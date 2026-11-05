"""Point d'entrée de l'exécutable : PyInstaller a besoin d'un script, pas d'un paquet."""

import sys

from pixelcity.main import main

if __name__ == "__main__":
    sys.exit(main())
