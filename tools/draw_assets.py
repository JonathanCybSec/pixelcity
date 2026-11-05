"""Génère nos assets originaux dans le style de pixel-agents.

Usage :  python tools/draw_assets.py [--sheet planche.png]

Écrit dans `pixelcity/assets/pixelcity/` :
- `furniture/<ID>/manifest.json` + PNG, au même format que pixel-agents
  (le jeu lit les deux collections avec le même code) ;
- `ground/<nom>.png` : tuiles d'extérieur 16×16 (herbe, trottoir, route...).

Option `--sheet` : produit une planche contact de tout ce qui a été dessiné,
pour vérifier le rendu d'un coup d'œil.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pygame
import sprites_furniture
from pixelart import Sprite, load, rgba

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pixelcity" / "assets" / "pixelcity"
TILE = 16


@dataclass(frozen=True)
class Item:
    """Déclaration d'un meuble : ce que pixel-agents appelle un manifest."""

    id: str
    name: str
    category: str
    width: int
    height: int
    footprint: tuple[int, int]
    background_tiles: int = 0
    on_walls: bool = False
    on_surfaces: bool = False
    states: bool = False  # variantes _OFF / _ON_1 / _ON_2
    overlays: tuple[tuple[str, str], ...] = ()


ITEMS: tuple[Item, ...] = (
    Item("FRIDGE", "Réfrigérateur", "kitchen", 16, 32, (1, 2), 1),
    Item("STOVE", "Cuisinière", "kitchen", 16, 32, (1, 2), 1, states=True),
    Item("KITCHEN_SINK", "Évier", "kitchen", 16, 32, (1, 2), 1),
    Item("KITCHEN_COUNTER", "Plan de travail", "kitchen", 16, 32, (1, 2), 1),
    Item("BED", "Lit", "bedroom", 16, 48, (1, 3), 1, overlays=(("occupied", "BED_COVER.png"),)),
    Item("WARDROBE", "Armoire", "bedroom", 16, 32, (1, 2), 1),
    Item("TV", "Télévision", "electronics", 32, 32, (2, 2), 1, states=True),
    Item("NIGHTSTAND", "Table de chevet", "bedroom", 16, 16, (1, 1)),
    Item("SHOWER", "Douche", "bathroom", 16, 32, (1, 2), 1, states=True),
    Item("TOILET", "Toilettes", "bathroom", 16, 32, (1, 2), 1),
    Item("WASHBASIN", "Lavabo", "bathroom", 16, 32, (1, 2), 1),
    Item("BREAD_OVEN", "Four à pain", "shop", 32, 32, (2, 2), 1, states=True),
    Item("WORKBENCH", "Pétrin", "shop", 32, 32, (2, 2), 1),
    Item("BAKERY_COUNTER", "Vitrine de boulangerie", "shop", 48, 32, (3, 2), 1),
    Item("CAFE_COUNTER", "Comptoir de café", "shop", 48, 32, (3, 2), 1),
    Item("CASH_REGISTER", "Caisse enregistreuse", "shop", 16, 16, (1, 1), on_surfaces=True),
    Item("ESPRESSO_MACHINE", "Machine à espresso", "shop", 16, 16, (1, 1), on_surfaces=True),
    Item("BREAD_SHELF", "Étagère à pains", "wall", 32, 32, (2, 2), on_walls=True),
    Item("MENU_BOARD", "Ardoise", "wall", 32, 32, (2, 2), on_walls=True),
    Item("SHELF_PRODUCE", "Rayon fruits et légumes", "shop", 32, 32, (2, 2), 1),
    Item("SHELF_GROCERY", "Rayon épicerie", "shop", 32, 32, (2, 2), 1),
    Item("SHELF_DRINKS", "Rayon boissons", "shop", 32, 32, (2, 2), 1),
    Item("CHECKOUT", "Caisse du supermarché", "shop", 32, 32, (2, 2), 1),
    Item("TREADMILL", "Tapis de course", "gym", 16, 32, (1, 2), 1),
    Item("WEIGHT_BENCH", "Banc de musculation", "gym", 16, 32, (1, 2), 1),
    Item("TREE_ROUND", "Arbre", "outdoor", 32, 48, (2, 3), 2),
    Item("TREE_PINE", "Pin", "outdoor", 32, 48, (2, 3), 2),
    Item("BUSH", "Buisson", "outdoor", 16, 16, (1, 1)),
    Item("HEDGE", "Haie", "outdoor", 16, 16, (1, 1)),
    Item("HEDGE_V", "Haie (verticale)", "outdoor", 16, 16, (1, 1)),
    Item("PARK_BENCH", "Banc public", "outdoor", 32, 16, (2, 1)),
    Item("LAMPPOST", "Lampadaire", "outdoor", 16, 32, (1, 2), 1),
    Item("WINDOW", "Fenêtre", "wall", 16, 32, (1, 2), on_walls=True),
    Item("SLOT_MACHINE", "Machine à sous", "casino", 16, 32, (1, 2), 1, states=True),
    Item("ROULETTE_TABLE", "Table de roulette", "casino", 48, 32, (3, 2), 1),
    Item("BOUTIQUE_COUNTER", "Caisse de la boutique", "shop", 32, 32, (2, 2), 1),
    Item("TECH_COUNTER", "Caisse du magasin hi-tech", "shop", 32, 32, (2, 2), 1),
    Item("BAR_COUNTER", "Comptoir du bar", "shop", 32, 32, (2, 2), 1),
    Item("CLOTHES_RACK", "Portant de vêtements", "shop", 32, 32, (2, 2), 1),
    Item("TECH_SHELF", "Rayon téléviseurs et téléphones", "shop", 32, 32, (2, 2), 1),
)


