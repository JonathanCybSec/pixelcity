# Crédits et licences

## Assets

| Asset | Origine | Licence |
|---|---|---|
| Personnages, sols, murs et meubles de bureau (`pixelcity/assets/pixel_agents/`) | [pixel-agents](https://github.com/pixel-agents-hq/pixel-agents), copiés sans modification (commit noté dans `SOURCE.md`) | MIT (fichier `LICENSE` conservé dans le dossier) |
| Bases des personnages | [Metro City](https://jik-a-4.itch.io/metrocity-free-topdown-character-pack) de JIK-A-4, retravaillés par pixel-agents | CC0 |
| Meubles de maison, de commerce, de sport et d'extérieur, sols extérieurs (`pixelcity/assets/pixelcity/`) | Dessinés par le code (`tools/sprites_furniture.py`, `tools/draw_assets.py`) dans le style de pixel-agents | celle du projet |
| Carte, tileset et murs colorisés (`pixelcity/assets/maps/`) | Générés par `tools/make_city.py` à partir des sols et murs de pixel-agents | MIT (pixel-agents) pour les motifs d'origine |
| Police [Inter](https://rsms.me/inter/) (`pixelcity/assets/fonts/`) | Rasmus Andersson et contributeurs, version 4.1 | SIL Open Font License 1.1 (fichier `Inter-LICENSE.txt` joint) |

Note sur pixel-agents : le dépôt est publié sous licence MIT et ne prévoit pas de licence distincte pour ses images. On applique donc la MIT (attribution et copie de la licence) ; si les auteurs précisent un jour une autre licence pour leurs assets, ce tableau sera mis à jour. Les pièces de leur moteur reprises en Python (colorisation HSL des sols et murs, auto-tuilage des murs par masque de voisins, règles de tri en profondeur des chaises et des objets posés) sont des portages de code MIT, signalés dans les commentaires.

## Dépendances

| Bibliothèque | Rôle | Licence |
|---|---|---|
| [pygame-ce](https://pyga.me/) | Fenêtre, rendu 2D, entrées, police | LGPL v2.1 |
| [PyTMX](https://github.com/bitcraft/pytmx) | Chargement des images de la carte Tiled (rendu) | LGPL v3 |
| [PyYAML](https://pyyaml.org/) | Lecture des fichiers de configuration | MIT |
| [Pydantic](https://docs.pydantic.dev/) | Validation de la configuration | MIT |
| pytest, mypy, ruff | Outils de développement (non distribués) | MIT |

Note pour l'exécutable Windows : pygame-ce et PyTMX sont sous LGPL. Les distribuer dans un `.exe` est permis, à condition que l'utilisateur puisse remplacer ces bibliothèques par une autre version. Le mode « dossier » de PyInstaller (`--onedir`) facilite cette conformité. La licence OFL d'Inter autorise d'embarquer la police, à condition de joindre sa licence.

## Inspirations

- J. S. Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, UIST 2023 (la ville « Smallville »).
- [AI Town](https://github.com/a16z-infra/ai-town) (a16z-infra), projet open source.
- *Les Sims* (Maxis, 2000) pour le principe des « smart objects » : l'intelligence est dans les objets.

Seule l'architecture (flux de mémoire, réflexion, planification, deux couches routine / cognition) est reprise de Generative Agents et d'AI Town ; aucun code de ces projets n'est réutilisé.
