"""Les données échangées entre la simulation et les générateurs de conversations.

Tout est figé (`frozen`) : la requête part dans un autre fil d'exécution
pendant que la simulation continue. Si elle contenait des objets vivants
(l'`Agent` lui-même), le fil du LLM lirait un état en train de changer :
une « condition de course ». Une photo immuable supprime le problème.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConversationKind(StrEnum):
    COUNTER = "counter"  # au comptoir : client et vendeur
    STREET = "street"  # une rencontre en ville, au parc, au café


@dataclass(frozen=True, slots=True)
class Persona:
    id: str
    name: str
    age: int
    job: str
    traits: str  # personnalité résumée en mots (« bavard, chaleureux »)
    values: tuple[str, ...]
    speech_style: str
    ideology: str
    doing: str  # ce qu'il est en train de faire
    finances: str  # « fauché », « à l'aise »...
    need: str | None  # son besoin le plus pressant, s'il y en a un
    model: str | None  # modèle LLM propre à cet habitant (None : celui par défaut)


@dataclass(frozen=True, slots=True)
class ConversationRequest:
    kind: ConversationKind
    a: Persona  # celui qui ouvre la conversation (le client, au comptoir)
    b: Persona
    place: str
    hour: str  # « 07:42 »
    relation: str  # « première rencontre », « amitié (12 rencontres) »
    memory: str | None  # résumé de leur dernière conversation
    flirt_allowed: bool
    item: str | None = None  # au comptoir : ce que le client vient acheter
    in_stock: bool = True
    can_pay: bool = True  # le client a-t-il de quoi payer ?
    price: float = 0.0
    seed: int = 0  # pour que le script de repli reste reproductible
    # Étape 5 : les souvenirs que chacun a en tête au moment de parler.
    memories_a: tuple[str, ...] = ()
    memories_b: tuple[str, ...] = ()
    # Lieux où ils peuvent convenir de se revoir demain : (id, nom). Vide : pas de rendez-vous.
    meet_places: tuple[tuple[str, str], ...] = ()
    affinity: float = 0.0
    occasion: str | None = None  # « ils avaient rendez-vous ici »
    # Étape 6 bis : l'un est dans le besoin, l'autre peut l'aider (montant maximal).
    needy: str | None = None
    max_help: float = 0.0


@dataclass(frozen=True, slots=True)
class ChatLine:
    speaker: str  # id de l'habitant
    text: str


@dataclass(frozen=True, slots=True)
class MeetProposal:
    place_id: str
    hour: str | None  # « 17:30 », validé ensuite par la simulation


@dataclass(frozen=True, slots=True)
class ConversationResult:
    lines: tuple[ChatLine, ...]
    affinity_delta: float | None  # None : laisser la simulation l'estimer
    flirt: bool = False
    summary: str | None = None
    source: str = "script"  # « script », ou le nom du modèle
    meet: MeetProposal | None = None
    help: float = 0.0  # euros donnés ou prêtés à celui qui est dans le besoin


@dataclass(frozen=True, slots=True)
class ReflectionRequest:
    """La nuit, un habitant repense à ses souvenirs marquants."""

    persona: Persona
    memories: tuple[str, ...]
    seed: int = 0


@dataclass(frozen=True, slots=True)
class ReflectionResult:
    insights: tuple[str, ...]  # vide : la simulation utilisera ses règles
    source: str = "script"


# --------------------------------------------------------------------------- #
# Étape 6 bis : l'IA décide de la vie de chaque habitant
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Option:
    id: str
    label: str  # ce que l'option veut dire, conséquences comprises


@dataclass(frozen=True, slots=True)
class IntentionRequest:
    """La veille au soir : que vais-je faire demain ?"""

    persona: Persona
    memories: tuple[str, ...]
    day: str  # « mardi »
    work: str | None  # « boulangerie, 05:00-13:00, 14 €/h » ; None : pas de travail prévu
    goods: tuple[Option, ...]  # ce qu'il pourrait s'acheter (prix compris)
    activities: tuple[Option, ...]
    seed: int = 0


@dataclass(frozen=True, slots=True)
class Intentions:
    work: bool = True
    purchases: tuple[str, ...] = ()
    activities: tuple[str, ...] = ()
    thought: str | None = None
    source: str = "règles"


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Un moment critique (faim sans le sou...) : que faire, tout de suite ?"""

    persona: Persona
    memories: tuple[str, ...]
    situation: str
    options: tuple[Option, ...]
    seed: int = 0


@dataclass(frozen=True, slots=True)
class Decision:
    choice: str | None  # None : laisser les règles décider
    thought: str | None = None
    source: str = "règles"
