"""Boucle de jeu : relie le temps réel au temps simulé.

C'est ici, et seulement ici, qu'intervient la vitesse de jeu. Le principe
de l'accumulateur (« Fix Your Timestep! », Glenn Fiedler, 2004) :

    à chaque image :
        accumulateur += temps réel écoulé × ticks par seconde × vitesse
        tant que accumulateur >= 1 :
            simulation.tick()      # pas FIXE de 10 s simulées
            accumulateur -= 1
        dessiner avec alpha = accumulateur (fraction du tick suivant)

- À x30, on exécute simplement 30 fois plus de ticks : chaque tick reste
  identique, donc la simulation se comporte exactement comme à x1.
- `alpha` sert à interpoler les positions entre deux ticks : sans lui, les
  habitants avanceraient par saccades.
- Le plafond `max_ticks_per_frame` évite la « spirale de la mort » : si la
  machine n'arrive plus à suivre, on abandonne le retard (la simulation
  ralentit) au lieu d'accumuler toujours plus de travail (la fenêtre gèle).
"""

from __future__ import annotations

import time

import pygame

from pixelcity.engine.camera import Camera
from pixelcity.engine.input import ActionKind, InputState
from pixelcity.engine.renderer import WorldRenderer
from pixelcity.sim.simulation import Simulation
from pixelcity.ui.ui import AppStatus, Ui

CAMERA_SPEED = 700  # pixels écran par seconde
MAX_FRAME_SECONDS = 0.25  # au-delà (fenêtre déplacée, point d'arrêt...), on plafonne
FOLLOW_HEAD_OFFSET = 12  # la caméra vise le buste, pas les pieds