def _asset(item: Item, asset_id: str, **extra: object) -> dict[str, object]:
    return {
        "type": "asset",
        "id": asset_id,
        "file": f"{asset_id}.png",
        "width": item.width,
        "height": item.height,
        "footprintW": item.footprint[0],
        "footprintH": item.footprint[1],
        **extra,
    }


def manifest(item: Item) -> dict[str, object]:
    common: dict[str, object] = {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "canPlaceOnWalls": item.on_walls,
        "canPlaceOnSurfaces": item.on_surfaces,
        "backgroundTiles": item.background_tiles,
    }
    if item.overlays:
        common["overlays"] = dict(item.overlays)
    if not item.states:
        return {**common, **_asset(item, item.id), "id": item.id, "name": item.name}
    return {
        **common,
        "type": "group",
        "groupType": "state",
        "members": [
            _asset(item, f"{item.id}_OFF", state="off"),
            {
                "type": "group",
                "groupType": "animation",
                "state": "on",
                "members": [
                    _asset(item, f"{item.id}_ON_1", frame=0),
                    _asset(item, f"{item.id}_ON_2", frame=1),
                ],
            },
        ],
    }


# --------------------------------------------------------------------------- #
# Tuiles de sol extérieures
# --------------------------------------------------------------------------- #
def _speckle(s: Sprite, rng: random.Random, colors: list[str], count: int) -> None:
    for _ in range(count):
        s.px(rng.randrange(TILE), rng.randrange(TILE), rng.choice(colors))


def _shore(sides: str, water: Sprite, grass: Sprite) -> Sprite:
    """Bord d'étang : de l'herbe côté `sides`, puis un liseré sombre, de l'écume, l'eau.

    On calcule pour chaque pixel sa distance au bord de l'eau (une « fonction
    de distance signée », comme en infographie) : négative = herbe. Les coins
    sont des quarts de cercle, d'où une berge arrondie.
    """
    margin, radius = 4.0, 5.0
    lo, hi = margin, TILE - margin
    s = Sprite(TILE, TILE)
    for y in range(TILE):
        for x in range(TILE):
            px, py = x + 0.5, y + 0.5
            d = 99.0
            if "n" in sides:
                d = min(d, py - lo)
            if "s" in sides:
                d = min(d, hi - py)
            if "w" in sides:
                d = min(d, px - lo)
            if "e" in sides:
                d = min(d, hi - px)
            for v, h in (("n", "w"), ("n", "e"), ("s", "w"), ("s", "e")):
                if v in sides and h in sides:
                    cx = lo + radius if h == "w" else hi - radius
                    cy = lo + radius if v == "n" else hi - radius
                    if (px < cx if h == "w" else px > cx) and (py < cy if v == "n" else py > cy):
                        d = radius - ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            if d < 0:
                color = grass.surface.get_at((x, y))
            elif d < 1:
                color = pygame.Color("#3b6f4a")
            elif d < 2:
                color = pygame.Color("#a9d2f0")
            else:
                color = water.surface.get_at((x, y))
            s.px(x, y, (color.r, color.g, color.b, 255))
    return s


