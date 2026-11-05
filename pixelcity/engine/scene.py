"""La scène statique : le sol pré-rendu, les murs et les meubles, triés en profondeur.

Vue « 3/4 de dessus » (pixel-agents, Stardew Valley, Zelda: A Link to the
Past...) : ce qui est plus bas à l'écran est plus près de nous, donc dessiné
APRÈS. Chaque élément porte une clé de profondeur `z` : l'ordonnée, en
pixels, de l'endroit où il touche le sol. On trie, on dessine dans l'ordre :
c'est l'« algorithme du peintre », celui des peintres qui posent l'arrière-plan
avant les personnages.

Les règles de `z` viennent de pixel-agents (layoutSerializer.ts) :
- meuble : bas du sprite ;
- chaise : bas de sa première rangée (le personnage assis passe devant),
  sauf la chaise vue de dos, dont le dossier cache le bas du personnage ;
- objet posé sur un meuble (caisse enregistreuse sur un comptoir) : juste
  devant son support ;
- mur : bas de sa tuile. On ajoute un quart de pixel aux objets accrochés aux
  murs pour qu'ils passent devant le mur qui les porte.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pygame
import pytmx  # le moteur a le droit d'utiliser pytmx (qui importe pygame) ; le noyau, non

from pixelcity.engine.sprites import TILE, SpriteBank
from pixelcity.sim.types import TilePos
from pixelcity.world.furniture import Furniture
from pixelcity.world.world import GROUND_LAYER, World

CHUNK = 16  # côté d'un « morceau » de carte, en tuiles, pour ne trier que le visible
ANIMATION_FPS = 5  # images par seconde des objets animés (feux, écrans, eau)
WALL_ITEM_BIAS = 0.25
SURFACE_ITEM_BIAS = 0.5

_N, _E, _S, _W = 1, 2, 4, 8


@dataclass(slots=True, eq=False)
class Prop:
    """Un sprite posé dans le monde : morceau de mur ou meuble."""

    x: int
    y: int
    z: float
    off: tuple[pygame.Surface, ...]
    on: tuple[pygame.Surface, ...] = ()
    furniture: Furniture | None = None
    cover: pygame.Surface | None = None  # couverture du lit, dessinée par-dessus le dormeur

    def image(self, seconds: float) -> pygame.Surface:
        frames = (
            self.on
            if (self.on and self.furniture is not None and self.furniture.is_on)
            else self.off
        )
        if len(frames) == 1:
            return frames[0]
        return frames[int(seconds * ANIMATION_FPS) % len(frames)]

    @property
    def rect(self) -> pygame.Rect:
        first = self.off[0]
        return pygame.Rect(self.x, self.y, first.get_width(), first.get_height())


@dataclass(slots=True)
class Scene:
    width: int  # en pixels
    height: int
    ground: pygame.Surface
    props: list[Prop]
    by_furniture: dict[str, Prop] = field(default_factory=dict)
    _chunks: dict[tuple[int, int], list[Prop]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        span = CHUNK * TILE
        for prop in self.props:
            rect = prop.rect
            for cy in range(rect.top // span, (rect.bottom - 1) // span + 1):
                for cx in range(rect.left // span, (rect.right - 1) // span + 1):
                    self._chunks.setdefault((cx, cy), []).append(prop)
            if prop.furniture is not None:
                self.by_furniture[prop.furniture.uid] = prop

    def props_in(self, view: pygame.Rect) -> Iterator[Prop]:
        """Les éléments qui touchent `view` (chacun une seule fois)."""
        span = CHUNK * TILE
        seen: set[int] = set()
        for cy in range(view.top // span, (view.bottom - 1) // span + 1):
            for cx in range(view.left // span, (view.right - 1) // span + 1):
                for prop in self._chunks.get((cx, cy), ()):
                    if id(prop) not in seen and prop.rect.colliderect(view):
                        seen.add(id(prop))
                        yield prop


def bake_ground(map_path: Path, layer_name: str = GROUND_LAYER) -> pygame.Surface:
    """Pré-rend le sol de toute la carte dans une seule image (« baking »).

    Le sol ne bouge jamais : on paie 6 000 petits blits une fois au chargement,
    puis chaque image du jeu n'en copie qu'un rectangle.
    """
    tmx = pytmx.util_pygame.load_pygame(str(map_path))
    surface = pygame.Surface((tmx.width * tmx.tilewidth, tmx.height * tmx.tileheight))
    surface.fill((0, 0, 0))
    layer = tmx.get_layer_by_name(layer_name)
    for x, y, image in layer.tiles():
        surface.blit(image, (x * tmx.tilewidth, y * tmx.tileheight))
    if pygame.display.get_surface() is not None:
        surface = surface.convert()
    return surface


def build_scene(world: World, bank: SpriteBank, ground: pygame.Surface) -> Scene:
    props = [*_wall_props(world.walls, bank), *_furniture_props(world, bank)]
    return Scene(world.width * TILE, world.height * TILE, ground, props)


def wall_mask(walls: dict[TilePos, str], x: int, y: int) -> int:
    mask = 0
    if (x, y - 1) in walls:
        mask |= _N
    if (x + 1, y) in walls:
        mask |= _E
    if (x, y + 1) in walls:
        mask |= _S
    if (x - 1, y) in walls:
        mask |= _W
    return mask


def _wall_props(walls: dict[TilePos, str], bank: SpriteBank) -> Iterator[Prop]:
    for (x, y), style in walls.items():
        piece = bank.wall_piece(style, wall_mask(walls, x, y))
        # La pièce fait deux tuiles de haut : la face du mur « monte » sur la
        # tuile du dessus. Sa base reste la tuile du mur.
        yield Prop(x * TILE, y * TILE - TILE, (y + 1) * TILE, (piece,))


def _furniture_props(world: World, bank: SpriteBank) -> Iterator[Prop]:
    items = list(world.furniture.values())
    host_z: dict[TilePos, float] = {}
    for item in items:  # supports possibles : tout ce qui n'est ni mural ni posé
        if item.is_flat:
            continue
        z = _sprite_bottom(item)
        for tile in item.tiles():
            host_z[tile] = max(host_z.get(tile, 0.0), z)
    for item in items:
        variant = item.spec.variant(item.orientation)
        off = bank.frames(variant, "off")
        on = bank.frames(variant, "on") if "on" in variant.states else ()
        z = _furniture_z(item, host_z)
        cover = bank.overlay(item.spec, "occupied")
        yield Prop(item.col * TILE, item.row * TILE, z, off, on, item, cover)


def _sprite_bottom(item: Furniture) -> float:
    _width, height = item.spec.variant(item.orientation).size
    return float(item.row * TILE + height)


def _furniture_z(item: Furniture, host_z: dict[TilePos, float]) -> float:
    spec = item.spec
    _width, footprint_h = item.footprint
    if spec.category == "chairs":
        if item.orientation == "back":
            return float((item.row + footprint_h) * TILE + 1)
        return float((item.row + 1) * TILE)
    z = _sprite_bottom(item)
    if spec.on_walls:
        return z + WALL_ITEM_BIAS
    if spec.on_surfaces:
        for tile in item.tiles():
            host = host_z.get(tile)
            if host is not None and host + SURFACE_ITEM_BIAS > z:
                z = host + SURFACE_ITEM_BIAS
    return z
