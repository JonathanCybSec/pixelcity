"""Bandeau d'informations permanent : heure, vitesse, performances, aide."""

from __future__ import annotations

import pygame

from pixelcity.sim.simulation import Simulation
from pixelcity.ui.widgets import MUTED, TEXT, panel

HELP = "  ·  ".join(
    (
        "Espace pause",
        "1-4 vitesse",
        "ZQSD/flèches caméra",
        "molette zoom",
        "F3 debug",
        "Échap quitter",
    )
)


class Hud:
    def __init__(self) -> None:
        self._big = pygame.font.Font(None, 30)
        self._small = pygame.font.Font(None, 20)

    def draw(
        self,
        screen: pygame.Surface,
        sim: Simulation,
        *,
        paused: bool,
        speed: int,
        fps: float,
        ticks_per_second: float,
    ) -> None:
        clock_text = self._big.render(sim.clock.label(), True, TEXT)
        speed_label = "PAUSE" if paused else f"vitesse x{speed}"
        speed_color = (240, 190, 90) if paused else (150, 210, 160)
        speed_text = self._small.render(speed_label, True, speed_color)
        box = panel(max(clock_text.get_width(), speed_text.get_width()) + 24, 58)
        box.blit(clock_text, (12, 8))
        box.blit(speed_text, (12, 36))
        screen.blit(box, (12, 12))

        perf = self._small.render(f"{fps:.0f} FPS  ·  {ticks_per_second:,.0f} ticks/s", True, MUTED)
        perf_box = panel(perf.get_width() + 20, perf.get_height() + 12)
        perf_box.blit(perf, (10, 6))
        screen.blit(perf_box, (screen.get_width() - perf_box.get_width() - 12, 12))

        help_text = self._small.render(HELP, True, MUTED)
        help_box = panel(help_text.get_width() + 20, help_text.get_height() + 10)
        help_box.blit(help_text, (10, 5))
        screen.blit(
            help_box,
            (
                (screen.get_width() - help_box.get_width()) // 2,
                screen.get_height() - help_box.get_height() - 10,
            ),
        )
