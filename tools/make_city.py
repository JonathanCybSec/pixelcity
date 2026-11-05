"""Génère la ville de l'étape 2 : `pixelcity/assets/maps/city.tmx` (96×64 tuiles).

Usage :  python tools/make_city.py

La ville est construite à partir de GABARITS de bâtiments (maison, appartement,
boulangerie, café...) posés sur un plan de rues. C'est ce qui permettra de
passer à une centaine de bâtiments à l'étape 6 sans tout dessiner à la main.

Le résultat est un vrai fichier Tiled : on peut l'ouvrir, le retoucher, et le
jeu le relira tel quel. (Relancer ce script écrase les retouches.)

Produit aussi :
- `city_tiles.png` : le tileset (sols extérieurs + sols intérieurs colorisés) ;
- `walls/<style>.png` : les murs de pixel-agents colorisés, un fichier par style.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame
from pixelart import Hsbc, colorize, load

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "pixelcity" / "assets"
OUT = ASSETS / "maps"
TILE = 16
MAP_W, MAP_H = 128, 64  # étape 6 : la ville s'étend vers l'est
COLUMNS = 8

# --------------------------------------------------------------------------- #
# Tileset : sols extérieurs (nos dessins) et intérieurs (pixel-agents colorisés)
# --------------------------------------------------------------------------- #
# nom → (source, coût). Coût 0 = infranchissable.
GROUND: dict[str, tuple[str, int]] = {
    "grass_0": ("grass_0", 3),
    "grass_1": ("grass_1", 3),
    "grass_2": ("grass_2", 3),
    "grass_flowers": ("grass_flowers", 3),
    "sidewalk": ("sidewalk", 1),
    "road": ("road", 8),
    "road_line_h": ("road_line_h", 8),
    "road_line_v": ("road_line_v", 8),
    "crosswalk_h": ("crosswalk_h", 1),
    "crosswalk_v": ("crosswalk_v", 1),
    "path": ("path", 1),
    "gravel": ("gravel", 1),
    "water_0": ("water_0", 0),
    "water_1": ("water_1", 0),
    **{
        f"water_{side}": (f"water_{side}", 0)
        for side in ("n", "s", "e", "w", "ne", "nw", "se", "sw")
    },
    "plaza": ("plaza", 1),
    "doormat": ("doormat", 1),
}
# Sols intérieurs : motif de pixel-agents (floor_N.png) + réglage de couleur.
FLOORS: dict[str, tuple[int, Hsbc]] = {
    "wood_warm": (6, Hsbc(25, 48, -43, -88)),  # le parquet du bureau de pixel-agents
    "wood_light": (5, Hsbc(32, 42, -8, -72)),
    "checker_gray": (8, Hsbc(209, 0, -16, -8)),
    "checker_warm": (7, Hsbc(22, 38, -12, -35)),
    "tile_white": (3, Hsbc(210, 8, 22, -55)),
    "tile_blue": (3, Hsbc(200, 32, 8, -55)),
    "carpet_blue": (0, Hsbc(209, 39, -25, -80)),
    "carpet_rose": (0, Hsbc(345, 30, -12, -80)),
    "lino": (4, Hsbc(40, 18, 14, -65)),
    "rubber": (0, Hsbc(215, 12, -30, -72)),
}
# Murs : wall_0.png de pixel-agents colorisé (mode Colorize, comme dans leur éditeur).
WALLS: dict[str, Hsbc] = {
    "navy": Hsbc(214, 30, -100, -55),  # les murs du bureau de pixel-agents
    "cream": Hsbc(36, 34, -30, -60),
    "lilac": Hsbc(268, 22, -38, -60),
    "rose": Hsbc(350, 30, -40, -58),
    "brick": Hsbc(12, 48, -62, -50),
    "sage": Hsbc(110, 18, -55, -58),
    "slate": Hsbc(210, 14, -66, -55),
    "sand": Hsbc(42, 32, -48, -60),
    "sky": Hsbc(200, 26, -45, -58),
}


@dataclass
class Tileset:
    names: list[str] = field(default_factory=list)
    surfaces: list[pygame.Surface] = field(default_factory=list)
    props: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, surface: pygame.Surface, **props: object) -> None:
        self.names.append(name)
        self.surfaces.append(surface)
        self.props.append({"kind": name, **props})

    def gid(self, name: str) -> int:
        return self.names.index(name) + 1


def build_tileset() -> Tileset:
    tiles = Tileset()
    ground_dir = ASSETS / "pixelcity" / "ground"
    for name, (source, cost) in GROUND.items():
        props: dict[str, object] = {"walkable": cost > 0}
        if cost:
            props["cost"] = cost
        tiles.add(name, load(ground_dir / f"{source}.png"), **props)
    floors_dir = ASSETS / "pixel_agents" / "floors"
    for name, (pattern, color) in FLOORS.items():
        tiles.add(
            name, colorize(load(floors_dir / f"floor_{pattern}.png"), color), walkable=True, cost=1
        )
    walls_png = load(ASSETS / "pixel_agents" / "walls" / "wall_0.png")
    (OUT / "walls").mkdir(parents=True, exist_ok=True)
    for style, color in WALLS.items():
        sheet = colorize(walls_png, color)
        pygame.image.save(sheet, str(OUT / "walls" / f"{style}.png"))
        # Aperçu pour Tiled : le bas de la pièce « mur horizontal » (masque E+W = 10).
        marker = sheet.subsurface(pygame.Rect((10 % 4) * 16, (10 // 4) * 32 + 16, 16, 16)).copy()
        tiles.add(f"wall_{style}", marker, walkable=False, wall_style=style)
    return tiles


# --------------------------------------------------------------------------- #
# Le plan de la ville
# --------------------------------------------------------------------------- #
@dataclass
class FurnitureObj:
    type: str
    x: int
    y: int
    w: int
    h: int
    orientation: str
    place_id: str


class City:
    def __init__(self, tiles: Tileset) -> None:
        self.tiles = tiles
        self.ground = [tiles.gid("grass_0")] * (MAP_W * MAP_H)
        self.walls = [0] * (MAP_W * MAP_H)
        self.places: list[tuple[str, str, int, int, int, int]] = []
        self.rooms: list[tuple[str, str, str, int, int, int, int]] = []
        self.furniture: list[FurnitureObj] = []
        self._sizes = _footprints()

    # -- sol et murs -----------------------------------------------------------------
    def set(self, x: int, y: int, name: str) -> None:
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            self.ground[y * MAP_W + x] = self.tiles.gid(name)
            self.walls[y * MAP_W + x] = 0

    def fill(self, x0: int, y0: int, x1: int, y1: int, name: str) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, name)

    def wall(self, x: int, y: int, style: str) -> None:
        self.walls[y * MAP_W + x] = self.tiles.gid(f"wall_{style}")

    def wall_line(self, x0: int, y0: int, x1: int, y1: int, style: str) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.wall(x, y, style)

    def door(self, x: int, y: int, floor: str) -> None:
        self.walls[y * MAP_W + x] = 0
        self.ground[y * MAP_W + x] = self.tiles.gid(floor)

    def building(self, x0: int, y0: int, w: int, h: int, style: str, floor: str) -> None:
        """Quatre murs et un sol ; les portes s'ouvrent ensuite avec `door`."""
        self.fill(x0, y0, x0 + w - 1, y0 + h - 1, floor)
        self.wall_line(x0, y0, x0 + w - 1, y0, style)
        self.wall_line(x0, y0 + h - 1, x0 + w - 1, y0 + h - 1, style)
        self.wall_line(x0, y0, x0, y0 + h - 1, style)
        self.wall_line(x0 + w - 1, y0, x0 + w - 1, y0 + h - 1, style)

    # -- objets ------------------------------------------------------------------------
    def place(self, place_id: str, name: str, x0: int, y0: int, w: int, h: int) -> None:
        self.places.append((place_id, name, x0, y0, w, h))

    def room(self, label: str, kind: str, place_id: str, x0: int, y0: int, w: int, h: int) -> None:
        self.rooms.append((label, kind, place_id, x0, y0, w, h))

    def put(self, type_id: str, x: int, y: int, place_id: str, orientation: str = "front") -> None:
        w, h = self._sizes[(type_id, orientation)]
        self.furniture.append(FurnitureObj(type_id, x, y, w, h, orientation, place_id))


