"""Les conversations : au comptoir et en ville, générées par le LLM (ou le script).

Cycle de vie d'une conversation :

    demandée ──(réponse du LLM)──▶ répliques programmées ──▶ terminée
       │  bulle « … » au-dessus         une bulle par réplique     effet sur la
       │  de celui qui parle            espacées selon leur        relation, souvenir
       ▼                                longueur                   de l'échange
    abandonnée (le vendeur quitte son poste, trop longue attente → repli sur le script)

La réponse du LLM arrive de façon ASYNCHRONE (dans un autre fil), mais elle
n'est appliquée au monde QUE pendant un tick, ici, dans `update()` : le monde
reste modifié à un seul endroit, comme le prévoit l'architecture.

Rencontres en ville : à chaque minute simulée, deux habitants proches, dans
la rue ou dans un lieu de détente (parc, café, salle de sport), peuvent
s'arrêter pour discuter. La probabilité dépend de leur sociabilité et de leur
relation ; un délai empêche les mêmes de bavarder toutes les cinq minutes.
Personne ne s'arrête s'il a une envie pressante ou s'il est en train de servir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from pixelcity.agents.tasks import Phase, TaskKind
from pixelcity.llm.backends import DialogueBackend, Pending, ScriptedBackend
from pixelcity.llm.types import ConversationKind, ConversationRequest, ConversationResult, Persona
from pixelcity.memory.stream import MemoryKind
from pixelcity.sim.appointments import MEET_PLACES, Appointment, parse_hour
from pixelcity.sim.events import EventKind
from pixelcity.sim.minds import MISSED_AFFINITY, memory_lines, remember, stamp
from pixelcity.sim.types import MINUTES_PER_DAY, Anim, Facing, NeedKind, PlaceKind, Pose

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext

THINKING = "…"
# Rythme des bulles : le temps de lire (en minutes simulées).
LINE_BASE_MINUTES = 0.7
LINE_MINUTES_PER_CHAR = 1 / 45
# Au-delà, on n'attend plus le LLM : on passe au script (en minutes simulées).
MAX_WAIT_MINUTES = 20.0
# Rencontres en ville.
STREET_RANGE = 2  # cases
STREET_PAIR_COOLDOWN_MINUTES = 6 * 60
STREET_AGENT_COOLDOWN_MINUTES = 45
STREET_SOCIAL_PLACES = {PlaceKind.PARK, PlaceKind.CAFE, PlaceKind.GYM}
MAX_PENDING_STREET = 1  # le GPU ne génère qu'une chose à la fois : pas de file interminable
FLIRT_MIN_AFFINITY = 20.0
MEET_MIN_AFFINITY = 10.0  # on ne donne rendez-vous qu'à quelqu'un qu'on apprécie un peu
RECALL_COUNT = 3
ADULT = 18

NEED_PHRASES = {
    NeedKind.HUNGER: "j'ai faim",
    NeedKind.ENERGY: "je suis épuisé",
    NeedKind.HYGIENE: "il faut que je prenne une douche",
    NeedKind.BLADDER: "il faut que je trouve des toilettes",
    NeedKind.FUN: "j'ai besoin de me changer les idées",
}
NEED_THRESHOLD = 35.0


@dataclass(slots=True)
class Spoken:
    tick: int
    speaker: str
    listener: str
    text: str
    minutes: float


@dataclass(slots=True, eq=False)
class Conversation:
    uid: int
    kind: ConversationKind
    a: str
    b: str
    place_id: str | None
    started_tick: int
    request: ConversationRequest
    pending: Pending[ConversationResult] | None
    lines: list[Spoken] = field(default_factory=list)
    result: ConversationResult | None = None
    ends_tick: int | None = None
    finished: bool = False

    @property
    def waiting(self) -> bool:
        return self.result is None

    def other(self, agent_id: str) -> str:
        return self.b if agent_id == self.a else self.a


class Conversations:
    def __init__(self, backend: DialogueBackend, script: ScriptedBackend) -> None:
        self.backend = backend
        self.script = script
        self.active: dict[int, Conversation] = {}
        self._next_uid = 1
        self._pair_cooldown: dict[tuple[str, str], int] = {}
        self._agent_cooldown: dict[str, int] = {}
        self.counts = {kind: 0 for kind in ConversationKind}
        self.by_source: dict[str, int] = {}

    def status(self) -> str:
        return self.backend.status()

    # ------------------------------------------------------------------ #
    # Démarrer
    # ------------------------------------------------------------------ #
    def start(
        self,
        ctx: SimContext,
        kind: ConversationKind,
        a: Agent,
        b: Agent,
        *,
        item: str | None = None,
        in_stock: bool = True,
        occasion: str | None = None,
        appointment: Appointment | None = None,
    ) -> Conversation:
        relation = ctx.relations.get(a.id, b.id)
        if relation is None or relation.familiarity == 0:
            relation_text = "ils ne se connaissent pas encore"
        else:
            relation_text = f"{relation.stage} ({relation.familiarity} rencontres)"
            if relation.flirts:
                relation_text += f", ils ont déjà flirté {relation.flirts} fois"
        place = ctx.world.places.get(a.place_id) if a.place_id else None
        place_name = place.name if place is not None else "la rue"
        affinity = relation.affinity if relation is not None else 0.0
        meet_places: tuple[tuple[str, str], ...] = ()
        if (
            appointment is None
            and affinity >= MEET_MIN_AFFINITY
            and ctx.appointments.between(a.id, b.id) is None
        ):
            meet_places = tuple(
                (p.id, p.name) for p in ctx.world.places.values() if p.kind in MEET_PLACES
            )
        request = ConversationRequest(
            kind=kind,
            a=persona(a),
            b=persona(b),
            place=place.name if place is not None else "dans la rue",
            hour=_hhmm(ctx),
            relation=relation_text,
            memory=relation.summary if relation is not None else None,
            flirt_allowed=flirt_allowed(a, b, relation.affinity if relation else 0.0),
            item=item,
            in_stock=in_stock,
            seed=ctx.rngs.stream("conversation").randrange(1 << 30),
            memories_a=_recall(ctx, a, b, place_name),
            memories_b=_recall(ctx, b, a, place_name),
            meet_places=meet_places,
            affinity=affinity,
            occasion=occasion,
        )
        conv = Conversation(
            uid=self._next_uid,
            kind=kind,
            a=a.id,
            b=b.id,
            place_id=a.place_id,
            started_tick=ctx.clock.tick,
            request=request,
            pending=self.backend.submit(request),
        )
        self._next_uid += 1
        self.active[conv.uid] = conv
        self.counts[kind] += 1
        if kind is ConversationKind.STREET:
            for agent, other in ((a, b), (b, a)):
                agent.conversation = conv.uid
                agent.facing = _facing_towards(agent, other)
                agent.anim = Anim.TALK
        ctx.emit(EventKind.CHAT_STARTED, a.id, a.place_id, other=b.id, mode=kind.value)
        self._poll(conv, ctx)
        if conv.waiting:
            ctx.emit(EventKind.CHAT_THINKING, a.id, a.place_id, other=b.id)
        return conv

    # ------------------------------------------------------------------ #
    # Faire avancer
    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        for conv in list(self.active.values()):
            self._poll(conv, ctx)
        if ctx.clock.tick % ctx.clock.ticks_per_minute == 0:
            self._appointments(ctx)
            self._street_encounters(ctx)

    def _poll(self, conv: Conversation, ctx: SimContext) -> None:
        if conv.finished:
            return
        now = ctx.clock.tick
        if conv.result is None:
            pending = conv.pending
            waited = (now - conv.started_tick) / ctx.clock.ticks_per_minute
            if pending is not None and pending.done():
                self._schedule(conv, pending.result(), ctx)
            elif waited >= MAX_WAIT_MINUTES:
                # Le LLM traîne (ou la simulation va très vite) : on n'immobilise
                # pas les habitants indéfiniment. Aux vitesses x10 et x30, la
                # plupart des répliques seront donc scriptées.
                if pending is not None:
                    pending.cancel()
                self._schedule(conv, self.script.generate(conv.request), ctx)
            else:
                return
        while conv.lines and conv.lines[0].tick <= now:
            line = conv.lines.pop(0)
            _say(ctx, line)
        if not conv.lines and conv.ends_tick is not None and now >= conv.ends_tick:
            self._finish(conv, ctx)

    def _schedule(self, conv: Conversation, result: ConversationResult, ctx: SimContext) -> None:
        conv.result = result
        conv.pending = None
        self.by_source[result.source] = self.by_source.get(result.source, 0) + 1
        per_minute = ctx.clock.ticks_per_minute
        tick = ctx.clock.tick
        for line in result.lines:
            minutes = LINE_BASE_MINUTES + len(line.text) * LINE_MINUTES_PER_CHAR
            listener = conv.other(line.speaker)
            conv.lines.append(Spoken(tick, line.speaker, listener, line.text, minutes))
            tick += max(1, round(minutes * per_minute))
        conv.ends_tick = tick

    def _finish(self, conv: Conversation, ctx: SimContext) -> None:
        conv.finished = True
        self.active.pop(conv.uid, None)
        a, b = ctx.agents.get(conv.a), ctx.agents.get(conv.b)
        for agent in (a, b):
            if agent is not None and agent.conversation == conv.uid:
                agent.conversation = None
                agent.anim = Anim.IDLE
        if a is None or b is None or conv.result is None:
            return
        result = conv.result
        tick = ctx.clock.tick
        relation, before, after = ctx.relations.meet(
            a.profile,
            b.profile,
            tick,
            ctx.rngs.stream("relations"),
            delta=result.affinity_delta,
        )
        if result.summary:
            relation.summary = result.summary
        self._remember(ctx, conv, a, b, result)
        if result.flirt:
            relation.flirts += 1
            ctx.emit(EventKind.FLIRT, a.id, conv.place_id, other=b.id)
        if before != after:
            ctx.emit(
                EventKind.RELATION, a.id, conv.place_id, other=b.id, stage=after, before=before
            )
        key = ctx.relations.key(a.id, b.id)
        self._pair_cooldown[key] = tick
        self._agent_cooldown[a.id] = self._agent_cooldown[b.id] = tick
        ctx.emit(
            EventKind.CHAT_DONE,
            a.id,
            conv.place_id,
            other=b.id,
            mode=conv.kind.value,
            source=result.source,
            delta=round(result.affinity_delta, 1) if result.affinity_delta is not None else None,
        )

    def _remember(
        self, ctx: SimContext, conv: Conversation, a: Agent, b: Agent, result: ConversationResult
    ) -> None:
        """Chacun garde un souvenir de l'échange ; un rendez-vous éventuel est inscrit."""
        place_name = _place_name(ctx, conv.place_id)
        gist = result.summary or "des banalités"
        delta = abs(result.affinity_delta or 0.0)
        importance = 3 + round(delta / 2) + (3 if result.flirt else 0)
        for me, them in ((a, b), (b, a)):
            text = f"J'ai discuté avec {them.first_name} ({place_name}) : {gist}"
            if result.flirt:
                text += " Il y avait un petit quelque chose entre nous."
            remember(
                ctx,
                me,
                MemoryKind.CONVERSATION,
                text,
                importance,
                about=(them.id,),
                place_id=conv.place_id,
            )
        if result.meet is not None:
            self._book(ctx, a, b, result.meet.place_id, result.meet.hour)

    def _book(self, ctx: SimContext, a: Agent, b: Agent, place_id: str, hour: str | None) -> None:
        place = ctx.world.places.get(place_id)
        if place is None:
            return
        day = ctx.clock.day_index + 1
        start = ctx.appointments.feasible_start(a.profile, b.profile, place, day, parse_hour(hour))
        if start is None:
            for me, them in ((a, b), (b, a)):
                remember(
                    ctx,
                    me,
                    MemoryKind.OBSERVATION,
                    f"{them.first_name} et moi voulions nous revoir demain, mais aucun "
                    "horaire ne nous allait",
                    3,
                    about=(them.id,),
                )
            return
        appointment = ctx.appointments.add(a.profile, b.profile, place_id, day, start)
        when = stamp(ctx, day * MINUTES_PER_DAY + start)
        for me, them in ((a, b), (b, a)):
            remember(
                ctx,
                me,
                MemoryKind.PLAN,
                f"Rendez-vous avec {them.first_name} {when}, {place.name}",
                5,
                about=(them.id,),
                place_id=place_id,
            )
        ctx.emit(
            EventKind.APPOINTMENT_SET, a.id, place_id, other=b.id, when=when, uid=appointment.uid
        )

    def _appointments(self, ctx: SimContext) -> None:
        """Rendez-vous du moment : on se retrouve, ou l'on constate une absence."""
        now = ctx.now
        for appointment in ctx.appointments.active(now):
            if appointment.kept:
                continue
            a, b = ctx.agents.get(appointment.a), ctx.agents.get(appointment.b)
            if a is None or b is None:
                continue
            here = [ag for ag in (a, b) if ag.place_id == appointment.place_id]
            if len(here) < 2 or any(not _can_meet(ag) for ag in here):
                continue
            appointment.kept = True
            appointment.closed = True
            place_name = _place_name(ctx, appointment.place_id)
            for me, them in ((a, b), (b, a)):
                remember(
                    ctx,
                    me,
                    MemoryKind.OBSERVATION,
                    f"{them.first_name} est bien venu à notre rendez-vous ({place_name})",
                    6,
                    about=(them.id,),
                    place_id=appointment.place_id,
                )
            ctx.emit(EventKind.APPOINTMENT_KEPT, a.id, appointment.place_id, other=b.id)
            self.start(
                ctx,
                ConversationKind.STREET,
                a,
                b,
                occasion=f"ils s'étaient donné rendez-vous ici, à {place_name}",
                appointment=appointment,
            )
        for appointment in ctx.appointments.overdue(now):
            appointment.closed = True
            a, b = ctx.agents.get(appointment.a), ctx.agents.get(appointment.b)
            if a is None or b is None:
                continue
            for me, them in ((a, b), (b, a)):
                remember(
                    ctx,
                    me,
                    MemoryKind.OBSERVATION,
                    f"Le rendez-vous avec {them.first_name} n'a pas eu lieu : "
                    f"{them.first_name} n'est pas venu, ou c'est moi qui ai manqué",
                    5,
                    about=(them.id,),
                    place_id=appointment.place_id,
                )
            relation = ctx.relations.get(a.id, b.id)
            if relation is not None:
                relation.affinity = max(-100.0, relation.affinity + MISSED_AFFINITY)
            ctx.emit(EventKind.APPOINTMENT_MISSED, a.id, appointment.place_id, other=b.id)

    def cancel(self, conv: Conversation, ctx: SimContext) -> None:
        """Conversation interrompue (le vendeur quitte son poste) : sans effet sur la relation."""
        if conv.pending is not None:
            conv.pending.cancel()
        conv.finished = True
        self.active.pop(conv.uid, None)
        for agent_id in (conv.a, conv.b):
            agent = ctx.agents.get(agent_id)
            if agent is not None and agent.conversation == conv.uid:
                agent.conversation = None
                agent.anim = Anim.IDLE

    # ------------------------------------------------------------------ #
    # Rencontres en ville
    # ------------------------------------------------------------------ #
    def _street_encounters(self, ctx: SimContext) -> None:
        if not self.backend.blocking:
            busy = sum(
                1 for c in self.active.values() if c.kind is ConversationKind.STREET and c.waiting
            )
            if busy >= MAX_PENDING_STREET:
                return
        now = ctx.clock.tick
        per_minute = ctx.clock.ticks_per_minute
        free = [agent for agent in ctx.agents.values() if _available(agent, ctx, self, now)]
        rng = ctx.rngs.stream("street")
        for a, b in combinations(free, 2):
            if a.conversation is not None or b.conversation is not None:
                continue
            if a.place_id != b.place_id:
                continue
            if max(abs(a.tile[0] - b.tile[0]), abs(a.tile[1] - b.tile[1])) > STREET_RANGE:
                continue
            key = ctx.relations.key(a.id, b.id)
            last = self._pair_cooldown.get(key)
            if last is not None and now - last < STREET_PAIR_COOLDOWN_MINUTES * per_minute:
                continue
            relation = ctx.relations.get(a.id, b.id)
            sociability = (
                a.profile.personality.extraversion + b.profile.personality.extraversion
            ) / 2
            chance = 0.12 + 0.3 * sociability
            if relation is None:
                chance *= 0.5  # on aborde moins facilement un inconnu
            elif relation.affinity >= FLIRT_MIN_AFFINITY:
                chance += 0.15
            elif relation.affinity < -20:
                chance *= 0.2
            if rng.random() < chance:
                # Celui qui engage la conversation : le plus extraverti.
                first, second = sorted(
                    (a, b), key=lambda ag: (-ag.profile.personality.extraversion, ag.id)
                )
                self.start(ctx, ConversationKind.STREET, first, second)
                if not self.backend.blocking:
                    return


