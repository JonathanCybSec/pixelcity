"""Fixtures partagées par les tests."""

from __future__ import annotations

import os
from collections.abc import Callable

# Doit être posé AVANT le premier `import pygame` (masque sa bannière) :
# conftest.py est chargé par pytest avant tous les modules de test.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pytest

from pixelcity.config.loader import GameConfig, load_config
from pixelcity.sim.simulation import Simulation


@pytest.fixture(scope="session")
def config() -> GameConfig:
    # La config est immuable (modèles Pydantic gelés) : on peut la partager
    # entre tous les tests sans risque qu'un test modifie celle d'un autre.
    return load_config()


@pytest.fixture
def make_sim(config: GameConfig) -> Callable[..., Simulation]:
    def factory(seed: int = 42) -> Simulation:
        return Simulation(config, seed=seed)

    return factory
