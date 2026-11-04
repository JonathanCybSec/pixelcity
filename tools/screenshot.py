"""Capture une image du rendu SANS ouvrir de fenêtre (pilote vidéo « dummy » de SDL).

Usage :
    python tools/screenshot.py docs/screenshot.png --hour 17.7 --zoom 2 --debug

Utile pour vérifier le rendu sur une machine sans écran (serveur, CI) et pour
illustrer la documentation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from pixelcity.config.loader import load_config
from pixelcity.engine.app import GameApp
from pixelcity.sim.simulation import Simulation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--hour", type=float, default=17.7, help="heure simulée du lundi")
    parser.add_argument("--zoom", type=int, default=2)
    parser.add_argument("--debug", action="store_true", help="afficher l'overlay F3")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--center", type=float, nargs=2, default=None, help="centre (tuiles)")
    args = parser.parse_args()

    sim = Simulation(load_config(), seed=args.seed)
    sim.run_ticks(round(args.hour * 60 * sim.clock.ticks_per_minute))
    app = GameApp(sim)
    app.camera.zoom = args.zoom
    if args.center:
        app.camera.center_x = args.center[0] * app.renderer.tile_w
        app.camera.center_y = args.center[1] * app.renderer.tile_h
    app.camera.clamp()
    app.overlay.enabled = args.debug
    app.paused = True
    app.frame(0.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(app.screen, str(args.output))
    pygame.quit()
    print(f"Capture enregistrée : {args.output} ({sim.clock.label()})")


if __name__ == "__main__":
    main()
