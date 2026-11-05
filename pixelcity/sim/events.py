"""Événements structurés : la « mémoire factuelle » de la simulation.

Chaque action notable (départ, arrivée, début d'activité, besoin critique...)
produit un `Event`. Plusieurs consommateurs s'y abonnent sans que le noyau ne
les connaisse (patron Observateur) :

- aujourd'hui : l'affichage du mode headless et le test de déterminisme ;
- plus tard : le journal filtrable de l'interface (étape 5), les logs SQLite
  (étape 7) et les métriques du module Test de produit (étape 6).

Poser ce flux dès l'étape 1 évite d'avoir à « instrumenter » le code après coup.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

# Valeurs autorisées dans `Event.data` : uniquement du JSON simple, pour que
# l'événement soit sérialisable tel quel (export, empreinte, SQLite plus tard).
type EventValue = str | int | float | bool | None


class EventKind(StrEnum):
    SIM_STARTED = "sim_started"
    DAY_STARTED = "day_started"
    PLAN_CREATED = "plan_created"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    # Tâches : une recette commence, chacune de ses étapes, sa fin ou son échec.
    TASK_STARTED = "task_started"
    STEP_STARTED = "step_started"
    TASK_DONE = "task_done"
    TASK_FAILED = "task_failed"
    NEED_CRITICAL = "need_critical"
    NEED_RECOVERED = "need_recovered"
    PLACE_CLOSED = "place_closed"
    PATH_NOT_FOUND = "path_not_found"
    # Commerces : la file, le service, les stocks.
    QUEUE_JOINED = "queue_joined"
    SERVICE_STARTED = "service_started"
    SERVICE_DONE = "service_done"
    STOCK_EMPTY = "stock_empty"
    # Une réplique prononcée (une bulle à l'écran).
    SAY = "say"
    # Deux habitants changent de palier (font connaissance, deviennent amis...).
    RELATION = "relation"


@dataclass(frozen=True, slots=True)
class Event:
    tick: int
    kind: EventKind
    agent_id: str | None = None
    place_id: str | None = None
    data: dict[str, EventValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, EventValue | dict[str, EventValue]]:
        return {
            "tick": self.tick,
            "kind": self.kind.value,
            "agent_id": self.agent_id,
            "place_id": self.place_id,
            "data": dict(self.data),
        }

    def to_json(self) -> str:
        # sort_keys + séparateurs fixes : la même donnée donne toujours la même
        # chaîne, condition pour que l'empreinte du journal soit stable.
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


type EventListener = Callable[[Event], None]


class EventLog:
    """Journal des événements, avec abonnés et empreinte cumulative.

    `max_events` borne la mémoire (file circulaire) pour les longues
    simulations ; l'empreinte, elle, porte sur TOUS les événements émis.
    """

    def __init__(self, max_events: int | None = 50_000) -> None:
        self._events: deque[Event] = deque(maxlen=max_events)
        self._listeners: list[EventListener] = []
        self._hasher = hashlib.sha256()
        self._count = 0

    def subscribe(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def emit(self, event: Event) -> None:
        self._events.append(event)
        self._hasher.update(event.to_json().encode())
        self._hasher.update(b"\n")
        self._count += 1
        for listener in self._listeners:
            listener(event)

    def digest(self) -> str:
        """Empreinte SHA-256 de tout le journal : identique ⇔ simulations identiques."""
        return self._hasher.copy().hexdigest()

    @property
    def total_emitted(self) -> int:
        return self._count

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)
