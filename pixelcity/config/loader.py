"""Chargement et validation croisée des fichiers de configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from pixelcity.config.schemas import (
    SPECIAL_VERBS,
    ActionsConfig,
    AgentsConfig,
    CityConfig,
    DialoguesConfig,
    ObjectsConfig,
    PlaceModel,
    Settings,
)
from pixelcity.resources import resource_path
from pixelcity.sim.types import ActivityType, PlaceKind


class ConfigError(Exception):
    """Erreur de configuration, avec un message lisible par un humain."""


@dataclass(frozen=True, slots=True)
class GameConfig:
    settings: Settings
    city: CityConfig
    agents: AgentsConfig
    objects: ObjectsConfig
    actions: ActionsConfig
    dialogues: DialoguesConfig

    def place(self, place_id: str) -> PlaceModel:
        for place in self.city.places:
            if place.id == place_id:
                return place
        raise KeyError(place_id)


def default_config_dir() -> Path:
    return resource_path("config")


def load_config(config_dir: Path | None = None) -> GameConfig:
    directory = config_dir if config_dir is not None else default_config_dir()
    config = GameConfig(
        settings=_load_model(directory / "settings.yaml", Settings),
        city=_load_model(directory / "city.yaml", CityConfig),
        agents=_load_model(directory / "agents.yaml", AgentsConfig),
        objects=_load_model(directory / "objects.yaml", ObjectsConfig),
        actions=_load_model(directory / "actions.yaml", ActionsConfig),
        dialogues=_load_model(directory / "dialogues.yaml", DialoguesConfig),
    )
    _cross_validate(config)
    _check_verbs_and_items(config)
    return config


def _check_verbs_and_items(config: GameConfig) -> None:
    """Les recettes ne doivent utiliser que des verbes et articles qui existent.

    Une faute de frappe (`take_fod`) ferait échouer l'étape en silence au
    milieu de la simulation : on la signale au démarrage.
    """
    offered: set[str] = set(SPECIAL_VERBS)
    for behaviour in config.objects.objects.values():
        for use in behaviour.uses:
            offered.update(use.verbs)
        for grant in behaviour.grants:
            offered.update(grant.verbs)
    errors: list[str] = []
    for name, recipe in config.actions.recipes.items():
        errors.extend(
            f"actions.yaml : {name} utilise le verbe {step.verb!r}, qu'aucun objet ne propose"
            for step in recipe.steps
            if step.verb not in offered
        )
    items = set(config.actions.items)
    for type_id, behaviour in config.objects.objects.items():
        stocked = set(behaviour.container.items) if behaviour.container else set()
        for item in sorted((stocked | set(behaviour.sells)) - items):
            errors.append(f"objects.yaml : {type_id} utilise l'article inconnu {item!r}")
    if errors:
        raise ConfigError("Configuration incohérente\n" + "\n".join(f"  → {e}" for e in errors))


def _load_model[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        # encoding="utf-8" explicite : sous Windows, l'encodage par défaut est
        # souvent cp1252 et les accents des fichiers YAML seraient corrompus.
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Fichier de configuration introuvable : {path}") from exc
    try:
        # safe_load, jamais load : le chargeur complet de PyYAML peut instancier
        # des objets Python arbitraires (`!!python/object/apply:os.system`),
        # donc exécuter du code caché dans un fichier de config piégé.
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} : YAML invalide\n{exc}") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path.name, exc, raw)) from exc


def _format_validation_error(filename: str, error: ValidationError, raw: Any) -> str:
    lines = [f"{filename} : configuration invalide"]
    for item in error.errors():
        location = _humanize_location(raw, item["loc"])
        lines.append(f"  → {location} : {item['msg']}")
    return "\n".join(lines)


def _humanize_location(raw: Any, location: tuple[int | str, ...]) -> str:
    """Remplace les indices de liste par l'`id` de l'élément quand il existe.

    `agents.1.home` devient `agents.lea.home` : bien plus parlant quand on
    corrige le fichier à la main.
    """
    parts: list[str] = []
    node = raw
    for key in location:
        if isinstance(key, int) and isinstance(node, list) and 0 <= key < len(node):
            node = node[key]
            identifier = node.get("id") if isinstance(node, dict) else None
            parts.append(str(identifier) if identifier is not None else str(key))
        else:
            node = node.get(key) if isinstance(node, dict) else None
            parts.append(str(key))
    return ".".join(parts) if parts else "(racine)"


def _cross_validate(config: GameConfig) -> None:
    """Vérifie les références ENTRE fichiers, que Pydantic ne peut pas voir seul."""
    places = {place.id: place for place in config.city.places}
    known = ", ".join(sorted(places))
    errors: list[str] = []
    for agent in config.agents.agents:
        home = places.get(agent.home)
        if home is None:
            errors.append(f"{agent.id}.home : lieu {agent.home!r} inconnu (lieux connus : {known})")
        elif home.kind is not PlaceKind.HOME:
            errors.append(f"{agent.id}.home : {agent.home!r} n'est pas un logement")
        if agent.work is None:
            continue
        work = places.get(agent.work.place)
        if work is None:
            unknown = agent.work.place
            errors.append(
                f"{agent.id}.work.place : lieu {unknown!r} inconnu (lieux connus : {known})"
            )
            continue
        if ActivityType.WORK not in work.staff_activities:
            errors.append(f"{agent.id}.work.place : {work.id!r} ne propose pas `work` aux employés")
        offers_meal = (
            ActivityType.EAT in work.staff_activities or ActivityType.EAT in work.activities
        )
        if agent.work.lunch_at_work and not offers_meal:
            errors.append(f"{agent.id}.work.lunch_at_work : {work.id!r} ne propose pas `eat`")
    if errors:
        raise ConfigError(
            "agents.yaml : références invalides\n" + "\n".join(f"  → {e}" for e in errors)
        )
