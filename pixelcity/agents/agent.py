"""L'habitant : une fiche d'identité immuable + un état qui évolue à chaque tick.

L'état visible à l'écran (position, regard, posture, animation) est rangé à
part des intentions (plan, pile de tâches) : le rendu ne lit que le premier,
et n'a pas à comprendre le second.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pixelcity.agents.needs import Needs
from pixelcity.agents.plan import DayPlan, PlanBlock
from pixelcity.agents.tasks import Task
from pixelcity.config.schemas import AgentModel
from pixelcity.memory.stream import MemoryStream
from pixelcity.sim.types import Anim, Facing, NeedKind, Pose, TilePos
from pixelcity.world.furniture import Spot


@dataclass(slots=True)
class Speech:
    """Ce que l'habitant est en train de dire (la bulle au-dessus de sa tête)."""

    text: str
    until_tick: int
    to: str | None = None


@dataclass(slots=True, eq=False)
class Agent:
    profile: AgentModel
    needs: Needs
    tile: TilePos
    # Position en tuiles (flottants) au tick courant et au tick précédent :
    # le rendu interpole entre les deux pour rester fluide à 60 images/s.
    pos: tuple[float, float]
    prev_pos: tuple[float, float]

    # --- Ce qu'on voit -----------------------------------------------------------
    facing: Facing = Facing.DOWN
    pose: Pose = Pose.STAND
    anim: Anim = Anim.IDLE
    spot: Spot | None = None  # la place occupée en ce moment (chaise, lit, comptoir...)
    speech: Speech | None = None
    memory: MemoryStream = field(default_factory=lambda: MemoryStream(360))
    conversation: int | None = None  # conversation en ville en cours (on s'arrête pour parler)

    # --- Où il est, ce qu'il veut faire ---------------------------------------------
    place_id: str | None = None
    plan: DayPlan | None = None
    block_index: int = 0
    # Pile de tâches : en bas, la tâche du bloc du plan ; au-dessus, ce qui
    # passe devant (une envie pressante, servir un client, ranger les courses).
    # On exécute toujours la tâche du SOMMET. C'est le principe de la pile
    # d'appels d'un programme : on traite l'interruption, puis on reprend.
    tasks: list[Task] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)
    # Bloc dont la tâche est finie (on n'y revient pas) et compteurs de repli.
    completed_block: PlanBlock | None = None
    fallbacks: int = 0
    urgent_retry: dict[NeedKind, int] = field(default_factory=dict)

    # --- Déplacement : on avance dans un chemin IMMUABLE grâce à un index ---------------
    path: tuple[TilePos, ...] = ()
    path_index: int = 0
    progress: float = 0.0
    retry_minute: int = 0

    # Statistiques : minutes passées par recette (tableau de bord, étape 5).
    minutes_by_recipe: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.profile.id

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def first_name(self) -> str:
        return self.profile.name.split()[0]

    @property
    def work_place_id(self) -> str | None:
        return self.profile.work.place if self.profile.work else None

    @property
    def task(self) -> Task | None:
        """La tâche en cours d'exécution (sommet de la pile)."""
        return self.tasks[-1] if self.tasks else None

    @property
    def block_task(self) -> Task | None:
        """La tâche du bloc du plan (bas de la pile)."""
        return self.tasks[0] if self.tasks and self.tasks[0].block is not None else None

    @property
    def is_moving(self) -> bool:
        return bool(self.path) and self.path_index < len(self.path) - 1

    def current_block(self) -> PlanBlock | None:
        if self.plan is None or not 0 <= self.block_index < len(self.plan.blocks):
            return None
        return self.plan.blocks[self.block_index]

    def next_block(self) -> PlanBlock | None:
        if self.plan is None or self.block_index + 1 >= len(self.plan.blocks):
            return None
        return self.plan.blocks[self.block_index + 1]

    def carries(self, item: str, quantity: int = 1) -> bool:
        return self.inventory.get(item, 0) >= quantity

    def give(self, item: str, quantity: int = 1) -> None:
        self.inventory[item] = self.inventory.get(item, 0) + quantity

    def remove(self, item: str, quantity: int = 1) -> bool:
        have = self.inventory.get(item, 0)
        if have < quantity:
            return False
        if have == quantity:
            del self.inventory[item]
        else:
            self.inventory[item] = have - quantity
        return True

    def status_text(self) -> str:
        """Phrase courte pour l'interface : « cuisine », « en route : déjeuner »."""
        task = self.task
        if task is None:
            return "ne fait rien de particulier"
        return task.status_text()
