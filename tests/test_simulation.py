"""Tests de la simulation entière : déterminisme, commandes, invariants, frontière."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pixelcity.config.loader import GameConfig
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind

ROOT = Path(__file__).resolve().parents[1]


def test_meme_graine_meme_simulation(make_sim: Callable[..., Simulation]) -> None:
    first, second = make_sim(seed=42), make_sim(seed=42)
    first.run_days(2)
    second.run_days(2)
    assert first.events.digest() == second.events.digest()


def test_graines_differentes_simulations_differentes(make_sim: Callable[..., Simulation]) -> None:
    first, second = make_sim(seed=1), make_sim(seed=2)
    first.run_days(2)
    second.run_days(2)
    assert first.events.digest() != second.events.digest()


@dataclass
class _Teleport:
    """Commande de test : téléporte un agent (préfigure le mode Dieu)."""

    agent_id: str
    tile: tuple[int, int]

    def execute(self, sim: Simulation) -> None:
        agent = sim.agents[self.agent_id]
        agent.tile = self.tile
        agent.pos = agent.prev_pos = (float(self.tile[0]), float(self.tile[1]))


def test_les_commandes_s_appliquent_au_tick_suivant(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    marcel = sim.agents["marcel"]
    before = marcel.tile
    sim.apply(_Teleport("marcel", (40, 30)))
    assert marcel.tile == before  # rien ne change hors d'un tick
    sim.tick()
    assert marcel.tile != before


# --------------------------------------------------------------------------- #
# Une semaine complète, contrôlée toutes les 10 minutes simulées
# --------------------------------------------------------------------------- #
@dataclass
class WeekReport:
    sim: Simulation
    problems: list[str] = field(default_factory=list)
    lowest: dict[tuple[str, NeedKind], float] = field(default_factory=dict)


@pytest.fixture(scope="module")
def week(config: GameConfig) -> WeekReport:
    sim = Simulation(config, seed=42)
    report = WeekReport(sim)
    deprived: Counter[str] = Counter()
    travelling: Counter[str] = Counter()
    per_check = 10 * sim.clock.ticks_per_minute
    for _check in range(7 * 24 * 6):
        sim.run_ticks(per_check)
        now = sim.clock.minute_of_day
        weekday = sim.clock.weekday
        stamp = sim.clock.label()
        for agent in sim.agents.values():
            for need in NeedKind:
                key = (agent.id, need)
                report.lowest[key] = min(report.lowest.get(key, 100.0), agent.needs[need])
            if any(agent.needs[need] <= 0.5 for need in NeedKind):
                deprived[agent.id] += 10
                if deprived[agent.id] > 60:
                    report.problems.append(f"{stamp} {agent.id} en manque depuis plus d'1 h")
            else:
                deprived[agent.id] = 0
            # Personne ne reste en route indéfiniment (chemin impossible, porte close...).
            task = agent.task
            if task is not None and task.phase.value in ("travel", "wait_open"):
                travelling[agent.id] += 10
                if travelling[agent.id] > 90:
                    report.problems.append(f"{stamp} {agent.id} en route depuis plus d'1 h 30")
            else:
                travelling[agent.id] = 0
            # À 3 h du matin, tout le monde est chez soi, et le bloc en cours est le sommeil.
            if now == 3 * 60:
                bottom = agent.block_task
                if (
                    agent.place_id != agent.profile.home
                    or bottom is None
                    or bottom.recipe_id != "sleep"
                ):
                    report.problems.append(f"{stamp} {agent.id} ne dort pas chez lui")
            # Au milieu de son service, chacun est sur son lieu de travail.
            if agent.profile.work and now == 10 * 60:
                shift = agent.profile.work.schedule.get(weekday)
                on_duty = shift is not None and shift[0] + 30 < now < shift[1]
                if on_duty and agent.place_id != agent.profile.work.place:
                    report.problems.append(f"{stamp} {agent.id} absent du travail")
        _check_consistency(sim, report)
    return report


def _check_consistency(sim: Simulation, report: WeekReport) -> None:
    """Ce que l'on vérifie en continu : pas de réservation, d'allumage ni de file fantôme."""
    stamp = sim.clock.label()
    switched: Counter[str] = Counter()
    for agent in sim.agents.values():
        for task in agent.tasks:
            if task.switched is not None:
                switched[task.switched.uid] += 1
        for place in sim.world.places.values():
            if (agent.id in place.occupants) != (agent.place_id == place.id):
                report.problems.append(f"{stamp} {agent.id} : occupation incohérente ({place.id})")
    for furniture in sim.world.furniture.values():
        if furniture.switched_on != switched[furniture.uid]:
            report.problems.append(
                f"{stamp} {furniture.type_id} allumé {furniture.switched_on} fois"
            )
    for desk in sim.desks.values():
        for customer_id in desk.queue:
            customer = sim.agents[customer_id]
            if not any(task.desk_uid == desk.uid for task in customer.tasks):
                report.problems.append(f"{stamp} {customer_id} dans la file sans l'attendre")


def test_une_semaine_sans_incoherence(week: WeekReport) -> None:
    assert week.problems[:10] == []


def test_personne_ne_se_perd(week: WeekReport) -> None:
    kinds = [event.kind for event in week.sim.events]
    assert EventKind.PATH_NOT_FOUND not in kinds
    # Les trajets aboutissent : presque autant d'arrivées que de départs (un
    # trajet peut être abandonné en route, pour une envie pressante par exemple).
    departures, arrivals = kinds.count(EventKind.DEPARTED), kinds.count(EventKind.ARRIVED)
    assert arrivals >= 0.9 * departures


def test_les_besoins_restent_sous_controle(week: WeekReport) -> None:
    """Sur une semaine, personne ne tombe à zéro de faim, de sommeil ou d'hygiène."""
    for (agent_id, need), lowest in week.lowest.items():
        if need in (NeedKind.HUNGER, NeedKind.ENERGY, NeedKind.HYGIENE):
            assert lowest > 5, (agent_id, need.value, lowest)


