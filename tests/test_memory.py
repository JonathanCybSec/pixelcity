"""Étape 5 : mémoire (flux, récupération, réflexion) et rendez-vous."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.config.loader import GameConfig
from pixelcity.llm.prompts import build_user_prompt, parse_result, schema_for
from pixelcity.llm.types import ConversationKind, ConversationRequest, Persona
from pixelcity.memory.stream import MemoryKind, MemoryStream, keywords
from pixelcity.sim.appointments import Appointments, parse_hour
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation

from .helpers import events_of

HOUR = 360  # ticks par heure


def test_mots_cles_sans_accents_ni_mots_vides() -> None:
    assert keywords("J'ai discuté avec Léa au café") == {"discute", "cafe"}


def test_la_recuperation_privilegie_la_personne_concernee() -> None:
    stream = MemoryStream(HOUR)
    stream.add(0, MemoryKind.OBSERVATION, "Le pain était délicieux", 3)
    about_lea = stream.add(
        HOUR, MemoryKind.CONVERSATION, "J'ai parlé de vacances", 3, about=("lea",)
    )
    stream.add(2 * HOUR, MemoryKind.OBSERVATION, "Il pleuvait sur le parc", 3)
    found = stream.retrieve(3 * HOUR, about=("lea",), count=1)
    assert found == [about_lea]
    assert about_lea.last_access == 3 * HOUR  # se souvenir ravive le souvenir


def test_l_importance_compte() -> None:
    stream = MemoryStream(HOUR)
    stream.add(0, MemoryKind.OBSERVATION, "banal", 1)
    big = stream.add(0, MemoryKind.OBSERVATION, "marquant", 9)
    assert stream.retrieve(HOUR, count=1) == [big]


def test_on_oublie_le_moins_utile_mais_jamais_une_reflexion() -> None:
    stream = MemoryStream(HOUR, capacity=3)
    thought = stream.add(0, MemoryKind.REFLECTION, "Je tiens à mes amis", 7)
    stream.add(0, MemoryKind.OBSERVATION, "anecdote", 1)
    stream.add(HOUR, MemoryKind.OBSERVATION, "autre chose", 5)
    stream.add(2 * HOUR, MemoryKind.OBSERVATION, "dernière chose", 5)
    assert len(stream) == 3
    assert thought in stream.memories
    assert all(m.text != "anecdote" for m in stream.memories)


def test_un_rendez_vous_evite_les_heures_de_travail(config: GameConfig) -> None:
    sim = Simulation(config)
    marcel = sim.agents["marcel"].profile  # boulanger, 05:00-13:00 du lundi au samedi
    lea = sim.agents["lea"].profile  # bureau 09:00-17:30 en semaine
    cafe = sim.world.places["cafe"]
    book = Appointments()
    tuesday = 1
    # Léa travaille jusqu'à 17:30 : rien n'est possible avant 18:00 un mardi.
    start = book.feasible_start(marcel, lea, cafe, tuesday, parse_hour("15:00"))
    assert start is None or start >= 18 * 60
    sunday = 6
    park = sim.world.places["parc"]
    assert book.feasible_start(marcel, lea, park, sunday, parse_hour("16:30")) == 16 * 60 + 30
    assert parse_hour("bientôt") is None


def _persona(pid: str) -> Persona:
    return Persona(pid, pid.title(), 30, "Testeur", "bavard", (), "", "", "flâne", None, None)


def test_le_rendez_vous_propose_par_le_llm_est_verifie() -> None:
    req = ConversationRequest(
        kind=ConversationKind.STREET,
        a=_persona("lea"),
        b=_persona("hugo"),
        place="Parc",
        hour="16:00",
        relation="sympathie",
        memory=None,
        flirt_allowed=False,
        memories_a=("lundi 12:00 — J'ai discuté avec Hugo : il aime le jazz",),
        meet_places=(("cafe", "Café des Arts"),),
    )
    prompt = build_user_prompt(req)
    assert "il aime le jazz" in prompt and "DEMAIN" in prompt
    assert schema_for(req)["properties"]["meet"]["properties"]["place"]["enum"] == ["cafe"]
    lines = [
        {"speaker": "lea", "text": "On se voit demain ?"},
        {"speaker": "hugo", "text": "Oui !"},
    ]
    ok = parse_result(
        req, {"lines": lines, "meet": {"agreed": True, "place": "cafe", "hour": "17:30"}}, "t"
    )
    assert ok.meet is not None and ok.meet.place_id == "cafe"
    bad = parse_result(
        req, {"lines": lines, "meet": {"agreed": True, "place": "mairie", "hour": "9"}}, "t"
    )
    assert bad.meet is None  # lieu inventé : refusé


def test_une_semaine_de_souvenirs_de_pensees_et_de_rendez_vous(
    make_sim: Callable[..., Simulation],
) -> None:
    sim = make_sim()
    sim.run_days(8.8)
    for agent in sim.agents.values():
        kinds = {m.kind for m in agent.memory.memories}
        assert MemoryKind.CONVERSATION in kinds, agent.id
    assert events_of(sim, EventKind.REFLECTION)
    booked = events_of(sim, EventKind.APPOINTMENT_SET)
    kept = events_of(sim, EventKind.APPOINTMENT_KEPT)
    assert booked and kept  # Hugo et Paul, dimanche → lundi 17:30 au parc
    plan = sim.agents[str(kept[0].agent_id)].memory.recent(50, (MemoryKind.PLAN,))
    assert plan and "Rendez-vous" in plan[0].text
