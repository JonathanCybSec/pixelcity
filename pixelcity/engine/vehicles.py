"""Le bus et ses arrêts, dessinés par le code en pixel art (comme nos meubles).

Pas d'image à charger : le bus est un petit dessin de 48×26 pixels (trois
tuiles de long), fait de rectangles et de quelques pixels. Les couleurs
reprennent la palette douce de pixel-agents ; on le retourne pour l'ouest.
"""

from __future__ import annotations

import pygame

BODY = (232, 180, 64)
BODY_DARK = (186, 132, 40)
ROOF = (246, 214, 120)
WINDOW = (126, 182, 214)
WINDOW_DARK = (82, 128, 160)
WHEEL = (40, 42, 52)
HUB = (150, 150, 160)
LIGHT = (255, 240, 170)
OUTLINE = (52, 40, 30)
SIGN = (70, 120, 200)
POLE = (90, 96, 110)


def bus_sprite(*, eastbound: bool) -> pygame.Surface:
    w, h = 48, 26
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, OUTLINE, (1, 3, w - 2, 19), border_radius=4)
    pygame.draw.rect(s, BODY, (2, 4, w - 4, 17), border_radius=3)
    pygame.draw.rect(s, ROOF, (4, 4, w - 8, 3))
    pygame.draw.rect(s, BODY_DARK, (2, 17, w - 4, 4))
    for x in range(6, w - 12, 8):  # vitres
        pygame.draw.rect(s, WINDOW, (x, 8, 6, 6))
        pygame.draw.line(s, WINDOW_DARK, (x, 13), (x + 5, 13))
    pygame.draw.rect(s, WINDOW, (w - 10, 8, 6, 8))  # pare-brise (avant à droite)
    pygame.draw.rect(s, LIGHT, (w - 4, 16, 2, 2))
    for x in (10, w - 14):  # roues
        pygame.draw.circle(s, WHEEL, (x, 21), 4)
        pygame.draw.circle(s, HUB, (x, 21), 1)
    return s if eastbound else pygame.transform.flip(s, True, False)


def stop_sprite() -> pygame.Surface:
    s = pygame.Surface((12, 26), pygame.SRCALPHA)
    pygame.draw.rect(s, POLE, (5, 8, 2, 18))
    pygame.draw.rect(s, OUTLINE, (0, 0, 12, 10), border_radius=2)
    pygame.draw.rect(s, SIGN, (1, 1, 10, 8), border_radius=2)
    pygame.draw.rect(s, (240, 240, 250), (3, 3, 6, 2))  # le « B » stylisé
    pygame.draw.rect(s, (240, 240, 250), (3, 6, 6, 1))
    return s