def _footprints() -> dict[tuple[str, str], tuple[int, int]]:
    """Emprises lues dans le catalogue (le même code que le jeu)."""
    sys.path.insert(0, str(ROOT))
    from pixelcity.world.catalog import load_catalog

    catalog = load_catalog(ASSETS / "pixel_agents", ASSETS / "pixelcity")
    sizes: dict[tuple[str, str], tuple[int, int]] = {}
    for spec in catalog.specs.values():
        for orientation, variant in spec.variants.items():
            sizes[(spec.id, orientation)] = variant.footprint
    return sizes


# --------------------------------------------------------------------------- #
# Gabarits de bâtiments (coordonnées relatives au coin haut-gauche)
# --------------------------------------------------------------------------- #
def house(
    city: City, place_id: str, name: str, x0: int, y0: int, style: str, floor: str, carpet: str
) -> None:
    """Maison 14×11 : séjour-cuisine, chambre, salle de bain, porte au sud.

    Piège de la vue 3/4 : la face du mur sud « monte » sur la dernière rangée
    intérieure et la cache à moitié. On n'y pose donc aucun meuble.
    """
    w, h = 14, 11
    city.building(x0, y0, w, h, style, floor)
    city.fill(x0 + 9, y0 + 1, x0 + 12, y0 + 4, carpet)
    city.fill(x0 + 9, y0 + 6, x0 + 12, y0 + 9, "tile_blue")
    city.wall_line(x0 + 8, y0 + 1, x0 + 8, y0 + 9, style)  # cloison séjour | chambres
    city.wall_line(x0 + 9, y0 + 5, x0 + 12, y0 + 5, style)  # cloison chambre | bain
    city.door(x0 + 8, y0 + 3, carpet)
    city.door(x0 + 8, y0 + 7, "tile_blue")
    city.door(x0 + 4, y0 + h - 1, floor)
    city.set(x0 + 4, y0 + h, "doormat")
    city.place(place_id, name, x0, y0, w, h)
    city.room("séjour", "living", place_id, x0 + 1, y0 + 1, 7, 9)
    city.room("chambre", "bedroom", place_id, x0 + 9, y0 + 1, 4, 4)
    city.room("salle de bain", "bathroom", place_id, x0 + 9, y0 + 6, 4, 4)
    p = place_id
    for dx, kind in enumerate(("FRIDGE", "STOVE", "KITCHEN_SINK", "KITCHEN_COUNTER")):
        city.put(kind, x0 + 1 + dx, y0, p)
    city.put("TV", x0 + 5, y0, p)
    city.put("SOFA", x0 + 5, y0 + 4, p, "back")
    city.put("SMALL_TABLE", x0 + 2, y0 + 6, p)
    city.put("WOODEN_CHAIR", x0 + 1, y0 + 6, p, "side")
    city.put("WOODEN_CHAIR", x0 + 4, y0 + 6, p, "left")
    city.put("PLANT", x0 + 7, y0 + 7, p)
    city.put("HANGING_PLANT", x0 + 7, y0 - 1, p)
    city.put("BED", x0 + 10, y0, p)
    city.put("NIGHTSTAND", x0 + 11, y0 + 1, p)
    city.put("WARDROBE", x0 + 12, y0, p)
    city.put("SHOWER", x0 + 9, y0 + 5, p)
    city.put("WASHBASIN", x0 + 11, y0 + 5, p)
    city.put("TOILET", x0 + 12, y0 + 5, p)
    city.put("WINDOW", x0 + 2, y0 + h - 2, p)
    city.put("WINDOW", x0 + 10, y0 + h - 2, p)


