"""Boucle de jeu : relie le temps réel au temps simulé.

C'est ici, et seulement ici, qu'intervient la vitesse de jeu. Le principe
de l'accumulateur (« Fix Your Timestep! », Glenn Fiedler, 2004) :

    à chaque image :
        accumulateur += temps réel écoulé × ticks par seconde × vitesse
        tant que accumulateur >= 1 :
            simulation.tick()      # pas FIXE de 10 s simulées
            accumulateur -= 1
        dessiner avec alpha = accumulateur (fraction du tick suivant)

- À x10, on exécute simplement 10 fois plus de ticks : chaque tick reste
  identique, donc la simulation se comporte exactement comme à x1.
- `alpha` sert à interpoler les positions entre deux ticks : à x1, il y a
  ~14 ticks par seconde pour 60 images, sans interpolation les habitants
  avanceraient par saccades.
- Le plafond `max_ticks_per_frame` évite la « spirale de la mort » : si la
  machine n'arrive plus à suivre, on abandonne le retard (la simulation
  ralentit) au lieu d'accumuler toujours plus de travail (la fenêtre gèle).
"""

from __future__ import annotations

import pygame

from pixelcity.engine.camera import Camera
from pixelcity.engine.input import ActionKind, InputState
from pixelcity.engine.renderer import Renderer
from pixelcity.sim.simulation import Simulation
from pixelcity.ui.debug_overlay import DebugOverlay
from pixelcity.ui.hud import Hud

CAMERA_SPEED = 700  # pixels écran par seconde
MAX_FRAME_SECONDS = 0.25  # au-delà (fenêtre déplacée, point d'arrêt...), on plafonne


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
        pygame.display.set_caption("PixelCity · étape 1 (MVP)")
        self.fps = window.fps
        self.frame_clock = pygame.time.Clock()

        self.renderer = Renderer(sim)
        self.camera = Camera.centered(
            self.screen.get_size(), self.renderer.world_size, window.start_zoom
        )
        self.input = InputState()
        self.hud = Hud()
        self.overlay = DebugOverlay()

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
        """Une image : entrées, simulation, dessin."""
        self._handle_events()
        dx, dy = self.input.camera_direction()
        if dx or dy:
            self.camera.move(dx * CAMERA_SPEED * real_dt, dy * CAMERA_SPEED * real_dt)
        if self.screen.get_size() != (self.camera.view_width, self.camera.view_height):
            self.camera.resize(*self.screen.get_size())

        executed = self._step_simulation(real_dt)
        if real_dt > 0:
            # Moyenne glissante : un affichage stable plutôt qu'un chiffre qui saute.
            self.measured_tps = 0.9 * self.measured_tps + 0.1 * (executed / real_dt)
        self._draw()

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

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            action = self.input.handle(event)
            if action is None:
                continue
            match action.kind:
                case ActionKind.QUIT:
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
                    self.overlay.toggle()

    def _draw(self) -> None:
        alpha = min(max(self.accumulator, 0.0), 1.0)
        self.renderer.draw(self.screen, self.sim, self.camera, alpha)
        self.overlay.draw(self.screen, self.sim, self.camera, self.renderer, alpha)
        self.hud.draw(
            self.screen,
            self.sim,
            paused=self.paused,
            speed=self.speeds[self.speed_index],
            fps=self.frame_clock.get_fps(),
            ticks_per_second=self.measured_tps,
        )
        pygame.display.flip()
