"""Tout ce que la ville propose à un habitant pour une journée donnée.

C'est le « menu » présenté à son IA chaque soir : chaque option dit ce qu'elle
coûte, quand c'est ouvert, ce qu'on y gagne. L'IA compose sa journée avec ;
le planificateur la traduit ensuite en blocs (lieu, recette, horaires).

Une seule fonction construit le menu, utilisée par les deux côtés (le prompt
et le planificateur) : impossible qu'ils divergent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pixelcity.sim.types import ActivityType, PlaceKind, Weekday

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.config.loader import GameConfig
    from pixelcity.world.world import World


@dataclass(frozen=True, slots=True)
class DayOption:
    id: str
    label: str  # pour l'IA : détails, prix, horaires
    short: str  # pour le plan affiché : « boit un verre au bar »
    place_id: str | None  # None : chez soi (le domicile du moment)
    activity: ActivityType
    recipe: str
    minutes: int
    window: tuple[int, int]  # ouvert de… à… (minutes du jour)


SEE_RECIPES: dict[PlaceKind, tuple[ActivityType, str]] = {
    PlaceKind.CAFE: (ActivityType.LEISURE, "cafe_coffee"),
    PlaceKind.BAR: (ActivityType.LEISURE, "bar_evening"),
    PlaceKind.CASINO: (ActivityType.LEISURE, "casino"),
    PlaceKind.BAKERY: (ActivityType.EAT, "bakery_lunch"),
}


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _open(world: World, place_id: str, weekday: Weekday) -> tuple[int, int] | None:
    place = world.places.get(place_id)
    if place is None or weekday.number not in place.hours.days:
        return None
    if place.hours.open_range is None:
        return (0, 24 * 60 - 1)
    start, end = place.hours.open_range
    return (start, end) if start < end else (start, 24 * 60 - 1)


def day_options(
    world: World, config: GameConfig, agent: Agent, others: list[Agent], day_index: int
) -> dict[str, DayOption]:
    weekday = Weekday.from_index(day_index)
    items = config.actions.items
    options: dict[str, DayOption] = {}

    def add(option: DayOption) -> None:
        options[option.id] = option

    def place_option(
        oid: str,
        place_id: str,
        label: str,
        short: str,
        activity: ActivityType,
        recipe: str,
        minutes: int,
        window: tuple[int, int] | None = None,
    ) -> None:
        hours = _open(world, place_id, weekday)
        if hours is None:
            return
        if window is not None:
            hours = (max(hours[0], window[0]), min(hours[1], window[1]))
            if hours[1] - hours[0] < 30:
                return
        name = world.places[place_id].name
        add(
            DayOption(
                oid,
                f"{label} ({name}, {_hhmm(hours[0])}-{_hhmm(hours[1])})",
                short,
                place_id,
                activity,
                recipe,
                minutes,
                hours,
            )
        )

    work = agent.profile.work
    shift = work.schedule.get(weekday) if work is not None else None
    if shift is not None and work is not None:
        hours = (shift[1] - shift[0]) / 60
        pay = agent.profile.wage * hours
        add(
            DayOption(
                "work",
                f"aller travailler à {world.places[work.place].name} de "
                f"{_hhmm(shift[0])} à {_hhmm(shift[1])} ({pay:.0f} € pour la journée)",
                "travail",
                work.place,
                ActivityType.WORK,
                "",
                0,
                shift,
            )
        )
    add(
        DayOption(
            "sleep_in",
            "faire la grasse matinée (2 heures de plus au lit)",
            "grasse matinée",
            None,
            ActivityType.SLEEP,
            "sleep",
            120,
            (0, 12 * 60),
        )
    )
    home_label = (
        "rester chez soi : télé, sieste, rien faire"
        if not agent.homeless
        else "traîner au parc, sans rien faire"
    )
    add(
        DayOption(
            "rest",
            home_label,
            "temps calme",
            None,
            ActivityType.RELAX,
            "relax_home" if not agent.homeless else "linger",
            90,
            (6 * 60, 23 * 60),
        )
    )
    if not agent.homeless:
        add(
            DayOption(
                "lunch_home",
                "déjeuner chez soi (ce qu'il y a dans le frigo)",
                "déjeuner à la maison",
                None,
                ActivityType.EAT,
                "home_meal",
                50,
                (11 * 60 + 30, 14 * 60 + 30),
            )
        )
    place_option(
        "lunch_cafe",
        "cafe",
        f"déjeuner, plat du jour {items['meal'].price:.0f} €",
        "déjeuner au café",
        ActivityType.EAT,
        "cafe_lunch",
        50,
        (11 * 60 + 30, 14 * 60 + 30),
    )
    place_option(
        "lunch_bakery",
        "boulangerie",
        f"un sandwich, {items['bread'].price:.2f} €",
        "sandwich à la boulangerie",
        ActivityType.EAT,
        "bakery_lunch",
        35,
        (11 * 60, 13 * 60),
    )
    if not agent.homeless:
        place_option(
            "groceries",
            "supermarche",
            f"faire les courses pour remplir le frigo ({items['groceries'].price:.0f} €)",
            "courses",
            ActivityType.SHOP,
            "shopping",
            50,
        )
    place_option(
        "cafe",
        "cafe",
        f"prendre un café et traîner ({items['coffee'].price:.2f} €)",
        "pause café",
        ActivityType.LEISURE,
        "cafe_coffee",
        60,
    )
    place_option(
        "bar",
        "bar",
        f"boire un verre (bière {items['beer'].price:.2f} €, cocktail "
        f"{items['cocktail'].price:.0f} €), voir du monde",
        "un verre au bar",
        ActivityType.LEISURE,
        "bar_evening",
        90,
    )
    place_option(
        "casino",
        "casino",
        "jouer au casino : machines à sous et roulette, on peut gagner gros… ou tout perdre",
        "casino",
        ActivityType.LEISURE,
        "casino",
        120,
    )
    place_option(
        "park",
        "parc",
        "se promener au parc (gratuit)",
        "promenade au parc",
        ActivityType.LEISURE,
        "park_walk",
        75,
        (7 * 60, 21 * 60),
    )
    place_option(
        "gym",
        "salle_de_sport",
        "faire du sport (gratuit)",
        "séance de sport",
        ActivityType.LEISURE,
        "gym_session",
        75,
    )
    if work is None and agent.profile.age < 64:
        add(
            DayOption(
                "job_search",
                "chercher un emploi (annonces, candidatures)",
                "cherche un emploi",
                None,
                ActivityType.RELAX,
                "job_search",
                60,
                (8 * 60, 19 * 60),
            )
        )
    if agent.money < 40 or agent.homeless:
        place_option(
            "beg",
            "parc",
            "faire la manche",
            "fait la manche",
            ActivityType.LEISURE,
            "beg",
            90,
            (8 * 60, 20 * 60),
        )
    if agent.money < 15 and "supermarche" not in agent.banned:
        place_option(
            "steal_food",
            "supermarche",
            "voler à manger (risque d'être vu, honte, interdit d'entrée)",
            "vole à manger",
            ActivityType.SHOP,
            "steal_food",
            40,
        )
    # Aller voir quelqu'un qu'on connaît, là où il travaille (comme client).
    for other in others:
        work_other = other.profile.work
        if other is agent or work_other is None:
            continue
        other_shift = work_other.schedule.get(weekday)
        place = world.places.get(work_other.place)
        if other_shift is None or place is None or place.kind not in SEE_RECIPES:
            continue
        activity, recipe = SEE_RECIPES[place.kind]
        place_option(
            f"see_{other.id}",
            place.id,
            f"aller voir {other.name} ({other.profile.job.lower()}, au travail de "
            f"{_hhmm(other_shift[0])} à {_hhmm(other_shift[1])})",
            f"voir {other.first_name}",
            activity,
            recipe,
            60,
            other_shift,
        )
    return options


def goods_options(
    world: World, config: GameConfig, agent: Agent, day_index: int
) -> dict[str, DayOption]:
    """Les biens à s'offrir, chacun dans le magasin qui le vend."""
    weekday = Weekday.from_index(day_index)
    items = config.actions.items
    sellers: dict[str, str] = {}
    for furniture in world.furniture.values():
        for sold in furniture.sells:
            if furniture.place_id is not None:
                sellers.setdefault(sold, furniture.place_id)
    goods: dict[str, DayOption] = {}
    for item_id, item in items.items():
        if not item.durable or item_id in agent.possessions or item_id not in sellers:
            continue
        place_id = sellers[item_id]
        hours = _open(world, place_id, weekday)
        if hours is None:
            continue
        name = world.places[place_id].name
        goods[item_id] = DayOption(
            item_id,
            f"{item.label}, {item.price:.0f} € ({name}, {_hhmm(hours[0])}-{_hhmm(hours[1])})",
            f"s'acheter : {item.label}",
            place_id,
            ActivityType.SHOP,
            f"buy_{item_id}",
            60,
            hours,
        )
    return goods
