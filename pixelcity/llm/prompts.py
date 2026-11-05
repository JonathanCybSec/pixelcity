"""Construction des prompts et validation des réponses du LLM.

Règle d'or : le LLM PROPOSE, la simulation DISPOSE. Il écrit les répliques
et suggère un effet sur la relation, mais :
- il ne décide pas si l'article est en stock (on le lui dit) ;
- sa variation d'affinité est bornée ;
- un flirt n'est retenu que si la simulation l'a autorisé (deux adultes,
  ouverts à la romance, sans autre partenaire, qui s'apprécient déjà).
Tout ce qui sort du modèle est donc vérifié, comme une entrée utilisateur
sur un site web : on ne fait jamais confiance à ce qui vient de l'extérieur.
"""

from __future__ import annotations

import re
from typing import Any

from pixelcity.llm.types import (
    ChatLine,
    ConversationKind,
    ConversationRequest,
    ConversationResult,
    MeetProposal,
    Persona,
    ReflectionRequest,
)

MAX_LINES = 6
MIN_LINES = 2
MAX_LINE_CHARS = 110
MAX_DELTA = 6.0

ITEM_NAMES = {
    "bread": "un sandwich ou du pain",
    "coffee": "un café",
    "meal": "un repas",
    "groceries": "ses courses",
}

MAX_INSIGHTS = 3
MAX_INSIGHT_CHARS = 140

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
            },
        },
        "affinity_delta": {"type": "number"},
        "flirt": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["lines", "affinity_delta", "flirt", "summary"],
}


def schema_for(req: ConversationRequest) -> dict[str, Any]:
    """Le schéma JSON imposé au modèle ; avec un rendez-vous possible, la liste des lieux."""
    if not req.meet_places:
        return SCHEMA
    schema = {**SCHEMA, "properties": dict(SCHEMA["properties"])}
    schema["properties"]["meet"] = {
        "type": "object",
        "properties": {
            "agreed": {"type": "boolean"},
            "place": {"type": "string", "enum": [pid for pid, _ in req.meet_places]},
            "hour": {"type": "string"},
        },
        "required": ["agreed", "place", "hour"],
    }
    return schema


REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"insights": {"type": "array", "items": {"type": "string"}}},
    "required": ["insights"],
}

REFLECTION_SYSTEM = (
    "Tu es la petite voix intérieure d'un habitant d'une simulation de vie. À partir de "
    "ses souvenirs, tu écris ce qu'il en retient, à la première personne, en français. "
    "Réponds uniquement avec le JSON demandé."
)

SYSTEM = (
    "Tu écris les dialogues d'une simulation de vie en pixel art, dans une petite ville "
    "française. Les répliques s'affichent dans des bulles : elles sont COURTES (moins de "
    "15 mots), naturelles, en français familier mais correct, sans didascalies ni emojis. "
    "Chaque habitant parle selon son caractère, son métier et sa façon de parler, et peut "
    "évoquer ce qu'il fait ou ce dont il a besoin. Réponds uniquement avec le JSON demandé."
)


def _persona_text(p: Persona) -> str:
    parts = [f"- {p.name} (id « {p.id} »), {p.age} ans, {p.job}. Caractère : {p.traits}."]
    if p.values:
        parts.append(f"  Tient à : {', '.join(p.values)}.")
    if p.ideology:
        parts.append(f"  Convictions : {p.ideology} (elles colorent ses propos, sans sermon).")
    if p.speech_style:
        parts.append(f"  Façon de parler : {p.speech_style}.")
    parts.append(f"  En ce moment : {p.doing}. Finances : {p.finances}.")
    if p.need:
        parts.append(f"  Besoin pressant : {p.need}.")
    return "\n".join(parts)


