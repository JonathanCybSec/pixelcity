"""Couche routine : décide, à chaque tick, QUELLE tâche l'habitant exécute.

C'est la couche « réflexe » de l'architecture à deux étages :
- ici, tout est déterministe et bon marché : besoins, horaires, urgences,
  devoir de servir les clients ;
- la couche « cognitive » (LLM, étape 3) ne fera qu'ÉCRIRE des plans et des
  conversations, à des moments choisis. Elle ne sera jamais appelée à chaque tick.

Déroulé d'un tick pour un habitant :
1. s'assurer qu'il a un plan pour aujourd'hui ;
2. aligner la tâche du bas de la pile sur le bloc du plan (départ anticipé
   si le bloc suivant est un rendez-vous à l'heure, comme le travail) ;
3. faire évoluer ses besoins selon ce qu'il fait ;
4. empiler une urgence si un besoin devient critique ;
5. un commerçant à son poste file servir le client qui attend ;
6. exécuter la tâche du sommet (`executor.run_task`) ;
7. dépiler ce qui est fini ; remplacer une tâche de bloc finie trop tôt par
   un « bouche-trou » (regarder la télé, flâner) jusqu'à la fin du bloc.
"""

from __future__ import annotations

from collections.abc import Mapping

from pixelcity.agents.agent import Agent
from pixelcity.agents.executor import (
    cancel_task,
    drop_suspended,
    is_committed,
    minutes_left,
    run_task,
    start_task,
    suspend_task,
)
from pixelcity.agents.plan import PlanBlock
from pixelcity.agents.planner import Planner, PlanningContext
from pixelcity.agents.tasks import Phase, Task, TaskKind
from pixelcity.sim.context import SimContext
from pixelcity.sim.events import EventKind
from pixelcity.sim.service import server_of
from pixelcity.sim.types import ActivityType, Anim, NeedKind, PlaceKind, Pose, Weekday
from pixelcity.world.place import Access, Place

ANTICIPATION_HORIZON = 180  # au-delà, inutile d'estimer le trajet
DEPARTURE_MARGIN = 5
URGENT_RETRY_MINUTES = 20  # si aucune solution, on réessaie plus tard
# Avant de partir, on passe aux toilettes si la vessie commence à tirer :
# sinon on fait demi-tour cinq minutes plus tard (vu dans le journal !).
BEFORE_LEAVING_BLADDER = 35.0
FINISH_STEP_FIRST_MINUTES = 8.0  # on finit son assiette avant d'aller aux toilettes
MIN_FILLER_MINUTES = 15  # en dessous, on passe directement au bloc suivant
MAX_FALLBACKS_PER_BLOCK = 4
NAP_MINUTES = 90
# Une tâche entamée (on a commandé son plat, rempli son panier) peut déborder
# sur le bloc suivant plutôt que d'être abandonnée à mi-chemin.
MAX_OVERRUN_MINUTES = 30
LATE_TOLERANCE_MINUTES = 10  # retard toléré sur un rendez-vous à l'heure (le travail)

URGENT_LABELS: dict[NeedKind, str] = {
    NeedKind.HUNGER: "fringale",
    NeedKind.ENERGY: "coup de fatigue",
    NeedKind.HYGIENE: "besoin de se laver",
    NeedKind.BLADDER: "envie pressante",
}
FOOD_RECIPES: dict[PlaceKind, str] = {
    PlaceKind.BAKERY: "bakery_lunch",
    PlaceKind.CAFE: "cafe_lunch",
}
# Ce qu'on peut manger tel quel, si on l'a sur soi : article → recette.
CARRIED_FOOD: dict[str, str] = {
    "bread": "eat_bread",
    "meal": "eat_meal",
    "lunchbox": "lunchbox_lunch",
}


