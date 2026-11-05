"""L'interface : état partagé, ordre de dessin, clics.

Ordre de dessin (du fond vers l'avant) :
1. accroches du monde : étiquettes des lieux, marqueur de sélection, bulles ;
2. panneaux en verre : barre du temps, habitants, fiche, journal ;
3. infobulle sous la souris, puis la couche de débogage (F3).

Les panneaux floutent ce qui est déjà à l'écran : ils doivent passer après
le monde ET après les accroches (une bulle sous un panneau apparaît floutée,
comme derrière une vitre).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame

from pixelcity.engine.camera import Camera
from pixelcity.engine.renderer import WorldRenderer
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind
from pixelcity.ui import overlays, panels
from pixelcity.ui.feed import Feed
from pixelcity.ui.glass import Glass
from pixelcity.ui.theme import Fonts, TextCache
from pixelcity.ui.widgets import Avatars, Hits

SLIDE_SPEED = 7.0  # vitesse d'apparition de la fiche (fraction par seconde)
NEED_SMOOTHING = 6.0  # les jauges glissent vers leur valeur au lieu de sauter


@dataclass(frozen=True, slots=True)
class AppStatus:
    paused: bool
    speed_index: int
    speeds: tuple[int, ...]
    fps: float
    ticks_per_second: float


@dataclass(slots=True)
class UiState:
    selected_agent: str | None = None
    selected_place: str | None = None
    follow: bool = False
    journal_mode: str = "all"
    hover_agent: str | None = None
    hover_place: str | None = None
    visible: bool = True
    debug: bool = False
    slide: float = 0.0
    # Sections et panneaux repliés (« menus déroulants ») : on clique leur titre.
    collapsed: set[str] = field(default_factory=lambda: {"sac", "relations"})


@dataclass(slots=True)
class UiFrame:
    """Tout ce dont un panneau a besoin pour se dessiner, pour UNE image."""

    screen: pygame.Surface
    sim: Simulation
    camera: Camera
    renderer: WorldRenderer
    alpha: float
    status: AppStatus
    state: UiState
    texts: TextCache
    glass: Glass
    avatars: Avatars
    feed: Feed
    hits: Hits
    mouse: tuple[int, int]
    smoothed_needs: dict[tuple[str, NeedKind], float] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.screen.get_width()

    @property
    def height(self) -> int:
        return self.screen.get_height()

    def smoothed(self, agent_id: str, need: NeedKind, value: float) -> float:
        return self.smoothed_needs.get((agent_id, need), value)


class Ui:
    def __init__(self, sim: Simulation, renderer: WorldRenderer) -> None:
        self.sim = sim
        self.renderer = renderer
        self.fonts = Fonts()
        self.texts = TextCache(self.fonts)
        self.glass = Glass()
        self.avatars = Avatars(renderer.bank)
        self.feed = Feed(sim)
        self.state = UiState()
        self.hits = Hits()
        self.panel_rects: list[pygame.Rect] = []
        self._smoothed: dict[tuple[str, NeedKind], float] = {}

    # ------------------------------------------------------------------ #
    # Mise à jour (animations)
    # ------------------------------------------------------------------ #
    def update(self, dt: float) -> None:
        state = self.state
        target = 1.0 if (state.selected_agent or state.selected_place) else 0.0
        step = SLIDE_SPEED * dt
        state.slide = (
            min(target, state.slide + step)
            if state.slide < target
            else max(target, state.slide - step)
        )
        k = min(1.0, NEED_SMOOTHING * dt)
        for agent in self.sim.agents.values():
            for need in NeedKind:
                key = (agent.id, need)
                current = self._smoothed.get(key, agent.needs[need])
                self._smoothed[key] = current + (agent.needs[need] - current) * k

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #
    def draw(self, screen: pygame.Surface, camera: Camera, alpha: float, status: AppStatus) -> None:
        self.hits.clear()
        self.panel_rects = []
        frame = UiFrame(
            screen=screen,
            sim=self.sim,
            camera=camera,
            renderer=self.renderer,
            alpha=alpha,
            status=status,
            state=self.state,
            texts=self.texts,
            glass=self.glass,
            avatars=self.avatars,
            feed=self.feed,
            hits=self.hits,
            mouse=pygame.mouse.get_pos(),
            smoothed_needs=self._smoothed,
        )
        overlays.place_labels(frame)
        overlays.selection_marker(frame)
        overlays.speech_bubbles(frame)
        if self.state.visible:
            self.glass.begin_frame(screen)
            self.panel_rects.append(panels.top_bar(frame))
            if screen.get_height() >= 560:
                self.panel_rects.append(panels.cast_panel(frame))
            eased = 1.0 - (1.0 - self.state.slide) ** 3
            if self.state.selected_agent is not None and eased > 0:
                self.panel_rects.append(panels.agent_card(frame, self.state.selected_agent, eased))
            elif self.state.selected_place is not None and eased > 0:
                self.panel_rects.append(panels.place_card(frame, self.state.selected_place, eased))
            if screen.get_width() >= 900:
                self.panel_rects.append(panels.journal_panel(frame))
            if screen.get_width() >= 1100:
                self.panel_rects.append(panels.help_hint(frame))
        if not self.is_over_ui(frame.mouse):  # pas d'infobulle de la ville sous un panneau
            overlays.tooltip(frame)
        if self.state.debug:
            overlays.debug_layer(frame)

    # ------------------------------------------------------------------ #
    # Interactions
    # ------------------------------------------------------------------ #
    def is_over_ui(self, pos: tuple[int, int]) -> bool:
        return any(rect.collidepoint(pos) for rect in self.panel_rects)

    def click(self, pos: tuple[int, int]) -> str | None:
        """Gère un clic sur l'interface. Renvoie l'action (pour l'application) ou None."""
        action = self.hits.at(pos)
        if action is None:
            return None
        state = self.state
        if action.startswith("agent:"):
            self.select_agent(action.removeprefix("agent:"), follow=True)
        elif action == "close":
            self.clear_selection()
        elif action == "follow":
            state.follow = not state.follow
        elif action.startswith("fold:"):
            key = action.removeprefix("fold:")
            state.collapsed.symmetric_difference_update({key})
        elif action.startswith("journal:"):
            state.journal_mode = action.removeprefix("journal:")
        return action

    def select_agent(self, agent_id: str | None, *, follow: bool = False) -> None:
        state = self.state
        if agent_id != state.selected_agent:
            state.slide = 0.0
        state.selected_agent = agent_id
        state.selected_place = None
        state.follow = follow and agent_id is not None
        self.renderer.selected_id = agent_id
        if agent_id is None and state.journal_mode == "agent":
            state.journal_mode = "all"

    def select_place(self, place_id: str | None) -> None:
        state = self.state
        if place_id != state.selected_place:
            state.slide = 0.0
        state.selected_place = place_id
        state.selected_agent = None
        state.follow = False
        self.renderer.selected_id = None

    def clear_selection(self) -> None:
        self.select_agent(None)
        self.state.selected_place = None

    def cycle_agent(self, step: int = 1) -> None:
        ids = list(self.sim.agents)
        if not ids:
            return
        current = self.state.selected_agent
        index = (ids.index(current) + step) % len(ids) if current in ids else 0
        self.select_agent(ids[index], follow=True)
