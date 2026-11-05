"""Capture une image du jeu SANS ouvrir de fenêtre (pilote vidéo « dummy » de SDL).

Usage :
    python tools/screenshot.py docs/screenshot.png --day 2 --hour 12.6 --zoom 3 \
        --select lea --size 1600 900

Utile pour vérifier le rendu sur une machine sans écran (serveur, CI) et pour
illustrer la documentation.
"""

from __future__ import annotations

import argparse
import dataclasses
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
    parser.add_argument("--day", type=int, default=1, help="jour (1 = lundi)")
    parser.add_argument("--hour", type=float, default=12.5, help="heure simulée (12.5 = 12:30)")
    parser.add_argument("--zoom", type=int, default=3)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--size", type=int, nargs=2, default=(1600, 900), help="taille de la fenêtre"
    )
    parser.add_argument("--center", type=float, nargs=2, default=None, help="centre (tuiles)")
    parser.add_argument("--select", default=None, help="habitant à sélectionner (et suivre)")
    parser.add_argument("--place", default=None, help="lieu à sélectionner")
    parser.add_argument("--debug", action="store_true", help="afficher la couche F3")
    parser.add_argument(
        "--frames", type=int, default=12, help="images avant la capture (animations)"
    )
    parser.add_argument(
        "--play", type=float, default=0.0, help="secondes jouées à x1 avant la capture (bulles)"
    )
    args = parser.parse_args()

    config = load_config()
    window = config.settings.window.model_copy(
        update={"width": args.size[0], "height": args.size[1]}
    )
    config = dataclasses.replace(
        config, settings=config.settings.model_copy(update={"window": window})
    )
    sim = Simulation(config, seed=args.seed)
    minutes = (args.day - 1) * 24 * 60 + args.hour * 60
    sim.run_ticks(round(minutes * sim.clock.ticks_per_minute))
    app = GameApp(sim)
    app.camera.zoom = args.zoom
    if args.center:
        app.camera.center_x = args.center[0] * 16
        app.camera.center_y = args.center[1] * 16
    app.camera.clamp()
    if args.select:
        app.ui.select_agent(args.select, follow=True)
    if args.place:
        app.ui.select_place(args.place)
    app.ui.state.debug = args.debug
    app.hover_enabled = False
    app.paused = args.play <= 0
    for _ in range(round(args.play * 30)):
        app.frame(1 / 30)
    app.paused = True
    for _ in range(args.frames):
        app.frame(1 / 30)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(app.screen, str(args.output))
    pygame.quit()
    print(f"Capture enregistrée : {args.output} ({sim.clock.label()})")


if __name__ == "__main__":
    main()
