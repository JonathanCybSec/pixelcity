"""Génère la carte du MVP : `pixelcity/assets/maps/mvp.tmx` + son tileset placeholder.

Usage :  python tools/make_mvp_map.py

Pourquoi un script plutôt qu'un dessin à la main dans Tiled ?
- La carte est reproductible et versionnée sous forme de code lisible.
- Le résultat est un VRAI fichier Tiled : tu peux l'ouvrir dans Tiled, le
  modifier à la main, et la simulation le relira tel quel.
  (Attention : relancer ce script écrase les retouches manuelles.)
- Le tileset est un placeholder en aplats de couleur. À l'étape 4, on le
  remplacera par de vrais assets CC0 ; le code de la simulation ne bougera pas.

Ce script est un OUTIL : il a le droit d'utiliser pygame (pour dessiner le
tileset), contrairement au noyau de la simulation.
"""

from __future__ import annotations

import os
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pixelcity.config.loader import load_config  # noqa: E402

TILE = 16
MAP_W, MAP_H = 48, 32
COLUMNS = 8
OUT_DIR = ROOT / "pixelcity" / "assets" / "maps"
TILESET_FILE = "placeholder_tiles.png"

RGB = tuple[int, int, int]


# --------------------------------------------------------------------------- #
# Définition du tileset : ordre = identifiant local de la tuile (GID - 1)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TileDef:
    name: str
    walkable: bool
    cost: int  # ignoré si non marchable


TILES: list[TileDef] = [
    TileDef("grass", True, 3),
    TileDef("grass_flowers", True, 3),
    TileDef("sidewalk", True, 1),
    TileDef("road", True, 8),
    TileDef("road_line_h", True, 8),
    TileDef("road_line_v", True, 8),
    TileDef("crosswalk_h_road", True, 1),
    TileDef("crosswalk_v_road", True, 1),
    TileDef("path", True, 1),
    TileDef("water", False, 0),
    TileDef("tree", False, 0),
    TileDef("hedge", False, 0),
    TileDef("bench", False, 0),
    TileDef("wall", False, 0),
    TileDef("door", True, 1),
    TileDef("roof_home", False, 0),
    TileDef("roof_apartment", False, 0),
    TileDef("roof_bakery", False, 0),
    TileDef("roof_cafe", False, 0),
    TileDef("roof_office", False, 0),
    TileDef("roof_school", False, 0),
    TileDef("roof_gym", False, 0),
    TileDef("roof_shop", False, 0),
]
GID = {tile.name: index + 1 for index, tile in enumerate(TILES)}

ROOF_COLORS: dict[str, RGB] = {
    "roof_home": (196, 92, 76),
    "roof_apartment": (112, 122, 140),
    "roof_bakery": (226, 150, 70),
    "roof_cafe": (70, 160, 150),
    "roof_office": (90, 130, 190),
    "roof_school": (226, 196, 90),
    "roof_gym": (150, 100, 190),
    "roof_shop": (110, 170, 110),
}


def darker(color: RGB, factor: float = 0.8) -> RGB:
    r, g, b = color
    return (int(r * factor), int(g * factor), int(b * factor))


