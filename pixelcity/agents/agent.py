"""L'habitant : une fiche d'identité immuable + un état qui évolue à chaque tick."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pixelcity.agents.needs import Needs
from pixelcity.agents.plan import DayPlan, PlanBlock
from pixelcity.config.schemas import AgentModel
from pixelcity.sim.types import ActivityType, NeedKind, TilePos


class AgentState(StrEnum):
    """Machine à états explicite de la routine.

    Une énumération plutôt qu'une pile de booléens (`is_walking`,
    `is_inside`...) : un agent est dans UN état à la fois, et les transitions
    sont lisibles dans `routine.py` au lieu d'être dispersées en `if/else`.
    """

    IDLE = "idle"  # rien de prévu ou en attente d'un nouvel essai
    WALKING = "walking"  # en chemin vers une destination
    ACTIVE = "active"  # dans un lieu, en train de faire une activité
    WAITING = "waiting"  # devant un lieu fermé, attend l'ouverture


@dataclass(frozen=True, slots=True)
class Override:
    """Dérogation temporaire au plan.

    - urgence : `need` renseigné, se termine quand ce besoin est comblé ;
    - repli   : `until` renseigné, se termine à cette minute (lieu prévu fermé...).
    """

    activity: ActivityType
    place_id: str
    label: str
    started: int
    need: NeedKind | None = None
    until: int | None = None


@dataclass(slots=True)
class Agent:
    profile: AgentModel
    needs: Needs
    tile: TilePos
    # Position en tuiles (flottants) au tick courant et au tick précédent :
    # le rendu interpole entre les deux pour rester fluide à 60 FPS.
    pos: tuple[float, float]
    prev_pos: tuple[float, float]
    facing: tuple[int, int] = (0, 1)
    state: AgentState = AgentState.IDLE
    place_id: str | None = None  # lieu dans lequel l'agent se trouve
    activity: ActivityType | None = None
    activity_label: str = ""
    plan: DayPlan | None = None
    block_index: int = 0
    override: Override | None = None
    # Déplacement : on avance dans un chemin IMMUABLE grâce à un index.
    path: tuple[TilePos, ...] = ()
    path_index: int = 0
    progress: float = 0.0
    destination: str | None = None
    # Lieux extérieurs : quand choisir un nouvel endroit où flâner.
    next_spot_minute: int = 0
    # Attente devant un lieu fermé / nouvel essai après un échec de chemin.
    wait_started: int | None = None
    retry_minute: int = 0
    # Statistiques : minutes passées par activité (tableau de bord, étape 5).
    minutes_by_activity: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.profile.id

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def work_place_id(self) -> str | None:
        return self.profile.work.place if self.profile.work else None

    def current_block(self) -> PlanBlock | None:
        if self.plan is None or not 0 <= self.block_index < len(self.plan.blocks):
            return None
        return self.plan.blocks[self.block_index]

    def next_block(self) -> PlanBlock | None:
        if self.plan is None or self.block_index + 1 >= len(self.plan.blocks):
            return None
        return self.plan.blocks[self.block_index + 1]

    def status_text(self) -> str:
        """Phrase courte pour l'interface : « au travail », « en chemin vers Café des Arts »."""
        if self.state is AgentState.WALKING and self.place_id is None:
            return f"en chemin ({self.activity_label or '...'})"
        if self.state is AgentState.WAITING:
            return "attend l'ouverture"
        return self.activity_label or self.state.value