def update_agent(agent: Agent, ctx: SimContext, planner: Planner) -> None:
    agent.prev_pos = agent.pos
    _ensure_plan(agent, ctx, planner)
    _sync_block_task(agent, ctx)
    _apply_needs(agent, ctx)
    _check_urgent_needs(agent, ctx)
    _check_service_duty(agent, ctx)

    task = agent.task
    place_before = agent.place_id
    if agent.conversation is not None:
        # En pleine discussion : on reste sur place. Les besoins continuent de
        # baisser, et une envie pressante attendra la fin de l'échange (court).
        agent.anim = Anim.TALK
        task = None
    if task is not None:
        run_task(agent, task, ctx)
    if agent.place_id is not None and agent.place_id != place_before:
        _on_enter(agent, ctx)
    _pop_finished(agent, ctx)
    if agent.speech is not None and ctx.clock.tick >= agent.speech.until_tick:
        agent.speech = None


# --------------------------------------------------------------------------- #
# 1. Plan
# --------------------------------------------------------------------------- #
def _ensure_plan(agent: Agent, ctx: SimContext, planner: Planner) -> None:
    day = ctx.clock.day_index
    if agent.plan is None or agent.plan.day_index != day:
        planning = PlanningContext(
            world=ctx.world,
            actions=ctx.config.actions,
            weekday=Weekday.from_index(day),
            rng=ctx.rngs.stream(f"planner:{agent.id}"),
            walk_speed=ctx.config.settings.walk_speed_tiles_per_minute,
            appointments=tuple(ctx.appointments.for_agent(agent.id, day)),
        )
        agent.plan = planner.plan_day(agent, day, planning)
        agent.block_index = 0
        ctx.emit(EventKind.PLAN_CREATED, agent.id, blocks=len(agent.plan.blocks))
    # Les blocs sont triés : on avance l'index au lieu de chercher à chaque tick.
    blocks = agent.plan.blocks
    now = ctx.now
    while agent.block_index < len(blocks) - 1 and blocks[agent.block_index].end <= now:
        agent.block_index += 1


# --------------------------------------------------------------------------- #
# 2. Tâche du bloc
# --------------------------------------------------------------------------- #
def _sync_block_task(agent: Agent, ctx: SimContext) -> None:
    target = _target_block(agent, ctx)
    bottom = agent.tasks[0] if agent.tasks else None
    if bottom is not None and bottom.kind is TaskKind.BLOCK and bottom.block is target:
        return
    if target is agent.completed_block and (bottom is None or bottom.kind is not TaskKind.BLOCK):
        return  # la tâche de ce bloc est déjà faite : on attend le bloc suivant
    if bottom is not None and _should_finish_first(agent, bottom, target, ctx):
        return
    if (
        bottom is not None
        and bottom.kind is TaskKind.BLOCK
        and bottom.block is not None
        and bottom.recipe_id == target.recipe
        and bottom.place_id == target.place_id
        and bottom.recipe_id in ("sleep", "relax_home")
    ):
        # Même recette, même lieu (le sommeil qui passe minuit) : on prolonge
        # la tâche au lieu de faire lever puis recoucher l'habitant.
        bottom.block = target
        bottom.ends_at = target.end
        if bottom.phase is Phase.PERFORM and bottom.step is not None and bottom.step.until_end:
            bottom.step_ends = float(target.end)
        return
    if bottom is not None and bottom.kind is TaskKind.BLOCK:
        if bottom is agent.task:
            cancel_task(agent, bottom, ctx)
        else:
            drop_suspended(bottom)
        agent.tasks.pop(0)
    agent.fallbacks = 0
    task = _block_task(target, target.recipe, target.label, ctx)
    agent.tasks.insert(0, task)
    if task is agent.task:
        start_task(agent, task, ctx)


def _should_finish_first(agent: Agent, bottom: Task, target: PlanBlock, ctx: SimContext) -> bool:
    """Terminer la tâche entamée avant de passer au bloc suivant ?

    Piège corrigé ici : couper un repas à l'heure pile laissait le plat
    acheté dans les mains de l'habitant… et l'habitant le ventre vide.
    """
    if bottom.kind is not TaskKind.BLOCK or bottom.finished:
        return False
    if not is_committed(bottom) or bottom.ends_at is None:
        return False
    if ctx.now >= bottom.ends_at + MAX_OVERRUN_MINUTES:
        return False
    left = minutes_left(bottom, ctx.now_exact)
    limit = LATE_TOLERANCE_MINUTES if target.punctual else MAX_OVERRUN_MINUTES
    return left is not None and left <= limit


