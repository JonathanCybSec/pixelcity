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
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from pixelcity.agents.agent import Agent
from pixelcity.agents.movement import place_at
from pixelcity.agents.needs import Needs
from pixelcity.agents.planner import Planner, RuleBasedPlanner
from pixelcity.agents.routine import update_agent
from pixelcity.config.loader import GameConfig
from pixelcity.config.schemas import AgentModel
from pixelcity.llm.backends import DialogueBackend, ScriptedBackend
from pixelcity.resources import assets_dir
from pixelcity.sim.appointments import Appointments
from pixelcity.sim.clock import SimClock
from pixelcity.sim.context import SimContext
from pixelcity.sim.conversation import Conversations
from pixelcity.sim.economy import Economy
from pixelcity.sim.events import EventKind, EventLog
from pixelcity.sim.life import Life
from pixelcity.sim.minds import Minds
from pixelcity.sim.relations import Relations
from pixelcity.sim.rng import RngRegistry
from pixelcity.sim.service import build_desks, update_desks
from pixelcity.sim.transit import Transit
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
        dialogue: DialogueBackend | None = None,
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
        self.closed_for_lack_of_staff = self._close_unstaffed_shops()
        self.relations = Relations()
        script = ScriptedBackend(config.dialogues)
        # Par défaut : le script (instantané, reproductible). main.py branche
        # Ollama quand le .env l'active.
        self.conversations = Conversations(dialogue or script, script)
        self.appointments = Appointments()
        self.minds = Minds(dialogue or script)
        self.economy = Economy()
        self.life = Life(dialogue or script)
        self.transit = Transit(self.world, config.settings.transit, self.clock)
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
            conversations=self.conversations,
            appointments=self.appointments,
            economy=self.economy,
            transit=self.transit,
            life=self.life,
        )
        for agent in self.agents.values():
            agent.money = agent.profile.money
            agent.memory.ticks_per_hour = self.clock.ticks_per_minute * 60
        # La mémoire écoute le journal : chaque événement notable devient un souvenir.
        self.events.subscribe(lambda event: self.minds.on_event(self.ctx, event))
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
        self.transit.update(self.ctx)
        update_desks(self.ctx)
        self.conversations.update(self.ctx)
        self.minds.update(self.ctx)
        self.economy.update(self.ctx)
        self.life.update(self.ctx)
        clock.advance()

    def run_ticks(self, count: int) -> None:
        for _ in range(count):
            self.tick()

    def run_days(self, days: float) -> None:
        self.run_ticks(round(days * self.clock.ticks_per_day))

    def close(self) -> None:
        """Arrête proprement le fil de travail du LLM."""
        self.conversations.backend.close()

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
    def _close_unstaffed_shops(self) -> list[str]:
        """Un commerce sans aucun employé dans le scénario reste fermé.

        Avec le studio, on peut créer une ville sans boulanger : la boulangerie
        n'ouvre donc pas, et le planificateur ne promet plus à personne un
        sandwich que nul ne servira. Une caisse automatique suffit à ouvrir.
        """
        employed = {m.work.place for m in self.config.agents.agents if m.work is not None}
        closed: list[str] = []
        for place_id, place in self.world.places.items():
            desks = [desk for desk in self.desks.values() if desk.place_id == place_id]
            if not desks or place_id in employed or any(d.self_service for d in desks):
                continue
            place.hours = replace(place.hours, days=frozenset())
            closed.append(place_id)
        return closed

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
