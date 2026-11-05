"""La ligne de bus : deux bus font l'aller-retour sur l'avenue, avec quatre arrêts.

    ouest ◀──────────── voie nord (y = 30) ──────────── est
    ouest ──────────── voie sud  (y = 31) ────────────▶ est
           arrêt        arrêt         arrêt        arrêt
         (Lilas)   (Commerces)   (Bureaux)    (Mimosas)

Chaque arrêt a deux quais : sur le trottoir sud pour aller vers l'est, sur
le trottoir nord pour aller vers l'ouest. Un trajet en bus se décide au
départ, quand l'habitant calcule son chemin :

    marche jusqu'au quai ─▶ attend ─▶ monte (paie) ─▶ voyage ─▶ descend ─▶ marche

On ne prend le bus que s'il fait gagner du temps (5 % au moins),
estimation de l'attente comprise, et si l'on a de quoi payer le ticket.
Dans le bus, l'habitant est caché (on voit le bus) ; la caméra qui le suit
suit donc le bus.

Le bus avance d'une distance fixe par tick, comme les piétons : à x30 il
fait exactement le même trajet qu'à x1, simplement plus vite à l'écran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pixelcity.config.schemas import TransitSettings
from pixelcity.sim.clock import SimClock
from pixelcity.sim.events import EventKind
from pixelcity.sim.types import Facing, Pose, TilePos
from pixelcity.world.world import World

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext

EAST_LANE, WEST_LANE = 31, 30
SOUTH_PLATFORM, NORTH_PLATFORM = 32, 29
STOPS: tuple[tuple[int, str], ...] = (
    (9, "Les Lilas"),
    (47, "Place des Commerces"),
    (79, "Bureaux - École"),
    (111, "Les Mimosas"),
)
CAPACITY = 12
MAX_WAIT_MINUTES = 30  # au-delà, on renonce au bus et l'on marche
GAIN_REQUIRED = 0.95  # le bus doit faire gagner au moins 5 % du temps de marche
WALK_DETOUR = 1.25  # les rues ne vont pas tout droit : distance à vol d'oiseau × 1,25


@dataclass(slots=True)
class Ride:
    agent_id: str
    origin: int  # index de l'arrêt de départ
    destination: int
    eastbound: bool
    platform: TilePos
    state: str = "to_stop"  # to_stop → waiting → onboard → alighted
    since: int = 0  # minute absolue d'arrivée au quai


@dataclass(slots=True, eq=False)
class Bus:
    uid: int
    s: float  # position sur la boucle : 0 → W-1 vers l'est, W → 2W-1 vers l'ouest
    dwell_until: int = 0
    passengers: set[str] = field(default_factory=set)
    prev: tuple[float, float] = (0.0, 0.0)


class Transit:
    def __init__(self, world: World, settings: TransitSettings, clock: SimClock) -> None:
        self.settings = settings
        self.width = world.width
        self.loop = 2 * world.width
        self.enabled = settings.enabled and settings.buses > 0 and self._road_ok(world)
        self.speed_per_tick = settings.speed_tiles_per_minute * clock.tick_seconds / 60
        self.dwell_ticks = round(settings.dwell_minutes * clock.ticks_per_minute)
        self.buses = [
            Bus(i + 1, i * self.loop / max(1, settings.buses)) for i in range(settings.buses)
        ]
        for bus in self.buses:
            bus.prev = self.position(bus)
        self.rides: dict[str, Ride] = {}
        self.trips = 0

    @staticmethod
    def _road_ok(world: World) -> bool:
        """La ligne suppose l'avenue de make_city ; une autre carte la désactive."""
        return (
            all(
                world.grid.is_walkable((x, y))
                for x, _name in STOPS
                for y in (SOUTH_PLATFORM, NORTH_PLATFORM)
                if x < world.width
            )
            and world.height > SOUTH_PLATFORM
        )

    # ------------------------------------------------------------------ #
    # Géométrie
    # ------------------------------------------------------------------ #
    def position(self, bus: Bus) -> tuple[float, float]:
        if bus.s < self.width:
            return (bus.s, float(EAST_LANE))
        return (self.loop - 1 - bus.s, float(WEST_LANE))

    def eastbound(self, bus: Bus) -> bool:
        return bus.s < self.width

    def _stop_s(self, index: int, eastbound: bool) -> float:
        x = STOPS[index][0]
        return float(x) if eastbound else float(self.loop - 1 - x)

    @staticmethod
    def platform(index: int, eastbound: bool) -> TilePos:
        return (STOPS[index][0], SOUTH_PLATFORM if eastbound else NORTH_PLATFORM)

    @staticmethod
    def nearest_stop(tile: TilePos) -> int:
        return min(range(len(STOPS)), key=lambda i: abs(STOPS[i][0] - tile[0]))

    # ------------------------------------------------------------------ #
    # Décider de prendre le bus
    # ------------------------------------------------------------------ #
    def plan(
        self, agent: Agent, goal: TilePos, walk_tiles: int, walk_speed: float, money: float
    ) -> Ride | None:
        if not self.enabled or walk_tiles < self.settings.min_walk_tiles:
            return None
        if money < self.settings.ticket:
            return None
        origin, destination = self.nearest_stop(agent.tile), self.nearest_stop(goal)
        if origin == destination:
            return None
        eastbound = STOPS[destination][0] > STOPS[origin][0]
        start = self.platform(origin, eastbound)
        end = self.platform(destination, eastbound)
        walk_a = _manhattan(agent.tile, start) * WALK_DETOUR
        walk_b = _manhattan(end, goal) * WALK_DETOUR
        distance = abs(STOPS[destination][0] - STOPS[origin][0])
        stops_between = abs(destination - origin)
        headway = (
            self.loop / self.settings.speed_tiles_per_minute
            + 2 * len(STOPS) * self.settings.dwell_minutes
        ) / len(self.buses)
        bus_minutes = (
            (walk_a + walk_b) / walk_speed
            + headway / 2
            + distance / self.settings.speed_tiles_per_minute
            + stops_between * self.settings.dwell_minutes
        )
        if bus_minutes > GAIN_REQUIRED * walk_tiles / walk_speed:
            return None
        return Ride(agent.id, origin, destination, eastbound, start)

    def ride_of(self, agent_id: str) -> Ride | None:
        return self.rides.get(agent_id)

    def drop(self, agent_id: str) -> None:
        """Le trajet est abandonné avant de monter (envie pressante, fin du bloc...)."""
        ride = self.rides.get(agent_id)
        if ride is not None and ride.state in ("to_stop", "waiting", "alighted"):
            del self.rides[agent_id]

    # ------------------------------------------------------------------ #
    # Un tick
    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        if not self.enabled:
            return
        now = ctx.clock.tick
        for bus in self.buses:
            bus.prev = self.position(bus)
            if now < bus.dwell_until:
                self._carry(bus, ctx)
                continue
            before = bus.s
            after = before + self.speed_per_tick
            east = self.eastbound(bus)
            for index in range(len(STOPS)):
                stop_s = self._stop_s(index, east)
                if before < stop_s <= after:
                    bus.s = stop_s
                    bus.dwell_until = now + self.dwell_ticks
                    self._at_stop(bus, index, east, ctx)
                    break
            else:
                bus.s = after % self.loop
            self._carry(bus, ctx)

    def _carry(self, bus: Bus, ctx: SimContext) -> None:
        x, y = self.position(bus)
        for agent_id in bus.passengers:
            agent = ctx.agents[agent_id]
            agent.pos = (x, y)
            agent.tile = (round(x), round(y))

    def _at_stop(self, bus: Bus, index: int, east: bool, ctx: SimContext) -> None:
        from pixelcity.agents.movement import place_at

        stop_name = STOPS[index][1]
        platform = self.platform(index, east)
        for agent_id in sorted(bus.passengers):
            ride = self.rides.get(agent_id)
            if ride is None or ride.destination != index:
                continue
            bus.passengers.discard(agent_id)
            agent = ctx.agents[agent_id]
            agent.bus = None
            agent.pose = Pose.STAND
            agent.facing = Facing.UP if east else Facing.DOWN
            place_at(agent, platform)
            agent.prev_pos = agent.pos
            ride.state = "alighted"
            ctx.emit(EventKind.BUS_ALIGHTED, agent_id, None, stop=stop_name, bus=bus.uid)
        for agent_id in sorted(self.rides):
            ride = self.rides[agent_id]
            if ride.state != "waiting" or ride.origin != index or ride.eastbound != east:
                continue
            if len(bus.passengers) >= CAPACITY:
                break
            agent = ctx.agents[agent_id]
            if agent.tile != ride.platform:
                continue
            ctx.economy.pay(ctx, agent, None, self.settings.ticket)
            bus.passengers.add(agent_id)
            agent.bus = bus.uid
            agent.pose = Pose.HIDDEN
            agent.path, agent.path_index, agent.progress = (), 0, 0.0
            ride.state = "onboard"
            self.trips += 1
            ctx.emit(
                EventKind.BUS_BOARDED,
                agent_id,
                None,
                stop=stop_name,
                bus=bus.uid,
                to=STOPS[ride.destination][1],
            )


def _manhattan(a: TilePos, b: TilePos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
