"""Petits composants de formulaire en « mode immédiat » : champ texte, curseur, choix, bouton.

Deux grandes familles d'interfaces graphiques :
- le mode RETENU (Qt, le DOM d'une page web) : on crée des objets « bouton »
  qui vivent longtemps et gardent leur état ;
- le mode IMMÉDIAT (Dear ImGui, très utilisé dans les outils de jeux vidéo) :
  à chaque image, on redessine tout et l'appel `if form.button(...)` renvoie
  True si l'on vient de cliquer dessus. La seule vérité, ce sont vos données.

On choisit le mode immédiat : avec pygame, qui ne fournit aucun widget, c'est
de loin le plus simple. Un formulaire = une fonction qui lit et écrit un
brouillon (`AgentDraft`), rien à synchroniser.

Saisie de texte : on écoute l'événement TEXTINPUT (et non KEYDOWN) parce
qu'il gère les accents, les touches mortes (^ puis e = ê) et les claviers
AZERTY. KEYDOWN ne sert qu'aux touches d'édition (effacer, Entrée, Tab).
"""

from __future__ import annotations

import time

import pygame

from pixelcity.ui.glass import rounded
from pixelcity.ui.theme import (
    ACCENT,
    ACTIVE_FILL,
    HOVER_FILL,
    MUTED,
    TEXT,
    TEXT_2,
    TRACK,
    TextCache,
    Weight,
)
from pixelcity.ui.widgets import label

FIELD_FILL = (255, 255, 255, 16)
FIELD_FOCUS = (124, 196, 255, 40)
PRIMARY_FILL = (124, 196, 255, 210)
PRIMARY_TEXT = (16, 24, 40)


