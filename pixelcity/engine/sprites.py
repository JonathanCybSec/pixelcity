"""Banque de sprites : chaque image est chargée et découpée UNE seule fois.

Tout le rendu se fait à la résolution native du pixel art (1 pixel de sprite =
1 pixel de l'image intermédiaire) ; l'agrandissement vient à la toute fin
(voir `renderer.py`). Les sprites ne sont donc jamais redimensionnés ici.

Piège classique : `Surface.convert_alpha()` rend les blits ~5 fois plus
rapides (format de pixels identique à l'écran), mais il exige qu'une fenêtre
existe. On ne l'appelle que si c'est le cas : la banque reste utilisable par
les outils et les tests, sans fenêtre.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from pixelcity.sim.types import Facing
from pixelcity.world.catalog import FurnitureSpec, SpriteRef, Variant

TILE = 16
CHAR_W, CHAR_H = 16, 32

# Planche d'un personnage pixel-agents : 7 images de 16×32 par direction,
# rangées bas / haut / droite (la gauche est la droite en miroir).
WALK_CYCLE = (0, 1, 2, 1)  # le cycle de marche de pixel-agents
IDLE_FRAME = 1
TYPE_FRAMES = (3, 4)  # assis, mains en mouvement (taper, cuisiner, servir...)
READ_FRAMES = (5, 6)  # assis, tête baissée (lire, manger)
_SHEET_ROW = {Facing.DOWN: 0, Facing.UP: 1, Facing.RIGHT: 2, Facing.LEFT: 2}
# Hauteur de la tête dans l'image « debout, de face » : sert au lit, où l'on
# ne voit dépasser que la tête de sous la couverture.
HEAD_TOP, HEAD_HEIGHT = 3, 12


def prepare(surface: pygame.Surface) -> pygame.Surface:
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return surface.convert_alpha()
    return surface


@dataclass(frozen=True, slots=True)
class CharacterSheet:
    frames: dict[Facing, tuple[pygame.Surface, ...]]
    head: pygame.Surface  # la tête seule, de face

    def frame(self, facing: Facing, index: int) -> pygame.Surface:
        return self.frames[facing][index]


class SpriteBank:
    """Images du jeu, mises en cache par chemin (et par miroir)."""

    def __init__(self, characters_dir: Path, walls_dir: Path) -> None:
        self._characters_dir = characters_dir
        self._walls_dir = walls_dir
        self._images: dict[tuple[Path, bool], pygame.Surface] = {}
        self._walls: dict[str, pygame.Surface] = {}
        self._wall_pieces: dict[tuple[str, int], pygame.Surface] = {}
        self._characters: dict[int, CharacterSheet] = {}

    # -- images ------------------------------------------------------------------------
    def image(self, path: Path, *, mirrored: bool = False) -> pygame.Surface:
        key = (path, mirrored)
        surface = self._images.get(key)
        if surface is None:
            if mirrored:
                surface = pygame.transform.flip(self.image(path), True, False)
            else:
                surface = prepare(pygame.image.load(str(path)))
            self._images[key] = surface
        return surface

    def frames(self, variant: Variant, state: str) -> tuple[pygame.Surface, ...]:
        refs: tuple[SpriteRef, ...] = variant.frames(state)
        return tuple(self.image(ref.file, mirrored=variant.mirrored) for ref in refs)

    def overlay(self, spec: FurnitureSpec, name: str) -> pygame.Surface | None:
        path = spec.overlays.get(name)
        return self.image(path) if path is not None else None

    # -- murs : planche 64×128 de 16 pièces 16×32, indexées par masque de voisins ----------
    def wall_piece(self, style: str, mask: int) -> pygame.Surface:
        """Pièce de mur selon ses voisins : N=1, E=2, S=4, O=8 (auto-tiling de pixel-agents)."""
        key = (style, mask)
        piece = self._wall_pieces.get(key)
        if piece is None:
            sheet = self._walls.get(style)
            if sheet is None:
                sheet = prepare(pygame.image.load(str(self._walls_dir / f"{style}.png")))
                self._walls[style] = sheet
            rect = pygame.Rect((mask % 4) * TILE, (mask // 4) * 2 * TILE, TILE, 2 * TILE)
            piece = sheet.subsurface(rect)
            self._wall_pieces[key] = piece
        return piece

    # -- personnages ---------------------------------------------------------------------
    def character(self, index: int) -> CharacterSheet:
        sheet = self._characters.get(index)
        if sheet is None:
            image = prepare(pygame.image.load(str(self._characters_dir / f"char_{index}.png")))
            frames: dict[Facing, tuple[pygame.Surface, ...]] = {}
            for facing, row in _SHEET_ROW.items():
                cut = tuple(
                    image.subsurface(pygame.Rect(i * CHAR_W, row * CHAR_H, CHAR_W, CHAR_H))
                    for i in range(7)
                )
                if facing is Facing.LEFT:
                    cut = tuple(pygame.transform.flip(frame, True, False) for frame in cut)
                frames[facing] = cut
            idle = frames[Facing.DOWN][IDLE_FRAME]
            head = idle.subsurface(pygame.Rect(0, HEAD_TOP, CHAR_W, HEAD_HEIGHT))
            sheet = CharacterSheet(frames, head)
            self._characters[index] = sheet
        return sheet
