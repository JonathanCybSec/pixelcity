"""Une tâche : l'exécution d'une recette d'actions.yaml, étape par étape.

Chaque étape traverse les mêmes phases, comme une petite machine à états :

    TRAVEL ──► (WAIT_OPEN) ──► SEEK ──► GOTO ──► PERFORM ──► étape suivante
                                  └────► QUEUE ─(servi)─┘

- TRAVEL    : rejoindre le lieu de la tâche (la boulangerie, chez soi...) ;
- WAIT_OPEN : devant la porte d'un lieu pas encore ouvert ;
- SEEK      : chercher dans le lieu un objet libre qui propose le verbe de
              l'étape, et le RÉSERVER (deux habitants ne prennent jamais la
              même chaise) ;
- GOTO      : marcher jusqu'à la place réservée ;
- PERFORM   : utiliser l'objet pendant la durée de l'étape ;
- QUEUE     : faire la queue au comptoir jusqu'à être servi.

Les tâches s'EMPILENT (voir `Agent.tasks`) : une envie pressante interrompt
le dîner, qui reprend ensuite là où il en était, avec le temps qui restait.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pixelcity.agents.plan import PlanBlock
from pixelcity.config.schemas import RecipeModel, StepModel
from pixelcity.sim.types import ActivityType, NeedKind, TilePos
from pixelcity.world.furniture import Furniture, Spot


class Phase(StrEnum):
    TRAVEL = "travel"
    WAIT_OPEN = "wait_open"
    SEEK = "seek"
    GOTO = "goto"
    PERFORM = "perform"
    QUEUE = "queue"
    DONE = "done"
    FAILED = "failed"


class TaskKind(StrEnum):
    BLOCK = "block"  # la tâche d'un bloc du plan
    URGENT = "urgent"  # un besoin pressant (toilettes, fringale...)
    CHORE = "chore"  # une corvée déclenchée par la situation (ranger les courses)
    SERVE = "serve"  # un commerçant qui va servir un client


@dataclass(slots=True, eq=False)
class Task:
    kind: TaskKind
    recipe_id: str
    recipe: RecipeModel
    place_id: str
    activity: ActivityType
    label: str
    created: int  # minute absolue
    # Fin des étapes `until_end` (et des boucles de métier) : la fin du bloc.
    ends_at: int | None = None
    block: PlanBlock | None = None
    need: NeedKind | None = None  # URGENT : le besoin à combler
    desk_uid: str | None = None  # SERVE : le comptoir à tenir

    # --- Progression ----------------------------------------------------------------
    step_index: int = 0
    phase: Phase = Phase.TRAVEL
    step_started: float = 0.0  # minute absolue (fractionnaire) du début de l'étape en cours
    step_ends: float = 0.0  # ... et de sa fin
    remaining: float | None = None  # minutes restantes d'une étape interrompue
    last_furniture: str | None = None  # pour les étapes `distinct`
    wait_started: int | None = None  # début d'attente (porte fermée, file)
    walk_goal: TilePos | None = None  # destination du trajet en cours
    spot: Spot | None = None  # la place réservée pour l'étape en cours
    switched: Furniture | None = None  # objet allumé par l'étape (resté allumé si interrompue)
    next_stroll: float = 0.0
    failure: str | None = None
    loops: int = 0
    announced: bool = False  # TASK_STARTED déjà émis ?
    departed: bool = False  # DEPARTED déjà émis pour ce trajet ?

    @property
    def step(self) -> StepModel | None:
        steps = self.recipe.steps
        return steps[self.step_index] if 0 <= self.step_index < len(steps) else None

    @property
    def finished(self) -> bool:
        return self.phase in (Phase.DONE, Phase.FAILED)

    @property
    def is_performing(self) -> bool:
        return self.phase is Phase.PERFORM

    @property
    def buying(self) -> str | None:
        """L'article commandé, si l'étape en cours est une commande au comptoir."""
        step = self.step
        return step.buy if step is not None and step.verb == "order" else None

    def status_text(self) -> str:
        step = self.step
        match self.phase:
            case Phase.TRAVEL:
                return f"en route : {self.label}"
            case Phase.WAIT_OPEN:
                return f"attend l'ouverture ({self.label})"
            case Phase.QUEUE:
                return step.label if step is not None else "fait la queue"
            case Phase.DONE:
                return f"a fini : {self.label}"
            case Phase.FAILED:
                return f"renonce : {self.label}"
            case _:
                return step.label if step is not None else self.label
