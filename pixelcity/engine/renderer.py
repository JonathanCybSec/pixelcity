"""Rendu du monde : tout est dessiné à la résolution du pixel art, puis agrandi.

Principe (celui des jeux pixel art « pixel perfect ») :
1. on dessine la portion visible du monde dans une petite image `frame`
   où 1 pixel = 1 pixel de sprite (≈ 430×240 à l'écran 1280×720 en zoom 3) ;
2. on l'agrandit d'un facteur ENTIER, au plus proche voisin ;
3. on la pose à l'écran avec un décalage de quelques pixels écran, ce qui
   rend le défilement fluide même si chaque sprite reste sur sa grille.

Avantages : les pixels restent tous de la même taille (pas de scintillement),
et le coût ne dépend pas du zoom (on trie et on dessine ~200 sprites de 16 px,
puis UNE seule mise à l'échelle).

Le renderer LIT l'état de la simulation et ne le modifie jamais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from pixelcity.agents.agent import Agent
from pixelcity.engine.camera import Camera
from pixelcity.engine.lighting import Lighting
from pixelcity.engine.scene import Prop, Scene, bake_ground, build_scene
from pixelcity.engine.sprites import (
    IDLE_FRAME,
    READ_FRAMES,
    TILE,
    TYPE_FRAMES,
    WALK_CYCLE,
    SpriteBank,
)
from pixelcity.resources import assets_dir
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import Anim, Pose

BACKGROUND = (22, 24, 30)
SITTING_OFFSET = 6  # pixel-agents : un personnage assis descend de 6 px dans sa chaise
CHARACTER_Z_OFFSET = TILE / 2 + 0.5  # tri : bas de la tuile, pour passer devant la chaise
WALK_PIXELS_PER_FRAME = 5  # la marche s'anime à la distance parcourue, pas au temps
HEAD_ON_PILLOW_Y = 11  # position de la tête dans le sprite du lit (16×48)
OUTLINE_COLOR = (255, 255, 255, 235)


@dataclass(slots=True)
class Drawable:
    z: float
    x: int
    y: int
    image: pygame.Surface


class WorldRenderer:
    def __init__(self, sim: Simulation) -> None:
        world = sim.world
        assets = assets_dir()
        self.bank = SpriteBank(
            assets / "pixel_agents" / "characters", world.map_path.parent / "walls"
        )
        self.scene: Scene = build_scene(world, self.bank, bake_ground(world.map_path))
        self.world_size = (self.scene.width, self.scene.height)
        self.lighting = Lighting(sim, self.scene)
        self._frame: pygame.Surface | None = None
        self._scaled: pygame.Surface | None = None
        self._outlines: dict[int, pygame.Surface] = {}
        self.selected_id: str | None = None
        self.hovered_id: str | None = None
        self.last_origin = (0, 0)  # coin haut-gauche du monde dessiné (en pixels monde)

    # ------------------------------------------------------------------ #
    # Positions (aussi utilisées par l'interface pour placer les bulles)
    # ------------------------------------------------------------------ #
    def agent_world_pos(self, agent: Agent, alpha: float) -> tuple[float, float]:
        """Position des PIEDS de l'habitant, en pixels monde, interpolée entre deux ticks."""
        (px, py), (cx, cy) = agent.prev_pos, agent.pos
        x = px + (cx - px) * alpha
        y = py + (cy - py) * alpha
        return (x + 0.5) * TILE, (y + 0.5) * TILE

    def agent_head_screen(self, agent: Agent, camera: Camera, alpha: float) -> tuple[int, int]:
        """Point écran au-dessus de la tête (pour une bulle ou un marqueur)."""
        x, y = self.agent_world_pos(agent, alpha)
        top = y - 30 + (SITTING_OFFSET if agent.pose is Pose.SIT else 0)
        if agent.pose is Pose.LIE:
            top = y - 8
        return camera.world_to_screen(x, top)

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #
    def draw(
        self,
        screen: pygame.Surface,
        sim: Simulation,
        camera: Camera,
        alpha: float,
        seconds: float,
    ) -> None:
        zoom = camera.zoom
        ox, oy = camera.offset()
        sw, sh = screen.get_size()
        left = math.floor(-ox / zoom)
        top = math.floor(-oy / zoom)
        width = math.ceil(sw / zoom) + 2
        height = math.ceil(sh / zoom) + 2
        frame = self._frame_surface(width, height)
        frame.fill(BACKGROUND)
        view = pygame.Rect(left, top, width, height)
        frame.blit(self.scene.ground, (0, 0), area=view)

        drawables = self._collect(sim, view, alpha, seconds)
        drawables.sort(key=lambda d: d.z)
        blit = frame.blit
        for drawable in drawables:
            blit(drawable.image, (drawable.x - left, drawable.y - top))

        self.lighting.apply(frame, view, sim, seconds)

        scaled = self._scaled_surface(width * zoom, height * zoom)
        pygame.transform.scale(frame, scaled.get_size(), scaled)
        screen.fill(BACKGROUND)
        screen.blit(scaled, (left * zoom + ox, top * zoom + oy))
        self.last_origin = (left, top)

    def _collect(
        self, sim: Simulation, view: pygame.Rect, alpha: float, seconds: float
    ) -> list[Drawable]:
        drawables: list[Drawable] = []
        sleepers: dict[str, Agent] = {}
        for agent in sim.agents.values():
            if agent.pose is Pose.LIE and agent.spot is not None:
                sleepers[agent.spot.furniture.uid] = agent
        for prop in self.scene.props_in(view):
            furniture = prop.furniture
            sleeper = sleepers.get(furniture.uid) if furniture is not None else None
            image = prop.image(seconds)
            if sleeper is not None:
                image = self._bed_with_sleeper(prop, image, sleeper)
            drawables.append(Drawable(prop.z, prop.x, prop.y, image))
        for agent in sim.agents.values():
            if agent.pose in (Pose.HIDDEN, Pose.LIE):
                continue
            drawable = self._character(agent, alpha, seconds)
            if drawable is not None and view.colliderect(
                drawable.x, drawable.y, drawable.image.get_width(), drawable.image.get_height()
            ):
                drawables.append(drawable)
                if agent.id in (self.selected_id, self.hovered_id):
                    outline = self._outline(drawable.image)
                    drawables.append(
                        Drawable(drawable.z - 0.01, drawable.x - 1, drawable.y - 1, outline)
                    )
        return drawables

    def _character(self, agent: Agent, alpha: float, seconds: float) -> Drawable | None:
        sheet = self.bank.character(agent.profile.sprite)
        x, y = self.agent_world_pos(agent, alpha)
        facing = agent.facing
        pose = agent.pose
        bob = 0
        if pose is Pose.WALK:
            step = int((x + y) / WALK_PIXELS_PER_FRAME)
            index = WALK_CYCLE[step % len(WALK_CYCLE)]
        elif pose is Pose.RUN:
            index = WALK_CYCLE[int(seconds / 0.1) % len(WALK_CYCLE)]
        elif pose is Pose.SIT:
            if agent.anim is Anim.INTERACT:
                index = TYPE_FRAMES[int(seconds / 0.3) % 2]
            elif agent.anim is Anim.EAT:
                index = READ_FRAMES[int(seconds / 0.45) % 2]
            elif agent.anim in (Anim.READ, Anim.TALK):
                index = (READ_FRAMES if agent.anim is Anim.READ else TYPE_FRAMES)[
                    int(seconds / 0.6) % 2
                ]
            else:
                index = TYPE_FRAMES[0]
        else:
            index = IDLE_FRAME
            if agent.anim in (Anim.INTERACT, Anim.TALK):
                bob = int(seconds / 0.35) % 2  # un léger mouvement : il s'affaire
        image = sheet.frame(facing, index)
        sit = SITTING_OFFSET if pose is Pose.SIT else 0
        draw_x = round(x - image.get_width() / 2)
        draw_y = round(y + sit - image.get_height() - bob)
        z = y + CHARACTER_Z_OFFSET
        spot = agent.spot
        if spot is not None and spot.is_seat and spot.furniture.spec.category != "chairs":
            # Assis sur un banc, couché sur un tapis de course : devant l'objet.
            prop = self.scene.by_furniture.get(spot.furniture.uid)
            if prop is not None:
                z = max(z, prop.z + 0.5)
        return Drawable(z, draw_x, draw_y, image)

    def _bed_with_sleeper(self, prop: Prop, bed: pygame.Surface, sleeper: Agent) -> pygame.Surface:
        """Le lit + la tête du dormeur sur l'oreiller + la couverture par-dessus."""
        composed = bed.copy()
        sheet = self.bank.character(sleeper.profile.sprite)
        composed.blit(sheet.head, (0, HEAD_ON_PILLOW_Y))
        if prop.cover is not None:
            composed.blit(prop.cover, (0, 0))
        return composed

    def _outline(self, image: pygame.Surface) -> pygame.Surface:
        """Contour blanc d'1 pixel autour du sprite (personnage sélectionné)."""
        key = id(image)
        outline = self._outlines.get(key)
        if outline is None:
            mask = pygame.mask.from_surface(image)
            silhouette = mask.to_surface(setcolor=OUTLINE_COLOR, unsetcolor=(0, 0, 0, 0))
            outline = pygame.Surface(
                (image.get_width() + 2, image.get_height() + 2), pygame.SRCALPHA
            )
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
                outline.blit(silhouette, (dx, dy))
            self._outlines[key] = outline
        return outline

    # ------------------------------------------------------------------ #
    # Surfaces réutilisées (allouer à chaque image coûte cher)
    # ------------------------------------------------------------------ #
    def _frame_surface(self, width: int, height: int) -> pygame.Surface:
        if self._frame is None or self._frame.get_size() != (width, height):
            self._frame = pygame.Surface((width, height))
            if pygame.display.get_surface() is not None:
                self._frame = self._frame.convert()
        return self._frame

    def _scaled_surface(self, width: int, height: int) -> pygame.Surface:
        if self._scaled is None or self._scaled.get_size() != (width, height):
            self._scaled = pygame.Surface((width, height))
            if pygame.display.get_surface() is not None:
                self._scaled = self._scaled.convert()
        return self._scaled

    def pick_agent(
        self, sim: Simulation, camera: Camera, screen_pos: tuple[int, int], alpha: float
    ) -> Agent | None:
        """L'habitant sous la souris (le plus « devant » s'ils se chevauchent)."""
        wx, wy = camera.screen_to_world(*screen_pos)
        best: tuple[float, Agent] | None = None
        for agent in sim.agents.values():
            if agent.pose is Pose.HIDDEN:
                continue
            x, y = self.agent_world_pos(agent, alpha)
            top = y - (12 if agent.pose is Pose.LIE else 28)
            if x - 7 <= wx <= x + 7 and top <= wy <= y + 2 and (best is None or y > best[0]):
                best = (y, agent)
        return best[1] if best else None
