"""Étape 3 : conversations (LLM ou script), relations, flirt et réglages .env."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pixelcity.config.loader import GameConfig
from pixelcity.llm.backends import OllamaBackend, ScriptedBackend
from pixelcity.llm.prompts import MAX_LINE_CHARS, build_user_prompt, parse_result
from pixelcity.llm.settings import LlmSettings, load_llm_settings, parse_env
from pixelcity.llm.types import ConversationKind, ConversationRequest, Persona
from pixelcity.sim.conversation import flirt_allowed
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation

from .helpers import events_of, run_to

MONDAY = 0


def _persona(pid: str, name: str, age: int = 30) -> Persona:
    return Persona(
        pid, name, age, "Testeur", "bavard", (), "", "", "se promène", "ça va", None, None
    )


def _request(**changes: Any) -> ConversationRequest:
    base: dict[str, Any] = {
        "kind": ConversationKind.COUNTER,
        "a": _persona("lea", "Léa Martin"),
        "b": _persona("marcel", "Marcel Dupont"),
        "place": "Boulangerie",
        "hour": "07:30",
        "relation": "ils ne se connaissent pas encore",
        "memory": None,
        "flirt_allowed": False,
        "item": "bread",
        "in_stock": True,
    }
    base.update(changes)
    return ConversationRequest(**base)


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #
def test_parse_env_ignore_commentaires_et_guillemets() -> None:
    values = parse_env('# commentaire\nOLLAMA_MODEL="mistral"  # fin\nexport PIXELCITY_LLM=off\n\n')
    assert values == {"OLLAMA_MODEL": "mistral", "PIXELCITY_LLM": "off"}


def test_l_environnement_l_emporte_sur_le_fichier(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OLLAMA_MODEL=fichier\nPIXELCITY_LLM=off\n", encoding="utf-8")
    settings = load_llm_settings({"OLLAMA_MODEL": "variable"}, [env_file])
    assert settings.model == "variable" and not settings.enabled
    assert settings.source == str(env_file)
    assert load_llm_settings({}, [tmp_path / "absent"]).enabled  # Ollama par défaut


# --------------------------------------------------------------------------- #
# Prompt et validation : le LLM propose, la simulation dispose
# --------------------------------------------------------------------------- #
def test_le_prompt_annonce_la_rupture_de_stock() -> None:
    assert "RUPTURE" in build_user_prompt(_request(in_stock=False))
    assert "Pas de flirt" in build_user_prompt(_request())


def test_la_reponse_est_nettoyee_et_bornee() -> None:
    data = {
        "lines": [
            {"speaker": "lea", "text": "  Bonjour   !  "},
            {"speaker": "Marcel", "text": "x " * 200},  # prénom au lieu de l'id, trop long
            {"speaker": "inconnu", "text": "intrus"},
            {"speaker": "lea", "text": ""},
        ],
        "affinity_delta": 50,
        "flirt": True,
        "summary": "Léa achète du pain.",
    }
    result = parse_result(_request(), data, "test")
    assert [line.speaker for line in result.lines] == ["lea", "marcel"]
    assert result.lines[0].text == "Bonjour !"
    assert len(result.lines[1].text) <= MAX_LINE_CHARS
    assert result.affinity_delta == 6.0  # borné
    assert result.flirt is False  # non autorisé par la simulation


def test_une_conversation_a_une_seule_voix_est_refusee() -> None:
    data = {"lines": [{"speaker": "lea", "text": "a"}, {"speaker": "lea", "text": "b"}]}
    with pytest.raises(ValueError):
        parse_result(_request(), data, "test")


def test_le_flirt_exige_deux_adultes_disponibles(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea, hugo, paul = sim.agents["lea"], sim.agents["hugo"], sim.agents["paul"]
    assert flirt_allowed(lea, hugo, 30.0)
    assert not flirt_allowed(lea, hugo, 0.0)  # pas encore d'affinité
    assert not flirt_allowed(lea, paul, 80.0)  # Paul n'est pas ouvert à la romance
    hugo.profile = hugo.profile.model_copy(update={"age": 16})
    assert not flirt_allowed(lea, hugo, 80.0)  # jamais avec un mineur
    hugo.profile = hugo.profile.model_copy(update={"age": 24, "partner": "sofia"})
    assert not flirt_allowed(lea, hugo, 80.0)  # déjà en couple


# --------------------------------------------------------------------------- #
# Dans la simulation
# --------------------------------------------------------------------------- #
def test_le_service_au_comptoir_passe_par_une_conversation(
    make_sim: Callable[..., Simulation],
) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 13.0)
    chats = [e for e in events_of(sim, EventKind.CHAT_DONE) if e.data.get("mode") == "counter"]
    assert chats
    first = chats[0]
    relation = sim.relations.get(str(first.agent_id), str(first.data["other"]))
    assert relation is not None and relation.familiarity >= 1


def test_des_habitants_discutent_en_ville_puis_repartent(
    make_sim: Callable[..., Simulation],
) -> None:
    sim = make_sim()
    sim.run_days(3)
    street = [e for e in events_of(sim, EventKind.CHAT_DONE) if e.data.get("mode") == "street"]
    assert street, "aucune rencontre en ville en trois jours"
    started = [e for e in events_of(sim, EventKind.CHAT_STARTED) if e.data.get("mode") == "street"]
    assert len(started) - len(street) <= 1  # au plus une en cours
    # Personne ne reste bloqué en conversation.
    stuck = [a.id for a in sim.agents.values() if a.conversation is not None]
    assert len(stuck) <= 2


def test_le_script_est_reproductible(config: GameConfig) -> None:
    def says(seed: int) -> list[str]:
        sim = Simulation(config, seed=seed)
        sim.run_days(1)
        return [str(e.data["text"]) for e in events_of(sim, EventKind.SAY)]

    assert says(7) == says(7)


# --------------------------------------------------------------------------- #
# Ollama : un faux serveur local, pour tester le vrai chemin HTTP sans GPU
# --------------------------------------------------------------------------- #
class _FakeOllama(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *args: object) -> None:  # silence
        pass

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"models": [{"name": "fake:latest"}]})

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        _FakeOllama.requests.append(request)
        prompt = request["messages"][1]["content"]
        ids = [part.split("»")[0] for part in prompt.split("(id « ")[1:]]
        reply = {
            "lines": [
                {"speaker": ids[0], "text": "Bonjour, généré par le faux LLM !"},
                {"speaker": ids[1], "text": "Ravi de vous voir."},
            ],
            "affinity_delta": 4,
            "flirt": False,
            "summary": "Un échange cordial.",
        }
        self._send({"message": {"role": "assistant", "content": json.dumps(reply)}})


@pytest.fixture
def fake_ollama() -> Iterator[str]:
    _FakeOllama.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_les_repliques_viennent_d_ollama(config: GameConfig, fake_ollama: str) -> None:
    settings = LlmSettings(host=fake_ollama, model="fake", timeout_s=5)
    backend = OllamaBackend(settings, ScriptedBackend(config.dialogues), blocking=True)
    sim = Simulation(config, dialogue=backend)
    try:
        run_to(sim, MONDAY, 13.0)
    finally:
        sim.close()
    texts = [e.data["text"] for e in events_of(sim, EventKind.SAY)]
    assert "Bonjour, généré par le faux LLM !" in texts
    assert _FakeOllama.requests[0]["format"]["required"]  # sortie JSON contrainte
    assert backend.generated >= 1 and "fake" in backend.status()
    pair = next(r for _, r in sim.relations.of("marcel") if r.summary)
    assert pair.summary == "Un échange cordial."


def test_sans_ollama_on_repasse_au_script(config: GameConfig) -> None:
    settings = LlmSettings(host="http://127.0.0.1:9", model="fake", timeout_s=2)
    backend = OllamaBackend(settings, ScriptedBackend(config.dialogues), blocking=True)
    sim = Simulation(config, dialogue=backend)
    try:
        run_to(sim, MONDAY, 13.0)
    finally:
        sim.close()
    assert "injoignable" in backend.status()
    assert events_of(sim, EventKind.SAY)  # les habitants parlent quand même