def apartment(city: City, place_id: str, name: str, x0: int, y0: int, style: str) -> None:
    """Appartement 10×11 (murs partagés avec les voisins) : pièce de vie, chambre, bain."""
    w, h = 10, 11
    city.building(x0, y0, w, h, style, "wood_light")
    city.fill(x0 + 6, y0 + 1, x0 + 8, y0 + 4, "carpet_blue")
    city.fill(x0 + 6, y0 + 6, x0 + 8, y0 + 9, "tile_white")
    city.wall_line(x0 + 5, y0 + 1, x0 + 5, y0 + 9, style)
    city.wall_line(x0 + 6, y0 + 5, x0 + 8, y0 + 5, style)
    city.door(x0 + 5, y0 + 3, "carpet_blue")
    city.door(x0 + 5, y0 + 7, "tile_white")
    city.door(x0 + 2, y0 + h - 1, "wood_light")
    city.set(x0 + 2, y0 + h, "doormat")
    city.place(place_id, name, x0, y0, w, h)
    city.room("pièce de vie", "living", place_id, x0 + 1, y0 + 1, 4, 9)
    city.room("chambre", "bedroom", place_id, x0 + 6, y0 + 1, 3, 4)
    city.room("salle de bain", "bathroom", place_id, x0 + 6, y0 + 6, 3, 4)
    p = place_id
    for dx, kind in enumerate(("FRIDGE", "STOVE", "KITCHEN_SINK", "KITCHEN_COUNTER")):
        city.put(kind, x0 + 1 + dx, y0, p)
    # Piège de gabarit : table + deux chaises de chaque côté = 4 cases, toute
    # la largeur de la pièce. La rangée devient un mur et coupe la cuisine et
    # la chambre du reste de l'appartement. On garde la colonne de droite libre.
    city.put("SMALL_TABLE", x0 + 1, y0 + 3, p)
    city.put("WOODEN_CHAIR", x0 + 3, y0 + 3, p, "left")
    city.put("WOODEN_CHAIR", x0 + 1, y0 + 4, p, "back")
    city.put("SOFA", x0 + 2, y0 + 8, p, "front")
    city.put("PLANT_2", x0 + 4, y0 + 5, p)
    city.put("BED", x0 + 7, y0, p)
    city.put("WARDROBE", x0 + 8, y0, p)
    city.put("SHOWER", x0 + 6, y0 + 5, p)
    city.put("WASHBASIN", x0 + 7, y0 + 5, p)
    city.put("TOILET", x0 + 8, y0 + 5, p)
    city.put("WINDOW", x0 + 7, y0 + h - 2, p)


def bakery(city: City, x0: int, y0: int) -> None:
    """Boulangerie 12×11, porte au nord : fournil derrière, vitrine, deux places assises."""
    p, w, h = "boulangerie", 12, 11
    city.building(x0, y0, w, h, "brick", "checker_warm")
    city.door(x0 + 2, y0, "checker_warm")
    city.set(x0 + 2, y0 - 1, "doormat")
    city.wall_line(x0 + 1, y0 + 6, x0 + 3, y0 + 6, "brick")  # WC du personnel
    city.wall_line(x0 + 3, y0 + 7, x0 + 3, y0 + 9, "brick")
    city.door(x0 + 3, y0 + 8, "tile_white")
    city.fill(x0 + 1, y0 + 7, x0 + 2, y0 + 9, "tile_white")
    city.place(p, "Boulangerie du Coin", x0, y0, w, h)
    city.room("fournil", "workshop", p, x0 + 4, y0 + 1, 7, 3)
    city.room("boutique", "shop", p, x0 + 4, y0 + 5, 7, 5)
    city.room("toilettes", "bathroom", p, x0 + 1, y0 + 7, 2, 3)
    city.put("TOILET", x0 + 2, y0 + 6, p)
    city.put("WASHBASIN", x0 + 1, y0 + 6, p)
    city.put("BREAD_OVEN", x0 + 5, y0, p)
    city.put("BREAD_SHELF", x0 + 8, y0 - 1, p)
    city.put("WORKBENCH", x0 + 8, y0 + 2, p)
    city.put("BAKERY_COUNTER", x0 + 5, y0 + 4, p)
    city.put("CASH_REGISTER", x0 + 7, y0 + 4, p)
    city.put("SMALL_TABLE", x0 + 9, y0 + 6, p)
    city.put("WOODEN_CHAIR", x0 + 8, y0 + 6, p, "side")
    city.put("WOODEN_CHAIR", x0 + 9, y0 + 8, p, "back")
    city.put("PLANT", x0 + 10, y0, p)


