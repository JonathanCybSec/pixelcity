"""Les comptoirs : file d'attente, service, répliques et stock.

Un comptoir (la vitrine du boulanger, le comptoir du café, la caisse du
supermarché) possède :
- une place VENDEUR derrière lui (`behind_center`), réservée au personnel ;
- une place CLIENT devant (`front_center`), et des places de FILE derrière.

Le client rejoint la file et avance à mesure qu'elle se vide. Quand il est
devant le comptoir ET qu'un vendeur se tient derrière, une SESSION commence :
une conversation (générée par le LLM, ou scriptée), puis l'article passe du
stock du commerce à l'inventaire du client. Si le stock est vide, le vendeur s'excuse et le
client repart les mains vides : à lui (à sa recette) de trouver une solution.

C'est un petit « protocole » entre deux agents, comme une poignée de main
réseau (SYN, SYN-ACK, ACK) : chacun attend l'autre, et rien ne se passe tant
que les deux ne sont pas en place. La conversation elle-même vit dans
`conversation.py` ; le comptoir attend simplement qu'elle se termine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pixelcity.llm.types import ConversationKind
from pixelcity.sim.events import EventKind
from pixelcity.sim.types import Anim, Facing, TilePos
from pixelcity.world.furniture import Container, Furniture, Spot

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext
    from pixelcity.sim.conversation import Conversation

SESSION_MINUTES = 3.0
SELF_SERVICE_WAIT_MINUTES = 2  # on laisse au caissier le temps d'arriver avant le libre-service
SPEECH_MINUTES = 1.0  # durée d'affichage d'une bulle, en temps simulé


@dataclass(frozen=True, slots=True)
class Line:
    tick: int
    speaker: str
    listener: str
    text: str


@dataclass(slots=True)
class Session:
    customer: str
    staff: str | None  # None : libre-service
    item: str
    in_stock: bool
    ends_tick: int
    lines: list[Line]
    conversation: Conversation | None = None
    price: float = 0.0
    can_pay: bool = True


@dataclass(slots=True, eq=False)
class ServiceDesk:
    furniture: Furniture
    place_id: str
    staff_spot: Spot
    front_spot: Spot
    queue_spots: tuple[Spot, ...]
    queue: list[str] = field(default_factory=list)
    session: Session | None = None
    front_since: int | None = None  # tick d'arrivée du premier client au comptoir
    # Issue des services terminés, en attente d'être lue par le client :
    # agent → True (servi) / False (reparti les mains vides).
    results: dict[str, bool] = field(default_factory=dict)
    served: int = 0

    @property
    def uid(self) -> str:
        return self.furniture.uid

    @property
    def sells(self) -> tuple[str, ...]:
        return self.furniture.sells

    @property
    def capacity(self) -> int:
        return 1 + len(self.queue_spots)

    @property
    def self_service(self) -> bool:
        behaviour = self.furniture.behaviour
        return behaviour is not None and behaviour.self_service

    def position_tile(self, index: int) -> TilePos:
        """Case où se tient le client numéro `index` (0 = au comptoir)."""
        if index <= 0 or not self.queue_spots:
            return self.front_spot.tile
        return self.queue_spots[min(index - 1, len(self.queue_spots) - 1)].tile

    def index_of(self, agent_id: str) -> int | None:
        try:
            return self.queue.index(agent_id)
        except ValueError:
            return None

    def join(self, agent_id: str) -> int | None:
        """Rejoint la file ; None si elle est pleine."""
        index = self.index_of(agent_id)
        if index is not None:
            return index
        if len(self.queue) >= self.capacity:
            return None
        self.queue.append(agent_id)
        return len(self.queue) - 1

    def leave(self, agent_id: str) -> None:
        """Le client s'en va (il abandonne, ou son plan l'appelle ailleurs)."""
        if agent_id in self.queue:
            self.queue.remove(agent_id)
        if self.session is not None and self.session.customer == agent_id:
            self.session = None
        if not self.queue:
            self.front_since = None
        self.results.pop(agent_id, None)

    def stock(self, place_container: Container | None) -> Container | None:
        """Le stock qui alimente ce comptoir : le sien, sinon celui du lieu."""
        own = self.furniture.container
        if own is not None:
            return own
        return place_container


def build_desks(furniture: dict[str, Furniture]) -> dict[str, ServiceDesk]:
    """Un comptoir pour chaque meuble qui vend quelque chose."""
    desks: dict[str, ServiceDesk] = {}
    for item in furniture.values():
        if not item.sells or item.place_id is None:
            continue
        staff = next((s for s in item.spots if s.kind == "behind_center"), None)
        front = next((s for s in item.spots if s.kind == "front_center"), None)
        if staff is None or front is None:
            raise ValueError(
                f"{item.type_id} vend {item.sells} mais n'a pas de place vendeur et client"
            )
        queue = tuple(s for s in item.spots if s.kind == "queue")
        desks[item.uid] = ServiceDesk(item, item.place_id, staff, front, queue)
    return desks


# --------------------------------------------------------------------------- #
# Un tick de tous les comptoirs
# --------------------------------------------------------------------------- #
def update_desks(ctx: SimContext) -> None:
    for desk in ctx.desks.values():
        if desk.session is not None:
            _continue_session(desk, ctx)
        elif desk.queue:
            _try_start_session(desk, ctx)


def server_of(desk: ServiceDesk, agents: dict[str, Agent]) -> Agent | None:
    """Le vendeur qui tient le comptoir en ce moment, s'il y en a un."""
    staff_id = desk.staff_spot.reserved_by
    if staff_id is None:
        return None
    staff = agents.get(staff_id)
    if staff is None or staff.spot is not desk.staff_spot or staff.is_moving:
        return None
    task = staff.task
    if task is None or not task.is_performing:
        return None
    return staff


