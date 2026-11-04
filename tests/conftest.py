"""Fixtures partagées par les tests."""

from __future__ import annotations

from collections.abc import Callable

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
