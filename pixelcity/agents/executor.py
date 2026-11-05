"""L'exécuteur de tâches : fait avancer d'un tick la tâche au sommet de la pile.

C'est ici que les besoins deviennent des GESTES visibles : pour manger, on ne
« remplit » pas une jauge par magie, on va au frigo (s'il reste quelque
chose dedans), on prend les ingrédients, on allume la cuisinière, on
s'assoit à table. Chaque geste réserve un objet précis, prend du temps et
peut échouer (frigo vide, vitrine dévalisée, plus de chaise libre).

Lecture conseillée : `tasks.py` (les phases), puis `run_task` ci-dessous.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pixelcity.agents.movement import arrived, step_along, walk_to
from pixelcity.agents.tasks import Phase, Task, TaskKind
from pixelcity.config.schemas import StepModel
from pixelcity.sim.events import EventKind
from pixelcity.sim.service import ServiceDesk
from pixelcity.sim.types import MINUTES_PER_DAY, Anim, Facing, Pose
from pixelcity.world.furniture import Furniture, Spot
from pixelcity.world.pathfinding import manhattan
from pixelcity.world.place import Access, Place

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext

MAX_WAIT_OPEN_MINUTES = 30  # attente maximale devant une porte fermée
MAX_QUEUE_MINUTES = 15  # au-delà, le client renonce (personne au comptoir)
SERVE_LINGER_MINUTES = 2.0  # le vendeur reste un peu au comptoir après le dernier client
STROLL_PAUSE = (2.0, 7.0)  # pause entre deux points de promenade (minutes)
SPOT_CANDIDATES = 4  # au plus 4 calculs de chemin par recherche d'objet
UNTIL_END_FALLBACK = 60  # durée d'une étape `until_end` sans fin de bloc
MAX_BUS_WAIT_MINUTES = 30
MAX_SPOT_WAIT_MINUTES = 12  # toilettes occupées, plan de travail pris : on patiente un peu
MAX_PHASES_PER_TICK = 8  # garde-fou : plusieurs phases peuvent s'enchaîner dans un tick

_EAT_VERBS = frozenset({"eat", "drink"})


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def run_task(agent: Agent, task: Task, ctx: SimContext) -> None:
    """Un tick de `task`. Les transitions instantanées s'enchaînent dans le même tick.

    Exemple : arriver dans la cuisine → chercher la cuisinière → elle est
    juste à côté → commencer à cuisiner. Le déplacement, lui, consomme le tick.
    """
    for _ in range(MAX_PHASES_PER_TICK):
        if task.finished:
            return
        handler = _HANDLERS[task.phase]
        if not handler(agent, task, ctx):
            return


def start_task(agent: Agent, task: Task, ctx: SimContext) -> None:
    """Annonce une nouvelle tâche et la place en phase de départ."""
    task.phase = Phase.SEEK if agent.place_id == task.place_id else Phase.TRAVEL
    task.walk_goal = None
    if task.announced:
        return
    task.announced = True
    ctx.emit(
        EventKind.TASK_STARTED,
        agent.id,
        task.place_id,
        recipe=task.recipe_id,
        label=task.label,
        task_kind=task.kind.value,
    )


def suspend_task(agent: Agent, task: Task, ctx: SimContext) -> None:
    """La tâche passe sous une autre (envie pressante...) : on libère sans tout perdre.

    Une étape interrompue garde le temps qui lui restait. Un objet allumé le
    reste (le four continue de cuire pendant que le boulanger sert un client).
    """
    now = ctx.now_exact
    step = task.step
    if task.phase is Phase.PERFORM and step is not None and not step.until_end:
        task.remaining = max(0.5, task.step_ends - now)
    if task.phase in (Phase.PERFORM, Phase.GOTO):
        _release(agent, task, keep_switched=True)
        task.phase = Phase.SEEK
    elif task.phase is Phase.QUEUE:
        _leave_queue(agent, task, ctx)
        task.phase = Phase.SEEK
    task.walk_goal = None
    task.no_bus = False
    ctx.transit.drop(agent.id)
    agent.path, agent.path_index, agent.progress = (), 0, 0.0
    if agent.pose is not Pose.WALK:
        agent.pose = Pose.STAND
    agent.anim = Anim.IDLE


def cancel_task(agent: Agent, task: Task, ctx: SimContext) -> None:
    """La tâche est abandonnée (le bloc du plan est fini) : on libère tout."""
    _release(agent, task, keep_switched=False)
    if task.phase is Phase.QUEUE:
        _leave_queue(agent, task, ctx)
    if task.switched is not None:
        _switch_off(task)
    task.walk_goal = None
    ctx.transit.drop(agent.id)
    agent.anim = Anim.IDLE
    if agent.pose in (Pose.SIT, Pose.LIE, Pose.HIDDEN, Pose.RUN):
        agent.pose = Pose.STAND


def minutes_left(task: Task, now: float) -> float | None:
    """Temps restant estimé d'une tâche ; None si elle est sans fin (boucle, `until_end`)."""
    if task.recipe.loop:
        return None
    total = 0.0
    for index in range(task.step_index, len(task.recipe.steps)):
        step = task.recipe.steps[index]
        if step.until_end:
            return None
        if index == task.step_index and task.phase is Phase.PERFORM:
            total += max(0.0, task.step_ends - now)
        elif step.verb == "order":
            total += 5.0
        else:
            total += step.minutes or 0.0
    return total


