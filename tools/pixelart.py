"""Boîte à outils de pixel art pour les générateurs d'assets (tools/).

Deux parties :
1. La colorisation HSL de pixel-agents (portage Python de leur `colorize.ts`,
   licence MIT) : elle transforme leurs sols et murs en niveaux de gris en
   n'importe quelle teinte, exactement comme dans leur éditeur.
2. Un petit « pinceau » (`Sprite`) pour dessiner nos propres meubles dans le
   même style : contour sombre propre à chaque matériau (jamais du noir pur),
   face du dessus claire, face avant plus sombre, ombre portée translucide.

Les outils ont le droit d'utiliser pygame ; le noyau de la simulation, non.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

type RGBA = tuple[int, int, int, int]
type Color = str | RGBA


def rgba(color: Color) -> RGBA:
    """ "#rrggbb", "#rrggbbaa" ou un tuple → (r, g, b, a)."""
    if isinstance(color, tuple):
        return color
    value = color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    a = int(value[6:8], 16) if len(value) == 8 else 255
    return (r, g, b, a)


# --------------------------------------------------------------------------- #
# Colorisation (portage de pixel-agents/webview-ui/src/office/colorize.ts)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Hsbc:
    """Réglage de couleur de pixel-agents : teinte, saturation, luminosité, contraste."""

    h: float
    s: float
    b: float = 0.0
    c: float = 0.0


def _hsl_to_rgb(h: float, s: float, light: float) -> tuple[int, int, int]:
    chroma = (1 - abs(2 * light - 1)) * s
    hp = (h % 360) / 60
    x = chroma * (1 - abs(hp % 2 - 1))
    if hp < 1:
        r1, g1, b1 = chroma, x, 0.0
    elif hp < 2:
        r1, g1, b1 = x, chroma, 0.0
    elif hp < 3:
        r1, g1, b1 = 0.0, chroma, x
    elif hp < 4:
        r1, g1, b1 = 0.0, x, chroma
    elif hp < 5:
        r1, g1, b1 = x, 0.0, chroma
    else:
        r1, g1, b1 = chroma, 0.0, x
    m = light - chroma / 2

    def channel(v: float) -> int:
        return max(0, min(255, round((v + m) * 255)))

    return channel(r1), channel(g1), channel(b1)


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    hi, lo = max(rf, gf, bf), min(rf, gf, bf)
    light = (hi + lo) / 2
    if hi == lo:
        return 0.0, 0.0, light
    d = hi - lo
    s = d / (2 - hi - lo) if light > 0.5 else d / (hi + lo)
    if hi == rf:
        h = ((gf - bf) / d + (6 if gf < bf else 0)) * 60
    elif hi == gf:
        h = ((bf - rf) / d + 2) * 60
    else:
        h = ((rf - gf) / d + 4) * 60
    return h, s, light


def _contrast_brightness(light: float, color: Hsbc) -> float:
    if color.c:
        light = 0.5 + (light - 0.5) * (100 + color.c) / 100
    if color.b:
        light = light + color.b / 200
    return max(0.0, min(1.0, light))


def colorize(surface: pygame.Surface, color: Hsbc) -> pygame.Surface:
    """Mode « Colorize » (façon Photoshop) : niveaux de gris → teinte fixe. Pour sols et murs."""
    data = bytearray(pygame.image.tobytes(surface, "RGBA"))
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            continue
        lum = (0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]) / 255
        data[i], data[i + 1], data[i + 2] = _hsl_to_rgb(
            color.h, color.s / 100, _contrast_brightness(lum, color)
        )
    return pygame.image.frombytes(bytes(data), surface.get_size(), "RGBA")


def adjust(surface: pygame.Surface, color: Hsbc) -> pygame.Surface:
    """Mode « Adjust » : décale la teinte et la saturation d'origine. Pour les meubles."""
    data = bytearray(pygame.image.tobytes(surface, "RGBA"))
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            continue
        h, s, light = _rgb_to_hsl(data[i], data[i + 1], data[i + 2])
        s = max(0.0, min(1.0, s + color.s / 100))
        data[i], data[i + 1], data[i + 2] = _hsl_to_rgb(
            (h + color.h) % 360, s, _contrast_brightness(light, color)
        )
    return pygame.image.frombytes(bytes(data), surface.get_size(), "RGBA")


# --------------------------------------------------------------------------- #
# Matériaux : palettes relevées sur les sprites de pixel-agents
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Material:
    hi: str  # reflet
    top: str  # face du dessus
    front: str  # face avant
    dark: str  # bas de la face avant, ombres internes
    line: str  # contour

    def tone(self, name: str) -> RGBA:
        return rgba(getattr(self, name))


