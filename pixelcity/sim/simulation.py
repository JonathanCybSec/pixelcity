"""La simulation : l'unique point d'entrée qui fait avancer le monde.

    sim = Simulation(load_config())
    sim.tick()          # avance de 10 secondes simulées
    sim.run_days(7)     # une semaine, aussi vite que possible

Règles d'architecture :
- AUCUN import de pygame dans ce module ni dans ceux qu'il importe ;
- le monde n'est modifié QUE pendant `tick()`. Les demandes extérieures
  (mode Dieu, réponses des LLM à l'étape 3) passent par `apply(commande)` et
  sont exécutées au début du tick suivant. Ainsi, tout changement a lieu à
  un instant précis et reproductible (patron Commande).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Protocol

from pixelcity.agents.agent import Agent
from pixelcity.agents.movement import place_at
from pixelcity.agents.needs import Needs
from pixelcity.agents.planner import Planner, RuleBasedPlanner
from pixelcity.agents.routine import update_agent
from pixelcity.config.loader import GameConfig
from pixelcity.config.schemas import AgentModel
from pixelcity.resources import assets_dir
from pixelcity.sim.clock import SimClock
from pixelcity.sim.context import SimContext
from pixelcity.sim.events import EventKind, EventLog
from pixelcity.sim.relations import Relations
from pixelcity.sim.rng import RngRegistry
from pixelcity.sim.service import build_desks, update_desks
from pixelcity.sim.types import Pose
from pixelcity.world.catalog import load_catalog
from pixelcity.world.world import World, load_world


class Command(Protocol):
    """Une modification du monde demandée de l'extérieur, appliquée au tick suivant."""

    def execute(self, sim: Simulation) -> None: ...


def default_asset_roots() -> tuple[Path, ...]:
    """Les meubles de pixel-agents, puis les nôtres (qui l'emportent en cas de doublon)."""
    root = assets_dir()
    return (root / "pixel_agents", root / "pixelcity")


class Simulation:
    def __init__(
        self,
        config: GameConfig,
        *,
        seed: int | None = None,
        map_path: Path | None = None,
        planner: Planner | None = None,
        max_events: int | None = 50_000,
        asset_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self.config = config
        self.seed = config.settings.seed if seed is None else seed
        self.clock = SimClock(config.settings.time.tick_seconds)
        self.rng = RngRegistry(self.seed)
        self.events = EventLog(max_events)
        catalog = load_catalog(*(asset_roots or default_asset_roots()))
        self.world: World = load_world(
            map_path or assets_dir() / "maps" / config.city.map,
            config.city,
            config.objects,
            catalog,
        )
        self.planner: Planner = planner or RuleBasedPlanner()
        # Dict ordonné comme agents.yaml : l'ordre de mise à jour des agents
        # est donc fixe d'un lancement à l'autre (déterminisme).
        self.agents: dict[str, Agent] = {
            model.id: self._create_agent(model) for model in config.agents.agents
        }
        self.desks = build_desks(self.world.furniture)
        self.relations = Relations()
        minutes_per_tick = self.clock.tick_seconds / 60
        self.ctx = SimContext(
            config=config,
            world=self.world,
            clock=self.clock,
            events=self.events,
            rngs=self.rng,
            agents=self.agents,
            desks=self.desks,
            relations=self.relations,
            walk_tiles_per_tick=config.settings.walk_speed_tiles_per_minute * minutes_per_tick,
            hours_per_tick=self.clock.hours_per_tick,
            minutes_per_tick=minutes_per_tick,
        )
        self._commands: deque[Command] = deque()
        self.ctx.emit(EventKind.SIM_STARTED, seed=self.seed, agents=len(self.agents))

    # ------------------------------------------------------------------ #
    # Faire avancer le temps
    # ------------------------------------------------------------------ #
    def tick(self) -> None:
        while self._commands:
            self._commands.popleft().execute(self)
        clock = self.clock
        if clock.is_start_of_day:
            self.ctx.emit(
                EventKind.DAY_STARTED, day=clock.day_index + 1, weekday=clock.weekday.value
            )
        for agent in self.agents.values():
            update_agent(agent, self.ctx, self.planner)
        update_desks(self.ctx)
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
        """Visible à l'écran : on voit l'intérieur des maisons, sauf sous la douche."""
        return agent.pose is not Pose.HIDDEN

    # ------------------------------------------------------------------ #
    # Création
    # ------------------------------------------------------------------ #
    def _create_agent(self, model: AgentModel) -> Agent:
        """Chaque habitant commence la simulation chez lui, un lundi à minuit."""
        home = self.world.places[model.home]
        bed = next(iter(home.spots_for("sleep")), None)
        tile = bed.tile if bed is not None else home.entrances[0]
        needs = Needs.initial(self.config.settings.needs, self.rng.stream(f"init:{model.id}"))
        agent = Agent(
            profile=model,
            needs=needs,
            tile=tile,
            pos=(float(tile[0]), float(tile[1])),
            prev_pos=(float(tile[0]), float(tile[1])),
            place_id=home.id,
        )
        place_at(agent, tile)
        home.occupants[agent.id] = None
        return agent