def is_committed(task: Task) -> bool:
    """La tâche a vraiment commencé (on a pris un objet, on fait la queue...)."""
    return task.step_index > 0 or task.phase in (Phase.GOTO, Phase.PERFORM, Phase.QUEUE)


def drop_suspended(task: Task) -> None:
    """Oublie une tâche suspendue (son bloc est passé) : on éteint ce qu'elle avait allumé."""
    _switch_off(task)


def leave_place(agent: Agent, ctx: SimContext) -> str | None:
    place_id = agent.place_id
    if place_id is not None:
        ctx.world.places[place_id].occupants.pop(agent.id, None)
        agent.place_id = None
    return place_id


def enter_place(agent: Agent, place: Place, ctx: SimContext) -> None:
    place.occupants[agent.id] = None
    agent.place_id = place.id
    ctx.emit(EventKind.ARRIVED, agent.id, place.id)


def access_for(
    agent: Agent, place: Place, task: Task, ctx: SimContext, *, entering: bool
) -> Access:
    clock = ctx.clock
    return place.check_access(
        task.activity,
        clock.weekday.number,
        clock.minute_of_day,
        resident=agent.profile.home == place.id,
        staff=agent.work_place_id == place.id,
        entering=entering,
    )


def opens_soon(place: Place, now: int, within: int = MAX_WAIT_OPEN_MINUTES) -> bool:
    later = now + within
    day, minute = divmod(later, MINUTES_PER_DAY)
    return place.hours.is_open(day % 7, minute)


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #
def _travel(agent: Agent, task: Task, ctx: SimContext) -> bool:
    place = ctx.world.places[task.place_id]
    if agent.place_id == place.id:
        task.phase = Phase.SEEK
        task.walk_goal = None
        return True
    if not _ride(agent, task, ctx):
        return False
    if task.walk_goal is None:
        entrance = place.nearest_entrance(agent.tile)
        if not walk_to(agent, entrance, ctx.world.pathfinder):
            ctx.emit(EventKind.PATH_NOT_FOUND, agent.id, place.id)
            _fail(agent, task, ctx, "aucun chemin")
            return False
        task.walk_goal = entrance
        origin = leave_place(agent, ctx)
        if origin is not None or not task.departed:
            # Un trajet repris après une interruption en pleine rue n'est pas
            # un nouveau départ : on ne le raconte qu'une fois.
            task.departed = True
            ctx.emit(
                EventKind.DEPARTED,
                agent.id,
                place.id,
                origin=origin,
                label=task.label,
                recipe=task.recipe_id,
            )
        if not task.no_bus and agent.place_id is None:
            ride = ctx.transit.plan(
                agent,
                entrance,
                len(agent.path),
                ctx.config.settings.walk_speed_tiles_per_minute,
                agent.money,
            )
            task.no_bus = True  # une seule décision par trajet
            if ride is not None and walk_to(agent, ride.platform, ctx.world.pathfinder):
                ctx.transit.rides[agent.id] = ride
                task.walk_goal = None
                return False
    if not step_along(agent, ctx.walk_tiles_per_tick):
        return False
    task.walk_goal = None
    access = access_for(agent, place, task, ctx, entering=True)
    if access is Access.OK:
        enter_place(agent, place, ctx)
        task.phase = Phase.SEEK
        return True
    if access is Access.CLOSED and opens_soon(place, ctx.now):
        ctx.emit(EventKind.PLACE_CLOSED, agent.id, place.id, reason="closed", waiting=True)
        task.phase = Phase.WAIT_OPEN
        task.wait_started = ctx.now
        doorstep = place.doorstep(agent.tile)
        if doorstep is not None:
            walk_to(agent, doorstep, ctx.world.pathfinder)
        return False
    ctx.emit(EventKind.PLACE_CLOSED, agent.id, place.id, reason=access.value, waiting=False)
    _fail(agent, task, ctx, f"{place.name} : {_ACCESS_TEXT.get(access, access.value)}")
    return False


