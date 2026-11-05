"""Nos meubles, dessinés dans le style de pixel-agents (16 px par tuile, vue 3/4).

Chaque fonction renvoie un dictionnaire {nom de fichier: Sprite}. Les
dimensions et emprises sont déclarées dans `draw_assets.py`, qui écrit les
manifest.json au même format que pixel-agents.

Conventions de construction (relevées sur leurs sprites) :
- un objet « contre le mur » fait 32 px de haut pour 1 tuile au sol : sa
  moitié haute (rangée d'arrière-plan) chevauche la face du mur ;
- contour d'un pixel dans la teinte la plus sombre du matériau ;
- reflet clair sur l'arête du dessus, bande sombre en bas de la face avant ;
- ombre portée translucide sur les deux dernières lignes.
"""

from __future__ import annotations

from pixelart import (
    BRICK,
    CREAM,
    CRIMSON,
    GRAPHITE,
    GREEN,
    NAVY,
    STEEL,
    TILE_BLUE,
    WHITE,
    WOOD,
    WOOD_DARK,
    Material,
    Sprite,
)

STONE = Material("#f7f8fa", "#e2e5ea", "#c6ccd4", "#a9b0ba", "#4a4650")
GLASS = "#bfe3ee"
GLASS_HI = "#eaf8fb"
FLAME = ("#fcde5a", "#f2a623", "#e85d24")
BREAD = ("#e8b46a", "#c98a3e", "#9a5f2a", "#6b3e1f")
LEAF = ("#9fd06a", "#74b25d", "#4f9447", "#356441", "#17201a")

type Sprites = dict[str, Sprite]


def _tiles(s: Sprite, x: int, y: int, w: int, h: int, mat: Material, step: int = 4) -> None:
    """Carrelage mural : fond clair et joints réguliers."""
    s.rect(x, y, w, h, mat.top)
    for yy in range(y, y + h, step):
        s.hline(x, x + w - 1, yy, mat.front)
    for row, yy in enumerate(range(y, y + h, step)):
        offset = 0 if row % 2 == 0 else step // 2
        for xx in range(x + offset, x + w, step):
            s.vline(xx, yy, min(yy + step - 1, y + h - 1), mat.front)


# --------------------------------------------------------------------------- #
# Cuisine
# --------------------------------------------------------------------------- #
def fridge() -> Sprites:
    s = Sprite(16, 32)
    s.box(1, 2, 14, 28, 4, WHITE)
    s.hline(2, 13, 12, WHITE.line)  # séparation congélateur / frigo
    s.hline(2, 13, 13, WHITE.hi)
    s.vline(12, 7, 10, STEEL.front)  # poignées
    s.vline(12, 15, 21, STEEL.front)
    s.vline(2, 6, 27, WHITE.hi)
    s.rect(4, 17, 2, 2, "#b84349")  # magnet
    s.rect(6, 19, 3, 3, CREAM.top)  # pense-bête
    s.px(7, 20, CREAM.front)
    s.shadow(1, 30, 14)
    return {"FRIDGE": s}


