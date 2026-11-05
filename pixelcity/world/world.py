"""Assemblage du monde : carte Tiled + catalogue de meubles + règles des YAML.

Couches attendues dans la carte (générée par tools/make_city.py) :
- `ground`  : le sol (herbe, trottoir, route, parquet...) ;
- `walls`   : les murs, dessinés en « auto-tuilage » par le rendu ;
- `places`  : un rectangle par lieu (propriété `place_id`) ;
- `rooms`   : les pièces (propriétés `room` et `place_id`), pour décrire où
  se trouve quelqu'un (« dans la cuisine ») ;
- `furniture` : un rectangle par meuble (propriétés `type`, `orientation`).

Les tuiles du tileset portent leurs propriétés : `walkable`, `cost`, `kind`,
et `wall_style` pour les murs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from pixelcity.config.schemas import CityConfig, ObjectsConfig
from pixelcity.sim.types import TilePos
from pixelcity.world.catalog import Catalog, CatalogError
from pixelcity.world.furniture import Container, Furniture, apply_grants, build_spots
from pixelcity.world.grid import BLOCKED, Grid
from pixelcity.world.pathfinding import Pathfinder
from pixelcity.world.place import OpeningHours, Place, TileRect
from pixelcity.world.tmx import TmxMap, load_tmx

GROUND_LAYER = "ground"
WALLS_LAYER = "walls"
PLACES_GROUP = "places"
ROOMS_GROUP = "rooms"
FURNITURE_GROUP = "furniture"


class MapError(Exception):
    """La carte et la configuration ne concordent pas."""


@dataclass(frozen=True, slots=True)
class Room:
    kind: str
    label: str
    area: TileRect
    place_id: str | None


@dataclass(slots=True)
class World:
    width: int
    height: int
    tile_width: int
    tile_height: int
    grid: Grid
    places: dict[str, Place]
    furniture: dict[str, Furniture]
    rooms: list[Room]
    walls: dict[TilePos, str]  # tuile de mur → style (couleur)
    pathfinder: Pathfinder
    map_path: Path
    tmx: TmxMap
    catalog: Catalog
    _place_index: dict[TilePos, str] = field(default_factory=dict)

    def place(self, place_id: str) -> Place:
        return self.places[place_id]

    def place_at(self, tile: TilePos) -> Place | None:
        place_id = self._place_index.get(tile)
        return self.places[place_id] if place_id else None

    def room_at(self, tile: TilePos) -> Room | None:
        for room in self.rooms:
            if room.area.contains(tile):
                return room
        return None

    def path_length_to(self, start: TilePos, place: Place) -> int | None:
        """Nombre de pas pour rejoindre l'entrée la plus proche du lieu (None si inatteignable)."""
        path = self.pathfinder.find_path(start, place.nearest_entrance(start))
        return None if path is None else len(path) - 1


def load_world(map_path: Path, city: CityConfig, objects: ObjectsConfig, catalog: Catalog) -> World:
    tmx = load_tmx(map_path)
    for layer in (GROUND_LAYER, WALLS_LAYER):
        if layer not in tmx.layers:
            raise MapError(f"{map_path.name} : couche de tuiles {layer!r} introuvable")
    if PLACES_GROUP not in tmx.object_groups:
        raise MapError(f"{map_path.name} : calque d'objets {PLACES_GROUP!r} introuvable")

    grid, walls = _build_grid(tmx)
    places = _build_places(tmx, city, map_path.name)
    furniture = _build_furniture(tmx, grid, places, objects, catalog, map_path.name)
    for place in places.values():
        # Les entrées se calculent APRÈS la pose des meubles : sinon toutes
        # les cases du bord du parc compteraient, haies comprises.
        place.entrances = _find_entrances(grid, place.area)
        if not place.entrances:
            raise MapError(
                f"{map_path.name} : le lieu {place.id!r} n'a aucune entrée "
                "(une case marchable sur son bord, ouverte vers l'extérieur)"
            )
        place.doorsteps = tuple(_doorstep(grid, place.area, e) for e in place.entrances)
        place.walk_tiles = tuple(
            tile
            for tile in place.area.tiles()
            if grid.is_walkable(tile) and not place.area.on_border(tile)
        )
        place.index_spots()
    rooms = _build_rooms(tmx)
    _check_connectivity(grid, places, map_path.name)
    _check_spots(grid, places, map_path.name)

    world = World(
        width=tmx.width,
        height=tmx.height,
        tile_width=tmx.tile_width,
        tile_height=tmx.tile_height,
        grid=grid,
        places=places,
        furniture=furniture,
        rooms=rooms,
        walls=walls,
        pathfinder=Pathfinder(grid),
        map_path=map_path,
        tmx=tmx,
        catalog=catalog,
    )
    for place in places.values():
        for tile in place.area.tiles():
            world._place_index.setdefault(tile, place.id)
    return world


