# Crédits et licences

## Assets

| Asset | Origine | Licence |
|---|---|---|
| Tileset placeholder (`pixelcity/assets/maps/placeholder_tiles.png`) | Généré par `tools/make_mvp_map.py` (création originale du projet) | celle du projet |
| Carte du MVP (`pixelcity/assets/maps/mvp.tmx`) | Générée par `tools/make_mvp_map.py` | celle du projet |
| Habitants (ronds colorés avec initiale) | Dessinés par le code (`engine/renderer.py`) | celle du projet |
| Police d'affichage | Police par défaut de pygame-ce (`freesansbold.ttf`, GNU FreeFont) | GPL v3 avec exception pour les polices |

À l'étape 4, le tileset placeholder sera remplacé par des assets pixel art CC0 (Kenney.nl notamment) ; chaque pack utilisé sera listé ici avec sa licence. À l'étape 5, une police pixel art sous licence CC0 ou OFL remplacera la police par défaut.

## Dépendances

| Bibliothèque | Rôle | Licence |
|---|---|---|
| [pygame-ce](https://pyga.me/) | Fenêtre, rendu 2D, entrées | LGPL v2.1 |
| [PyTMX](https://github.com/bitcraft/pytmx) | Chargement des images de la carte Tiled (rendu) | LGPL v3 |
| [PyYAML](https://pyyaml.org/) | Lecture des fichiers de configuration | MIT |
| [Pydantic](https://docs.pydantic.dev/) | Validation de la configuration | MIT |
| pytest, mypy, ruff | Outils de développement (non distribués) | MIT |

Note pour l'étape 8 : pygame-ce et PyTMX sont sous LGPL. Les distribuer dans un `.exe` est permis, à condition que l'utilisateur puisse remplacer ces bibliothèques par une autre version. Le mode « dossier » de PyInstaller (`--onedir`) facilite cette conformité.

## Inspirations

- J. S. Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, UIST 2023 (la ville « Smallville »).
- [AI Town](https://github.com/a16z-infra/ai-town) (a16z-infra), projet open source.

Seule l'architecture (flux de mémoire, réflexion, planification, deux couches routine / cognition) est reprise ; aucun code de ces projets n'est réutilisé.
