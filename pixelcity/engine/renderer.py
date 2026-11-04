"""Rendu de la ville : carte pré-rendue, étiquettes des lieux, habitants.

Le renderer LIT l'état de la simulation et ne le modifie jamais.

Optimisation principale : la carte ne bouge pas, donc on la dessine UNE
fois dans une grande image (« baking »), une par niveau de zoom. Chaque
image affichée ne fait alors qu'une seule copie au lieu de 1 536 tuiles.
"""

from __future__ import annotations

import pygame
import pytmx  # ici, pytmx a le droit d'importer pygame : on est dans le moteur

from pixelcity.agents.agent import Agent
from pixelcity.engine.camera import Camera
from pixelcity.sim.simulation import Simulation
from pixelcity.world.place import Place

BACKGROUND = (24, 26, 32)
LABEL_TEXT = (245, 242, 230)
LABEL_BG = (20, 22, 28, 170)


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


class Renderer:
    def __init__(self, sim: Simulation) -> None:
        world = sim.world
        self.tile_w, self.tile_h = world.tile_width, world.tile_height
        self.world_size = (world.width * self.tile_w, world.height * self.tile_h)
        self._base = self._bake_map(sim)
        self._baked: dict[int, pygame.Surface] = {1: self._base}
        self._label_font = pygame.font.Font(None, 18)
        self._labels: dict[str, pygame.Surface] = {
            place.id: self._make_label(place.name) for place in world.places.values()
        }
        self._sprites: dict[tuple[str, int], pygame.Surface] = {}

    # ------------------------------------------------------------------ #
    # Préparation (une seule fois)
    # ------------------------------------------------------------------ #
    def _bake_map(self, sim: Simulation) -> pygame.Surface:
        tmx = pytmx.util_pygame.load_pygame(str(sim.world.map_path))
        surface = pygame.Surface(self.world_size).convert()
        surface.fill(BACKGROUND)
        for layer in tmx.visible_layers:
            if isinstance(layer, pytmx.TiledTileLayer):
                for x, y, image in layer.tiles():
                    surface.blit(image, (x * self.tile_w, y * self.tile_h))
        return surface

    def _make_label(self, text: str) -> pygame.Surface:
        rendered = self._label_font.render(text, True, LABEL_TEXT)
        padding = 4
        label = pygame.Surface(
            (rendered.get_width() + 2 * padding, rendered.get_height() + 2), pygame.SRCALPHA
        )
        pygame.draw.rect(label, LABEL_BG, label.get_rect(), border_radius=4)
        label.blit(rendered, (padding, 1))
        return label

    def baked_map(self, zoom: int) -> pygame.Surface:
        """Carte à l'échelle `zoom`, mise en cache.

        `transform.scale` agrandit au plus proche voisin : les pixels restent
        nets. (`smoothscale` lisserait et rendrait le pixel art flou.)
        """
        surface = self._baked.get(zoom)
        if surface is None:
            width, height = self.world_size
            surface = pygame.transform.scale(self._base, (width * zoom, height * zoom))
            self._baked[zoom] = surface
        return surface

    def _sprite(self, agent: Agent, zoom: int) -> pygame.Surface:
        """Placeholder : un rond coloré avec l'initiale. Mis en cache par zoom."""
        key = (agent.id, zoom)
        sprite = self._sprites.get(key)
        if sprite is None:
            size = self.tile_w * zoom
            sprite = pygame.Surface((size, size), pygame.SRCALPHA)
            color = hex_to_rgb(agent.profile.color)
            outline = tuple(int(c * 0.55) for c in color)
            center = (size // 2, size // 2)
            radius = max(3, int(size * 0.42))
            pygame.draw.circle(sprite, outline, center, radius)
            pygame.draw.circle(sprite, color, center, max(2, radius - max(1, zoom)))
            if zoom >= 2:
                font = pygame.font.Font(None, max(12, int(size * 0.75)))
                letter = font.render(agent.name[0], True, (255, 255, 255))
                sprite.blit(letter, letter.get_rect(center=(center[0], center[1] + 1)))
            self._sprites[key] = sprite
        return sprite

    # ------------------------------------------------------------------ #
    # Dessin (à chaque image)
    # ------------------------------------------------------------------ #
    def draw(self, screen: pygame.Surface, sim: Simulation, camera: Camera, alpha: float) -> None:
        screen.fill(BACKGROUND)
        screen.blit(self.baked_map(camera.zoom), camera.offset())
        for place in sim.world.places.values():
            self._draw_place(screen, sim, place, camera)
        self._draw_agents(screen, sim, camera, alpha)

    def agent_screen_pos(self, agent: Agent, camera: Camera, alpha: float) -> tuple[int, int]:
        """Position écran du CENTRE de l'agent, interpolée entre les deux derniers ticks."""
        (px, py), (cx, cy) = agent.prev_pos, agent.pos
        x = px + (cx - px) * alpha
        y = py + (cy - py) * alpha
        return camera.world_to_screen((x + 0.5) * self.tile_w, (y + 0.5) * self.tile_h)

    def _draw_place(
        self, screen: pygame.Surface, sim: Simulation, place: Place, camera: Camera
    ) -> None:
        area = place.area
        top_center_x = (area.x + area.width / 2) * self.tile_w
        label = self._labels[place.id]
        sx, sy = camera.world_to_screen(top_center_x, area.y * self.tile_h)
        screen.blit(label, (sx - label.get_width() // 2, sy - label.get_height() - 2))
        if place.outdoor or not place.occupants:
            return
        # Les habitants à l'intérieur sont cachés : une pastille de leur couleur
        # au-dessus de la porte indique qui est là.
        ex, ey = place.entrances[0]
        dot = max(3, 2 * camera.zoom)
        door_x, door_y = camera.world_to_screen((ex + 0.5) * self.tile_w, ey * self.tile_h)
        count = len(place.occupants)
        start_x = door_x - (count - 1) * (dot * 2 + 2) // 2
        above_door = (
            door_y - dot - 2 if ey > area.y else door_y + self.tile_h * camera.zoom + dot + 2
        )
        for index, agent_id in enumerate(place.occupants):
            color = hex_to_rgb(sim.agents[agent_id].profile.color)
            center = (start_x + index * (dot * 2 + 2), above_door)
            pygame.draw.circle(screen, (15, 15, 20), center, dot + 1)
            pygame.draw.circle(screen, color, center, dot)

    def _draw_agents(
        self, screen: pygame.Surface, sim: Simulation, camera: Camera, alpha: float
    ) -> None:
        visible = [agent for agent in sim.agents.values() if sim.is_visible(agent)]
        positioned = [(self.agent_screen_pos(agent, camera, alpha), agent) for agent in visible]
        # Tri par y (« y-sorting ») : celui qui est plus bas à l'écran passe devant.
        positioned.sort(key=lambda item: item[0][1])
        for (sx, sy), agent in positioned:
            sprite = self._sprite(agent, camera.zoom)
            size = sprite.get_width()
            shadow = pygame.Rect(0, 0, int(size * 0.6), max(2, size // 6))
            shadow.center = (sx, sy + int(size * 0.38))
            pygame.draw.ellipse(screen, (20, 30, 20), shadow)
            screen.blit(sprite, (sx - size // 2, sy - size // 2))