# --------------------------------------------------------------------------- #
# Grille : sol + murs
# --------------------------------------------------------------------------- #
def _tile_cost(tmx: TmxMap, gid: int, *, default: int) -> int:
    properties = tmx.tile_properties.get(gid, {})
    if properties.get("walkable") is False:
        return BLOCKED
    cost = properties.get("cost")
    return int(cost) if isinstance(cost, int | float) else default


def _build_grid(tmx: TmxMap) -> tuple[Grid, dict[TilePos, str]]:
    costs: list[int] = []
    walls: dict[TilePos, str] = {}
    for y in range(tmx.height):
        for x in range(tmx.width):
            wall_gid = tmx.gid_at(WALLS_LAYER, x, y)
            if wall_gid:
                style = tmx.tile_properties.get(wall_gid, {}).get("wall_style", "default")
                walls[(x, y)] = str(style)
                costs.append(BLOCKED)
                continue
            ground = tmx.gid_at(GROUND_LAYER, x, y)
            costs.append(_tile_cost(tmx, ground, default=1) if ground else BLOCKED)
    return Grid(tmx.width, tmx.height, costs), walls


# --------------------------------------------------------------------------- #
# Lieux
# --------------------------------------------------------------------------- #
def _rect(tmx: TmxMap, x: float, y: float, width: float, height: float) -> TileRect:
    return TileRect(
        x=round(x / tmx.tile_width),
        y=round(y / tmx.tile_height),
        width=max(1, round(width / tmx.tile_width)),
        height=max(1, round(height / tmx.tile_height)),
    )


def _build_places(tmx: TmxMap, city: CityConfig, map_name: str) -> dict[str, Place]:
    areas: dict[str, TileRect] = {}
    for obj in tmx.object_groups[PLACES_GROUP]:
        place_id = obj.properties.get("place_id")
        if not isinstance(place_id, str) or not place_id:
            raise MapError(f"{map_name} : l'objet #{obj.id} n'a pas de propriété `place_id`")
        if place_id in areas:
            raise MapError(f"{map_name} : `place_id` {place_id!r} utilisé deux fois")
        areas[place_id] = _rect(tmx, obj.x, obj.y, obj.width, obj.height)

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
    for model in city.places:  # l'ordre de city.yaml : un ordre d'itération stable
        area = areas[model.id]
        places[model.id] = Place(
            id=model.id,
            name=model.name,
            kind=model.kind,
            capacity=model.capacity,
            hours=OpeningHours(model.hours, frozenset(day.number for day in model.days)),
            activities=frozenset(model.activities),
            staff_activities=frozenset(model.staff_activities),
            area=area,
            entrances=(),
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


def _doorstep(grid: Grid, area: TileRect, entrance: TilePos) -> TilePos:
    """La case juste devant la porte, côté extérieur (là où l'on attend l'ouverture)."""
    for neighbor in grid.neighbors(entrance):
        if not area.contains(neighbor):
            return neighbor
    return entrance


def _build_rooms(tmx: TmxMap) -> list[Room]:
    rooms: list[Room] = []
    for obj in tmx.object_groups.get(ROOMS_GROUP, ()):
        kind = str(obj.properties.get("room", "room"))
        place_id = obj.properties.get("place_id")
        rooms.append(
            Room(
                kind=kind,
                label=obj.name or kind,
                area=_rect(tmx, obj.x, obj.y, obj.width, obj.height),
                place_id=str(place_id) if place_id else None,
            )
        )
    return rooms


# --------------------------------------------------------------------------- #
# Meubles
# --------------------------------------------------------------------------- #
def _build_furniture(
    tmx: TmxMap,
    grid: Grid,
    places: dict[str, Place],
    objects: ObjectsConfig,
    catalog: Catalog,
    map_name: str,
) -> dict[str, Furniture]:
    furniture: dict[str, Furniture] = {}
    occupied: dict[TilePos, str] = {}
    errors: list[str] = []
    for obj in tmx.object_groups.get(FURNITURE_GROUP, ()):
        # Propriété « furniture » et non « type » : `type` est un nom réservé
        # des objets Tiled, que pytmx refuse comme propriété personnalisée.
        type_id = str(obj.properties.get("furniture", ""))
        try:
            spec = catalog.get(type_id)
            orientation = str(obj.properties.get("orientation") or spec.default_orientation)
            spec.variant(orientation)
        except CatalogError as exc:
            errors.append(f"meuble #{obj.id} : {exc}")
            continue
        col, row = round(obj.x / tmx.tile_width), round(obj.y / tmx.tile_height)
        place_id = obj.properties.get("place_id")
        if not isinstance(place_id, str) or not place_id:
            place_id = next(
                (p.id for p in places.values() if p.area.contains((col, row + 1))), None
            )
        behaviour = objects.objects.get(type_id)
        item = Furniture(
            uid=f"f{obj.id}",
            spec=spec,
            orientation=orientation,
            col=col,
            row=row,
            place_id=place_id,
            behaviour=behaviour,
            container=(
                Container.from_model(behaviour.container)
                if behaviour and behaviour.container
                else None
            ),
        )
        if not item.is_flat:
            for tile in item.base_tiles():
                if not grid.in_bounds(tile) or not grid.is_walkable(tile):
                    errors.append(f"{type_id} #{obj.id} posé sur une case non libre {tile}")
                elif tile in occupied:
                    errors.append(f"{type_id} #{obj.id} chevauche {occupied[tile]} en {tile}")
                else:
                    occupied[tile] = f"{type_id} #{obj.id}"
        build_spots(item)
        furniture[item.uid] = item

    if errors:
        raise MapError(f"{map_name} : meubles mal placés\n" + "\n".join(f"  → {e}" for e in errors))

    for item in furniture.values():  # le sol est occupé : on bloque, sauf les sièges
        if item.is_flat:
            continue
        for tile in item.base_tiles():
            grid.block(tile)
        for spot in item.spots:
            if spot.is_seat:
                grid.seats.add(spot.tile)
    apply_grants(list(furniture.values()))
    for item in furniture.values():
        if item.place_id in places:
            places[item.place_id].furniture.append(item)
    return furniture


# --------------------------------------------------------------------------- #
# Vérifications : on préfère une erreur claire au chargement qu'un habitant
# bloqué à 14 h 37.
# --------------------------------------------------------------------------- #
def _reachable_from(grid: Grid, origin: TilePos) -> set[TilePos]:
    seen = {origin}
    queue = deque([origin])
    while queue:
        for neighbor in grid.neighbors(queue.popleft()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _check_connectivity(grid: Grid, places: dict[str, Place], map_name: str) -> None:
    """Toutes les entrées de tous les lieux doivent être reliées entre elles."""
    all_entrances = [(place.id, e) for place in places.values() for e in place.entrances]
    seen = _reachable_from(grid, all_entrances[0][1])
    unreachable = sorted({place_id for place_id, e in all_entrances if e not in seen})
    if unreachable:
        raise MapError(
            f"{map_name} : lieux inaccessibles depuis le reste de la ville : {unreachable}"
        )


def _check_spots(grid: Grid, places: dict[str, Place], map_name: str) -> None:
    """Chaque place d'utilisation doit être atteignable depuis l'entrée de son lieu."""
    problems: list[str] = []
    for place in places.values():
        reachable = _reachable_from(grid, place.entrances[0])
        for furniture in place.furniture:
            for spot in furniture.spots:
                x, y = spot.tile
                if spot.is_seat:
                    ok = any(
                        (x + dx, y + dy) in reachable
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    )
                else:
                    ok = spot.tile in reachable
                if not ok:
                    problems.append(
                        f"{place.id} : {furniture.type_id} ({spot.kind}) en {spot.tile}"
                    )
    if problems:
        raise MapError(
            f"{map_name} : places d'utilisation inaccessibles\n"
            + "\n".join(f"  → {p}" for p in problems)
        )
