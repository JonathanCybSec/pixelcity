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

from typing import Annotated, Literal, Self

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


class TransitSettings(StrictModel):
    """La ligne de bus (étape 6)."""

    enabled: bool = True
    buses: int = Field(2, ge=0, le=6)
    speed_tiles_per_minute: float = Field(18.0, gt=0)
    dwell_minutes: float = Field(1.0, ge=0)
    ticket: float = Field(1.5, ge=0)
    # On prend le bus seulement si la marche dépasse cette distance (en cases).
    min_walk_tiles: int = Field(45, ge=0)


class EconomySettings(StrictModel):
    enabled: bool = True
    # En dessous, on évite de dépenser (déjeuner dehors, café) : on se serre la ceinture.
    tight_budget: float = 40.0
    comfortable: float = 400.0


class Settings(StrictModel):
    seed: int = 42
    time: TimeSettings = TimeSettings()
    window: WindowSettings = WindowSettings()
    walk_speed_tiles_per_minute: float = Field(3.0, gt=0)
    needs: dict[NeedKind, NeedSpec]
    # Effets permanents de la marche. Les effets des activités, eux, sont
    # portés par les étapes des recettes (actions.yaml).
    walking_effects: NeedEffects = {}
    economy: EconomySettings = EconomySettings()
    transit: TransitSettings = TransitSettings()

    @model_validator(mode="after")
    def _check_completeness(self) -> Self:
        missing_needs = set(NeedKind) - set(self.needs)
        if missing_needs:
            raise ValueError(f"besoins manquants dans `needs` : {sorted(missing_needs)}")
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
    rent: float = Field(0.0, ge=0)  # loyer par jour (logements), prélevé à minuit

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.kind is PlaceKind.HOME and ActivityType.SLEEP not in self.activities:
            raise ValueError("un logement doit proposer l'activité `sleep`")
        if not self.days:
            raise ValueError("`days` ne peut pas être vide")
        return self


class CityConfig(StrictModel):
    # Nom du fichier de carte Tiled, dans `pixelcity/assets/maps/`.
    map: str = "city.tmx"
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
    # Couleur d'accent dans l'interface, et apparence : l'un des 6 personnages
    # de pixel-agents (char_0.png à char_5.png).
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    sprite: int = Field(0, ge=0, le=5)
    sleep: SleepModel
    work: WorkModel | None = None
    personality: Personality
    values: tuple[str, ...] = ()
    # Étape 3 : ce qui nourrit les conversations.
    speech_style: str = ""  # « phrases courtes, tutoie tout le monde »
    ideology: str = ""  # convictions, vision du monde (« écologiste convaincu »)
    llm_model: str | None = None  # modèle Ollama propre à cet habitant
    # Le flirt n'est possible qu'entre deux adultes ouverts à la romance et
    # sans autre partenaire. `partner` : l'id de son ou sa partenaire.
    romance: bool = False
    partner: Slug | None = None
    # Étape 6 : l'argent. Salaire horaire (payé au fil des heures travaillées),
    # revenu quotidien (retraite, bourse, allocation), économies de départ.
    wage: float = Field(0.0, ge=0)
    allowance: float = Field(0.0, ge=0)
    money: float = 300.0


class AgentsConfig(StrictModel):
    agents: tuple[AgentModel, ...]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        _ensure_unique([agent.id for agent in self.agents], "agent")
        return self


# --------------------------------------------------------------------------- #
# objects.yaml : ce qu'on peut faire avec chaque meuble
# --------------------------------------------------------------------------- #
SpotKind = Literal["front", "front_center", "behind_center", "seat", "head"]
PoseName = Literal["stand", "sit", "lie", "run", "hidden"]
FacingName = Literal["up", "down", "left", "right"]
RoleName = Literal["any", "staff", "customer", "resident"]


class UseModel(StrictModel):
    """Une façon d'utiliser l'objet : des verbes, à un emplacement précis.

    - front / front_center : debout devant l'objet (toutes les colonnes ou celle du milieu) ;
    - behind_center : derrière (le vendeur derrière son comptoir) ;
    - seat : sur l'objet lui-même (chaise, banc, canapé), une place par tuile ;
    - head : la première tuile au sol (oreiller du lit, bac de douche...).
    """

    verbs: tuple[Slug, ...]
    at: SpotKind = "front"
    pose: PoseName = "stand"
    facing: FacingName | None = None
    role: RoleName = "any"
    queue: int = Field(0, ge=0, le=6)  # places de file d'attente derrière le client


class GrantModel(StrictModel):
    """Verbes offerts aux sièges tournés vers cet objet (table → manger, télé → regarder)."""

    verbs: tuple[Slug, ...]
    range: int = Field(1, ge=1, le=8)
    width: int = Field(0, ge=0, le=4)


class ContainerModel(StrictModel):
    """Stock d'un objet : article → quantité de départ (-1 = illimité)."""

    items: dict[Slug, int]
    capacity: int = Field(ge=1)


