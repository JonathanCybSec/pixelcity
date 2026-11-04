"""Traduit les événements en phrases lisibles (journal du mode headless, puis de l'UI)."""

from __future__ import annotations

from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.types import NeedKind, Weekday

_REASONS = {"closed": "fermé", "full": "complet", "forbidden": "non accessible"}


def describe(event: Event, agent_names: dict[str, str], place_names: dict[str, str]) -> str:
    who = agent_names.get(event.agent_id or "", event.agent_id or "?")
    where = place_names.get(event.place_id or "", event.place_id or "?")
    data = event.data
    match event.kind:
        case EventKind.SIM_STARTED:
            return f"Simulation lancée (graine {data.get('seed')}, {data.get('agents')} habitants)"
        case EventKind.DAY_STARTED:
            weekday = Weekday(str(data.get("weekday", "mon")))
            return f"──── {weekday.label}, jour {data.get('day')} ────"
        case EventKind.PLAN_CREATED:
            return f"{who} planifie sa journée ({data.get('blocks')} activités)"
        case EventKind.DEPARTED:
            return f"{who} part vers {where} ({data.get('label')})"
        case EventKind.ARRIVED:
            return f"{who} arrive à {where}"
        case EventKind.ACTIVITY_STARTED:
            return f"{who} : {data.get('label')} ({where})"
        case EventKind.NEED_CRITICAL:
            need = NeedKind(str(data.get("need")))
            return f"{who} : {need.label.lower()} critique ({data.get('value')}/100) → {where}"
        case EventKind.NEED_RECOVERED:
            need = NeedKind(str(data.get("need")))
            return f"{who} : {need.label.lower()} revenue à {data.get('value')}/100"
        case EventKind.PLACE_CLOSED:
            reason = _REASONS.get(str(data.get("reason")), str(data.get("reason")))
            suite = ", attend l'ouverture" if data.get("waiting") else ", cherche ailleurs"
            return f"{who} trouve {where} {reason}{suite}"
        case EventKind.PATH_NOT_FOUND:
            return f"{who} ne trouve aucun chemin vers {where}"
    return f"{event.kind.value} {event.data}"
