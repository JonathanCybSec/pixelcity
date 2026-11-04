"""Tests du moteur : caméra (calculs purs) et rendu avec une fenêtre factice."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pygame
import pytest

from pixelcity.engine.app import GameApp
from pixelcity.engine.camera import Camera
from pixelcity.sim.simulation import Simulation


def test_zoom_garde_le_point_sous_la_souris() -> None:
    camera = Camera.centered(view=(1280, 720), world=(768, 512), zoom=2)
    mouse = (900, 200)
    before = camera.screen_to_world(*mouse)
    camera.zoom_at(3, *mouse)
    after = camera.screen_to_world(*mouse)
    assert camera.zoom == 3
    assert after == pytest.approx(before, abs=0.5)


def test_la_camera_reste_dans_la_carte() -> None:
    camera = Camera.centered(view=(1280, 720), world=(768, 512), zoom=3)
    camera.move(-100_000, -100_000)
    left, top = camera.screen_to_world(0, 0)
    assert left >= -0.5 and top >= -0.5


def test_petite_carte_centree() -> None:
    camera = Camera.centered(view=(1280, 720), world=(768, 512), zoom=1)
    camera.move(500, 500)  # la carte tient à l'écran : la caméra ne bouge pas
    assert (camera.center_x, camera.center_y) == (384, 256)


def test_offset_entier() -> None:
    camera = Camera.centered(view=(1281, 721), world=(768, 512), zoom=2)
    camera.move(3.3, 1.7)
    ox, oy = camera.offset()
    assert isinstance(ox, int) and isinstance(oy, int)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, make_sim: Callable[..., Simulation]) -> Iterator[GameApp]:
    """Application complète avec le pilote vidéo factice de SDL : aucune fenêtre ne s'ouvre.

    Le pilote est lu par `pygame.display.init()`, pas par `import pygame` :
    il suffit donc de poser la variable avant de créer l'application.
    """
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    instance = GameApp(make_sim())
    yield instance
    pygame.quit()


def test_le_rendu_tourne_sans_ecran(app: GameApp) -> None:
    app.overlay.enabled = True
    for _ in range(5):
        app.frame(1 / 60)
    app.speed_index = 3  # x10
    for _ in range(20):
        app.frame(0.1)
    # 20 images de 0,1 s à x10, avec ~14,4 ticks/s à x1 : ~288 ticks.
    assert 250 < app.sim.clock.tick < 330


def test_la_pause_fige_la_simulation(app: GameApp) -> None:
    app.paused = True
    app.frame(1.0)
    assert app.sim.clock.tick == 0


def test_protection_spirale_de_la_mort(app: GameApp) -> None:
    executed = app._step_simulation(1000.0)  # une « image » de 1000 s : la machine rame
    assert executed == app.max_ticks_per_frame
    assert app.accumulator <= 1.0  # le retard est abandonné, pas accumulé


def test_la_boucle_principale_s_arrete_proprement(app: GameApp) -> None:
    app.run(max_frames=3)
    assert app.sim.clock.tick >= 0
