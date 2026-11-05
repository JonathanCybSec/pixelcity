"""Tests de la carte, des meubles, des places d'utilisation et des horaires."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pixelcity.config.loader import GameConfig
from pixelcity.resources import assets_dir
from pixelcity.sim.simulation import default_asset_roots
from pixelcity.sim.types import ActivityType, Facing, PlaceKind
from pixelcity.world.catalog import Catalog, load_catalog
from pixelcity.world.place import Access, OpeningHours
from pixelcity.world.world import MapError, World, load_world

FRIDAY, SATURDAY, SUNDAY = 4, 5, 6


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog(*default_asset_roots())


@pytest.fixture(scope="module")
def world(config: GameConfig, catalog: Catalog) -> World:
    return load_world(map_path(config), config.city, config.objects, catalog)


def map_path(config: GameConfig) -> Path:
    return assets_dir() / "maps" / config.city.map


# --------------------------------------------------------------------------- #
# La carte
# --------------------------------------------------------------------------- #
def test_tous_les_lieux_sont_sur_la_carte(world: World, config: GameConfig) -> None:
    assert list(world.places) == [place.id for place in config.city.places]
    assert (world.width, world.height) == (96, 64)
    for place in world.places.values():
        assert place.entrances, f"{place.id} n'a pas d'entrée"


def test_le_seuil_est_dehors(world: World) -> None:
    """On attend l'ouverture d'un commerce DEVANT la porte, pas dans l'embrasure."""
    for place in world.places.values():
        assert len(place.doorsteps) == len(place.entrances)
        for step in place.doorsteps:
            assert not place.area.contains(step), place.id
            assert world.grid.is_walkable(step)


def test_toutes_les_entrees_sont_reliees(world: World) -> None:
    places = list(world.places.values())
    origin = places[0].entrances[0]
    for place in places[1:]:
        for entrance in place.entrances:
            assert world.pathfinder.find_path(origin, entrance) is not None, place.id


def test_on_ne_traverse_pas_les_murs(world: World) -> None:
    for tile in world.walls:
        assert not world.grid.is_walkable(tile)


def test_les_trottoirs_sont_preferes_a_la_chaussee(world: World) -> None:
    """Pour traverser, A* doit emprunter un passage piéton (coût 1), pas la chaussée (8)."""
    home = world.places["maison_dupont"].entrances[0]
    bakery = world.places["boulangerie"].entrances[0]
    path = world.pathfinder.find_path(home, bakery)
    assert path is not None
    assert all(world.grid.cost(tile) <= 3 for tile in path)


# --------------------------------------------------------------------------- #
# Les meubles et leurs places
# --------------------------------------------------------------------------- #
def test_chaque_logement_permet_de_vivre(world: World) -> None:
    """Dormir, cuisiner, manger, se laver : tout doit exister dans CHAQUE logement."""
    needed = {"sleep", "take_food", "cook", "eat", "shower", "use_toilet", "relax"}
    for place in world.places.values():
        if place.kind is PlaceKind.HOME:
            missing = {verb for verb in needed if not place.offers_verb(verb)}
            assert not missing, (place.id, missing)


def test_les_meubles_bloquent_le_sol_mais_pas_les_sieges(world: World) -> None:
    sofa = next(f for f in world.furniture.values() if f.type_id == "SOFA")
    for tile in sofa.base_tiles():
        assert not world.grid.is_walkable(tile)
        assert world.grid.is_endpoint(tile)  # mais on peut aller s'y asseoir


def test_la_table_donne_a_manger_aux_chaises_qui_la_regardent(world: World) -> None:
    eat_seats = [s for s in world.places["maison_dupont"].spots_for("eat")]
    assert eat_seats and all(s.is_seat for s in eat_seats)
    for seat in eat_seats:
        assert seat.granted_by["eat"].type_id in ("SMALL_TABLE", "TABLE_FRONT")


def test_on_allume_la_tele_pas_le_canape(world: World) -> None:
    spot = world.places["maison_dupont"].spots_for("watch_tv")[0]
    assert spot.furniture.type_id == "SOFA"
    assert spot.granted_by["watch_tv"].type_id == "TV"
    assert spot.facing is Facing.UP  # le canapé vu de dos regarde la télé


def test_les_comptoirs_ont_un_vendeur_et_une_file(world: World) -> None:
    counter = next(f for f in world.furniture.values() if f.type_id == "BAKERY_COUNTER")
    kinds = [spot.kind for spot in counter.spots]
    assert "behind_center" in kinds and "front_center" in kinds
    assert kinds.count("queue") == 3
    staff = next(s for s in counter.spots if s.kind == "behind_center")
    assert staff.role == "staff" and staff.facing is Facing.DOWN


def _furniture_object(source: str, type_id: str) -> str:
    match = re.search(rf'<object id="\d+" name="{type_id}".*?</object>', source, re.S)
    assert match is not None
    return match.group(0)


def test_deux_meubles_au_meme_endroit(config: GameConfig, catalog: Catalog, tmp_path: Path) -> None:
    source = map_path(config).read_text(encoding="utf-8")
    fridge = _furniture_object(source, "FRIDGE")
    duplicate = re.sub(r'id="(\d+)"', 'id="99999"', fridge, count=1)
    broken = tmp_path / "city.tmx"
    broken.write_text(source.replace(fridge, fridge + duplicate, 1), encoding="utf-8")
    # Le noyau ne lit que le XML (le tileset est intégré à la carte) : pas besoin
    # de copier les images. Tant mieux : un lien symbolique exige des droits
    # d'administrateur sous Windows.
    with pytest.raises(MapError, match="chevauche"):
        load_world(broken, config.city, config.objects, catalog)


def test_carte_et_config_discordantes(config: GameConfig, catalog: Catalog, tmp_path: Path) -> None:
    source = map_path(config).read_text(encoding="utf-8")
    broken = tmp_path / "broken.tmx"
    broken.write_text(source.replace('value="cafe"', 'value="cafe_fantome"'), encoding="utf-8")
    with pytest.raises(MapError) as error:
        load_world(broken, config.city, config.objects, catalog)
    assert "cafe_fantome" in str(error.value) and "cafe" in str(error.value)


# --------------------------------------------------------------------------- #
# Horaires et accès
# --------------------------------------------------------------------------- #
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
    # Les toilettes de la boulangerie sont réservées au personnel.
    assert access(bakery.id, ActivityType.TOILET, noon) is Access.FORBIDDEN
    assert access(bakery.id, ActivityType.TOILET, noon, staff=True) is Access.OK
    # On ne dort que chez soi.
    assert access(home.id, ActivityType.SLEEP, noon, resident=True) is Access.OK
    assert access(home.id, ActivityType.SLEEP, noon) is Access.FORBIDDEN
