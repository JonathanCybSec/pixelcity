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
    app.ui.state.debug = True
    for _ in range(5):
        app.frame(1 / 60)
    app.speed_index = 2  # x10
    for _ in range(20):
        app.frame(0.1)
    # 20 images de 0,1 s à x10, avec 6 ticks/s à x1 (1 minute simulée par seconde) : 120 ticks.
    assert 110 <= app.sim.clock.tick <= 130


def test_toutes_les_postures_se_dessinent(app: GameApp) -> None:
    """Assis, couché, caché, sur un tapis de course... aucune posture ne doit planter le rendu."""
    from pixelcity.sim.types import Anim, Pose

    sim = app.sim
    for index, agent in enumerate(sim.agents.values()):
        agent.pose = list(Pose)[index % len(Pose)]
        agent.anim = list(Anim)[index % len(Anim)]
    bed = next(s for s in sim.world.places["maison_dupont"].spots_for("sleep"))
    marcel = sim.agents["marcel"]
    marcel.pose, marcel.spot = Pose.LIE, bed
    for _ in range(3):
        app.frame(1 / 60)


def test_clic_sur_un_habitant_le_selectionne(app: GameApp) -> None:
    sim = app.sim
    lea = sim.agents["lea"]
    app.camera.zoom = 3
    x, y = app.renderer.agent_world_pos(lea, 0.0)
    app.camera.center_x, app.camera.center_y = x, y
    app.camera.clamp()
    app.frame(1 / 60)
    sx, sy = app.camera.world_to_screen(x, y - 10)
    app._click((sx, sy))
    assert app.ui.state.selected_agent == "lea" and app.ui.state.follow
    app.frame(1 / 60)  # la fiche s'affiche
    app._click((1, app.screen.get_height() // 2))  # clic dans le vide (hors interface)
    assert app.ui.state.selected_agent is None


def test_les_bulles_suivent_le_temps_reel(app: GameApp) -> None:
    """Une réplique reste lisible ~3 s à l'écran, même à x30."""
    from pixelcity.sim.service import say

    say(app.sim.ctx, "lea", "Bonjour !")
    bubbles = app.ui.feed.live_bubbles()
    assert "lea" in bubbles
    app.speed_index = 3  # x30 : des milliers de ticks défilent
    for _ in range(10):
        app.frame(0.1)
    assert "lea" in app.ui.feed.live_bubbles()  # une seconde réelle plus tard, toujours là


def test_teinte_de_la_nuit() -> None:
    from pixelcity.engine.lighting import darkness, tint_at

    assert tint_at(12 * 60) == (255, 255, 255)
    night = tint_at(2 * 60)
    assert darkness(night) > 0.3
    dusk = tint_at(19 * 60 + 30)
    assert dusk[0] > dusk[2]  # le crépuscule tire vers l'orangé


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
