"""Tests des besoins, du planificateur et de la routine."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from pixelcity.agents.needs import Needs
from pixelcity.agents.plan import PlanBuilder
from pixelcity.agents.planner import PlanningContext, RuleBasedPlanner
from pixelcity.config.loader import GameConfig
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType, NeedKind, PlaceKind, Weekday

# --------------------------------------------------------------------------- #
# Besoins
# --------------------------------------------------------------------------- #


def test_les_besoins_baissent_et_restent_bornes(config: GameConfig) -> None:
    specs = config.settings.needs
    needs = Needs(dict.fromkeys(NeedKind, 50.0))
    needs.update(specs, {}, hours=1.0)
    assert needs[NeedKind.HUNGER] == pytest.approx(50 - specs[NeedKind.HUNGER].decay_per_hour)
    needs.update(specs, {}, hours=1000.0)
    assert all(value == 0.0 for value in needs.values.values())
    needs.update(specs, dict.fromkeys(NeedKind, 1000.0), hours=1.0)
    assert all(value == 100.0 for value in needs.values.values())


def test_hysteresis(config: GameConfig) -> None:
    specs = config.settings.needs
    spec = specs[NeedKind.HUNGER]
    needs = Needs(dict.fromkeys(NeedKind, 100.0))
    needs.values[NeedKind.HUNGER] = spec.critical - 1
    assert needs.critical_needs(specs) == [NeedKind.HUNGER]
    # Entre les deux seuils : plus critique, mais pas encore « comblé ».
    needs.values[NeedKind.HUNGER] = (spec.critical + spec.satisfied) / 2
    assert needs.critical_needs(specs) == []
    assert not needs.is_satisfied(NeedKind.HUNGER, specs)


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


def test_le_builder_empeche_les_trous() -> None:
    builder = PlanBuilder(day_index=2)
    builder.add(7 * 60, ActivityType.SLEEP, "maison", "sommeil")
    builder.add(6 * 60, ActivityType.EAT, "maison", "ignoré : finirait avant le curseur")
    builder.add(MINUTES_PER_DAY, ActivityType.RELAX, "maison", "journée")
    plan = builder.build()
    assert plan.validation_errors() == []
    assert plan.blocks[0].start == 2 * MINUTES_PER_DAY
    with pytest.raises(ValueError):
        PlanBuilder(0).build()  # plan incomplet


@pytest.mark.parametrize("day_index", range(7))
def test_plans_valides_toute_la_semaine(
    make_sim: Callable[..., Simulation], day_index: int
) -> None:
    sim = make_sim()
    planner = RuleBasedPlanner()
    weekday = Weekday.from_index(day_index)
    for agent in sim.agents.values():
        ctx = PlanningContext(sim.world, weekday, random.Random(day_index))
        plan = planner.plan_day(agent, day_index, ctx)
        assert plan.validation_errors() == [], agent.id
        assert plan.blocks[0].activity is ActivityType.SLEEP
        assert plan.blocks[-1].activity is ActivityType.SLEEP
        shift = agent.profile.work.schedule.get(weekday) if agent.profile.work else None
        work_blocks = [b for b in plan.blocks if b.activity is ActivityType.WORK]
        if shift is None:
            assert not work_blocks, f"{agent.id} travaille un jour de repos"
        else:
            assert work_blocks and all(b.punctual for b in work_blocks)
            assert work_blocks[0].start == plan.start + shift[0]
            assert work_blocks[-1].end == plan.start + shift[1]
        for block in plan.blocks:
            place = sim.world.places[block.place_id]
            if place.kind is PlaceKind.HOME or block.place_id == agent.work_place_id:
                continue
            minute = block.start - plan.start
            assert place.hours.is_open(day_index, minute), (agent.id, block.label)
            assert place.hours.is_open(day_index, block.end - plan.start - 1), block.label


def test_le_planificateur_est_reproductible(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    agent = sim.agents["lea"]
    plans = [
        RuleBasedPlanner().plan_day(
            agent, 5, PlanningContext(sim.world, Weekday.SAT, random.Random(3))
        )
        for _ in range(2)
    ]
    assert plans[0] == plans[1]


# --------------------------------------------------------------------------- #
# Routine
# --------------------------------------------------------------------------- #


def test_depart_anticipe_pour_arriver_a_l_heure(make_sim: Callable[..., Simulation]) -> None:
    """Karim commence à 8 h : il doit être à l'école à 8 h, donc partir avant."""
    sim = make_sim()
    sim.run_ticks(8 * 60 * sim.clock.ticks_per_minute)  # lundi 08:00
    karim = sim.agents["karim"]
    assert karim.place_id == "ecole"
    assert karim.activity is ActivityType.WORK


def test_une_faim_critique_interrompt_le_plan(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    sim.run_ticks(10 * 60 * sim.clock.ticks_per_minute)  # lundi 10:00, Léa au bureau
    lea = sim.agents["lea"]
    assert lea.place_id == "bureaux"
    lea.needs.values[NeedKind.HUNGER] = 5.0
    sim.tick()
    assert lea.override is not None and lea.override.need is NeedKind.HUNGER
    # Elle va manger, puis reprend son plan une fois rassasiée.
    for _ in range(90 * sim.clock.ticks_per_minute):
        sim.tick()
        if lea.override is None:
            break
    assert lea.override is None
    assert lea.needs[NeedKind.HUNGER] >= sim.config.settings.needs[NeedKind.HUNGER].satisfied
    kinds = [event.kind for event in sim.events if event.agent_id == "lea"]
    assert EventKind.NEED_CRITICAL in kinds and EventKind.NEED_RECOVERED in kinds


def test_les_occupants_sont_coherents(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    for _ in range(48):
        sim.run_ticks(30 * sim.clock.ticks_per_minute)
        for agent in sim.agents.values():
            for place in sim.world.places.values():
                assert (agent.id in place.occupants) == (agent.place_id == place.id)
