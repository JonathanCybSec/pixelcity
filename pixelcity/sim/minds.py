"""Ce que les habitants retiennent : souvenirs, réflexions nocturnes, rendez-vous.

Les souvenirs s'écrivent à la PREMIÈRE personne (« J'ai discuté avec Léa ») :
ils sont recopiés tels quels dans les prompts du LLM, sous « ce que Léa a en
tête ». Écrire comme pense le personnage évite au modèle de confondre qui a
vécu quoi.

Les observations viennent du journal des événements (patron Observateur :
on s'abonne à `EventLog`, sans toucher au code qui émet). Les conversations
et les rendez-vous sont notés directement par `conversation.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pixelcity.llm.backends import DialogueBackend, Pending
from pixelcity.llm.types import ReflectionRequest, ReflectionResult
from pixelcity.memory.stream import Memory, MemoryKind
from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.types import MINUTES_PER_DAY, Weekday

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext

REFLECTION_THRESHOLD = 18  # importance cumulée avant de « repenser à tout ça »
REFLECTION_MEMORIES = 15
MISSED_AFFINITY = -4.0

NEED_TEXT = {
    "hunger": "J'ai eu une grosse fringale",
    "energy": "J'étais épuisé",
    "hygiene": "Je me sentais sale",
    "bladder": "J'ai eu une envie pressante",
}


def stamp(ctx: SimContext, minute: int | None = None) -> str:
    total = ctx.clock.total_minutes if minute is None else minute
    day = Weekday.from_index(total // MINUTES_PER_DAY).label
    m = total % MINUTES_PER_DAY
    return f"{day} {m // 60:02d}:{m % 60:02d}"


def remember(
    ctx: SimContext,
    agent: Agent,
    kind: MemoryKind,
    text: str,
    importance: int,
    *,
    about: tuple[str, ...] = (),
    place_id: str | None = None,
) -> Memory:
    memory = agent.memory.add(
        ctx.clock.tick, kind, text, importance, about=about, place_id=place_id
    )
    if kind is MemoryKind.REFLECTION:
        ctx.emit(EventKind.REFLECTION, agent.id, place_id, text=text)
    return memory


def memory_lines(ctx: SimContext, memories: list[Memory]) -> tuple[str, ...]:
    """Pour un prompt : « lundi 12:41 — J'ai discuté avec Marcel... »."""
    per_minute = ctx.clock.ticks_per_minute
    return tuple(f"{stamp(ctx, m.tick // per_minute)} — {m.text}" for m in memories)


