"""Types de base partagés par tout le noyau.

Ce module ne dépend d'aucun autre module du projet : c'est la « fondation »
sur laquelle s'appuient `world/`, `agents/` et `config/`, ce qui garantit
qu'il ne participera jamais à un import circulaire.
"""

from __future__ import annotations

from enum import StrEnum

# Une position sur la grille, en tuiles : (x, y), origine en haut à gauche.
# Un tuple plutôt qu'une classe : hashable (clé de dictionnaire, cache A*),
# immuable, et très rapide à comparer.
type TilePos = tuple[int, int]

MINUTES_PER_DAY = 24 * 60
SECONDS_PER_DAY = 24 * 60 * 60


class NeedKind(StrEnum):
    """Les besoins de type Sims. Une jauge à 100 = besoin parfaitement satisfait."""

    HUNGER = "hunger"
    ENERGY = "energy"
    HYGIENE = "hygiene"
    FUN = "fun"

    @property
    def label(self) -> str:
        return _NEED_LABELS[self]


_NEED_LABELS: dict[NeedKind, str] = {
    NeedKind.HUNGER: "Faim",
    NeedKind.ENERGY: "Énergie",
    NeedKind.HYGIENE: "Hygiène",
    NeedKind.FUN: "Loisir",
}


class ActivityType(StrEnum):
    """Ce qu'un agent peut faire dans un lieu."""

    SLEEP = "sleep"
    EAT = "eat"
    HYGIENE = "hygiene"
    WORK = "work"
    LEISURE = "leisure"
    SHOP = "shop"
    RELAX = "relax"

    @property
    def label(self) -> str:
        return _ACTIVITY_LABELS[self]


_ACTIVITY_LABELS: dict[ActivityType, str] = {
    ActivityType.SLEEP: "dormir",
    ActivityType.EAT: "manger",
    ActivityType.HYGIENE: "se laver",
    ActivityType.WORK: "travailler",
    ActivityType.LEISURE: "se divertir",
    ActivityType.SHOP: "faire les courses",
    ActivityType.RELAX: "se reposer",
}


class PlaceKind(StrEnum):
    """Catégorie d'un lieu. La ville complète (étape 4) en ajoutera beaucoup."""

    HOME = "home"
    BAKERY = "bakery"
    CAFE = "cafe"
    OFFICE = "office"
    SCHOOL = "school"
    SUPERMARKET = "supermarket"
    GYM = "gym"
    PARK = "park"

    @property
    def is_outdoor(self) -> bool:
        """Un lieu extérieur n'a pas de murs : l'agent y reste visible et s'y promène."""
        return self in _OUTDOOR_KINDS


_OUTDOOR_KINDS = frozenset({PlaceKind.PARK})


class Weekday(StrEnum):
    """Jours de la semaine, tels qu'on les écrit dans les fichiers YAML."""

    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"

    @property
    def number(self) -> int:
        """0 = lundi ... 6 = dimanche (même convention que `datetime.weekday()`).

        Attention au nom : une `StrEnum` hérite de toutes les méthodes de `str`.
        Appeler cette propriété `index` écraserait `str.index()` en silence
        (mypy --strict l'a signalé, c'est pour ça qu'elle s'appelle `number`).
        """
        return _WEEKDAY_ORDER.index(self)

    @classmethod
    def from_index(cls, index: int) -> Weekday:
        return _WEEKDAY_ORDER[index % 7]

    @property
    def label(self) -> str:
        return _WEEKDAY_LABELS[self.number]

    @property
    def short_label(self) -> str:
        return _WEEKDAY_LABELS[self.number][:3]


_WEEKDAY_ORDER: tuple[Weekday, ...] = (
    Weekday.MON,
    Weekday.TUE,
    Weekday.WED,
    Weekday.THU,
    Weekday.FRI,
    Weekday.SAT,
    Weekday.SUN,
)
_WEEKDAY_LABELS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")


def parse_hhmm(text: str) -> int:
    """Convertit "07:30" en minutes depuis minuit (450).

    "24:00" est accepté et vaut 1440 : pratique pour écrire « jusqu'à minuit ».
    """
    try:
        hours_text, minutes_text = text.strip().split(":")
        hours, minutes = int(hours_text), int(minutes_text)
    except ValueError as exc:
        raise ValueError(f"heure invalide {text!r}, format attendu HH:MM") from exc
    if not (0 <= minutes < 60) or not (0 <= hours <= 24) or (hours == 24 and minutes != 0):
        raise ValueError(f"heure hors limites {text!r}")
    return hours * 60 + minutes


def format_hhmm(minute_of_day: int) -> str:
    """Convertit des minutes depuis minuit en "HH:MM" (1440 s'affiche "24:00")."""
    hours, minutes = divmod(minute_of_day, 60)
    return f"{hours:02d}:{minutes:02d}"
