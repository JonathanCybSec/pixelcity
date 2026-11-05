"""L'argent circule : chaque euro vient de quelqu'un et va à quelqu'un.

Les comptes :
- les HABITANTS (leur porte-monnaie, `agent.money`) ;
- les EMPLOYEURS : chaque commerce a sa caisse ; les bureaux (Entreprise
  Horizon) et l'école (Mairie) sont payés par l'extérieur ;
- trois STRUCTURES : l'État (retraites, bourses, chômage, taxes), le Bailleur
  (les loyers), les Fournisseurs (la marchandise des commerces) ;
- la CLIENTÈLE EXTÉRIEURE : les passants et les autres quartiers qu'on ne
  simule pas achètent aussi dans nos commerces (`external_revenue`). Sans
  elle, six habitants ne feraient jamais vivre une boulangerie et son boulanger.

Chaque mouvement est un VIREMENT `transfer(de, vers, montant, motif)` : on
garde la trace des flux (le bilan montre qui paie qui). C'est le principe de
la comptabilité en partie double (Luca Pacioli, Venise, 1494) : rien ne se
crée, tout se transfère.

Les règles de la vraie vie :
- le salaire n'est gagné qu'en étant AU TRAVAIL (une absence n'est pas payée) ;
  si la caisse du commerce est vide, l'employé n'est pas payé (et s'en souvient) ;
- les factures tombent chaque nuit, qu'on ait de l'argent ou non :
  loyer pour un locataire, charges et taxe foncière (30 %) pour un propriétaire ;
- un compte négatif, c'est une dette : l'expulsion (gérée par `life.py`) suit.

Montants arrondis au centime à chaque opération : en `float`, 0,1 + 0,2
vaut 0,30000000000000004. Une banque compterait en centimes entiers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pixelcity.memory.stream import MemoryKind
from pixelcity.sim.events import EventKind
from pixelcity.sim.types import ActivityType

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.sim.context import SimContext

STATE, LANDLORD, SUPPLIERS, OUTSIDE = "etat", "bailleur", "fournisseurs", "exterieur"
STRUCTURE_NAMES = {
    STATE: "l'État",
    LANDLORD: "le bailleur",
    SUPPLIERS: "les fournisseurs",
    OUTSIDE: "la clientèle extérieure",
}
GOODS_COST = 0.45  # part du prix de vente qui repart chez les fournisseurs
OWNER_CHARGES = 0.3  # charges d'un propriétaire, en part du loyer du logement
SHOP_CAPITAL = 1500.0  # trésorerie de départ d'un commerce


def cents(value: float) -> float:
    return round(value, 2)


class Economy:
    def __init__(self) -> None:
        self.accounts: dict[str, float] = {}  # caisses des employeurs « fermés » (commerces)
        self.revenue: dict[str, float] = defaultdict(float)  # ventes aux habitants
        self.sales: dict[str, int] = defaultdict(int)
        self.flows: dict[tuple[str, str], float] = defaultdict(float)  # (de, vers) → total
        self.transit_revenue = 0.0
        self._broke: set[str] = set()
        self._unpaid_noted: set[tuple[str, int]] = set()

    def setup(self, ctx: SimContext) -> None:
        for place in ctx.config.city.places:
            if place.external_revenue:  # un commerce : il vit de ses ventes
                self.accounts[place.id] = SHOP_CAPITAL

    # ------------------------------------------------------------------ #
    # Virements
    # ------------------------------------------------------------------ #
    def balance(self, ctx: SimContext, who: str) -> float:
        agent = ctx.agents.get(who)
        if agent is not None:
            return agent.money
        return self.accounts.get(who, float("inf"))  # l'extérieur ne manque jamais d'argent

    def transfer(self, ctx: SimContext, source: str, target: str, amount: float) -> None:
        amount = cents(amount)
        if amount <= 0:
            return
        for who, sign in ((source, -1), (target, 1)):
            agent = ctx.agents.get(who)
            if agent is not None:
                agent.money = cents(agent.money + sign * amount)
                if sign > 0:
                    agent.income = cents(agent.income + amount)
                else:
                    agent.expenses = cents(agent.expenses + amount)
            elif who in self.accounts:
                self.accounts[who] = cents(self.accounts[who] + sign * amount)
        self.flows[(_kind(ctx, source), _kind(ctx, target))] += amount

    # ------------------------------------------------------------------ #
    # Un tick
    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        if not ctx.config.settings.economy.enabled:
            return
        if ctx.clock.tick == 0:
            self.setup(ctx)
            for agent in ctx.agents.values():
                self._check_broke(ctx, agent)
        hours = ctx.hours_per_tick
        clock = ctx.clock
        for agent in ctx.agents.values():
            block = agent.current_block()
            at_work = (
                block is not None
                and block.activity is ActivityType.WORK
                and agent.place_id is not None
                and agent.place_id == agent.work_place_id
            )
            if at_work:
                agent.worked_minutes += ctx.minutes_per_tick
                if agent.profile.wage:
                    self._pay_wage(ctx, agent, agent.profile.wage * hours)
        # La clientèle extérieure, pendant les heures d'ouverture.
        for place_id in self.accounts:
            place = ctx.world.places[place_id]
            if place.hours.is_open(clock.weekday.number, clock.minute_of_day):
                model = ctx.config.place(place_id)
                gross = model.external_revenue * hours
                self.transfer(ctx, OUTSIDE, place_id, gross)
                self.transfer(ctx, place_id, SUPPLIERS, gross * GOODS_COST)
        if clock.is_start_of_day and clock.tick > 0:
            for agent in ctx.agents.values():
                self._nightly(ctx, agent)

    def _pay_wage(self, ctx: SimContext, agent: Agent, amount: float) -> None:
        employer = agent.work_place_id
        assert employer is not None
        if self.balance(ctx, employer) >= amount:
            # Bureaux et école : payés par une structure extérieure (entreprise, mairie).
            self.transfer(ctx, employer, agent.id, amount)
            return
        agent.unpaid = cents(agent.unpaid + amount)
        key = (agent.id, ctx.clock.day_index)
        if key not in self._unpaid_noted:
            self._unpaid_noted.add(key)
            from pixelcity.sim.minds import remember

            remember(
                ctx,
                agent,
                MemoryKind.OBSERVATION,
                f"La caisse de {ctx.world.places[employer].name} est vide : "
                "je n'ai pas été payé aujourd'hui",
                7,
                place_id=employer,
            )

    def _nightly(self, ctx: SimContext, agent: Agent) -> None:
        if agent.profile.allowance:
            self.transfer(ctx, STATE, agent.id, agent.profile.allowance)
        if not agent.homeless:
            rent = ctx.config.place(agent.home).rent
            if agent.profile.housing == "owner":
                self.transfer(ctx, agent.id, STATE, rent * OWNER_CHARGES)
            else:
                self.transfer(ctx, agent.id, LANDLORD, rent)
        self._check_broke(ctx, agent)

    # ------------------------------------------------------------------ #
    # Achats
    # ------------------------------------------------------------------ #
    def can_pay(self, agent: Agent, price: float) -> bool:
        return agent.money >= price

    def pay(self, ctx: SimContext, agent: Agent, place_id: str | None, price: float) -> None:
        """Un achat : au commerce (qui reverse sa part aux fournisseurs) ou au bus."""
        if place_id is None:
            self.transfer(ctx, agent.id, STATE, price)  # le bus est un service public
            self.transit_revenue = cents(self.transit_revenue + price)
        else:
            target = place_id if place_id in self.accounts else OUTSIDE
            self.transfer(ctx, agent.id, target, price)
            if target != OUTSIDE:
                self.transfer(ctx, target, SUPPLIERS, price * GOODS_COST)
            self.revenue[place_id] = cents(self.revenue[place_id] + price)
            self.sales[place_id] += 1
        self._check_broke(ctx, agent)

    def give(self, ctx: SimContext, donor: Agent, receiver: Agent, amount: float) -> None:
        self.transfer(ctx, donor.id, receiver.id, amount)
        self._check_broke(ctx, donor)

    def _check_broke(self, ctx: SimContext, agent: Agent) -> None:
        from pixelcity.sim.minds import remember

        tight = ctx.config.settings.economy.tight_budget
        if agent.money < tight and agent.id not in self._broke:
            self._broke.add(agent.id)
            remember(
                ctx,
                agent,
                MemoryKind.OBSERVATION,
                f"Je suis presque à sec ({agent.money:.0f} €), je dois faire attention",
                6,
            )
            ctx.emit(EventKind.MONEY_LOW, agent.id, agent.place_id, money=round(agent.money))
        elif agent.money >= 2 * tight:
            self._broke.discard(agent.id)

    # ------------------------------------------------------------------ #
    @staticmethod
    def situation(agent: Agent, ctx: SimContext) -> str:
        """Pour le LLM : argent, logement, travail, biens, en une phrase."""
        settings = ctx.config.settings.economy
        parts: list[str] = []
        if agent.money < 0:
            parts.append(f"endetté ({agent.money:.0f} €)")
        elif agent.money < settings.tight_budget:
            parts.append(f"fauché ({agent.money:.0f} €)")
        elif agent.money >= settings.comfortable:
            parts.append(f"à l'aise ({agent.money:.0f} €)")
        else:
            parts.append(f"budget serré ({agent.money:.0f} €)")
        if agent.homeless:
            parts.append("SANS DOMICILE, dort au parc")
        elif agent.arrears_days:
            parts.append(f"loyer impayé depuis {agent.arrears_days} nuit(s), menacé d'expulsion")
        else:
            parts.append("propriétaire" if agent.profile.housing == "owner" else "locataire")
        if agent.profile.work is None:
            parts.append("sans emploi" if agent.profile.age < 64 else "retraité")
        if agent.possessions:
            parts.append("possède : " + ", ".join(sorted(set(agent.possessions))))
        return ", ".join(parts)


def _kind(ctx: SimContext, who: str) -> str:
    """Pour les flux du bilan : « habitants » plutôt qu'un nom, sauf pour les structures."""
    if who in ctx.agents:
        return "habitants"
    if who in STRUCTURE_NAMES:
        return STRUCTURE_NAMES[who]
    place = ctx.world.places.get(who)
    return place.name if place is not None else who