def _block_task(block: PlanBlock, recipe_id: str, label: str, ctx: SimContext) -> Task:
    return Task(
        kind=TaskKind.BLOCK,
        recipe_id=recipe_id,
        recipe=ctx.config.actions.recipes[recipe_id],
        place_id=block.place_id,
        activity=block.activity,
        label=label,
        created=ctx.now,
        ends_at=block.end,
        block=block,
    )


def _target_block(agent: Agent, ctx: SimContext) -> PlanBlock:
    """Le bloc à suivre maintenant : le bloc courant, ou le suivant s'il faut partir tôt."""
    block = agent.current_block()
    assert block is not None  # garanti par _ensure_plan
    upcoming = agent.next_block()
    if upcoming is not None and agent.completed_block is block:
        return upcoming  # fini en avance : on enchaîne (rentrer, aller au parc...)
    if upcoming is None or not upcoming.punctual or upcoming.place_id == block.place_id:
        return block
    bottom = agent.tasks[0] if agent.tasks else None
    if bottom is not None and bottom.block is upcoming:
        return upcoming
    now = ctx.now
    if upcoming.start - now > ANTICIPATION_HORIZON:
        return block
    if agent.place_id == upcoming.place_id:
        # Déjà sur place (le bureau, avant la reprise) : on ne part pas en avance.
        # Piège : « déjà là, donc on y va » ferait sauter tout le bloc courant
        # (le déjeuner !) au lieu de partir 5 minutes plus tôt.
        travel = 0.0
    else:
        length = ctx.world.path_length_to(agent.tile, ctx.world.places[upcoming.place_id])
        if length is None:
            return block
        travel = length / ctx.config.settings.walk_speed_tiles_per_minute
    if now >= upcoming.start - travel - DEPARTURE_MARGIN:
        return upcoming
    return block


# --------------------------------------------------------------------------- #
# 3. Besoins
# --------------------------------------------------------------------------- #
def _apply_needs(agent: Agent, ctx: SimContext) -> None:
    settings = ctx.config.settings
    task = agent.task
    effects: Mapping[NeedKind, float] = {}
    stat = "trajet" if agent.is_moving else (task.recipe_id if task is not None else "rien")
    if task is not None and task.phase is Phase.PERFORM and task.step is not None:
        effects = task.step.effects
    elif agent.is_moving:
        effects = settings.walking_effects
    agent.needs.update(settings.needs, effects, ctx.hours_per_tick)
    stats = agent.minutes_by_recipe
    stats[stat] = stats.get(stat, 0.0) + ctx.minutes_per_tick


# --------------------------------------------------------------------------- #
# 4. Urgences
# --------------------------------------------------------------------------- #
def _check_urgent_needs(agent: Agent, ctx: SimContext) -> None:
    if any(task.kind in (TaskKind.URGENT, TaskKind.SERVE) for task in agent.tasks):
        return
    top = agent.task
    if (
        top is not None
        and top.phase is Phase.PERFORM
        and top.step is not None
        and not top.step.until_end
        and top.step_ends - ctx.now_exact <= FINISH_STEP_FIRST_MINUTES
    ):
        return  # le geste en cours est presque fini : l'urgence attendra un peu
    if _toilet_before_leaving(agent, ctx):
        return
    specs = ctx.config.settings.needs
    now = ctx.now
    for need in agent.needs.critical_needs(specs):
        if need is NeedKind.FUN or _is_being_remedied(agent, need, ctx):
            continue
        if now < agent.urgent_retry.get(need, 0):
            continue
        task = _urgent_task(agent, need, ctx)
        if task is None:
            agent.urgent_retry[need] = now + URGENT_RETRY_MINUTES
            continue
        ctx.emit(
            EventKind.NEED_CRITICAL,
            agent.id,
            task.place_id,
            need=need.value,
            value=round(agent.needs[need]),
            recipe=task.recipe_id,
        )
        _push(agent, task, ctx)
        return


