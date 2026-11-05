"""Le lanceur : menu → studio → partie → menu... une petite machine à états.

    ┌──────┐  jouer   ┌────────┐  Échap  ┌──────┐
    │ menu │ ───────▶ │ partie │ ──────▶ │ menu │
    └──────┘          └────────┘         └──────┘
       │ studio          ▲
       ▼                 │ enregistrer et jouer
    ┌────────┐ ──────────┘
    │ studio │
    └────────┘

Une seule fenêtre pour tout le programme : la recréer à chaque écran la
ferait clignoter (et sous Windows, elle reprendrait sa position par défaut).
"""

from __future__ import annotations

import pygame

from pixelcity.config.loader import ConfigError, GameConfig
from pixelcity.engine.app import GameApp
from pixelcity.engine.screens import Backdrop, MenuScreen, Shared, StudioScreen
from pixelcity.llm.backends import make_backend
from pixelcity.llm.settings import LlmSettings
from pixelcity.sim.simulation import Simulation
from pixelcity.studio import scenario as sc


def run_launcher(
    config: GameConfig, llm: LlmSettings, *, seed: int | None = None, max_frames: int | None = None
) -> None:
    pygame.display.init()
    pygame.font.init()
    window = config.settings.window
    screen = pygame.display.set_mode((window.width, window.height), pygame.RESIZABLE)
    pygame.display.set_caption("PixelCity")
    clock = pygame.time.Clock()
    shared = Shared(config, llm)
    shared.backdrop = Backdrop(config)
    current: MenuScreen | StudioScreen = MenuScreen(shared)
    frames = 0
    try:
        while max_frames is None or frames < max_frames:
            dt = clock.tick(window.fps) / 1000.0
            frames += 1
            events = pygame.event.get()
            if any(event.type == pygame.QUIT for event in events):
                return
            if isinstance(current, MenuScreen):
                choice = current.frame(screen, events, dt)
                pygame.display.flip()
                if choice is None:
                    continue
                if choice.action == "quit":
                    return
                if choice.action == "studio":
                    current = StudioScreen(shared, choice.scenario)
                    continue
                scenario = choice.scenario
            else:
                studio_choice = current.frame(screen, events, dt)
                pygame.display.flip()
                if studio_choice is None:
                    continue
                if studio_choice.action == "menu":
                    current = MenuScreen(shared)
                    continue
                scenario = studio_choice.scenario
            # --- Une partie --------------------------------------------------------------
            if _play(screen, config, llm, scenario, seed) == "quit":
                return
            current = MenuScreen(shared)
    finally:
        pygame.quit()


def _play(
    screen: pygame.Surface,
    config: GameConfig,
    llm: LlmSettings,
    scenario: sc.Scenario | None,
    seed: int | None,
) -> str:
    try:
        game_config = sc.apply(scenario, config) if scenario is not None else config
    except ConfigError:
        return "menu"  # le studio n'autorise pas l'enregistrement d'un scénario invalide
    backend = make_backend(llm, config.dialogues)
    sim = Simulation(game_config, seed=seed, dialogue=backend)
    title = f"PixelCity · {scenario.name}" if scenario is not None else "PixelCity"
    pygame.display.set_caption(title)
    try:
        return GameApp(sim, screen).run()
    finally:
        sim.close()
        pygame.display.set_caption("PixelCity")
