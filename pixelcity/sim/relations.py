"""Relations entre habitants : familiarité et affinité, nourries par les rencontres.

Étape 2 : chaque service au comptoir est une rencontre. On se connaît un peu
mieux (familiarité) et l'on s'apprécie plus ou moins selon la compatibilité
des caractères (affinité). À l'étape 3, ce sont les conversations générées
par les LLM qui feront évoluer ces valeurs.

Choix de modèle : l'affinité est SYMÉTRIQUE (une seule valeur par paire).
C'est faux dans la vraie vie (on peut apprécier quelqu'un qui nous ignore),
mais c'est un bon début, lisible et testable. Une relation asymétrique
(deux valeurs par paire) sera facile à introduire plus tard si besoin.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from pixelcity.config.schemas import AgentModel

AFFINITY_MIN, AFFINITY_MAX = -100.0, 100.0
# Paliers, du plus bas au plus haut : (seuil d'affinité, nom du palier).
STAGES: tuple[tuple[float, str], ...] = (
    (-100.0, "froid"),
    (-20.0, "connaissance"),
    (20.0, "sympathie"),
    (45.0, "amitié"),
    (70.0, "grande amitié"),
)


@dataclass(slots=True)
class Relation:
    familiarity: int = 0  # nombre de rencontres
    affinity: float = 0.0
    last_tick: int = 0
    flirts: int = 0
    summary: str | None = None  # souvenir de la dernière conversation (donné au LLM)

    @property
    def stage(self) -> str:
        current = STAGES[0][1]
        for threshold, name in STAGES:
            if self.affinity >= threshold:
                current = name
        return current


def compatibility(a: AgentModel, b: AgentModel) -> float:
    """Entre -1 et 1 : deux caractères vont-ils bien s'entendre ?

    Une heuristique assumée (pas une vérité psychologique) : la gentillesse
    (agréabilité) et la sociabilité (extraversion) aident, les esprits qui se
    ressemblent (ouverture) aussi, l'anxiété (névrosisme) complique tout.
    """
    pa, pb = a.personality, b.personality
    warmth = (pa.agreeableness + pb.agreeableness) / 2
    sociability = (pa.extraversion + pb.extraversion) / 2
    similarity = 1.0 - abs(pa.openness - pb.openness)
    stress = (pa.neuroticism + pb.neuroticism) / 2
    score = 0.9 * warmth + 0.4 * sociability + 0.4 * similarity - 0.7 * stress - 0.75
    return max(-1.0, min(1.0, score * 1.6))


class Relations:
    def __init__(self) -> None:
        self._pairs: dict[tuple[str, str], Relation] = {}

    @staticmethod
    def key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def get(self, a: str, b: str) -> Relation | None:
        return self._pairs.get(self.key(a, b))

    def pairs(self) -> list[tuple[tuple[str, str], Relation]]:
        return sorted(self._pairs.items())

    def of(self, agent_id: str) -> list[tuple[str, Relation]]:
        """Les relations d'un habitant, de la plus forte à la plus faible."""
        found = [
            (b if a == agent_id else a, relation)
            for (a, b), relation in self._pairs.items()
            if agent_id in (a, b)
        ]
        found.sort(key=lambda item: (-item[1].affinity, item[0]))
        return found

    def meet(
        self,
        a: AgentModel,
        b: AgentModel,
        tick: int,
        rng: random.Random,
        *,
        delta: float | None = None,
    ) -> tuple[Relation, str, str]:
        """Une rencontre de plus. Renvoie la relation, et le palier avant / après.

        `delta` : l'effet de la conversation jugé par le LLM (de -6 à 6). Sans
        lui, on l'estime d'après la compatibilité des caractères. Dans les deux
        cas, le caractère compte un peu : un LLM trop enthousiaste ne rend pas
        amis deux habitants que tout oppose.
        """
        key = self.key(a.id, b.id)
        relation = self._pairs.get(key)
        if relation is None:
            relation = self._pairs[key] = Relation()
        before = relation.stage if relation.familiarity else ""
        relation.familiarity += 1
        # Les premières rencontres comptent le plus : l'effet s'atténue ensuite.
        weight = 1.0 / (1.0 + relation.familiarity / 8)
        base = 8.0 * compatibility(a, b) + rng.uniform(-1.5, 1.5)
        raw = base if delta is None else 1.2 * delta + 0.3 * base
        delta = raw * weight
        relation.affinity = max(AFFINITY_MIN, min(AFFINITY_MAX, relation.affinity + delta))
        relation.last_tick = tick
        return relation, before, relation.stage
