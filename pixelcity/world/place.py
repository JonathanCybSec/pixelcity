"""Les lieux de la ville : bâtiments ET espaces extérieurs.

On modélise des « lieux » et pas seulement des bâtiments : le parc n'a pas de
murs, comme le marché ou le stade à l'étape 4.

Chaque lieu « annonce » les activités qu'il permet et leur effet sur les
besoins. C'est le principe des « smart objects » des Sims (2000) :
l'intelligence est dans les objets, pas dans les personnages. L'agent n'a
jamais « si faim alors boulangerie » codé en dur ; il cherche un lieu qui
annonce `eat`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pixelcity.sim.types import ActivityType, NeedKind, PlaceKind, TilePos, format_hhmm


@dataclass(frozen=True, slots=True)
class TileRect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, pos: TilePos) -> bool:
        px, py = pos
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height

    def on_border(self, pos: TilePos) -> bool:
        px, py = pos
        return self.contains(pos) and (
            px in (self.x, self.x + self.width - 1) or py in (self.y, self.y + self.height - 1)
        )

    def tiles(self) -> list[TilePos]:
        return [
            (x, y)
            for y in range(self.y, self.y + self.height)
            for x in range(self.x, self.x + self.width)
        ]


@dataclass(frozen=True, slots=True)
class OpeningHours:
    # None = ouvert toute la journée (les jours indiqués).
    open_range: tuple[int, int] | None
    days: frozenset[int]  # 0 = lundi ... 6 = dimanche

    def is_open(self, weekday: int, minute_of_day: int) -> bool:
        if self.open_range is None:
            return weekday in self.days
        start, end = self.open_range
        if start < end:
            return weekday in self.days and start <= minute_of_day < end
        # Plage qui passe minuit (ex. un bar 18:00-02:00). Piège classique :
        # le test naïf `start <= t < end` est toujours faux ici. Et la partie
        # après minuit appartient à la VEILLE : le samedi à 01:00, le bar est
        # ouvert si le VENDREDI est un jour d'ouverture.
        if minute_of_day >= start:
            return weekday in self.days
        if minute_of_day < end:
            return (weekday - 1) % 7 in self.days
        return False

    def describe(self) -> str:
        days = "tous les jours" if len(self.days) == 7 else f"{len(self.days)} j/7"
        if self.open_range is None:
            return f"24 h/24, {days}"
        start, end = self.open_range
        return f"{format_hhmm(start)}-{format_hhmm(end)}, {days}"


class Access(StrEnum):
    """Réponse d'un lieu à « puis-je faire cette activité ici, maintenant ? »."""

    OK = "ok"
    CLOSED = "closed"
    FULL = "full"
    FORBIDDEN = "forbidden"


@dataclass(slots=True)
class Place:
    id: str
    name: str
    kind: PlaceKind
    capacity: int
    hours: OpeningHours
    activities: frozenset[ActivityType]
    staff_activities: frozenset[ActivityType]
    # Effets par activité, déjà fusionnés : valeurs par défaut + surcharges du lieu.
    effects: dict[ActivityType, dict[NeedKind, float]]
    area: TileRect
    entrances: tuple[TilePos, ...]
    # Lieux extérieurs : cases intérieures où l'on peut flâner.
    spots: tuple[TilePos, ...] = ()
    # Agents présents. Un dict (ordonné) plutôt qu'un set : l'ordre
    # d'itération d'un set de chaînes change d'un lancement à l'autre.
    occupants: dict[str, None] = field(default_factory=dict)

    @property
    def outdoor(self) -> bool:
        return self.kind.is_outdoor

    def offers(self, activity: ActivityType, *, staff: bool = False) -> bool:
        return activity in self.activities or (staff and activity in self.staff_activities)

    def check_access(
        self,
        activity: ActivityType,
        weekday: int,
        minute_of_day: int,
        *,
        resident: bool,
        staff: bool,
        entering: bool,
    ) -> Access:
        if self.kind is PlaceKind.HOME:
            # Chez soi : toujours ouvert, mais seulement pour ceux qui y vivent.
            return Access.OK if resident and activity in self.activities else Access.FORBIDDEN
        if staff and activity in self.staff_activities:
            return Access.OK  # les employés entrent hors des heures d'ouverture
        if activity not in self.activities:
            return Access.FORBIDDEN
        if not self.hours.is_open(weekday, minute_of_day):
            return Access.CLOSED
        if entering and len(self.occupants) >= self.capacity:
            return Access.FULL
        return Access.OK

    def nearest_entrance(self, from_pos: TilePos) -> TilePos:
        """Entrée la plus proche à vol d'oiseau (départage stable par ordre de déclaration)."""
        fx, fy = from_pos
        return min(self.entrances, key=lambda e: abs(e[0] - fx) + abs(e[1] - fy))
