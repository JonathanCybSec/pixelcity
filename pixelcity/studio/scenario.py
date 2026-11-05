"""Scénarios : un jeu d'habitants enregistré, que l'on peut relancer à volonté.

Un scénario est un fichier YAML lisible, rangé dans le dossier de
l'utilisateur (jamais dans le dossier du jeu, qui peut être en lecture seule
une fois installé) :
- Windows : %APPDATA%/PixelCity/scenarios/
- ailleurs : ~/.local/share/pixelcity/scenarios/

On y enregistre des « brouillons » (`AgentDraft`) plutôt que des
`AgentModel` complets : le métier y figure par sa clé de préréglage, pas par
ses horaires. Le fichier reste court, et si l'on corrige un préréglage, tous
les scénarios en profitent.
"""

from __future__ import annotations

import os
import random
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from pixelcity.config.loader import ConfigError, GameConfig, _cross_validate
from pixelcity.config.schemas import AgentModel, AgentsConfig
from pixelcity.sim.types import PlaceKind
from pixelcity.studio.presets import (
    ACCENT_COLORS,
    IDEOLOGIES,
    JOBS,
    JOBS_BY_KEY,
    SPEECH_STYLES,
    VALUES,
    job_for,
    random_name,
    slugify,
)

TRAITS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
MAX_AGENTS = 12
FORMAT_VERSION = 1


@dataclass(slots=True)
class AgentDraft:
    """Un habitant en cours d'édition : des champs simples, modifiables par l'interface."""

    name: str = "Nouvel habitant"
    age: int = 30
    job: str = "employe_bureau"  # clé d'un préréglage de presets.JOBS
    job_title: str = ""  # intitulé affiché (« Caissière ») ; vide : celui du préréglage
    home: str = ""
    sprite: int = 0
    color: str = "#5b8def"
    personality: dict[str, float] = field(default_factory=lambda: dict.fromkeys(TRAITS, 0.5))
    values: str = ""  # séparées par des virgules
    speech_style: str = ""
    ideology: str = ""
    llm_model: str = ""  # vide : modèle par défaut du .env
    romance: bool = False

    def to_model(self, agent_id: str) -> AgentModel:
        """Convertit en fiche validée par Pydantic (lève ValidationError si incohérent)."""
        job = JOBS_BY_KEY.get(self.job, JOBS_BY_KEY["retraite"])
        data: dict[str, Any] = {
            "id": agent_id,
            "name": self.name.strip(),
            "age": self.age,
            "job": self.job_title.strip() or job.label,
            "home": self.home,
            "color": self.color,
            "sprite": self.sprite,
            "sleep": {"wake": job.wake, "bed": job.bed, "weekend_wake": job.weekend_wake},
            "personality": {trait: round(self.personality[trait], 2) for trait in TRAITS},
            "values": [v.strip() for v in self.values.split(",") if v.strip()],
            "speech_style": self.speech_style.strip(),
            "ideology": self.ideology.strip(),
            "llm_model": self.llm_model.strip() or None,
            "romance": self.romance and self.age >= 18,
        }
        if job.place is not None:
            data["work"] = {
                "place": job.place,
                "schedule": dict(job.schedule),
                "lunch_at_work": job.lunch_at_work,
            }
        return AgentModel.model_validate(data)

    @classmethod
    def from_model(cls, model: AgentModel) -> AgentDraft:
        job = job_for(model.job, model.work.place if model.work else None)
        p = model.personality
        return cls(
            name=model.name,
            age=model.age,
            job=job.key,
            job_title=model.job,
            home=model.home,
            sprite=model.sprite,
            color=model.color,
            personality={trait: float(getattr(p, trait)) for trait in TRAITS},
            values=", ".join(model.values),
            speech_style=model.speech_style,
            ideology=model.ideology,
            llm_model=model.llm_model or "",
            romance=model.romance,
        )


@dataclass(slots=True)
class Scenario:
    name: str
    agents: list[AgentDraft]
    path: Path | None = None

    def ids(self) -> list[str]:
        """Identifiants uniques dérivés des noms (« lea_martin », « lea_martin_2 »...)."""
        ids: list[str] = []
        for draft in self.agents:
            base = slugify(draft.name)
            candidate, n = base, 2
            while candidate in ids:
                candidate, n = f"{base}_{n}", n + 1
            ids.append(candidate)
        return ids


# --------------------------------------------------------------------------- #
# Validation : des messages pour un humain, pas des traces Pydantic
# --------------------------------------------------------------------------- #
def homes(config: GameConfig) -> list[tuple[str, str]]:
    return [(p.id, p.name) for p in config.city.places if p.kind is PlaceKind.HOME]


