"""Tests de la carte, des lieux et des horaires d'ouverture."""

from __future__ import annotations

from pathlib import Path

import pytest

from pixelcity.config.loader import GameConfig
from pixelcity.resources import resource_path
from pixelcity.sim.types import ActivityType, PlaceKind
from pixelcity.world.place import Access, OpeningHours
from pixelcity.world.world import MapError, World, load_world

FRIDAY, SATURDAY, SUNDAY = 4, 5, 6


@pytest.fixture(scope="module")
def world(config: GameConfig) -> World:
    return load_world(
        resource_path("assets", "maps", config.city.map), config.city, config.settings
    )


def test_tous_les_lieux_sont_sur_la_carte(world: World, config: GameConfig) -> None:
    assert list(world.places) == [place.id for place in config.city.places]
    for place in world.places.values():
        assert place.entrances, f"{place.id} n'a pas d'entrée"


def test_toutes_les_entrees_sont_reliees(world: World) -> None:
    places = list(world.places.values())
    origin = places[0].entrances[0]
    for place in places[1:]:
        for entrance in place.entrances:
            assert world.pathfinder.find_path(origin, entrance) is not None, place.id


def test_les_murs_sont_infranchissables_sauf_les_portes(world: World) -> None:
    for place in world.places.values():
        if place.outdoor:
            continue
        for tile in place.area.tiles():
            assert world.grid.is_walkable(tile) == (tile in place.entrances), (place.id, tile)


def test_le_parc_a_des_endroits_ou_flaner(world: World) -> None:
    park = world.places["parc"]
    assert park.kind is PlaceKind.PARK and park.outdoor
    assert len(park.spots) > 50


def test_les_trottoirs_sont_preferes_a_la_chaussee(world: World) -> None:
    """Pour traverser, A* doit emprunter un passage piéton (coût 1), pas la chaussée (8)."""
    home = world.places["maison_dupont"].entrances[0]
    bakery = world.places["boulangerie"].entrances[0]
    path = world.pathfinder.find_path(home, bakery)
    assert path is not None
    assert all(world.grid.cost(tile) <= 3 for tile in path)


def test_horaires_simples() -> None:
    hours = OpeningHours((6 * 60 + 30, 19 * 60 + 30), frozenset(range(6)))
    assert hours.is_open(0, 7 * 60)
    assert not hours.is_open(0, 6 * 60)
    assert not hours.is_open(0, 19 * 60 + 30)  # la fermeture est exclue
    assert not hours.is_open(SUNDAY, 12 * 60)


def test_horaires_qui_passent_minuit() -> None:
    """Un bar ouvert le vendredi de 18:00 à 02:00 : piège classique."""
    bar = OpeningHours((18 * 60, 2 * 60), frozenset({FRIDAY}))
    assert bar.is_open(FRIDAY, 23 * 60)
    assert bar.is_open(SATURDAY, 1 * 60)  # la nuit de vendredi déborde sur samedi
    assert not bar.is_open(SATURDAY, 23 * 60)  # le samedi soir, fermé
    assert not bar.is_open(FRIDAY, 1 * 60)  # jeudi n'est pas un jour d'ouverture
    assert not bar.is_open(FRIDAY, 12 * 60)


def test_regles_d_acces(world: World) -> None:
    bakery, home = world.places["boulangerie"], world.places["maison_dupont"]
    monday, five_am, noon = 0, 5 * 60, 12 * 60

    def access(place_id: str, activity: ActivityType, minute: int, **who: bool) -> Access:
        flags = {"resident": False, "staff": False, **who}
        return world.places[place_id].check_access(activity, monday, minute, entering=True, **flags)

    # Le boulanger entre avant l'ouverture au public ; un client, non.
    assert access(bakery.id, ActivityType.WORK, five_am, staff=True) is Access.OK
    assert access(bakery.id, ActivityType.EAT, five_am) is Access.CLOSED
    assert access(bakery.id, ActivityType.EAT, noon) is Access.OK
    assert access(bakery.id, ActivityType.WORK, noon) is Access.FORBIDDEN
    # On ne dort que chez soi.
    assert access(home.id, ActivityType.SLEEP, noon, resident=True) is Access.OK
    assert access(home.id, ActivityType.SLEEP, noon) is Access.FORBIDDEN


def test_carte_et_config_discordantes(config: GameConfig, tmp_path: Path) -> None:
    source = resource_path("assets", "maps", config.city.map)
    broken = tmp_path / "broken.tmx"
    broken.write_text(
        source.read_text(encoding="utf-8").replace('value="cafe"', 'value="cafe_fantome"'),
        encoding="utf-8",
    )
    with pytest.raises(MapError) as error:
        load_world(broken, config.city, config.settings)
    assert "cafe_fantome" in str(error.value) and "cafe" in str(error.value)
