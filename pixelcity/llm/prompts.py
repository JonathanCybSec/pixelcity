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
    Persona,
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
    parts.append(f"  En ce moment : {p.doing}.")
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
    if req.kind is ConversationKind.COUNTER:
        item = ITEM_NAMES.get(req.item or "", req.item or "quelque chose")
        lines.append(f"Situation : {a.name} est client et vient acheter {item} ; {b.name} le sert.")
        lines.append(
            "L'article est disponible : la vente se fait."
            if req.in_stock
            else "L'article est en RUPTURE de stock : le vendeur doit s'excuser, rien n'est vendu."
        )
        count = "4"
    else:
        lines.append(
            f"Situation : {a.name} et {b.name} se croisent et s'arrêtent pour discuter un moment."
        )
        count = "4 à 6"
    if req.flirt_allowed:
        lines.append(
            "Ils se plaisent un peu : un flirt léger est possible s'il vient naturellement "
            "(compliment, sourire, proposition de se revoir), toujours respectueux et sans rien "
            "d'explicite. Mets flirt à true seulement s'il y en a eu un."
        )
    else:
        lines.append("Pas de flirt ni de drague : flirt vaut false.")
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
    return ConversationResult(tuple(lines), delta, flirt, summary, source)