def _ride(agent: Agent, task: Task, ctx: SimContext) -> bool:
    """Le trajet en bus, s'il y en a un. True : on peut (re)prendre la marche normale."""
    ride = ctx.transit.ride_of(agent.id)
    if ride is None:
        return True
    if ride.state == "onboard":
        return False
    if ride.state == "to_stop":
        if step_along(agent, ctx.walk_tiles_per_tick):
            ride.state = "waiting"
            ride.since = ctx.now
            agent.facing = Facing.DOWN if ride.eastbound else Facing.UP
        return False
    if ride.state == "waiting":
        if ctx.now - ride.since < MAX_BUS_WAIT_MINUTES:
            return False
        ctx.transit.drop(agent.id)  # le bus ne vient pas : on y va à pied
    else:  # descendu : on finit à pied depuis l'arrêt
        ctx.transit.drop(agent.id)
    task.walk_goal = None
    task.no_bus = True
    return True


_ACCESS_TEXT = {Access.CLOSED: "fermé", Access.FULL: "complet", Access.FORBIDDEN: "interdit"}


def _wait_open(agent: Agent, task: Task, ctx: SimContext) -> bool:
    if not arrived(agent):
        step_along(agent, ctx.walk_tiles_per_tick)
        return False
    place = ctx.world.places[task.place_id]
    if access_for(agent, place, task, ctx, entering=True) is Access.OK:
        task.phase = Phase.TRAVEL
        task.walk_goal = None
        return True
    agent.facing = Facing.from_delta(
        place.entrances[0][0] - agent.tile[0], place.entrances[0][1] - agent.tile[1]
    )
    started = task.wait_started if task.wait_started is not None else ctx.now
    if ctx.now - started >= MAX_WAIT_OPEN_MINUTES:
        _fail(agent, task, ctx, f"{place.name} toujours fermé")
    return False


def _seek(agent: Agent, task: Task, ctx: SimContext) -> bool:
    step = task.step
    if step is None:
        if task.recipe.loop and task.ends_at is not None and ctx.now < task.ends_at:
            task.step_index = 0
            task.loops += 1
            return True
        task.phase = Phase.DONE
        ctx.emit(
            EventKind.TASK_DONE, agent.id, task.place_id, recipe=task.recipe_id, label=task.label
        )
        return False
    reason = _start_step(agent, task, step, ctx)
    if reason is None:
        task.seek_since = None
        return True
    if reason.startswith("rien de libre") and not step.optional:
        # Tout est pris (deux collègues, une seule toilette) : on attend son
        # tour au lieu d'abandonner et de réessayer en boucle.
        if task.seek_since is None:
            task.seek_since = ctx.now_exact
        if ctx.now_exact - task.seek_since < MAX_SPOT_WAIT_MINUTES:
            return False
    if step.optional:
        task.step_index += 1
        task.remaining = None
        return True
    _fail(agent, task, ctx, reason)
    return False


