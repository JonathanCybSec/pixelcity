"""Horloge simulée : le temps de la ville, découplé du temps réel.

Principe clé (« Fix Your Timestep! », Glenn Fiedler, 2004) : la simulation
avance par pas FIXES, les ticks. Ici 1 tick = 10 secondes simulées.

- La vitesse de jeu (x1, x2, x10) ne change JAMAIS la taille du tick : elle
  change le nombre de ticks exécutés par seconde réelle (c'est le travail du
  moteur, dans `engine/app.py`).
- L'horloge ne lit donc jamais `time.time()` : elle ne connaît que son compteur.
  C'est ce qui rend la simulation reproductible et testable en mode headless.

Convention : le tick 0 est un lundi à 00:00.
"""

from __future__ import annotations

from dataclasses import dataclass

from pixelcity.sim.types import MINUTES_PER_DAY, SECONDS_PER_DAY, Weekday, format_hhmm


@dataclass(slots=True)
class SimClock:
    tick_seconds: int = 10
    tick: int = 0

    def __post_init__(self) -> None:
        # Un tick doit diviser exactement la minute ET la journée, sinon les
        # heures « tombent » entre deux ticks et `07:00` n'arrive jamais pile.
        if self.tick_seconds <= 0 or 60 % self.tick_seconds != 0:
            raise ValueError(
                "tick_seconds doit être un diviseur de 60 (1, 2, 5, 10, 15, 20, 30, 60)"
            )

    # ------------------------------------------------------------------ #
    # Avancer
    # ------------------------------------------------------------------ #
    def advance(self, ticks: int = 1) -> None:
        self.tick += ticks

    # ------------------------------------------------------------------ #
    # Lecture du temps
    # ------------------------------------------------------------------ #
    @property
    def ticks_per_day(self) -> int:
        return SECONDS_PER_DAY // self.tick_seconds

    @property
    def ticks_per_minute(self) -> int:
        return 60 // self.tick_seconds

    @property
    def total_seconds(self) -> int:
        return self.tick * self.tick_seconds

    @property
    def total_minutes(self) -> int:
        """Minutes écoulées depuis le début de la simulation (temps « absolu »)."""
        return self.total_seconds // 60

    @property
    def day_index(self) -> int:
        """0 pour le premier jour (un lundi), 1 pour le mardi, etc."""
        return self.total_seconds // SECONDS_PER_DAY

    @property
    def minute_of_day(self) -> int:
        return self.total_minutes % MINUTES_PER_DAY

    @property
    def hour(self) -> int:
        return self.minute_of_day // 60

    @property
    def minute(self) -> int:
        return self.minute_of_day % 60

    @property
    def weekday(self) -> Weekday:
        return Weekday.from_index(self.day_index)

    @property
    def is_start_of_day(self) -> bool:
        return self.tick % self.ticks_per_day == 0

    @property
    def is_start_of_minute(self) -> bool:
        return self.tick % self.ticks_per_minute == 0

    @property
    def hours_per_tick(self) -> float:
        return self.tick_seconds / 3600

    # ------------------------------------------------------------------ #
    # Affichage
    # ------------------------------------------------------------------ #
    def label(self) -> str:
        """Ex. "Lundi 07:42 · jour 1"."""
        return f"{self.weekday.label} {format_hhmm(self.minute_of_day)} · jour {self.day_index + 1}"

    def short_label(self) -> str:
        """Ex. "Lun 07:42", utilisé en tête des lignes du journal."""
        return f"{self.weekday.short_label} {format_hhmm(self.minute_of_day)}"


def format_absolute_minute(absolute_minute: int) -> str:
    """Formate une minute absolue (depuis le début de la simulation) : "Mar 13:05"."""
    day, minute_of_day = divmod(absolute_minute, MINUTES_PER_DAY)
    return f"{Weekday.from_index(day).short_label} {format_hhmm(minute_of_day)}"
