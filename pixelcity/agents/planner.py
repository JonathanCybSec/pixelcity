"""Planification de la journée : QUOI faire, OÙ, et avec quelle recette.

`Planner` est une INTERFACE (un `Protocol`) : la routine appelle
`plan_day(...)` sans savoir qui répond. Aujourd'hui, c'est le planificateur
à règles ci-dessous. À l'étape 3, un `LLMPlanner` répondra à la même
interface, et gardera celui-ci comme solution de repli si le modèle est
lent, absent ou hors budget.

`Protocol` plutôt qu'une classe abstraite (ABC) : c'est du « typage
structurel ». Une classe n'a pas besoin d'hériter de `Planner` pour en être
un : il suffit qu'elle ait la bonne méthode, et mypy le vérifie.

Ce planificateur regarde aussi le FRIGO : s'il reste peu de provisions, il
glisse des courses dans la journée. Les besoins ne se gèrent pas tout seuls.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pixelcity.agents.agent import Agent
from pixelcity.agents.plan import DayPlan, PlanBuilder
from pixelcity.config.schemas import ActionsConfig, AgentModel
from pixelcity.llm.types import Intentions
from pixelcity.sim.appointments import Appointment
from pixelcity.sim.options import DayOption
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType, PlaceKind, Weekday
from pixelcity.world.place import Place
from pixelcity.world.world import World

LUNCH_START = 12 * 60 + 15
LUNCH_MINUTES = 60
STAFF_LUNCH_START = 11 * 60 + 15  # les commerçants déjeunent avant le coup de feu
STAFF_LUNCH_MINUTES = 30
WEEKEND_LUNCH = 12 * 60 + 30
DINNER = 19 * 60 + 30
DINNER_MINUTES = 60
MORNING_MINUTES = 20
BREAKFAST_MINUTES = 30
SATURDAY_SHOPPING = 10 * 60
SHOPPING_MINUTES = 45
MIN_LEISURE_GAP = 75
DEPARTURE_MARGIN = 5  # minutes d'avance pour un engagement à l'heure
FRIDGE_LOW = 4  # provisions : en dessous, on fait des courses
PACK_LUNCH_MINUTES = 10
MEAL_OPEN_MINUTES = 30  # pour manger dehors, il suffit que ce soit ouvert 30 min
HOME_LUNCH_MAX_COMMUTE = 12  # au-delà, rentrer déjeuner chez soi prend trop de temps

# Fonction de pondération : (profil, type de lieu) -> poids du tirage au sort.
type WeightFn = Callable[[AgentModel, PlaceKind], float]

SPENDING_PLACES = {PlaceKind.CAFE, PlaceKind.BAKERY}  # où un loisir ou un repas coûte

LEISURE: dict[PlaceKind, tuple[str, str]] = {
    PlaceKind.GYM: ("séance de sport", "gym_session"),
    PlaceKind.PARK: ("promenade au parc", "park_walk"),
    PlaceKind.CAFE: ("pause au café", "cafe_coffee"),
}
LUNCH_OUT: dict[PlaceKind, tuple[str, str]] = {
    PlaceKind.BAKERY: ("déjeuner à la boulangerie", "bakery_lunch"),
    PlaceKind.CAFE: ("déjeuner au café", "cafe_lunch"),
}


@dataclass(frozen=True, slots=True)
class Lunch:
    """Le déjeuner d'un jour de travail, décidé AVANT la matinée.

    Pourquoi avant ? Parce que la gamelle se prépare le matin.
    """

    start: int
    end: int
    place_id: str
    label: str
    recipe: str
    lunchbox: bool = False


@dataclass(frozen=True, slots=True)
class PlanningContext:
    world: World
    actions: ActionsConfig
    weekday: Weekday
    rng: random.Random
    walk_speed: float  # tuiles par minute
    # Étape 5 : rendez-vous pris la veille, à caser dans la journée.
    appointments: tuple[Appointment, ...] = ()
    # Étape 6 : budget serré → pas de déjeuner dehors ni de café.
    tight_budget: bool = False
    # Étape 6 bis : ce que l'IA de l'habitant a décidé la veille, et sa situation.
    intentions: Intentions | None = None
    homeless: bool = False
    money: float = 0.0
    prices: dict[str, float] = field(default_factory=dict)
    # Étape 6 ter : le menu de la ville (options du jour) et, pour une
    # replanification en cours de journée, la minute à partir de laquelle replanifier.
    options: dict[str, DayOption] = field(default_factory=dict)
    replan_from: int | None = None


class Planner(Protocol):
    def plan_day(self, agent: Agent, day_index: int, ctx: PlanningContext) -> DayPlan: ...


class RuleBasedPlanner:
    """Planificateur déterministe : métier + jour + frigo + un soupçon de personnalité.

    Le hasard (choix du lieu de loisir, durées) passe uniquement par
    `ctx.rng`, un flux dédié à l'agent : même graine, mêmes plans.
    """

    def plan_day(self, agent: Agent, day_index: int, ctx: PlanningContext) -> DayPlan:
        profile = agent.profile
        today = Weekday.from_index(day_index)
        tomorrow = Weekday.from_index(day_index + 1)
        shift = profile.work.schedule.get(today) if profile.work else None
        if shift and ctx.intentions is not None and not ctx.intentions.work:
            shift = None  # l'habitant a décidé de ne pas y aller : journée non payée
        if ctx.intentions is not None and ctx.intentions.schedule and ctx.options:
            return self._ai_day(agent, day_index, shift, ctx)
        if ctx.homeless:
            return self._homeless_day(agent, day_index, shift, ctx)
        works_tomorrow = profile.work is not None and tomorrow in profile.work.schedule

        if shift:
            wake = profile.sleep.wake
        elif profile.sleep.weekend_wake is not None:
            wake = profile.sleep.weekend_wake
        else:
            wake = min(profile.sleep.wake + 90, 11 * 60)
        # On se couche plus tard la veille d'un jour sans travail.
        bed = profile.sleep.bed if works_tomorrow else min(profile.sleep.bed + 60, 23 * 60 + 45)

        home = profile.home
        visited: set[str] = set()  # lieux de loisir déjà prévus aujourd'hui
        lunch = self._workday_lunch(agent, shift, ctx) if shift else None
        builder = PlanBuilder(day_index)
        builder.add(wake, ActivityType.SLEEP, home, "sommeil", "sleep")
        morning_end = wake + MORNING_MINUTES
        breakfast_end = wake + MORNING_MINUTES + BREAKFAST_MINUTES
        if shift:
            # Le travail n'attend pas : on raccourcit le matin si le trajet est long.
            leave = shift[0] - self._commute(agent, ctx) - DEPARTURE_MARGIN
            if lunch is not None and lunch.lunchbox:
                leave -= PACK_LUNCH_MINUTES
            morning_end = min(morning_end, leave)
            breakfast_end = min(breakfast_end, leave)
        builder.add(morning_end, ActivityType.HYGIENE, home, "toilette du matin", "morning")
        breakfast = "breakfast" if breakfast_end - builder.cursor >= 20 else "snack"
        builder.add(breakfast_end, ActivityType.EAT, home, "petit-déjeuner", breakfast)
        if lunch is not None and lunch.lunchbox:
            builder.add(
                builder.cursor + PACK_LUNCH_MINUTES,
                ActivityType.EAT,
                home,
                "prépare sa gamelle",
                "pack_lunch",
            )

        shopping = self._fridge_is_low(agent, ctx)
        if shift:
            # Frigo vide et service jusqu'au soir (serveur, 11 h - 19 h) : le
            # supermarché sera fermé en sortant, on fait donc les courses le
            # matin, s'il reste le temps avant de partir travailler.
            if shopping:
                shopping = self._free_time(
                    builder, agent, shift[0] - 30, ctx, visited, max_blocks=0, shopping=True
                )
            self._workday(builder, agent, shift, lunch, ctx)
        else:
            shopping = self._day_off(builder, agent, ctx, shopping, visited)

        dinner = min(DINNER, bed - DINNER_MINUTES - 30)
        shopping = self._appointments(builder, agent, dinner, ctx, visited, shopping)
        self._intended(builder, agent, dinner, ctx, visited)
        self._free_time(builder, agent, dinner, ctx, visited, shopping=shopping)
        builder.add(dinner, ActivityType.RELAX, home, "temps libre à la maison", "relax_home")
        builder.add(dinner + DINNER_MINUTES, ActivityType.EAT, home, "dîner", "home_meal")
        builder.add(bed, ActivityType.RELAX, home, "soirée tranquille", "relax_home")
        builder.add(MINUTES_PER_DAY, ActivityType.SLEEP, home, "sommeil", "sleep")
        return builder.build()

    # ------------------------------------------------------------------ #
    # Journées types
    # ------------------------------------------------------------------ #
    def _workday_lunch(
        self, agent: Agent, shift: tuple[int, int], ctx: PlanningContext
    ) -> Lunch | None:
        """Où et comment déjeuner un jour de travail (None si le service ne couvre pas midi)."""
        profile = agent.profile
        work = profile.work
        assert work is not None
        place = ctx.world.places[work.place]
        job = ctx.actions.jobs.get(place.kind, "wait_here")
        serves = ctx.actions.recipes[job].serve
        start = STAFF_LUNCH_START if serves else LUNCH_START
        end = start + (STAFF_LUNCH_MINUTES if work.lunch_at_work and serves else LUNCH_MINUTES)
        if not (shift[0] <= start - 60 and shift[1] >= end + 60):
            return None
        if work.lunch_at_work:
            if place.kind is PlaceKind.SCHOOL:
                return Lunch(start, end, work.place, "déjeuner à la cantine", "cantine_lunch")
            return Lunch(start, end, work.place, "pause déjeuner", "staff_lunch")
        shop = self._pick_place(
            ctx,
            ActivityType.EAT,
            start,
            end,
            profile,
            _lunch_weight,
            kinds=set(LUNCH_OUT),
            open_minutes=MEAL_OPEN_MINUTES,
        )
        if shop is not None:
            label, recipe = LUNCH_OUT[shop.kind]
            return Lunch(start, end, shop.id, label, recipe)
        if self._commute(agent, ctx) <= HOME_LUNCH_MAX_COMMUTE:
            return Lunch(start, end, profile.home, "déjeuner", "home_meal")
        # Rien d'ouvert et la maison est loin : on emporte sa gamelle.
        return Lunch(
            start, end, work.place, "déjeuner sur le pouce", "lunchbox_lunch", lunchbox=True
        )

    def _workday(
        self,
        builder: PlanBuilder,
        agent: Agent,
        shift: tuple[int, int],
        lunch: Lunch | None,
        ctx: PlanningContext,
    ) -> None:
        profile = agent.profile
        work = profile.work
        assert work is not None  # garanti par l'appelant (shift existe)
        start, end = shift
        home = profile.home
        place = ctx.world.places[work.place]
        job = ctx.actions.jobs.get(place.kind, "wait_here")

        # Temps libre avant le travail : la routine fera partir l'agent assez
        # tôt pour arriver à l'heure (bloc de travail « ponctuel »).
        builder.add(start, ActivityType.RELAX, home, "temps libre", "relax_home")

        if lunch is not None:
            builder.add(lunch.start, ActivityType.WORK, work.place, "travail", job, punctual=True)
            builder.add(lunch.end, ActivityType.EAT, lunch.place_id, lunch.label, lunch.recipe)
            builder.add(end, ActivityType.WORK, work.place, "travail", job, punctual=True)
        else:
            builder.add(end, ActivityType.WORK, work.place, "travail", job, punctual=True)
            if 11 * 60 <= end <= 14 * 60:
                builder.add(end + 60, ActivityType.EAT, home, "déjeuner", "home_meal")
                if profile.sleep.wake <= 5 * 60:
                    # Les lève-tôt (le boulanger !) font la sieste.
                    builder.add(builder.cursor + 75, ActivityType.SLEEP, home, "sieste", "nap")

    # ------------------------------------------------------------------ #
    # Étape 6 bis : les intentions de l'IA, et la vie à la rue
    # ------------------------------------------------------------------ #
    def _intended(
        self,
        builder: PlanBuilder,
        agent: Agent,
        until: int,
        ctx: PlanningContext,
        visited: set[str],
    ) -> None:
        """Place dans le temps libre ce que l'habitant a décidé hier soir de faire."""
        intentions = ctx.intentions
        if intentions is None:
            return
        home = agent.profile.home
        money = ctx.money
        for item in intentions.purchases:
            price = ctx.prices.get(item)
            if price is None or price > money or until - builder.cursor < 75:
                continue  # trop cher, finalement : on ne fait pas de dette pour ça
            start = builder.cursor
            # Le magasin qui vend l'article, ouvert pendant l'heure du bloc (trajet compris).
            shop = next(
                (ctx.world.places[p] for p in _sellers(ctx, item) if _is_open_for(ctx, p, start)),
                None,
            )
            if shop is None:
                continue
            money -= price
            label = ctx.actions.items[item].label
            builder.add(
                start + 60, ActivityType.SHOP, shop.id, f"s'acheter : {label}", f"buy_{item}"
            )
        for activity in intentions.activities:
            if until - builder.cursor < 40:
                break
            start = builder.cursor
            match activity:
                case "job_search":
                    builder.add(
                        start + 50, ActivityType.RELAX, home, "cherche un emploi", "job_search"
                    )
                case "beg":
                    builder.add(start + 90, ActivityType.LEISURE, "parc", "fait la manche", "beg")
                case "steal_food":
                    shop = self._pick_place(
                        ctx,
                        ActivityType.SHOP,
                        start,
                        start + 50,
                        agent.profile,
                        lambda _p, _k: 1.0,
                        kinds={PlaceKind.SUPERMARKET},
                    )
                    if shop is not None:
                        builder.add(
                            start + 50, ActivityType.SHOP, shop.id, "voler à manger", "steal_food"
                        )
                case "rest":
                    builder.add(
                        start + 60,
                        ActivityType.RELAX,
                        home,
                        "se repose",
                        "relax_home" if not ctx.homeless else "linger",
                    )
                case "casino" | "bar":
                    kind = PlaceKind.CASINO if activity == "casino" else PlaceKind.BAR
                    place = self._pick_place(
                        ctx,
                        ActivityType.LEISURE,
                        start,
                        start + 90,
                        agent.profile,
                        _leisure_weight,
                        kinds={kind},
                    )
                    if place is not None:
                        recipe = "casino" if activity == "casino" else "bar_evening"
                        label = "casino" if activity == "casino" else "un verre au bar"
                        builder.add(start + 90, ActivityType.LEISURE, place.id, label, recipe)
                case "park" | "gym" | "cafe":
                    kind = {"park": PlaceKind.PARK, "gym": PlaceKind.GYM, "cafe": PlaceKind.CAFE}[
                        activity
                    ]
                    duration = 75
                    place = self._pick_place(
                        ctx,
                        ActivityType.LEISURE,
                        start,
                        start + duration,
                        agent.profile,
                        _leisure_weight,
                        kinds={kind},
                    )
                    if place is not None:
                        label, recipe = LEISURE[place.kind]
                        builder.add(start + duration, ActivityType.LEISURE, place.id, label, recipe)
                        visited.add(place.id)

    def _ai_day(
        self, agent: Agent, day_index: int, shift: tuple[int, int] | None, ctx: PlanningContext
    ) -> DayPlan:
        """La journée composée par l'IA de l'habitant, heure par heure.

        Le corps garde ses exigences (dormir, se laver, manger le soir) ; tout le
        reste suit le programme choisi. Chaque activité est recalée dans les
        horaires d'ouverture ; une activité impossible (fermé, trop court) saute.
        """
        intentions = ctx.intentions
        assert intentions is not None
        profile = agent.profile
        homeless = ctx.homeless
        home = "parc" if homeless else profile.home
        idle = "linger" if homeless else "relax_home"
        builder = PlanBuilder(day_index)
        chosen = [a for _m, a in intentions.schedule]
        if ctx.replan_from is not None:
            # Replanification : le passé ne bouge pas, on repart de maintenant.
            builder.add(ctx.replan_from, ActivityType.RELAX, home, "…", idle)
        else:
            if shift:
                wake = profile.sleep.wake
            elif profile.sleep.weekend_wake is not None:
                wake = profile.sleep.weekend_wake
            else:
                wake = min(profile.sleep.wake + 90, 11 * 60)
            if "sleep_in" in chosen:
                wake = min(wake + 120, 12 * 60)
            sleep_recipe = "sleep_rough" if homeless else "sleep"
            builder.add(wake, ActivityType.SLEEP, home, "sommeil", sleep_recipe)
            if not homeless:
                builder.add(
                    wake + MORNING_MINUTES,
                    ActivityType.HYGIENE,
                    home,
                    "toilette du matin",
                    "morning",
                )
                builder.add(
                    builder.cursor + BREAKFAST_MINUTES,
                    ActivityType.EAT,
                    home,
                    "petit-déjeuner",
                    "breakfast",
                )
        lunch = self._workday_lunch(agent, shift, ctx) if shift and "work" in chosen else None
        bed = min(profile.sleep.bed, 23 * 60 + 30)
        for minute, activity in intentions.schedule:
            if activity == "sleep_in":
                continue
            if activity == "work":
                if not shift or "work" not in chosen or builder.cursor > shift[0]:
                    continue
                leave = shift[0] - self._commute(agent, ctx) - DEPARTURE_MARGIN
                if leave - builder.cursor >= 15:
                    builder.add(leave, ActivityType.RELAX, home, "temps libre", idle)
                self._workday(builder, agent, shift, lunch, ctx)
                continue
            option = ctx.options.get(activity)
            if option is None:
                continue
            open_from, open_until = option.window
            start = max(minute, builder.cursor, open_from)
            end = min(start + option.minutes, open_until, bed)
            if end - start < 20:
                continue
            if shift and "work" in chosen and start < shift[1] and end > shift[0] - 30:
                continue  # le travail passe avant (c'est l'habitant qui l'a choisi)
            leave = start - 15  # le temps d'y aller
            if leave - builder.cursor >= 15:
                builder.add(leave, ActivityType.RELAX, home, "temps libre", idle)
            place = option.place_id or home
            builder.add(end, option.activity, place, option.short, option.recipe)
        if not homeless and builder.cursor <= DINNER:
            builder.add(DINNER, ActivityType.RELAX, home, "temps libre à la maison", idle)
            builder.add(DINNER + DINNER_MINUTES, ActivityType.EAT, home, "dîner", "home_meal")
        if builder.cursor < bed:
            builder.add(bed, ActivityType.RELAX, home, "soirée tranquille", idle)
        builder.add(
            MINUTES_PER_DAY,
            ActivityType.SLEEP,
            home,
            "sommeil",
            "sleep_rough" if homeless else "sleep",
        )
        return builder.build()

    def _homeless_day(
        self, agent: Agent, day_index: int, shift: tuple[int, int] | None, ctx: PlanningContext
    ) -> DayPlan:
        """Une journée à la rue : nuit sur un banc, travail s'il en a un, débrouille."""
        park = "parc"
        builder = PlanBuilder(day_index)
        wake = min(agent.profile.sleep.wake, 7 * 60)
        builder.add(wake, ActivityType.SLEEP, park, "nuit dehors", "sleep_rough")
        if shift is not None and agent.profile.work is not None:
            commute = self._commute(agent, ctx)
            builder.add(
                shift[0] - commute - DEPARTURE_MARGIN,
                ActivityType.RELAX,
                park,
                "attend au parc",
                "linger",
            )
            job = ctx.actions.jobs.get(ctx.world.places[agent.profile.work.place].kind, "wait_here")
            builder.add(
                shift[1], ActivityType.WORK, agent.profile.work.place, "travail", job, punctual=True
            )
        self._intended(builder, agent, 20 * 60 + 30, ctx, set())
        builder.add(21 * 60 + 30, ActivityType.LEISURE, park, "traîne au parc", "park_walk")
        builder.add(MINUTES_PER_DAY, ActivityType.SLEEP, park, "nuit dehors", "sleep_rough")
        return builder.build()

    def _appointments(
        self,
        builder: PlanBuilder,
        agent: Agent,
        until: int,
        ctx: PlanningContext,
        visited: set[str],
        shopping: bool,
    ) -> bool:
        """Cale les rendez-vous de la journée : temps libre jusque-là, puis le rendez-vous.

        Le bloc est « ponctuel » : la routine fait partir l'habitant assez tôt
        pour arriver à l'heure, comme pour le travail.
        """
        for appointment in ctx.appointments:
            if appointment.start - 20 < builder.cursor or appointment.end > until:
                continue  # trop tôt (encore au travail) ou trop tard : il ne pourra pas venir
            place = ctx.world.places.get(appointment.place_id)
            if place is None or place.kind not in LEISURE:
                continue
            shopping = self._free_time(
                builder,
                agent,
                appointment.start - 20,
                ctx,
                visited,
                max_blocks=1,
                shopping=shopping,
            )
            # Long creux avant le rendez-vous : on l'attend chez soi. Court : on part
            # directement (un aller-retour à la maison pour 20 minutes serait absurde).
            if appointment.start - 20 - builder.cursor > 60:
                builder.add(
                    appointment.start - 20,
                    ActivityType.RELAX,
                    agent.profile.home,
                    "temps libre à la maison",
                    "relax_home",
                )
            _label, recipe = LEISURE[place.kind]
            builder.add(
                appointment.end,
                ActivityType.LEISURE,
                place.id,
                appointment.label_for(agent.id),
                recipe,
                punctual=True,
            )
            visited.add(place.id)
        return shopping

    def _day_off(
        self,
        builder: PlanBuilder,
        agent: Agent,
        ctx: PlanningContext,
        shopping: bool,
        visited: set[str],
    ) -> bool:
        """Matinée libre, courses éventuelles, déjeuner.

        Renvoie True s'il reste des courses à faire dans l'après-midi.
        """
        profile = agent.profile
        home = profile.home
        if shopping or ctx.weekday is Weekday.SAT:
            # Après le petit-déjeuner, même pour qui se lève tard.
            start = max(SATURDAY_SHOPPING, builder.cursor)
            shop = self._pick_place(
                ctx,
                ActivityType.SHOP,
                start,
                start + SHOPPING_MINUTES,
                profile,
                lambda _p, _k: 1.0,
                kinds={PlaceKind.SUPERMARKET},
            )
            if shop is not None:
                builder.add(start, ActivityType.RELAX, home, "matinée tranquille", "relax_home")
                builder.add(
                    start + SHOPPING_MINUTES, ActivityType.SHOP, shop.id, "courses", "shopping"
                )
                shopping = False
        self._free_time(builder, agent, WEEKEND_LUNCH, ctx, visited, max_blocks=1)
        builder.add(WEEKEND_LUNCH, ActivityType.RELAX, home, "matinée tranquille", "relax_home")
        cafe = self._pick_place(
            ctx,
            ActivityType.EAT,
            WEEKEND_LUNCH,
            WEEKEND_LUNCH + 60,
            profile,
            _lunch_weight,
            kinds={PlaceKind.CAFE},
            open_minutes=MEAL_OPEN_MINUTES,
        )
        # Le week-end, on déjeune plutôt chez soi... sauf les plus sociables.
        if cafe is not None and ctx.rng.random() < 0.5 * profile.personality.extraversion:
            label, recipe = LUNCH_OUT[cafe.kind]
            builder.add(WEEKEND_LUNCH + 60, ActivityType.EAT, cafe.id, label, recipe)
        else:
            builder.add(WEEKEND_LUNCH + 60, ActivityType.EAT, home, "déjeuner", "home_meal")
        return shopping

    def _free_time(
        self,
        builder: PlanBuilder,
        agent: Agent,
        until: int,
        ctx: PlanningContext,
        visited: set[str],
        max_blocks: int = 2,
        *,
        shopping: bool = False,
    ) -> bool:
        """Remplit un créneau libre : courses si le frigo est vide, puis 1 ou 2 loisirs.

        Renvoie True s'il reste des courses à faire (pas eu le temps, ou fermé).
        """
        home = agent.profile.home
        if shopping and until - builder.cursor >= SHOPPING_MINUTES + 30:
            start = builder.cursor
            shop = self._pick_place(
                ctx,
                ActivityType.SHOP,
                start,
                start + SHOPPING_MINUTES,
                agent.profile,
                lambda _p, _k: 1.0,
                kinds={PlaceKind.SUPERMARKET},
            )
            if shop is not None:
                builder.add(
                    start + SHOPPING_MINUTES, ActivityType.SHOP, shop.id, "courses", "shopping"
                )
                builder.add(
                    builder.cursor + 20, ActivityType.RELAX, home, "range ses courses", "relax_home"
                )
                shopping = False
        added = 0
        while added < max_blocks and until - builder.cursor >= MIN_LEISURE_GAP:
            if added > 0:
                if until - builder.cursor < 60 + MIN_LEISURE_GAP:
                    break
                builder.add(
                    builder.cursor + 60, ActivityType.RELAX, home, "temps calme", "relax_home"
                )
            start = builder.cursor
            duration = min(until - start - 30, ctx.rng.choice((60, 75, 90, 105, 120)))
            place = self._pick_place(
                ctx,
                ActivityType.LEISURE,
                start,
                start + duration,
                agent.profile,
                _leisure_weight,
                avoid=visited,
                kinds=set(LEISURE),
            )
            if place is None:
                break
            visited.add(place.id)
            label, recipe = LEISURE[place.kind]
            builder.add(start + duration, ActivityType.LEISURE, place.id, label, recipe)
            added += 1
        return shopping

    # ------------------------------------------------------------------ #
    # Outils
    # ------------------------------------------------------------------ #
    def _commute(self, agent: Agent, ctx: PlanningContext) -> int:
        """Durée du trajet domicile → travail, en minutes (estimée par A*)."""
        work = agent.profile.work
        if work is None:
            return 0
        home = ctx.world.places[agent.profile.home]
        length = ctx.world.path_length_to(home.entrances[0], ctx.world.places[work.place])
        if length is None:
            return 0
        return round(length / ctx.walk_speed) + 3  # + le temps de sortir et d'entrer

    def _fridge_is_low(self, agent: Agent, ctx: PlanningContext) -> bool:
        home = ctx.world.places[agent.profile.home]
        fridge = home.container_with("provisions")
        if fridge is None:
            return False
        stock = fridge.count("provisions") + 10 * agent.inventory.get("groceries", 0)
        affordable = ctx.money >= ctx.prices.get("groceries", 0.0)
        return stock <= FRIDGE_LOW and affordable

    def _pick_place(
        self,
        ctx: PlanningContext,
        activity: ActivityType,
        start: int,
        end: int,
        profile: AgentModel,
        weight: WeightFn,
        avoid: set[str] | None = None,
        kinds: set[PlaceKind] | None = None,
        open_minutes: int | None = None,
    ) -> Place | None:
        """Tire au sort un lieu public proposant `activity` et ouvert sur le créneau.

        `open_minutes` : il suffit que le lieu soit ouvert ce temps-là après le
        début (on peut finir son sandwich après la fermeture de la boulangerie).

        Les lieux de `avoid` (déjà fréquentés aujourd'hui) restent possibles
        mais 4 fois moins probables : un peu de variété dans les journées.
        Le lieu où l'on TRAVAILLE est exclu : on ne prend pas son café chez soi.
        """
        day = ctx.weekday.number
        # Son propre lieu de travail est exclu pour les loisirs et les repas
        # (on ne prend pas son café chez soi), pas pour les courses.
        work_place = (
            profile.work.place if profile.work and activity is not ActivityType.SHOP else None
        )
        last = start + open_minutes - 1 if open_minutes is not None else end - 1
        candidates = [
            place
            for place in ctx.world.places.values()
            if place.kind is not PlaceKind.HOME
            and place.id != work_place
            and (kinds is None or place.kind in kinds)
            and activity in place.activities
            and place.hours.is_open(day, start)
            and place.hours.is_open(day, last)
            and not (
                ctx.tight_budget
                and activity in (ActivityType.EAT, ActivityType.LEISURE)
                and place.kind in SPENDING_PLACES
            )
        ]
        if not candidates:
            return None
        origin = ctx.world.places[profile.home].entrances[0]
        weights = [
            max(0.05, weight(profile, place.kind))
            * (0.25 if avoid and place.id in avoid else 1.0)
            * _proximity(ctx, origin, place)
            for place in candidates
        ]
        return ctx.rng.choices(candidates, weights=weights, k=1)[0]