def _cooktop(s: Sprite, on: int) -> None:
    """Plaques de cuisson : on=0 éteintes, 1 ou 2 = flammes (deux images)."""
    for bx in (3, 9):
        s.rect(bx, 16, 4, 3, GRAPHITE.line)
        s.rect(bx + 1, 17, 2, 1, GRAPHITE.front if not on else FLAME[(bx // 3 + on) % 3])
        if on:
            s.px(bx, 17, FLAME[2])
            s.px(bx + 3, 17, FLAME[(on + 1) % 3])


def stove() -> Sprites:
    out: Sprites = {}
    for name, on in (("STOVE_OFF", 0), ("STOVE_ON_1", 1), ("STOVE_ON_2", 2)):
        s = Sprite(16, 32)
        s.rect(3, 1, 10, 6, STEEL.line)  # hotte
        s.rect(4, 2, 8, 4, STEEL.top)
        s.hline(4, 11, 2, STEEL.hi)
        s.hline(4, 11, 5, STEEL.dark)
        s.rect(6, 0, 4, 1, STEEL.line)
        _tiles(s, 2, 7, 12, 7, WHITE, step=3)  # crédence
        s.box(1, 14, 14, 16, 6, WHITE)
        s.rect(2, 15, 12, 5, GRAPHITE.top)  # plaque
        _cooktop(s, on)
        for kx in (3, 6, 9, 12):  # boutons
            s.px(kx, 20, GRAPHITE.line)
        s.rect(4, 22, 8, 5, GRAPHITE.line)  # porte du four
        s.rect(5, 23, 6, 3, GRAPHITE.front if not on else "#7a3b2a")
        s.hline(5, 10, 23, GRAPHITE.hi)
        if on:  # une casserole et un peu de vapeur
            s.rect(9, 13, 5, 3, STEEL.line)
            s.rect(10, 14, 3, 1, STEEL.hi)
            for vx, vy in (
                ((10, 10), (12, 8), (11, 11)) if on == 1 else ((11, 9), (10, 7), (12, 11))
            ):
                s.px(vx, vy, (255, 255, 255, 170))
        s.shadow(1, 30, 14)
        out[name] = s
    return out


def _counter_base(s: Sprite, top_mat: Material) -> None:
    """Plan de travail en pierre sur un meuble bas en bois."""
    s.rect(0, 15, 16, 15, WOOD.line)
    s.rect(1, 16, 14, 5, top_mat.top)
    s.hline(1, 14, 16, top_mat.hi)
    s.hline(1, 14, 20, top_mat.dark)
    s.rect(1, 21, 14, 8, WOOD.front)
    s.vline(8, 21, 28, WOOD.line)  # deux portes
    s.px(6, 24, WOOD.hi)
    s.px(10, 24, WOOD.hi)
    s.hline(1, 14, 28, WOOD.dark)
    s.shadow(0, 30, 16)


def kitchen_sink() -> Sprites:
    s = Sprite(16, 32)
    _tiles(s, 1, 6, 14, 9, WHITE, step=3)
    _counter_base(s, STONE)
    s.rect(4, 17, 8, 3, STEEL.line)  # bac
    s.rect(5, 17, 6, 2, STEEL.front)
    s.hline(5, 10, 18, STEEL.dark)
    s.rect(7, 11, 2, 5, STEEL.line)  # robinet
    s.rect(7, 11, 4, 1, STEEL.line)
    s.px(10, 12, STEEL.top)
    s.px(7, 12, STEEL.hi)
    return {"KITCHEN_SINK": s}


def kitchen_counter() -> Sprites:
    s = Sprite(16, 32)
    _tiles(s, 1, 6, 14, 9, WHITE, step=3)
    for ux, color in ((4, STEEL.front), (7, WOOD.front), (10, STEEL.front)):  # ustensiles
        s.vline(ux, 7, 11, color)
        s.px(ux, 7, GRAPHITE.line)
    s.hline(3, 11, 6, GRAPHITE.front)
    _counter_base(s, STONE)
    s.rect(3, 17, 6, 3, WOOD.line)  # planche à découper
    s.rect(4, 17, 4, 2, WOOD.hi)
    s.rect(11, 15, 3, 4, CRIMSON.line)  # pot à ustensiles
    s.rect(12, 16, 1, 2, CRIMSON.top)
    return {"KITCHEN_COUNTER": s}


# --------------------------------------------------------------------------- #
# Chambre et salon
# --------------------------------------------------------------------------- #
BLANKET = NAVY


def _blanket(s: Sprite, y0: int, body: bool) -> None:
    """Couverture vue de dessus ; avec `body`, le relief d'un dormeur dessous."""
    s.rect(2, y0, 12, 41 - y0, BLANKET.line)
    s.rect(3, y0 + 1, 10, 40 - y0 - 1, BLANKET.top)
    s.rect(3, y0 + 1, 10, 2, BLANKET.hi)  # revers
    s.hline(3, 12, y0 + 3, BLANKET.front)
    if body:
        s.rect(5, y0 + 5, 6, 12, BLANKET.hi)
        s.rect(6, y0 + 6, 4, 10, BLANKET.top)
        s.vline(4, y0 + 6, y0 + 15, BLANKET.front)
        s.vline(11, y0 + 6, y0 + 15, BLANKET.front)
    s.hline(3, 12, 39, BLANKET.front)


def bed() -> Sprites:
    s = Sprite(16, 48)
    s.rounded(1, 6, 14, 12, WOOD_DARK.top, WOOD_DARK.line)  # tête de lit
    s.hline(2, 13, 7, WOOD_DARK.hi)
    s.rect(3, 9, 10, 6, WOOD_DARK.front)
    s.rect(1, 15, 14, 29, WOOD.line)  # cadre
    s.rect(2, 16, 12, 27, WOOD.top)
    s.rect(3, 16, 10, 6, WHITE.line)  # oreiller
    s.rect(4, 17, 8, 4, WHITE.top)
    s.hline(4, 11, 17, WHITE.hi)
    _blanket(s, 21, body=False)
    s.rect(1, 41, 14, 3, WOOD.front)  # pied de lit
    s.hline(1, 14, 43, WOOD.line)
    s.shadow(1, 44, 14)
    cover = Sprite(16, 48)  # couverture posée sur un dormeur (calque au-dessus de sa tête)
    _blanket(cover, 20, body=True)
    return {"BED": s, "BED_COVER": cover}


def wardrobe() -> Sprites:
    s = Sprite(16, 32)
    s.box(1, 1, 14, 29, 3, WOOD_DARK)
    s.vline(7, 4, 27, WOOD_DARK.line)
    s.vline(8, 4, 27, WOOD_DARK.hi)
    s.px(6, 15, WOOD.hi)
    s.px(9, 15, WOOD.hi)
    s.hline(2, 13, 26, WOOD_DARK.dark)
    s.shadow(1, 30, 14)
    return {"WARDROBE": s}


def tv() -> Sprites:
    out: Sprites = {}
    screens = {
        "TV_OFF": None,
        "TV_ON_1": ("#3b6ea5", "#6fb3d9", "#e9d36b"),
        "TV_ON_2": ("#4a7d4f", "#8fc58a", "#e9e2c7"),
    }
    for name, colors in screens.items():
        s = Sprite(32, 32)
        s.rect(4, 3, 24, 14, GRAPHITE.line)  # écran plat
        s.rect(5, 4, 22, 12, "#1e2632" if colors is None else colors[0])
        if colors is None:
            s.hline(6, 12, 5, "#3a4656")
            s.hline(6, 9, 6, "#3a4656")
        else:
            s.rect(5, 11, 22, 5, colors[1])
            s.rect(16, 6, 5, 5, colors[2])
            s.rect(8, 8, 3, 6, GRAPHITE.top)
        s.rect(14, 17, 4, 1, GRAPHITE.line)
        s.box(1, 18, 30, 12, 5, WOOD_DARK)  # meuble télé
        s.vline(11, 23, 28, WOOD_DARK.line)
        s.vline(21, 23, 28, WOOD_DARK.line)
        s.px(6, 25, WOOD.hi)
        s.px(16, 25, WOOD.hi)
        s.px(26, 25, WOOD.hi)
        s.shadow(1, 30, 30)
        out[name] = s
    return out


def nightstand() -> Sprites:
    s = Sprite(16, 16)
    s.box(2, 6, 12, 8, 3, WOOD)
    s.hline(4, 11, 10, WOOD.line)
    s.rect(6, 1, 4, 3, "#fce8a8")  # lampe
    s.rect(7, 4, 2, 2, STEEL.front)
    s.shadow(2, 14, 12)
    return {"NIGHTSTAND": s}


# --------------------------------------------------------------------------- #
# Salle de bain
# --------------------------------------------------------------------------- #
def shower() -> Sprites:
    out: Sprites = {}
    for name, closed, shift in (
        ("SHOWER_OFF", False, 0),
        ("SHOWER_ON_1", True, 0),
        ("SHOWER_ON_2", True, 1),
    ):
        s = Sprite(16, 32)
        _tiles(s, 1, 2, 14, 15, TILE_BLUE)
        s.rect(6, 3, 4, 2, STEEL.line)  # pommeau
        s.rect(7, 5, 2, 1, STEEL.front)
        s.box(1, 16, 14, 14, 3, WHITE)  # receveur
        s.rect(3, 19, 10, 8, TILE_BLUE.top)
        s.px(8, 23, STEEL.dark)
        s.hline(1, 14, 4, STEEL.line)  # tringle
        if closed:  # rideau tiré, plis qui bougent
            for x in range(2, 14):
                color = TILE_BLUE.line if (x + shift) % 3 == 0 else "#6f9fc4"
                s.vline(x, 5, 27, color)
            s.hline(2, 13, 5, "#4f7ea6")
        else:  # rideau replié sur le côté
            for x in range(2, 5):
                s.vline(x, 5, 27, "#6f9fc4" if x != 3 else "#4f7ea6")
        s.shadow(1, 30, 14)
        out[name] = s
    return out


def toilet() -> Sprites:
    s = Sprite(16, 32)
    s.box(3, 9, 10, 8, 3, WHITE)  # réservoir contre le mur
    s.rect(7, 10, 2, 1, STEEL.front)
    s.rect(4, 17, 8, 11, WHITE.line)  # cuvette
    s.rect(5, 18, 6, 8, WHITE.top)
    s.rect(6, 19, 4, 5, WHITE.front)
    s.hline(5, 10, 18, WHITE.hi)
    s.rect(6, 27, 4, 2, WHITE.front)
    s.shadow(4, 29, 8)
    return {"TOILET": s}


def washbasin() -> Sprites:
    s = Sprite(16, 32)
    s.rect(3, 2, 10, 11, STEEL.line)  # miroir
    s.rect(4, 3, 8, 9, GLASS)
    s.vline(5, 4, 7, GLASS_HI)
    s.vline(6, 4, 5, GLASS_HI)
    s.rect(2, 15, 12, 6, WHITE.line)  # vasque
    s.rect(3, 16, 10, 4, WHITE.top)
    s.rect(5, 17, 6, 2, WHITE.front)
    s.rect(7, 14, 2, 2, STEEL.front)
    s.rect(6, 21, 4, 8, WHITE.line)  # colonne
    s.rect(7, 21, 2, 7, WHITE.top)
    s.shadow(5, 29, 6)
    return {"WASHBASIN": s}


# --------------------------------------------------------------------------- #
# Boulangerie, café, supermarché
# --------------------------------------------------------------------------- #
def bread_oven() -> Sprites:
    out: Sprites = {}
    for name, glow in (("BREAD_OVEN_OFF", 0), ("BREAD_OVEN_ON_1", 1), ("BREAD_OVEN_ON_2", 2)):
        s = Sprite(32, 32)
        s.rect(13, 0, 6, 5, STEEL.line)  # conduit
        s.rect(14, 0, 4, 4, STEEL.front)
        s.box(1, 4, 30, 26, 4, BRICK)
        for row, y in enumerate(range(9, 28, 3)):  # briques
            s.hline(2, 29, y, BRICK.dark)
            for x in range(2 + (row % 2) * 3, 29, 6):
                s.vline(x, y + 1, min(y + 2, 28), BRICK.dark)
        s.rect(9, 13, 14, 12, GRAPHITE.line)  # bouche du four
        s.rect(10, 14, 12, 10, GRAPHITE.front if not glow else FLAME[2])
        if glow:
            s.rect(11, 17, 10, 6, FLAME[1])
            for x in range(11, 21, 2):
                s.px(x + (glow - 1), 19, FLAME[0])
            s.rect(12, 21, 8, 2, BREAD[1])  # les pains qui cuisent
        s.hline(9, 22, 13, STEEL.front)
        s.shadow(1, 30, 30)
        out[name] = s
    return out


def workbench() -> Sprites:
    s = Sprite(32, 32)
    s.rect(1, 8, 30, 20, WOOD.line)
    s.rect(2, 9, 28, 14, WOOD.top)
    s.hline(2, 29, 9, WOOD.hi)
    s.rect(2, 23, 28, 4, WOOD.front)
    for fx, fy in ((5, 12), (9, 18), (14, 11), (22, 19), (26, 13), (18, 15), (7, 15)):  # farine
        s.px(fx, fy, "#f6f1e7")
    s.rounded(5, 11, 9, 7, "#efe3c4", "#bfae86")  # pâtons
    s.rounded(16, 13, 7, 6, "#efe3c4", "#bfae86")
    s.px(8, 13, "#fbf3df")
    s.rect(21, 10, 7, 2, WOOD.hi)  # rouleau
    s.px(20, 10, WOOD.line)
    s.px(28, 10, WOOD.line)
    s.rect(2, 27, 3, 2, WOOD.line)
    s.rect(27, 27, 3, 2, WOOD.line)
    s.shadow(4, 29, 24)
    return {"WORKBENCH": s}


def _pastries(s: Sprite, x0: int, x1: int, y: int) -> None:
    """Une rangée de viennoiseries et de pains dans une vitrine."""
    kinds = ("croissant", "baguette", "tarte", "pain")
    for i, x in enumerate(range(x0, x1 - 3, 6)):
        kind = kinds[i % len(kinds)]
        if kind == "croissant":
            s.rect(x, y + 1, 4, 2, BREAD[1])
            s.px(x + 1, y, BREAD[0])
            s.px(x + 2, y, BREAD[0])
        elif kind == "baguette":
            s.rect(x, y + 1, 5, 2, BREAD[0])
            s.hline(x, x + 4, y + 2, BREAD[2])
        elif kind == "tarte":
            s.rect(x, y, 4, 3, BREAD[2])
            s.rect(x + 1, y + 1, 2, 1, "#c8323f")
        else:
            s.rounded(x, y, 4, 3, BREAD[1], BREAD[3])


def bakery_counter() -> Sprites:
    s = Sprite(48, 32)
    s.rect(0, 2, 48, 27, WOOD.line)
    s.rect(1, 3, 46, 5, WOOD.top)  # dessus
    s.hline(1, 46, 3, WOOD.hi)
    s.hline(1, 46, 8, WOOD.dark)
    s.rect(1, 9, 46, 15, GLASS)  # vitrine
    s.hline(1, 46, 9, GLASS_HI)
    s.hline(1, 46, 16, STEEL.front)
    _pastries(s, 3, 46, 12)
    _pastries(s, 6, 46, 19)
    s.vline(2, 10, 22, GLASS_HI)
    s.rect(1, 24, 46, 4, WOOD.front)
    s.hline(1, 46, 27, WOOD.dark)
    s.shadow(0, 29, 48, 3)
    return {"BAKERY_COUNTER": s}


def cafe_counter() -> Sprites:
    s = Sprite(48, 32)
    s.rect(0, 2, 48, 27, WOOD_DARK.line)
    s.rect(1, 3, 46, 5, WOOD_DARK.top)
    s.hline(1, 46, 3, WOOD_DARK.hi)
    s.hline(1, 46, 8, WOOD_DARK.dark)
    s.rect(1, 9, 46, 18, WOOD_DARK.front)
    for x in range(5, 46, 6):  # lambris
        s.vline(x, 10, 23, WOOD_DARK.dark)
    s.hline(1, 46, 24, "#d4a94a")  # repose-pieds en laiton
    s.hline(1, 46, 26, WOOD_DARK.dark)
    s.shadow(0, 29, 48, 3)
    return {"CAFE_COUNTER": s}


def cash_register() -> Sprites:
    s = Sprite(16, 16)
    s.rect(3, 2, 10, 5, GRAPHITE.line)  # écran
    s.rect(4, 3, 8, 3, "#5fc6a0")
    s.rect(2, 7, 12, 7, GRAPHITE.line)
    s.rect(3, 8, 10, 5, GRAPHITE.top)
    for kx in range(4, 12, 2):
        s.px(kx, 9, GRAPHITE.hi)
        s.px(kx, 11, GRAPHITE.hi)
    return {"CASH_REGISTER": s}


def espresso_machine() -> Sprites:
    s = Sprite(16, 16)
    s.rect(2, 3, 12, 11, STEEL.line)
    s.rect(3, 4, 10, 4, STEEL.top)
    s.hline(3, 12, 4, STEEL.hi)
    s.rect(3, 8, 10, 5, STEEL.front)
    s.rect(5, 8, 2, 2, GRAPHITE.line)  # groupe
    s.rect(9, 8, 2, 2, GRAPHITE.line)
    s.rect(5, 11, 2, 2, WHITE.top)  # tasses
    s.rect(9, 11, 2, 2, WHITE.top)
    s.rect(4, 1, 2, 2, WHITE.top)
    s.rect(7, 1, 2, 2, WHITE.top)
    return {"ESPRESSO_MACHINE": s}


def bread_shelf() -> Sprites:
    s = Sprite(32, 32)
    s.rect(1, 9, 30, 21, WOOD_DARK.line)
    s.rect(2, 10, 28, 19, "#3a2422")
    for y in (15, 21, 27):  # étagères
        s.hline(2, 29, y, WOOD.top)
        s.hline(2, 29, y + 1, WOOD.front)
    for x in range(3, 28, 4):  # baguettes debout
        s.vline(x, 10, 14, BREAD[0])
        s.vline(x + 1, 11, 14, BREAD[2])
    for x in range(3, 27, 5):  # pains ronds
        s.rounded(x, 17, 4, 4, BREAD[1], BREAD[3])
    for x in range(4, 26, 6):
        s.rect(x, 24, 4, 3, BREAD[2])
        s.hline(x, x + 3, 24, BREAD[0])
    return {"BREAD_SHELF": s}


def menu_board() -> Sprites:
    s = Sprite(32, 32)
    s.rect(2, 10, 28, 18, WOOD.line)
    s.rect(3, 11, 26, 16, "#2f3d36")
    for i, y in enumerate((13, 16, 19, 22, 25)):  # lignes à la craie
        s.hline(5, 5 + (8, 14, 10, 16, 12)[i], y, "#d9e3dc")
        s.hline(24, 26, y, "#e9d36b")
    return {"MENU_BOARD": s}


_GOODS = {
    "SHELF_PRODUCE": ("#c8323f", "#f2a623", "#7cc35a", "#e9d36b", "#4f9447"),
    "SHELF_GROCERY": ("#e85d24", "#658eb1", "#efe3c4", "#b84349", "#d4a94a"),
    "SHELF_DRINKS": ("#4f8fd0", "#5fc6a0", "#d6ecf5", "#c8323f", "#3b6ea5"),
}


def shelves() -> Sprites:
    out: Sprites = {}
    for name, goods in _GOODS.items():
        s = Sprite(32, 32)
        s.rect(1, 2, 30, 27, STEEL.line)
        s.rect(2, 3, 28, 3, STEEL.top)
        s.hline(2, 29, 3, STEEL.hi)
        s.rect(2, 6, 28, 22, "#e9ecef")
        for row, y in enumerate((7, 14, 21)):
            for i, x in enumerate(range(3, 28, 3)):
                color = goods[(i + row * 2) % len(goods)]
                height = 4 if name != "SHELF_DRINKS" else 5
                if name == "SHELF_PRODUCE":
                    s.rounded(x, y + 2, 3, 3, color, "#4a3b2a")
                else:
                    s.rect(x, y + 5 - height + 1, 2, height, color)
                    s.px(x, y + 5 - height + 1, "#ffffff")
            s.hline(2, 29, y + 6, STEEL.front)
        s.vline(2, 6, 27, STEEL.front)
        s.vline(29, 6, 27, STEEL.front)
        s.shadow(1, 29, 30, 3)
        out[name] = s
    return out


def checkout() -> Sprites:
    s = Sprite(32, 32)
    s.rect(0, 2, 32, 27, STEEL.line)
    s.rect(1, 3, 18, 6, GRAPHITE.front)  # tapis roulant
    for x in range(3, 18, 3):
        s.vline(x, 3, 8, GRAPHITE.top)
    s.rect(19, 3, 12, 6, STEEL.top)
    s.rect(21, 0, 8, 5, GRAPHITE.line)  # caisse
    s.rect(22, 1, 6, 3, "#5fc6a0")
    s.rect(1, 9, 30, 18, WHITE.front)
    s.rect(1, 13, 30, 3, "#c8323f")  # bandeau de l'enseigne
    s.hline(1, 30, 9, WHITE.hi)
    s.hline(1, 30, 26, WHITE.dark)
    s.shadow(0, 29, 32, 3)
    return {"CHECKOUT": s}


# --------------------------------------------------------------------------- #
# Salle de sport
# --------------------------------------------------------------------------- #
def treadmill() -> Sprites:
    s = Sprite(16, 32)
    s.rect(2, 6, 12, 6, GRAPHITE.line)  # console
    s.rect(3, 7, 10, 4, GRAPHITE.top)
    s.rect(5, 8, 6, 2, "#e85d24")
    s.vline(2, 11, 20, STEEL.front)  # rampes
    s.vline(13, 11, 20, STEEL.front)
    s.rect(2, 14, 12, 15, GRAPHITE.line)  # tapis
    s.rect(3, 15, 10, 13, GRAPHITE.front)
    for y in range(16, 28, 3):
        s.hline(3, 12, y, GRAPHITE.top)
    s.shadow(2, 29, 12)
    return {"TREADMILL": s}


def weight_bench() -> Sprites:
    s = Sprite(16, 32)
    s.rect(1, 8, 14, 2, STEEL.line)  # barre
    s.rect(0, 6, 3, 6, GRAPHITE.line)
    s.rect(13, 6, 3, 6, GRAPHITE.line)
    s.vline(3, 10, 14, STEEL.front)
    s.vline(12, 10, 14, STEEL.front)
    s.rounded(4, 12, 8, 16, CRIMSON.top, CRIMSON.line)  # banc rembourré
    s.vline(5, 13, 26, CRIMSON.hi)
    s.rect(6, 28, 4, 1, STEEL.dark)
    s.shadow(4, 29, 8)
    return {"WEIGHT_BENCH": s}


# --------------------------------------------------------------------------- #
# Extérieur
# --------------------------------------------------------------------------- #
def _canopy(s: Sprite, cx: int, cy: int, r: int, palette: tuple[str, ...]) -> None:
    """Feuillage arrondi : disque sombre, puis plus clair vers le haut-gauche."""
    hi, light, mid, dark, line = palette
    for dy in range(-r - 1, r + 2):
        for dx in range(-r - 1, r + 2):
            d2 = dx * dx + dy * dy
            if d2 <= (r + 1) * (r + 1) - r:
                s.px(cx + dx, cy + dy, line)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            d2 = dx * dx + dy * dy
            if d2 > r * r:
                continue
            shade = dx + dy
            color = dark if shade > r // 2 else mid if shade > -r // 2 else light
            if (dx * 7 + dy * 13) % 11 == 0:
                color = hi if shade < 0 else mid
            s.px(cx + dx, cy + dy, color)


def trees() -> Sprites:
    out: Sprites = {}
    round_tree = Sprite(32, 48)
    round_tree.rect(6, 43, 20, 3, (0, 0, 0, 60))
    round_tree.rect(13, 28, 6, 16, WOOD_DARK.line)
    round_tree.rect(14, 28, 4, 15, WOOD_DARK.front)
    round_tree.vline(15, 29, 41, WOOD_DARK.hi)
    _canopy(round_tree, 16, 18, 13, LEAF)
    _canopy(round_tree, 10, 23, 7, LEAF)
    _canopy(round_tree, 22, 23, 7, LEAF)
    out["TREE_ROUND"] = round_tree

    pine = Sprite(32, 48)
    pine.rect(8, 43, 16, 3, (0, 0, 0, 60))
    pine.rect(14, 34, 4, 10, WOOD_DARK.line)
    pine.rect(15, 34, 2, 9, WOOD_DARK.front)
    dark_leaf = ("#6fae68", "#4f9447", "#3b7a45", "#2a5a37", "#13201a")
    for layer, (top, half) in enumerate(((2, 5), (10, 8), (18, 11), (25, 13))):
        for y in range(top, top + 10):
            width = max(1, int((y - top + 1) / 10 * half))
            for x in range(16 - width, 16 + width):
                edge = x in (16 - width, 16 + width - 1) or y == top + 9
                color = dark_leaf[4] if edge else dark_leaf[1 if x < 16 else 2]
                if not edge and (x + y + layer) % 7 == 0:
                    color = dark_leaf[0]
                pine.px(x, y, color)
    out["TREE_PINE"] = pine

    bush = Sprite(16, 16)
    bush.rect(2, 13, 12, 2, (0, 0, 0, 60))
    _canopy(bush, 8, 8, 6, LEAF)
    out["BUSH"] = bush
    return out


def hedge() -> Sprites:
    s = Sprite(16, 16)
    s.rect(0, 2, 16, 12, GREEN.line)
    s.rect(0, 3, 16, 5, GREEN.top)
    s.rect(0, 8, 16, 5, GREEN.front)
    for x, y in ((2, 4), (7, 3), (12, 5), (4, 6), (10, 4), (14, 6)):
        s.px(x, y, GREEN.hi)
    for x, y in ((3, 10), (8, 9), (13, 11), (6, 12), (11, 9)):
        s.px(x, y, GREEN.dark)
    s.rect(0, 14, 16, 2, (0, 0, 0, 55))
    # Morceau vertical : vue de dessus, on ne voit que le sommet de la haie,
    # qui se raccorde sans couture vers le haut et vers le bas.
    v = Sprite(16, 16)
    v.rect(2, 0, 12, 16, GREEN.line)
    v.rect(3, 0, 10, 16, GREEN.top)
    v.rect(10, 0, 3, 16, GREEN.front)
    for x, y in ((4, 2), (6, 7), (5, 12), (8, 4), (7, 14), (4, 9)):
        v.px(x, y, GREEN.hi)
    for x, y in ((11, 3), (10, 9), (12, 13)):
        v.px(x, y, GREEN.dark)
    v.rect(14, 0, 2, 16, (0, 0, 0, 45))
    return {"HEDGE": s, "HEDGE_V": v}


def park_bench() -> Sprites:
    s = Sprite(32, 16)
    s.rect(1, 1, 30, 6, WOOD.line)  # dossier
    s.rect(2, 2, 28, 2, WOOD.top)
    s.rect(2, 4, 28, 2, WOOD.front)
    s.rect(1, 7, 30, 4, WOOD.line)  # assise
    s.rect(2, 7, 28, 3, WOOD.hi)
    s.hline(2, 29, 9, WOOD.top)
    for x in (3, 27):  # pieds en fonte
        s.rect(x, 11, 2, 3, GRAPHITE.line)
    s.shadow(2, 14, 28)
    return {"PARK_BENCH": s}


def lamppost() -> Sprites:
    s = Sprite(16, 32)
    s.rect(4, 2, 8, 5, GRAPHITE.line)
    s.rect(5, 3, 6, 3, "#fcde5a")
    s.hline(5, 10, 3, "#fff6c4")
    s.rect(7, 7, 2, 21, GRAPHITE.line)
    s.vline(7, 8, 26, GRAPHITE.top)
    s.rect(5, 27, 6, 2, GRAPHITE.line)
    s.shadow(5, 29, 6)
    return {"LAMPPOST": s}


def window() -> Sprites:
    s = Sprite(16, 32)
    s.rect(2, 12, 12, 15, WHITE.line)
    s.rect(3, 13, 10, 13, WHITE.top)
    s.rect(4, 14, 8, 11, GLASS)
    s.vline(7, 14, 24, WHITE.top)  # croisillons
    s.hline(4, 11, 19, WHITE.top)
    s.px(5, 15, GLASS_HI)
    s.px(5, 16, GLASS_HI)
    s.px(9, 20, GLASS_HI)
    s.hline(1, 14, 27, WHITE.front)  # appui de fenêtre
    return {"WINDOW": s}


# --------------------------------------------------------------------------- #
# Étape 6 ter : casino, bar, boutiques
# --------------------------------------------------------------------------- #
def slot_machine() -> Sprites:
    """Machine à sous : trois rouleaux, un levier ; allumée, elle clignote."""
    out: Sprites = {}
    lights = {
        "SLOT_MACHINE_OFF": None,
        "SLOT_MACHINE_ON_1": "#fcde5a",
        "SLOT_MACHINE_ON_2": "#e85d24",
    }
    for name, light in lights.items():
        s = Sprite(16, 32)
        s.rect(1, 2, 13, 27, CRIMSON.line)
        s.rect(2, 3, 11, 25, CRIMSON.front)
        s.rect(2, 3, 11, 3, light or CRIMSON.top)  # fronton lumineux
        s.rect(3, 8, 9, 7, GRAPHITE.line)  # rouleaux
        for i, symbol in enumerate(("#e85d24", "#fcde5a", "#5fc6a0")):
            s.rect(4 + 3 * i, 9, 2, 5, WHITE.top)
            s.rect(4 + 3 * i, 11, 2, 1, symbol if light else "#c6ccd4")
        s.rect(4, 17, 7, 2, "#d4a94a")  # fente à pièces
        s.rect(3, 22, 9, 5, CRIMSON.dark)  # bac
        s.vline(14, 6, 13, STEEL.front)  # levier
        s.px(14, 5, "#c8323f")
        s.px(15, 5, "#c8323f")
        s.shadow(1, 29, 14)
        out[name] = s
    return out


def roulette_table() -> Sprites:
    s = Sprite(48, 32)
    s.rect(0, 4, 48, 24, WOOD_DARK.line)
    s.rect(1, 5, 46, 20, "#2f7a4a")  # tapis vert
    s.frame(1, 5, 46, 20, "#245d39")
    for i in range(6):  # cases
        s.rect(20 + 4 * i, 8, 3, 3, "#c8323f" if i % 2 else "#1e1c22")
        s.rect(20 + 4 * i, 13, 3, 3, "#1e1c22" if i % 2 else "#c8323f")
    s.rect(4, 7, 13, 13, WOOD.line)  # cylindre
    s.rect(5, 8, 11, 11, WOOD.front)
    s.rect(7, 10, 7, 7, "#c8323f")
    s.rect(9, 12, 3, 3, "#d4a94a")
    s.px(10, 13, WHITE.hi)
    s.hline(1, 46, 25, WOOD_DARK.front)
    s.shadow(0, 28, 48, 3)
    return {"ROULETTE_TABLE": s}


def _counter(color: Material, stripe: str) -> Sprite:
    s = Sprite(32, 32)
    s.rect(0, 2, 32, 27, color.line)
    s.rect(1, 3, 30, 6, color.top)
    s.hline(1, 30, 3, color.hi)
    s.rect(1, 9, 30, 18, color.front)
    s.rect(1, 13, 30, 3, stripe)
    s.rect(21, 0, 8, 5, GRAPHITE.line)  # terminal de paiement
    s.rect(22, 1, 6, 3, "#5fc6a0")
    s.hline(1, 30, 26, color.dark)
    s.shadow(0, 29, 32, 3)
    return s


def shop_counters() -> Sprites:
    return {
        "BOUTIQUE_COUNTER": _counter(CREAM, "#c25769"),
        "TECH_COUNTER": _counter(GRAPHITE, "#4f8fd0"),
        "BAR_COUNTER": _counter(WOOD_DARK, "#d4a94a"),
    }


def clothes_rack() -> Sprites:
    s = Sprite(32, 32)
    s.hline(2, 29, 6, STEEL.line)  # tringle
    s.vline(2, 6, 28, STEEL.front)
    s.vline(29, 6, 28, STEEL.front)
    colors = ("#c25769", "#658eb1", "#efe3c4", "#619947", "#e9d36b", "#3a3a40")
    for i, color in enumerate(colors):
        x = 4 + 4 * i
        s.rect(x, 7, 3, 13, color)
        s.vline(x, 7, 19, GRAPHITE.line)
        s.px(x + 1, 6, STEEL.line)
    s.hline(1, 30, 28, STEEL.line)
    s.shadow(1, 29, 30, 3)
    return {"CLOTHES_RACK": s}


def tech_shelf() -> Sprites:
    s = Sprite(32, 32)
    s.rect(0, 1, 32, 28, GRAPHITE.line)
    s.rect(1, 2, 30, 26, GRAPHITE.front)
    s.rect(3, 4, 12, 8, "#1e2632")  # téléviseurs
    s.rect(4, 5, 10, 6, "#3b6ea5")
    s.rect(17, 4, 12, 8, "#1e2632")
    s.rect(18, 5, 10, 6, "#4a7d4f")
    s.hline(1, 30, 14, GRAPHITE.top)
    for i in range(6):  # téléphones et consoles
        s.rect(3 + 5 * i, 17, 3, 5, "#1e1c22")
        s.px(4 + 5 * i, 18, "#6fb3d9")
    s.hline(1, 30, 24, GRAPHITE.top)
    s.shadow(0, 29, 32, 3)
    return {"TECH_SHELF": s}


ALL = (
    fridge,
    stove,
    kitchen_sink,
    kitchen_counter,
    bed,
    wardrobe,
    tv,
    nightstand,
    shower,
    toilet,
    washbasin,
    bread_oven,
    workbench,
    bakery_counter,
    cafe_counter,
    cash_register,
    espresso_machine,
    bread_shelf,
    menu_board,
    shelves,
    checkout,
    treadmill,
    weight_bench,
    trees,
    hedge,
    park_bench,
    lamppost,
    window,
    slot_machine,
    roulette_table,
    shop_counters,
    clothes_rack,
    tech_shelf,
)

# Palette réutilisée par d'autres modules (sols extérieurs).
PALETTE = {"leaf": LEAF, "bread": BREAD, "cream": CREAM}
