"""Aperçu de la ville sans lancer le jeu : la carte entière + des gros plans.

Usage :  python tools/preview_city.py [dossier_de_sortie]

Sert à vérifier un gabarit de bâtiment après l'avoir modifié dans
`make_city.py` : on voit tout de suite un meuble mal placé ou un mur oublié.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from pixelcity.config.loader import load_config
from pixelcity.engine.scene import bake_ground, build_scene
from pixelcity.engine.sprites import TILE, SpriteBank
from pixelcity.resources import assets_dir
from pixelcity.world.catalog import load_catalog
from pixelcity.world.world import load_world

ROOT = Path(__file__).resolve().parents[1]

# Gros plans (en tuiles) : x, y, largeur, hauteur, nom.
CLOSEUPS = (
    (0, 1, 30, 28, "quartier_residentiel"),
    (33, 14, 30, 16, "residence_tilleuls"),
    (65, 12, 31, 18, "bureaux"),
    (33, 32, 30, 32, "commerces"),
    (65, 32, 31, 32, "ecole_sport"),
    (0, 33, 30, 31, "parc"),
)


def render_full_map() -> pygame.Surface:
    config = load_config()
    assets = assets_dir()
    catalog = load_catalog(assets / "pixel_agents", assets / "pixelcity")
    map_path = assets / "maps" / config.city.map
    world = load_world(map_path, config.city, config.objects, catalog)
    bank = SpriteBank(assets / "pixel_agents" / "characters", map_path.parent / "walls")
    scene = build_scene(world, bank, bake_ground(map_path))
    image = scene.ground.copy()
    for prop in sorted(scene.props, key=lambda p: p.z):
        image.blit(prop.image(0.0), (prop.x, prop.y))
    return image


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    image = render_full_map()
    pygame.image.save(image, str(out_dir / "city_full.png"))
    for x, y, w, h, name in CLOSEUPS:
        crop = image.subsurface(pygame.Rect(x * TILE, y * TILE, w * TILE, h * TILE))
        big = pygame.transform.scale_by(crop, 2)
        pygame.image.save(big, str(out_dir / f"city_{name}.png"))
    print(f"Aperçus écrits dans {out_dir}")


if __name__ == "__main__":
    main()