def _goto(agent: Agent, task: Task, ctx: SimContext) -> bool:
    if not step_along(agent, ctx.walk_tiles_per_tick):
        return False
    step = task.step
    assert step is not None
    _begin_perform(agent, task, step, task.spot, ctx)
    return True


def _perform(agent: Agent, task: Task, ctx: SimContext) -> bool:
    step = task.step
    assert step is not None
    now = ctx.now_exact
    if step.verb == "stroll":
        _stroll(agent, task, ctx)
    if task.kind is TaskKind.SERVE and task.desk_uid is not None:
        desk = ctx.desks[task.desk_uid]
        if desk.queue or desk.session is not None:
            task.step_ends = max(task.step_ends, now + SERVE_LINGER_MINUTES)
    if now < task.step_ends:
        return False
    _finish_step(agent, task, step, ctx)
    return True


def _queue(agent: Agent, task: Task, ctx: SimContext) -> bool:
    assert task.desk_uid is not None
    desk = ctx.desks[task.desk_uid]
    result = desk.results.pop(agent.id, None)
    step = task.step
    assert step is not None
    if result is not None:
        task.desk_uid = None
        if result:
            task.step_index += 1
            task.phase = Phase.SEEK
            return True
        if step.optional:
            task.step_index += 1
            task.phase = Phase.SEEK
            return True
        _fail(agent, task, ctx, "reparti les mains vides")
        return False
    index = desk.index_of(agent.id)
    if index is None:
        task.desk_uid = None
        task.phase = Phase.SEEK  # retiré de la file sans résultat : on recommence
        return True
    goal = desk.position_tile(index)
    if task.walk_goal != goal:
        task.walk_goal = goal
        walk_to(agent, goal, ctx.world.pathfinder)
    if not arrived(agent):
        step_along(agent, ctx.walk_tiles_per_tick)
        return False
    agent.pose = Pose.STAND
    agent.facing = Facing.UP
    started = task.wait_started if task.wait_started is not None else ctx.now
    if desk.session is None and ctx.now - started >= MAX_QUEUE_MINUTES:
        _leave_queue(agent, task, ctx)
        _fail(agent, task, ctx, "personne pour servir")
    return False


_HANDLERS = {
    Phase.TRAVEL: _travel,
    Phase.WAIT_OPEN: _wait_open,
    Phase.SEEK: _seek,
    Phase.GOTO: _goto,
    Phase.PERFORM: _perform,
    Phase.QUEUE: _queue,
}


# --------------------------------------------------------------------------- #
# Étapes : commencer, utiliser, finir
# --------------------------------------------------------------------------- #
def _start_step(agent: Agent, task: Task, step: StepModel, ctx: SimContext) -> str | None:
    """Lance l'étape. Renvoie None si c'est parti, sinon la raison de l'échec."""
    place = ctx.world.places[task.place_id]
    items = ctx.config.actions.items
    for item, quantity in step.consume.items():
        if not agent.carries(item, quantity):
            return f"n'a pas de {items[item].label}"
    if step.verb in ("wait", "stroll"):
        _begin_perform(agent, task, step, None, ctx)
        return None
    if step.verb == "order":
        if step.buy is not None and agent.carries(step.buy):
            # Déjà acheté (un service interrompu plus tôt) : inutile de refaire la queue.
            task.step_index += 1
            task.phase = Phase.SEEK
            return None
        return _join_queue(agent, task, step, place, ctx)
    spot, reason = _find_spot(agent, task, step, place, ctx)
    if spot is None:
        return reason
    spot.reserved_by = agent.id
    task.spot = spot
    if agent.tile == spot.tile:
        _begin_perform(agent, task, step, spot, ctx)
        return None
    if not walk_to(agent, spot.tile, ctx.world.pathfinder):
        spot.reserved_by = None
        task.spot = None
        return "aucun chemin jusqu'à l'objet"
    task.walk_goal = spot.tile
    task.phase = Phase.GOTO
    return None


