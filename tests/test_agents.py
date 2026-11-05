"""Tests des besoins, des plans et du planificateur."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from pixelcity.agents.needs import Needs
from pixelcity.agents.plan import PlanBuilder
from pixelcity.agents.planner import MEAL_OPEN_MINUTES, PlanningContext, RuleBasedPlanner
from pixelcity.config.loader import GameConfig
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import MINUTES_PER_DAY, ActivityType, NeedKind, PlaceKind, Weekday
from pixelcity.world.place import OpeningHours


def planning(sim: Simulation, day_index: int, seed: int = 0) -> PlanningContext:
    return PlanningContext(
        world=sim.world,
        actions=sim.config.actions,
        weekday=Weekday.from_index(day_index),
        rng=random.Random(seed),
        walk_speed=sim.config.settings.walk_speed_tiles_per_minute,
    )


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
    builder.add(7 * 60, ActivityType.SLEEP, "maison", "sommeil", "sleep")
    builder.add(6 * 60, ActivityType.EAT, "maison", "ignoré : finirait avant le curseur", "snack")
    builder.add(MINUTES_PER_DAY, ActivityType.RELAX, "maison", "journée", "relax_home")
    plan = builder.build()
    assert plan.validation_errors() == []
    assert plan.blocks[0].start == 2 * MINUTES_PER_DAY
    with pytest.raises(ValueError):
        PlanBuilder(0).build()  # plan incomplet


def test_deux_blocs_identiques_fusionnent() -> None:
    builder = PlanBuilder(day_index=0)
    builder.add(60, ActivityType.RELAX, "maison", "repos", "relax_home")
    builder.add(120, ActivityType.RELAX, "maison", "repos", "relax_home")
    builder.add(MINUTES_PER_DAY, ActivityType.SLEEP, "maison", "sommeil", "sleep")
    assert len(builder.build().blocks) == 2


@pytest.mark.parametrize("day_index", range(7))
def test_plans_valides_toute_la_semaine(
    make_sim: Callable[..., Simulation], day_index: int
) -> None:
    sim = make_sim()
    planner = RuleBasedPlanner()
    weekday = Weekday.from_index(day_index)
    recipes = sim.config.actions.recipes
    for agent in sim.agents.values():
        plan = planner.plan_day(agent, day_index, planning(sim, day_index, day_index))
        assert plan.validation_errors() == [], agent.id
        assert plan.blocks[0].recipe == "sleep" and plan.blocks[-1].recipe == "sleep"
        shift = agent.profile.work.schedule.get(weekday) if agent.profile.work else None
        work_blocks = [b for b in plan.blocks if b.activity is ActivityType.WORK]
        if shift is None:
            assert not work_blocks, f"{agent.id} travaille un jour de repos"
        else:
            assert work_blocks and all(b.punctual for b in work_blocks)
            assert work_blocks[0].start == plan.start + shift[0]
            assert work_blocks[-1].end == plan.start + shift[1]
        for block in plan.blocks:
            assert block.recipe in recipes, block.recipe
            place = sim.world.places[block.place_id]
            if place.kind is PlaceKind.HOME or block.place_id == agent.work_place_id:
                continue
            start = block.start - plan.start
            assert place.hours.is_open(day_index, start), (agent.id, block.label)
            last = (
                start + MEAL_OPEN_MINUTES - 1
                if block.activity is ActivityType.EAT
                else block.end - plan.start - 1
            )
            assert place.hours.is_open(day_index, last), (agent.id, block.label)


def test_le_planificateur_est_reproductible(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    agent = sim.agents["lea"]
    plans = [RuleBasedPlanner().plan_day(agent, 5, planning(sim, 5, 3)) for _ in range(2)]
    assert plans[0] == plans[1]


def test_frigo_presque_vide_donc_courses(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    paul = sim.agents["paul"]
    fridge = sim.world.places[paul.profile.home].container_with("provisions")
    assert fridge is not None
    fridge.items["provisions"] = 1
    plan = RuleBasedPlanner().plan_day(paul, 1, planning(sim, 1))
    assert any(block.recipe == "shopping" for block in plan.blocks)
    fridge.items["provisions"] = 12
    plan = RuleBasedPlanner().plan_day(paul, 1, planning(sim, 1))
    assert not any(block.recipe == "shopping" for block in plan.blocks)


def test_rien_d_ouvert_a_midi_donc_gamelle(make_sim: Callable[..., Simulation]) -> None:
    """Boulangerie et café fermés, maison trop loin : Léa emporte sa gamelle."""
    sim = make_sim()
    for place_id in ("boulangerie", "cafe"):
        sim.world.places[place_id].hours = OpeningHours((0, 1), frozenset())
    plan = RuleBasedPlanner().plan_day(sim.agents["lea"], 0, planning(sim, 0))
    recipes = [block.recipe for block in plan.blocks]
    assert "pack_lunch" in recipes and "lunchbox_lunch" in recipes
    assert recipes.index("pack_lunch") < recipes.index("lunchbox_lunch")
    lunch = next(block for block in plan.blocks if block.recipe == "lunchbox_lunch")
    assert lunch.place_id == "bureaux"  # elle déjeune au bureau
