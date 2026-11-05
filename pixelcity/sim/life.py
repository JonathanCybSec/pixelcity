"""La vraie vie : ce que chacun DÉCIDE de faire, et ce que la ville lui fait subir.

Qui décide ? L'IA de chaque habitant (même modèle Ollama pour tous, mais une
personnalité, une mémoire et une situation propres à chacun) :
- chaque soir à 21:00, elle choisit les INTENTIONS du lendemain : aller au
  travail ou non, s'offrir quelque chose, chercher un emploi, faire la manche,
  voler, se détendre ;
- dans un moment critique (une faim terrible sans un sou), elle DÉCIDE sur le
  champ : mendier, voler, ou tenir bon.
Le « corps » (le moteur) exécute ensuite les gestes : marcher, attendre, manger.
Sans Ollama, des règles de secours tiennent la ville en vie (pastille orange).

Ce que la ville impose, sans discussion :
- LOGEMENT : trois nuits de loyer impayé (compte négatif) et l'huissier passe
  le matin. À la rue, on dort sur un banc du parc, sans frigo ni douche.
  On retrouve un logement libre dès qu'on a de quoi payer une semaine de loyer.
- TRAVAIL : une journée de travail sans y avoir passé une heure est une
  absence ; trois absences en sept jours, c'est le licenciement. Chercher un
  emploi peut aboutir s'il y a un poste libre (moins facile à la rue).
- VOL : on peut être vu. Par le personnel : pris sur le fait, rien d'obtenu,
  interdit d'entrée. Par un client : il s'en souvient, l'estime s'effondre, et
  il pourra en parler (sa mémoire alimente ses conversations : la rumeur).
- MANCHE : les passants (habitants et anonymes) donnent parfois quelques euros,
  selon leur gentillesse et ce qu'ils pensent du mendiant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pixelcity.config.schemas import StepModel
from pixelcity.llm.backends import DialogueBackend, Pending
from pixelcity.llm.types import (
    Decision,
    DecisionRequest,
    IntentionRequest,
    Intentions,
    Option,
)
from pixelcity.memory.stream import MemoryKind
from pixelcity.sim.economy import OUTSIDE, Economy
from pixelcity.sim.events import EventKind
from pixelcity.sim.minds import memory_lines, remember
from pixelcity.sim.types import NeedKind, PlaceKind, Pose, Weekday

if TYPE_CHECKING:
    from pixelcity.agents.agent import Agent
    from pixelcity.agents.tasks import Task
    from pixelcity.sim.context import SimContext

INTENTION_HOUR = 21 * 60
EVICTION_HOUR = 8 * 60
REHOUSING_HOUR = 10 * 60
EVICTION_NIGHTS = 3
ABSENCE_MIN_WORK = 60  # minutes au travail en dessous desquelles la journée est une absence
FIRING_ABSENCES = 3
UNEMPLOYMENT_BENEFIT = 30.0
REHOUSING_WEEKS = 7  # jours de loyer d'avance pour retrouver un toit
HIRE_CHANCE, HIRE_CHANCE_HARD = 0.45, 0.2
STAFF_NOTICE, WITNESS_NOTICE = 0.5, 0.35
BEG_RADIUS = 6
DECISION_RETRY_MINUTES = 3
MAX_REPLANS = 2
CRAVING_DECAY = 0.04  # par nuit : une envie qu'on ne nourrit pas s'éteint doucement

ACTIVITIES: dict[str, str] = {
    "job_search": "chercher un emploi (annonces, candidatures)",
    "beg": "faire la manche au parc",
    "steal_food": (
        "voler à manger au supermarché (risque d'être vu, d'avoir honte, d'être interdit d'entrée)"
    ),
    "park": "se promener au parc (gratuit)",
    "gym": "aller à la salle de sport",
    "cafe": "prendre un café au Café des Arts (2,50 €)",
    "rest": "rester tranquille chez soi",
}
GOODS = ("phone", "headphones", "clothes", "shoes", "book", "tv", "console")


@dataclass(slots=True)
class _Session:
    budget: float
    net: float = 0.0
    rounds: int = 0
    chased: bool = False


@dataclass(slots=True)
class _Waiting:
    pending: Pending[Decision | None]
    request: DecisionRequest


class Life:
    def __init__(self, backend: DialogueBackend) -> None:
        self.backend = backend
        self._intentions: dict[str, tuple[int, Pending[Intentions | None]]] = {}
        self._decisions: dict[str, _Waiting] = {}
        self._donated: dict[tuple[str, str], int] = {}
        # Dernière décision urgente, réutilisée 3 h : on ne se repose pas la question
        # toutes les 90 minutes (et c'est autant d'appels à l'IA en moins).
        self._recent: dict[str, tuple[str, int]] = {}
        self._sessions: dict[str, _Session] = {}
        self.thefts = 0
        self.evictions = 0
        self.hires = 0
        self.firings = 0

    # ------------------------------------------------------------------ #
    # Un tick
    # ------------------------------------------------------------------ #
    def update(self, ctx: SimContext) -> None:
        clock = ctx.clock
        if clock.tick % clock.ticks_per_minute:
            self._poll_intentions(ctx)
            return
        minute = clock.minute_of_day
        if clock.is_start_of_day and clock.tick > 0:
            for agent in list(ctx.agents.values()):
                self._midnight(ctx, agent)
        if minute == INTENTION_HOUR:
            for agent in ctx.agents.values():
                self._ask_intentions(ctx, agent)
        if minute == EVICTION_HOUR:
            for agent in list(ctx.agents.values()):
                self._check_eviction(ctx, agent)
        if minute == REHOUSING_HOUR:
            for agent in list(ctx.agents.values()):
                self._check_rehousing(ctx, agent)
        self._poll_intentions(ctx)
        self._begging(ctx)
        for agent_id in list(self._sessions):
            agent = ctx.agents[agent_id]
            if agent.task is None or agent.task.recipe_id != "casino":
                self._end_session(ctx, agent)

    # ------------------------------------------------------------------ #
    # Intentions du lendemain
    # ------------------------------------------------------------------ #
    def _ask_intentions(
        self, ctx: SimContext, agent: Agent, *, day: int | None = None, replan: bool = False
    ) -> None:
        """Demande à l'IA de l'habitant sa journée (demain, ou la fin d'aujourd'hui)."""
        from pixelcity.sim.conversation import persona
        from pixelcity.sim.options import day_options, goods_options

        day = ctx.clock.day_index + 1 if day is None else day
        weekday = Weekday.from_index(day)
        others = list(ctx.agents.values())
        options = day_options(ctx.world, ctx.config, agent, others, day)
        goods = goods_options(ctx.world, ctx.config, agent, day)
        if replan:
            now = ctx.clock.minute_of_day
            options = {k: o for k, o in options.items() if o.window[1] > now + 30}
            goods = {k: o for k, o in goods.items() if o.window[1] > now + 30}
        work = options.get("work")
        memories = agent.memory.retrieve(
            ctx.clock.tick, query="argent travail envie plaisir casino demain", count=6
        )
        sleep = agent.profile.sleep
        wake = sleep.wake if work is not None or sleep.weekend_wake is None else sleep.weekend_wake
        label = weekday.label.lower()
        if replan:
            clock_text = _hhmm(ctx.clock.minute_of_day)
            label = f"aujourd'hui {label}, il est {clock_text} : la suite de ta journée"
        request = IntentionRequest(
            persona(agent, Economy.situation(agent, ctx)),
            memory_lines(ctx, memories),
            label,
            work.label if work is not None else None,
            tuple(Option(o.id, o.label) for o in goods.values()),
            tuple(Option(o.id, o.label) for o in options.values() if o.id != "work")
            + ((Option("work", work.label),) if work is not None else ()),
            seed=ctx.rngs.stream("intentions").randrange(1 << 30),
            cravings=cravings_text(agent),
            wake=_hhmm(wake),
            bed=_hhmm(sleep.bed),
        )
        self._intentions[agent.id] = (day, self.backend.submit_intentions(request))

    def _poll_intentions(self, ctx: SimContext) -> None:
        for agent_id, (day, pending) in list(self._intentions.items()):
            if not pending.done():
                continue
            del self._intentions[agent_id]
            agent = ctx.agents[agent_id]
            answer = pending.result()
            if answer is None and day == ctx.clock.day_index:
                continue  # replanification sans IA : on garde le plan en cours
            intentions = answer or self.rule_intentions(ctx, agent)
            agent.intentions[day] = intentions
            if intentions.pros_cons:
                agent.deliberation = intentions.pros_cons
            if day == ctx.clock.day_index:
                agent.plan = None  # la suite de la journée est replanifiée tout de suite
            if intentions.thought:
                ctx.emit(
                    EventKind.INTENTION,
                    agent_id,
                    agent.place_id,
                    text=intentions.thought,
                    source=intentions.source,
                )
                text = f"Ce que je prévois : {intentions.thought}"
                remember(ctx, agent, MemoryKind.PLAN, text, 4)

    def rule_intentions(self, ctx: SimContext, agent: Agent) -> Intentions:
        """Règles de secours (pas d'IA) : un comportement plausible, sans finesse."""
        rng = ctx.rngs.stream(f"rules:{agent.id}")
        p = agent.profile.personality
        honesty = (p.agreeableness + p.conscientiousness) / 2
        settings = ctx.config.settings.economy
        work = not (
            agent.needs[NeedKind.FUN] < 20 and p.conscientiousness < 0.45 and rng.random() < 0.5
        )
        activities: list[str] = []
        if agent.profile.work is None and agent.profile.age < 64:
            activities.append("job_search")
        if agent.homeless or agent.money < 0:
            activities.append("beg")
            if honesty < 0.5 and rng.random() < 0.4:
                activities.append("steal_food")
        purchases: list[str] = []
        items = ctx.config.actions.items
        if agent.money > settings.comfortable:
            for good in GOODS:
                affordable = agent.money - items[good].price > settings.comfortable / 2
                if good not in agent.possessions and affordable and rng.random() < 0.15:
                    purchases.append(good)
                    break
        craving = agent.cravings.get("casino", 0.0)
        if craving > 0 and agent.money > 20 and rng.random() < craving and len(activities) < 2:
            activities.append("casino")  # l'envie l'emporte
        if len(activities) < 2 and "casino" not in activities and agent.money > 100:
            risky = (1 - p.conscientiousness) * 0.15 + p.neuroticism * 0.05
            if rng.random() < risky:
                activities.append("casino")  # « juste pour voir »
        if len(activities) < 2 and p.extraversion > 0.6 and rng.random() < 0.2:
            activities.append("bar")
        if agent.needs[NeedKind.FUN] < 50 and len(activities) < 2:
            activities.append(rng.choice(("park", "gym")))
        thought = None
        if not work:
            thought = "Demain, je n'ai pas le courage d'aller travailler."
        elif purchases:
            thought = f"Demain, je m'offre ça : {items[purchases[0]].label}."
        elif "beg" in activities:
            thought = "Il va falloir tendre la main demain…"
        return Intentions(work, tuple(purchases), tuple(activities[:2]), thought, "règles")

    # ------------------------------------------------------------------ #
    # Décisions urgentes (faim sans le sou)
    # ------------------------------------------------------------------ #
    def deciding(self, agent_id: str) -> bool:
        return agent_id in self._decisions

    def emergency_food(self, ctx: SimContext, agent: Agent) -> tuple[str, str] | None:
        """(recette, lieu) choisis pour manger sans argent ; None tant que l'IA réfléchit."""
        recent = self._recent.get(agent.id)
        if recent is not None and ctx.now < recent[1]:
            return self._food_task(ctx, agent, recent[0])
        waiting = self._decisions.get(agent.id)
        if waiting is None:
            options = self._food_options(ctx, agent)
            if not options:
                return None
            from pixelcity.sim.conversation import persona

            memories = agent.memory.retrieve(
                ctx.clock.tick, query="faim argent voler manche", count=4
            )
            request = DecisionRequest(
                persona(agent, Economy.situation(agent, ctx)),
                memory_lines(ctx, memories),
                f"Tu as terriblement faim (faim {agent.needs[NeedKind.HUNGER]:.0f}/100), "
                f"rien à manger et {agent.money:.2f} € en poche : pas de quoi payer.",
                tuple(options),
                seed=ctx.rngs.stream("decision").randrange(1 << 30),
            )
            waiting = _Waiting(self.backend.submit_decision(request), request)
            self._decisions[agent.id] = waiting
            ctx.emit(EventKind.CHAT_THINKING, agent.id, agent.place_id, other=agent.id)
        if not waiting.pending.done():
            return None
        del self._decisions[agent.id]
        decision = waiting.pending.result() or self._rule_decision(ctx, agent, waiting.request)
        if decision.thought:
            ctx.emit(
                EventKind.DECISION,
                agent.id,
                agent.place_id,
                text=decision.thought,
                choice=decision.choice,
                source=decision.source,
            )
        choice = decision.choice or "beg"
        self._recent[agent.id] = (choice, ctx.now + 180)
        return self._food_task(ctx, agent, choice)

    def _food_task(self, ctx: SimContext, agent: Agent, choice: str) -> tuple[str, str]:
        match choice:
            case "steal_food":
                shop = self._steal_target(ctx, agent)
                return ("steal_food", shop) if shop else ("beg", "parc")
            case "beg":
                return ("beg", "parc")
            case _:
                return ("rest_hungry", agent.home)

    def _food_options(self, ctx: SimContext, agent: Agent) -> list[Option]:
        options = [Option("beg", "faire la manche au parc pour pouvoir s'acheter à manger")]
        if self._steal_target(ctx, agent):
            options.append(Option("steal_food", "voler à manger au supermarché (risque d'être vu)"))
        options.append(Option("endure", "tenir bon et attendre, le ventre vide"))
        return options

    def _steal_target(self, ctx: SimContext, agent: Agent) -> str | None:
        place = ctx.world.places.get("supermarche")
        if place is None or "supermarche" in agent.banned:
            return None
        clock = ctx.clock
        return (
            "supermarche"
            if place.hours.is_open(clock.weekday.number, clock.minute_of_day)
            else None
        )

    def _rule_decision(self, ctx: SimContext, agent: Agent, req: DecisionRequest) -> Decision:
        p = agent.profile.personality
        honesty = (p.agreeableness + p.conscientiousness) / 2
        ids = {o.id for o in req.options}
        if "steal_food" in ids and honesty < 0.55 and agent.needs[NeedKind.HUNGER] < 10:
            return Decision("steal_food", "Tant pis, j'ai trop faim…")
        return Decision("beg", "Je n'ai pas le choix, je vais demander de l'aide.")

    # ------------------------------------------------------------------ #
    # Minuit : absences, dettes
    # ------------------------------------------------------------------ #
    def _midnight(self, ctx: SimContext, agent: Agent) -> None:
        yesterday = ctx.clock.day_index - 1
        work = agent.profile.work
        shift_day = work is not None and Weekday.from_index(yesterday) in work.schedule
        absent = agent.worked_minutes < ABSENCE_MIN_WORK and agent.hired_day != yesterday
        if work is not None and shift_day and absent:
            agent.absences.append(yesterday)
            remember(
                ctx,
                agent,
                MemoryKind.OBSERVATION,
                "Je ne suis pas allé travailler hier : journée non payée",
                5,
                place_id=work.place,
            )
            recent = [d for d in agent.absences if d > yesterday - 7]
            if len(recent) >= FIRING_ABSENCES:
                self.fire(ctx, agent)
        agent.worked_minutes = 0.0
        for name, value in list(agent.cravings.items()):
            agent.cravings[name] = max(0.0, value - CRAVING_DECAY)
        for old in [d for d in agent.intentions if d < yesterday]:
            del agent.intentions[old]
        agent.arrears_days = agent.arrears_days + 1 if agent.money < 0 else 0

    def fire(self, ctx: SimContext, agent: Agent) -> None:
        work = agent.profile.work
        if work is None:
            return
        place = ctx.world.places[work.place]
        agent.profile = agent.profile.model_copy(
            update={
                "work": None,
                "wage": 0.0,
                "job": "Sans emploi",
                "allowance": max(agent.profile.allowance, UNEMPLOYMENT_BENEFIT),
            }
        )
        agent.absences.clear()
        agent.plan = None
        self.firings += 1
        remember(
            ctx,
            agent,
            MemoryKind.OBSERVATION,
            f"J'ai été licencié de {place.name} : trop d'absences",
            9,
            place_id=place.id,
        )
        ctx.emit(EventKind.FIRED, agent.id, place.id)

    def hire(self, ctx: SimContext, agent: Agent, place_id: str) -> None:
        from pixelcity.studio.presets import JOBS

        preset = next(job for job in JOBS if job.place == place_id)
        work = {
            "place": place_id,
            "schedule": dict(preset.schedule),
            "lunch_at_work": preset.lunch_at_work,
        }
        model = agent.profile.model_dump()
        model.update(
            work=work,
            job=preset.label,
            wage=preset.wage,
            allowance=0.0,
            sleep={"wake": preset.wake, "bed": preset.bed, "weekend_wake": preset.weekend_wake},
        )
        agent.profile = type(agent.profile).model_validate(model)
        agent.absences.clear()
        agent.hired_day = ctx.clock.day_index
        agent.plan = None
        self.hires += 1
        place = ctx.world.places[place_id]
        remember(
            ctx,
            agent,
            MemoryKind.OBSERVATION,
            f"J'ai été embauché à {place.name} comme {preset.label.lower()} !",
            9,
            place_id=place_id,
        )
        ctx.emit(EventKind.HIRED, agent.id, place_id, job=preset.label)

    # ------------------------------------------------------------------ #
    # Logement
    # ------------------------------------------------------------------ #
    def _check_eviction(self, ctx: SimContext, agent: Agent) -> None:
        if agent.homeless:
            return
        owner = agent.profile.housing == "owner"
        nights = EVICTION_NIGHTS * (3 if owner else 1)  # un propriétaire tient plus longtemps
        if agent.arrears_days < nights:
            return
        self.evict(ctx, agent)

    def evict(self, ctx: SimContext, agent: Agent) -> None:
        from pixelcity.agents.executor import cancel_task, leave_place
        from pixelcity.agents.movement import place_at

        old = ctx.world.places[agent.home]
        for task in list(agent.tasks):
            cancel_task(agent, task, ctx)
        agent.tasks.clear()
        ctx.transit.drop(agent.id)
        if agent.place_id == old.id:
            leave_place(agent, ctx)
            doorstep = old.doorstep(agent.tile) or old.entrances[0]
            place_at(agent, doorstep)
        agent.pose = Pose.STAND
        agent.spot = None
        agent.homeless = True
        agent.profile = agent.profile.model_copy(update={"home": "parc", "housing": "tenant"})
        agent.plan = None
        agent.arrears_days = 0
        self.evictions += 1
        text = f"J'ai été expulsé de {old.name}. Je n'ai plus de toit, je vais dormir au parc"
        remember(ctx, agent, MemoryKind.OBSERVATION, text, 10, place_id=old.id)
        ctx.emit(EventKind.EVICTED, agent.id, old.id)

    def _check_rehousing(self, ctx: SimContext, agent: Agent) -> None:
        if not agent.homeless:
            return
        taken = {a.home for a in ctx.agents.values()}
        free = [p for p in ctx.config.city.places if p.kind is PlaceKind.HOME and p.id not in taken]
        affordable = [p for p in free if agent.money >= REHOUSING_WEEKS * p.rent]
        if not affordable:
            return
        home = min(affordable, key=lambda p: (p.rent, p.id))
        agent.homeless = False
        agent.profile = agent.profile.model_copy(update={"home": home.id, "housing": "tenant"})
        agent.plan = None
        remember(
            ctx,
            agent,
            MemoryKind.OBSERVATION,
            f"J'ai retrouvé un toit : {home.name}, {home.rent:.0f} € par jour",
            9,
            place_id=home.id,
        )
        ctx.emit(EventKind.REHOUSED, agent.id, home.id)

    # ------------------------------------------------------------------ #
    # Gestes spéciaux (appelés à la fin d'une étape de recette)
    # ------------------------------------------------------------------ #
    def on_special(self, ctx: SimContext, agent: Agent, task: Task, step: StepModel) -> None:
        if step.special == "gamble":
            self._gamble(ctx, agent, task)
        elif step.special == "steal" and step.steal is not None:
            self._steal(ctx, agent, task.place_id, step.steal)
        elif step.special == "job_search":
            self._job_search(ctx, agent)

    def _steal(self, ctx: SimContext, agent: Agent, place_id: str, item: str) -> None:
        rng = ctx.rngs.stream("theft")
        place = ctx.world.places[place_id]
        present = [
            other
            for other in ctx.agents.values()
            if other is not agent and other.place_id == place_id and other.pose is not Pose.LIE
        ]
        staff = [o for o in present if o.work_place_id == place_id]
        seen_by_staff = [o for o in staff if rng.random() < STAFF_NOTICE]
        witnesses = [o for o in present if o not in staff and rng.random() < WITNESS_NOTICE]
        label = ctx.config.actions.items[item].label
        self.thefts += 1
        if seen_by_staff:
            agent.banned.add(place_id)
            remember(
                ctx,
                agent,
                MemoryKind.OBSERVATION,
                f"Pris en flagrant délit de vol à {place.name} : honte, et interdit d'entrée",
                9,
                about=tuple(o.id for o in seen_by_staff),
                place_id=place_id,
            )
        else:
            agent.give(item)
            text = f"J'ai volé un {label} à {place.name}" + (
                ", et quelqu'un m'a peut-être vu…" if witnesses else ", personne n'a rien vu"
            )
            remember(ctx, agent, MemoryKind.OBSERVATION, text, 7, place_id=place_id)
        for other in seen_by_staff + witnesses:
            remember(
                ctx,
                other,
                MemoryKind.OBSERVATION,
                f"J'ai vu {agent.first_name} voler un {label} à {place.name}",
                8,
                about=(agent.id,),
                place_id=place_id,
            )
            relation, _, _ = ctx.relations.meet(
                other.profile, agent.profile, ctx.clock.tick, rng, delta=-6
            )
            relation.affinity = max(-100.0, relation.affinity - 18)
        ctx.emit(
            EventKind.THEFT,
            agent.id,
            place_id,
            item=item,
            caught=bool(seen_by_staff),
            witnesses=len(seen_by_staff) + len(witnesses),
        )

    def _job_search(self, ctx: SimContext, agent: Agent) -> None:
        if agent.profile.work is not None:
            return
        rng = ctx.rngs.stream("jobs")
        employed: dict[str, int] = {}
        for other in ctx.agents.values():
            if other.profile.work is not None:
                employed[other.profile.work.place] = employed.get(other.profile.work.place, 0) + 1
        openings = [p.id for p in ctx.config.city.places if p.jobs > employed.get(p.id, 0)]
        hard = agent.homeless or agent.needs[NeedKind.HYGIENE] < 30
        if openings and rng.random() < (HIRE_CHANCE_HARD if hard else HIRE_CHANCE):
            self.hire(ctx, agent, rng.choice(sorted(openings)))
            return
        text = (
            "Aucune réponse à mes candidatures"
            if openings
            else "Aucun poste libre en ville en ce moment"
        )
        if hard and openings:
            text += " ; sans adresse et pas très présentable, c'est dur"
        remember(ctx, agent, MemoryKind.OBSERVATION, text, 4)

    # ------------------------------------------------------------------ #
    # Le jeu : une machine à renforcer les envies
    # ------------------------------------------------------------------ #
    def _gamble(self, ctx: SimContext, agent: Agent, task: Task) -> None:
        """Une partie. Le hasard décide ; l'envie, le budget et le caractère font continuer."""
        rng = ctx.rngs.stream("casino")
        session = self._sessions.get(agent.id)
        if session is None:
            intentions = agent.intentions.get(ctx.clock.day_index)
            budget = intentions.casino_budget if intentions and intentions.casino_budget else 0.0
            if budget <= 0:  # pas de budget décidé : une part de ce qu'on a, selon l'envie
                craving = agent.cravings.get("casino", 0.0)
                budget = max(10.0, agent.money * (0.05 + 0.15 * craving))
            session = self._sessions[agent.id] = _Session(min(budget, max(agent.money, 0.0)))
        bet = float(min(max(5, round(agent.money * 0.03)), 50, max(agent.money, 0)))
        if bet < 1:
            task.ends_at = ctx.now  # plus un sou : on s'en va
            self._end_session(ctx, agent)
            return
        ctx.economy.transfer(ctx, agent.id, "casino", bet)
        roll = rng.random()
        multiplier = 50 if roll < 0.004 else 5 if roll < 0.054 else 2 if roll < 0.27 else 0
        win = bet * multiplier
        if win:
            ctx.economy.transfer(ctx, "casino", agent.id, win)
        session.net += win - bet
        session.rounds += 1
        if multiplier >= 5:
            from pixelcity.sim.service import say

            say(ctx, agent.id, "JACKPOT !!!" if multiplier == 50 else f"Gagné ! +{win:.0f} €")
        # Continuer ? Les pertes poussent à « se refaire », les gains à rejouer.
        p = agent.profile.personality
        craving = agent.cravings.get("casino", 0.0)
        lost = -session.net
        stop = agent.money < 5
        if not stop and lost >= session.budget:
            chase = 0.15 + 0.5 * craving + 0.3 * p.neuroticism - 0.4 * p.conscientiousness
            stop = rng.random() > chase  # « encore une, pour me refaire »… ou pas
            if not stop:
                session.chased = True
        if not stop and session.net > 2 * bet and p.conscientiousness > 0.6:
            stop = rng.random() < 0.5  # un prudent empoche ses gains
        if stop:
            task.ends_at = ctx.now
            self._end_session(ctx, agent)

    def _end_session(self, ctx: SimContext, agent: Agent) -> None:
        session = self._sessions.pop(agent.id, None)
        if session is None or session.rounds == 0:
            return
        net = session.net
        agent.casino_last = net
        agent.casino_total += net
        craving = agent.cravings.get("casino", 0.0)
        # Renforcement intermittent (Skinner) : un gain marque bien plus qu'une perte.
        if net > 0:
            craving += 0.15 + min(0.3, net / 400)
        elif session.chased:
            craving += 0.08  # l'envie de se refaire
        else:
            craving -= 0.05
        agent.cravings["casino"] = max(0.0, min(1.0, craving))
        if net >= 0:
            text = f"J'ai gagné {net:.0f} € au casino ! J'ai hâte d'y retourner"
        elif session.chased:
            text = (
                f"J'ai perdu {-net:.0f} € au casino, j'ai voulu me refaire… "
                "il faut que je me rattrape"
            )
        else:
            text = f"J'ai perdu {-net:.0f} € au casino"
        remember(
            ctx,
            agent,
            MemoryKind.OBSERVATION,
            text,
            min(10, 5 + int(abs(net) / 60)),
            place_id="casino",
        )
        ctx.emit(EventKind.GAMBLED, agent.id, "casino", net=round(net), rounds=session.rounds)
        if abs(net) >= 60:
            self.request_replan(
                ctx,
                agent,
                f"vient de {'gagner' if net > 0 else 'perdre'} {abs(net):.0f} € au casino",
            )

    # ------------------------------------------------------------------ #
    # Replanifier quand la journée bascule (gros gain, licenciement...)
    # ------------------------------------------------------------------ #
    def request_replan(self, ctx: SimContext, agent: Agent, reason: str) -> None:
        if not self.backend.live:
            return  # sans IA, le plan des règles continue
        day = ctx.clock.day_index
        if agent.replans.get(day, 0) >= MAX_REPLANS or ctx.clock.minute_of_day > 21 * 60:
            return
        if agent.id in self._intentions:
            return
        agent.replans[day] = agent.replans.get(day, 0) + 1
        remember(ctx, agent, MemoryKind.OBSERVATION, f"Je repense à ma journée : {reason}", 4)
        self._ask_intentions(ctx, agent, day=day, replan=True)

    # ------------------------------------------------------------------ #
    # La manche
    # ------------------------------------------------------------------ #
    def _begging(self, ctx: SimContext) -> None:
        beggars = [
            a
            for a in ctx.agents.values()
            if a.task is not None
            and a.task.is_performing
            and a.task.step is not None
            and a.task.step.special == "beg"
        ]
        if not beggars:
            return
        rng = ctx.rngs.stream("begging")
        day = ctx.clock.day_index
        tight = ctx.config.settings.economy.tight_budget
        for beggar in beggars:
            # Les passants qu'on ne simule pas : de temps en temps, une pièce.
            if rng.random() < 0.02:
                amount = float(rng.choice((0.5, 1, 1, 2)))
                ctx.economy.transfer(ctx, OUTSIDE, beggar.id, amount)
            for donor in ctx.agents.values():
                if (
                    donor is beggar
                    or donor.homeless
                    or donor.money < 2 * tight
                    or donor.conversation is not None
                    or donor.place_id != beggar.place_id
                ):
                    continue
                if (
                    abs(donor.tile[0] - beggar.tile[0]) + abs(donor.tile[1] - beggar.tile[1])
                    > BEG_RADIUS
                ):
                    continue
                if self._donated.get((donor.id, beggar.id)) == day:
                    continue
                relation = ctx.relations.get(donor.id, beggar.id)
                affinity = relation.affinity if relation is not None else 0.0
                chance = 0.05 * donor.profile.personality.agreeableness + max(0.0, affinity) / 400
                if rng.random() >= chance:
                    continue
                self._donated[(donor.id, beggar.id)] = day
                amount = float(rng.choice((1, 2, 2, 5, 5, 10)))
                ctx.economy.give(ctx, donor, beggar, amount)
                remember(
                    ctx,
                    donor,
                    MemoryKind.OBSERVATION,
                    f"J'ai donné {amount:.0f} € à {beggar.first_name} qui faisait la manche",
                    5,
                    about=(beggar.id,),
                    place_id=beggar.place_id,
                )
                remember(
                    ctx,
                    beggar,
                    MemoryKind.OBSERVATION,
                    f"{donor.first_name} m'a donné {amount:.0f} €",
                    6,
                    about=(donor.id,),
                    place_id=beggar.place_id,
                )
                ctx.relations.meet(donor.profile, beggar.profile, ctx.clock.tick, rng, delta=2)
                ctx.emit(
                    EventKind.DONATION, donor.id, beggar.place_id, other=beggar.id, amount=amount
                )


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def cravings_text(agent: Agent) -> tuple[str, ...]:
    """Les envies, dites comme on se les dit (pour le prompt du soir)."""
    lines: list[str] = []
    casino = agent.cravings.get("casino", 0.0)
    if casino >= 0.15:
        strength = "irrésistible" if casino > 0.7 else "forte" if casino > 0.4 else "une petite"
        last = agent.casino_last
        detail = f"dernière séance : {last:+.0f} €, au total {agent.casino_total:+.0f} €"
        motive = "pour te refaire" if agent.casino_total < 0 else "parce que ça peut payer gros"
        lines.append(f"{strength} envie de retourner au casino, {motive} ({detail})")
    return tuple(lines)
