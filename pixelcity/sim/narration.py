"""Traduit les événements en phrases lisibles (journal du mode headless et de l'interface)."""

from __future__ import annotations

from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.types import NeedKind, Weekday

_REASONS = {"closed": "fermé", "full": "complet", "forbidden": "non accessible"}
_ITEMS = {
    "bread": "un sandwich",
    "coffee": "un café",
    "meal": "le plat du jour",
    "groceries": "ses courses",
}

_STAGE_TEXT = {
    "froid": "le courant ne passe pas",
    "connaissance": "de simples connaissances",
    "sympathie": "une vraie sympathie",
    "amitié": "deviennent amis",
    "grande amitié": "une grande amitié",
}

# Événements « de détail » : utiles au débogage, trop bavards pour le journal.
VERBOSE_KINDS = frozenset({EventKind.PLAN_CREATED, EventKind.TASK_STARTED, EventKind.QUEUE_JOINED})


def describe(event: Event, agent_names: dict[str, str], place_names: dict[str, str]) -> str:
    who = _first(agent_names.get(event.agent_id or "", event.agent_id or "?"))
    where = place_names.get(event.place_id or "", event.place_id or "?")
    data = event.data
    match event.kind:
        case EventKind.SIM_STARTED:
            return f"Simulation lancée (graine {data.get('seed')}, {data.get('agents')} habitants)"
        case EventKind.DAY_STARTED:
            weekday = Weekday(str(data.get("weekday", "mon")))
            # Tirets cadratins plutôt que « ─ » (U+2500) : la police Inter ne
            # contient pas les caractères de dessin de boîte, ils s'afficheraient en « tofu ».
            return f"——— {weekday.label}, jour {data.get('day')} ———"
        case EventKind.PLAN_CREATED:
            return f"{who} planifie sa journée ({data.get('blocks')} moments)"
        case EventKind.DEPARTED:
            return f"{who} part vers {where} ({data.get('label')})"
        case EventKind.ARRIVED:
            return f"{who} arrive à {where}"
        case EventKind.TASK_STARTED:
            return f"{who} : {data.get('label')}"
        case EventKind.STEP_STARTED:
            return f"{who} {data.get('label')}"
        case EventKind.TASK_DONE:
            return f"{who} a fini : {data.get('label')}"
        case EventKind.TASK_FAILED:
            return f"{who} renonce à « {data.get('label')} » ({data.get('reason')})"
        case EventKind.NEED_CRITICAL:
            need = NeedKind(str(data.get("need")))
            return f"{who} : {need.label.lower()} critique ({data.get('value')}/100) → {where}"
        case EventKind.NEED_RECOVERED:
            need = NeedKind(str(data.get("need")))
            return f"{who} : {need.label.lower()} revenue à {data.get('value')}/100"
        case EventKind.PLACE_CLOSED:
            reason = _REASONS.get(str(data.get("reason")), str(data.get("reason")))
            suite = ", attend l'ouverture" if data.get("waiting") else ", fait demi-tour"
            return f"{who} trouve {where} {reason}{suite}"
        case EventKind.PATH_NOT_FOUND:
            return f"{who} ne trouve aucun chemin vers {where}"
        case EventKind.QUEUE_JOINED:
            position = int(str(data.get("position", 0)))
            rank = "au comptoir" if position == 0 else f"{position + 1}e dans la file"
            return f"{who} fait la queue ({rank})"
        case EventKind.SERVICE_STARTED:
            staff = data.get("staff")
            if staff is None:
                return f"{who} passe à la caisse automatique"
            return f"{_first(agent_names.get(str(staff), str(staff)))} sert {who}"
        case EventKind.SERVICE_DONE:
            item = _ITEMS.get(str(data.get("item")), str(data.get("item")))
            if data.get("ok"):
                return f"{who} repart avec {item}"
            return f"{who} repart sans {item}"
        case EventKind.STOCK_EMPTY:
            item = _ITEMS.get(str(data.get("item")), str(data.get("item")))
            return f"{where} : plus de stock ({item})"
        case EventKind.SAY:
            return f"{who} : « {data.get('text')} »"
        case EventKind.RELATION:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            stage = str(data.get("stage"))
            if not data.get("before"):
                return f"{who} et {other} font connaissance"
            return f"{who} et {other} : {_STAGE_TEXT.get(stage, stage)}"
        case EventKind.BUS_BOARDED:
            stop, to = data.get("stop"), data.get("to")
            return f"{who} monte dans le bus n°{data.get('bus')} à « {stop} » (→ {to})"
        case EventKind.BUS_ALIGHTED:
            return f"{who} descend du bus à « {data.get('stop')} »"
        case EventKind.MONEY_LOW:
            return f"{who} est presque à sec ({data.get('money')} €)"
        case EventKind.REFLECTION:
            return f"{who} pense : « {data.get('text')} »"
        case EventKind.APPOINTMENT_SET:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"{who} et {other} se donnent rendez-vous {data.get('when')} ({where})"
        case EventKind.APPOINTMENT_KEPT:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"{who} et {other} se retrouvent comme prévu ({where})"
        case EventKind.APPOINTMENT_MISSED:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"Rendez-vous manqué entre {who} et {other} ({where})"
        case EventKind.FLIRT:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"{who} et {other} se font les yeux doux"
        case EventKind.CHAT_STARTED:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"{who} discute avec {other}"
        case EventKind.CHAT_DONE:
            other = _first(agent_names.get(str(data.get("other")), str(data.get("other"))))
            return f"{who} et {other} se quittent"
    return f"{event.kind.value} {event.data}"


def _first(name: str) -> str:
    """Le prénom suffit dans un journal : « Marcel » plutôt que « Marcel Dupont »."""
    return name.split()[0] if name else name