def cafe(city: City, x0: int, y0: int) -> None:
    """Café 14×11, porte au nord : comptoir, deux tables, toilettes."""
    p, w, h = "cafe", 14, 11
    city.building(x0, y0, w, h, "sage", "checker_gray")
    city.door(x0 + 2, y0, "checker_gray")
    city.set(x0 + 2, y0 - 1, "doormat")
    city.wall_line(x0 + 10, y0 + 5, x0 + 10, y0 + 9, "sage")  # toilettes
    city.wall_line(x0 + 11, y0 + 5, x0 + 12, y0 + 5, "sage")
    city.door(x0 + 10, y0 + 8, "tile_white")
    city.fill(x0 + 11, y0 + 6, x0 + 12, y0 + 9, "tile_white")
    city.place(p, "Café des Arts", x0, y0, w, h)
    city.room("salle", "shop", p, x0 + 1, y0 + 1, 9, 9)
    city.room("toilettes", "bathroom", p, x0 + 11, y0 + 6, 2, 4)
    city.put("MENU_BOARD", x0 + 9, y0 - 1, p)
    city.put("KITCHEN_COUNTER", x0 + 12, y0, p)
    city.put("CAFE_COUNTER", x0 + 8, y0 + 3, p)
    city.put("ESPRESSO_MACHINE", x0 + 10, y0 + 3, p)
    city.put("CASH_REGISTER", x0 + 8, y0 + 3, p)
    for tx, ty in ((2, 4), (2, 7), (5, 1)):
        city.put("SMALL_TABLE", x0 + tx, y0 + ty, p)
        city.put("WOODEN_CHAIR", x0 + tx - 1, y0 + ty, p, "side")
        city.put("WOODEN_CHAIR", x0 + tx + 2, y0 + ty, p, "left")
    city.put("TOILET", x0 + 12, y0 + 5, p)
    city.put("WASHBASIN", x0 + 11, y0 + 5, p)
    city.put("LARGE_PLANT", x0 + 6, y0 + 6, p)


def supermarket(city: City, x0: int, y0: int) -> None:
    """Supermarché 24×13 : trois rangées de rayons, une caisse, une réserve avec WC."""
    p, w, h = "supermarche", 24, 13
    city.building(x0, y0, w, h, "slate", "lino")
    city.door(x0 + 3, y0, "lino")
    city.set(x0 + 3, y0 - 1, "doormat")
    city.wall_line(x0 + 19, y0 + 1, x0 + 19, y0 + 4, "slate")  # réserve du personnel
    city.wall_line(x0 + 20, y0 + 4, x0 + 22, y0 + 4, "slate")
    city.door(x0 + 19, y0 + 2, "tile_white")
    city.fill(x0 + 20, y0 + 1, x0 + 22, y0 + 3, "tile_white")
    city.place(p, "Supermarché Fraîcheur", x0, y0, w, h)
    city.room("magasin", "shop", p, x0 + 1, y0 + 1, w - 2, h - 2)
    city.room("réserve", "bathroom", p, x0 + 20, y0 + 1, 3, 3)
    kinds = ("SHELF_DRINKS", "SHELF_GROCERY", "SHELF_PRODUCE", "SHELF_DRINKS", "SHELF_GROCERY")
    for row, order in ((0, kinds), (4, kinds[::-1]), (8, kinds[1:] + kinds[:1])):
        for i, kind in enumerate(order):
            city.put(kind, x0 + 6 + 2 * i, y0 + row, p)
    city.put("CHECKOUT", x0 + 18, y0 + 6, p)
    city.put("TOILET", x0 + 22, y0, p)
    city.put("WASHBASIN", x0 + 21, y0, p)
    city.put("PLANT", x0 + 1, y0 + 9, p)
    city.put("BIN", x0 + 17, y0 + 10, p)


def casino(city: City, x0: int, y0: int) -> None:
    """Casino 20×11, porte au sud : machines à sous le long du mur, roulette, toilettes."""
    p, w, h = "casino", 20, 11
    city.building(x0, y0, w, h, "navy", "carpet_rose")
    city.door(x0 + 9, y0 + h - 1, "carpet_rose")
    city.set(x0 + 9, y0 + h, "doormat")
    city.wall_line(x0 + 16, y0 + 1, x0 + 16, y0 + 4, "navy")  # toilettes
    city.wall_line(x0 + 17, y0 + 4, x0 + 18, y0 + 4, "navy")
    city.door(x0 + 16, y0 + 3, "tile_white")
    city.fill(x0 + 17, y0 + 1, x0 + 18, y0 + 3, "tile_white")
    city.place(p, "Casino Le Lucky", x0, y0, w, h)
    city.room("salle de jeu", "shop", p, x0 + 1, y0 + 1, 15, 8)
    city.room("toilettes", "bathroom", p, x0 + 17, y0 + 1, 2, 3)
    for dx in range(1, 15, 2):
        city.put("SLOT_MACHINE", x0 + dx, y0, p)
    city.put("ROULETTE_TABLE", x0 + 5, y0 + 4, p)
    city.put("ROULETTE_TABLE", x0 + 11, y0 + 4, p)
    city.put("TOILET", x0 + 18, y0, p)
    city.put("WASHBASIN", x0 + 17, y0, p)
    city.put("LARGE_PLANT", x0 + 1, y0 + 7, p)
    city.put("LARGE_PLANT", x0 + 17, y0 + 7, p)