class Minds:
    def __init__(self, backend: DialogueBackend) -> None:
        self.backend = backend
        self._pending: dict[str, Pending[ReflectionResult]] = {}
        self.reflections = 0

    # ------------------------------------------------------------------ #
    # Observations tirées du journal
    # ------------------------------------------------------------------ #
    def on_event(self, ctx: SimContext, event: Event) -> None:
        agent = ctx.agents.get(event.agent_id or "")
        if agent is None:
            return
        data = event.data
        place_name = _place_name(ctx, event.place_id)
        match event.kind:
            case EventKind.RELATION:
                other = ctx.agents.get(str(data.get("other")))
                if other is None or not data.get("before"):
                    return
                stage = str(data.get("stage"))
                for me, them in ((agent, other), (other, agent)):
                    remember(
                        ctx,
                        me,
                        MemoryKind.OBSERVATION,
                        f"{them.first_name} et moi : notre relation est passée à « {stage} »",
                        6,
                        about=(them.id,),
                        place_id=event.place_id,
                    )
            case EventKind.SERVICE_DONE if data.get("reason") == "money":
                remember(
                    ctx,
                    agent,
                    MemoryKind.OBSERVATION,
                    f"Je n'avais pas assez d'argent pour payer à {place_name}, c'était gênant",
                    5,
                    place_id=event.place_id,
                )
            case EventKind.SERVICE_DONE if data.get("ok") is False:
                remember(
                    ctx,
                    agent,
                    MemoryKind.OBSERVATION,
                    f"Je suis reparti de {place_name} les mains vides",
                    3,
                    place_id=event.place_id,
                )
            case EventKind.STOCK_EMPTY:
                remember(
                    ctx,
                    agent,
                    MemoryKind.OBSERVATION,
                    f"Plus rien en stock à {place_name}, il a fallu décevoir des clients",
                    3,
                    place_id=event.place_id,
                )
            case EventKind.NEED_CRITICAL:
                text = NEED_TEXT.get(str(data.get("need")))
                if text is not None:
                    remember(ctx, agent, MemoryKind.OBSERVATION, text, 2, place_id=event.place_id)
            case _:
                return

    # ------------------------------------------------------------------ #
    # Réflexion, chaque nuit
    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        if ctx.clock.is_start_of_day:
            for agent in ctx.agents.values():
                stream = agent.memory
                if (
                    agent.id in self._pending
                    or stream.importance_since_reflection < REFLECTION_THRESHOLD
                ):
                    continue
                recent = sorted(
                    stream.since(stream.last_reflection_tick),
                    key=lambda m: (-m.importance, -m.uid),
                )[:REFLECTION_MEMORIES]
                recent.sort(key=lambda m: m.uid)
                from pixelcity.sim.conversation import persona
                from pixelcity.sim.economy import Economy

                request = ReflectionRequest(
                    persona(agent, Economy.situation(agent, ctx)),
                    memory_lines(ctx, recent),
                    seed=ctx.rngs.stream("reflection").randrange(1 << 30),
                )
                stream.importance_since_reflection = 0
                stream.last_reflection_tick = ctx.clock.tick
                self._pending[agent.id] = self.backend.submit_reflection(request)
        for agent_id, pending in list(self._pending.items()):
            if not pending.done():
                continue
            del self._pending[agent_id]
            agent = ctx.agents[agent_id]
            insights = pending.result().insights or self.rule_insights(ctx, agent)
            known = {m.text for m in agent.memory.memories if m.kind is MemoryKind.REFLECTION}
            for text in insights:
                if text in known:
                    continue
                about = tuple(
                    other.id
                    for other in ctx.agents.values()
                    if other is not agent and other.first_name in text
                )
                remember(ctx, agent, MemoryKind.REFLECTION, text, 7, about=about)
                self.reflections += 1

    def rule_insights(self, ctx: SimContext, agent: Agent) -> tuple[str, ...]:
        """Sans LLM : quelques pensées tirées de règles simples (relations, déboires)."""
        insights: list[str] = []
        recent = agent.memory.since(max(0, ctx.clock.tick - ctx.clock.ticks_per_day))
        people = {who for m in recent for who in m.about}
        for other_id in sorted(people):
            other = ctx.agents.get(other_id)
            relation = ctx.relations.get(agent.id, other_id)
            if other is None or relation is None:
                continue
            if relation.flirts and relation.affinity >= 40:
                insights.append(f"Je crois que {other.first_name} me plaît vraiment.")
            elif relation.affinity >= 45:
                insights.append(f"Je me sens proche de {other.first_name}, ça compte pour moi.")
            elif relation.affinity >= 20:
                insights.append(f"J'aime bien discuter avec {other.first_name}.")
            elif relation.affinity <= -20:
                insights.append(f"{other.first_name} m'agace un peu, je préfère l'éviter.")
        talks: dict[str, int] = {}
        for m in recent:
            if m.kind is MemoryKind.CONVERSATION:
                for who in m.about:
                    talks[who] = talks.get(who, 0) + 1
        if talks and not insights:
            best = max(sorted(talks), key=lambda who: talks[who])
            if talks[best] >= 2 and best in ctx.agents:
                insights.append(f"Je croise souvent {ctx.agents[best].first_name} ces temps-ci.")
        if sum(1 for m in recent if "fringale" in m.text) >= 2:
            insights.append("Je devrais mieux organiser mes repas.")
        if any("n'est pas venu" in m.text for m in recent):
            insights.append("Je n'aime pas qu'on me pose un lapin.")
        empty = [m for m in recent if "mains vides" in m.text]
        if len(empty) >= 2 and empty[-1].place_id is not None:
            name = _place_name(ctx, empty[-1].place_id)
            insights.append(f"À {name}, il vaut mieux venir tôt : c'est souvent vide.")
        return tuple(insights[:3])


def _place_name(ctx: SimContext, place_id: str | None) -> str:
    if place_id is None:
        return "la rue"
    place = ctx.world.places.get(place_id)
    return place.name if place is not None else place_id