class Form:
    def __init__(self, texts: TextCache) -> None:
        self.texts = texts
        self.mouse: tuple[int, int] = (0, 0)
        self.click: tuple[int, int] | None = None  # clic de cette image (consommé par un widget)
        self.wheel = 0
        self.focus: str | None = None
        self.buffer = ""
        self.dragging: str | None = None
        self.submitted = False  # Entrée pressée dans un champ
        self.escape = False
        self._consumed = False
        self._focus_seen = False

    # ------------------------------------------------------------------ #
    # Événements (avant de dessiner)
    # ------------------------------------------------------------------ #
    def begin(self, events: list[pygame.event.Event]) -> None:
        self.mouse = pygame.mouse.get_pos()
        self.click = None
        self.wheel = 0
        self.submitted = False
        self.escape = False
        self._consumed = False
        self._focus_seen = False
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.click = event.pos
                self.mouse = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.dragging = None
            elif event.type == pygame.MOUSEWHEEL:
                self.wheel += event.y
            elif event.type == pygame.TEXTINPUT and self.focus is not None:
                self.buffer += event.text
            elif event.type == pygame.KEYDOWN:
                self._key(event)

    def _key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_ESCAPE:
            if self.focus is not None:
                self.focus = None
            else:
                self.escape = True
            return
        if self.focus is None:
            return
        if event.key == pygame.K_BACKSPACE:
            if event.mod & pygame.KMOD_CTRL:
                self.buffer = self.buffer.rstrip().rpartition(" ")[0]
            else:
                self.buffer = self.buffer[:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
            self.submitted = True

    def end(self) -> None:
        """Après avoir dessiné : un clic dans le vide retire le focus du champ texte."""
        if self.click is not None and not self._consumed:
            self.focus = None
        if self.focus is not None and not self._focus_seen:
            self.focus = None  # le champ n'est plus affiché (autre habitant sélectionné)
        if self.focus is None:
            pygame.key.stop_text_input()

    def _clicked(self, rect: pygame.Rect) -> bool:
        if self.click is not None and not self._consumed and rect.collidepoint(self.click):
            self._consumed = True
            return True
        return False

    def hovered(self, rect: pygame.Rect) -> bool:
        return rect.collidepoint(self.mouse)

    # ------------------------------------------------------------------ #
    # Composants
    # ------------------------------------------------------------------ #
    def text(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        key: str,
        value: str,
        *,
        placeholder: str = "",
        max_len: int = 120,
    ) -> str:
        focused = self.focus == key
        if self._clicked(rect) and not focused:
            self.focus, self.buffer, focused = key, value, True
            pygame.key.start_text_input()
            pygame.key.set_text_input_rect(rect)
        if focused:
            self._focus_seen = True
            self.buffer = self.buffer[:max_len]
            value = self.buffer
            if self.submitted:
                self.focus = None
        rounded(screen, rect, FIELD_FOCUS if focused else FIELD_FILL, 8)
        if focused:
            rounded(screen, rect, (*ACCENT, 160), 8, width=1)
        shown = value if value or focused else placeholder
        color = TEXT if value else MUTED
        inner = rect.width - 20
        # Le texte trop long défile : on montre la FIN quand on tape, le début sinon.
        if self.texts.fonts.get(13).size(shown)[0] > inner:
            if focused:
                while shown and self.texts.fonts.get(13).size("…" + shown)[0] > inner:
                    shown = shown[1:]
                shown = "…" + shown
            else:
                shown = self.texts.fit(shown, 13, inner)
        text_rect = label(
            screen,
            self.texts,
            shown,
            (rect.x + 10, rect.centery),
            size=13,
            color=color,
            anchor="midleft",
        )
        if focused and int(time.monotonic() * 2) % 2 == 0:
            x = text_rect.right + 1 if value else rect.x + 10
            pygame.draw.line(screen, ACCENT, (x, rect.y + 7), (x, rect.bottom - 7), 2)
        return value

    def slider(self, screen: pygame.Surface, rect: pygame.Rect, key: str, value: float) -> float:
        """Valeur entre 0 et 1 ; on clique ou on fait glisser."""
        if self._clicked(rect.inflate(0, 12)):
            self.dragging = key
        if self.dragging == key:
            if not pygame.mouse.get_pressed()[0]:
                self.dragging = None
            value = (self.mouse[0] - rect.x) / max(1, rect.width)
        value = min(1.0, max(0.0, value))
        track = pygame.Rect(rect.x, rect.centery - 3, rect.width, 6)
        rounded(screen, track, TRACK, 3)
        filled = track.copy()
        filled.width = max(6, round(track.width * value))
        rounded(screen, filled, (*ACCENT, 200), 3)
        knob = (rect.x + round(rect.width * value), rect.centery)
        pygame.draw.circle(screen, (245, 247, 252), knob, 8)
        pygame.draw.circle(screen, ACCENT, knob, 8, width=2)
        return value

    def choice(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        options: list[str],
        index: int,
    ) -> int:
        """◀ option ▶ : un clic à gauche recule, à droite avance (en boucle)."""
        if not options:
            return 0
        index %= len(options)
        left = pygame.Rect(rect.x, rect.y, 30, rect.height)
        right = pygame.Rect(rect.right - 30, rect.y, 30, rect.height)
        if self._clicked(left):
            index = (index - 1) % len(options)
        elif self._clicked(right):
            index = (index + 1) % len(options)
        elif self.hovered(rect) and self.wheel:
            index = (index - self.wheel) % len(options)
            self.wheel = 0
        rounded(screen, rect, FIELD_FILL, 8)
        for arrow, direction in ((left, -1), (right, 1)):
            if self.hovered(arrow):
                rounded(screen, arrow, HOVER_FILL, 8)
            cx, cy = arrow.center
            points = [
                (cx + 4 * direction, cy),
                (cx - 3 * direction, cy - 6),
                (cx - 3 * direction, cy + 6),
            ]
            pygame.draw.polygon(screen, TEXT_2, points)
        text = self.texts.fit(options[index], 13, rect.width - 70)
        label(screen, self.texts, text, rect.center, size=13, anchor="center")
        return index

    def toggle(self, screen: pygame.Surface, rect: pygame.Rect, value: bool, text: str) -> bool:
        switch = pygame.Rect(rect.x, rect.centery - 11, 40, 22)
        if self._clicked(rect):
            value = not value
        rounded(screen, switch, (*ACCENT, 200) if value else TRACK, 11)
        knob_x = switch.right - 11 if value else switch.x + 11
        pygame.draw.circle(screen, (245, 247, 252), (knob_x, switch.centery), 8)
        label(
            screen,
            self.texts,
            text,
            (switch.right + 10, rect.centery),
            size=13,
            color=TEXT if value else TEXT_2,
            anchor="midleft",
        )
        return value

    def button(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        *,
        primary: bool = False,
        enabled: bool = True,
        size: int = 13,
    ) -> bool:
        hovered = enabled and self.hovered(rect)
        if primary:
            fill = PRIMARY_FILL if enabled else (124, 196, 255, 70)
            if hovered:
                fill = (150, 210, 255, 235)
            color = PRIMARY_TEXT
        else:
            fill = ACTIVE_FILL if hovered else FIELD_FILL
            color = TEXT if enabled else MUTED
        rounded(screen, rect, fill, rect.height // 2)
        label(
            screen,
            self.texts,
            text,
            rect.center,
            size=size,
            color=color,
            weight=Weight.SEMIBOLD,
            anchor="center",
        )
        return self._clicked(rect) and enabled
