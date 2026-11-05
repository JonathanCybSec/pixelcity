"""Résolution des chemins vers les données du projet (config, cartes, assets).

Piège classique : `open("assets/maps/city.tmx")` dépend du dossier depuis
lequel on LANCE le programme (le « répertoire courant »), pas de l'endroit où
se trouve le code. Ça marche dans VS Code, ça casse en double-cliquant sur le
.exe. On résout donc toujours les chemins par rapport au paquet lui-même.

Pour PyInstaller (étape 8) : un exécutable « onefile » décompresse ses données
dans un dossier temporaire indiqué par `sys._MEIPASS`. On y placera le dossier
`pixelcity/` ; cette fonction est le seul endroit à adapter si besoin.
"""

from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is not None:
        return Path(bundle_dir) / "pixelcity"
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Chemin absolu d'une ressource du paquet : `resource_path("config", "city.yaml")`."""
    return package_root().joinpath(*parts)


def assets_dir() -> Path:
    """Dossier des images et des cartes."""
    return resource_path("assets")
