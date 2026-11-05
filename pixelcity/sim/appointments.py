"""Les rendez-vous : « on se retrouve demain au café vers 17 h 30 ? »

Le LLM peut faire dire aux habitants qu'ils se reverront ; c'est la
simulation qui vérifie que c'est POSSIBLE et qui l'inscrit dans leurs plans :
- seulement le LENDEMAIN : les plans sont faits à minuit, un rendez-vous
  pour aujourd'hui demanderait de tout replanifier ;
- entre 14:00 et 18:00, sur une heure, dans un lieu de détente ouvert ;
- hors des heures de travail des deux (avec 30 min de battement), et sans
  chevaucher un autre de leurs rendez-vous.
Si l'heure proposée ne va pas, on prend le créneau possible le plus proche ;
s'il n'y en a aucun, pas de rendez-vous (et les répliques restent des mots).

Le jour venu : si les deux sont sur place, ils discutent (rendez-vous tenu).
Si l'un ne vient pas, l'autre s'en souvient, et l'affinité en pâtit.
"""

from __future__ import annotations

from dataclasses import dataclass

from pixelcity.config.schemas import AgentModel
from pixelcity.sim.types import MINUTES_PER_DAY, PlaceKind, Weekday
from pixelcity.world.place import Place

MEET_PLACES = (PlaceKind.CAFE, PlaceKind.PARK, PlaceKind.GYM)
EARLIEST, LATEST = 14 * 60, 18 * 60  # début du rendez-vous
DURATION = 60
STEP = 30
WORK_MARGIN = 30  # avant le travail
AFTER_WORK_MARGIN = 150  # après : rentrer, déjeuner, la sieste du boulanger...
DEFAULT_START = 17 * 60 + 30


@dataclass(slots=True, eq=False)
class Appointment:
    uid: int
    a: str
    b: str
    place_id: str
    day_index: int
    start: int  # minute du jour
    names: dict[str, str]  # id → prénom (pour l'étiquette du plan de l'autre)
    kept: bool = False
    closed: bool = False

    @property
    def end(self) -> int:
        return self.start + DURATION

    def absolute_start(self) -> int:
        return self.day_index * MINUTES_PER_DAY + self.start

    def absolute_end(self) -> int:
        return self.absolute_start() + DURATION

    def other(self, agent_id: str) -> str:
        return self.b if agent_id == self.a else self.a

    def label_for(self, agent_id: str) -> str:
        return f"rendez-vous avec {self.names[self.other(agent_id)]}"

    def involves(self, agent_id: str) -> bool:
        return agent_id in (self.a, self.b)


def parse_hour(text: str | None) -> int | None:
    if not text:
        return None
    try:
        hours, _, minutes = text.strip().partition(":")
        value = int(hours) * 60 + int(minutes or 0)
    except ValueError:
        return None
    return value if 0 <= value < MINUTES_PER_DAY else None


def _busy(profile: AgentModel, weekday: Weekday) -> tuple[int, int] | None:
    if profile.work is None:
        return None
    return profile.work.schedule.get(weekday)


class Appointments:
    def __init__(self) -> None:
        self.items: list[Appointment] = []
        self._next_uid = 1

    def for_agent(self, agent_id: str, day_index: int) -> list[Appointment]:
        return sorted(
            (ap for ap in self.items if ap.day_index == day_index and ap.involves(agent_id)),
            key=lambda ap: ap.start,
        )

    def between(self, a: str, b: str) -> Appointment | None:
        return next((ap for ap in self.items if not ap.closed and {ap.a, ap.b} == {a, b}), None)

    def active(self, now_absolute: int) -> list[Appointment]:
        return [
            ap
            for ap in self.items
            if not ap.closed and ap.absolute_start() <= now_absolute < ap.absolute_end()
        ]

    def overdue(self, now_absolute: int) -> list[Appointment]:
        return [ap for ap in self.items if not ap.closed and now_absolute >= ap.absolute_end()]

    def feasible_start(
        self,
        a: AgentModel,
        b: AgentModel,
        place: Place,
        day_index: int,
        wanted: int | None,
    ) -> int | None:
        weekday = Weekday.from_index(day_index)
        taken = [ap for ap in self.items if ap.day_index == day_index and not ap.closed]
        candidates: list[int] = []
        for start in range(EARLIEST, LATEST + 1, STEP):
            end = start + DURATION
            if not (
                place.hours.is_open(weekday.number, start)
                and place.hours.is_open(weekday.number, end - 1)
            ):
                continue
            clash = False
            for profile in (a, b):
                shift = _busy(profile, weekday)
                if (
                    shift is not None
                    and start < shift[1] + AFTER_WORK_MARGIN
                    and end + WORK_MARGIN > shift[0]
                ):
                    clash = True
                if any(
                    ap.involves(profile.id) and start < ap.end and end > ap.start for ap in taken
                ):
                    clash = True
            if not clash:
                candidates.append(start)
        if not candidates:
            return None
        target = wanted if wanted is not None else DEFAULT_START
        return min(candidates, key=lambda s: (abs(s - target), s))

    def add(
        self, a: AgentModel, b: AgentModel, place_id: str, day_index: int, start: int
    ) -> Appointment:
        appointment = Appointment(
            self._next_uid,
            a.id,
            b.id,
            place_id,
            day_index,
            start,
            {a.id: a.name.split()[0], b.id: b.name.split()[0]},
        )
        self._next_uid += 1
        self.items.append(appointment)
        return appointment