def bar(city: City, x0: int, y0: int) -> None:
    """Bar 14×11, porte au sud : comptoir, tables, toilettes."""
    p, w, h = "bar", 14, 11
    city.building(x0, y0, w, h, "brick", "wood_warm")
    city.door(x0 + 4, y0 + h - 1, "wood_warm")
    city.set(x0 + 4, y0 + h, "doormat")
    city.wall_line(x0 + 10, y0 + 1, x0 + 10, y0 + 4, "brick")
    city.wall_line(x0 + 11, y0 + 4, x0 + 12, y0 + 4, "brick")
    city.door(x0 + 10, y0 + 3, "tile_white")
    city.fill(x0 + 11, y0 + 1, x0 + 12, y0 + 3, "tile_white")
    city.place(p, "Bar Le Zinc", x0, y0, w, h)
    city.room("salle", "shop", p, x0 + 1, y0 + 1, 9, 8)
    city.room("toilettes", "bathroom", p, x0 + 11, y0 + 1, 2, 3)
    city.put("SHELF_DRINKS", x0 + 2, y0, p)
    city.put("BAR_COUNTER", x0 + 2, y0 + 2, p)
    for tx, ty in ((5, 2), (6, 6)):
        city.put("SMALL_TABLE", x0 + tx, y0 + ty, p)
        city.put("WOODEN_CHAIR", x0 + tx - 1, y0 + ty, p, "side")
        city.put("WOODEN_CHAIR", x0 + tx + 2, y0 + ty, p, "left")
    city.put("TOILET", x0 + 12, y0, p)
    city.put("WASHBASIN", x0 + 11, y0, p)
    city.put("PLANT", x0 + 12, y0 + 7, p)


def store(
    city: City,
    p: str,
    name: str,
    x0: int,
    y0: int,
    style: str,
    floor: str,
    counter: str,
    shelf: str,
) -> None:
    """Boutique 14×11, porte au nord : deux rangées de présentoirs, une caisse."""
    w, h = 14, 11
    city.building(x0, y0, w, h, style, floor)
    city.door(x0 + 2, y0, floor)
    city.set(x0 + 2, y0 - 1, "doormat")
    city.place(p, name, x0, y0, w, h)
    city.room("magasin", "shop", p, x0 + 1, y0 + 1, w - 2, h - 2)
    for i in range(4):
        city.put(shelf, x0 + 4 + 2 * i, y0 + 2, p)
        city.put(shelf, x0 + 4 + 2 * i, y0 + 6, p)
    city.put(counter, x0 + 11, y0 + 4, p)
    city.put("PLANT", x0 + 1, y0 + 8, p)


def office(city: City, x0: int, y0: int) -> None:
    """Bureaux 22×14 dans le style de pixel-agents : six postes, coin café, réunion."""
    p, w, h = "bureaux", 22, 14
    city.building(x0, y0, w, h, "navy", "wood_warm")
    city.door(x0 + 10, y0 + h - 1, "wood_warm")
    city.set(x0 + 10, y0 + h, "doormat")
    city.fill(x0 + 15, y0 + 6, x0 + 20, y0 + 12, "carpet_blue")
    city.place(p, "Bureaux Horizon", x0, y0, w, h)
    city.wall_line(x0 + 18, y0 + 1, x0 + 18, y0 + 4, "navy")  # toilettes
    city.wall_line(x0 + 19, y0 + 4, x0 + 20, y0 + 4, "navy")
    city.door(x0 + 18, y0 + 2, "tile_white")
    city.fill(x0 + 19, y0 + 1, x0 + 20, y0 + 3, "tile_white")
    city.room("open space", "office", p, x0 + 1, y0 + 1, 14, 12)
    city.room("toilettes", "bathroom", p, x0 + 19, y0 + 1, 2, 3)
    city.room("salle de réunion", "meeting", p, x0 + 15, y0 + 6, 6, 7)
    for row in (1, 6):
        for dx in (1, 5, 9):
            city.put("DESK", x0 + dx, y0 + row, p)
            city.put("PC", x0 + dx + 1, y0 + row, p)
            city.put("CUSHIONED_CHAIR", x0 + dx + 1, y0 + row + 2, p, "back")
    city.put("DOUBLE_BOOKSHELF", x0 + 13, y0 - 1, p)
    city.put("WHITEBOARD", x0 + 9, y0 - 1, p)
    city.put("KITCHEN_COUNTER", x0 + 16, y0, p)
    city.put("KITCHEN_COUNTER", x0 + 17, y0, p)
    # Un objet « posé » se met sur la PREMIÈRE rangée du meuble (son dessus).
    city.put("ESPRESSO_MACHINE", x0 + 17, y0, p)
    city.put("TOILET", x0 + 20, y0, p)
    city.put("WASHBASIN", x0 + 19, y0, p)
    city.put("TABLE_FRONT", x0 + 17, y0 + 7, p)
    city.put("WOODEN_CHAIR", x0 + 16, y0 + 7, p, "side")
    city.put("WOODEN_CHAIR", x0 + 16, y0 + 9, p, "side")
    city.put("WOODEN_CHAIR", x0 + 20, y0 + 7, p, "left")
    city.put("WOODEN_CHAIR", x0 + 20, y0 + 9, p, "left")
    city.put("LARGE_PLANT", x0 + 1, y0 + 9, p)
    city.put("PLANT", x0 + 14, y0 + 10, p)
    city.put("CLOCK", x0 + 6, y0 - 1, p)


