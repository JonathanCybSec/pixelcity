"""Le contexte partagé d'un tick : tout ce dont la routine et l'exécuteur ont besoin.

Plutôt que de passer dix arguments à chaque fonction (le monde, l'horloge, le
journal, les comptoirs...), on les regroupe dans un seul objet. C'est aussi
un point unique pour les conversions d'unités (minutes ↔ ticks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pixelcity.config.loader import GameConfig
from pixelcity.sim.clock import SimClock
from pixelcity.sim.events import Event, EventKind, EventLog, EventValue
from pixelcity.sim.relations import Relations
from pixelcity.sim.rng import RngRegistry
from pixelcity.sim.service import ServiceDesk
from pixelcity.world.world import World

if TYPE_CHECKING:
    from pixelcity.sim.conversation import Conversations

if TYPE_CHECKING:  # uniquement pour mypy : évite un import circulaire à l'exécution
    from pixelcity.agents.agent import Agent


@dataclass(slots=True)
class SimContext:
    config: GameConfig
    world: World
    clock: SimClock
    events: EventLog
    rngs: RngRegistry
    agents: dict[str, Agent]
    desks: dict[str, ServiceDesk]  # uid du meuble → comptoir
    relations: Relations
    walk_tiles_per_tick: float
    hours_per_tick: float
    minutes_per_tick: float
    conversations: Conversations

    @property
    def now(self) -> int:
        """Minute absolue depuis le début de la simulation."""
        return self.clock.total_minutes

    @property
    def now_exact(self) -> float:
        """Minute absolue avec les secondes (les étapes durent parfois 1,5 min)."""
        return self.clock.total_seconds / 60

    def emit(
        self,
        kind: EventKind,
        agent_id: str | None = None,
        place_id: str | None = None,
        **data: EventValue,
    ) -> None:
        self.events.emit(Event(self.clock.tick, kind, agent_id, place_id, data))

    def desks_in(self, place_id: str) -> list[ServiceDesk]:
        return [desk for desk in self.desks.values() if desk.place_id == place_id]