def build_user_prompt(req: ConversationRequest) -> str:
    a, b = req.a, req.b
    lines = [
        f"Lieu : {req.place}, {req.hour}.",
        "Personnages :",
        _persona_text(a),
        _persona_text(b),
    ]
    lines.append(f"Leur relation : {req.relation}.")
    if req.memory:
        lines.append(f"Leur dernière conversation : {req.memory}")
    for persona, memories in ((a, req.memories_a), (b, req.memories_b)):
        if memories:
            lines.append(f"Ce que {persona.name} a en tête :")
            lines.extend(f"  - {memory}" for memory in memories)
    if req.kind is ConversationKind.COUNTER:
        item = ITEM_NAMES.get(req.item or "", req.item or "quelque chose")
        lines.append(f"Situation : {a.name} est client et vient acheter {item} ; {b.name} le sert.")
        if not req.in_stock:
            lines.append(
                "L'article est en RUPTURE de stock : le vendeur doit s'excuser, rien n'est vendu."
            )
        elif not req.can_pay:
            lines.append(
                f"Cela coûte {req.price:.2f} € mais le client n'a PAS assez d'argent : "
                "rien n'est vendu, il repart gêné."
            )
        else:
            lines.append(
                f"L'article est disponible, il coûte {req.price:.2f} € : la vente se fait."
            )
        count = "4"
    else:
        lines.append(
            f"Situation : {a.name} et {b.name} se croisent et s'arrêtent pour discuter un moment."
        )
        count = "4 à 6"
    if req.occasion:
        lines.append(f"Occasion : {req.occasion}.")
    if req.flirt_allowed:
        lines.append(
            "Ils se plaisent un peu : un flirt léger est possible s'il vient naturellement "
            "(compliment, sourire, proposition de se revoir), toujours respectueux et sans rien "
            "d'explicite. Mets flirt à true seulement s'il y en a eu un."
        )
    else:
        lines.append("Pas de flirt ni de drague : flirt vaut false.")
    if req.meet_places:
        places = ", ".join(f"{name} (« {pid} »)" for pid, name in req.meet_places)
        lines.append(
            "S'ils en ont envie, ils peuvent convenir de se revoir DEMAIN entre 14:00 et 18:00 "
            f"dans l'un de ces lieux : {places}. Mets meet.agreed à true seulement si une "
            "réplique le propose et que l'autre accepte, avec le lieu et l'heure (« 17:30 »)."
        )
    lines.append(
        f"Écris {count} répliques en alternant, en commençant par « {a.id} ». "
        f"speaker vaut « {a.id} » ou « {b.id} ». "
        "affinity_delta (de -6 à 6) dit si l'échange les a rapprochés (positif) ou agacés "
        "(négatif). summary résume l'échange en une phrase, pour s'en souvenir plus tard."
    )
    return "\n".join(lines)


_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = _SPACES.sub(" ", text).strip().strip('"«» ')
    if len(text) > MAX_LINE_CHARS:
        cut = text[: MAX_LINE_CHARS - 1].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


def parse_result(req: ConversationRequest, data: dict[str, Any], source: str) -> ConversationResult:
    """Valide la réponse du modèle. Lève ValueError si elle est inutilisable."""
    allowed = {req.a.id, req.b.id}
    names = {req.a.name.lower(): req.a.id, req.b.name.lower(): req.b.id}
    for persona in (req.a, req.b):
        names[persona.name.split()[0].lower()] = persona.id
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list):
        raise ValueError("pas de répliques")
    lines: list[ChatLine] = []
    for item in raw_lines[:MAX_LINES]:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "")).strip()
        speaker = speaker if speaker in allowed else names.get(speaker.lower(), "")
        text = clean_text(str(item.get("text", "")))
        if speaker and text:
            lines.append(ChatLine(speaker, text))
    if len(lines) < MIN_LINES or len({line.speaker for line in lines}) < 2:
        raise ValueError("conversation trop courte ou à une seule voix")
    try:
        delta = float(data.get("affinity_delta", 0.0))
    except (TypeError, ValueError):
        delta = 0.0
    if delta != delta:  # NaN
        delta = 0.0
    delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
    summary = clean_text(str(data.get("summary", "")))[:200] or None
    flirt = bool(data.get("flirt", False)) and req.flirt_allowed
    meet = None
    raw_meet = data.get("meet")
    allowed_places = {pid for pid, _ in req.meet_places}
    if isinstance(raw_meet, dict) and raw_meet.get("agreed") is True:
        place = str(raw_meet.get("place", ""))
        if place in allowed_places:
            hour = raw_meet.get("hour")
            meet = MeetProposal(place, str(hour) if hour else None)
    return ConversationResult(tuple(lines), delta, flirt, summary, source, meet)


def build_reflection_prompt(req: ReflectionRequest) -> str:
    p = req.persona
    lines = [
        _persona_text(p),
        "",
        f"Souvenirs récents de {p.name}, du plus ancien au plus récent :",
    ]
    lines.extend(f"{i}. {memory}" for i, memory in enumerate(req.memories, start=1))
    lines.append(
        f"Écris 1 à {MAX_INSIGHTS} pensées de {p.name}, à la première personne, de moins de 20 "
        "mots chacune, qui GÉNÉRALISENT ces souvenirs : ce qu'il pense des gens qu'il a vus, "
        "ses habitudes, ses envies, ses inquiétudes. Pas de simple résumé d'un souvenir."
    )
    return "\n".join(lines)


def parse_reflection(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("insights")
    if not isinstance(raw, list):
        raise ValueError("pas de pensées")
    insights: list[str] = []
    for item in raw[:MAX_INSIGHTS]:
        text = clean_text(str(item))[:MAX_INSIGHT_CHARS]
        if len(text) >= 8:
            insights.append(text)
    if not insights:
        raise ValueError("pensées vides")
    return tuple(insights)