class GameApp:
    def __init__(self, sim: Simulation) -> None:
        self.sim = sim
        settings = sim.config.settings
        # On n'initialise que ce dont on a besoin : pas de module audio, qui
        # échoue sur les machines sans carte son (serveurs, CI, VM).
        pygame.display.init()
        pygame.font.init()
        window = settings.window
        self.screen = pygame.display.set_mode((window.width, window.height), pygame.RESIZABLE)
        pygame.display.set_caption("PixelCity")
        self.fps = window.fps
        self.frame_clock = pygame.time.Clock()

        self.renderer = WorldRenderer(sim)
        self.camera = Camera.centered(
            self.screen.get_size(), self.renderer.world_size, window.start_zoom
        )
        self.ui = Ui(sim, self.renderer)
        self.input = InputState()

        time_settings = settings.time
        self.speeds = time_settings.speeds
        self.speed_index = 0
        self.paused = False
        self.max_ticks_per_frame = time_settings.max_ticks_per_frame
        self.ticks_per_second_x1 = sim.clock.ticks_per_day / (
            time_settings.real_minutes_per_day * 60
        )
        self.accumulator = 0.0
        self.measured_tps = 0.0
        self.running = True
        self.hover_enabled = True  # désactivé pour les captures (souris fictive en 0,0)
        self._started = time.monotonic()

    # ------------------------------------------------------------------ #
    # Boucle principale
    # ------------------------------------------------------------------ #
    def run(self, max_frames: int | None = None) -> None:
        """Lance la boucle. `max_frames` sert aux tests (fenêtre factice)."""
        frames = 0
        try:
            while self.running and (max_frames is None or frames < max_frames):
                real_dt = min(self.frame_clock.tick(self.fps) / 1000.0, MAX_FRAME_SECONDS)
                self.frame(real_dt)
                frames += 1
        finally:
            pygame.quit()

    def frame(self, real_dt: float) -> None:
        """Une image : entrées, simulation, caméra, dessin."""
        self._handle_events()
        dx, dy = self.input.camera_direction()
        if dx or dy:
            self.camera.move(dx * CAMERA_SPEED * real_dt, dy * CAMERA_SPEED * real_dt)
            self.ui.state.follow = False
        if self.screen.get_size() != (self.camera.view_width, self.camera.view_height):
            self.camera.resize(*self.screen.get_size())

        executed = self._step_simulation(real_dt)
        if real_dt > 0:
            # Moyenne glissante : un affichage stable plutôt qu'un chiffre qui saute.
            self.measured_tps = 0.9 * self.measured_tps + 0.1 * (executed / real_dt)
        alpha = self._alpha()
        self._follow(real_dt, alpha)
        self._update_hover(alpha)
        self.ui.update(real_dt)
        self._draw(alpha)

    def _alpha(self) -> float:
        return 0.0 if self.paused else min(max(self.accumulator, 0.0), 1.0)

    def _step_simulation(self, real_dt: float) -> int:
        if self.paused:
            return 0
        speed = self.speeds[self.speed_index]
        self.accumulator += real_dt * self.ticks_per_second_x1 * speed
        executed = 0
        while self.accumulator >= 1.0 and executed < self.max_ticks_per_frame:
            self.sim.tick()
            self.accumulator -= 1.0
            executed += 1
        if executed >= self.max_ticks_per_frame:
            self.accumulator = min(self.accumulator, 1.0)
        return executed

    def _follow(self, dt: float, alpha: float) -> None:
        state = self.ui.state
        if not state.follow or state.selected_agent is None:
            return
        agent = self.sim.agents[state.selected_agent]
        x, y = self.renderer.agent_world_pos(agent, alpha)
        self.camera.follow(x, y - FOLLOW_HEAD_OFFSET, dt)

    def _update_hover(self, alpha: float) -> None:
        state = self.ui.state
        mouse = pygame.mouse.get_pos()
        state.hover_agent = None
        state.hover_place = None
        if not self.hover_enabled or self.ui.is_over_ui(mouse) or not pygame.mouse.get_focused():
            self.renderer.hovered_id = None
            return
        agent = self.renderer.pick_agent(self.sim, self.camera, mouse, alpha)
        if agent is not None:
            state.hover_agent = agent.id
        else:
            wx, wy = self.camera.screen_to_world(*mouse)
            place = self.sim.world.place_at((int(wx // 16), int(wy // 16)))
            state.hover_place = place.id if place is not None else None
        self.renderer.hovered_id = state.hover_agent

    # ------------------------------------------------------------------ #
    # Entrées
    # ------------------------------------------------------------------ #
    def _handle_events(self) -> None:
        for event in pygame.event.get():
            action = self.input.handle(event)
            if action is None:
                continue
            state = self.ui.state
            match action.kind:
                case ActionKind.QUIT:
                    self.running = False
                case ActionKind.ESCAPE:
                    if state.selected_agent or state.selected_place:
                        self.ui.clear_selection()
                    else:
                        self.running = False
                case ActionKind.TOGGLE_PAUSE:
                    self.paused = not self.paused
                case ActionKind.SET_SPEED:
                    if action.value < len(self.speeds):
                        self.speed_index = action.value
                        self.paused = False
                case ActionKind.ZOOM:
                    self.camera.zoom_at(self.camera.zoom + action.value, *action.pos)
                case ActionKind.TOGGLE_DEBUG:
                    state.debug = not state.debug
                case ActionKind.TOGGLE_UI:
                    state.visible = not state.visible
                case ActionKind.TOGGLE_FOLLOW:
                    state.follow = not state.follow and state.selected_agent is not None
                case ActionKind.TOGGLE_LIGHTING:
                    self.renderer.lighting.enabled = not self.renderer.lighting.enabled
                case ActionKind.NEXT_AGENT:
                    self.ui.cycle_agent()
                case ActionKind.DRAG:
                    dx, dy = action.pos
                    self.camera.move(-dx, -dy)
                    state.follow = False
                case ActionKind.CLICK:
                    self._click(action.pos)

    def _click(self, pos: tuple[int, int]) -> None:
        ui_action = self.ui.click(pos)
        if ui_action is not None:
            if ui_action == "pause":
                self.paused = not self.paused
            elif ui_action.startswith("speed:"):
                self.speed_index = int(ui_action.removeprefix("speed:"))
                self.paused = False
            return
        if self.ui.is_over_ui(pos):
            return
        agent = self.renderer.pick_agent(self.sim, self.camera, pos, self._alpha())
        if agent is not None:
            self.ui.select_agent(agent.id, follow=True)
            return
        wx, wy = self.camera.screen_to_world(*pos)
        place = self.sim.world.place_at((int(wx // 16), int(wy // 16)))
        if place is not None:
            self.ui.select_place(place.id)
        else:
            self.ui.clear_selection()

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #
    def _draw(self, alpha: float) -> None:
        seconds = time.monotonic() - self._started
        self.renderer.draw(self.screen, self.sim, self.camera, alpha, seconds)
        status = AppStatus(
            paused=self.paused,
            speed_index=self.speed_index,
            speeds=tuple(self.speeds),
            fps=self.frame_clock.get_fps(),
            ticks_per_second=self.measured_tps,
        )
        self.ui.draw(self.screen, self.camera, alpha, status)
        pygame.display.flip()
