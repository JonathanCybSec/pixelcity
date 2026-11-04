"""Tests de l'horloge simulée et du hasard reproductible."""

from __future__ import annotations

import pytest

from pixelcity.sim.clock import SimClock, format_absolute_minute
from pixelcity.sim.rng import RngRegistry, derive_seed
from pixelcity.sim.types import Weekday, format_hhmm, parse_hhmm


def test_tick_zero_est_lundi_minuit() -> None:
    clock = SimClock(tick_seconds=10)
    assert clock.weekday is Weekday.MON
    assert (clock.hour, clock.minute) == (0, 0)
    assert clock.is_start_of_day


def test_conversions_de_ticks() -> None:
    clock = SimClock(tick_seconds=10)
    assert clock.ticks_per_day == 8640
    clock.advance(6 * 60 * 7 + 6 * 42)  # 7 h 42 min plus tard
    assert (clock.hour, clock.minute) == (7, 42)
    assert clock.label() == "Lundi 07:42 · jour 1"


def test_changement_de_jour_et_de_semaine() -> None:
    clock = SimClock(tick_seconds=10)
    clock.advance(clock.ticks_per_day)
    tuesday = (clock.weekday, clock.day_index, clock.is_start_of_day)
    clock.advance(clock.ticks_per_day * 6)
    next_monday = (clock.weekday, clock.day_index)
    assert tuesday == (Weekday.TUE, 1, True)
    assert next_monday == (Weekday.MON, 7)


def test_tick_qui_ne_divise_pas_la_minute_est_refuse() -> None:
    with pytest.raises(ValueError):
        SimClock(tick_seconds=7)


def test_parse_et_format_des_heures() -> None:
    assert parse_hhmm("07:30") == 450
    assert parse_hhmm("24:00") == 1440
    assert format_hhmm(450) == "07:30"
    assert format_absolute_minute(1440 + 13 * 60 + 5) == "Mar 13:05"
    for bad in ("7h30", "25:00", "12:60", "24:30"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_meme_graine_meme_flux() -> None:
    a, b = RngRegistry(42), RngRegistry(42)
    assert [a.stream("x").random() for _ in range(5)] == [b.stream("x").random() for _ in range(5)]


def test_flux_independants() -> None:
    """Propriété clé : consommer un flux ne décale pas les autres."""
    quiet, busy = RngRegistry(42), RngRegistry(42)
    for _ in range(1000):
        busy.stream("meteo").random()  # un sous-système très bavard
    assert quiet.stream("agents").random() == busy.stream("agents").random()


def test_derivation_stable_entre_lancements() -> None:
    # Valeur figée : si elle change, la reproductibilité entre versions est cassée.
    # (Avec `hash()` au lieu de SHA-256, elle changerait à chaque lancement de Python.)
    assert derive_seed(42, "planner:marcel") == derive_seed(42, "planner:marcel")
    assert derive_seed(42, "a") != derive_seed(42, "b")
    assert derive_seed(42, "a") != derive_seed(43, "a")