def _toilet_before_leaving(agent: Agent, ctx: SimContext) -> bool:
    top = agent.task
    if top is None or top.phase is not Phase.TRAVEL or top.walk_goal is not None:
        return False  # on ne part pas (ou on est déjà en route)
    if agent.place_id is None or agent.place_id == top.place_id:
        return False
    if agent.needs[NeedKind.BLADDER] >= BEFORE_LEAVING_BLADDER:
        return False
    here = ctx.world.places[agent.place_id]
    if not here.offers_verb("use_toilet") or not _can_use(agent, here, ActivityType.TOILET, ctx):
        return False
    task = _make_urgent(agent, NeedKind.BLADDER, "toilet", here, ActivityType.TOILET, ctx)
    if task is None:
        return False
    task.label = "passe aux toilettes avant de partir"
    _push(agent, task, ctx)
    return True


def _is_being_remedied(agent: Agent, need: NeedKind, ctx: SimContext) -> bool:
    """Une tâche de la pile va-t-elle combler ce besoin (manger au déjeuner prévu...) ?

    On ne compte que les étapes au gain NET positif : dormir freine la faim
    mais ne la comble pas, donc une fringale réveille quand même le dormeur.
    """
    decay = ctx.config.settings.needs[need].decay_per_hour
    for task in agent.tasks:
        for step in task.recipe.steps[task.step_index :]:
            if step.effects.get(need, 0.0) > decay:
                return True
    return False


def _urgent_task(agent: Agent, need: NeedKind, ctx: SimContext) -> Task | None:
    home = ctx.world.places[agent.profile.home]
    sleeping = agent.pose is Pose.LIE
    match need:
        case NeedKind.BLADDER:
            place = _nearest_place_with(agent, "use_toilet", ActivityType.TOILET, ctx)
            return _make_urgent(agent, need, "toilet", place, ActivityType.TOILET, ctx)
        case NeedKind.HUNGER:
            for item, recipe_id in CARRIED_FOOD.items():
                if agent.carries(item):
                    table = _nearest_place_with(agent, "eat", ActivityType.EAT, ctx)
                    return _make_urgent(agent, need, recipe_id, table, ActivityType.EAT, ctx)
            fridge = home.container_with("provisions")
            has_food = fridge is not None and fridge.has("provisions")
            if agent.place_id == home.id and has_food:
                return _make_urgent(agent, need, "snack", home, ActivityType.EAT, ctx)
            shop = _nearest_food_place(agent, ctx)
            if shop is not None:
                recipe = FOOD_RECIPES[shop.kind]
                return _make_urgent(agent, need, recipe, shop, ActivityType.EAT, ctx)
            if has_food:
                return _make_urgent(agent, need, "snack", home, ActivityType.EAT, ctx)
            return None
        case NeedKind.ENERGY:
            if sleeping:
                return None
            return _make_urgent(
                agent, need, "nap", home, ActivityType.SLEEP, ctx, minutes=NAP_MINUTES
            )
        case NeedKind.HYGIENE:
            if sleeping:
                return None  # on ne se réveille pas pour une douche : ça attendra le matin
            return _make_urgent(agent, need, "shower", home, ActivityType.HYGIENE, ctx)
        case _:
            return None


def _make_urgent(
    agent: Agent,
    need: NeedKind,
    recipe_id: str,
    place: Place | None,
    activity: ActivityType,
    ctx: SimContext,
    *,
    minutes: int | None = None,
) -> Task | None:
    if place is None:
        return None
    recipe = ctx.config.actions.recipes[recipe_id]
    return Task(
        kind=TaskKind.URGENT,
        recipe_id=recipe_id,
        recipe=recipe,
        place_id=place.id,
        activity=activity,
        label=f"{URGENT_LABELS.get(need, need.label)} : {recipe.label}",
        created=ctx.now,
        ends_at=ctx.now + minutes if minutes is not None else None,
        need=need,
    )


