"""Tests de la simulation entière : déterminisme, commandes, invariants, frontière."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import ActivityType, NeedKind

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
    sim.apply(_Teleport("marcel", (0, 13)))
    assert marcel.tile == before  # rien ne change hors d'un tick
    sim.tick()
    assert marcel.tile != before


def test_invariants_sur_une_semaine(make_sim: Callable[..., Simulation]) -> None:
    """Une semaine complète en headless : la ville doit « tenir debout »."""
    sim = make_sim(seed=42)
    ticks_per_minute = sim.clock.ticks_per_minute
    starving: dict[str, int] = dict.fromkeys(sim.agents, 0)
    for day in range(7):
        for minute in range(0, 24 * 60, 10):
            sim.run_ticks(10 * ticks_per_minute)
            now = (minute + 10) % (24 * 60)
            for agent in sim.agents.values():
                # Personne ne reste en manque prolongé d'un besoin.
                if any(agent.needs[kind] <= 0.5 for kind in NeedKind):
                    starving[agent.id] += 10
                assert starving[agent.id] <= 60, f"{agent.id} en manque depuis plus d'1 h"
                # À 3 h du matin, tout le monde dort chez soi.
                if now == 3 * 60:
                    assert agent.place_id == agent.profile.home, (day, agent.id)
                    assert agent.activity is ActivityType.SLEEP
                # Au milieu de son service, chacun est au travail.
                if agent.profile.work and now == 10 * 60:
                    shift = agent.profile.work.schedule.get(sim.clock.weekday)
                    if shift is not None and shift[0] < now < shift[1]:
                        assert agent.place_id == agent.profile.work.place, (day, agent.id)
    kinds = [event.kind for event in sim.events]
    assert EventKind.PATH_NOT_FOUND not in kinds
    # Chaque départ est suivi d'une arrivée (personne ne se perd en route).
    departures = kinds.count(EventKind.DEPARTED)
    arrivals = kinds.count(EventKind.ARRIVED)
    assert departures - arrivals <= len(sim.agents)


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
