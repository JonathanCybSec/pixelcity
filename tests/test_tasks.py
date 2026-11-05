"""Tests de l'exécuteur de tâches : les besoins passent par des gestes concrets."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.agents.tasks import Phase, TaskKind
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind, Pose

from .helpers import events_of, run_to, run_until, step_started

MONDAY = 0


def test_le_petit_dejeuner_passe_par_le_frigo(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    fridge = sim.world.places["appart_1"].container_with("provisions")
    assert fridge is not None
    run_to(sim, MONDAY, 7.25)
    before = fridge.count("provisions")
    took = step_started(sim, "lea", "take_food")
    assert run_until(sim, took, max_minutes=30)
    sim.run_ticks(sim.clock.ticks_per_minute * 2)  # le temps de sortir les provisions
    assert lea.carries("provisions") and fridge.count("provisions") == before - 1
    eats = step_started(sim, "lea", "eat")
    assert run_until(sim, eats, max_minutes=20)
    assert lea.pose is Pose.SIT  # on mange assis, à table
    hunger_before = lea.needs[NeedKind.HUNGER]
    assert run_until(sim, lambda: not lea.carries("provisions"), max_minutes=25)
    assert lea.needs[NeedKind.HUNGER] > hunger_before + 30


def test_cuisiner_allume_la_cuisiniere(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 19.4)
    cooks = step_started(sim, "karim", "cook")
    assert run_until(sim, cooks, max_minutes=30)
    task = sim.agents["karim"].task
    assert task is not None and task.switched is not None
    stove = task.switched
    assert stove.type_id == "STOVE" and stove.is_on
    eats = step_started(sim, "karim", "eat")
    assert run_until(sim, eats, max_minutes=30)
    assert not stove.is_on  # on éteint en passant à table


def test_une_envie_pressante_interrompt_puis_reprend(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 10.0)
    lea = sim.agents["lea"]
    assert lea.place_id == "bureaux"
    work = lea.block_task
    assert work is not None and work.recipe_id == "job_office"
    lea.needs.values[NeedKind.BLADDER] = 5.0
    sim.run_ticks(10 * sim.clock.ticks_per_minute)  # finir le geste en cours puis y aller

    def toilet_done() -> bool:
        return not any(t.kind is TaskKind.URGENT for t in lea.tasks)

    urgent = [task for task in lea.tasks if task.kind is TaskKind.URGENT]
    assert urgent or toilet_done()
    assert run_until(sim, toilet_done, max_minutes=30)
    assert lea.needs[NeedKind.BLADDER] > 80
    assert lea.block_task is work  # le travail reprend là où il en était
    assert run_until(sim, lambda: work.phase is Phase.PERFORM, max_minutes=10)
    assert events_of(sim, EventKind.NEED_RECOVERED, "lea")


def test_les_courses_finissent_dans_le_frigo(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 9.0)  # Paul se promène au parc
    paul = sim.agents["paul"]
    assert paul.place_id != paul.profile.home
    fridge = sim.world.places[paul.profile.home].container_with("provisions")
    assert fridge is not None
    before = fridge.count("provisions")
    paul.give("groceries")
    assert run_until(sim, lambda: not paul.carries("groceries"), max_minutes=4 * 60)
    assert paul.place_id == paul.profile.home
    assert fridge.count("provisions") == min(fridge.capacity, before + 10)


def test_on_ne_ressort_pas_du_frigo_ce_qu_on_a_en_main(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 7.0)
    lea = sim.agents["lea"]
    fridge = sim.world.places["appart_1"].container_with("provisions")
    assert fridge is not None
    lea.give("provisions")
    before = fridge.count("provisions")
    eats = step_started(sim, "lea", "eat")
    assert run_until(sim, eats, max_minutes=60)
    assert fridge.count("provisions") == before


def test_une_place_ne_se_reserve_qu_une_fois(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    for _ in range(2 * 24 * 6):  # deux jours, contrôle toutes les 10 minutes
        sim.run_ticks(10 * sim.clock.ticks_per_minute)
        holders: dict[str, int] = {}
        for furniture in sim.world.furniture.values():
            for spot in furniture.spots:
                if spot.reserved_by is not None:
                    holders[spot.reserved_by] = holders.get(spot.reserved_by, 0) + 1
                    owner = sim.agents[spot.reserved_by]
                    assert any(task.spot is spot for task in owner.tasks), spot.uid
        assert all(count == 1 for count in holders.values()), holders
