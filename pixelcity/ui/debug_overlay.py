"""Overlay de débogage (F3) : ce que pense et fait chaque habitant.

- au-dessus de chaque agent visible : son nom et son activité ;
- le reste de son chemin A* tracé dans sa couleur ;
- un panneau listant tous les habitants, même ceux cachés dans un bâtiment,
  avec leurs jauges et leur prochain bloc de plan.
"""

from __future__ import annotations

import pygame

from pixelcity.engine.camera import Camera
from pixelcity.engine.renderer import Renderer, hex_to_rgb
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind
from pixelcity.ui.widgets import MUTED, TEXT, fit_text, gauge, gauge_color, panel

PANEL_WIDTH = 340


class DebugOverlay:
    def __init__(self) -> None:
        self.enabled = False
        self._font = pygame.font.Font(None, 18)
        self._bold = pygame.font.Font(None, 22)

    def toggle(self) -> None:
        self.enabled = not self.enabled

    def draw(
        self,
        screen: pygame.Surface,
        sim: Simulation,
        camera: Camera,
        renderer: Renderer,
        alpha: float,
    ) -> None:
        if not self.enabled:
            return
        self._draw_paths_and_tags(screen, sim, camera, renderer, alpha)
        self._draw_panel(screen, sim)

    def _draw_paths_and_tags(
        self,
        screen: pygame.Surface,
        sim: Simulation,
        camera: Camera,
        renderer: Renderer,
        alpha: float,
    ) -> None:
        tile_w, tile_h = renderer.tile_w, renderer.tile_h
        for agent in sim.agents.values():
            if not sim.is_visible(agent):
                continue
            color = hex_to_rgb(agent.profile.color)
            sx, sy = renderer.agent_screen_pos(agent, camera, alpha)
            remaining = agent.path[agent.path_index + 1 :] if agent.path else ()
            if remaining:
                points = [(sx, sy)] + [
                    camera.world_to_screen((x + 0.5) * tile_w, (y + 0.5) * tile_h)
                    for x, y in remaining
                ]
                pygame.draw.lines(screen, color, False, points, max(1, camera.zoom // 2 + 1))
            tag = self._font.render(f"{agent.name.split()[0]} · {agent.status_text()}", True, TEXT)
            box = panel(tag.get_width() + 8, tag.get_height() + 4)
            box.blit(tag, (4, 2))
            screen.blit(
                box, (sx - box.get_width() // 2, sy - tile_h * camera.zoom - box.get_height())
            )

    def _draw_panel(self, screen: pygame.Surface, sim: Simulation) -> None:
        row_height = 128
        text_width = PANEL_WIDTH - 42
        box = panel(PANEL_WIDTH, 14 + row_height * len(sim.agents))
        y = 10
        for agent in sim.agents.values():
            color = hex_to_rgb(agent.profile.color)
            pygame.draw.circle(box, color, (18, y + 8), 6)
            title = fit_text(self._bold, f"{agent.name} · {agent.profile.job}", text_width)
            box.blit(self._bold.render(title, True, TEXT), (30, y))
            place = sim.world.places[agent.place_id].name if agent.place_id else "dehors"
            status = fit_text(self._font, f"{agent.status_text()} · {place}", text_width)
            box.blit(self._font.render(status, True, MUTED), (30, y + 20))
            upcoming = agent.next_block()
            if upcoming is not None:
                text = fit_text(self._font, f"ensuite : {upcoming.describe()}", text_width)
                box.blit(self._font.render(text, True, MUTED), (30, y + 36))
            for index, kind in enumerate(NeedKind):
                value = agent.needs[kind]
                gy = y + 58 + index * 16
                box.blit(self._font.render(kind.label, True, MUTED), (30, gy - 3))
                gauge(box, pygame.Rect(102, gy, PANEL_WIDTH - 160, 9), value, gauge_color(value))
                box.blit(self._font.render(f"{value:.0f}", True, TEXT), (PANEL_WIDTH - 46, gy - 3))
            y += row_height
        screen.blit(box, (screen.get_width() - PANEL_WIDTH - 12, 52))
