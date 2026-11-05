"""Petits éléments d'interface dessinés « en mode immédiat ».

Interface « immédiate » (immediate mode GUI, popularisée par Dear ImGui) :
plutôt que de créer des objets bouton qui vivent longtemps, on REDESSINE
tout à chaque image, et chaque élément cliquable enregistre sa zone dans
`Hits`. Au clic suivant, on regarde quelle zone est sous la souris. C'est
très simple pour une interface qui change sans arrêt (des jauges, une
horloge, des habitants qui vont et viennent).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame

from pixelcity.engine.sprites import IDLE_FRAME, SpriteBank
from pixelcity.sim.types import Facing
from pixelcity.ui.glass import rounded
from pixelcity.ui.theme import RGB, RGBA, TEXT, TRACK, TextCache, Weight


@dataclass(slots=True)
class Hits:
    """Zones cliquables de l'image en cours : (rectangle, identifiant d'action)."""

    regions: list[tuple[pygame.Rect, str]] = field(default_factory=list)

    def add(self, rect: pygame.Rect, action: str) -> None:
        self.regions.append((rect.copy(), action))

    def at(self, pos: tuple[int, int]) -> str | None:
        for rect, action in reversed(self.regions):  # le dernier dessiné est au-dessus
            if rect.collidepoint(pos):
                return action
        return None

    def clear(self) -> None:
        self.regions.clear()


def label(
    screen: pygame.Surface,
    texts: TextCache,
    text: str,
    pos: tuple[int, int],
    *,
    size: int = 13,
    color: RGB = TEXT,
    weight: Weight = Weight.REGULAR,
    anchor: str = "topleft",
    max_width: int | None = None,
) -> pygame.Rect:
    if max_width is not None:
        text = texts.fit(text, size, max_width, weight)
    surface = texts.render(text, size, color, weight)
    rect = surface.get_rect(**{anchor: pos})
    screen.blit(surface, rect)
    return rect


def bar(
    screen: pygame.Surface, rect: pygame.Rect, fraction: float, color: RGB, track: RGBA = TRACK
) -> None:
    """Jauge arrondie (une « pilule »)."""
    radius = rect.height // 2
    rounded(screen, rect, track, radius)
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0:
        filled = pygame.Rect(
            rect.x, rect.y, max(rect.height, round(rect.width * fraction)), rect.height
        )
        rounded(screen, filled, (*color, 255), radius)


def chip(
    screen: pygame.Surface,
    texts: TextCache,
    text: str,
    pos: tuple[int, int],
    *,
    fill: RGBA = (255, 255, 255, 22),
    color: RGB = TEXT,
    size: int = 12,
) -> pygame.Rect:
    surface = texts.render(text, size, color, Weight.MEDIUM)
    rect = pygame.Rect(pos, (surface.get_width() + 16, surface.get_height() + 6))
    rounded(screen, rect, fill, rect.height // 2)
    screen.blit(surface, surface.get_rect(center=rect.center))
    return rect


class Avatars:
    """Portraits des habitants : la tête du sprite pixel-agents, agrandie sans flou."""

    def __init__(self, bank: SpriteBank) -> None:
        self._bank = bank
        self._cache: dict[tuple[int, int], pygame.Surface] = {}
        self._composed: dict[tuple[int, int, RGB], pygame.Surface] = {}

    def get(self, sprite: int, scale: int) -> pygame.Surface:
        key = (sprite, scale)
        image = self._cache.get(key)
        if image is None:
            frame = self._bank.character(sprite).frame(Facing.DOWN, IDLE_FRAME)
            bust = frame.subsurface(pygame.Rect(0, 2, 16, 15))
            image = pygame.transform.scale_by(bust, scale)
            self._cache[key] = image
        return image

    def draw(
        self, screen: pygame.Surface, sprite: int, center: tuple[int, int], radius: int, ring: RGB
    ) -> pygame.Rect:
        key = (sprite, radius, ring)
        layer = self._composed.get(key)
        if layer is None:
            layer = self._compose(sprite, radius, ring)
            self._composed[key] = layer
        rect = layer.get_rect(center=center)
        screen.blit(layer, rect)
        return rect

    def _compose(self, sprite: int, radius: int, ring: RGB) -> pygame.Surface:
        layer = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(layer, (*ring, 70), (radius, radius), radius)
        pygame.draw.circle(layer, (*ring, 255), (radius, radius), radius, width=2)
        scale = max(1, (radius * 2 - 6) // 16)
        portrait = self.get(sprite, scale)
        clip = pygame.Surface(layer.get_size(), pygame.SRCALPHA)
        clip.blit(portrait, portrait.get_rect(midbottom=(radius, radius * 2 - 2)))
        circle = pygame.Surface(layer.get_size(), pygame.SRCALPHA)
        pygame.draw.circle(circle, (255, 255, 255, 255), (radius, radius), radius - 2)
        clip.blit(circle, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        layer.blit(clip, (0, 0))
        return layer


# --------------------------------------------------------------------------- #
# Icônes vectorielles (dessinées, pas d'images à charger)
# --------------------------------------------------------------------------- #
def icon_pause(screen: pygame.Surface, center: tuple[int, int], color: RGB) -> None:
    x, y = center
    pygame.draw.rect(screen, color, (x - 5, y - 6, 3, 12), border_radius=1)
    pygame.draw.rect(screen, color, (x + 2, y - 6, 3, 12), border_radius=1)


def icon_sun(screen: pygame.Surface, center: tuple[int, int], color: RGB) -> None:
    x, y = center
    pygame.draw.circle(screen, color, center, 5)
    for dx, dy in ((0, -9), (0, 9), (-9, 0), (9, 0), (6, 6), (-6, -6), (6, -6), (-6, 6)):
        pygame.draw.circle(screen, color, (x + dx * 7 // 9, y + dy * 7 // 9), 1)


def icon_moon(screen: pygame.Surface, center: tuple[int, int], color: RGB, background: RGB) -> None:
    x, y = center
    pygame.draw.circle(screen, color, center, 7)
    pygame.draw.circle(screen, background, (x + 4, y - 3), 6)
