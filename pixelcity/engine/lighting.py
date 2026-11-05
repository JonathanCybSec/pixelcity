"""Lumière du jour et de la nuit, appliquée sur l'image native (avant agrandissement).

Deux opérations de « mélange » (blend), comme les calques de Photoshop :
- MULTIPLIER par une couleur assombrit et teinte tout (le bleu de la nuit,
  l'orangé du crépuscule) ;
- AJOUTER une couleur éclaircit localement (lampadaires, fenêtres allumées).

Comme on travaille sur la petite image native (~430×240), c'est quasi gratuit.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pygame

from pixelcity.engine.scene import Scene
from pixelcity.sim.types import Pose

if TYPE_CHECKING:
    from pixelcity.sim.simulation import Simulation

type RGB = tuple[int, int, int]

# Teinte du monde au fil de la journée : (minute du jour, couleur). Entre deux
# repères, on interpole linéairement.
KEYFRAMES: tuple[tuple[int, RGB], ...] = (
    (0, (92, 104, 160)),
    (5 * 60 + 15, (100, 110, 165)),
    (6 * 60 + 15, (255, 214, 186)),
    (7 * 60 + 15, (255, 255, 255)),
    (18 * 60 + 30, (255, 255, 255)),
    (19 * 60 + 30, (255, 208, 168)),
    (20 * 60 + 45, (118, 126, 182)),
    (24 * 60, (92, 104, 160)),
)
WINDOW_LIGHT: RGB = (46, 36, 14)  # lumière chaude ajoutée dans les pièces occupées
LAMP_RADIUS = 34
LAMP_TYPES = frozenset({"LAMPPOST"})


def tint_at(minute_of_day: float) -> RGB:
    for (m0, c0), (m1, c1) in itertools.pairwise(KEYFRAMES):
        if m0 <= minute_of_day <= m1:
            t = (minute_of_day - m0) / (m1 - m0) if m1 > m0 else 0.0
            return (
                round(c0[0] + (c1[0] - c0[0]) * t),
                round(c0[1] + (c1[1] - c0[1]) * t),
                round(c0[2] + (c1[2] - c0[2]) * t),
            )
    return KEYFRAMES[-1][1]


def darkness(tint: RGB) -> float:
    """0 en plein jour, ~0,6 au cœur de la nuit."""
    return 1.0 - (tint[0] + tint[1] + tint[2]) / (3 * 255)


def _radial_glow(radius: int, color: RGB) -> pygame.Surface:
    size = radius * 2
    glow = pygame.Surface((size, size))
    glow.fill((0, 0, 0))
    for r in range(radius, 0, -1):
        k = (1 - r / radius) ** 2
        pygame.draw.circle(
            glow,
            (round(color[0] * k), round(color[1] * k), round(color[2] * k)),
            (radius, radius),
            r,
        )
    return glow


class Lighting:
    def __init__(self, sim: Simulation, scene: Scene) -> None:
        self._lamps = [
            (prop.x + 8, prop.y + 5)
            for prop in scene.props
            if prop.furniture is not None and prop.furniture.type_id in LAMP_TYPES
        ]
        self._glow = _radial_glow(LAMP_RADIUS, (120, 96, 52))
        self._rooms = [
            (
                place.id,
                pygame.Rect(
                    place.area.x * 16,
                    place.area.y * 16 - 8,
                    place.area.width * 16,
                    place.area.height * 16,
                ),
            )
            for place in sim.world.places.values()
            if not place.outdoor
        ]
        self.enabled = True

    def apply(
        self, frame: pygame.Surface, view: pygame.Rect, sim: Simulation, seconds: float
    ) -> None:
        if not self.enabled:
            return
        minute = sim.clock.total_seconds / 60 % (24 * 60)
        tint = tint_at(minute)
        if tint == (255, 255, 255):
            return
        frame.fill(tint, special_flags=pygame.BLEND_MULT)
        night = darkness(tint)
        if night < 0.15:
            return
        k = min(1.0, (night - 0.15) / 0.4)
        light = (round(WINDOW_LIGHT[0] * k), round(WINDOW_LIGHT[1] * k), round(WINDOW_LIGHT[2] * k))
        for place_id, rect in self._rooms:
            occupants = sim.world.places[place_id].occupants
            awake = any(sim.agents[a].pose is not Pose.LIE for a in occupants if a in sim.agents)
            if awake and rect.colliderect(view):
                frame.fill(light, rect.move(-view.x, -view.y), special_flags=pygame.BLEND_ADD)
        for x, y in self._lamps:
            if view.collidepoint(x, y) or view.colliderect(
                x - LAMP_RADIUS, y - LAMP_RADIUS, 2 * LAMP_RADIUS, 2 * LAMP_RADIUS
            ):
                frame.blit(
                    self._glow,
                    (x - LAMP_RADIUS - view.x, y - LAMP_RADIUS + 10 - view.y),
                    special_flags=pygame.BLEND_ADD,
                )