WOOD = Material("#cfa86d", "#b38857", "#885c47", "#6e4637", "#532e3d")
WOOD_DARK = Material("#a07650", "#885c47", "#6e4637", "#55352c", "#3b1f2a")
WHITE = Material("#ffffff", "#eef0f4", "#d5dae1", "#b5bfc7", "#3f3740")
STEEL = Material("#e1e3e9", "#b5bfc7", "#8f979c", "#757b7c", "#3f3740")
GRAPHITE = Material("#757b7c", "#5f6064", "#4a4b50", "#3a3a40", "#1e1c22")
BRICK = Material("#d98a6a", "#b8614a", "#94473a", "#77352e", "#4a1f22")
GREEN = Material("#87bd4d", "#619947", "#458e48", "#356441", "#17201a")
GREEN_CUSHION = Material("#8fc293", "#6fa374", "#487841", "#33592f", "#173115")
CRIMSON = Material("#d97a8a", "#c25769", "#972651", "#7a1d43", "#420517")
NAVY = Material("#7ea0c8", "#658eb1", "#4b6f93", "#3a5878", "#1c2a3d")
CREAM = Material("#fbf3df", "#efe3c4", "#d9c9a3", "#bfae86", "#5a4632")
TILE_BLUE = Material("#eaf4fb", "#cfe3f1", "#a9c8de", "#86a9c4", "#3d5266")

SHADOW: RGBA = (0, 0, 0, 70)
OUTLINE_SOFT: RGBA = rgba("#3f3740")


# --------------------------------------------------------------------------- #
# Le pinceau
# --------------------------------------------------------------------------- #
class Sprite:
    """Une image RGBA et quelques primitives de dessin au pixel près.

    `fill` remplace les pixels (alpha compris) au lieu de les mélanger : c'est
    ce qu'on veut en pixel art, où chaque pixel a une couleur décidée.
    """

    def __init__(self, width: int, height: int) -> None:
        self.surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self.width, self.height = width, height

    # -- primitives ----------------------------------------------------------
    def px(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.surface.set_at((x, y), rgba(color))

    def rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        if w > 0 and h > 0:
            self.surface.fill(rgba(color), pygame.Rect(x, y, w, h))

    def hline(self, x0: int, x1: int, y: int, color: Color) -> None:
        self.rect(x0, y, x1 - x0 + 1, 1, color)

    def vline(self, x: int, y0: int, y1: int, color: Color) -> None:
        self.rect(x, y0, 1, y1 - y0 + 1, color)

    def frame(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        """Contour d'un rectangle (1 px)."""
        self.hline(x, x + w - 1, y, color)
        self.hline(x, x + w - 1, y + h - 1, color)
        self.vline(x, y, y + h - 1, color)
        self.vline(x + w - 1, y, y + h - 1, color)

    def rounded(self, x: int, y: int, w: int, h: int, fill: Color, line: Color) -> None:
        """Rectangle plein aux coins « coupés » d'un pixel, avec contour."""
        self.rect(x + 1, y, w - 2, h, line)
        self.rect(x, y + 1, w, h - 2, line)
        self.rect(x + 1, y + 1, w - 2, h - 2, fill)

    def shadow(self, x: int, y: int, w: int, h: int = 2) -> None:
        """Ombre portée translucide au sol, comme sous les meubles de pixel-agents."""
        self.rect(x, y, w, h, SHADOW)

    def stamp(self, other: Sprite | pygame.Surface, x: int, y: int) -> None:
        source = other.surface if isinstance(other, Sprite) else other
        self.surface.blit(source, (x, y))

    def pattern(self, x: int, y: int, rows: list[str], palette: dict[str, Color]) -> None:
        """Dessine un motif décrit en texte : chaque caractère est une couleur ('.' = rien)."""
        for dy, row in enumerate(rows):
            for dx, char in enumerate(row):
                if char != ".":
                    self.px(x + dx, y + dy, palette[char])

    # -- formes composées ------------------------------------------------------
    def box(self, x: int, y: int, w: int, h: int, top: int, mat: Material) -> None:
        """Boîte vue de dessus en 3/4 : face du dessus (`top` px) puis face avant.

        Contour au trait du matériau, reflet sur le bord supérieur, bande plus
        sombre en bas de la face avant : c'est la construction des tables et
        des chaises de pixel-agents.
        """
        self.rect(x, y, w, h, mat.line)
        self.rect(x + 1, y + 1, w - 2, top - 1, mat.top)
        self.hline(x + 1, x + w - 2, y + 1, mat.hi)
        if h - top - 1 > 0:
            self.rect(x + 1, y + top, w - 2, h - top - 1, mat.front)
            self.hline(x + 1, x + w - 2, y + top, mat.dark)
            if h - top - 1 > 2:
                self.hline(x + 1, x + w - 2, y + h - 2, mat.dark)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self.surface, str(path))


def load(path: Path) -> pygame.Surface:
    """Charge une image sans avoir besoin d'une fenêtre (pas de convert_alpha)."""
    return pygame.image.load(str(path))