def validate(scenario: Scenario, config: GameConfig) -> tuple[list[AgentModel], list[str]]:
    """Renvoie les fiches valides et la liste des problèmes (vide si tout va bien)."""
    errors: list[str] = []
    if not scenario.name.strip():
        errors.append("Donne un nom au scénario.")
    if not scenario.agents:
        errors.append("Il faut au moins un habitant.")
    if len(scenario.agents) > MAX_AGENTS:
        errors.append(f"{MAX_AGENTS} habitants au maximum.")
    home_names = dict(homes(config))
    occupants: dict[str, list[str]] = {}
    models: list[AgentModel] = []
    for draft, agent_id in zip(scenario.agents, scenario.ids(), strict=True):
        who = draft.name.strip() or "(sans nom)"
        if not draft.name.strip():
            errors.append("Un habitant n'a pas de nom.")
            continue
        if draft.home not in home_names:
            errors.append(f"{who} : choisis un logement.")
            continue
        occupants.setdefault(draft.home, []).append(who)
        try:
            models.append(draft.to_model(agent_id))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"])
            errors.append(f"{who} : {where} — {first['msg']}")
    for home_id, names in occupants.items():
        # Un lit par logement dans la ville actuelle (l'étape 6 en ajoutera).
        if len(names) > 1:
            errors.append(
                f"{home_names[home_id]} : un seul lit, mais {' et '.join(names)} y vivent."
            )
    if not errors:
        try:
            _cross_validate(replace(config, agents=AgentsConfig(agents=tuple(models))))
        except ConfigError as exc:
            errors.append(str(exc))
    return models, errors


def apply(scenario: Scenario, config: GameConfig) -> GameConfig:
    """La configuration du jeu, avec les habitants du scénario. Lève ConfigError si invalide."""
    models, errors = validate(scenario, config)
    if errors:
        raise ConfigError(f"Scénario « {scenario.name} » invalide :\n" + "\n".join(errors))
    return replace(config, agents=AgentsConfig(agents=tuple(models)))


# --------------------------------------------------------------------------- #
# Création
# --------------------------------------------------------------------------- #
def default_scenario(config: GameConfig) -> Scenario:
    """Les habitants livrés avec le jeu (agents.yaml), comme point de départ."""
    return Scenario("Ma ville", [AgentDraft.from_model(m) for m in config.agents.agents])


def free_home(scenario: Scenario, config: GameConfig) -> str:
    taken = {draft.home for draft in scenario.agents}
    for home_id, _name in homes(config):
        if home_id not in taken:
            return home_id
    return ""


def random_draft(scenario: Scenario, config: GameConfig, rng: random.Random) -> AgentDraft:
    """Un habitant crédible tiré au hasard : de quoi peupler une ville en trois clics."""
    job = rng.choice(JOBS)
    age = rng.randint(66, 82) if job.key == "retraite" else rng.randint(19, 60)
    if job.key == "etudiant":
        age = rng.randint(18, 25)
    return AgentDraft(
        name=random_name(rng, {d.name for d in scenario.agents}),
        age=age,
        job=job.key,
        job_title=job.label,
        home=free_home(scenario, config),
        sprite=rng.randrange(6),
        color=rng.choice(ACCENT_COLORS),
        personality={trait: round(rng.uniform(0.15, 0.9), 2) for trait in TRAITS},
        values=", ".join(rng.sample(VALUES, 3)),
        speech_style=rng.choice(SPEECH_STYLES),
        ideology=rng.choice(IDEOLOGIES),
        romance=age >= 18 and rng.random() < 0.5,
    )


# --------------------------------------------------------------------------- #
# Fichiers
# --------------------------------------------------------------------------- #
def scenarios_dir() -> Path:
    override = os.environ.get("PIXELCITY_DATA")
    if override:
        base = Path(override)
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "PixelCity"
    else:
        base = Path.home() / ".local" / "share" / "pixelcity"
    return base / "scenarios"


def save(scenario: Scenario, directory: Path | None = None) -> Path:
    directory = directory or scenarios_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = scenario.path or directory / f"{slugify(scenario.name)}.yaml"
    payload = {
        "version": FORMAT_VERSION,
        "name": scenario.name.strip(),
        "agents": [asdict(draft) for draft in scenario.agents],
    }
    # Écriture atomique : on écrit à côté puis on renomme. Si le jeu plante
    # au milieu, l'ancien fichier reste intact au lieu d'être à moitié écrit.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "# Scénario PixelCity (modifiable aussi dans le studio du jeu)\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    scenario.path = path
    return path


def load(path: Path) -> Scenario:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path.name} : illisible ({exc})") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("agents"), list):
        raise ConfigError(f"{path.name} : ce n'est pas un scénario PixelCity")
    known = set(AgentDraft.__dataclass_fields__)
    drafts: list[AgentDraft] = []
    for item in raw["agents"]:
        if not isinstance(item, dict):
            continue
        fields = {key: value for key, value in item.items() if key in known}
        draft = AgentDraft(**fields)
        draft.personality = {trait: float(draft.personality.get(trait, 0.5)) for trait in TRAITS}
        drafts.append(draft)
    return Scenario(str(raw.get("name") or path.stem), drafts, path)


def list_scenarios(directory: Path | None = None) -> list[Scenario]:
    directory = directory or scenarios_dir()
    found: list[Scenario] = []
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.yaml")):
        try:
            found.append(load(path))
        except ConfigError:
            continue  # un fichier abîmé ne doit pas empêcher d'ouvrir les autres
    return found


def find(name_or_path: str, directory: Path | None = None) -> Scenario:
    path = Path(name_or_path)
    if path.suffix == ".yaml" and path.is_file():
        return load(path)
    for scenario in list_scenarios(directory):
        if name_or_path in (scenario.name, scenario.path.stem if scenario.path else ""):
            return scenario
    raise ConfigError(f"scénario introuvable : {name_or_path}")
