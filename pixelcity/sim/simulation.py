"""La simulation : l'unique point d'entrée qui fait avancer le monde.

    sim = Simulation(load_config())
    sim.tick()          # avance de 10 secondes simulées
    sim.run_days(7)     # une semaine, aussi vite que possible

Règles d'architecture :
- AUCUN import de pygame dans ce module ni dans ceux qu'il importe ;
- le monde n'est modifié QUE pendant `tick()`. Les demandes extérieures
  (mode Dieu à l'étape 5, réponses du LLM à l'étape 2) passent par
  `apply(commande)` et sont exécutées au début du tick suivant. Ainsi, tout
  changement a lieu à un instant précis et reproductible (patron Commande).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Protocol

from pixelcity.agents.agent import Agent, AgentState
from pixelcity.agents.needs import Needs
from pixelcity.agents.planner import Planner, RuleBasedPlanner
from pixelcity.agents.routine import RoutineContext, update_agent
from pixelcity.config.loader import GameConfig
from pixelcity.config.schemas import AgentModel
from pixelcity.resources import resource_path
from pixelcity.sim.clock import SimClock
from pixelcity.sim.events import Event, EventKind, EventLog
from pixelcity.sim.rng import RngRegistry
from pixelcity.sim.types import ActivityType
from pixelcity.world.world import World, load_world


class Command(Protocol):
    """Une modification du monde demandée de l'extérieur, appliquée au tick suivant."""

    def execute(self, sim: Simulation) -> None: ...


class Simulation:
    def __init__(
        self,
        config: GameConfig,
        *,
        seed: int | None = None,
        map_path: Path | None = None,
        planner: Planner | None = None,
        max_events: int | None = 50_000,
    ) -> None:
        self.config = config
        self.seed = config.settings.seed if seed is None else seed
        self.clock = SimClock(config.settings.time.tick_seconds)
        self.rng = RngRegistry(self.seed)
        self.events = EventLog(max_events)
        self.world: World = load_world(
            map_path or resource_path("assets", "maps", config.city.map),
            config.city,
            config.settings,
        )
        self.planner: Planner = planner or RuleBasedPlanner()
        # Dict ordonné comme agents.yaml : l'ordre de mise à jour des agents
        # est donc fixe d'un lancement à l'autre (déterminisme).
        self.agents: dict[str, Agent] = {
            model.id: self._create_agent(model) for model in config.agents.agents
        }
        self._commands: deque[Command] = deque()
        self._ctx = RoutineContext.create(
            self.world, self.clock, config.settings, self.events, self.planner, self.rng
        )
        self.events.emit(
            Event(0, EventKind.SIM_STARTED, data={"seed": self.seed, "agents": len(self.agents)})
        )

    # ------------------------------------------------------------------ #
    # Faire avancer le temps
    # ------------------------------------------------------------------ #
    def tick(self) -> None:
        while self._commands:
            self._commands.popleft().execute(self)
        clock = self.clock
        if clock.is_start_of_day:
            self.events.emit(
                Event(
                    clock.tick,
                    EventKind.DAY_STARTED,
                    data={"day": clock.day_index + 1, "weekday": clock.weekday.value},
                )
            )
        for agent in self.agents.values():
            update_agent(agent, self._ctx)
        clock.advance()

    def run_ticks(self, count: int) -> None:
        for _ in range(count):
            self.tick()

    def run_days(self, days: float) -> None:
        self.run_ticks(round(days * self.clock.ticks_per_day))

    def apply(self, command: Command) -> None:
        """Programme une commande : elle sera exécutée au début du prochain tick."""
        self._commands.append(command)

    # ------------------------------------------------------------------ #
    # Lecture (pour le rendu, l'interface, le mode headless)
    # ------------------------------------------------------------------ #
    def agent_names(self) -> dict[str, str]:
        return {agent_id: agent.name for agent_id, agent in self.agents.items()}

    def place_names(self) -> dict[str, str]:
        return {place_id: place.name for place_id, place in self.world.places.items()}

    def is_visible(self, agent: Agent) -> bool:
        """Visible sur la carte : dehors, ou dans un lieu extérieur (parc)."""
        if agent.place_id is None:
            return True
        return self.world.places[agent.place_id].outdoor

    # ------------------------------------------------------------------ #
    # Création
    # ------------------------------------------------------------------ #
    def _create_agent(self, model: AgentModel) -> Agent:
        """Chaque habitant commence la simulation endormi chez lui, un lundi à minuit."""
        home = self.world.places[model.home]
        tile = home.entrances[0]
        position = (float(tile[0]), float(tile[1]))
        needs = Needs.initial(self.config.settings.needs, self.rng.stream(f"init:{model.id}"))
        agent = Agent(
            profile=model,
            needs=needs,
            tile=tile,
            pos=position,
            prev_pos=position,
            state=AgentState.ACTIVE,
            place_id=home.id,
            activity=ActivityType.SLEEP,
            activity_label="sommeil",
        )
        home.occupants[agent.id] = None
        return agent
