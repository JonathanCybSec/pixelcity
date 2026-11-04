"""Permet `python -m pixelcity`.

Ce fichier doit rester lisible par n'importe quelle version de Python 3 :
c'est lui qui vérifie la version AVANT d'importer le reste du projet. Le code
utilise la syntaxe de Python 3.12 (`type X = ...`, `def f[T](...)`) ; lancé
avec un Python plus ancien, on obtiendrait sinon une `SyntaxError`
incompréhensible au lieu d'un message qui dit quoi faire.
"""

import sys

# `noqa: UP036` : ruff juge ce test inutile, puisque le projet déclare
# Python >= 3.12. Mais un linter suppose que cette règle est respectée, et ce
# garde-fou sert justement aux cas où elle ne l'est pas (mauvais interpréteur).
if sys.version_info < (3, 12):  # noqa: UP036
    sys.exit(
        "PixelCity nécessite Python 3.12, mais cet interpréteur est Python "
        f"{sys.version.split()[0]} :\n  {sys.executable}\n"
        "Active l'environnement virtuel du projet (.venv\\Scripts\\Activate.ps1 "
        "sous Windows), vérifie avec `python --version`, puis relance."
    )

from pixelcity.main import main

raise SystemExit(main())
