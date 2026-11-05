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
    BLADDER = "bladder"
    FUN = "fun"

    @property
    def label(self) -> str:
        return _NEED_LABELS[self]


_NEED_LABELS: dict[NeedKind, str] = {
    NeedKind.HUNGER: "Faim",
    NeedKind.ENERGY: "Énergie",
    NeedKind.HYGIENE: "Hygiène",
    NeedKind.BLADDER: "Vessie",
    NeedKind.FUN: "Loisir",
}


class Facing(StrEnum):
    """Direction du regard d'un personnage (les sprites ont 4 orientations)."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    @property
    def delta(self) -> tuple[int, int]:
        return _FACING_DELTAS[self]

    @classmethod
    def from_delta(cls, dx: int, dy: int) -> Facing:
        if abs(dx) >= abs(dy) and dx != 0:
            return cls.RIGHT if dx > 0 else cls.LEFT
        return cls.DOWN if dy >= 0 else cls.UP


_FACING_DELTAS: dict[Facing, tuple[int, int]] = {
    Facing.UP: (0, -1),
    Facing.DOWN: (0, 1),
    Facing.LEFT: (-1, 0),
    Facing.RIGHT: (1, 0),
}


class Pose(StrEnum):
    """Posture du personnage : c'est ce qui choisit le sprite à l'écran."""

    STAND = "stand"
    WALK = "walk"
    SIT = "sit"
    LIE = "lie"  # couché dans un lit : le rendu dessine la tête sur l'oreiller
    RUN = "run"  # sur un tapis de course : animation de marche sur place
    HIDDEN = "hidden"  # douche, toilettes : on ne montre pas le personnage


class Anim(StrEnum):
    """Ce que fait le personnage dans sa posture."""

    IDLE = "idle"
    INTERACT = "interact"  # manipule un objet (cuisine, pétrit, range...)
    READ = "read"
    EAT = "eat"
    TALK = "talk"


class ActivityType(StrEnum):
    """Ce qu'un agent peut faire dans un lieu."""

    SLEEP = "sleep"
    EAT = "eat"
    HYGIENE = "hygiene"
    TOILET = "toilet"
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
    ActivityType.TOILET: "aller aux toilettes",
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
    # Étape 6 ter : plus de tentations en ville.
    CASINO = "casino"
    BAR = "bar"
    BOUTIQUE = "boutique"
    ELECTRONICS = "electronics"

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
