"""Étape 6 : l'argent (salaires, loyers, achats) et le bus."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.config.loader import GameConfig
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.transit import STOPS, Transit
from pixelcity.studio import scenario as sc

from .helpers import events_of, run_to

MONDAY = 0


def test_le_salaire_tombe_pendant_le_travail(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    start = lea.money
    run_to(sim, MONDAY, 9.0)
    morning = lea.money
    run_to(sim, MONDAY, 12.0)
    assert lea.money > morning  # trois heures au bureau, payées 18 €/h
    assert lea.income >= 18 * 2.5
    assert start != 0


def test_loyer_et_retraite_a_minuit(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    paul = sim.agents["paul"]
    run_to(sim, MONDAY, 23.9)
    before_income, before_expenses = paul.income, paul.expenses
    run_to(sim, MONDAY + 1, 0.05)
    assert paul.income - before_income == 55  # retraite
    assert paul.expenses - before_expenses >= 28  # loyer de la maison


def test_les_commerces_encaissent(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    sim.run_days(2)
    assert sim.economy.revenue["cafe"] > 0
    assert sum(sim.economy.sales.values()) >= 5


def test_sans_argent_pas_de_vente(config: GameConfig) -> None:
    scenario = sc.default_scenario(config)
    for draft in scenario.agents:
        if draft.name.startswith(("Léa", "Hugo", "Sofia", "Karim")):
            draft.money = 0.0  # fauchés avant la paie
    sim = Simulation(sc.apply(scenario, config))
    run_to(sim, MONDAY, 13.5)
    refused = [e for e in events_of(sim, EventKind.SERVICE_DONE) if e.data.get("reason") == "money"]
    broke = events_of(sim, EventKind.MONEY_LOW)
    assert {str(e.agent_id) for e in broke} >= {"lea_martin", "hugo_lambert"}
    assert any("à sec" in m.text for m in sim.agents["lea_martin"].memory.memories)
    # Un client fauché qui se présente au comptoir repart sans rien.
    for event in refused:
        assert not sim.agents[str(event.agent_id)].carries(str(event.data["item"]))


def test_le_bus_tourne_et_transporte(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    transit: Transit = sim.transit
    assert transit.enabled and len(transit.buses) == 3
    sim.run_days(1)
    boarded = events_of(sim, EventKind.BUS_BOARDED)
    alighted = events_of(sim, EventKind.BUS_ALIGHTED)
    assert boarded and alighted
    assert transit.trips == len(boarded)
    assert sim.economy.transit_revenue == transit.trips * 1.5
    # Personne n'est resté coincé dans un bus.
    on_board = {pid for bus in transit.buses for pid in bus.passengers}
    assert all(sim.agents[pid].bus is not None for pid in on_board)
    stop_names = {name for _x, name in STOPS}
    assert {str(e.data["stop"]) for e in alighted} <= stop_names


def test_on_marche_quand_c_est_tout_pres(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    entrance = sim.world.places["appart_1"].entrances[0]
    ride = sim.transit.plan(lea, entrance, 10, 4.0, lea.money)
    assert ride is None
