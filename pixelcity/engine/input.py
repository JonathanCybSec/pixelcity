"""Traduction des événements clavier/souris en intentions de jeu.

Point important pour un clavier AZERTY : on lit les SCANCODES, c'est-à-dire
la position PHYSIQUE des touches, et non le caractère produit.
- Les touches de déplacement sont celles qu'on appelle WASD sur un clavier
  QWERTY : sur ton AZERTY, ce sont Z, Q, S, D. Même code, les deux claviers
  fonctionnent.
- Sur AZERTY, la touche « 1 » de la rangée du haut produit « & » sans Maj :
  avec le keycode K_1, il faudrait appuyer sur Maj. Avec le scancode, non.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pygame


class ActionKind(Enum):
    QUIT = auto()
    TOGGLE_PAUSE = auto()
    SET_SPEED = auto()
    ZOOM = auto()
    TOGGLE_DEBUG = auto()


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    value: int = 0
    pos: tuple[int, int] = (0, 0)


_MOVE_SCANCODES: dict[int, tuple[int, int]] = {
    pygame.KSCAN_W: (0, -1),
    pygame.KSCAN_S: (0, 1),
    pygame.KSCAN_A: (-1, 0),
    pygame.KSCAN_D: (1, 0),
    pygame.KSCAN_UP: (0, -1),
    pygame.KSCAN_DOWN: (0, 1),
    pygame.KSCAN_LEFT: (-1, 0),
    pygame.KSCAN_RIGHT: (1, 0),
}
_SPEED_SCANCODES = (pygame.KSCAN_1, pygame.KSCAN_2, pygame.KSCAN_3, pygame.KSCAN_4)
_SPEED_KEYPAD = (pygame.K_KP1, pygame.K_KP2, pygame.K_KP3, pygame.K_KP4)


class InputState:
    def __init__(self) -> None:
        self._held: set[int] = set()

    def handle(self, event: pygame.event.Event) -> Action | None:
        if event.type == pygame.QUIT:
            return Action(ActionKind.QUIT)
        if event.type == pygame.WINDOWFOCUSLOST:
            # Piège : si on relâche une touche pendant que la fenêtre n'a pas
            # le focus, on ne reçoit jamais le KEYUP et la caméra file seule.
            self._held.clear()
        elif event.type == pygame.KEYUP:
            self._held.discard(event.scancode)
        elif event.type == pygame.KEYDOWN:
            self._held.add(event.scancode)
            return self._key_action(event)
        elif event.type == pygame.MOUSEWHEEL:
            x, y = pygame.mouse.get_pos()
            return Action(ActionKind.ZOOM, 1 if event.y > 0 else -1, (x, y))
        return None

    def _key_action(self, event: pygame.event.Event) -> Action | None:
        if event.key == pygame.K_ESCAPE:
            return Action(ActionKind.QUIT)
        if event.key == pygame.K_SPACE:
            return Action(ActionKind.TOGGLE_PAUSE)
        if event.key == pygame.K_F3:
            return Action(ActionKind.TOGGLE_DEBUG)
        if event.key in (pygame.K_KP_PLUS, pygame.K_PAGEUP):
            return Action(ActionKind.ZOOM, 1, pygame.mouse.get_pos())
        if event.key in (pygame.K_KP_MINUS, pygame.K_PAGEDOWN):
            return Action(ActionKind.ZOOM, -1, pygame.mouse.get_pos())
        for index, (scancode, keypad) in enumerate(
            zip(_SPEED_SCANCODES, _SPEED_KEYPAD, strict=True)
        ):
            if event.scancode == scancode or event.key == keypad:
                return Action(ActionKind.SET_SPEED, index)
        return None

    def camera_direction(self) -> tuple[int, int]:
        dx = sum(_MOVE_SCANCODES[code][0] for code in self._held if code in _MOVE_SCANCODES)
        dy = sum(_MOVE_SCANCODES[code][1] for code in self._held if code in _MOVE_SCANCODES)
        return max(-1, min(1, dx)), max(-1, min(1, dy))