def school(city: City, x0: int, y0: int) -> None:
    """École 26×16 : une classe et une cantine, toilettes."""
    p, w, h = "ecole", 26, 16
    city.building(x0, y0, w, h, "sand", "wood_light")
    city.door(x0 + 4, y0, "wood_light")
    city.set(x0 + 4, y0 - 1, "doormat")
    city.wall_line(x0 + 15, y0 + 1, x0 + 15, y0 + 14, "sand")
    city.door(x0 + 15, y0 + 4, "tile_white")
    city.door(x0 + 15, y0 + 11, "tile_white")
    city.fill(x0 + 16, y0 + 1, x0 + 24, y0 + 14, "tile_white")
    city.wall_line(x0 + 21, y0 + 10, x0 + 24, y0 + 10, "sand")  # toilettes
    city.wall_line(x0 + 21, y0 + 11, x0 + 21, y0 + 14, "sand")
    city.door(x0 + 21, y0 + 12, "tile_blue")
    city.fill(x0 + 22, y0 + 11, x0 + 24, y0 + 14, "tile_blue")
    city.place(p, "École Jules-Ferry", x0, y0, w, h)
    city.room("salle de classe", "classroom", p, x0 + 1, y0 + 1, 14, 14)
    city.room("cantine", "canteen", p, x0 + 16, y0 + 1, 9, 9)
    city.room("toilettes", "bathroom", p, x0 + 22, y0 + 11, 3, 4)
    city.put("WHITEBOARD", x0 + 6, y0 - 1, p)
    city.put("CLOCK", x0 + 10, y0 - 1, p)
    city.put("DESK", x0 + 2, y0 + 2, p)
    city.put("CUSHIONED_CHAIR", x0 + 3, y0 + 4, p, "back")
    for ty in (6, 10):
        for tx in (4, 8, 12):
            city.put("SMALL_TABLE", x0 + tx - 1, y0 + ty, p)
            city.put("CUSHIONED_BENCH", x0 + tx - 1, y0 + ty + 2, p)
            city.put("CUSHIONED_BENCH", x0 + tx, y0 + ty + 2, p)
    city.put("DOUBLE_BOOKSHELF", x0 + 12, y0 - 1, p)
    city.put("TABLE_FRONT", x0 + 18, y0 + 2, p)
    for ty in (2, 4):
        city.put("WOODEN_CHAIR", x0 + 17, y0 + ty, p, "side")
        city.put("WOODEN_CHAIR", x0 + 21, y0 + ty, p, "left")
    city.put("TOILET", x0 + 24, y0 + 10, p)
    city.put("WASHBASIN", x0 + 23, y0 + 10, p)
    city.put("PLANT", x0 + 16, y0 + 12, p)


def gym(city: City, x0: int, y0: int) -> None:
    """Salle de sport 18×11 : plateau (tapis, bancs) et vestiaire (douches, WC)."""
    p, w, h = "salle_de_sport", 18, 11
    city.building(x0, y0, w, h, "slate", "rubber")
    city.door(x0 + 2, y0, "rubber")
    city.set(x0 + 2, y0 - 1, "doormat")
    city.wall_line(x0 + 11, y0 + 1, x0 + 11, y0 + 9, "slate")
    city.door(x0 + 11, y0 + 6, "tile_white")
    city.fill(x0 + 12, y0 + 1, x0 + 16, y0 + 9, "tile_white")
    city.place(p, "Salle de sport Olympe", x0, y0, w, h)
    city.room("plateau", "gym", p, x0 + 1, y0 + 1, 10, h - 2)
    city.room("vestiaire", "bathroom", p, x0 + 12, y0 + 1, 5, h - 2)
    for dx in (4, 6, 8, 10):
        city.put("TREADMILL", x0 + dx, y0, p)
    for dx in (3, 6, 9):
        city.put("WEIGHT_BENCH", x0 + dx, y0 + 5, p)
    for dx in (12, 13):
        city.put("SHOWER", x0 + dx, y0, p)
    city.put("WASHBASIN", x0 + 14, y0, p)
    city.put("TOILET", x0 + 16, y0, p)
    city.put("WOODEN_BENCH", x0 + 14, y0 + 5, p)
    city.put("WOODEN_BENCH", x0 + 15, y0 + 5, p)
    city.put("LARGE_PLANT", x0 + 1, y0 + 6, p)
    city.put("BIN", x0 + 10, y0 + 8, p)
    city.put("PLANT", x0 + 16, y0 + 7, p)


