"""Petits outils de dessin partagés par le HUD et l'overlay de débogage."""

from __future__ import annotations

import pygame

PANEL_BG = (16, 18, 24, 200)
TEXT = (238, 236, 228)
MUTED = (160, 164, 172)


def panel(width: int, height: int) -> pygame.Surface:
    """Surface semi-transparente aux coins arrondis."""
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(surface, PANEL_BG, surface.get_rect(), border_radius=6)
    return surface


def gauge(
    surface: pygame.Surface, rect: pygame.Rect, value: float, color: tuple[int, int, int]
) -> None:
    """Barre de jauge 0-100."""
    pygame.draw.rect(surface, (50, 54, 62), rect, border_radius=2)
    filled = rect.copy()
    filled.width = round(rect.width * max(0.0, min(100.0, value)) / 100)
    if filled.width:
        pygame.draw.rect(surface, color, filled, border_radius=2)


def fit_text(font: pygame.font.Font, text: str, max_width: int) -> str:
    """Raccourcit `text` avec « … » pour qu'il tienne dans `max_width` pixels."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "…")[0] > max_width:
        text = text[:-1]
    return text + "…"


def gauge_color(value: float) -> tuple[int, int, int]:
    """Vert si tout va bien, orange si ça baisse, rouge si c'est critique."""
    if value >= 60:
        return (96, 190, 110)
    if value >= 30:
        return (226, 170, 70)
    return (220, 80, 70)
