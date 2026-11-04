"""Point d'entrée de PixelCity.

python -m pixelcity                                  # fenêtre
python -m pixelcity --headless --days 7 --seed 42    # sans fenêtre
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pixelcity.config.loader import ConfigError, load_config
from pixelcity.sim.simulation import Simulation
from pixelcity.world.tmx import TmxError
from pixelcity.world.world import MapError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixelcity", description="Simulation de vie en pixel art, avec des habitants IA."
    )
    parser.add_argument("--headless", action="store_true", help="simuler sans fenêtre")
    parser.add_argument("--days", type=float, default=1.0, help="jours simulés en headless")
    parser.add_argument("--seed", type=int, default=None, help="graine (sinon settings.yaml)")
    parser.add_argument("--quiet", action="store_true", help="n'afficher que le bilan")
    parser.add_argument("--log", type=Path, default=None, help="exporter les événements (JSONL)")
    parser.add_argument("--config", type=Path, default=None, help="dossier de configuration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        sim = Simulation(config, seed=args.seed)
    except (ConfigError, MapError, TmxError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2

    if args.headless:
        from pixelcity.headless import run_headless

        run_headless(sim, args.days, verbose=not args.quiet, jsonl_path=args.log)
        return 0

    # Import « paresseux » : pygame n'est chargé QUE si on ouvre une fenêtre.
    # Le mode headless ne le touche jamais, même indirectement.
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from pixelcity.engine.app import GameApp

    GameApp(sim).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