def pond(city: City, x0: int, y0: int, x1: int, y1: int) -> None:
    """Étang rectangulaire aux berges arrondies (tuiles de bord dessinées par draw_assets)."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            side = ("n" if y == y0 else "s" if y == y1 else "") + (
                "w" if x == x0 else "e" if x == x1 else ""
            )
            city.set(
                x, y, f"water_{side}" if side else ("water_1" if (x + y) % 3 == 0 else "water_0")
            )


def park(city: City, x0: int, y0: int, x1: int, y1: int) -> None:
    """Parc entouré d'une haie, avec allées, étang, arbres et bancs."""
    p = "parc"
    city.fill(x0, y0, x1, y1, "grass_1")
    openings = {(x0 + 13, y0), (x0 + 14, y0), (x1, y0 + 13), (x1, y0 + 14)}
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            if (x, y) not in openings:
                city.put("HEDGE", x, y, p)
    for y in range(y0 + 1, y1):
        for x in (x0, x1):
            if (x, y) not in openings:
                city.put("HEDGE_V", x, y, p)
    city.fill(x0 + 13, y0 + 1, x0 + 14, y1 - 2, "gravel")  # allée nord-sud
    city.fill(x0 + 2, y0 + 13, x1 - 1, y0 + 14, "gravel")  # allée est-ouest
    pond(city, x0 + 4, y0 + 3, x0 + 11, y0 + 9)
    for x, y in ((x0 + 3, y0 + 17), (x0 + 18, y0 + 20), (x0 + 23, y0 + 6), (x0 + 7, y0 + 22)):
        city.fill(x, y, x + 1, y + 1, "grass_flowers")
    city.place(p, "Parc du Lac", x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    for bx, by in ((x0 + 16, y0 + 11), (x0 + 5, y0 + 11), (x0 + 16, y0 + 16), (x0 + 9, y0 + 16)):
        city.put("PARK_BENCH", bx, by, p)
    trees = ((2, 2), (17, 3), (21, 8), (24, 15), (3, 19), (19, 22), (11, 24), (24, 24), (6, 25))
    for i, (tx, ty) in enumerate(trees):
        city.put("TREE_ROUND" if i % 3 else "TREE_PINE", x0 + tx, y0 + ty, p)
    for bx, by in ((x0 + 12, y0 + 4), (x0 + 22, y0 + 19), (x0 + 2, y0 + 15), (x0 + 16, y0 + 25)):
        city.put("BUSH", bx, by, p)
    city.put("LAMPPOST", x0 + 15, y0 + 10, p)
    city.put("LAMPPOST", x0 + 12, y0 + 16, p)


# --------------------------------------------------------------------------- #
# Assemblage
# --------------------------------------------------------------------------- #
def streets(city: City) -> None:
    """Une avenue est-ouest et deux rues nord-sud, trottoirs et passages piétons."""
    city.fill(0, 29, MAP_W - 1, 29, "sidewalk")
    city.fill(0, 32, MAP_W - 1, 32, "sidewalk")
    city.fill(0, 30, MAP_W - 1, 30, "road_line_h")
    city.fill(0, 31, MAP_W - 1, 31, "road")
    for road_x in (31, 63, 95):
        city.fill(road_x - 1, 0, road_x - 1, MAP_H - 1, "sidewalk")
        city.fill(road_x + 2, 0, road_x + 2, MAP_H - 1, "sidewalk")
        city.fill(road_x, 0, road_x, MAP_H - 1, "road_line_v")
        city.fill(road_x + 1, 0, road_x + 1, MAP_H - 1, "road")
        city.fill(road_x, 30, road_x + 1, 31, "road")  # carrefour
        for y in (14, 29, 32, 47):
            city.fill(road_x, y, road_x + 1, y, "crosswalk_v")
    for x in (15, 30, 33, 47, 62, 65, 80, 94, 97, 112):
        city.fill(x, 30, x, 31, "crosswalk_h")


def street_trees(city: City) -> None:
    """Un peu de verdure le long des rues, sans jamais bloquer un trottoir."""
    for x, y in ((35, 2), (36, 9), (57, 2), (58, 9)):
        city.put("TREE_ROUND", x, y, "")
    for x, y in ((92, 1), (91, 8)):
        city.put("TREE_ROUND" if x % 2 else "TREE_PINE", x, y, "")
    for x, y in ((50, 12), (55, 12)):
        city.put("PARK_BENCH", x, y, "")
    for x, y in ((34, 45), (61, 45), (66, 50), (126, 13)):
        city.put("LAMPPOST", x, y, "")
    for x in range(1, 30, 4):
        city.put("BUSH", x, 0, "")


def build_city(tiles: Tileset) -> City:
    city = City(tiles)
    for x in range(MAP_W):  # herbe un peu variée
        for y in range(MAP_H):
            city.set(x, y, ("grass_0", "grass_1", "grass_2")[(x * 7 + y * 13) % 3])
    streets(city)

    # Quartier résidentiel (nord-ouest) : quatre maisons et leurs allées.
    city.fill(1, 14, 29, 14, "path")
    for x0, y0, place_id, name, style, floor, carpet in (
        (1, 2, "maison_lilas", "Maison des Lilas", "lilac", "wood_warm", "carpet_blue"),
        (16, 2, "maison_girard", "Maison Girard", "cream", "wood_light", "carpet_rose"),
        (1, 16, "maison_dupont", "Maison Dupont", "sand", "wood_warm", "carpet_rose"),
        (16, 16, "maison_benali", "Maison Benali", "sky", "wood_light", "carpet_blue"),
    ):
        house(city, place_id, name, x0, y0, style, floor, carpet)
        city.set(x0 + 4, y0 + 12, "path")
    # Résidence des Tilleuls (nord, au centre) : trois appartements mitoyens.
    for k, place_id in enumerate(("appart_1", "appart_2", "appart_3")):
        apartment(city, place_id, f"Appartement {k + 1} (Tilleuls)", 34 + 9 * k, 16, "rose")
        city.set(34 + 9 * k + 2, 28, "path")
    city.fill(34, 14, 61, 14, "path")

    office(city, 67, 14)  # nord-est
    city.set(77, 28, "path")
    park(city, 1, 34, 28, 62)  # sud-ouest
    city.fill(29, 47, 29, 48, "path")
    # Commerces (sud, au centre) autour d'une petite place.
    bakery(city, 35, 34)
    cafe(city, 48, 34)
    city.fill(34, 45, 61, 47, "plaza")
    supermarket(city, 36, 48)
    # École et salle de sport (sud-est).
    school(city, 67, 34)
    city.fill(66, 50, 94, 51, "path")
    gym(city, 70, 52)
    # Étape 6 : quartier des Mimosas (est), six appartements de part et d'autre de l'avenue.
    for k in range(3):
        x0 = 99 + 9 * k
        apartment(city, f"mimosas_{k + 1}", f"Mimosas {k + 1}", x0, 16, "sage")
        city.set(x0 + 2, 28, "path")
        apartment(city, f"mimosas_{k + 4}", f"Mimosas {k + 4}", x0, 34, "sage")
        city.fill(x0 + 2, 46, x0 + 2, 47, "path")
    city.fill(98, 14, 126, 14, "path")
    city.fill(98, 48, 126, 48, "path")
    city.fill(98, 46, 98, 48, "path")
    # Étape 6 ter : les tentations. Bar et casino au nord, boutiques au sud-est.
    bar(city, 41, 1)
    city.fill(45, 12, 45, 13, "path")
    casino(city, 70, 1)
    city.fill(66, 13, 94, 13, "path")
    city.set(79, 12, "path")
    store(
        city,
        "boutique",
        "Boutique Mode & Co",
        99,
        50,
        "rose",
        "wood_light",
        "BOUTIQUE_COUNTER",
        "CLOTHES_RACK",
    )
    store(city, "hitech", "Hi-Tech Center", 113, 50, "slate", "lino", "TECH_COUNTER", "TECH_SHELF")
    street_trees(city)
    return city


def _csv(layer: list[int]) -> str:
    rows = [",".join(str(v) for v in layer[y * MAP_W : (y + 1) * MAP_W]) for y in range(MAP_H)]
    return "\n" + ",\n".join(rows) + "\n"


def write_tmx(city: City, tiles: Tileset, path: Path, sheet: tuple[int, int]) -> None:
    root = ET.Element(
        "map",
        version="1.10",
        tiledversion="1.11.0",
        orientation="orthogonal",
        renderorder="right-down",
        width=str(MAP_W),
        height=str(MAP_H),
        tilewidth=str(TILE),
        tileheight=str(TILE),
        infinite="0",
        nextlayerid="6",
        nextobjectid=str(len(city.places) + len(city.rooms) + len(city.furniture) + 1),
    )
    tileset = ET.SubElement(
        root,
        "tileset",
        firstgid="1",
        name="city",
        tilewidth=str(TILE),
        tileheight=str(TILE),
        tilecount=str(len(tiles.names)),
        columns=str(COLUMNS),
    )
    ET.SubElement(
        tileset, "image", source="city_tiles.png", width=str(sheet[0]), height=str(sheet[1])
    )
    for index, props in enumerate(tiles.props):
        element = ET.SubElement(tileset, "tile", id=str(index))
        properties = ET.SubElement(element, "properties")
        for name, value in props.items():
            if isinstance(value, bool):
                ET.SubElement(
                    properties, "property", name=name, type="bool", value=str(value).lower()
                )
            elif isinstance(value, int):
                ET.SubElement(properties, "property", name=name, type="int", value=str(value))
            else:
                ET.SubElement(properties, "property", name=name, value=str(value))

    for layer_id, (name, data) in enumerate((("ground", city.ground), ("walls", city.walls)), 1):
        layer = ET.SubElement(
            root, "layer", id=str(layer_id), name=name, width=str(MAP_W), height=str(MAP_H)
        )
        ET.SubElement(layer, "data", encoding="csv").text = _csv(data)

    next_id = 1

    def group(layer_id: int, name: str) -> ET.Element:
        return ET.SubElement(root, "objectgroup", id=str(layer_id), name=name)

    def obj(parent: ET.Element, label: str, x: int, y: int, w: int, h: int, **props: str) -> None:
        nonlocal next_id
        element = ET.SubElement(
            parent,
            "object",
            id=str(next_id),
            name=label,
            x=str(x * TILE),
            y=str(y * TILE),
            width=str(w * TILE),
            height=str(h * TILE),
        )
        properties = ET.SubElement(element, "properties")
        for key, value in props.items():
            if value:
                ET.SubElement(properties, "property", name=key, value=value)
        next_id += 1

    places = group(3, "places")
    for place_id, name, x0, y0, w, h in city.places:
        obj(places, name, x0, y0, w, h, place_id=place_id)
    rooms = group(4, "rooms")
    for label, kind, place_id, x0, y0, w, h in city.rooms:
        obj(rooms, label, x0, y0, w, h, room=kind, place_id=place_id)
    furniture = group(5, "furniture")
    for item in city.furniture:
        obj(
            furniture,
            item.type,
            item.x,
            item.y,
            item.w,
            item.h,
            furniture=item.type,
            orientation=item.orientation,
            place_id=item.place_id,
        )

    ET.indent(root, space=" ")
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in ("mvp.tmx", "placeholder_tiles.png"):  # la carte de l'étape 1
        (OUT / old).unlink(missing_ok=True)
    tiles = build_tileset()
    rows = (len(tiles.surfaces) + COLUMNS - 1) // COLUMNS
    sheet = pygame.Surface((COLUMNS * TILE, rows * TILE), pygame.SRCALPHA)
    for index, surface in enumerate(tiles.surfaces):
        sheet.blit(surface, ((index % COLUMNS) * TILE, (index // COLUMNS) * TILE))
    pygame.image.save(sheet, str(OUT / "city_tiles.png"))
    city = build_city(tiles)
    write_tmx(city, tiles, OUT / "city.tmx", sheet.get_size())
    print(
        f"Ville écrite : {OUT / 'city.tmx'} ({MAP_W}×{MAP_H} tuiles, {len(city.places)} lieux, "
        f"{len(city.furniture)} meubles)"
    )


if __name__ == "__main__":
    main()
