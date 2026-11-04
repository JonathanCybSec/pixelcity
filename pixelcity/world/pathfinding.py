"""Recherche de chemin A* sur la grille, avec cache des trajets.

Un peu d'histoire : A* a été publié en 1968 par Peter Hart, Nils Nilsson et
Bertram Raphael, au Stanford Research Institute, pour Shakey, le premier robot
mobile capable de planifier ses propres déplacements. Nos habitants marchent
avec l'algorithme de ce robot.

Rappel du principe : A* explore en priorité les cases qui minimisent
    f(n) = g(n) + h(n)
avec g(n) le coût réel depuis le départ, et h(n) une ESTIMATION du coût
restant. Tant que h ne surestime jamais le vrai coût (heuristique
« admissible »), le chemin trouvé est optimal. Ici h = distance de Manhattan
× coût minimal d'une tuile (1) : on ne peut pas faire moins.
"""

from __future__ import annotations

import heapq
from collections import OrderedDict

from pixelcity.sim.types import TilePos
from pixelcity.world.grid import Grid

# Un chemin est un TUPLE (immuable), pas une liste. Les chemins sont mis en
# cache et partagés entre agents : si un agent faisait `path.pop(0)` sur une
# liste partagée, il corromprait le cache pour tous les autres. Les agents
# gardent donc un index de progression au lieu de modifier le chemin.
type Path = tuple[TilePos, ...]

_MIN_TILE_COST = 1


def manhattan(a: TilePos, b: TilePos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(grid: Grid, start: TilePos, goal: TilePos) -> Path | None:
    """Plus court chemin (en coût) de `start` à `goal`, ou None s'il n'existe pas.

    Le chemin inclut le départ et l'arrivée. Coût d'un pas = coût de la tuile
    sur laquelle on entre.
    """
    if not grid.is_walkable(start) or not grid.is_walkable(goal):
        return None
    if start == goal:
        return (start,)

    # Entrées du tas : (f, h, compteur, case).
    # - h en 2e position : à f égal, on préfère la case la plus proche du but
    #   (moins de cases explorées, chemins plus droits) ;
    # - le compteur garantit un ordre FIFO stable : à (f, h) égaux, heapq
    #   comparerait sinon l'élément suivant, la case elle-même. Avec des tuples
    #   (x, y) ça « marche » mais biaise les chemins vers les petits x ; avec
    #   des objets non comparables, ce serait une TypeError.
    counter = 0
    h_start = manhattan(start, goal) * _MIN_TILE_COST
    open_heap: list[tuple[int, int, int, TilePos]] = [(h_start, h_start, counter, start)]
    g_score: dict[TilePos, int] = {start: 0}
    came_from: dict[TilePos, TilePos] = {}
    closed: set[TilePos] = set()

    while open_heap:
        _f, _h, _count, current = heapq.heappop(open_heap)
        if current == goal:
            return _reconstruct(came_from, current)
        if current in closed:
            # « Suppression paresseuse » : une case peut être dans le tas
            # plusieurs fois avec des coûts différents ; on ignore les doublons
            # périmés au lieu de les chercher pour les retirer (coûteux).
            continue
        closed.add(current)
        current_g = g_score[current]
        for neighbor in grid.neighbors(current):
            if neighbor in closed:
                continue
            tentative_g = current_g + grid.cost(neighbor)
            if tentative_g < g_score.get(neighbor, 1 << 60):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                h = manhattan(neighbor, goal) * _MIN_TILE_COST
                counter += 1
                heapq.heappush(open_heap, (tentative_g + h, h, counter, neighbor))
    return None


def _reconstruct(came_from: dict[TilePos, TilePos], end: TilePos) -> Path:
    path = [end]
    while path[-1] in came_from:
        path.append(came_from[path[-1]])
    path.reverse()
    return tuple(path)


def path_cost(grid: Grid, path: Path) -> int:
    """Coût total d'un chemin (la case de départ ne compte pas)."""
    return sum(grid.cost(pos) for pos in path[1:])


class Pathfinder:
    """A* + cache LRU des trajets.

    La plupart des trajets vont d'une porte à une autre : les mêmes paires
    reviennent sans cesse. Le cache transforme un calcul de quelques
    millisecondes en une simple lecture de dictionnaire.
    """

    def __init__(self, grid: Grid, cache_size: int = 8192) -> None:
        self.grid = grid
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[TilePos, TilePos], Path | None] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def find_path(self, start: TilePos, goal: TilePos) -> Path | None:
        key = (start, goal)
        if key in self._cache:
            self._cache.move_to_end(key)  # marque l'entrée comme « récemment utilisée »
            self.hits += 1
            return self._cache[key]
        self.misses += 1
        path = astar(self.grid, start, goal)
        self._cache[key] = path
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)  # évince la plus anciennement utilisée
        return path

    def clear(self) -> None:
        """À appeler si la carte change (travaux, route coupée...)."""
        self._cache.clear()