def _can_meet(agent: Agent) -> bool:
    """Libre pour discuter : pas déjà en conversation, ni dans une file, ni pressé."""
    if agent.conversation is not None or agent.pose in (Pose.LIE, Pose.HIDDEN):
        return False
    if any(task.kind in (TaskKind.URGENT, TaskKind.SERVE) for task in agent.tasks):
        return False
    task = agent.task
    return task is None or task.phase in (Phase.PERFORM, Phase.SEEK, Phase.GOTO, Phase.TRAVEL)


def _recall(ctx: SimContext, me: Agent, them: Agent, place_name: str) -> tuple[str, ...]:
    """Les souvenirs qui reviennent à `me` en voyant `them` à cet endroit."""
    memories = me.memory.retrieve(
        ctx.clock.tick,
        query=f"{them.name} {place_name} {me.status_text()}",
        about=(them.id,),
        place_id=me.place_id,
        count=RECALL_COUNT,
    )
    return memory_lines(ctx, memories)


def _place_name(ctx: SimContext, place_id: str | None) -> str:
    if place_id is None:
        return "dans la rue"
    place = ctx.world.places.get(place_id)
    return place.name if place is not None else place_id


def _available(agent: Agent, ctx: SimContext, convs: Conversations, now: int) -> bool:
    if agent.conversation is not None or agent.pose in (Pose.LIE, Pose.HIDDEN):
        return False
    last = convs._agent_cooldown.get(agent.id)
    if last is not None and now - last < STREET_AGENT_COOLDOWN_MINUTES * ctx.clock.ticks_per_minute:
        return False
    if any(task.kind in (TaskKind.URGENT, TaskKind.SERVE) for task in agent.tasks):
        return False
    if agent.place_id is not None:
        place = ctx.world.places.get(agent.place_id)
        if place is None or place.kind not in STREET_SOCIAL_PLACES:
            return False
        if agent.place_id == agent.work_place_id:
            return False  # au travail, on ne papote pas avec les clients hors comptoir
    return True


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
def flirt_allowed(a: Agent, b: Agent, affinity: float) -> bool:
    pa, pb = a.profile, b.profile
    if pa.age < ADULT or pb.age < ADULT:
        return False
    if not (pa.romance and pb.romance):
        return False
    if pa.partner not in (None, pb.id) or pb.partner not in (None, pa.id):
        return False
    return affinity >= FLIRT_MIN_AFFINITY