def ground_tiles() -> dict[str, Sprite]:
    rng = random.Random(2026)  # motifs aléatoires mais identiques à chaque génération
    tiles: dict[str, Sprite] = {}

    def tile(name: str, base: str) -> Sprite:
        s = Sprite(TILE, TILE)
        s.rect(0, 0, TILE, TILE, base)
        tiles[name] = s
        return s

    for i in range(3):
        _speckle(tile(f"grass_{i}", "#6ea75a"), rng, ["#5e9a4d", "#7fb766", "#649f52"], 26)
    flowers = tile("grass_flowers", "#6ea75a")
    _speckle(flowers, rng, ["#5e9a4d", "#7fb766"], 20)
    for _ in range(5):
        x, y = rng.randrange(1, 15), rng.randrange(1, 15)
        flowers.px(x, y, rng.choice(["#f4e27a", "#f2a6c0", "#ffffff", "#c9a0e8"]))

    side = tile("sidewalk", "#cfc8bb")
    for y in (0, 8):
        side.hline(0, 15, y, "#b3ab9c")
    for y, offset in ((0, 0), (8, 4)):
        for x in range(offset, TILE, 8):
            side.vline(x, y, y + 7, "#b3ab9c")
    _speckle(side, rng, ["#d8d2c6", "#c4bdaf"], 8)

    for name in ("road", "road_line_h", "road_line_v", "crosswalk_h", "crosswalk_v"):
        road = tile(name, "#565861")
        _speckle(road, rng, ["#4e5058", "#60626b", "#5a5c65"], 22)
        if name == "road_line_h":
            for x in range(0, TILE, 8):
                road.rect(x + 1, 15, 5, 1, "#e9e4d0")
        elif name == "road_line_v":
            for y in range(0, TILE, 8):
                road.rect(15, y + 1, 1, 5, "#e9e4d0")
        elif name == "crosswalk_h":  # passage pour traverser une route horizontale
            for x in range(1, TILE, 4):
                road.rect(x, 1, 2, 14, "#eeeae0")
        elif name == "crosswalk_v":
            for y in range(1, TILE, 4):
                road.rect(1, y, 14, 2, "#eeeae0")

    _speckle(tile("path", "#c9a978"), rng, ["#b8986a", "#d6b88a", "#bfa070"], 24)
    _speckle(tile("gravel", "#bdb6a6"), rng, ["#a8a191", "#cdc7b8", "#9c9585"], 30)

    for i in range(2):
        water = tile(f"water_{i}", "#4f8fd0")
        for y in (3 + i, 9 + i, 14):
            for x in range(rng.randrange(0, 4), TILE, 7):
                water.hline(x, min(x + 2, 15), y, "#7fb2e3")

    for sides in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
        tiles[f"water_{sides}"] = _shore(sides, tiles["water_0"], tiles["grass_0"])

    plaza = tile("plaza", "#d6cfc2")
    plaza.frame(0, 0, TILE, TILE, "#bab1a2")
    plaza.hline(1, 14, 1, "#e4ded3")
    _speckle(plaza, rng, ["#cfc7b9"], 6)

    mat = tile("doormat", "#cfc8bb")
    mat.rect(2, 4, 12, 9, "#6b3e1f")
    mat.rect(3, 5, 10, 7, "#8b5a3c")
    for x in range(3, 13, 2):
        mat.px(x, 13, "#6b3e1f")
    return tiles


# --------------------------------------------------------------------------- #
# Planche contact
# --------------------------------------------------------------------------- #
def contact_sheet(sprites: dict[str, pygame.Surface], path: Path, scale: int = 4) -> None:
    pygame.font.init()
    font = pygame.font.Font(None, 18)
    cell_w, cell_h = 48 * scale + 16, 48 * scale + 26
    cols = 8
    rows = (len(sprites) + cols - 1) // cols
    sheet = pygame.Surface((cols * cell_w, rows * cell_h))
    sheet.fill(rgba("#5a5d68"))
    for i, (name, surface) in enumerate(sprites.items()):
        x, y = (i % cols) * cell_w + 8, (i // cols) * cell_h + 6
        big = pygame.transform.scale_by(surface, scale)
        sheet.blit(big, (x, y))
        sheet.blit(font.render(name, True, (255, 255, 255)), (x, y + 48 * scale + 4))
    pygame.image.save(sheet, str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet", type=Path, default=None, help="planche contact à écrire")
    args = parser.parse_args()

    drawn: dict[str, Sprite] = {}
    for draw in sprites_furniture.ALL:
        drawn.update(draw())

    furniture_dir = OUT / "furniture"
    if furniture_dir.exists():
        shutil.rmtree(furniture_dir)
    preview: dict[str, pygame.Surface] = {}
    for item in ITEMS:
        folder = furniture_dir / item.id
        # Les images d'un meuble : ID, ID_OFF, ID_ON_1, ID_ON_2... (pas HEDGE_V pour HEDGE !)
        files = [name for name in drawn if re.fullmatch(rf"{item.id}(_OFF|_ON_\d+)?", name)]
        files += [Path(file).stem for _, file in item.overlays]
        if not files:
            raise SystemExit(f"aucun sprite dessiné pour {item.id}")
        for name in files:
            sprite = drawn[name]
            if (sprite.width, sprite.height) != (item.width, item.height):
                raise SystemExit(
                    f"{name} : {sprite.width}×{sprite.height}, attendu {item.width}×{item.height}"
                )
            sprite.save(folder / f"{name}.png")
            preview[name] = sprite.surface
        (folder / "manifest.json").write_text(
            json.dumps(manifest(item), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    ground_dir = OUT / "ground"
    if ground_dir.exists():
        shutil.rmtree(ground_dir)
    for name, sprite in ground_tiles().items():
        sprite.save(ground_dir / f"{name}.png")
        preview[f"sol:{name}"] = load(ground_dir / f"{name}.png")

    tiles = len(list(ground_dir.glob("*.png")))
    print(f"{len(ITEMS)} meubles et {tiles} tuiles de sol écrits dans {OUT}")
    if args.sheet:
        contact_sheet(preview, args.sheet)
        print(f"Planche contact : {args.sheet}")


if __name__ == "__main__":
    main()
