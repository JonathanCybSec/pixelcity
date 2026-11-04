"""Schémas des fichiers de configuration (Pydantic v2).

Principe : on valide aux FRONTIÈRES. Un fichier YAML est une donnée externe,
modifiable à la main, donc potentiellement fausse : on la vérifie entièrement
au démarrage, avec des messages clairs. Une fois validée, le reste du code lui
fait confiance et travaille avec des objets simples (dataclasses).

Deux réglages importants sur tous les modèles :
- `extra="forbid"` : une faute de frappe dans une clé (`capacty: 10`) devient
  une erreur au lieu d'être ignorée en silence ;
- `frozen=True` : la configuration ne peut pas être modifiée par accident
  pendant la simulation.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from pixelcity.sim.types import ActivityType, NeedKind, PlaceKind, Weekday, parse_hhmm

ALL_DAYS: tuple[Weekday, ...] = tuple(Weekday)


# --------------------------------------------------------------------------- #
# Types réutilisables : heures et plages horaires
# --------------------------------------------------------------------------- #
def _parse_time(value: object) -> int:
    if isinstance(value, str):
        return parse_hhmm(value)
    if isinstance(value, int) and not isinstance(value, bool):
        # Piège YAML 1.1 : sans guillemets, `bed: 23:00` est lu comme le nombre
        # 1380 (base 60), alors que `wake: 07:00` reste une chaîne (le zéro
        # initial empêche la conversion). On refuse pour forcer l'écriture claire.
        raise ValueError(
            'heure lue comme un nombre : mettez-la entre guillemets, ex. "23:00" '
            "(sans guillemets, YAML lit 23:00 comme un nombre en base 60)"
        )
    raise ValueError('heure attendue au format "HH:MM"')


def _parse_range(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or "-" not in value:
        raise ValueError('plage attendue au format "HH:MM-HH:MM"')
    start_text, end_text = value.split("-", 1)
    return parse_hhmm(start_text), parse_hhmm(end_text)


def _parse_hours(value: object) -> tuple[int, int] | None:
    """`"always"` → None (toujours ouvert), sinon une plage qui peut passer minuit."""
    if value == "always":
        return None
    return _parse_range(value)


Minute = Annotated[int, BeforeValidator(_parse_time)]
TimeRange = Annotated[tuple[int, int], BeforeValidator(_parse_range)]
OpeningRange = Annotated[tuple[int, int] | None, BeforeValidator(_parse_hours)]
Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
Gauge = Annotated[float, Field(ge=0.0, le=100.0)]

# Effets d'une activité sur les besoins, en points PAR HEURE simulée.
type NeedEffects = dict[NeedKind, float]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# settings.yaml
# --------------------------------------------------------------------------- #
class TimeSettings(StrictModel):
    tick_seconds: int = Field(10, ge=1, le=60)
    real_minutes_per_day: float = Field(10.0, gt=0)
    speeds: tuple[int, ...] = (1, 2, 5, 10)
    max_ticks_per_frame: int = Field(500, ge=1)


class WindowSettings(StrictModel):
    width: int = Field(1280, ge=640)
    height: int = Field(720, ge=360)
    fps: int = Field(60, ge=10, le=240)
    start_zoom: int = Field(2, ge=1, le=4)


class NeedSpec(StrictModel):
    decay_per_hour: float = Field(ge=0.0)
    critical: Gauge
    satisfied: Gauge
    initial: Gauge

    @model_validator(mode="after")
    def _check_thresholds(self) -> Self:
        # L'écart entre les deux seuils, c'est l'hystérésis : sans lui, un agent
        # affamé mangerait une bouchée, repartirait, et reviendrait aussitôt.
        if self.critical >= self.satisfied:
            raise ValueError("le seuil `critical` doit être inférieur à `satisfied`")
        return self


class Settings(StrictModel):
    seed: int = 42
    time: TimeSettings = TimeSettings()
    window: WindowSettings = WindowSettings()
    walk_speed_tiles_per_minute: float = Field(2.0, gt=0)
    needs: dict[NeedKind, NeedSpec]
    activity_effects: dict[ActivityType, NeedEffects]
    walking_effects: NeedEffects = {}

    @model_validator(mode="after")
    def _check_completeness(self) -> Self:
        missing_needs = set(NeedKind) - set(self.needs)
        if missing_needs:
            raise ValueError(f"besoins manquants dans `needs` : {sorted(missing_needs)}")
        missing_effects = set(ActivityType) - set(self.activity_effects)
        if missing_effects:
            raise ValueError(
                f"activités manquantes dans `activity_effects` : {sorted(missing_effects)}"
            )
        if 60 % self.time.tick_seconds != 0:
            raise ValueError("`time.tick_seconds` doit diviser 60")
        return self


# --------------------------------------------------------------------------- #
# city.yaml
# --------------------------------------------------------------------------- #
class PlaceModel(StrictModel):
    id: Slug
    name: str
    kind: PlaceKind
    capacity: int = Field(ge=1)
    hours: OpeningRange = None
    days: tuple[Weekday, ...] = ALL_DAYS
    # Ce que tout le monde peut faire ici, aux heures d'ouverture.
    activities: tuple[ActivityType, ...] = ()
    # Ce que seuls les employés du lieu peuvent faire, à toute heure
    # (le boulanger arrive avant l'ouverture de la boutique).
    staff_activities: tuple[ActivityType, ...] = ()
    # Surcharges des effets par défaut de `settings.yaml` (ex. le sport fatigue).
    effects: dict[ActivityType, NeedEffects] = {}

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        offered = set(self.activities) | set(self.staff_activities)
        unknown = set(self.effects) - offered
        if unknown:
            raise ValueError(f"effets définis pour des activités non proposées : {sorted(unknown)}")
        if self.kind is PlaceKind.HOME and ActivityType.SLEEP not in self.activities:
            raise ValueError("un logement doit proposer l'activité `sleep`")
        if not self.days:
            raise ValueError("`days` ne peut pas être vide")
        return self


class CityConfig(StrictModel):
    # Nom du fichier de carte Tiled, dans `pixelcity/assets/maps/`.
    map: str = "mvp.tmx"
    places: tuple[PlaceModel, ...]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        _ensure_unique([place.id for place in self.places], "lieu")
        return self


# --------------------------------------------------------------------------- #
# agents.yaml
# --------------------------------------------------------------------------- #
class SleepModel(StrictModel):
    wake: Minute
    bed: Minute
    weekend_wake: Minute | None = None

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        # MVP : on se couche avant minuit et on se lève le matin. Gérer les
        # couchers après minuit compliquerait le découpage des plans par jour.
        if not 3 * 60 <= self.wake <= 11 * 60:
            raise ValueError("`wake` doit être entre 03:00 et 11:00")
        if self.weekend_wake is not None and not 3 * 60 <= self.weekend_wake <= 11 * 60:
            raise ValueError("`weekend_wake` doit être entre 03:00 et 11:00")
        if not 19 * 60 <= self.bed <= 23 * 60 + 30:
            raise ValueError("`bed` doit être entre 19:00 et 23:30")
        return self


class WorkModel(StrictModel):
    place: Slug
    schedule: dict[Weekday, TimeRange]
    lunch_at_work: bool = False

    @model_validator(mode="after")
    def _check_shifts(self) -> Self:
        for day, (start, end) in self.schedule.items():
            if start >= end:
                raise ValueError(f"horaire de travail invalide le {day.value} (pas de nuit au MVP)")
        return self


class Personality(StrictModel):
    """Modèle des Big Five (OCEAN), chaque trait entre 0 et 1."""

    openness: UnitFloat
    conscientiousness: UnitFloat
    extraversion: UnitFloat
    agreeableness: UnitFloat
    neuroticism: UnitFloat


class AgentModel(StrictModel):
    id: Slug
    name: str
    age: int = Field(ge=0, le=120)
    job: str
    home: Slug
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    sleep: SleepModel
    work: WorkModel | None = None
    personality: Personality
    values: tuple[str, ...] = ()


class AgentsConfig(StrictModel):
    agents: tuple[AgentModel, ...]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        _ensure_unique([agent.id for agent in self.agents], "agent")
        return self


def _ensure_unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"identifiant de {what} en double : {identifier!r}")
        seen.add(identifier)
