"""Le flux de souvenirs d'un habitant, et la récupération des plus utiles.

Score d'un souvenir (comme dans Generative Agents) :

    score = récence + importance + pertinence      (chacun ramené entre 0 et 1)

- récence : décroît exponentiellement depuis le dernier RAPPEL du souvenir
  (×0,99 par heure simulée). Se souvenir d'une chose la ravive : c'est
  l'effet de « répétition espacée » bien connu en apprentissage ;
- importance : de 1 (banal) à 10 (marquant), fixée à l'écriture ;
- pertinence : le souvenir concerne-t-il la personne à qui l'on parle, le
  lieu où l'on est, les mots de la situation ?

Le papier mesure la pertinence avec des « embeddings » (des vecteurs qui
représentent le sens d'un texte). On utilise ici des mots-clés et les
personnes concernées : pas de second modèle à installer, un calcul
instantané et reproductible. Les embeddings d'Ollama (`/api/embed`) pourront
remplacer `_relevance` plus tard sans rien changer d'autre.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

RECENCY_DECAY_PER_HOUR = 0.99
DEFAULT_CAPACITY = 300

_STOPWORDS = frozenset(
    [
        "avec",
        "dans",
        "pour",
        "sont",
        "mais",
        "elle",
        "elles",
        "leur",
        "leurs",
        "nous",
        "vous",
        "avait",
        "avoir",
        "etre",
        "etait",
        "cette",
        "ceci",
        "cela",
        "plus",
        "tres",
        "bien",
        "tout",
        "tous",
        "toute",
        "toutes",
        "comme",
        "quand",
        "alors",
        "aussi",
        "encore",
        "deja",
        "sous",
        "chez",
        "entre",
        "faire",
        "fait",
        "vers",
        "apres",
        "avant",
        "depuis",
        "jour",
        "journee",
    ]
)
_WORD = re.compile(r"[a-z]{4,}")


class MemoryKind(StrEnum):
    OBSERVATION = "observation"  # ce qu'il a vu ou vécu
    CONVERSATION = "conversation"  # le résumé d'une discussion
    PLAN = "plan"  # un rendez-vous pris
    REFLECTION = "reflection"  # une idée tirée de ses souvenirs


def keywords(text: str) -> frozenset[str]:
    ascii_text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return frozenset(w for w in _WORD.findall(ascii_text) if w not in _STOPWORDS)


@dataclass(slots=True, eq=False)
class Memory:
    uid: int
    tick: int
    kind: MemoryKind
    text: str
    importance: int  # 1 à 10
    about: tuple[str, ...] = ()  # habitants concernés
    place_id: str | None = None
    last_access: int = 0
    words: frozenset[str] = field(default_factory=frozenset)


class MemoryStream:
    def __init__(self, ticks_per_hour: int, capacity: int = DEFAULT_CAPACITY) -> None:
        self.ticks_per_hour = ticks_per_hour
        self.capacity = capacity
        self.memories: list[Memory] = []
        self._next_uid = 1
        self.importance_since_reflection = 0
        self.last_reflection_tick = 0

    def __len__(self) -> int:
        return len(self.memories)

    def add(
        self,
        tick: int,
        kind: MemoryKind,
        text: str,
        importance: int,
        *,
        about: Iterable[str] = (),
        place_id: str | None = None,
    ) -> Memory:
        importance = max(1, min(10, importance))
        memory = Memory(
            self._next_uid,
            tick,
            kind,
            text,
            importance,
            tuple(about),
            place_id,
            tick,
            keywords(text),
        )
        self._next_uid += 1
        self.memories.append(memory)
        if kind is not MemoryKind.REFLECTION:
            self.importance_since_reflection += importance
        if len(self.memories) > self.capacity:
            self._forget(tick)
        return memory

    def _forget(self, now: int) -> None:
        """On oublie le souvenir le moins utile (jamais une réflexion, ni un plan à venir)."""
        candidates = [
            m for m in self.memories if m.kind not in (MemoryKind.REFLECTION, MemoryKind.PLAN)
        ]
        if not candidates:
            candidates = self.memories
        weakest = min(candidates, key=lambda m: (m.importance / 10 + self._recency(m, now), m.uid))
        self.memories.remove(weakest)

    def _recency(self, memory: Memory, now: int) -> float:
        hours = max(0.0, (now - memory.last_access) / self.ticks_per_hour)
        return float(RECENCY_DECAY_PER_HOUR**hours)

    def recent(self, count: int, kinds: Iterable[MemoryKind] | None = None) -> list[Memory]:
        wanted = set(kinds) if kinds is not None else None
        found = [m for m in reversed(self.memories) if wanted is None or m.kind in wanted]
        return found[:count]

    def since(self, tick: int) -> list[Memory]:
        return [m for m in self.memories if m.tick >= tick]

    def retrieve(
        self,
        now: int,
        *,
        query: str = "",
        about: Iterable[str] = (),
        place_id: str | None = None,
        count: int = 4,
        touch: bool = True,
    ) -> list[Memory]:
        """Les `count` souvenirs les plus utiles pour la situation décrite."""
        if not self.memories:
            return []
        words = keywords(query)
        people = set(about)
        memories = self.memories
        recency = _minmax([self._recency(m, now) for m in memories])
        importance = _minmax([m.importance / 10 for m in memories])
        relevance = _minmax([_relevance(m, words, people, place_id) for m in memories])
        # Normalisation min-max : chaque critère pèse autant, quelle que soit son échelle.
        scored = sorted(
            ((recency[i] + importance[i] + relevance[i], m.uid, m) for i, m in enumerate(memories)),
            key=lambda row: (row[0], row[1]),
            reverse=True,
        )
        chosen = [memory for _score, _uid, memory in scored[:count]]
        if touch:
            for memory in chosen:
                memory.last_access = now
        return chosen


def _relevance(
    memory: Memory, words: frozenset[str], people: set[str], place_id: str | None
) -> float:
    score = 0.0
    if people and people.intersection(memory.about):
        score += 1.0
    if place_id is not None and memory.place_id == place_id:
        score += 0.3
    if words and memory.words:
        score += len(words & memory.words) / math.sqrt(len(words) * len(memory.words))
    return score


def _minmax(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [0.0 for _ in values]
    return [(v - low) / (high - low) for v in values]
