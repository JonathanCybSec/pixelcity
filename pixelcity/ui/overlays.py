"""Ce qui est dessiné PAR-DESSUS le monde, accroché aux habitants et aux lieux.

Bulles de dialogue, étiquettes des lieux, marqueur de sélection, infobulle.
Tout est dessiné à la résolution de l'écran (texte net), à la position
écran calculée par le renderer à partir de la position monde.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import pygame

from pixelcity.sim.types import Pose
from pixelcity.ui.glass import rounded
from pixelcity.ui.theme import (
    BUBBLE_BORDER,
    BUBBLE_FILL,
    DANGER,
    DARK_TEXT,
    GLASS_FILL_STRONG,
    MUTED,
    SUCCESS,
    TEXT,
    TEXT_2,
    Weight,
    hex_to_rgb,
)
from pixelcity.ui.widgets import label

if TYPE_CHECKING:
    from pixelcity.ui.ui import UiFrame

BUBBLE_MAX_TEXT_WIDTH = 210
BUBBLE_PAD_X, BUBBLE_PAD_Y = 10, 7
LABEL_MIN_ZOOM = 2


def speech_bubbles(f: UiFrame) -> None:
    """Une bulle par habitant qui parle, empilées pour ne pas se recouvrir."""
    placed: list[pygame.Rect] = []
    bubbles = f.feed.live_bubbles()
    items = []
    for agent_id, (bubble, opacity) in bubbles.items():
        agent = f.sim.agents.get(agent_id)
        if agent is None or agent.pose is Pose.HIDDEN:
            continue
        anchor = f.renderer.agent_head_screen(agent, f.camera, f.alpha)
        if not f.screen.get_rect().inflate(-20, -20).collidepoint(anchor):
            continue  # hors de l'écran : une bulle collée au bord ne dirait pas qui parle
        items.append((anchor[1], agent, bubble, opacity, anchor))
    # Du haut vers le bas de l'écran : les bulles basses se poussent vers le haut.
    for _y, agent, bubble, opacity, (ax, ay) in sorted(items, key=lambda item: -item[0]):
        lines = f.texts.wrap(bubble.text, 12, BUBBLE_MAX_TEXT_WIDTH)
        name = agent.first_name
        name_surface = f.texts.render(name, 11, hex_to_rgb(agent.profile.color), Weight.SEMIBOLD)
        line_surfaces = [f.texts.render(line, 12, DARK_TEXT, Weight.MEDIUM) for line in lines]
        width = (
            max([name_surface.get_width(), *(s.get_width() for s in line_surfaces)])
            + 2 * BUBBLE_PAD_X
        )
        height = (
            name_surface.get_height()
            + sum(s.get_height() for s in line_surfaces)
            + 2 * BUBBLE_PAD_Y
        )
        rect = pygame.Rect(0, 0, width, height)
        rect.midbottom = (ax, ay - 8)
        for other in placed:
            if rect.colliderect(other.inflate(4, 4)):
                rect.bottom = other.top - 4
        rect.clamp_ip(pygame.Rect(4, 64, f.width - 8, f.height - 68))
        placed.append(rect)
        layer = pygame.Surface((rect.width, rect.height + 8), pygame.SRCALPHA)
        body = pygame.Rect(0, 0, rect.width, rect.height)
        pygame.draw.rect(layer, BUBBLE_FILL, body, border_radius=10)
        pygame.draw.rect(layer, BUBBLE_BORDER, body, width=1, border_radius=10)
        tail_x = max(12, min(rect.width - 12, ax - rect.x))
        pygame.draw.polygon(
            layer,
            BUBBLE_FILL,
            (
                (tail_x - 6, rect.height - 1),
                (tail_x + 6, rect.height - 1),
                (tail_x, rect.height + 7),
            ),
        )
        y = BUBBLE_PAD_Y
        layer.blit(name_surface, (BUBBLE_PAD_X, y))
        y += name_surface.get_height()
        for surface in line_surfaces:
            layer.blit(surface, (BUBBLE_PAD_X, y))
            y += surface.get_height()
        layer.set_alpha(round(255 * opacity))
        f.screen.blit(layer, rect.topleft)


def place_labels(f: UiFrame) -> None:
    """Le nom de chaque lieu au-dessus de son entrée (à partir du zoom ×2)."""
    if f.camera.zoom < LABEL_MIN_ZOOM:
        return
    screen_rect = f.screen.get_rect()
    for place in f.sim.world.places.values():
        area = place.area
        wx = (area.x + area.width / 2) * 16
        wy = area.y * 16 - 14
        sx, sy = f.camera.world_to_screen(wx, wy)
        if not screen_rect.collidepoint(sx, sy):
            continue
        hovered = place.id in (f.state.hover_place, f.state.selected_place)
        surface = f.texts.render(place.name, 11, TEXT if hovered else TEXT_2, Weight.SEMIBOLD)
        rect = surface.get_rect(center=(sx, sy)).inflate(16, 8)
        rounded(f.screen, rect, (18, 20, 30, 190 if hovered else 140), rect.height // 2)
        f.screen.blit(surface, surface.get_rect(center=rect.center))


def selection_marker(f: UiFrame) -> None:
    agent_id = f.state.selected_agent
    if agent_id is None:
        return
    agent = f.sim.agents[agent_id]
    x, y = f.renderer.agent_head_screen(agent, f.camera, f.alpha)
    bob = round(math.sin(time.monotonic() * 4) * 2)
    color = hex_to_rgb(agent.profile.color)
    top = y - 16 + bob
    pygame.draw.polygon(f.screen, (20, 22, 30), ((x - 7, top - 1), (x + 7, top - 1), (x, top + 9)))
    pygame.draw.polygon(f.screen, color, ((x - 5, top), (x + 5, top), (x, top + 7)))


def tooltip(f: UiFrame) -> None:
    """Infobulle sous la souris : qui est là, ou quel est ce lieu."""
    mx, my = f.mouse
    lines: list[tuple[str, tuple[int, int, int], int, Weight]] = []
    if f.state.hover_agent is not None:
        agent = f.sim.agents[f.state.hover_agent]
        lines = [
            (agent.name, hex_to_rgb(agent.profile.color), 13, Weight.SEMIBOLD),
            (agent.status_text(), TEXT_2, 12, Weight.REGULAR),
        ]
    elif f.state.hover_place is not None:
        place = f.sim.world.places[f.state.hover_place]
        clock = f.sim.clock
        open_now = place.hours.is_open(clock.weekday.number, clock.minute_of_day)
        lines = [
            (place.name, TEXT, 13, Weight.SEMIBOLD),
            ("ouvert" if open_now else "fermé", SUCCESS if open_now else DANGER, 12, Weight.MEDIUM),
            (f"{len(place.occupants)} présent(s)", MUTED, 12, Weight.REGULAR),
        ]
    if not lines:
        return
    surfaces = [f.texts.render(text, size, color, weight) for text, color, size, weight in lines]
    width = max(s.get_width() for s in surfaces) + 20
    height = sum(s.get_height() for s in surfaces) + 14
    rect = pygame.Rect(mx + 16, my + 18, width, height)
    rect.clamp_ip(f.screen.get_rect().inflate(-8, -8))
    rounded(f.screen, rect, GLASS_FILL_STRONG, 8)
    y = rect.y + 7
    for surface in surfaces:
        f.screen.blit(surface, (rect.x + 10, y))
        y += surface.get_height()


def debug_layer(f: UiFrame) -> None:
    """F3 : le chemin restant de chaque habitant, et quelques compteurs."""
    for agent in f.sim.agents.values():
        if not agent.path or agent.path_index >= len(agent.path) - 1:
            continue
        color = hex_to_rgb(agent.profile.color)
        points = [
            f.camera.world_to_screen((x + 0.5) * 16, (y + 0.5) * 16)
            for x, y in agent.path[agent.path_index :]
        ]
        if len(points) >= 2:
            pygame.draw.lines(f.screen, color, False, points, 2)
    finder = f.sim.world.pathfinder
    total = finder.hits + finder.misses
    rate = 100 * finder.hits / total if total else 0
    text = (
        f"{f.status.fps:.0f} img/s · {f.status.ticks_per_second:,.0f} ticks/s · "
        f"cache A* {rate:.0f} % · {f.sim.events.total_emitted} événements"
    )
    label(f.screen, f.texts, text, (f.width // 2, 66), size=12, color=TEXT_2, anchor="midtop")
