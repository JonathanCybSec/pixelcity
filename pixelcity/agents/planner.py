"""Planification de la journée.

`Planner` est une INTERFACE (un `Protocol`) : la routine appelle
`plan_day(...)` sans savoir qui répond. À l'étape 1, c'est le planificateur
à règles ci-dessous. À l'étape 2, un `LLMPlanner` répondra à la même
interface, et gardera celui-ci comme solution de repli si Ollama est lent,
absent ou hors budget.

`Protocol` plutôt qu'une classe abstraite (ABC) : c'est du « typage
structurel ». Une classe n'a pas besoin d'hériter de `Planner` pour en être
un : il suffit qu'elle ait la bonne méthode, et mypy le vérifie.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pixelcity.agents.agent import Agent
from pixelcity.agents.plan import DayPlan, PlanBuilder
from pixelcity.config.schemas import AgentModel
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType, PlaceKind, Weekday
from pixelcity.world.place import Place
from pixelcity.world.world import World

LUNCH_START = 12 * 60 + 15
LUNCH_MINUTES = 60
WEEKEND_LUNCH = 12 * 60 + 30
DINNER = 19 * 60 + 30
DINNER_MINUTES = 45
SATURDAY_SHOPPING = 10 * 60
SHOPPING_MINUTES = 45
MIN_LEISURE_GAP = 75

# Fonction de pondération : (profil, type de lieu) -> poids du tirage au sort.
type WeightFn = Callable[[AgentModel, PlaceKind], float]

LEISURE_LABELS: dict[PlaceKind, str] = {
    PlaceKind.GYM: "séance de sport",
    PlaceKind.PARK: "promenade au parc",
    PlaceKind.CAFE: "pause au café",
}


@dataclass(frozen=True, slots=True)
class PlanningContext:
    world: World
    weekday: Weekday
    rng: random.Random


class Planner(Protocol):
    def plan_day(self, agent: Agent, day_index: int, ctx: PlanningContext) -> DayPlan: ...


class RuleBasedPlanner:
    """Planificateur déterministe : métier + jour de la semaine + un soupçon de personnalité.

    Le hasard (choix du lieu de loisir, durées) passe uniquement par
    `ctx.rng`, un flux dédié à l'agent : même graine, mêmes plans.
    """

    def plan_day(self, agent: Agent, day_index: int, ctx: PlanningContext) -> DayPlan:
        profile = agent.profile
        today = Weekday.from_index(day_index)
        tomorrow = Weekday.from_index(day_index + 1)
        shift = profile.work.schedule.get(today) if profile.work else None
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
        builder = PlanBuilder(day_index)
        builder.add(wake, ActivityType.SLEEP, home, "sommeil")
        builder.add(wake + 20, ActivityType.HYGIENE, home, "douche")
        builder.add(wake + 40, ActivityType.EAT, home, "petit-déjeuner")

        if shift:
            self._workday(builder, agent, shift, ctx)
        else:
            self._day_off(builder, agent, ctx)

        dinner = min(DINNER, bed - 90)
        self._free_time(builder, agent, dinner, ctx)
        builder.add(dinner, ActivityType.RELAX, home, "temps libre à la maison")
        builder.add(dinner + DINNER_MINUTES, ActivityType.EAT, home, "dîner")
        builder.add(bed, ActivityType.RELAX, home, "soirée tranquille")
        builder.add(MINUTES_PER_DAY, ActivityType.SLEEP, home, "sommeil")
        return builder.build()

    # ------------------------------------------------------------------ #
    # Journées types
    # ------------------------------------------------------------------ #
    def _workday(
        self, builder: PlanBuilder, agent: Agent, shift: tuple[int, int], ctx: PlanningContext
    ) -> None:
        profile = agent.profile
        work = profile.work
        assert work is not None  # garanti par l'appelant (shift existe)
        start, end = shift
        home = profile.home

        # Temps libre avant le travail : la routine fera partir l'agent assez
        # tôt pour arriver à l'heure (bloc de travail « ponctuel »).
        builder.add(start, ActivityType.RELAX, home, "temps libre")

        lunch_end = LUNCH_START + LUNCH_MINUTES
        if start <= LUNCH_START - 60 and end >= lunch_end + 60:
            builder.add(LUNCH_START, ActivityType.WORK, work.place, "travail", punctual=True)
            if work.lunch_at_work:
                builder.add(lunch_end, ActivityType.EAT, work.place, "déjeuner à la cantine")
            else:
                place = self._pick_place(
                    ctx, ActivityType.EAT, LUNCH_START, lunch_end, profile, _lunch_weight
                )
                builder.add(lunch_end, ActivityType.EAT, place.id if place else home, "déjeuner")
            builder.add(end, ActivityType.WORK, work.place, "travail", punctual=True)
        else:
            builder.add(end, ActivityType.WORK, work.place, "travail", punctual=True)
            if 11 * 60 <= end <= 14 * 60:
                builder.add(end + 60, ActivityType.EAT, home, "déjeuner")
                if profile.sleep.wake <= 5 * 60:
                    # Les lève-tôt (le boulanger !) font la sieste.
                    builder.add(builder.cursor + 75, ActivityType.SLEEP, home, "sieste")

    def _day_off(self, builder: PlanBuilder, agent: Agent, ctx: PlanningContext) -> None:
        profile = agent.profile
        home = profile.home
        if ctx.weekday is Weekday.SAT:
            shop = self._pick_place(
                ctx,
                ActivityType.SHOP,
                SATURDAY_SHOPPING,
                SATURDAY_SHOPPING + SHOPPING_MINUTES,
                profile,
                lambda _p, _k: 1.0,
            )
            if shop is not None:
                builder.add(SATURDAY_SHOPPING, ActivityType.RELAX, home, "matinée tranquille")
                builder.add(
                    SATURDAY_SHOPPING + SHOPPING_MINUTES, ActivityType.SHOP, shop.id, "courses"
                )
        self._free_time(builder, agent, WEEKEND_LUNCH, ctx, max_blocks=1)
        builder.add(WEEKEND_LUNCH, ActivityType.RELAX, home, "matinée tranquille")
        lunch_place = home
        cafe = self._pick_place(
            ctx, ActivityType.EAT, WEEKEND_LUNCH, WEEKEND_LUNCH + 60, profile, _lunch_weight
        )
        # Le week-end, on déjeune plutôt chez soi... sauf les plus sociables.
        if cafe is not None and ctx.rng.random() < 0.5 * profile.personality.extraversion:
            lunch_place = cafe.id
        builder.add(WEEKEND_LUNCH + 60, ActivityType.EAT, lunch_place, "déjeuner")

    def _free_time(
        self,
        builder: PlanBuilder,
        agent: Agent,
        until: int,
        ctx: PlanningContext,
        max_blocks: int = 2,
    ) -> None:
        """Remplit un créneau libre avec 1 ou 2 loisirs, séparés par un temps calme."""
        home = agent.profile.home
        added = 0
        visited: set[str] = set()
        while added < max_blocks and until - builder.cursor >= MIN_LEISURE_GAP:
            if added > 0:
                if until - builder.cursor < 60 + MIN_LEISURE_GAP:
                    break
                builder.add(builder.cursor + 60, ActivityType.RELAX, home, "temps calme")
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
            )
            if place is None:
                break
            visited.add(place.id)
            label = LEISURE_LABELS.get(place.kind, "loisir")
            builder.add(start + duration, ActivityType.LEISURE, place.id, label)
            if place.kind is PlaceKind.GYM and until - builder.cursor >= 50:
                # Après le sport, une douche s'impose (la salle fait baisser l'hygiène).
                builder.add(
                    builder.cursor + 40, ActivityType.HYGIENE, home, "douche après le sport"
                )
            added += 1

    # ------------------------------------------------------------------ #
    # Choix des lieux
    # ------------------------------------------------------------------ #
    def _pick_place(
        self,
        ctx: PlanningContext,
        activity: ActivityType,
        start: int,
        end: int,
        profile: AgentModel,
        weight: WeightFn,
        avoid: set[str] | None = None,
    ) -> Place | None:
        """Tire au sort un lieu public proposant `activity` et ouvert sur tout le créneau.

        Les lieux de `avoid` (déjà fréquentés aujourd'hui) restent possibles
        mais 4 fois moins probables : un peu de variété dans les journées.
        """
        day = ctx.weekday.number
        candidates = [
            place
            for place in ctx.world.places.values()
            if place.kind is not PlaceKind.HOME
            and activity in place.activities
            and place.hours.is_open(day, start)
            and place.hours.is_open(day, end - 1)
        ]
        if not candidates:
            return None
        weights = [
            max(0.05, weight(profile, place.kind)) * (0.25 if avoid and place.id in avoid else 1.0)
            for place in candidates
        ]
        return ctx.rng.choices(candidates, weights=weights, k=1)[0]


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
