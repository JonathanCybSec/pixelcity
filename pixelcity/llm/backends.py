"""Les générateurs de conversations : le script (instantané) et Ollama (en arrière-plan).

Le piège n°1 d'un jeu qui appelle un LLM : faire l'appel DANS la boucle de
jeu. Une réponse prend 1 à 10 secondes ; pendant ce temps la fenêtre gèle
(« Ne répond pas »). On envoie donc la requête à un fil de travail
(`ThreadPoolExecutor`) et la simulation vient VÉRIFIER à chaque tick si la
réponse est arrivée (« polling ») : c'est le principe du ticket au
restaurant, on ne reste pas planté devant la cuisine.

Un seul fil de travail : sur une machine personnelle, le GPU traite de toute
façon une génération à la fois ; en envoyer dix en parallèle ne ferait que
les ralentir toutes.
"""

from __future__ import annotations

import random
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from pixelcity.config.schemas import DialoguesConfig
from pixelcity.llm.client import LlmError, OllamaClient
from pixelcity.llm.prompts import (
    REFLECTION_SCHEMA,
    REFLECTION_SYSTEM,
    SYSTEM,
    build_reflection_prompt,
    build_user_prompt,
    parse_reflection,
    parse_result,
    schema_for,
)
from pixelcity.llm.settings import LlmSettings
from pixelcity.llm.types import (
    ChatLine,
    ConversationKind,
    ConversationRequest,
    ConversationResult,
    MeetProposal,
    ReflectionRequest,
    ReflectionResult,
)


class Pending[T](Protocol):
    """Une réponse à venir (le « ticket » du restaurant). Générique : conversation ou réflexion."""

    def done(self) -> bool: ...
    def result(self) -> T: ...
    def cancel(self) -> None: ...


class DialogueBackend(Protocol):
    blocking: bool  # True : la simulation attend la réponse (mode headless)

    def submit(self, request: ConversationRequest) -> Pending[ConversationResult]: ...
    def submit_reflection(self, request: ReflectionRequest) -> Pending[ReflectionResult]: ...
    def status(self) -> str: ...
    def close(self) -> None: ...


class _Ready[T]:
    def __init__(self, result: T) -> None:
        self._result = result

    def done(self) -> bool:
        return True

    def result(self) -> T:
        return self._result

    def cancel(self) -> None:
        pass


class ScriptedBackend:
    """Répliques tirées de dialogues.yaml : instantané, gratuit et reproductible."""

    blocking = True

    def __init__(self, dialogues: DialoguesConfig, reason: str = "") -> None:
        self.dialogues = dialogues
        self.reason = reason

    def status(self) -> str:
        return "répliques scriptées" + (f" ({self.reason})" if self.reason else "")

    def close(self) -> None:
        pass

    def submit(self, request: ConversationRequest) -> Pending[ConversationResult]:
        return _Ready(self.generate(request))

    def submit_reflection(self, request: ReflectionRequest) -> Pending[ReflectionResult]:
        # Pas de LLM : la simulation tirera ses réflexions de règles simples.
        return _Ready(ReflectionResult(()))

    def generate(self, req: ConversationRequest) -> ConversationResult:
        rng = random.Random(req.seed)
        d = self.dialogues
        a, b = req.a.id, req.b.id
        if req.kind is ConversationKind.COUNTER:
            item = req.item or ""
            texts = [
                (a, f"{rng.choice(d.greet)} {rng.choice(d.order.get(item, ('Bonjour !',)))}"),
                (
                    b,
                    rng.choice(d.serve.get(item, ("Voilà !",)))
                    if req.in_stock
                    else rng.choice(d.out_of_stock),
                ),
                (a, rng.choice(d.thanks if req.in_stock else d.disappointed)),
                (b, rng.choice(d.goodbye)),
            ]
        else:
            street = d.street
            texts = [(a, rng.choice(street.opener)), (b, rng.choice(street.reply))]
            need = req.a.need or req.b.need
            if need is not None:
                who = a if req.a.need else b
                texts.append((who, rng.choice(street.need).format(need=need)))
            meet = None
            if req.meet_places and req.affinity >= 10 and rng.random() < 0.4:
                place_id, place_name = rng.choice(req.meet_places)
                hour = rng.choice(("15:00", "16:30", "17:30"))
                texts.append(
                    (a, f"On se retrouve demain vers {hour.replace(':', 'h')}, {place_name} ?")
                )
                texts.append((b, "Avec plaisir, à demain !"))
                meet = MeetProposal(place_id, hour)
            texts.append((b if texts[-1][0] == a else a, rng.choice(street.closer)))
            return ConversationResult(tuple(ChatLine(s, t) for s, t in texts), None, meet=meet)
        return ConversationResult(tuple(ChatLine(s, t) for s, t in texts), None)


