"""Ce que l'interface retient des événements : le journal et les bulles de dialogue.

L'interface S'ABONNE au journal d'événements de la simulation (patron
Observateur) : la simulation ne sait pas qu'une interface existe.

Piège de l'échelle de temps : à x30, une réplique prononcée dure 2 secondes
SIMULÉES, soit 0,07 seconde réelle. Illisible ! Les bulles se mesurent donc
en temps RÉEL : chacune reste affichée ~3 secondes à l'écran, quelle que soit
la vitesse de la simulation.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from pixelcity.sim.clock import format_absolute_minute
from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.narration import VERBOSE_KINDS, describe
from pixelcity.sim.simulation import Simulation

BUBBLE_SECONDS = 3.2
BUBBLE_SECONDS_PER_CHAR = 0.03
JOURNAL_SIZE = 300
# Événements trop fréquents ou trop techniques pour le journal de l'interface.
THINKING = "…"
THINKING_SECONDS = 30.0
HIDDEN_KINDS = VERBOSE_KINDS | {EventKind.SIM_STARTED, EventKind.CHAT_THINKING}


@dataclass(frozen=True, slots=True)
class Bubble:
    text: str
    born: float  # temps réel (time.monotonic)
    to: str | None

    def age(self, now: float) -> float:
        return now - self.born

    @property
    def lifetime(self) -> float:
        if self.text == THINKING:
            return THINKING_SECONDS  # remplacée par la première réplique dès qu'elle arrive
        return BUBBLE_SECONDS + BUBBLE_SECONDS_PER_CHAR * len(self.text)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    stamp: str
    text: str
    kind: EventKind
    agent_id: str | None
    involved: frozenset[str]


class Feed:
    def __init__(self, sim: Simulation) -> None:
        self._agent_names = sim.agent_names()
        self._place_names = sim.place_names()
        self._tick_seconds = sim.clock.tick_seconds
        self.bubbles: dict[str, Bubble] = {}
        self.journal: deque[JournalEntry] = deque(maxlen=JOURNAL_SIZE)
        # Les événements passés vont au journal, mais pas en bulles : une
        # réplique d'il y a trois heures n'a rien à faire au-dessus d'une tête.
        for event in list(sim.events):
            self._on_event(event, live=False)
        sim.events.subscribe(self._on_event)

    def _on_event(self, event: Event, *, live: bool = True) -> None:
        if live and event.kind is EventKind.CHAT_THINKING and event.agent_id is not None:
            self.bubbles[event.agent_id] = Bubble(THINKING, time.monotonic(), None)
        if live and event.kind is EventKind.SAY and event.agent_id is not None:
            to = event.data.get("to")
            self.bubbles[event.agent_id] = Bubble(
                str(event.data.get("text", "")), time.monotonic(), str(to) if to else None
            )
        if event.kind in HIDDEN_KINDS:
            return
        involved = {event.agent_id} if event.agent_id else set()
        for key in ("staff", "to"):
            value = event.data.get(key)
            if isinstance(value, str):
                involved.add(value)
        stamp = format_absolute_minute(event.tick * self._tick_seconds // 60)[4:]
        self.journal.append(
            JournalEntry(
                stamp,
                describe(event, self._agent_names, self._place_names),
                event.kind,
                event.agent_id,
                frozenset(involved),
            )
        )

    def live_bubbles(self) -> dict[str, tuple[Bubble, float]]:
        """Bulles encore visibles, avec leur opacité (fondu à la fin)."""
        now = time.monotonic()
        alive: dict[str, tuple[Bubble, float]] = {}
        for agent_id, bubble in list(self.bubbles.items()):
            age = bubble.age(now)
            if age > bubble.lifetime:
                del self.bubbles[agent_id]
                continue
            fade = min(1.0, (bubble.lifetime - age) / 0.4, age / 0.12)
            alive[agent_id] = (bubble, max(0.0, fade))
        return alive

    def entries(self, mode: str, agent_id: str | None, limit: int) -> list[JournalEntry]:
        result: list[JournalEntry] = []
        for entry in reversed(self.journal):
            if mode == "talk" and entry.kind is not EventKind.SAY:
                continue
            if mode == "agent" and (agent_id is None or agent_id not in entry.involved):
                continue
            if mode == "all" and entry.kind is EventKind.STEP_STARTED:
                # « Tout » reste lisible : les gestes détaillés vont dans le filtre habitant.
                continue
            result.append(entry)
            if len(result) >= limit:
                break
        result.reverse()
        return result