# --------------------------------------------------------------------------- #
# Dessin des tuiles placeholder
# --------------------------------------------------------------------------- #
def draw_tileset() -> pygame.Surface:
    rows = (len(TILES) + COLUMNS - 1) // COLUMNS
    sheet = pygame.Surface((COLUMNS * TILE, rows * TILE), pygame.SRCALPHA)
    noise = random.Random(1234)  # motifs aléatoires mais identiques à chaque génération

    def specks(surface: pygame.Surface, colors: list[RGB], count: int) -> None:
        for _ in range(count):
            surface.set_at((noise.randrange(TILE), noise.randrange(TILE)), noise.choice(colors))

    for index, tile in enumerate(TILES):
        s = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        name = tile.name
        if name in ("grass", "grass_flowers"):
            s.fill((112, 170, 84))
            specks(s, [(96, 150, 72), (130, 186, 98)], 22)
            if name == "grass_flowers":
                specks(s, [(240, 210, 90), (232, 140, 170), (245, 245, 240)], 6)
        elif name == "sidewalk":
            s.fill((206, 204, 196))
            for k in (0, 8):
                pygame.draw.line(s, (176, 174, 166), (k, 0), (k, TILE - 1))
                pygame.draw.line(s, (176, 174, 166), (0, k), (TILE - 1, k))
        elif name.startswith("road") or name.startswith("crosswalk"):
            s.fill((78, 80, 88))
            specks(s, [(70, 72, 80), (86, 88, 96)], 14)
            if name == "road_line_h":  # marquage entre les deux voies, sur le bord bas
                for x in range(0, TILE, 8):
                    pygame.draw.line(s, (232, 226, 200), (x, TILE - 1), (x + 4, TILE - 1))
            elif name == "road_line_v":  # marquage sur le bord droit
                for y in range(0, TILE, 8):
                    pygame.draw.line(s, (232, 226, 200), (TILE - 1, y), (TILE - 1, y + 4))
            elif name == "crosswalk_h_road":  # bandes parallèles à une route horizontale
                for y in range(1, TILE, 4):
                    pygame.draw.rect(s, (236, 236, 236), (2, y, TILE - 4, 2))
            elif name == "crosswalk_v_road":  # bandes parallèles à une route verticale
                for x in range(1, TILE, 4):
                    pygame.draw.rect(s, (236, 236, 236), (x, 2, 2, TILE - 4))
        elif name == "path":
            s.fill((204, 178, 128))
            specks(s, [(184, 158, 110), (218, 194, 146)], 18)
        elif name == "water":
            s.fill((70, 140, 206))
            for y in (4, 11):
                pygame.draw.line(s, (120, 180, 230), (3, y), (7, y))
                pygame.draw.line(s, (120, 180, 230), (10, y - 2), (13, y - 2))
        elif name == "tree":
            pygame.draw.rect(s, (110, 80, 50), (7, 10, 2, 5))
            pygame.draw.circle(s, (52, 120, 60), (8, 7), 6)
            pygame.draw.circle(s, (78, 150, 76), (6, 5), 2)
        elif name == "hedge":
            pygame.draw.rect(s, (60, 125, 62), (0, 1, TILE, TILE - 2), border_radius=4)
            specks(s, [(82, 150, 80), (48, 105, 52)], 16)
        elif name == "bench":
            pygame.draw.rect(s, (150, 105, 60), (2, 6, 12, 3))
            pygame.draw.rect(s, (150, 105, 60), (2, 10, 12, 2))
            pygame.draw.rect(s, (80, 60, 40), (3, 12, 1, 3))
            pygame.draw.rect(s, (80, 60, 40), (12, 12, 1, 3))
        elif name in ("wall", "door"):
            s.fill((176, 150, 128))
            for y in range(3, TILE, 4):
                pygame.draw.line(s, (156, 130, 110), (0, y), (TILE - 1, y))
            if name == "door":
                pygame.draw.rect(s, (80, 52, 30), (3, 2, 10, 14))
                pygame.draw.rect(s, (110, 72, 44), (4, 3, 8, 13))
                s.set_at((10, 9), (230, 200, 90))
        elif name in ROOF_COLORS:
            color = ROOF_COLORS[name]
            s.fill(color)
            for y in range(3, TILE, 5):
                pygame.draw.line(s, darker(color), (0, y), (TILE - 1, y))
        sheet.blit(s, ((index % COLUMNS) * TILE, (index // COLUMNS) * TILE))
    return sheet


# --------------------------------------------------------------------------- #
# Construction de la carte
# --------------------------------------------------------------------------- #
class MapBuilder:
    def __init__(self) -> None:
        self.ground = [GID["grass"]] * (MAP_W * MAP_H)
        self.structures = [0] * (MAP_W * MAP_H)
        self.places: list[tuple[str, int, int, int, int]] = []

    def set(self, layer: list[int], x: int, y: int, name: str) -> None:
        layer[y * MAP_W + x] = GID[name]

    def fill(self, layer: list[int], x0: int, y0: int, x1: int, y1: int, name: str) -> None:
        """Remplit le rectangle [x0..x1] × [y0..y1] (bornes incluses)."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(layer, x, y, name)

    def building(
        self, place_id: str, x: int, y: int, w: int, h: int, roof: str, doors: list[tuple[int, int]]
    ) -> None:
        """Toit partout, mur sur le côté des portes, portes marchables."""
        self.fill(self.structures, x, y, x + w - 1, y + h - 1, roof)
        for dx, dy in doors:
            if dy in (y, y + h - 1):  # porte sur un mur horizontal (haut ou bas)
                self.fill(self.structures, x, dy, x + w - 1, dy, "wall")
            else:  # porte sur un mur vertical (gauche ou droite)
                self.fill(self.structures, dx, y, dx, y + h - 1, "wall")
        for dx, dy in doors:
            self.set(self.structures, dx, dy, "door")
        self.places.append((place_id, x, y, w, h))


def build_map() -> MapBuilder:
    m = MapBuilder()
    g, s = m.ground, m.structures

    # --- Routes : une horizontale (y 14-15), une verticale (x 23-24) --------
    m.fill(g, 0, 14, MAP_W - 1, 14, "road_line_h")
    m.fill(g, 0, 15, MAP_W - 1, 15, "road")
    m.fill(g, 23, 0, 23, MAP_H - 1, "road_line_v")
    m.fill(g, 24, 0, 24, MAP_H - 1, "road")
    m.fill(g, 23, 14, 24, 15, "road")  # carrefour sans marquage

    # --- Trottoirs de part et d'autre --------------------------------------
    m.fill(g, 0, 13, MAP_W - 1, 13, "sidewalk")
    m.fill(g, 0, 16, MAP_W - 1, 16, "sidewalk")
    m.fill(g, 22, 0, 22, MAP_H - 1, "sidewalk")
    m.fill(g, 25, 0, 25, MAP_H - 1, "sidewalk")

    # --- Passages piétons ---------------------------------------------------
    for x in (10, 22, 25, 40):  # pour traverser la route horizontale
        m.fill(g, x, 14, x, 15, "crosswalk_h_road")
    for y in (13, 16, 24):  # pour traverser la route verticale
        m.fill(g, 23, y, 24, y, "crosswalk_v_road")

    # --- Quartier résidentiel (nord-ouest) ----------------------------------
    m.building("maison_dupont", 2, 8, 5, 5, "roof_home", [(4, 12)])
    m.building("maison_benali", 9, 8, 5, 5, "roof_home", [(11, 12)])
    m.building("immeuble_tilleuls", 15, 3, 6, 10, "roof_apartment", [(17, 12)])
    for x, y in [(1, 2), (5, 3), (9, 2), (12, 5), (3, 6), (8, 6), (1, 10)]:
        m.set(s, x, y, "tree")
    for x, y in [(2, 4), (6, 5), (10, 4), (13, 7), (7, 10)]:
        m.set(g, x, y, "grass_flowers")

    # --- Travail (nord-est) ---------------------------------------------------
    m.building("ecole", 27, 4, 10, 9, "roof_school", [(31, 12)])
    m.building("bureaux", 39, 2, 7, 11, "roof_office", [(42, 12)])
    for x, y in [(27, 1), (31, 1), (35, 1), (38, 4), (46, 7), (37, 9)]:
        m.set(s, x, y, "tree")

    # --- Commerces et loisirs (sud-est) --------------------------------------
    m.building("boulangerie", 27, 17, 5, 5, "roof_bakery", [(29, 17)])
    m.building("cafe", 33, 17, 5, 5, "roof_cafe", [(35, 17)])
    m.building("supermarche", 39, 17, 8, 7, "roof_shop", [(42, 17), (43, 17)])
    m.building("salle_de_sport", 26, 25, 8, 6, "roof_gym", [(26, 27)])
    for x, y in [(36, 24), (38, 27), (42, 26), (45, 29), (35, 30)]:
        m.set(s, x, y, "tree")

    # --- Parc (sud-ouest) : haie, allées, étang ------------------------------
    px0, py0, px1, py1 = 1, 17, 21, 30
    m.fill(s, px0, py0, px1, py0, "hedge")
    m.fill(s, px0, py1, px1, py1, "hedge")
    m.fill(s, px0, py0, px0, py1, "hedge")
    m.fill(s, px1, py0, px1, py1, "hedge")
    m.fill(g, 10, 17, 11, 25, "path")  # allée nord-sud
    m.fill(g, 5, 23, 21, 24, "path")  # allée est-ouest
    for x, y in [(10, 17), (11, 17), (21, 23), (21, 24)]:  # ouvertures dans la haie
        s[y * MAP_W + x] = 0
    m.fill(g, 3, 19, 7, 21, "water")
    for x, y in [(14, 19), (17, 20), (19, 27), (5, 27), (8, 28), (15, 28), (18, 19)]:
        m.set(s, x, y, "tree")
    for x, y in [(12, 21), (9, 26), (15, 22)]:
        m.set(s, x, y, "bench")
    for x, y in [(4, 25), (13, 27), (17, 25), (6, 29)]:
        m.set(g, x, y, "grass_flowers")
    m.places.append(("parc", px0, py0, px1 - px0 + 1, py1 - py0 + 1))
    return m


# --------------------------------------------------------------------------- #
# Écriture au format Tiled
# --------------------------------------------------------------------------- #
def _csv(layer: list[int]) -> str:
    rows = [",".join(str(v) for v in layer[y * MAP_W : (y + 1) * MAP_W]) for y in range(MAP_H)]
    return "\n" + ",\n".join(rows) + "\n"


def write_tmx(
    m: MapBuilder, names: dict[str, str], path: Path, sheet_size: tuple[int, int]
) -> None:
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
        nextlayerid="4",
        nextobjectid=str(len(m.places) + 1),
    )
    tileset = ET.SubElement(
        root,
        "tileset",
        firstgid="1",
        name="placeholder",
        tilewidth=str(TILE),
        tileheight=str(TILE),
        tilecount=str(len(TILES)),
        columns=str(COLUMNS),
    )
    ET.SubElement(
        tileset, "image", source=TILESET_FILE, width=str(sheet_size[0]), height=str(sheet_size[1])
    )
    for index, tile in enumerate(TILES):
        element = ET.SubElement(tileset, "tile", id=str(index))
        props = ET.SubElement(element, "properties")
        ET.SubElement(props, "property", name="kind", value=tile.name)
        ET.SubElement(
            props, "property", name="walkable", type="bool", value=str(tile.walkable).lower()
        )
        if tile.walkable:
            ET.SubElement(props, "property", name="cost", type="int", value=str(tile.cost))

    for layer_id, (name, data) in enumerate(
        (("ground", m.ground), ("structures", m.structures)), 1
    ):
        layer = ET.SubElement(
            root, "layer", id=str(layer_id), name=name, width=str(MAP_W), height=str(MAP_H)
        )
        ET.SubElement(layer, "data", encoding="csv").text = _csv(data)

    group = ET.SubElement(root, "objectgroup", id="3", name="places")
    for object_id, (place_id, x, y, w, h) in enumerate(m.places, 1):
        obj = ET.SubElement(
            group,
            "object",
            id=str(object_id),
            name=names[place_id],
            x=str(x * TILE),
            y=str(y * TILE),
            width=str(w * TILE),
            height=str(h * TILE),
        )
        props = ET.SubElement(obj, "properties")
        ET.SubElement(props, "property", name="place_id", value=place_id)

    ET.indent(root, space=" ")
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    config = load_config()
    names = {place.id: place.name for place in config.city.places}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sheet = draw_tileset()
    pygame.image.save(sheet, str(OUT_DIR / TILESET_FILE))

    builder = build_map()
    unknown = {place_id for place_id, *_ in builder.places} - set(names)
    if unknown:
        raise SystemExit(f"lieux absents de city.yaml : {sorted(unknown)}")
    write_tmx(builder, names, OUT_DIR / config.city.map, sheet.get_size())
    print(f"Carte écrite : {OUT_DIR / config.city.map} ({MAP_W}×{MAP_H} tuiles)")
    print(f"Tileset écrit : {OUT_DIR / TILESET_FILE} ({len(TILES)} tuiles)")


if __name__ == "__main__":
    main()
