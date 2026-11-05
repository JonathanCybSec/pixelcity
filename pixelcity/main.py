"""Point d'entrée de PixelCity.

python -m pixelcity                                  # fenêtre
python -m pixelcity --headless --days 7 --seed 42    # sans fenêtre
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from pixelcity.config.loader import ConfigError, load_config
from pixelcity.llm.backends import make_backend
from pixelcity.llm.settings import load_llm_settings
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
    parser.add_argument(
        "--no-llm", action="store_true", help="répliques scriptées, sans appeler Ollama"
    )
    return parser


def _ensure_utf8_output() -> None:
    """Évite un plantage classique sous Windows.

    Dans une console, Python écrit en Unicode sans souci. Mais si la sortie est
    redirigée (`python -m pixelcity --headless > journal.txt`), il utilise
    l'encodage local, cp1252, qui ne connaît ni « ─ » ni « → » : `print()`
    lèverait une `UnicodeEncodeError`. On force donc l'UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        if not isinstance(stream, io.TextIOWrapper):
            continue  # flux remplacé (tests, IDE) : on n'y touche pas
        if stream.encoding.lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days doit être strictement positif")
    try:
        config = load_config(args.config)
        settings = load_llm_settings()
        if args.no_llm:
            settings = replace(settings, enabled=False)
        # En headless, la simulation attend chaque réponse : le journal reste
        # lisible et ne dépend pas de la vitesse de la carte graphique.
        backend = make_backend(settings, config.dialogues, blocking=args.headless)
        sim = Simulation(config, seed=args.seed, dialogue=backend)
    except (ConfigError, MapError, TmxError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2

    if args.headless:
        from pixelcity.headless import run_headless

        try:
            print(f"Conversations : {sim.conversations.status()}")
            run_headless(sim, args.days, verbose=not args.quiet, jsonl_path=args.log)
        except BrokenPipeError:
            # Sortie envoyée dans un programme qui s'arrête avant la fin
            # (`... | head -20`) : ce n'est pas une erreur de la simulation.
            # On redirige stdout vers « nulle part » pour que Python ne
            # replante pas en vidant ses tampons à la fermeture.
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            return 1
        finally:
            sim.close()
        return 0

    # Import « paresseux » : pygame n'est chargé QUE si on ouvre une fenêtre.
    # Le mode headless ne le touche jamais, même indirectement.
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from pixelcity.engine.app import GameApp

    try:
        GameApp(sim).run()
    finally:
        sim.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
