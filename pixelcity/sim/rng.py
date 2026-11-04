"""Hasard reproductible : un générateur par sous-système, tous dérivés d'une graine.

Pourquoi pas un simple `random.seed(42)` global ?
Parce qu'avec un générateur unique, AJOUTER un seul tirage quelque part (par
exemple dans la météo) décale tous les tirages suivants, partout. Deux
simulations « même graine » divergent alors pour une raison invisible.

Ici, chaque sous-système demande son propre flux par son nom
(`rng.stream("planner:marcel")`) : les flux sont indépendants, et en ajouter
un nouveau ne perturbe pas les autres.

Pourquoi `hashlib` et pas `hash()` ? Parce que `hash("texte")` change à chaque
lancement de Python (randomisation des hash, variable PYTHONHASHSEED) :
utiliser `hash()` pour dériver une graine casserait silencieusement la
reproductibilité. SHA-256 donne le même résultat partout, tout le temps.
"""

from __future__ import annotations

import hashlib
import random


def derive_seed(master_seed: int, name: str) -> int:
    """Dérive une graine stable de 64 bits à partir de la graine maîtresse et d'un nom."""
    digest = hashlib.sha256(f"{master_seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class RngRegistry:
    """Distribue des générateurs `random.Random` indépendants et reproductibles."""

    def __init__(self, master_seed: int) -> None:
        self.master_seed = master_seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        """Renvoie le flux `name`, créé à la première demande puis réutilisé.

        Réutiliser le même objet est essentiel : recréer le générateur à chaque
        appel renverrait toujours les mêmes premiers nombres.
        """
        rng = self._streams.get(name)
        if rng is None:
            rng = random.Random(derive_seed(self.master_seed, name))
            self._streams[name] = rng
        return rng