def test_la_ville_vit(week: WeekReport) -> None:
    """Les commerces servent, les gens se parlent et font connaissance."""
    events = list(week.sim.events)
    served = Counter(
        e.place_id for e in events if e.kind is EventKind.SERVICE_DONE and e.data.get("ok")
    )
    assert served["boulangerie"] >= 3 and served["cafe"] >= 5 and served["supermarche"] >= 3
    assert sum(1 for e in events if e.kind is EventKind.SAY) >= 40
    assert any(e.kind is EventKind.RELATION for e in events)
    # Les courses ont été faites : chaque frigo a encore de quoi tenir.
    for agent in week.sim.agents.values():
        fridge = week.sim.world.places[agent.profile.home].container_with("provisions")
        assert fridge is not None and fridge.count("provisions") > 0, agent.id


def test_les_inventaires_ne_fuient_pas(week: WeekReport) -> None:
    """Un plat acheté finit mangé : rien ne s'accumule dans les poches."""
    for agent in week.sim.agents.values():
        assert sum(agent.inventory.values()) <= 2, (agent.id, agent.inventory)


# --------------------------------------------------------------------------- #
# Frontière d'architecture et ligne de commande
# --------------------------------------------------------------------------- #
def test_le_noyau_tourne_sans_pygame() -> None:
    """La frontière d'architecture, vérifiée automatiquement.

    On lance un interpréteur Python neuf (pour partir d'un `sys.modules`
    vierge), on simule une journée, et on vérifie que pygame n'a jamais été
    importé, même indirectement. C'est ce test qui a révélé que `pytmx`
    importe pygame de lui-même.
    """
    script = (
        "import sys\n"
        "from pixelcity.config.loader import load_config\n"
        "from pixelcity.headless import run_headless\n"
        "from pixelcity.sim.simulation import Simulation\n"
        "import io\n"
        "run_headless(Simulation(load_config()), 1, verbose=False, out=io.StringIO())\n"
        "assert 'pygame' not in sys.modules, 'pygame importé par le noyau !'\n"
        "print('ok')\n"
    )
    result = _run_python("-c", script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_cli_headless() -> None:
    result = _run_python("-m", "pixelcity", "--headless", "--days", "0.5")
    assert result.returncode == 0, result.stderr
    assert "Simulation lancée (graine 42" in result.stdout
    assert "empreinte du journal" in result.stdout


def test_cli_refuse_une_duree_negative() -> None:
    result = _run_python("-m", "pixelcity", "--headless", "--days", "-1")
    assert result.returncode == 2
    assert "strictement positif" in result.stderr


def _run_python(*args: str) -> subprocess.CompletedProcess[str]:
    """Lance un interpréteur Python neuf, en UTF-8 des deux côtés.

    Sans `PYTHONIOENCODING` et `encoding="utf-8"`, sous Windows, l'enfant
    écrirait en cp1252 et le parent décoderait avec l'encodage local : les
    accents des messages d'erreur feraient planter... le test lui-même.
    """
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