def _customer_ready(desk: ServiceDesk, customer: Agent) -> bool:
    return (
        customer.tile == desk.front_spot.tile
        and not customer.is_moving
        and customer.place_id == desk.place_id
    )


def _try_start_session(desk: ServiceDesk, ctx: SimContext) -> None:
    customer = ctx.agents.get(desk.queue[0])
    if customer is None:
        desk.queue.pop(0)
        return
    if not _customer_ready(desk, customer):
        desk.front_since = None
        return
    now = ctx.clock.tick
    if desk.front_since is None:
        desk.front_since = now
    staff = server_of(desk, ctx.agents)
    if staff is None:
        waited = (now - desk.front_since) / ctx.clock.ticks_per_minute
        if not desk.self_service or waited < SELF_SERVICE_WAIT_MINUTES:
            return
    task = customer.task
    item = task.buying if task is not None else None
    if item is None:
        return
    place = ctx.world.places[desk.place_id]
    stock = desk.stock(place.container_with(item))
    in_stock = stock is not None and stock.has(item)
    item_model = ctx.config.actions.items.get(item)
    price = item_model.price if item_model is not None else 0.0
    can_pay = ctx.economy.can_pay(customer, price)
    ticks_per_minute = ctx.clock.ticks_per_minute
    conversation = None
    lines: list[Line] = []
    if staff is not None:
        conversation = ctx.conversations.start(
            ctx,
            ConversationKind.COUNTER,
            customer,
            staff,
            item=item,
            in_stock=in_stock,
            can_pay=can_pay,
            price=price,
        )
        minutes = SESSION_MINUTES  # durée minimale ; on attend aussi la fin de l'échange
        # Face à face : le client regarde le comptoir, le vendeur regarde le client.
        staff.facing = Facing.DOWN
        staff.anim = Anim.TALK
    else:
        rng = ctx.rngs.stream(f"dialogue:{desk.uid}")
        text = rng.choice(
            ctx.config.dialogues.self_checkout if can_pay else ctx.config.dialogues.no_money
        )
        lines = [Line(now, customer.id, customer.id, text)]
        minutes = SESSION_MINUTES / 2
    customer.facing = Facing.UP
    customer.anim = Anim.TALK if staff is not None else Anim.INTERACT
    desk.session = Session(
        customer=customer.id,
        staff=staff.id if staff is not None else None,
        item=item,
        in_stock=in_stock and can_pay,  # pas d'argent : pas de vente
        ends_tick=now + round(minutes * ticks_per_minute),
        lines=lines,
        conversation=conversation,
        price=price,
        can_pay=can_pay,
    )
    ctx.emit(
        EventKind.SERVICE_STARTED,
        customer.id,
        desk.place_id,
        staff=staff.id if staff is not None else None,
        item=item,
        in_stock=in_stock,
    )
    _say_due_lines(desk.session, ctx)


def _continue_session(desk: ServiceDesk, ctx: SimContext) -> None:
    session = desk.session
    assert session is not None
    customer = ctx.agents.get(session.customer)
    staff = server_of(desk, ctx.agents)
    staff_gone = session.staff is not None and (staff is None or staff.id != session.staff)
    if customer is None or staff_gone:
        # Le vendeur a quitté son poste (fin de service) : on interrompt.
        if session.conversation is not None:
            ctx.conversations.cancel(session.conversation, ctx)
        desk.session = None
        if customer is not None:
            desk.results[customer.id] = False
            if customer.id in desk.queue:
                desk.queue.remove(customer.id)
        ctx.emit(
            EventKind.SERVICE_DONE, session.customer, desk.place_id, item=session.item, ok=False
        )
        return
    _say_due_lines(session, ctx)
    if ctx.clock.tick < session.ends_tick:
        return
    if session.conversation is not None and not session.conversation.finished:
        return  # on se dit encore au revoir

    ok = False
    if session.in_stock:
        place = ctx.world.places[desk.place_id]
        stock = desk.stock(place.container_with(session.item))
        if stock is not None and stock.take(session.item):
            customer.give(session.item)
            ctx.economy.pay(ctx, customer, desk.place_id, session.price)
            ok = True
            if stock.count(session.item) == 0:
                ctx.emit(EventKind.STOCK_EMPTY, session.staff, desk.place_id, item=session.item)
    desk.results[customer.id] = ok
    if desk.queue and desk.queue[0] == customer.id:
        desk.queue.pop(0)
    desk.session = None
    desk.front_since = None
    desk.served += 1
    customer.anim = Anim.IDLE
    if staff is not None:
        staff.anim = Anim.IDLE
    ctx.emit(
        EventKind.SERVICE_DONE,
        customer.id,
        desk.place_id,
        staff=session.staff,
        item=session.item,
        ok=ok,
        reason="" if ok or session.can_pay else "money",
    )


def _say_due_lines(session: Session, ctx: SimContext) -> None:
    now = ctx.clock.tick
    while session.lines and session.lines[0].tick <= now:
        line = session.lines.pop(0)
        say(ctx, line.speaker, line.text, line.listener)


def say(ctx: SimContext, speaker_id: str, text: str, listener_id: str | None = None) -> None:
    """Fait parler un habitant : une bulle au-dessus de sa tête et une ligne au journal."""
    from pixelcity.agents.agent import Speech  # import local : agent.py importe ce module

    speaker = ctx.agents[speaker_id]
    until = ctx.clock.tick + round(SPEECH_MINUTES * ctx.clock.ticks_per_minute)
    speaker.speech = Speech(text, until, listener_id)
    ctx.emit(EventKind.SAY, speaker_id, speaker.place_id, text=text, to=listener_id)
