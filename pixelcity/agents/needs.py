"""Besoins de type Sims : des jauges de 0 à 100 qui baissent avec le temps.

Une jauge à 100 = besoin parfaitement satisfait (rassasié, reposé...).
Chaque tick : valeur += (effet de l'activité − baisse naturelle) × durée.

Hystérésis (comme un thermostat) : un besoin devient urgent sous `critical`,
mais n'est considéré comblé qu'au-dessus de `satisfied`. Sans cet écart,
l'agent oscillerait : il mangerait une bouchée, repartirait, reviendrait.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from pixelcity.config.schemas import NeedSpec
from pixelcity.sim.types import ActivityType, NeedKind

# Le remède à chaque besoin urgent. Le loisir n'y figure pas : s'ennuyer ne
# fait pas quitter son travail en urgence, les plans s'en chargent.
REMEDIES: dict[NeedKind, ActivityType] = {
    NeedKind.HUNGER: ActivityType.EAT,
    NeedKind.ENERGY: ActivityType.SLEEP,
    NeedKind.HYGIENE: ActivityType.HYGIENE,
}

_NEED_ORDER: tuple[NeedKind, ...] = tuple(NeedKind)


@dataclass(slots=True)
class Needs:
    values: dict[NeedKind, float]

    @classmethod
    def initial(
        cls, specs: Mapping[NeedKind, NeedSpec], rng: random.Random, spread: float = 10.0
    ) -> Needs:
        """Valeurs de départ : la valeur configurée ± un peu de variété, reproductible."""
        return cls(
            {
                kind: _clamp(specs[kind].initial + rng.uniform(-spread, spread))
                for kind in _NEED_ORDER
            }
        )

    def __getitem__(self, kind: NeedKind) -> float:
        return self.values[kind]

    def update(
        self,
        specs: Mapping[NeedKind, NeedSpec],
        effects: Mapping[NeedKind, float],
        hours: float,
    ) -> None:
        """Applique en une passe la baisse naturelle et les effets de l'activité."""
        values = self.values
        for kind in _NEED_ORDER:
            delta = effects.get(kind, 0.0) - specs[kind].decay_per_hour
            values[kind] = _clamp(values[kind] + delta * hours)

    def critical_needs(self, specs: Mapping[NeedKind, NeedSpec]) -> list[NeedKind]:
        """Besoins sous leur seuil critique, du plus pressant au moins pressant.

        « Pressant » = le plus bas RELATIVEMENT à son seuil. Le tri est stable :
        à égalité, l'ordre de déclaration de `NeedKind` départage.
        """
        critical = [kind for kind in _NEED_ORDER if self.values[kind] < specs[kind].critical]
        return sorted(critical, key=lambda kind: self.values[kind] / max(specs[kind].critical, 1.0))

    def is_satisfied(self, kind: NeedKind, specs: Mapping[NeedKind, NeedSpec]) -> bool:
        return self.values[kind] >= specs[kind].satisfied

    def snapshot(self) -> dict[str, int]:
        """Valeurs arrondies : pour l'affichage et les événements."""
        return {kind.value: round(self.values[kind]) for kind in _NEED_ORDER}


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else 100.0 if value > 100.0 else value
