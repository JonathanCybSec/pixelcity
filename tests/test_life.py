"""Étape 6 bis : la vraie vie (décisions, dettes, expulsion, travail, vol, manche)."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.config.loader import GameConfig
from pixelcity.llm.prompts import intention_schema, parse_intentions
from pixelcity.llm.types import IntentionRequest, Intentions, Option, Persona
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind
from pixelcity.studio import scenario as sc

from .helpers import events_of, run_to

MONDAY = 0


def _persona() -> Persona:
    return Persona(
        "noah", "Noah N", 23, "Étudiant", "réservé", (), "", "", "flâne", "fauché", None, None
    )


def test_les_intentions_de_l_ia_sont_filtrees() -> None:
    req = IntentionRequest(
        _persona(),
        (),
        "mardi",
        "Bureaux, 09:00-17:30, 15 €/h",
        (Option("phone", "téléphone (420 €)"),),
        (Option("beg", "faire la manche"), Option("park", "parc")),
    )
    schema = intention_schema(req)
    assert schema["properties"]["activities"]["items"]["enum"] == ["beg", "park"]
    got = parse_intentions(
        req,
        {
            "work": False,
            "purchases": ["phone", "yacht"],
            "activities": ["voler_banque", "beg"],
            "thought": "Pas envie d'y aller.",
        },
        "test",
    )
    assert got == Intentions(False, ("phone",), ("beg",), "Pas envie d'y aller.", "test")


def _broke_scenario(config: GameConfig, money: float = -200.0) -> Simulation:
    scenario = sc.default_scenario(config)
    scenario.agents.append(
        sc.AgentDraft(name="Noah Nguyen", age=23, job="sans_emploi", home="mimosas_1", money=money)
    )
    return Simulation(sc.apply(scenario, config))


def test_trois_nuits_de_dette_et_c_est_l_expulsion(config: GameConfig) -> None:
    sim = _broke_scenario(config)
    noah = sim.agents["noah_nguyen"]
    run_to(sim, MONDAY + 3, 9.0)  # trois nuits à découvert, l'huissier passe à 08:00
    assert events_of(sim, EventKind.EVICTED, "noah_nguyen")
    assert noah.homeless and noah.home == "parc"
    assert any("expulsé" in m.text for m in noah.memory.memories)
    run_to(sim, MONDAY + 4, 3.0)
    assert noah.plan is not None and noah.plan.blocks[0].recipe == "sleep_rough"
    assert noah.place_id == "parc"


def test_trois_absences_et_c_est_le_licenciement(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    lea.intentions[0] = Intentions(work=False, thought="Pas envie.")
    rules = sim.life.rule_intentions
    # Les soirs suivants, son « IA » (ici les règles, forcées) refuse encore d'y aller.
    sim.life.rule_intentions = lambda ctx, agent: (  # type: ignore[method-assign]
        Intentions(work=False, thought="Pas envie.") if agent is lea else rules(ctx, agent)
    )
    run_to(sim, MONDAY + 3, 0.5)
    assert events_of(sim, EventKind.FIRED, "lea")
    assert lea.profile.work is None and lea.profile.wage == 0
    assert lea.profile.allowance > 0  # le chômage


def test_chercher_un_emploi_peut_aboutir(config: GameConfig) -> None:
    sim = _broke_scenario(config, money=50)
    noah = sim.agents["noah_nguyen"]
    for _ in range(30):
        sim.life._job_search(sim.ctx, noah)
        if noah.profile.work is not None:
            break
    assert noah.profile.work is not None and noah.profile.wage > 0
    assert events_of(sim, EventKind.HIRED, "noah_nguyen")


def test_voler_sous_les_yeux_du_personnel(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 11.0)  # Sofia tient la caisse du supermarché
    thief = sim.agents["hugo"]
    sofia = sim.agents["sofia"]
    assert sofia.place_id == "supermarche"
    thief.place_id = "supermarche"
    for _ in range(20):
        sim.life._steal(sim.ctx, thief, "supermarche", "snack")
        if "supermarche" in thief.banned:
            break
    assert "supermarche" in thief.banned
    assert any("voler" in m.text for m in sofia.memory.memories)
    relation = sim.relations.get("hugo", "sofia")
    assert relation is not None and relation.affinity < 0
    thefts = events_of(sim, EventKind.THEFT, "hugo")
    assert thefts[-1].data["caught"] is True


def test_faim_sans_le_sou_l_habitant_decide(config: GameConfig) -> None:
    sim = _broke_scenario(config, money=0)
    noah = sim.agents["noah_nguyen"]
    run_to(sim, MONDAY, 10.0)
    noah.needs.values[NeedKind.HUNGER] = 5.0
    noah.money = 0.0
    fridge = sim.world.places["mimosas_1"].container_with("provisions")
    assert fridge is not None
    fridge.take("provisions", fridge.count("provisions"))
    sim.run_ticks(sim.clock.ticks_per_minute * 20)
    assert events_of(sim, EventKind.DECISION, "noah_nguyen")
    assert any(t.recipe_id in ("beg", "steal_food", "rest_hungry") for t in noah.tasks)


def test_l_argent_vient_de_quelqu_un(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    sim.run_days(2)
    flows = sim.economy.flows
    assert flows[("Bureaux Horizon", "habitants")] > 0  # le salaire de Léa
    assert flows[("habitants", "le bailleur")] > 0  # les loyers
    assert flows[("l'État", "habitants")] > 0  # la retraite de Paul
    assert flows[("la clientèle extérieure", "Boulangerie du Coin")] > 0
    assert sim.economy.accounts["boulangerie"] > 0
