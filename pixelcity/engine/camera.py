"""Caméra 2D : conversion monde ↔ écran, déplacement et zoom ENTIER.

Pourquoi un zoom entier (x1, x2, x3, x4) ? En pixel art, un zoom de 1,5
donnerait des pixels de tailles inégales (certains de 1, d'autres de 2
pixels écran) : l'image « scintille » quand la caméra bouge. Avec un zoom
entier, chaque pixel du jeu devient un carré net de N×N pixels écran.

Autre piège : arrondir de façon incohérente (la carte d'un côté, les
sprites de l'autre) fait trembler les personnages d'un pixel. Ici, tout
passe par `offset()`, arrondi UNE seule fois par image.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_ZOOM, MAX_ZOOM = 1, 4


@dataclass(slots=True)
class Camera:
    view_width: int
    view_height: int
    world_width: int  # taille de la carte en pixels (zoom 1)
    world_height: int
    center_x: float
    center_y: float
    zoom: int = 2

    @classmethod
    def centered(cls, view: tuple[int, int], world: tuple[int, int], zoom: int) -> Camera:
        camera = cls(view[0], view[1], world[0], world[1], world[0] / 2, world[1] / 2, zoom)
        camera.clamp()
        return camera

    def resize(self, width: int, height: int) -> None:
        self.view_width, self.view_height = width, height
        self.clamp()

    def move(self, dx_screen: float, dy_screen: float) -> None:
        """Déplace la caméra d'une distance exprimée en pixels ÉCRAN."""
        self.center_x += dx_screen / self.zoom
        self.center_y += dy_screen / self.zoom
        self.clamp()

    def zoom_at(self, new_zoom: int, screen_x: int, screen_y: int) -> None:
        """Change le zoom en gardant fixe le point du monde situé sous la souris."""
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        if new_zoom == self.zoom:
            return
        world_x, world_y = self.screen_to_world(screen_x, screen_y)
        self.zoom = new_zoom
        self.center_x = world_x - (screen_x - self.view_width / 2) / new_zoom
        self.center_y = world_y - (screen_y - self.view_height / 2) / new_zoom
        self.clamp()

    def clamp(self) -> None:
        """Empêche de sortir de la carte ; la centre si elle est plus petite que l'écran."""
        half_w = self.view_width / (2 * self.zoom)
        half_h = self.view_height / (2 * self.zoom)
        if self.world_width <= 2 * half_w:
            self.center_x = self.world_width / 2
        else:
            self.center_x = min(max(self.center_x, half_w), self.world_width - half_w)
        if self.world_height <= 2 * half_h:
            self.center_y = self.world_height / 2
        else:
            self.center_y = min(max(self.center_y, half_h), self.world_height - half_h)

    def offset(self) -> tuple[int, int]:
        """Décalage entier tel que : écran = monde × zoom + offset."""
        return (
            round(self.view_width / 2 - self.center_x * self.zoom),
            round(self.view_height / 2 - self.center_y * self.zoom),
        )

    def world_to_screen(self, world_x: float, world_y: float) -> tuple[int, int]:
        ox, oy = self.offset()
        return round(world_x * self.zoom) + ox, round(world_y * self.zoom) + oy

    def screen_to_world(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        ox, oy = self.offset()
        return (screen_x - ox) / self.zoom, (screen_y - oy) / self.zoom
