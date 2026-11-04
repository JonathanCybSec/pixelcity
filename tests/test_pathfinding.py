"""Tests de la grille et d'A*."""

from __future__ import annotations

import heapq
import itertools
import random

from pixelcity.sim.types import TilePos
from pixelcity.world.grid import Grid
from pixelcity.world.pathfinding import Pathfinder, astar, path_cost

LEGEND = {".": 1, "~": 3, "#": 0}


def grid(*rows: str) -> Grid:
    return Grid.from_rows(list(rows), LEGEND)


def test_ligne_droite() -> None:
    g = grid(".....")
    assert astar(g, (0, 0), (4, 0)) == ((0, 0), (1, 0), (2, 0), (3, 0), (4, 0))


def test_depart_egal_arrivee() -> None:
    assert astar(grid("..."), (1, 0), (1, 0)) == ((1, 0),)


def test_contourne_un_mur() -> None:
    g = grid(
        ".#.",
        ".#.",
        "...",
    )
    path = astar(g, (0, 0), (2, 0))
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (2, 0)
    assert all(g.is_walkable(pos) for pos in path)
    assert len(path) == 7  # descend, traverse en bas, remonte


def test_inatteignable_renvoie_none() -> None:
    g = grid(
        ".#.",
        "##.",
        "...",
    )
    assert astar(g, (0, 0), (2, 2)) is None


def test_destination_bloquee_renvoie_none() -> None:
    assert astar(grid("..#"), (0, 0), (2, 0)) is None


def test_prefere_les_tuiles_peu_couteuses() -> None:
    # Tout droit : 4 cases de pelouse (3 chacune) + l'arrivée (1) = 13.
    # Le détour par le trottoir du haut : 7 pas de coût 1 = 7, moins cher.
    g = grid(
        "......",
        ".~~~~.",
    )
    path = astar(g, (0, 1), (5, 1))
    assert path is not None
    assert path_cost(g, path) == 7
    assert all(pos[1] == 0 for pos in path[1:-1])


def test_pas_de_diagonale() -> None:
    path = astar(grid("...", "...", "..."), (0, 0), (2, 2))
    assert path is not None
    for (x1, y1), (x2, y2) in itertools.pairwise(path):
        assert abs(x1 - x2) + abs(y1 - y2) == 1


def _dijkstra_cost(g: Grid, start: TilePos, goal: TilePos) -> int | None:
    """Référence « bête et sûre » pour vérifier l'optimalité d'A*."""
    best = {start: 0}
    heap = [(0, start)]
    while heap:
        cost, pos = heapq.heappop(heap)
        if pos == goal:
            return cost
        if cost > best[pos]:
            continue
        for n in g.neighbors(pos):
            new_cost = cost + g.cost(n)
            if new_cost < best.get(n, 1 << 60):
                best[n] = new_cost
                heapq.heappush(heap, (new_cost, n))
    return None


def test_astar_optimal_sur_des_grilles_aleatoires() -> None:
    """A* doit trouver le même coût que Dijkstra sur 60 grilles aléatoires.

    C'est un test « par propriété » : au lieu de vérifier quelques cas écrits à
    la main, on vérifie une propriété générale sur beaucoup de cas générés.
    La graine fixe rend le test reproductible.
    """
    rng = random.Random(7)
    for _ in range(60):
        width, height = rng.randint(5, 14), rng.randint(5, 14)
        costs = [rng.choice([1, 1, 1, 3, 8, 0]) for _ in range(width * height)]
        g = Grid(width, height, costs)
        cells = [(x, y) for y in range(height) for x in range(width) if g.is_walkable((x, y))]
        if len(cells) < 2:
            continue
        start, goal = rng.sample(cells, 2)
        path = astar(g, start, goal)
        expected = _dijkstra_cost(g, start, goal)
        if expected is None:
            assert path is None
        else:
            assert path is not None
            assert path_cost(g, path) == expected


def test_le_cache_renvoie_le_meme_chemin_immuable() -> None:
    finder = Pathfinder(grid("....", "...."))
    first = finder.find_path((0, 0), (3, 1))
    second = finder.find_path((0, 0), (3, 1))
    assert first is second  # même objet : lecture du cache
    assert isinstance(first, tuple)  # immuable : un agent ne peut pas corrompre le cache
    assert (finder.hits, finder.misses) == (1, 1)


def test_le_cache_evince_les_plus_anciens() -> None:
    finder = Pathfinder(grid("....."), cache_size=2)
    finder.find_path((0, 0), (1, 0))
    finder.find_path((0, 0), (2, 0))
    finder.find_path((0, 0), (3, 0))  # évince (0,0)->(1,0)
    finder.find_path((0, 0), (1, 0))
    assert finder.misses == 4
