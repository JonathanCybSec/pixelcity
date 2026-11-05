"""Tests du catalogue de meubles (manifest.json au format pixel-agents)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixelcity.resources import assets_dir
from pixelcity.world.catalog import Catalog, CatalogError, load_catalog


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    root = assets_dir()
    return load_catalog(root / "pixel_agents", root / "pixelcity")


def test_les_deux_packs_sont_charges(catalog: Catalog) -> None:
    # Un meuble de pixel-agents et un des nôtres.
    assert "DESK" in catalog and "FRIDGE" in catalog
    assert len(catalog.specs) > 50


def test_gauche_est_le_cote_en_miroir(catalog: Catalog) -> None:
    """Convention de pixel-agents : « left » n'a pas d'image, c'est « side » retourné."""
    chair = catalog.get("WOODEN_CHAIR")
    left, side = chair.variant("left"), chair.variant("side")
    assert left.mirrored and not side.mirrored
    assert left.frames("default") == side.frames("default")


def test_etats_et_animation(catalog: Catalog) -> None:
    stove = catalog.get("STOVE").variant("front")
    assert len(stove.frames("off")) == 1
    assert len(stove.frames("on")) == 2  # deux images : les flammes bougent
    # Un état inconnu retombe sur « off » plutôt que de planter le rendu.
    assert stove.frames("cassé") == stove.frames("off")


def test_rangees_d_arriere_plan_et_calques(catalog: Catalog) -> None:
    bed = catalog.get("BED")
    assert bed.background_tiles == 1
    assert bed.variant("front").footprint == (1, 3)
    assert "occupied" in bed.overlays  # la couverture posée sur le dormeur
    assert catalog.get("WINDOW").on_walls
    assert catalog.get("CASH_REGISTER").on_surfaces


def test_meuble_inconnu(catalog: Catalog) -> None:
    with pytest.raises(CatalogError, match="inconnu"):
        catalog.get("TRAMPOLINE")
    with pytest.raises(CatalogError, match="orientation"):
        catalog.get("FRIDGE").variant("back")


def test_image_manquante(tmp_path: Path) -> None:
    folder = tmp_path / "furniture" / "GHOST"
    folder.mkdir(parents=True)
    manifest = {"id": "GHOST", "type": "asset", "width": 16, "height": 16, "file": "GHOST.png"}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogError, match="image manquante"):
        load_catalog(tmp_path)


def test_le_dernier_pack_l_emporte(tmp_path: Path, catalog: Catalog) -> None:
    source = assets_dir() / "pixelcity" / "furniture" / "BUSH"
    folder = tmp_path / "furniture" / "BUSH"
    folder.mkdir(parents=True)
    for file in source.iterdir():
        (folder / file.name).write_bytes(file.read_bytes())
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    data["name"] = "Buisson remplacé"
    (folder / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    merged = load_catalog(assets_dir() / "pixel_agents", assets_dir() / "pixelcity", tmp_path)
    assert merged.get("BUSH").name == "Buisson remplacé"
