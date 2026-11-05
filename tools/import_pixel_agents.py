"""Importe les assets de pixel-agents (licence MIT) dans `pixelcity/assets/pixel_agents/`.

Usage :
    git clone --depth 1 https://github.com/pixel-agents-hq/pixel-agents /chemin/pixel-agents
    python tools/import_pixel_agents.py /chemin/pixel-agents

Le script copie les personnages, sols, murs, tapis et meubles, ainsi que la
licence MIT du projet d'origine, et note le commit importé dans SOURCE.md.
On versionne le résultat : le jeu ne dépend pas d'un clone de pixel-agents.

Rappel sur les licences (voir CREDITS.md) : le code et les assets de
pixel-agents sont publiés sous MIT ; leurs personnages sont basés sur le pack
CC0 « Metro City » de JIK-A-4.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "pixelcity" / "assets" / "pixel_agents"
FOLDERS = ("characters", "floors", "walls", "carpets", "furniture")


def main() -> None:
    parser = argparse.ArgumentParser(description="Importe les assets de pixel-agents.")
    parser.add_argument("source", type=Path, help="clone local de pixel-agents")
    args = parser.parse_args()

    assets = args.source / "webview-ui" / "public" / "assets"
    if not assets.is_dir():
        raise SystemExit(f"dossier d'assets introuvable : {assets}")

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    for folder in FOLDERS:
        shutil.copytree(assets / folder, DEST / folder)
    shutil.copy(args.source / "LICENSE", DEST / "LICENSE")

    commit = subprocess.run(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    (DEST / "SOURCE.md").write_text(
        "# Origine de ces fichiers\n\n"
        "Copiés sans modification depuis https://github.com/pixel-agents-hq/pixel-agents "
        f"(dossier `webview-ui/public/assets/`, commit `{commit or 'inconnu'}`).\n\n"
        "Licence : MIT (voir `LICENSE` dans ce dossier). Les personnages sont basés sur le pack "
        "CC0 « Metro City » de JIK-A-4 : https://jik-a-4.itch.io/metrocity-free-topdown-character-pack\n",
        encoding="utf-8",
    )
    count = sum(1 for _ in DEST.rglob("*.png"))
    print(f"{count} images importées dans {DEST}")


if __name__ == "__main__":
    main()