def _proximity(ctx: PlanningContext, origin: tuple[int, int], place: Place) -> float:
    """1 juste à côté, 0,5 à 20 minutes de marche : la distance compte dans les choix."""
    length = ctx.world.path_length_to(origin, place)
    if length is None:
        return 0.0
    minutes = length / ctx.walk_speed
    return 1.0 / (1.0 + minutes / 20.0)


def _leisure_weight(profile: AgentModel, kind: PlaceKind) -> float:
    """Pondération des loisirs par la personnalité (Big Five) et l'âge."""
    traits = profile.personality
    youth = max(0.0, 1.0 - profile.age / 80)
    if kind is PlaceKind.GYM:
        return 0.15 + 0.6 * traits.conscientiousness + 0.4 * youth - 0.2 * traits.neuroticism
    if kind is PlaceKind.PARK:
        return 0.3 + 0.5 * traits.openness + 0.3 * traits.agreeableness
    if kind is PlaceKind.CAFE:
        return 0.2 + 0.8 * traits.extraversion
    return 0.3


def _lunch_weight(profile: AgentModel, kind: PlaceKind) -> float:
    traits = profile.personality
    if kind is PlaceKind.CAFE:
        return 0.3 + 0.7 * traits.extraversion
    if kind is PlaceKind.BAKERY:
        return 0.4 + 0.4 * (1 - traits.extraversion) + 0.2 * traits.conscientiousness
    return 0.3


def _sellers(ctx: PlanningContext, item: str) -> list[str]:
    """Les lieux dont un comptoir vend `item` (la boutique pour les vêtements...)."""
    found = {
        furniture.place_id
        for furniture in ctx.world.furniture.values()
        if item in furniture.sells and furniture.place_id is not None
    }
    return sorted(found)


def _is_open_for(ctx: PlanningContext, place_id: str, start: int) -> bool:
    hours = ctx.world.places[place_id].hours
    day = ctx.weekday.number
    return hours.is_open(day, start) and hours.is_open(day, start + 59)