def _find_spot(
    agent: Agent, task: Task, step: StepModel, place: Place, ctx: SimContext
) -> tuple[Spot | None, str]:
    """L'objet libre le plus proche qui propose le verbe de l'étape.

    On trie par distance « à vol d'oiseau » (Manhattan, gratuite) et on ne
    calcule le vrai chemin (A*, coûteux) que pour les quelques meilleurs.
    """
    candidates: list[Spot] = []
    empty: str | None = None
    for spot in place.spots_for(step.verb):
        if not spot.is_free_for(agent.id) or not _role_ok(spot, agent, place):
            continue
        furniture = spot.furniture
        if step.distinct and task.last_furniture == furniture.uid:
            continue
        if task.kind is TaskKind.SERVE and furniture.uid != task.desk_uid:
            continue
        needed = _still_needed(agent, step.take)
        if needed and not _has_stock(furniture, needed):
            empty = furniture.label
            continue
        if step.put and furniture.container is None:
            continue
        candidates.append(spot)
    if not candidates:
        if empty is not None:
            return None, f"{empty} vide"
        return None, f"rien de libre pour « {step.label} »"
    candidates.sort(key=lambda s: manhattan(agent.tile, s.tile))
    pathfinder = ctx.world.pathfinder
    for spot in candidates[:SPOT_CANDIDATES]:
        if spot.tile == agent.tile or pathfinder.find_path(agent.tile, spot.tile) is not None:
            return spot, ""
    return None, "objet inaccessible"


def _role_ok(spot: Spot, agent: Agent, place: Place) -> bool:
    match spot.role:
        case "staff":
            return agent.work_place_id == place.id
        case "customer":
            return agent.work_place_id != place.id
        case "resident":
            return agent.profile.home == place.id
        case _:
            return True


def _still_needed(agent: Agent, wanted: dict[str, int]) -> dict[str, int]:
    """Ce qu'il faut encore prendre : on ne ressort pas du frigo ce qu'on a déjà en main."""
    return {
        item: quantity - agent.inventory.get(item, 0)
        for item, quantity in wanted.items()
        if quantity > agent.inventory.get(item, 0)
    }


def _has_stock(furniture: Furniture, wanted: dict[str, int]) -> bool:
    container = furniture.container
    return container is not None and all(container.has(i, q) for i, q in wanted.items())


def _begin_perform(
    agent: Agent, task: Task, step: StepModel, spot: Spot | None, ctx: SimContext
) -> None:
    now = ctx.now_exact
    task.spot = spot
    agent.spot = spot
    agent.path, agent.path_index, agent.progress = (), 0, 0.0
    if spot is not None:
        agent.pose = Pose(spot.pose)
        agent.facing = spot.facing
        spot.furniture.users[agent.id] = None
        container = spot.furniture.container
        if step.take and container is not None:
            for item, quantity in _still_needed(agent, step.take).items():
                if container.take(item, quantity):
                    agent.give(item, quantity)
        if step.switch_on and task.switched is None:
            target = spot.granted_by.get(step.verb, spot.furniture)
            target.switched_on += 1
            task.switched = target
    else:
        agent.pose = Pose.STAND
    agent.anim = _anim_for(step, agent.pose)
    if task.remaining is not None:
        duration = task.remaining
    elif step.minutes is not None:
        duration = step.minutes
    else:
        end = task.ends_at if task.ends_at is not None else ctx.now + UNTIL_END_FALLBACK
        duration = max(1.0, end - now)
    task.remaining = None
    task.step_started = now
    task.step_ends = now + duration
    task.phase = Phase.PERFORM
    task.next_stroll = 0.0
    ctx.emit(
        EventKind.STEP_STARTED,
        agent.id,
        task.place_id,
        verb=step.verb,
        label=step.label,
        furniture=spot.furniture.type_id if spot is not None else None,
        minutes=round(duration, 1),
    )


def _anim_for(step: StepModel, pose: Pose) -> Anim:
    if step.anim is not None:
        return Anim(step.anim)
    if step.verb in _EAT_VERBS:
        return Anim.EAT
    if pose is Pose.SIT and step.verb.startswith("work"):
        return Anim.INTERACT
    return Anim.IDLE


