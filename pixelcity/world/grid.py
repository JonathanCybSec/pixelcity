"""Grille de marche : où peut-on marcher, et à quel coût ?

Chaque tuile a un coût de traversée :
- 0  : infranchissable (mur, arbre, eau) ;
- 1  : idéal (trottoir, passage piéton, allée) ;
- 3  : possible mais évité (pelouse) ;
- 8  : à éviter fortement (chaussée hors passage piéton).

A* minimise la SOMME des coûts : les habitants prennent naturellement les
trottoirs et les passages piétons, sans qu'on code de règle spéciale.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from pixelcity.sim.types import TilePos

BLOCKED = 0

# Ordre FIXE des voisins (est, ouest, sud, nord) : à coût égal, A* départage
# toujours de la même façon, condition du déterminisme.
_NEIGHBOR_OFFSETS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass(slots=True)
class Grid:
    width: int
    height: int
    # Tableau « aplati » (ligne après ligne) plutôt qu'une liste de listes :
    # un seul accès mémoire par lecture, et index = y * width + x.
    costs: list[int]

    def __post_init__(self) -> None:
        if len(self.costs) != self.width * self.height:
            raise ValueError("taille du tableau de coûts incohérente avec la grille")

    @classmethod
    def from_rows(cls, rows: list[str], legend: dict[str, int]) -> Grid:
        """Construit une grille depuis du texte, très pratique dans les tests.

        >>> Grid.from_rows(["..#", "..."], {".": 1, "#": 0}).is_walkable((2, 0))
        False
        """
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("toutes les lignes doivent avoir la même longueur")
        return cls(width, len(rows), [legend[char] for row in rows for char in row])

    def in_bounds(self, pos: TilePos) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def cost(self, pos: TilePos) -> int:
        x, y = pos
        return self.costs[y * self.width + x]

    def is_walkable(self, pos: TilePos) -> bool:
        return self.in_bounds(pos) and self.cost(pos) != BLOCKED

    def neighbors(self, pos: TilePos) -> Iterator[TilePos]:
        """Voisins franchissables en 4 directions (pas de diagonales).

        4 directions plutôt que 8 : les sprites pixel art ont 4 orientations,
        et on évite les « coupes de coin » à travers les angles de murs.
        """
        x, y = pos
        width, height, costs = self.width, self.height, self.costs
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and costs[ny * width + nx] != BLOCKED:
                yield (nx, ny)
