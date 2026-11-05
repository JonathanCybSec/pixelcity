"""Tests des comptoirs : file, service, répliques, stock, caisse automatique, relations."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pixelcity.agents.movement import place_at
from pixelcity.agents.tasks import Phase, Task, TaskKind
from pixelcity.sim.events import EventKind
from pixelcity.sim.relations import Relations, compatibility
from pixelcity.sim.service import ServiceDesk, update_desks
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import ActivityType

from .helpers import events_of, run_to

MONDAY = 0


def test_la_boulangerie_sert_ses_clients(make_sim: Callable[..., Simulation]) -> None:
    """Lundi midi : Sofia et Léa vont chercher un sandwich, Marcel les sert."""
    sim = make_sim()
    run_to(sim, MONDAY, 13.0)
    services = [e for e in events_of(sim, EventKind.SERVICE_DONE) if e.place_id == "boulangerie"]
    assert services and all(e.data.get("staff") == "marcel" and e.data.get("ok") for e in services)
    customers = {e.agent_id for e in services}
    # Chacun a dit quelque chose, et Marcel a répondu.
    speakers = {e.agent_id for e in events_of(sim, EventKind.SAY) if e.place_id == "boulangerie"}
    assert customers | {"marcel"} <= speakers
    # Et ils se connaissent un peu mieux.
    for customer in customers:
        assert customer is not None
        relation = sim.relations.get(customer, "marcel")
        assert relation is not None and relation.familiarity >= 1


def _desk(sim: Simulation, place_id: str) -> ServiceDesk:
    return next(desk for desk in sim.desks.values() if desk.place_id == place_id)


def _customer_at_counter(sim: Simulation, agent_id: str, desk: ServiceDesk, item: str) -> Task:
    """Installe un client devant le comptoir, en train de commander `item`."""
    agent = sim.agents[agent_id]
    recipe_id = {"bread": "bakery_lunch", "groceries": "shopping"}[item]
    recipe = sim.config.actions.recipes[recipe_id]
    step_index = next(i for i, step in enumerate(recipe.steps) if step.verb == "order")
    task = Task(
        kind=TaskKind.BLOCK,
        recipe_id=recipe_id,
        recipe=recipe,
        place_id=desk.place_id,
        activity=ActivityType.EAT,
        label="test",
        created=0,
        step_index=step_index,
        phase=Phase.QUEUE,
        desk_uid=desk.uid,
    )
    agent.tasks = [task]
    agent.place_id = desk.place_id
    sim.world.places[desk.place_id].occupants[agent.id] = None
    place_at(agent, desk.front_spot.tile)
    desk.queue = [agent.id]
    return task


def _staff_behind(sim: Simulation, agent_id: str, desk: ServiceDesk) -> None:
    staff = sim.agents[agent_id]
    task = Task(
        kind=TaskKind.SERVE,
        recipe_id="serve_customers",
        recipe=sim.config.actions.recipes["serve_customers"],
        place_id=desk.place_id,
        activity=ActivityType.WORK,
        label="test",
        created=0,
        phase=Phase.PERFORM,
        spot=desk.staff_spot,
        step_ends=10_000.0,
    )
    staff.tasks = [task]
    staff.spot = desk.staff_spot
    desk.staff_spot.reserved_by = staff.id
    place_at(staff, desk.staff_spot.tile)


def _serve(sim: Simulation, minutes: float) -> None:
    for _ in range(round(minutes * sim.clock.ticks_per_minute)):
        update_desks(sim.ctx)
        sim.clock.advance()


def test_rupture_de_stock(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    desk = _desk(sim, "boulangerie")
    assert desk.furniture.container is not None
    desk.furniture.container.items["bread"] = 0
    _customer_at_counter(sim, "lea", desk, "bread")
    _staff_behind(sim, "marcel", desk)
    _serve(sim, 5)
    assert desk.results.get("lea") is False
    assert not sim.agents["lea"].carries("bread")
    lines = [e.data.get("text") for e in events_of(sim, EventKind.SAY, "marcel")]
    assert any(text in sim.config.dialogues.out_of_stock for text in lines)


def test_service_normal_et_stock(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    desk = _desk(sim, "boulangerie")
    assert desk.furniture.container is not None
    before = desk.furniture.container.count("bread")
    _customer_at_counter(sim, "lea", desk, "bread")
    _staff_behind(sim, "marcel", desk)
    _serve(sim, 5)
    assert desk.results.get("lea") is True
    assert sim.agents["lea"].carries("bread")
    assert desk.furniture.container.count("bread") == before - 1
    assert len(events_of(sim, EventKind.SAY)) == 4  # deux répliques chacun
    assert desk.queue == []


def test_sans_vendeur_personne_n_est_servi(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    desk = _desk(sim, "boulangerie")
    _customer_at_counter(sim, "lea", desk, "bread")
    _serve(sim, 10)
    assert "lea" not in desk.results  # la boulangerie n'a pas de caisse automatique


def test_caisse_automatique(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    desk = _desk(sim, "supermarche")
    assert desk.self_service
    _customer_at_counter(sim, "paul", desk, "groceries")
    _serve(sim, 1)
    assert "paul" not in desk.results  # on laisse d'abord sa chance à la caissière
    _serve(sim, 4)
    assert desk.results.get("paul") is True
    assert sim.agents["paul"].carries("groceries")
    done = events_of(sim, EventKind.SERVICE_DONE, "paul")
    assert done and done[-1].data.get("staff") is None


# --------------------------------------------------------------------------- #
# Relations
# --------------------------------------------------------------------------- #
def test_compatibilite_symetrique_et_bornee(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    models = [agent.profile for agent in sim.agents.values()]
    for a in models:
        for b in models:
            score = compatibility(a, b)
            assert -1.0 <= score <= 1.0
            assert score == pytest.approx(compatibility(b, a))


def test_les_rencontres_rapprochent(make_sim: Callable[..., Simulation]) -> None:
    import random

    sim = make_sim()
    relations = Relations()
    lea, hugo = sim.agents["lea"].profile, sim.agents["hugo"].profile
    rng = random.Random(1)
    _relation, before, after = relations.meet(lea, hugo, 0, rng)
    assert before == "" and after == "connaissance"  # première rencontre
    for tick in range(1, 30):
        relations.meet(hugo, lea, tick, rng)
    relation = relations.get("hugo", "lea")
    assert relation is not None and relation.familiarity == 30
    # Deux caractères ouverts et sociables finissent par bien s'entendre.
    assert relation.affinity > 20 and relation.stage in ("sympathie", "amitié", "grande amitié")
    assert [other for other, _ in relations.of("lea")] == ["hugo"]
