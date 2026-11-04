"""Couche routine : exécute le plan de chaque agent, à chaque tick, SANS LLM.

C'est la couche « réflexe » de l'architecture à deux étages :
- ici, tout est déterministe et bon marché : besoins, déplacements A*,
  respect des horaires, réactions aux imprévus simples ;
- la couche « cognitive » (LLM, étape 2) ne fera qu'ÉCRIRE des plans, à des
  moments choisis. Elle ne sera jamais appelée à chaque tick.

Déroulé d'un tick pour un agent :
1. s'assurer qu'il a un plan pour aujourd'hui ;
2. faire évoluer ses besoins selon ce qu'il fait ;
3. vérifier les urgences (faim, fatigue, hygiène critiques) ;
4. choisir sa cible : dérogation en cours, sinon bloc du plan (avec départ
   anticipé si le bloc suivant est un engagement à l'heure) ;
5. avancer dans la machine à états pour atteindre cette cible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from pixelcity.agents.agent import Agent, AgentState, Override
from pixelcity.agents.needs import REMEDIES
from pixelcity.agents.planner import Planner, PlanningContext
from pixelcity.config.schemas import Settings
from pixelcity.sim.clock import SimClock
from pixelcity.sim.events import Event, EventKind, EventLog, EventValue
from pixelcity.sim.rng import RngRegistry
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType, NeedKind, Weekday
from pixelcity.world.place import Access, Place
from pixelcity.world.world import World

ANTICIPATION_MARGIN = 5  # minutes d'avance pour un engagement à l'heure
ANTICIPATION_HORIZON = 180  # au-delà, inutile d'estimer le trajet
MAX_WAIT_MINUTES = 30  # attente maximale devant un lieu fermé
URGENT_MAX_MINUTES = 4 * 60  # une urgence ne dure jamais plus longtemps
PATH_RETRY_MINUTES = 30  # délai avant de réessayer un chemin introuvable
SPOT_STAY_MINUTES = (15, 40)  # durée sur place avant de changer d'endroit (parc)

URGENT_LABELS: dict[NeedKind, str] = {
    NeedKind.HUNGER: "fringale : va manger",
    NeedKind.ENERGY: "épuisement : va se reposer",
    NeedKind.HYGIENE: "besoin urgent de se laver",
}


@dataclass(frozen=True, slots=True)
class Target:
    activity: ActivityType
    place_id: str
    label: str


@dataclass(slots=True)
class RoutineContext:
    world: World
    clock: SimClock
    settings: Settings
    events: EventLog
    planner: Planner
    rngs: RngRegistry
    walk_tiles_per_tick: float
    hours_per_tick: float
    minutes_per_tick: float

    @classmethod
    def create(
        cls,
        world: World,
        clock: SimClock,
        settings: Settings,
        events: EventLog,
        planner: Planner,
        rngs: RngRegistry,
    ) -> RoutineContext:
        minutes_per_tick = clock.tick_seconds / 60
        return cls(
            world=world,
            clock=clock,
            settings=settings,
            events=events,
            planner=planner,
            rngs=rngs,
            walk_tiles_per_tick=settings.walk_speed_tiles_per_minute * minutes_per_tick,
            hours_per_tick=clock.hours_per_tick,
            minutes_per_tick=minutes_per_tick,
        )

    def emit(
        self, kind: EventKind, agent: Agent, place_id: str | None = None, **data: EventValue
    ) -> None:
        self.events.emit(Event(self.clock.tick, kind, agent.id, place_id, data))


# --------------------------------------------------------------------------- #
# Point d'entrée : un tick pour un agent
# --------------------------------------------------------------------------- #
def update_agent(agent: Agent, ctx: RoutineContext) -> None:
    now = ctx.clock.total_minutes
    agent.prev_pos = agent.pos
    _ensure_plan(agent, ctx, now)
    _apply_needs(agent, ctx)
    _update_override(agent, ctx, now)
    target = _choose_target(agent, ctx, now)
    _pursue(agent, target, ctx, now)


# --------------------------------------------------------------------------- #
# 1. Plan
# --------------------------------------------------------------------------- #
def _ensure_plan(agent: Agent, ctx: RoutineContext, now: int) -> None:
    day = ctx.clock.day_index
    if agent.plan is None or agent.plan.day_index != day:
        planning = PlanningContext(
            world=ctx.world,
            weekday=Weekday.from_index(day),
            rng=ctx.rngs.stream(f"planner:{agent.id}"),
        )
        agent.plan = ctx.planner.plan_day(agent, day, planning)
        agent.block_index = 0
        ctx.emit(EventKind.PLAN_CREATED, agent, blocks=len(agent.plan.blocks))
    # Les blocs sont triés : on avance l'index au lieu de chercher à chaque tick.
    blocks = agent.plan.blocks
    while agent.block_index < len(blocks) - 1 and blocks[agent.block_index].end <= now:
        agent.block_index += 1


# --------------------------------------------------------------------------- #
# 2. Besoins
# --------------------------------------------------------------------------- #
def _apply_needs(agent: Agent, ctx: RoutineContext) -> None:
    effects: Mapping[NeedKind, float] = {}
    stat_key = "idle"
    if agent.state is AgentState.ACTIVE and agent.activity is not None and agent.place_id:
        effects = ctx.world.places[agent.place_id].effects.get(agent.activity, {})
        stat_key = agent.activity.value
    elif agent.state is AgentState.WALKING:
        effects = ctx.settings.walking_effects
        stat_key = "walk"
    agent.needs.update(ctx.settings.needs, effects, ctx.hours_per_tick)
    stats = agent.minutes_by_activity
    stats[stat_key] = stats.get(stat_key, 0.0) + ctx.minutes_per_tick


# --------------------------------------------------------------------------- #
# 3. Urgences et dérogations
# --------------------------------------------------------------------------- #
def _update_override(agent: Agent, ctx: RoutineContext, now: int) -> None:
    specs = ctx.settings.needs
    override = agent.override
    if override is not None:
        if override.need is not None:
            recovered = agent.needs.is_satisfied(override.need, specs)
            if recovered or now - override.started >= URGENT_MAX_MINUTES:
                agent.override = None
                ctx.emit(
                    EventKind.NEED_RECOVERED,
                    agent,
                    need=override.need.value,
                    value=round(agent.needs[override.need]),
                )
        elif override.until is not None and now >= override.until:
            agent.override = None
        return

    for need in agent.needs.critical_needs(specs):
        remedy = REMEDIES.get(need)
        if remedy is None:
            continue
        block = agent.current_block()
        doing_it = agent.state is AgentState.ACTIVE and agent.activity is remedy
        if doing_it or (block is not None and block.activity is remedy):
            continue  # déjà en train d'y remédier, ou le plan s'en charge
        if need is NeedKind.HYGIENE and agent.activity is ActivityType.SLEEP:
            continue  # on ne se réveille pas pour une douche : ça attendra le matin
        place = _find_place_for(agent, remedy, ctx)
        if place is None:
            continue
        agent.override = Override(remedy, place.id, URGENT_LABELS[need], started=now, need=need)
        ctx.emit(
            EventKind.NEED_CRITICAL,
            agent,
            place.id,
            need=need.value,
            value=round(agent.needs[need]),
        )
        return


def _find_place_for(
    agent: Agent, activity: ActivityType, ctx: RoutineContext, exclude: str | None = None
) -> Place | None:
    """Le lieu accessible MAINTENANT le plus proche (en pas) qui propose `activity`."""
    clock = ctx.clock
    weekday, minute = clock.weekday.number, clock.minute_of_day
    best: Place | None = None
    best_length = 1 << 30
    for place in ctx.world.places.values():
        if place.id == exclude:
            continue
        access = place.check_access(
            activity,
            weekday,
            minute,
            resident=agent.profile.home == place.id,
            staff=agent.work_place_id == place.id,
            entering=agent.place_id != place.id,
        )
        if access is not Access.OK:
            continue
        length = 0 if agent.place_id == place.id else ctx.world.path_length_to(agent.tile, place)
        if length is not None and length < best_length:
            best, best_length = place, length
    return best


# --------------------------------------------------------------------------- #
# 4. Choix de la cible
# --------------------------------------------------------------------------- #
def _choose_target(agent: Agent, ctx: RoutineContext, now: int) -> Target:
    if agent.override is not None:
        o = agent.override
        return Target(o.activity, o.place_id, o.label)
    block = agent.current_block()
    assert block is not None  # garanti par _ensure_plan
    upcoming = agent.next_block()
    if upcoming is not None and upcoming.punctual and upcoming.place_id != block.place_id:
        heading_there = agent.state is AgentState.WALKING and agent.destination == upcoming.place_id
        if heading_there:
            return Target(upcoming.activity, upcoming.place_id, upcoming.label)
        if upcoming.start - now <= ANTICIPATION_HORIZON:
            travel = _travel_minutes(agent, ctx.world.places[upcoming.place_id], ctx)
            if travel is not None and now >= upcoming.start - travel - ANTICIPATION_MARGIN:
                return Target(upcoming.activity, upcoming.place_id, upcoming.label)
    return Target(block.activity, block.place_id, block.label)


def _travel_minutes(agent: Agent, place: Place, ctx: RoutineContext) -> float | None:
    if agent.place_id == place.id:
        return 0.0
    length = ctx.world.path_length_to(agent.tile, place)
    if length is None:
        return None
    return length / ctx.settings.walk_speed_tiles_per_minute


# --------------------------------------------------------------------------- #
# 5. Machine à états
# --------------------------------------------------------------------------- #
def _pursue(agent: Agent, target: Target, ctx: RoutineContext, now: int) -> None:
    place = ctx.world.places[target.place_id]

    # a) Déjà dans le bon lieu.
    if agent.place_id == place.id:
        access = _access(agent, place, target.activity, ctx, entering=False)
        if access is not Access.OK:
            _handle_refusal(agent, target, place, access, ctx, now)
            return
        if (
            agent.state is not AgentState.ACTIVE
            or agent.activity is not target.activity
            or agent.activity_label != target.label
        ):
            _start_activity(agent, target, ctx)
        if place.outdoor:
            _stroll(agent, place, ctx, now)
        return

    # b) En route vers ce lieu.
    if agent.state is AgentState.WALKING and agent.destination == place.id:
        if _advance_along_path(agent, ctx):
            _arrive(agent, target, place, ctx, now)
        return

    # c) Devant ce lieu, en attente de l'ouverture.
    if agent.state is AgentState.WAITING and agent.destination == place.id:
        if _access(agent, place, target.activity, ctx, entering=True) is Access.OK:
            _enter(agent, target, place, ctx)
        elif (
            now - (agent.wait_started if agent.wait_started is not None else now)
            >= MAX_WAIT_MINUTES
        ):
            _handle_refusal(agent, target, place, Access.CLOSED, ctx, now)
        return

    # d) Il faut partir.
    if now >= agent.retry_minute:
        _depart(agent, target, place, ctx, now)


def _access(
    agent: Agent, place: Place, activity: ActivityType, ctx: RoutineContext, *, entering: bool
) -> Access:
    clock = ctx.clock
    return place.check_access(
        activity,
        clock.weekday.number,
        clock.minute_of_day,
        resident=agent.profile.home == place.id,
        staff=agent.work_place_id == place.id,
        entering=entering,
    )


def _depart(agent: Agent, target: Target, place: Place, ctx: RoutineContext, now: int) -> None:
    path = ctx.world.pathfinder.find_path(agent.tile, place.nearest_entrance(agent.tile))
    if path is None:
        ctx.emit(EventKind.PATH_NOT_FOUND, agent, place.id)
        agent.state = AgentState.IDLE
        agent.retry_minute = now + PATH_RETRY_MINUTES
        return
    from_place = agent.place_id
    _leave_current_place(agent, ctx)
    agent.path, agent.path_index, agent.progress = path, 0, 0.0
    agent.state = AgentState.WALKING
    agent.destination = place.id
    agent.activity = None
    agent.activity_label = target.label
    agent.wait_started = None
    ctx.emit(
        EventKind.DEPARTED,
        agent,
        place.id,
        origin=from_place,
        activity=target.activity.value,
        label=target.label,
    )
    if _advance_along_path(agent, ctx):
        _arrive(agent, target, place, ctx, now)


def _leave_current_place(agent: Agent, ctx: RoutineContext) -> None:
    if agent.place_id is not None:
        ctx.world.places[agent.place_id].occupants.pop(agent.id, None)
        agent.place_id = None


def _advance_along_path(agent: Agent, ctx: RoutineContext) -> bool:
    """Avance l'agent le long de son chemin. Renvoie True s'il est arrivé au bout.

    La vitesse est fixe en tuiles par tick : comme le tick a une durée fixe,
    l'agent parcourt exactement la même distance à x1 qu'à x10.
    """
    path = agent.path
    last = len(path) - 1
    index, progress = agent.path_index, agent.progress
    remaining = ctx.walk_tiles_per_tick
    while remaining > 0 and index < last:
        step = 1.0 - progress
        if remaining >= step:
            index += 1
            progress = 0.0
            remaining -= step
        else:
            progress += remaining
            remaining = 0.0
    agent.path_index, agent.progress = index, progress
    cx, cy = path[index]
    agent.tile = (cx, cy)
    if index < last:
        nx, ny = path[index + 1]
        agent.pos = (cx + (nx - cx) * progress, cy + (ny - cy) * progress)
        agent.facing = (nx - cx, ny - cy)
        return False
    agent.pos = (float(cx), float(cy))
    return True


def _arrive(agent: Agent, target: Target, place: Place, ctx: RoutineContext, now: int) -> None:
    access = _access(agent, place, target.activity, ctx, entering=True)
    if access is Access.OK:
        _enter(agent, target, place, ctx)
        return
    if access is Access.CLOSED and _opens_soon(place, now):
        agent.state = AgentState.WAITING
        agent.wait_started = now
        ctx.emit(EventKind.PLACE_CLOSED, agent, place.id, reason="closed", waiting=True)
        return
    _handle_refusal(agent, target, place, access, ctx, now)


def _opens_soon(place: Place, now: int) -> bool:
    later = now + MAX_WAIT_MINUTES
    day, minute = divmod(later, MINUTES_PER_DAY)
    return place.hours.is_open(day % 7, minute)


def _enter(agent: Agent, target: Target, place: Place, ctx: RoutineContext) -> None:
    place.occupants[agent.id] = None
    agent.place_id = place.id
    agent.destination = None
    agent.wait_started = None
    agent.next_spot_minute = 0
    ctx.emit(EventKind.ARRIVED, agent, place.id)
    _start_activity(agent, target, ctx)


def _start_activity(agent: Agent, target: Target, ctx: RoutineContext) -> None:
    agent.state = AgentState.ACTIVE
    agent.activity = target.activity
    agent.activity_label = target.label
    agent.path, agent.path_index, agent.progress = (), 0, 0.0
    ctx.emit(
        EventKind.ACTIVITY_STARTED,
        agent,
        agent.place_id,
        activity=target.activity.value,
        label=target.label,
    )


def _stroll(agent: Agent, place: Place, ctx: RoutineContext, now: int) -> None:
    """Dans un lieu extérieur, l'agent flâne d'un endroit à l'autre."""
    if agent.path and agent.path_index < len(agent.path) - 1:
        _advance_along_path(agent, ctx)
        return
    if now < agent.next_spot_minute:
        return
    rng = ctx.rngs.stream(f"stroll:{agent.id}")
    spot = rng.choice(place.spots)
    path = ctx.world.pathfinder.find_path(agent.tile, spot)
    if path is not None:
        agent.path, agent.path_index, agent.progress = path, 0, 0.0
    agent.next_spot_minute = now + rng.randint(*SPOT_STAY_MINUTES)


def _handle_refusal(
    agent: Agent, target: Target, place: Place, access: Access, ctx: RoutineContext, now: int
) -> None:
    """Le lieu visé refuse l'agent (fermé, complet...) : on se replie ailleurs."""
    ctx.emit(EventKind.PLACE_CLOSED, agent, place.id, reason=access.value, waiting=False)
    if agent.state is AgentState.WAITING:
        agent.state = AgentState.IDLE
    alternative = _find_place_for(agent, target.activity, ctx, exclude=place.id)
    current = agent.override
    if current is not None and current.need is not None:
        # Urgence : même besoin, autre lieu (le logement convient toujours).
        fallback_place = alternative.id if alternative else agent.profile.home
        agent.override = replace(current, place_id=fallback_place)
        return
    until = _target_block_end(agent, target, now)
    if alternative is not None:
        agent.override = Override(target.activity, alternative.id, target.label, now, until=until)
    else:
        agent.override = Override(
            ActivityType.RELAX, agent.profile.home, "rentre à la maison", now, until=until
        )


def _target_block_end(agent: Agent, target: Target, now: int) -> int:
    for block in (agent.current_block(), agent.next_block()):
        if block is not None and block.place_id == target.place_id and block.end > now:
            return block.end
    return now + 60
