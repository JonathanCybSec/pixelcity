"""Traduction des événements clavier/souris en intentions de jeu.

Point important pour un clavier AZERTY : on lit les SCANCODES, c'est-à-dire
la position PHYSIQUE des touches, et non le caractère produit.
- Les touches de déplacement sont celles qu'on appelle WASD sur un clavier
  QWERTY : sur ton AZERTY, ce sont Z, Q, S, D. Même code, les deux claviers
  fonctionnent.
- Sur AZERTY, la touche « 1 » de la rangée du haut produit « & » sans Maj :
  avec le keycode K_1, il faudrait appuyer sur Maj. Avec le scancode, non.

La souris distingue le CLIC du GLISSER : on ne sait qu'au relâchement si
l'utilisateur voulait sélectionner (il n'a presque pas bougé) ou déplacer la
caméra (il a glissé de plus de quelques pixels).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pygame

DRAG_THRESHOLD = 5  # pixels : en dessous, c'est un clic


class ActionKind(Enum):
    QUIT = auto()
    TOGGLE_PAUSE = auto()
    SET_SPEED = auto()
    ZOOM = auto()
    TOGGLE_DEBUG = auto()
    TOGGLE_UI = auto()
    TOGGLE_FOLLOW = auto()
    TOGGLE_LIGHTING = auto()
    NEXT_AGENT = auto()
    ESCAPE = auto()
    CLICK = auto()  # clic gauche sans glisser (sélection)
    DRAG = auto()  # déplacement de la caméra à la souris (value = dx, pos = (dx, dy))


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
        self._press: tuple[int, int] | None = None  # où le bouton a été enfoncé
        self._last: tuple[int, int] = (0, 0)
        self._dragging = False

    def handle(self, event: pygame.event.Event) -> Action | None:
        if event.type == pygame.QUIT:
            return Action(ActionKind.QUIT)
        if event.type == pygame.WINDOWFOCUSLOST:
            # Piège : si on relâche une touche pendant que la fenêtre n'a pas
            # le focus, on ne reçoit jamais le KEYUP et la caméra file seule.
            self._held.clear()
            self._press = None
        elif event.type == pygame.KEYUP:
            self._held.discard(event.scancode)
        elif event.type == pygame.KEYDOWN:
            self._held.add(event.scancode)
            return self._key_action(event)
        elif event.type == pygame.MOUSEWHEEL:
            x, y = pygame.mouse.get_pos()
            return Action(ActionKind.ZOOM, 1 if event.y > 0 else -1, (x, y))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2, 3):
            self._press = event.pos
            self._last = event.pos
            self._dragging = event.button != 1  # clic droit / molette : toujours un glisser
        elif event.type == pygame.MOUSEMOTION and self._press is not None:
            x, y = event.pos
            if not self._dragging:
                px, py = self._press
                self._dragging = abs(x - px) + abs(y - py) > DRAG_THRESHOLD
            if self._dragging:
                lx, ly = self._last
                self._last = event.pos
                return Action(ActionKind.DRAG, 0, (x - lx, y - ly))
            self._last = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2, 3):
            was_click = self._press is not None and not self._dragging and event.button == 1
            self._press = None
            self._dragging = False
            if was_click:
                return Action(ActionKind.CLICK, 0, event.pos)
        return None

    def _key_action(self, event: pygame.event.Event) -> Action | None:
        keys = {
            pygame.K_ESCAPE: ActionKind.ESCAPE,
            pygame.K_SPACE: ActionKind.TOGGLE_PAUSE,
            pygame.K_F3: ActionKind.TOGGLE_DEBUG,
            pygame.K_TAB: ActionKind.NEXT_AGENT,
        }
        if event.key in keys:
            return Action(keys[event.key])
        scancodes = {
            pygame.KSCAN_H: ActionKind.TOGGLE_UI,
            pygame.KSCAN_F: ActionKind.TOGGLE_FOLLOW,
            pygame.KSCAN_L: ActionKind.TOGGLE_LIGHTING,
        }
        if event.scancode in scancodes:
            return Action(scancodes[event.scancode])
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