def _can_use(agent: Agent, place: Place, activity: ActivityType, ctx: SimContext) -> bool:
    clock = ctx.clock
    return (
        place.check_access(
            activity,
            clock.weekday.number,
            clock.minute_of_day,
            resident=agent.profile.home == place.id,
            staff=agent.work_place_id == place.id,
            entering=agent.place_id != place.id,
        )
        is Access.OK
    )


def _nearest_place_with(
    agent: Agent, verb: str, activity: ActivityType, ctx: SimContext
) -> Place | None:
    """Le lieu accessible le plus proche (en pas) dont un objet propose `verb`."""
    if agent.place_id is not None:
        here = ctx.world.places[agent.place_id]
        if here.offers_verb(verb) and _can_use(agent, here, activity, ctx):
            return here
    best: Place | None = None
    best_length = 1 << 30
    for place in ctx.world.places.values():
        if place.id == agent.place_id or not place.offers_verb(verb):
            continue
        if not _can_use(agent, place, activity, ctx):
            continue
        length = ctx.world.path_length_to(agent.tile, place)
        if length is not None and length < best_length:
            best, best_length = place, length
    return best


def _nearest_food_place(agent: Agent, ctx: SimContext) -> Place | None:
    best: Place | None = None
    best_length = 1 << 30
    for place in ctx.world.places.values():
        if place.kind not in FOOD_RECIPES or place.id == agent.work_place_id:
            continue
        if not _can_use(agent, place, ActivityType.EAT, ctx):
            continue
        length = 0 if agent.place_id == place.id else ctx.world.path_length_to(agent.tile, place)
        if length is not None and length < best_length:
            best, best_length = place, length
    return best


# --------------------------------------------------------------------------- #
# 5. Le commerçant sert ses clients
# --------------------------------------------------------------------------- #
def _check_service_duty(agent: Agent, ctx: SimContext) -> None:
    block_task = agent.block_task
    if block_task is None or not block_task.recipe.serve:
        return
    if agent.place_id != block_task.place_id or agent.place_id is None:
        return
    top = agent.task
    if top is None or top.kind in (TaskKind.SERVE, TaskKind.URGENT):
        return
    for desk in ctx.desks_in(agent.place_id):
        if not desk.queue or desk.staff_spot.reserved_by is not None:
            continue
        if server_of(desk, ctx.agents) is not None:
            continue
        recipe = ctx.config.actions.recipes["serve_customers"]
        task = Task(
            kind=TaskKind.SERVE,
            recipe_id="serve_customers",
            recipe=recipe,
            place_id=agent.place_id,
            activity=ActivityType.WORK,
            label=recipe.label,
            created=ctx.now,
            desk_uid=desk.uid,
        )
        _push(agent, task, ctx)
        return


# --------------------------------------------------------------------------- #
# 6-7. Pile de tâches
# --------------------------------------------------------------------------- #
def _push(agent: Agent, task: Task, ctx: SimContext) -> None:
    top = agent.task
    if top is not None:
        suspend_task(agent, top, ctx)
    agent.tasks.append(task)
    start_task(agent, task, ctx)


def _resume(agent: Agent, task: Task, ctx: SimContext) -> None:
    """La tâche redevient active après une interruption."""
    if not task.announced:
        start_task(agent, task, ctx)
        return
    task.walk_goal = None
    if task.phase in (Phase.TRAVEL, Phase.WAIT_OPEN) or agent.place_id != task.place_id:
        task.phase = Phase.TRAVEL
    else:
        task.phase = Phase.SEEK