class ObjectModel(StrictModel):
    label: str
    uses: tuple[UseModel, ...] = ()
    grants: tuple[GrantModel, ...] = ()
    container: ContainerModel | None = None
    sells: tuple[Slug, ...] = ()
    self_service: bool = False  # un client peut se servir seul si personne ne tient le comptoir


class ObjectsConfig(StrictModel):
    objects: dict[str, ObjectModel]


# --------------------------------------------------------------------------- #
# actions.yaml : les recettes d'actions
# --------------------------------------------------------------------------- #
AnimName = Literal["idle", "interact", "read", "eat", "talk"]

# Verbes qui ne dépendent d'aucun objet.
SPECIAL_VERBS = frozenset({"order", "stroll", "wait"})


class StepModel(StrictModel):
    verb: Slug
    label: str
    minutes: float | None = Field(None, gt=0)
    until_end: bool = False  # jusqu'à la fin du bloc (dormir, travailler...)
    anim: AnimName | None = None
    effects: NeedEffects = {}  # points par heure pendant l'étape
    take: dict[Slug, int] = {}  # stock de l'objet → inventaire (au début)
    put: dict[Slug, int] = {}  # inventaire → stock de l'objet (à la fin)
    consume: dict[Slug, int] = {}  # inventaire → disparaît (à la fin)
    produce: dict[Slug, int] = {}  # → stock du commerce du lieu (à la fin)
    make: dict[Slug, int] = {}  # → inventaire de l'habitant (à la fin) : la gamelle préparée
    buy: Slug | None = None  # pour `order` : l'article acheté au comptoir
    optional: bool = False  # si impossible, on passe à l'étape suivante
    # Allume l'objet pendant l'étape. Un booléen plutôt que `state: on` :
    # en YAML 1.1, `on` sans guillemets est lu comme… le booléen True.
    switch_on: bool = False
    distinct: bool = False  # un autre objet qu'à l'étape précédente

    @model_validator(mode="after")
    def _check_duration(self) -> Self:
        if self.verb == "order":
            if self.buy is None:
                raise ValueError("une étape `order` doit préciser `buy`")
        elif (self.minutes is None) == (not self.until_end):
            raise ValueError(f"étape {self.verb!r} : donner `minutes` OU `until_end: true`")
        return self


class RecipeModel(StrictModel):
    label: str
    steps: tuple[StepModel, ...]
    loop: bool = False  # répète les étapes jusqu'à la fin du bloc (les métiers)
    serve: bool = False  # sert les clients en priorité (commerçants)

    @model_validator(mode="after")
    def _check_steps(self) -> Self:
        if not self.steps:
            raise ValueError("une recette doit avoir au moins une étape")
        return self


class ItemModel(StrictModel):
    label: str
    price: float = Field(0.0, ge=0)  # prix de vente au comptoir, en euros
    stores_as: dict[Slug, int] = {}  # sac de courses → 6 provisions dans le frigo


class ActionsConfig(StrictModel):
    items: dict[Slug, ItemModel]
    recipes: dict[Slug, RecipeModel]
    jobs: dict[PlaceKind, Slug]  # lieu de travail → recette du métier
    fillers: dict[str, Slug]  # recette d'attente : "home", type de lieu ou "default"

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        for name in (*self.jobs.values(), *self.fillers.values()):
            if name not in self.recipes:
                raise ValueError(f"recette inconnue : {name!r}")
        if "default" not in self.fillers:
            raise ValueError("`fillers` doit avoir une entrée `default`")
        for recipe_name, recipe in self.recipes.items():
            for step in recipe.steps:
                for item in (*step.take, *step.put, *step.consume, *step.produce, *step.make):
                    if item not in self.items:
                        raise ValueError(f"{recipe_name}.{step.verb} : article inconnu {item!r}")
                if step.buy is not None and step.buy not in self.items:
                    raise ValueError(f"{recipe_name}.{step.verb} : article inconnu {step.buy!r}")
        return self


# --------------------------------------------------------------------------- #
# dialogues.yaml : les répliques scriptées (avant les LLM de l'étape 3)
# --------------------------------------------------------------------------- #
class StreetDialogues(StrictModel):
    opener: tuple[str, ...]
    reply: tuple[str, ...]
    need: tuple[str, ...]  # « {need} » est remplacé par le besoin (« j'ai faim »)
    closer: tuple[str, ...]


class DialoguesConfig(StrictModel):
    greet: tuple[str, ...]
    welcome: tuple[str, ...]
    order: dict[Slug, tuple[str, ...]]
    serve: dict[Slug, tuple[str, ...]]
    thanks: tuple[str, ...]
    disappointed: tuple[str, ...]
    self_checkout: tuple[str, ...]
    goodbye: tuple[str, ...]
    out_of_stock: tuple[str, ...]
    street: StreetDialogues
    no_money: tuple[str, ...] = ("Ah… la carte ne passe pas. Désolé.",)


def _ensure_unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"identifiant de {what} en double : {identifier!r}")
        seen.add(identifier)
