"""Panneaux en « verre dépoli » : flou de ce qu'il y a derrière + voile translucide.

Recette (la même que le « glassmorphism » des interfaces web, en pygame) :
1. une ombre douce sous le panneau (rectangle arrondi flouté, mis en cache) ;
2. on copie la zone de l'écran DERRIÈRE le panneau, on la réduit ×4, on la
   floute (pygame-ce : `transform.gaussian_blur`) et on la ré-agrandit :
   flouter une petite image coûte 16 fois moins cher qu'une grande, et
   l'agrandissement lissé finit le travail ;
3. un voile sombre translucide, un liseré clair d'1 pixel en haut, un contour.

Piège : il faut dessiner le panneau APRÈS le monde (on floute ce qui est
déjà à l'écran). C'est pourquoi l'interface se dessine en dernier.
"""

from __future__ import annotations

import pygame

from pixelcity.ui.theme import GLASS_BORDER, GLASS_FILL, GLASS_HIGHLIGHT, RADIUS, RGBA, SHADOW

BLUR_DOWNSCALE = 4
BLUR_RADIUS = 3
SHADOW_SPREAD = 10


class Glass:
    def __init__(self) -> None:
        self._masks: dict[tuple[int, int, int], pygame.Surface] = {}
        self._shadows: dict[tuple[int, int, int], pygame.Surface] = {}
        self._blurred: pygame.Surface | None = None
        self.blur_enabled = True

    def begin_frame(self, screen: pygame.Surface) -> None:
        """Appelé avant les panneaux : rien à préparer pour l'instant (point d'extension)."""
        self._blurred = None

    def mask(self, width: int, height: int, radius: int) -> pygame.Surface:
        """Masque blanc opaque en rectangle arrondi (multiplié avec l'image floutée)."""
        key = (width, height, radius)
        mask = self._masks.get(key)
        if mask is None:
            mask = pygame.Surface((width, height), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
            self._masks[key] = mask
        return mask

    def _shadow(self, width: int, height: int, radius: int) -> pygame.Surface:
        key = (width, height, radius)
        shadow = self._shadows.get(key)
        if shadow is None:
            spread = SHADOW_SPREAD
            shadow = pygame.Surface((width + 2 * spread, height + 2 * spread), pygame.SRCALPHA)
            pygame.draw.rect(
                shadow, SHADOW, (spread, spread, width, height), border_radius=radius + 2
            )
            shadow = pygame.transform.gaussian_blur(shadow, 6)
            self._shadows[key] = shadow
        return shadow

    def panel(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        *,
        radius: int = RADIUS,
        fill: RGBA = GLASS_FILL,
        border: RGBA = GLASS_BORDER,
        shadow: bool = True,
    ) -> None:
        rect = rect.clip(screen.get_rect())
        if rect.width < 4 or rect.height < 4:
            return
        if shadow:
            screen.blit(
                self._shadow(rect.width, rect.height, radius),
                (rect.x - SHADOW_SPREAD, rect.y - SHADOW_SPREAD + 4),
            )
        if self.blur_enabled:
            # Réduction au plus proche voisin (rapide) : le flou gomme ensuite l'aliasing.
            small_size = (
                max(1, rect.width // BLUR_DOWNSCALE),
                max(1, rect.height // BLUR_DOWNSCALE),
            )
            small = pygame.transform.scale(screen.subsurface(rect), small_size)
            small = pygame.transform.gaussian_blur(small, BLUR_RADIUS)
            blurred = pygame.transform.smoothscale(small, rect.size).convert_alpha()
            blurred.blit(
                self.mask(rect.width, rect.height, radius),
                (0, 0),
                special_flags=pygame.BLEND_RGBA_MULT,
            )
            screen.blit(blurred, rect.topleft)
        veil = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(veil, fill, veil.get_rect(), border_radius=radius)
        pygame.draw.line(veil, GLASS_HIGHLIGHT, (radius, 1), (rect.width - radius, 1))
        pygame.draw.rect(veil, border, veil.get_rect(), width=1, border_radius=radius)
        screen.blit(veil, rect.topleft)


def rounded(
    screen: pygame.Surface, rect: pygame.Rect, color: RGBA, radius: int, width: int = 0
) -> None:
    """Rectangle arrondi avec transparence (pygame.draw ignore l'alpha sur l'écran)."""
    if rect.width <= 0 or rect.height <= 0:
        return
    if len(color) == 4 and color[3] < 255:
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, color, layer.get_rect(), width=width, border_radius=radius)
        screen.blit(layer, rect.topleft)
    else:
        pygame.draw.rect(screen, color, rect, width=width, border_radius=radius)
