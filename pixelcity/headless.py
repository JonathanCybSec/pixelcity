"""Mode headless : la simulation sans fenêtre, aussi vite que le CPU le permet.

Usages : tests rapides, débogage, et plus tard les campagnes de tests A/B
(étape 6), où l'on lancera des dizaines de simulations en parallèle.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pixelcity.memory.stream import MemoryKind
from pixelcity.sim.clock import format_absolute_minute
from pixelcity.sim.events import Event, EventKind
from pixelcity.sim.narration import VERBOSE_KINDS, describe
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind


@dataclass(frozen=True, slots=True)
class HeadlessReport:
    days: float
    ticks: int
    real_seconds: float
    events: int
    digest: str

    @property
    def ticks_per_second(self) -> float:
        return self.ticks / self.real_seconds if self.real_seconds > 0 else float("inf")


def run_headless(
    sim: Simulation,
    days: float,
    *,
    verbose: bool = True,
    out: TextIO = sys.stdout,
    jsonl_path: Path | None = None,
) -> HeadlessReport:
    agent_names, place_names = sim.agent_names(), sim.place_names()
    tick_seconds = sim.clock.tick_seconds
    jsonl = jsonl_path.open("w", encoding="utf-8") if jsonl_path else None

    def on_event(event: Event) -> None:
        if jsonl is not None:
            jsonl.write(event.to_json() + "\n")
        if verbose and event.kind not in VERBOSE_KINDS:
            stamp = format_absolute_minute(event.tick * tick_seconds // 60)
            separator = "" if event.kind is EventKind.DAY_STARTED else f"{stamp}  "
            print(separator + describe(event, agent_names, place_names), file=out)

    # Les événements émis AVANT l'abonnement (le lancement de la simulation)
    # sont rejoués, pour que le journal et l'export soient complets.
    for past_event in list(sim.events):
        on_event(past_event)
    sim.events.subscribe(on_event)
    ticks = round(days * sim.clock.ticks_per_day)
    start = time.perf_counter()
    try:
        sim.run_ticks(ticks)
    finally:
        if jsonl is not None:
            jsonl.close()
    elapsed = time.perf_counter() - start

    report = HeadlessReport(days, ticks, elapsed, sim.events.total_emitted, sim.events.digest())
    _print_summary(sim, report, out)
    return report


def _print_summary(sim: Simulation, report: HeadlessReport, out: TextIO) -> None:
    print("\n=== Bilan ===", file=out)
    print(
        f"{report.days:g} jour(s) simulé(s) · {report.ticks} ticks en {report.real_seconds:.2f} s "
        f"({report.ticks_per_second:,.0f} ticks/s) · {report.events} événements",
        file=out,
    )
    print(f"Graine {sim.seed} · empreinte du journal : {report.digest[:16]}", file=out)
    convs = sim.conversations
    counts = " · ".join(f"{kind.value} {n}" for kind, n in convs.counts.items())
    sources = ", ".join(f"{name} {n}" for name, n in sorted(convs.by_source.items())) or "aucune"
    flirts = sum(relation.flirts for _, relation in sim.relations.pairs())
    print(f"Conversations : {counts} (répliques : {sources}) · flirts : {flirts}", file=out)
    booked = sim.appointments.items
    kept = sum(1 for ap in booked if ap.kept)
    memories = sum(len(agent.memory) for agent in sim.agents.values())
    print(
        f"Mémoire : {memories} souvenirs · {sim.minds.reflections} réflexions · "
        f"rendez-vous : {len(booked)} pris, {kept} tenus",
        file=out,
    )
    for agent in sim.agents.values():
        needs = " · ".join(f"{kind.label} {agent.needs[kind]:.0f}" for kind in NeedKind)
        top = sorted(agent.minutes_by_recipe.items(), key=lambda item: -item[1])[:5]
        hours = ", ".join(f"{name} {minutes / 60:.1f} h" for name, minutes in top)
        print(f"- {agent.name} ({agent.profile.job}) : {needs}", file=out)
        print(f"    temps passé : {hours}", file=out)
        thought = agent.memory.recent(1, (MemoryKind.REFLECTION,))
        if thought:
            print(f"    pense : « {thought[0].text} »", file=out)
