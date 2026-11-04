"""Assemblage du monde : carte Tiled + règles de city.yaml → grille et lieux."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from pixelcity.config.schemas import CityConfig, PlaceModel, Settings
from pixelcity.sim.types import ActivityType, NeedKind, TilePos
from pixelcity.world.grid import BLOCKED, Grid
from pixelcity.world.pathfinding import Pathfinder
from pixelcity.world.place import OpeningHours, Place, TileRect
from pixelcity.world.tmx import TmxMap, load_tmx

GROUND_LAYER = "ground"
STRUCTURES_LAYER = "structures"
PLACES_GROUP = "places"


class MapError(Exception):
    """La carte et la configuration ne concordent pas."""


@dataclass(slots=True)
class World:
    width: int
    height: int
    tile_width: int
    tile_height: int
    grid: Grid
    places: dict[str, Place]
    pathfinder: Pathfinder
    map_path: Path

    def place(self, place_id: str) -> Place:
        return self.places[place_id]

    def path_length_to(self, start: TilePos, place: Place) -> int | None:
        """Nombre de pas pour rejoindre l'entrée la plus proche du lieu (None si inatteignable)."""
        path = self.pathfinder.find_path(start, place.nearest_entrance(start))
        return None if path is None else len(path) - 1


def load_world(map_path: Path, city: CityConfig, settings: Settings) -> World:
    tmx = load_tmx(map_path)
    for layer in (GROUND_LAYER, STRUCTURES_LAYER):
        if layer not in tmx.layers:
            raise MapError(f"{map_path.name} : couche de tuiles {layer!r} introuvable")
    if PLACES_GROUP not in tmx.object_groups:
        raise MapError(f"{map_path.name} : calque d'objets {PLACES_GROUP!r} introuvable")

    grid = _build_grid(tmx)
    places = _build_places(tmx, grid, city, settings, map_path.name)
    _check_connectivity(grid, places, map_path.name)
    return World(
        width=tmx.width,
        height=tmx.height,
        tile_width=tmx.tile_width,
        tile_height=tmx.tile_height,
        grid=grid,
        places=places,
        pathfinder=Pathfinder(grid),
        map_path=map_path,
    )


def _tile_cost(tmx: TmxMap, gid: int, *, default: int) -> int:
    properties = tmx.tile_properties.get(gid, {})
    if properties.get("walkable") is False:
        return BLOCKED
    cost = properties.get("cost")
    return int(cost) if isinstance(cost, int | float) else default


def _build_grid(tmx: TmxMap) -> Grid:
    """Coût de chaque case = celui de la structure s'il y en a une, sinon celui du sol.

    Par défaut (tuile sans propriétés) : un sol est marchable (coût 1), une
    structure est un obstacle. Le générateur de carte renseigne explicitement
    `walkable` et `cost` sur chaque tuile du tileset.
    """
    costs: list[int] = []
    for y in range(tmx.height):
        for x in range(tmx.width):
            structure = tmx.gid_at(STRUCTURES_LAYER, x, y)
            if structure:
                costs.append(_tile_cost(tmx, structure, default=BLOCKED))
            else:
                ground = tmx.gid_at(GROUND_LAYER, x, y)
                costs.append(_tile_cost(tmx, ground, default=1) if ground else BLOCKED)
    return Grid(tmx.width, tmx.height, costs)


def _build_places(
    tmx: TmxMap, grid: Grid, city: CityConfig, settings: Settings, map_name: str
) -> dict[str, Place]:
    areas: dict[str, TileRect] = {}
    for obj in tmx.object_groups[PLACES_GROUP]:
        place_id = obj.properties.get("place_id")
        if not isinstance(place_id, str) or not place_id:
            raise MapError(f"{map_name} : l'objet #{obj.id} n'a pas de propriété `place_id`")
        if place_id in areas:
            raise MapError(f"{map_name} : `place_id` {place_id!r} utilisé deux fois")
        areas[place_id] = TileRect(
            x=round(obj.x / tmx.tile_width),
            y=round(obj.y / tmx.tile_height),
            width=max(1, round(obj.width / tmx.tile_width)),
            height=max(1, round(obj.height / tmx.tile_height)),
        )

    configured = {place.id for place in city.places}
    missing_on_map = sorted(configured - set(areas))
    missing_in_config = sorted(set(areas) - configured)
    if missing_on_map or missing_in_config:
        details = []
        if missing_on_map:
            details.append(f"absents de la carte : {', '.join(missing_on_map)}")
        if missing_in_config:
            details.append(f"absents de city.yaml : {', '.join(missing_in_config)}")
        raise MapError(f"{map_name} et city.yaml ne concordent pas ({' ; '.join(details)})")

    places: dict[str, Place] = {}
    # On suit l'ordre de city.yaml : un ordre d'itération stable et maîtrisé.
    for model in city.places:
        area = areas[model.id]
        entrances = _find_entrances(grid, area)
        if not entrances:
            raise MapError(
                f"{map_name} : le lieu {model.id!r} n'a aucune entrée "
                "(une case marchable sur son bord, ouverte vers l'extérieur)"
            )
        spots: tuple[TilePos, ...] = ()
        if model.kind.is_outdoor:
            spots = tuple(
                tile for tile in area.tiles() if grid.is_walkable(tile) and not area.on_border(tile)
            )
            if not spots:
                raise MapError(f"{map_name} : le lieu extérieur {model.id!r} n'a aucune case libre")
        places[model.id] = Place(
            id=model.id,
            name=model.name,
            kind=model.kind,
            capacity=model.capacity,
            hours=OpeningHours(model.hours, frozenset(day.number for day in model.days)),
            activities=frozenset(model.activities),
            staff_activities=frozenset(model.staff_activities),
            effects=_merge_effects(model, settings),
            area=area,
            entrances=entrances,
            spots=spots,
        )
    return places


def _find_entrances(grid: Grid, area: TileRect) -> tuple[TilePos, ...]:
    """Une entrée = case marchable du bord, voisine d'une case marchable extérieure."""
    entrances: list[TilePos] = []
    for tile in area.tiles():
        if not area.on_border(tile) or not grid.is_walkable(tile):
            continue
        if any(not area.contains(n) for n in grid.neighbors(tile)):
            entrances.append(tile)
    return tuple(entrances)


def _merge_effects(
    model: PlaceModel, settings: Settings
) -> dict[ActivityType, dict[NeedKind, float]]:
    merged: dict[ActivityType, dict[NeedKind, float]] = {}
    for activity in (*model.activities, *model.staff_activities):
        effects = dict(settings.activity_effects[activity])
        effects.update(model.effects.get(activity, {}))
        merged[activity] = effects
    return merged


def _check_connectivity(grid: Grid, places: dict[str, Place], map_name: str) -> None:
    """Toutes les entrées doivent être reliées entre elles.

    Un parcours en largeur depuis une entrée suffit : si une autre entrée n'est
    pas atteinte, un habitant pourrait rester bloqué. On le détecte au
    chargement plutôt qu'en pleine simulation.
    """
    all_entrances = [(place.id, e) for place in places.values() for e in place.entrances]
    origin = all_entrances[0][1]
    seen = {origin}
    queue = deque([origin])
    while queue:
        for neighbor in grid.neighbors(queue.popleft()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    unreachable = sorted({place_id for place_id, e in all_entrances if e not in seen})
    if unreachable:
        raise MapError(
            f"{map_name} : lieux inaccessibles depuis le reste de la ville : {unreachable}"
        )