def _traits(agent: Agent) -> str:
    p = agent.profile.personality
    words = [
        "curieux" if p.openness > 0.6 else "attaché à ses habitudes" if p.openness < 0.4 else "",
        "organisé"
        if p.conscientiousness > 0.7
        else "un peu désordonné"
        if p.conscientiousness < 0.35
        else "",
        "bavard" if p.extraversion > 0.6 else "réservé" if p.extraversion < 0.4 else "",
        "chaleureux"
        if p.agreeableness > 0.6
        else "franc, parfois sec"
        if p.agreeableness < 0.4
        else "",
        "anxieux" if p.neuroticism > 0.6 else "calme" if p.neuroticism < 0.35 else "",
    ]
    return ", ".join(word for word in words if word) or "ordinaire"


def persona(agent: Agent) -> Persona:
    need_kind = min(NeedKind, key=lambda kind: agent.needs[kind])
    need = NEED_PHRASES[need_kind] if agent.needs[need_kind] < NEED_THRESHOLD else None
    profile = agent.profile
    return Persona(
        id=agent.id,
        name=profile.name,
        age=profile.age,
        job=profile.job,
        traits=_traits(agent),
        values=profile.values,
        speech_style=profile.speech_style,
        ideology=profile.ideology,
        doing=agent.status_text(),
        need=need,
        model=profile.llm_model,
    )


def _hhmm(ctx: SimContext) -> str:
    minutes = ctx.clock.total_minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _facing_towards(agent: Agent, other: Agent) -> Facing:
    dx = other.pos[0] - agent.pos[0]
    dy = other.pos[1] - agent.pos[1]
    if abs(dx) >= abs(dy):
        return Facing.RIGHT if dx > 0 else Facing.LEFT
    return Facing.DOWN if dy > 0 else Facing.UP


def _say(ctx: SimContext, line: Spoken) -> None:
    from pixelcity.agents.agent import Speech

    speaker = ctx.agents.get(line.speaker)
    if speaker is None:
        return
    until = ctx.clock.tick + max(1, round(line.minutes * ctx.clock.ticks_per_minute))
    speaker.speech = Speech(line.text, until, line.listener)
    ctx.emit(EventKind.SAY, line.speaker, speaker.place_id, text=line.text, to=line.listener)
