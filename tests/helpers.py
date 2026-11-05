"""Petits outils partagés par les tests de simulation."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.simulation import Simulation


def run_until(sim: Simulation, condition: Callable[[], bool], *, max_minutes: float) -> bool:
    """Avance tick par tick jusqu'à `condition()` (True) ou la limite de temps (False)."""
    for _ in range(round(max_minutes * sim.clock.ticks_per_minute)):
        if condition():
            return True
        sim.tick()
    return condition()


def run_to(sim: Simulation, day: int, hour: float) -> None:
    """Avance jusqu'au jour `day` (0 = lundi) à l'heure `hour` (12.5 = 12:30)."""
    target = round((day * 24 * 60 + hour * 60) * sim.clock.ticks_per_minute)
    sim.run_ticks(max(0, target - sim.clock.tick))


def events_of(sim: Simulation, kind: EventKind, agent_id: str | None = None) -> list[Event]:
    return [
        e for e in sim.events if e.kind is kind and (agent_id is None or e.agent_id == agent_id)
    ]


def step_started(sim: Simulation, agent_id: str, verb: str) -> Callable[[], bool]:
    """Condition : l'habitant a commencé une étape de ce verbe (à partir de maintenant).

    On s'abonne au journal plutôt que de le relire à chaque tick : relire
    50 000 événements 8 640 fois par jour simulé, c'est le genre de test qui
    met dix minutes à passer.
    """
    seen: list[Event] = []

    def listener(event: Event) -> None:
        is_step = event.kind is EventKind.STEP_STARTED and event.agent_id == agent_id
        if is_step and event.data.get("verb") == verb:
            seen.append(event)

    sim.events.subscribe(listener)
    return lambda: bool(seen)
