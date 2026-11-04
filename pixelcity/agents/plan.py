"""Plan de journée : une suite de blocs « lieu + activité » couvrant 24 heures.

Les heures des blocs sont des MINUTES ABSOLUES (depuis le début de la
simulation), pas des heures du jour : un bloc ne « passe » donc jamais minuit
par accident, et comparer deux instants est une simple comparaison d'entiers.

À l'étape 2, le LLM produira ces mêmes objets : la routine qui les exécute
ne saura pas (et n'aura pas à savoir) qui les a écrits.
"""

from __future__ import annotations

from dataclasses import dataclass

from pixelcity.sim.clock import format_absolute_minute
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType


@dataclass(frozen=True, slots=True)
class PlanBlock:
    start: int
    end: int
    activity: ActivityType
    place_id: str
    label: str
    # Engagement à l'heure (travail) : l'agent part en avance pour être à
    # l'heure. Les autres blocs commencent quand on arrive.
    punctual: bool = False

    @property
    def duration(self) -> int:
        return self.end - self.start

    def contains(self, minute: int) -> bool:
        return self.start <= minute < self.end

    def describe(self) -> str:
        """Ex. "Lun 09:00–12:15 travail" (l'heure de fin sans le jour)."""
        end_time = format_absolute_minute(self.end)[4:]
        return f"{format_absolute_minute(self.start)}–{end_time} {self.label}"


@dataclass(frozen=True, slots=True)
class DayPlan:
    day_index: int
    blocks: tuple[PlanBlock, ...]

    @property
    def start(self) -> int:
        return self.day_index * MINUTES_PER_DAY

    @property
    def end(self) -> int:
        return self.start + MINUTES_PER_DAY

    def validation_errors(self) -> list[str]:
        """Liste les incohérences (vide si le plan est valide). Utilisé par les tests."""
        errors: list[str] = []
        if not self.blocks:
            return ["plan vide"]
        if self.blocks[0].start != self.start:
            errors.append("le plan ne commence pas à minuit")
        if self.blocks[-1].end != self.end:
            errors.append("le plan ne finit pas à minuit")
        for previous, block in zip(self.blocks, self.blocks[1:], strict=False):
            if block.start != previous.end:
                errors.append(f"trou ou chevauchement avant « {block.label} »")
        errors.extend(f"bloc vide « {b.label} »" for b in self.blocks if b.duration <= 0)
        return errors


class PlanBuilder:
    """Construit un plan SANS TROU par construction.

    Chaque `add(until, ...)` crée un bloc qui commence là où le précédent
    s'arrête : impossible d'oublier un créneau ou d'en superposer deux.
    C'est l'idée de « rendre les états invalides impossibles à représenter ».
    """

    def __init__(self, day_index: int) -> None:
        self.day_index = day_index
        self._day_start = day_index * MINUTES_PER_DAY
        self._cursor = 0  # minute du jour atteinte par le dernier bloc
        self._blocks: list[PlanBlock] = []

    @property
    def cursor(self) -> int:
        return self._cursor

    def add(
        self,
        until: int,
        activity: ActivityType,
        place_id: str,
        label: str,
        *,
        punctual: bool = False,
    ) -> None:
        """Ajoute un bloc du curseur jusqu'à `until` (minute du jour). Ignoré s'il serait vide."""
        until = min(until, MINUTES_PER_DAY)
        if until <= self._cursor:
            return
        start = self._day_start + self._cursor
        end = self._day_start + until
        last = self._blocks[-1] if self._blocks else None
        if last and (last.activity, last.place_id, last.label) == (activity, place_id, label):
            # Deux blocs identiques consécutifs : on les fusionne.
            self._blocks[-1] = PlanBlock(last.start, end, activity, place_id, label, punctual)
        else:
            self._blocks.append(PlanBlock(start, end, activity, place_id, label, punctual))
        self._cursor = until

    def build(self) -> DayPlan:
        if self._cursor != MINUTES_PER_DAY:
            raise ValueError("le plan doit couvrir toute la journée")
        return DayPlan(self.day_index, tuple(self._blocks))