def _finish_step(agent: Agent, task: Task, step: StepModel, ctx: SimContext) -> None:
    spot = task.spot
    items = ctx.config.actions.items
    if step.put and spot is not None and spot.furniture.container is not None:
        container = spot.furniture.container
        for item, quantity in step.put.items():
            if agent.remove(item, quantity):
                stored = items[item].stores_as or {item: 1}
                for stored_item, per_unit in stored.items():
                    container.put(stored_item, per_unit * quantity)
    for item, quantity in step.consume.items():
        agent.remove(item, quantity)
    for item, quantity in step.make.items():
        agent.give(item, quantity)
    if step.produce:
        place = ctx.world.places[task.place_id]
        for item, quantity in step.produce.items():
            stock = place.container_with(item)
            if stock is not None:
                stock.put(item, quantity)
    if step.verb == "stroll":
        agent.path, agent.path_index, agent.progress = (), 0, 0.0
        agent.pos = (float(agent.tile[0]), float(agent.tile[1]))
    task.last_furniture = spot.furniture.uid if spot is not None else None
    _release(agent, task, keep_switched=False)
    task.step_index += 1
    task.phase = Phase.SEEK
    agent.anim = Anim.IDLE
    if agent.pose is not Pose.WALK:
        agent.pose = Pose.STAND


def _release(agent: Agent, task: Task, *, keep_switched: bool) -> None:
    spot = task.spot
    if spot is not None:
        if spot.reserved_by == agent.id:
            spot.reserved_by = None
        spot.furniture.users.pop(agent.id, None)
    task.spot = None
    if agent.spot is spot:
        agent.spot = None
    if not keep_switched and task.switched is not None:
        _switch_off(task)


def _switch_off(task: Task) -> None:
    if task.switched is not None:
        task.switched.switched_on = max(0, task.switched.switched_on - 1)
        task.switched = None


def _fail(agent: Agent, task: Task, ctx: SimContext, reason: str) -> None:
    _release(agent, task, keep_switched=False)
    if task.phase is Phase.QUEUE:
        _leave_queue(agent, task, ctx)
    task.phase = Phase.FAILED
    task.failure = reason
    agent.anim = Anim.IDLE
    if agent.pose in (Pose.SIT, Pose.LIE, Pose.HIDDEN, Pose.RUN):
        agent.pose = Pose.STAND
    ctx.emit(
        EventKind.TASK_FAILED,
        agent.id,
        task.place_id,
        recipe=task.recipe_id,
        label=task.label,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# Comptoirs et promenade
# --------------------------------------------------------------------------- #
def _join_queue(
    agent: Agent, task: Task, step: StepModel, place: Place, ctx: SimContext
) -> str | None:
    item = step.buy
    desks = [desk for desk in ctx.desks_in(place.id) if item in desk.sells]
    if not desks:
        return f"rien ne vend de {item} ici"
    desk: ServiceDesk = min(desks, key=lambda d: len(d.queue))
    index = desk.join(agent.id)
    if index is None:
        return "trop de monde au comptoir"
    task.desk_uid = desk.uid
    task.wait_started = ctx.now
    task.walk_goal = None
    task.phase = Phase.QUEUE
    ctx.emit(EventKind.QUEUE_JOINED, agent.id, place.id, item=item, position=index)
    return None


def _leave_queue(agent: Agent, task: Task, ctx: SimContext) -> None:
    if task.desk_uid is not None and task.kind is not TaskKind.SERVE:
        desk = ctx.desks.get(task.desk_uid)
        if desk is not None:
            desk.leave(agent.id)
        task.desk_uid = None


def _stroll(agent: Agent, task: Task, ctx: SimContext) -> None:
    """Flâner : marcher vers un point au hasard, s'y arrêter un peu, repartir."""
    if not arrived(agent):
        step_along(agent, ctx.walk_tiles_per_tick)
        return
    now = ctx.now_exact
    rng = ctx.rngs.stream(f"stroll:{agent.id}")
    if task.next_stroll == 0.0:
        task.next_stroll = now + rng.uniform(*STROLL_PAUSE)
        agent.pose = Pose.STAND
        return
    if now < task.next_stroll:
        return
    place = ctx.world.places[task.place_id]
    if place.walk_tiles:
        walk_to(agent, rng.choice(place.walk_tiles), ctx.world.pathfinder)
    task.next_stroll = 0.0
