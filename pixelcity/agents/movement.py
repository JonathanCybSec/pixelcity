"""Se déplacer : calculer un chemin, puis l'avancer d'un pas par tick.

La vitesse est fixe en tuiles PAR TICK : comme le tick a une durée fixe,
l'habitant parcourt exactement la même distance à x1 qu'à x30. Le rendu, lui,
interpole entre la position du tick précédent et celle du tick courant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pixelcity.sim.types import Facing, Pose, TilePos
from pixelcity.world.pathfinding import Pathfinder

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent


def walk_to(agent: Agent, goal: TilePos, pathfinder: Pathfinder) -> bool:
    """Prépare le trajet jusqu'à `goal`. False s'il n'existe aucun chemin."""
    if agent.tile == goal:
        agent.path, agent.path_index, agent.progress = (goal,), 0, 0.0
        return True
    path = pathfinder.find_path(agent.tile, goal)
    if path is None:
        return False
    agent.path, agent.path_index, agent.progress = path, 0, 0.0
    agent.pose = Pose.WALK
    agent.spot = None
    return True


def arrived(agent: Agent) -> bool:
    return not agent.path or agent.path_index >= len(agent.path) - 1


def step_along(agent: Agent, tiles: float) -> bool:
    """Avance de `tiles` tuiles le long du chemin. True si l'on est au bout."""
    path = agent.path
    if not path:
        return True
    last = len(path) - 1
    index, progress = agent.path_index, agent.progress
    remaining = tiles
    while remaining > 0 and index < last:
        step = 1.0 - progress
        if remaining >= step:
            index += 1
            progress = 0.0
            remaining -= step
        else:
            progress += remaining
            remaining = 0.0
    agent.path_index, agent.progress = index, progress
    cx, cy = path[index]
    agent.tile = (cx, cy)
    if index < last:
        nx, ny = path[index + 1]
        agent.pos = (cx + (nx - cx) * progress, cy + (ny - cy) * progress)
        agent.facing = Facing.from_delta(nx - cx, ny - cy)
        agent.pose = Pose.WALK
        return False
    agent.pos = (float(cx), float(cy))
    if agent.pose is Pose.WALK:
        agent.pose = Pose.STAND
    return True


def place_at(agent: Agent, tile: TilePos) -> None:
    """Pose l'habitant sur une case, sans trajet (création, chargement)."""
    agent.tile = tile
    agent.pos = agent.prev_pos = (float(tile[0]), float(tile[1]))
    agent.path, agent.path_index, agent.progress = (), 0, 0.0
