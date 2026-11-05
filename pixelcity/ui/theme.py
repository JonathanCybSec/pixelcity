"""Thème de l'interface : couleurs, polices, cache de textes.

Le monde est en pixel art ; l'interface, elle, est NETTE (police Inter, à la
résolution de l'écran) et translucide, façon « verre dépoli ». Ce contraste
est volontaire : on lit facilement l'interface sans qu'elle fasse oublier la ville.

Toutes les couleurs sont ici : pour changer l'ambiance, c'est le seul fichier
à toucher (pixel-agents a la même règle, contrôlée par un linter).
"""

from __future__ import annotations

from collections import OrderedDict
from enum import StrEnum

import pygame

from pixelcity.resources import assets_dir
from pixelcity.sim.types import NeedKind

type RGB = tuple[int, int, int]
type RGBA = tuple[int, int, int, int]

TEXT: RGB = (241, 243, 248)
TEXT_2: RGB = (178, 184, 200)
MUTED: RGB = (118, 124, 142)
DARK_TEXT: RGB = (28, 30, 40)
ACCENT: RGB = (124, 196, 255)
SUCCESS: RGB = (98, 212, 154)
WARNING: RGB = (245, 181, 71)
DANGER: RGB = (255, 107, 107)

GLASS_FILL: RGBA = (18, 21, 32, 168)
GLASS_FILL_STRONG: RGBA = (16, 18, 28, 205)
GLASS_BORDER: RGBA = (255, 255, 255, 34)
GLASS_HIGHLIGHT: RGBA = (255, 255, 255, 18)
HOVER_FILL: RGBA = (255, 255, 255, 18)
ACTIVE_FILL: RGBA = (124, 196, 255, 46)
TRACK: RGBA = (255, 255, 255, 26)
SHADOW: RGBA = (0, 0, 0, 90)
BUBBLE_FILL: RGBA = (250, 250, 252, 238)
BUBBLE_BORDER: RGBA = (20, 22, 30, 60)

NEED_COLORS: dict[NeedKind, RGB] = {
    NeedKind.HUNGER: (255, 159, 92),
    NeedKind.ENERGY: (255, 214, 102),
    NeedKind.HYGIENE: (110, 200, 255),
    NeedKind.BLADDER: (190, 150, 255),
    NeedKind.FUN: (110, 220, 160),
}

RADIUS = 12
GAP = 10
PAD = 14


def hex_to_rgb(color: str) -> RGB:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


class Weight(StrEnum):
    REGULAR = "Regular"
    MEDIUM = "Medium"
    SEMIBOLD = "SemiBold"


class Fonts:
    """Polices Inter (licence OFL) chargées à la demande, par graisse et par taille."""

    def __init__(self) -> None:
        self._dir = assets_dir() / "fonts"
        self._cache: dict[tuple[Weight, int], pygame.font.Font] = {}

    def get(self, size: int, weight: Weight = Weight.REGULAR) -> pygame.font.Font:
        key = (weight, size)
        font = self._cache.get(key)
        if font is None:
            path = self._dir / f"Inter-{weight.value}.ttf"
            font = (
                pygame.font.Font(str(path), size)
                if path.is_file()
                else pygame.font.Font(None, size + 4)
            )
            self._cache[key] = font
        return font


class TextCache:
    """`Font.render` est lent (rastérisation FreeType) : on garde les textes déjà rendus.

    Cache LRU : les textes qui changent souvent (l'heure) chassent les plus anciens.
    """

    def __init__(self, fonts: Fonts, capacity: int = 1024) -> None:
        self.fonts = fonts
        self._capacity = capacity
        self._cache: OrderedDict[tuple[str, int, Weight, RGB], pygame.Surface] = OrderedDict()
        self._fitted: OrderedDict[tuple[str, int, int, Weight], str] = OrderedDict()

    def render(
        self, text: str, size: int, color: RGB = TEXT, weight: Weight = Weight.REGULAR
    ) -> pygame.Surface:
        key = (text, size, weight, color)
        surface = self._cache.get(key)
        if surface is not None:
            self._cache.move_to_end(key)
            return surface
        surface = self.fonts.get(size, weight).render(text, True, color)
        self._cache[key] = surface
        if len(self._cache) > self._capacity:
            self._cache.popitem(last=False)
        return surface

    def fit(self, text: str, size: int, max_width: int, weight: Weight = Weight.REGULAR) -> str:
        """Tronque avec « … » pour tenir dans `max_width` pixels (résultat mis en cache)."""
        key = (text, size, max_width, weight)
        fitted = self._fitted.get(key)
        if fitted is not None:
            self._fitted.move_to_end(key)
            return fitted
        font = self.fonts.get(size, weight)
        fitted = text
        if font.size(text)[0] > max_width:
            while fitted and font.size(fitted + "…")[0] > max_width:
                fitted = fitted[:-1]
            fitted = fitted.rstrip() + "…"
        self._fitted[key] = fitted
        if len(self._fitted) > self._capacity:
            self._fitted.popitem(last=False)
        return fitted

    def wrap(
        self, text: str, size: int, max_width: int, weight: Weight = Weight.REGULAR
    ) -> list[str]:
        """Coupe un texte en lignes qui tiennent dans `max_width` pixels."""
        font = self.fonts.get(size, weight)
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines
