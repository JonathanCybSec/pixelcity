"""Meubles posés dans le monde : emprise, places d'utilisation, stocks, réservations.

Vocabulaire :
- emprise (footprint) : les tuiles couvertes par le meuble ;
- rangées d'arrière-plan : le haut du sprite, qui « dépasse » sur le mur ou
  derrière l'objet. On peut y marcher (le vendeur se tient derrière sa vitrine) ;
- base : les rangées qui touchent vraiment le sol. On ne les traverse pas ;
- place (Spot) : une tuile précise où un habitant se tient pour utiliser le
  meuble, avec une orientation et une posture. Une place se RÉSERVE : deux
  habitants n'utilisent jamais la même chaise en même temps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pixelcity.config.schemas import ContainerModel, ObjectModel, UseModel
from pixelcity.sim.types import Facing, Pose, TilePos
from pixelcity.world.catalog import FurnitureSpec

INFINITE = -1

# Orientation d'un siège selon la variante du meuble (convention de pixel-agents).
_SEAT_FACING = {
    "front": Facing.DOWN,
    "back": Facing.UP,
    "side": Facing.RIGHT,
    "left": Facing.LEFT,
}


@dataclass(slots=True)
class Container:
    """Stock d'un meuble : le frigo, la vitrine du boulanger..."""

    items: dict[str, int]
    capacity: int

    @classmethod
    def from_model(cls, model: ContainerModel) -> Container:
        return cls(dict(model.items), model.capacity)

    def count(self, item: str) -> int:
        """Quantité en stock ; INFINITE (-1) si illimité, 0 si absent."""
        return self.items.get(item, 0)

    def has(self, item: str, quantity: int = 1) -> bool:
        stock = self.count(item)
        return stock == INFINITE or stock >= quantity

    def take(self, item: str, quantity: int = 1) -> bool:
        if not self.has(item, quantity):
            return False
        if self.items[item] != INFINITE:
            self.items[item] -= quantity
        return True

    def put(self, item: str, quantity: int = 1) -> int:
        """Range jusqu'à `quantity` articles ; renvoie combien ont trouvé de la place."""
        stock = self.items.get(item, 0)
        if stock == INFINITE:
            return quantity
        stored = max(0, min(quantity, self.capacity - stock))
        self.items[item] = stock + stored
        return stored


@dataclass(slots=True, eq=False)
class Spot:
    furniture: Furniture
    index: int
    tile: TilePos
    facing: Facing
    pose: Pose
    verbs: frozenset[str]
    role: str
    kind: str
    reserved_by: str | None = None
    # Verbe accordé → meuble qui l'accorde (la télé pour `watch_tv` sur le canapé) :
    # c'est CE meuble qu'on allume, pas le canapé.
    granted_by: dict[str, Furniture] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.furniture.uid}#{self.index}"

    @property
    def is_seat(self) -> bool:
        return self.kind in ("seat", "head")

    def is_free_for(self, agent_id: str) -> bool:
        return self.reserved_by is None or self.reserved_by == agent_id


@dataclass(slots=True, eq=False)
class Furniture:
    uid: str
    spec: FurnitureSpec
    orientation: str
    col: int
    row: int
    place_id: str | None
    behaviour: ObjectModel | None
    container: Container | None
    spots: list[Spot] = field(default_factory=list)
    # Habitants qui l'utilisent en ce moment (le dormeur d'un lit, le cuisinier...).
    users: dict[str, None] = field(default_factory=dict)
    # Nombre d'étapes en cours qui demandent l'objet allumé (cuisinière, four).
    switched_on: int = 0

    @property
    def type_id(self) -> str:
        return self.spec.id

    @property
    def label(self) -> str:
        return self.behaviour.label if self.behaviour else self.spec.name.lower()

    @property
    def footprint(self) -> tuple[int, int]:
        return self.spec.variant(self.orientation).footprint

    @property
    def sells(self) -> tuple[str, ...]:
        return self.behaviour.sells if self.behaviour else ()

    @property
    def is_on(self) -> bool:
        return self.switched_on > 0

    @property
    def is_flat(self) -> bool:
        """Posé au mur ou sur une table : n'occupe pas le sol."""
        return self.spec.on_walls or self.spec.on_surfaces

    def tiles(self) -> list[TilePos]:
        width, height = self.footprint
        return [(self.col + dx, self.row + dy) for dy in range(height) for dx in range(width)]

    def base_rows(self) -> range:
        _width, height = self.footprint
        first = min(self.row + self.spec.background_tiles, self.row + height - 1)
        return range(first, self.row + height)

    def base_tiles(self) -> list[TilePos]:
        width, _height = self.footprint
        return [(self.col + dx, y) for y in self.base_rows() for dx in range(width)]

    def spots_for(self, verb: str) -> list[Spot]:
        return [spot for spot in self.spots if verb in spot.verbs]


def build_spots(furniture: Furniture) -> None:
    """Crée les places d'utilisation décrites par objects.yaml."""
    if furniture.behaviour is None:
        return
    width, height = furniture.footprint
    col, row = furniture.col, furniture.row
    center_x = col + width // 2
    front_y = row + height
    base = furniture.base_tiles()
    for use in furniture.behaviour.uses:
        pose = Pose(use.pose)
        if use.at == "front":
            tiles = [(col + dx, front_y) for dx in range(width)]
            default_facing = Facing.UP
        elif use.at == "front_center":
            tiles = [(center_x, front_y)]
            default_facing = Facing.UP
        elif use.at == "behind_center":
            tiles = [(center_x, furniture.base_rows().start - 1)]
            default_facing = Facing.DOWN
        elif use.at == "head":
            tiles = [base[0]]
            default_facing = _SEAT_FACING.get(furniture.orientation, Facing.DOWN)
        else:  # seat
            tiles = base
            default_facing = _SEAT_FACING.get(furniture.orientation, Facing.DOWN)
        facing = Facing(use.facing) if use.facing else default_facing
        kind = use.at
        for tile in tiles:
            _add_spot(furniture, tile, facing, pose, use, kind)
        if use.queue and use.at == "front_center":
            for depth in range(1, use.queue + 1):
                _add_spot(furniture, (center_x, front_y + depth), Facing.UP, pose, use, "queue")


def _add_spot(
    furniture: Furniture, tile: TilePos, facing: Facing, pose: Pose, use: UseModel, kind: str
) -> None:
    furniture.spots.append(
        Spot(
            furniture=furniture,
            index=len(furniture.spots),
            tile=tile,
            facing=facing,
            pose=pose,
            verbs=frozenset(use.verbs),
            role=use.role,
            kind=kind,
        )
    )


def apply_grants(furniture_list: list[Furniture]) -> None:
    """Donne aux sièges les verbes des objets qu'ils regardent.

    Une chaise ne sait pas qu'elle permet de manger : c'est la table en face
    qui le lui « accorde ». Le même mécanisme donne `work_computer` aux
    sièges face à un ordinateur et `watch_tv` aux canapés face à une télé.
    """
    granting: dict[TilePos, list[Furniture]] = {}
    for furniture in furniture_list:
        if furniture.behaviour and furniture.behaviour.grants:
            for tile in furniture.tiles():
                granting.setdefault(tile, []).append(furniture)
    if not granting:
        return
    for furniture in furniture_list:
        for spot in furniture.spots:
            if not spot.is_seat:
                continue
            gained: set[str] = set()
            dx, dy = spot.facing.delta
            for giver in _facing_objects(spot, granting, dx, dy):
                assert giver.behaviour is not None
                for grant in giver.behaviour.grants:
                    if _within(spot, giver, grant.range, grant.width, dx, dy):
                        gained.update(grant.verbs)
                        for verb in grant.verbs:
                            spot.granted_by.setdefault(verb, giver)
            if gained:
                spot.verbs = spot.verbs | gained


def _facing_objects(
    spot: Spot, granting: dict[TilePos, list[Furniture]], dx: int, dy: int
) -> list[Furniture]:
    x, y = spot.tile
    found: dict[str, Furniture] = {}
    for distance in range(1, 9):
        for lateral in range(-4, 5):
            tile = (x + dx * distance + dy * lateral, y + dy * distance + dx * lateral)
            for giver in granting.get(tile, ()):
                if giver is not spot.furniture:
                    found.setdefault(giver.uid, giver)
    return list(found.values())


def _within(spot: Spot, giver: Furniture, reach: int, width: int, dx: int, dy: int) -> bool:
    x, y = spot.tile
    for tx, ty in giver.tiles():
        along = (tx - x) * dx + (ty - y) * dy
        lateral = abs((tx - x) * dy + (ty - y) * dx)
        if 1 <= along <= reach and lateral <= width:
            return True
    return False
