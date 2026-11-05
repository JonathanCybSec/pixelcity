"""L'argent : salaires, revenus, loyers, achats, recettes des commerces.

Règles volontairement simples (c'est un bac à sable, pas un simulateur fiscal) :
- le salaire tombe AU FIL des heures passées au travail (pas de paie mensuelle :
  on voit l'effet tout de suite) ;
- retraite, bourse ou allocation arrivent chaque nuit, le loyer part chaque nuit ;
- au comptoir, le client paie s'il le peut ; sinon il repart les mains vides ;
- chaque commerce cumule ses recettes : c'est ce que mesurera le test de produit.

Piège classique : stocker de l'argent en `float` accumule des erreurs
d'arrondi (0,1 + 0,2 = 0,30000000000000004). Une banque utiliserait
`decimal.Decimal` ou des centimes entiers ; ici les montants sont arrondis au
centime à chaque opération, ce qui suffit pour une simulation.
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


def cents(value: float) -> float:
    return round(value, 2)


class Economy:
    def __init__(self) -> None:
        self.revenue: dict[str, float] = defaultdict(float)  # lieu → recettes
        self.sales: dict[str, int] = defaultdict(int)
        self.transit_revenue = 0.0
        self._broke: set[str] = set()  # habitants déjà signalés « à court d'argent »

    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        settings = ctx.config.settings.economy
        if not settings.enabled:
            return
        hours = ctx.hours_per_tick
        if ctx.clock.tick == 0:
            for agent in ctx.agents.values():
                self._check_broke(ctx, agent)  # fauché dès le départ (scénario du studio)
        for agent in ctx.agents.values():
            block = agent.current_block()
            if (
                agent.profile.wage
                and block is not None
                and block.activity is ActivityType.WORK
                and agent.place_id == agent.work_place_id
            ):
                self._credit(agent, agent.profile.wage * hours)
        if ctx.clock.is_start_of_day and ctx.clock.tick > 0:
            for agent in ctx.agents.values():
                self._credit(agent, agent.profile.allowance)
                rent = ctx.config.place(agent.profile.home).rent
                agent.money = cents(agent.money - rent)
                agent.expenses = cents(agent.expenses + rent)
                self._check_broke(ctx, agent)

    def _credit(self, agent: Agent, amount: float) -> None:
        if amount:
            agent.money = cents(agent.money + amount)
            agent.income = cents(agent.income + amount)

    def can_pay(self, agent: Agent, price: float) -> bool:
        return agent.money >= price

    def pay(self, ctx: SimContext, agent: Agent, place_id: str | None, price: float) -> None:
        agent.money = cents(agent.money - price)
        agent.expenses = cents(agent.expenses + price)
        if place_id is None:
            self.transit_revenue = cents(self.transit_revenue + price)
        else:
            self.revenue[place_id] = cents(self.revenue[place_id] + price)
            self.sales[place_id] += 1
        self._check_broke(ctx, agent)

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

    @staticmethod
    def situation(agent: Agent, ctx: SimContext) -> str:
        """Pour le LLM : la situation financière en quelques mots."""
        settings = ctx.config.settings.economy
        if agent.money < 0:
            return "endetté, il n'arrive plus à payer son loyer"
        if agent.money < settings.tight_budget:
            return "fauché, compte chaque euro"
        if agent.money >= settings.comfortable:
            return "à l'aise financièrement"
        return "budget serré mais ça va"