class _LlmPending[T]:
    def __init__(self, future: Future[T]) -> None:
        self._future = future

    def done(self) -> bool:
        return self._future.done()

    def result(self) -> T:
        return self._future.result()

    def cancel(self) -> None:
        # Libère le GPU si la génération n'a pas encore commencé.
        self._future.cancel()


class OllamaBackend:
    """Conversations générées par Ollama ; repli automatique sur le script en cas d'échec."""

    blocking = False

    def __init__(
        self,
        settings: LlmSettings,
        fallback: ScriptedBackend,
        client: OllamaClient | None = None,
        *,
        blocking: bool = False,
    ) -> None:
        self.settings = settings
        self.fallback = fallback
        self.client = client or OllamaClient(settings.host, settings.timeout_s)
        self.blocking = blocking
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._lock = threading.Lock()
        self._state = "connexion à Ollama…"
        self._available: set[str] | None = None
        self.generated = 0
        self.failures = 0
        self._probe = self._pool.submit(self._check)

    # --- État (lu par l'interface, écrit par le fil de travail : d'où le verrou) ----
    def _set_state(self, text: str) -> None:
        with self._lock:
            self._state = text

    def status(self) -> str:
        with self._lock:
            return self._state

    def _check(self) -> None:
        try:
            models = self.client.models()
        except LlmError:
            self._set_state(f"Ollama injoignable ({self.settings.host}) : répliques scriptées")
            self._available = set()
            return
        self._available = {m for m in models} | {m.removesuffix(":latest") for m in models}
        if self.settings.model not in self._available:
            self._set_state(
                f"modèle {self.settings.model} absent (ollama pull {self.settings.model})"
            )
        else:
            self._set_state(f"IA locale : {self.settings.model}")

    def _model_for(self, req: ConversationRequest) -> str | None:
        available = self._available or set()
        for wanted in (req.a.model, self.settings.model):
            if wanted and wanted in available:
                return wanted
        return None

    def _generate(self, req: ConversationRequest) -> ConversationResult:
        model = self._model_for(req)
        if model is None:
            return self.fallback.generate(req)
        try:
            data = self.client.chat_json(
                model, SYSTEM, build_user_prompt(req), schema_for(req), seed=req.seed
            )
            result = parse_result(req, data, model)
        except (LlmError, ValueError) as exc:
            self.failures += 1
            if isinstance(exc, LlmError):
                self._set_state(f"erreur Ollama, repli sur le script : {exc}"[:120])
            return self.fallback.generate(req)
        self.generated += 1
        self._set_state(f"IA locale : {model}")
        return result

    def submit(self, request: ConversationRequest) -> Pending[ConversationResult]:
        # Le test de connexion passe en premier dans la file : la requête l'attend.
        pending = _LlmPending(self._pool.submit(self._generate, request))
        if self.blocking:
            pending.result()
        return pending

    def _reflect(self, req: ReflectionRequest) -> ReflectionResult:
        available = self._available or set()
        model = next(
            (m for m in (req.persona.model, self.settings.model) if m and m in available), None
        )
        if model is None:
            return ReflectionResult(())
        try:
            data = self.client.chat_json(
                model,
                REFLECTION_SYSTEM,
                build_reflection_prompt(req),
                REFLECTION_SCHEMA,
                temperature=0.6,
                seed=req.seed,
            )
            return ReflectionResult(parse_reflection(data), model)
        except (LlmError, ValueError):
            self.failures += 1
            return ReflectionResult(())

    def submit_reflection(self, request: ReflectionRequest) -> Pending[ReflectionResult]:
        pending = _LlmPending(self._pool.submit(self._reflect, request))
        if self.blocking:
            pending.result()
        return pending

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def make_backend(
    settings: LlmSettings, dialogues: DialoguesConfig, *, blocking: bool = False
) -> DialogueBackend:
    script = ScriptedBackend(dialogues, "IA désactivée" if not settings.enabled else "")
    if not settings.enabled:
        return script
    return OllamaBackend(settings, script, blocking=blocking)
