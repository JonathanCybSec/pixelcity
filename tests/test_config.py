"""Tests du chargement et de la validation de la configuration."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pixelcity.config.loader import ConfigError, GameConfig, default_config_dir, load_config
from pixelcity.sim.types import NeedKind


def test_la_config_par_defaut_est_valide(config: GameConfig) -> None:
    assert len(config.agents.agents) == 6
    assert len(config.city.places) == 14
    assert set(config.settings.needs) == set(NeedKind)
    # Chaque type de lieu de travail a sa recette de métier.
    workplaces = {config.place(a.work.place).kind for a in config.agents.agents if a.work}
    assert workplaces <= set(config.actions.jobs)


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    """Copie de la config dans un dossier temporaire, qu'un test peut abîmer."""
    target = tmp_path / "config"
    shutil.copytree(default_config_dir(), target, ignore=shutil.ignore_patterns("*.py"))
    return target


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"motif introuvable dans {path.name} : {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_reference_vers_un_lieu_inconnu(config_copy: Path) -> None:
    _replace(config_copy / "agents.yaml", "home: appart_1", "home: maison_4")
    with pytest.raises(ConfigError) as error:
        load_config(config_copy)
    message = str(error.value)
    assert "lea.home" in message and "maison_4" in message


def test_faute_de_frappe_dans_une_cle(config_copy: Path) -> None:
    _replace(config_copy / "city.yaml", "capacity: 10", "capacty: 10")
    with pytest.raises(ConfigError) as error:
        load_config(config_copy)
    assert "boulangerie" in str(error.value)  # l'erreur nomme le lieu, pas « places.3 »


def test_heure_sans_guillemets(config_copy: Path) -> None:
    # Piège YAML 1.1 : sans guillemets, 23:00 est lu comme le NOMBRE 1380
    # (base 60), alors que 07:00 reste une chaîne à cause du zéro initial.
    # Incohérent, donc sournois : on exige des guillemets partout.
    _replace(config_copy / "agents.yaml", 'bed: "23:00"', "bed: 23:00")
    with pytest.raises(ConfigError) as error:
        load_config(config_copy)
    assert "guillemets" in str(error.value)


def test_trait_de_personnalite_hors_limites(config_copy: Path) -> None:
    _replace(config_copy / "agents.yaml", "openness: 0.35", "openness: 1.5")
    with pytest.raises(ConfigError):
        load_config(config_copy)


def test_seuils_de_besoin_incoherents(config_copy: Path) -> None:
    _replace(
        config_copy / "settings.yaml", "critical: 20, satisfied: 90", "critical: 95, satisfied: 90"
    )
    with pytest.raises(ConfigError):
        load_config(config_copy)


def test_fichier_manquant(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        load_config(tmp_path)


def test_verbe_qu_aucun_objet_ne_propose(config_copy: Path) -> None:
    """Une faute de frappe dans une recette doit casser au démarrage, pas à 14 h 37."""
    _replace(config_copy / "actions.yaml", "verb: cook,", "verb: cuisiner,")
    with pytest.raises(ConfigError) as error:
        load_config(config_copy)
    assert "cuisiner" in str(error.value)


def test_article_inconnu(config_copy: Path) -> None:
    _replace(config_copy / "objects.yaml", "sells: [bread]", "sells: [croissant]")
    with pytest.raises(ConfigError) as error:
        load_config(config_copy)
    assert "croissant" in str(error.value)


def test_une_commande_doit_dire_quoi_acheter(config_copy: Path) -> None:
    _replace(config_copy / "actions.yaml", "{verb: order, buy: coffee, ", "{verb: order, ")
    with pytest.raises(ConfigError):
        load_config(config_copy)


def test_etape_sans_duree(config_copy: Path) -> None:
    _replace(config_copy / "actions.yaml", "{verb: cook, minutes: 18, ", "{verb: cook, ")
    with pytest.raises(ConfigError):
        load_config(config_copy)