def _on_enter(agent: Agent, ctx: SimContext) -> None:
    """En rentrant chez soi avec des courses, on les range (comme dans les Sims)."""
    if agent.place_id != agent.profile.home:
        return
    items = ctx.config.actions.items
    if not any(items[item].stores_as for item in agent.inventory if item in items):
        return
    if any(task.recipe_id == "store_groceries" for task in agent.tasks):
        return
    recipe = ctx.config.actions.recipes["store_groceries"]
    chore = Task(
        kind=TaskKind.CHORE,
        recipe_id="store_groceries",
        recipe=recipe,
        place_id=agent.place_id,
        activity=ActivityType.RELAX,
        label=recipe.label,
        created=ctx.now,
    )
    _push(agent, chore, ctx)


def _pop_finished(agent: Agent, ctx: SimContext) -> None:
    while agent.tasks and agent.tasks[-1].finished:
        done = agent.tasks.pop()
        if done.kind is TaskKind.URGENT and done.need is not None and done.phase is Phase.DONE:
            ctx.emit(
                EventKind.NEED_RECOVERED,
                agent.id,
                done.place_id,
                need=done.need.value,
                value=round(agent.needs[done.need]),
            )
        if done.kind is TaskKind.BLOCK:
            replacement = _after_block_task(agent, done, ctx)
            if replacement is None:
                agent.completed_block = done.block
            else:
                agent.tasks.insert(0, replacement)
                if replacement is agent.task:
                    start_task(agent, replacement, ctx)
                    continue
        top = agent.task
        if top is not None:
            _resume(agent, top, ctx)


def _after_block_task(agent: Agent, done: Task, ctx: SimContext) -> Task | None:
    """Une tâche de bloc s'est terminée (ou a échoué) avant la fin du bloc : et maintenant ?"""
    block = done.block
    if block is None or ctx.now >= block.end - MIN_FILLER_MINUTES:
        return None
    agent.fallbacks += 1
    actions = ctx.config.actions
    home = ctx.world.places[agent.profile.home]
    if agent.fallbacks > MAX_FALLBACKS_PER_BLOCK:
        place = ctx.world.places[agent.place_id] if agent.place_id else home
        return _filler(block, "wait_here", place, "attend", ctx)
    if done.phase is Phase.FAILED:
        if done.activity is ActivityType.EAT:
            shop = _nearest_food_place(agent, ctx)
            fridge = home.container_with("provisions")
            if shop is not None and shop.id != done.place_id:
                return _filler(block, FOOD_RECIPES[shop.kind], shop, "va manger ailleurs", ctx)
            if fridge is not None and fridge.has("provisions"):
                return _filler(block, "snack", home, "mange un morceau chez soi", ctx)
        if agent.place_id == home.id or done.place_id != home.id:
            return _filler(block, actions.fillers["home"], home, "rentre à la maison", ctx)
        return _filler(block, "wait_here", home, "attend", ctx)
    # Tâche réussie, mais le bloc n'est pas fini : un bouche-trou adapté au lieu.
    # Sans bouche-trou prévu pour ce lieu (le supermarché), on passe au bloc suivant,
    # sauf au travail, où l'on attend la reprise.
    place = ctx.world.places[done.place_id]
    key = "home" if place.kind is PlaceKind.HOME else place.kind.value
    recipe_id = actions.fillers.get(key)
    if recipe_id is None:
        if place.id != agent.work_place_id:
            return None
        recipe_id = actions.fillers["default"]
    if place.id != agent.place_id:
        place = home
        recipe_id = actions.fillers["home"]
    label = actions.recipes[recipe_id].label
    return _filler(block, recipe_id, place, label, ctx)


def _filler(block: PlanBlock, recipe_id: str, place: Place, label: str, ctx: SimContext) -> Task:
    recipe = ctx.config.actions.recipes[recipe_id]
    activity = block.activity if place.id == block.place_id else ActivityType.RELAX
    if recipe_id in FOOD_RECIPES.values() or recipe_id == "snack":
        activity = ActivityType.EAT
    return Task(
        kind=TaskKind.BLOCK,
        recipe_id=recipe_id,
        recipe=recipe,
        place_id=place.id,
        activity=activity,
        label=label,
        created=ctx.now,
        ends_at=block.end,
        block=block,
    )
