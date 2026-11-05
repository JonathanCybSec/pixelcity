"""Les panneaux de l'interface : barre du temps, habitants, fiche, lieu, journal.

Chaque panneau est une fonction de dessin qui reçoit le contexte (`UiFrame`)
et renvoie le rectangle qu'il occupe (pour savoir si la souris est « sur
l'interface » et ne pas cliquer dans le monde à travers un panneau).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pygame

from pixelcity.agents.agent import Agent
from pixelcity.agents.tasks import Phase
from pixelcity.memory.stream import Memory, MemoryKind
from pixelcity.sim.events import EventKind
from pixelcity.sim.life import cravings_text
from pixelcity.sim.types import NeedKind, PlaceKind, Pose, format_hhmm
from pixelcity.ui.glass import rounded
from pixelcity.ui.theme import (
    ACCENT,
    ACTIVE_FILL,
    DANGER,
    HOVER_FILL,
    MUTED,
    NEED_COLORS,
    PAD,
    RGB,
    SUCCESS,
    TEXT,
    TEXT_2,
    WARNING,
    Weight,
    hex_to_rgb,
)
from pixelcity.ui.widgets import bar, chip, icon_moon, icon_pause, icon_sun, label

if TYPE_CHECKING:
    from pixelcity.sim.simulation import Simulation
    from pixelcity.ui.ui import UiFrame

PLACE_KIND_LABELS: dict[PlaceKind, str] = {
    PlaceKind.HOME: "Logement",
    PlaceKind.BAKERY: "Boulangerie",
    PlaceKind.CAFE: "Café",
    PlaceKind.OFFICE: "Bureaux",
    PlaceKind.SCHOOL: "École",
    PlaceKind.SUPERMARKET: "Supermarché",
    PlaceKind.GYM: "Salle de sport",
    PlaceKind.PARK: "Parc",
    PlaceKind.CASINO: "Casino",
    PlaceKind.BAR: "Bar",
    PlaceKind.BOUTIQUE: "Boutique de vêtements",
    PlaceKind.ELECTRONICS: "Magasin hi-tech",
}
CAST_WIDTH = 236
CARD_WIDTH = 332
ROW_HEIGHT = 46


def _section(f: UiFrame, text: str, x: int, y: int) -> int:
    label(f.screen, f.texts, text.upper(), (x, y), size=11, color=MUTED, weight=Weight.SEMIBOLD)
    return y + 18


def chevron(screen: pygame.Surface, center: tuple[int, int], opened: bool, color: RGB) -> None:
    """Petite flèche : vers le bas (ouvert) ou vers la droite (replié)."""
    cx, cy = center
    if opened:
        points = [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 3)]
    else:
        points = [(cx - 2, cy - 4), (cx - 2, cy + 4), (cx + 3, cy)]
    pygame.draw.polygon(screen, color, points)


def _fold(
    f: UiFrame,
    key: str,
    title: str,
    x0: int,
    y: int,
    inner: int,
    measure: bool,
    content_height: int,
    draw: Callable[[int], None],
) -> int:
    """Une section repliable (un « menu déroulant ») : on clique le titre pour l'ouvrir."""
    opened = key not in f.state.collapsed
    if not measure:
        header = pygame.Rect(x0 - 6, y - 3, inner + 12, 19)
        if header.collidepoint(f.mouse):
            rounded(f.screen, header, HOVER_FILL, 6)
        chevron(f.screen, (x0 + 3, y + 6), opened, TEXT_2)
        label(
            f.screen,
            f.texts,
            title.upper(),
            (x0 + 13, y),
            size=11,
            color=MUTED,
            weight=Weight.SEMIBOLD,
            max_width=inner - 13,
        )
        if f.screen.get_clip().contains(header):  # pas de zone cliquable invisible
            f.hits.add(header, f"fold:{key}")
    y += 20
    if opened:
        if not measure:
            draw(y)
        y += content_height
    return y + 8


def _ai_planned(agent: Agent, sim: Simulation) -> bool:
    intentions = agent.intentions.get(sim.clock.day_index)
    return intentions is not None and bool(intentions.schedule)


def _reasoning_lines(f: UiFrame, agent: Agent, width: int) -> list[tuple[str, RGB]]:
    """La délibération de son IA (pour / contre) et ses envies, découpées en lignes."""
    lines: list[tuple[str, RGB]] = []
    intentions = agent.intentions.get(f.sim.clock.day_index)
    if intentions is not None and intentions.thought:
        for part in f.texts.wrap(f"« {intentions.thought} »", 12, width):
            lines.append((part, ACCENT))
    for item in agent.deliberation:
        for part in f.texts.wrap(item.choice, 12, width):
            lines.append((part, TEXT))
        for part in f.texts.wrap(f"+ {item.pros}", 12, width):
            lines.append((part, SUCCESS))
        for part in f.texts.wrap(f"− {item.cons}", 12, width):
            lines.append((part, DANGER))
    for craving in cravings_text(agent):
        for part in f.texts.wrap(f"Envie : {craving}", 12, width):
            lines.append((part, WARNING))
    return lines


# --------------------------------------------------------------------------- #
# Barre du temps (en haut, au centre)
# --------------------------------------------------------------------------- #
def top_bar(f: UiFrame) -> pygame.Rect:
    sim, status = f.sim, f.status
    clock = sim.clock
    width = 448
    rect = pygame.Rect((f.width - width) // 2, 12, width, 46)
    f.glass.panel(f.screen, rect, radius=23)
    x, cy = rect.x + 22, rect.centery
    minute = clock.minute_of_day
    if 7 * 60 <= minute < 19 * 60 + 30:
        icon_sun(f.screen, (x, cy), WARNING)
    else:
        icon_moon(f.screen, (x, cy), (210, 220, 255), (28, 31, 44))
    x += 18
    day_name = label(
        f.screen,
        f.texts,
        clock.weekday.label,
        (x, cy - 1),
        size=14,
        weight=Weight.SEMIBOLD,
        anchor="midleft",
    )
    day_rect = label(
        f.screen,
        f.texts,
        f"jour {clock.day_index + 1}",
        (day_name.right + 8, cy),
        size=12,
        color=TEXT_2,
        anchor="midleft",
    )
    time_box = pygame.Rect(day_rect.right + 10, rect.y + 8, 62, 30)
    label(
        f.screen,
        f.texts,
        format_hhmm(minute),
        time_box.center,
        size=19,
        weight=Weight.SEMIBOLD,
        anchor="center",
    )
    # Vitesses : pause, puis ×1, ×3...
    bx = time_box.right + 16
    pygame.draw.line(f.screen, (255, 255, 255), (bx - 8, rect.y + 12), (bx - 8, rect.bottom - 12))
    buttons = [("pause", "")] + [
        (f"speed:{i}", f"×{speed}") for i, speed in enumerate(status.speeds)
    ]
    for action, text in buttons:
        w = 34 if not text else 44
        button = pygame.Rect(bx, rect.y + 9, w, 28)
        active = (status.paused and action == "pause") or (
            not status.paused and action == f"speed:{status.speed_index}"
        )
        hovered = button.collidepoint(f.mouse)
        if active:
            rounded(f.screen, button, ACTIVE_FILL, 14)
        elif hovered:
            rounded(f.screen, button, HOVER_FILL, 14)
        color = ACCENT if active else TEXT
        if action == "pause":
            icon_pause(f.screen, button.center, color)
        else:
            label(
                f.screen,
                f.texts,
                text,
                button.center,
                size=13,
                color=color,
                weight=Weight.MEDIUM,
                anchor="center",
            )
        f.hits.add(button, action)
        bx += w + 2
    _llm_pill(f, rect)
    return rect


def _llm_pill(f: UiFrame, bar: pygame.Rect) -> None:
    """Sous l'horloge : qui écrit les répliques (le LLM local, ou le script de repli)."""
    text = f.sim.conversations.status()
    live = text.startswith("IA locale") and f.sim.conversations.backend.live
    if not live:
        text = "IA absente : règles de secours · " + text
    text_rect = f.texts.render(text[:70], 12, TEXT_2, Weight.MEDIUM).get_rect()
    pill = pygame.Rect(0, bar.bottom + 6, text_rect.width + 30, 22)
    pill.centerx = bar.centerx
    f.glass.panel(f.screen, pill, radius=11)
    dot = (pill.x + 12, pill.centery)
    pygame.draw.circle(f.screen, SUCCESS if live else DANGER, dot, 4)
    label(
        f.screen,
        f.texts,
        text[:70],
        (pill.x + 22, pill.centery),
        size=12,
        color=TEXT_2,
        weight=Weight.MEDIUM,
        anchor="midleft",
    )


# --------------------------------------------------------------------------- #
# Liste des habitants (à gauche)
# --------------------------------------------------------------------------- #
def cast_panel(f: UiFrame) -> pygame.Rect:
    agents = list(f.sim.agents.values())
    opened = "habitants" not in f.state.collapsed
    # Jamais sous le journal : avec beaucoup d'habitants, les lignes se resserrent.
    journal_top = f.height - 12 - journal_height(f)
    available = journal_top - 12 - 72 - 46
    row_height = (
        ROW_HEIGHT
        if ROW_HEIGHT * len(agents) <= available
        else max(24, available // max(1, len(agents)))
    )
    height = 40 + row_height * len(agents) + 6 if opened else 38
    rect = pygame.Rect(12, 72, CAST_WIDTH, height)
    f.glass.panel(f.screen, rect)
    header = pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, 30)
    if header.collidepoint(f.mouse):
        rounded(f.screen, header, HOVER_FILL, 10)
    chevron(f.screen, (rect.x + PAD + 3, rect.y + 20), opened, TEXT_2)
    label(
        f.screen,
        f.texts,
        "Habitants",
        (rect.x + PAD + 13, rect.y + 12),
        size=14,
        weight=Weight.SEMIBOLD,
    )
    f.hits.add(header, "fold:habitants")
    label(
        f.screen,
        f.texts,
        str(len(agents)),
        (rect.right - PAD, rect.y + 13),
        size=12,
        color=MUTED,
        anchor="topright",
    )
    if not opened:
        return rect
    compact = row_height < 40
    y = rect.y + 38
    for agent in agents:
        row = pygame.Rect(rect.x + 6, y, rect.width - 12, row_height - 2)
        selected = agent.id == f.state.selected_agent
        if selected:
            rounded(f.screen, row, ACTIVE_FILL, 10)
        elif row.collidepoint(f.mouse) or agent.id == f.state.hover_agent:
            rounded(f.screen, row, HOVER_FILL, 10)
        color = hex_to_rgb(agent.profile.color)
        radius = 16 if not compact else max(8, row_height // 2 - 3)
        f.avatars.draw(f.screen, agent.profile.sprite, (row.x + 22, row.centery), radius, color)
        tx = row.x + 46
        name_y = row.y + 5 if not compact else row.centery - 8
        name = label(
            f.screen, f.texts, agent.first_name, (tx, name_y), size=13, weight=Weight.SEMIBOLD
        )
        status = agent.status_text()
        if (
            agent.pose is Pose.LIE
            and agent.task is not None
            and agent.task.recipe_id in ("sleep", "nap")
        ):
            status = "dort"
        status_pos = (tx, row.y + 23) if not compact else (name.right + 8, name_y + 1)
        label(
            f.screen,
            f.texts,
            status,
            status_pos,
            size=12,
            color=TEXT_2,
            max_width=row.right - status_pos[0] - 22,
        )
        worst = min(NeedKind, key=lambda need: agent.needs[need])
        if agent.needs[worst] < 30:
            pygame.draw.circle(f.screen, NEED_COLORS[worst], (row.right - 10, row.centery), 4)
        f.hits.add(row, f"agent:{agent.id}")
        y += row_height
    return rect


# --------------------------------------------------------------------------- #
# Fiche d'un habitant (à droite)
# --------------------------------------------------------------------------- #
def _shown_memories(agent: Agent) -> list[Memory]:
    stream = agent.memory
    thought = stream.recent(1, (MemoryKind.REFLECTION,))
    recent = [m for m in stream.recent(3) if m not in thought][: 3 - len(thought)]
    return thought + recent


def agent_card(f: UiFrame, agent_id: str, slide: float) -> pygame.Rect:
    sim = f.sim
    agent = sim.agents[agent_id]
    profile = agent.profile
    color = hex_to_rgb(profile.color)
    max_height = f.height - 72 - 12
    x = f.width - 12 - CARD_WIDTH + round((1.0 - slide) * 48)
    rect = pygame.Rect(x, 72, CARD_WIDTH, max_height)
    content_height = _agent_card_content(f, agent_id, rect, color, measure=True)
    rect.height = min(max_height, content_height)
    f.glass.panel(f.screen, rect)
    # Trop long pour l'écran : on coupe au bord (replier une section libère de la place).
    previous_clip = f.screen.get_clip()
    f.screen.set_clip(rect.inflate(-2, -6))
    _agent_card_content(f, agent_id, rect, color, measure=False)
    f.screen.set_clip(previous_clip)
    return rect


def _agent_card_content(
    f: UiFrame, agent_id: str, rect: pygame.Rect, color: tuple[int, int, int], *, measure: bool
) -> int:
    """Dessine (ou mesure seulement) le contenu ; renvoie la hauteur utile."""
    sim = f.sim
    agent = sim.agents[agent_id]
    screen = f.screen
    texts = f.texts
    x0, inner = rect.x + PAD, rect.width - 2 * PAD
    y = rect.y + PAD

    # --- En-tête -------------------------------------------------------------------------
    if not measure:
        f.avatars.draw(screen, agent.profile.sprite, (x0 + 26, y + 26), 26, color)
        label(
            screen,
            texts,
            agent.name,
            (x0 + 64, y + 4),
            size=17,
            weight=Weight.SEMIBOLD,
            max_width=inner - 90,
        )
        label(
            screen,
            texts,
            f"{agent.profile.job} · {agent.profile.age} ans · {agent.money:.0f} €",
            (x0 + 64, y + 27),
            size=12,
            color=TEXT_2,
            max_width=inner - 70,
        )
        where = sim.world.places[agent.place_id].name if agent.place_id else "dans la rue"
        if agent.homeless:
            where = f"SANS DOMICILE · {where}"
        label(screen, texts, where, (x0 + 64, y + 44), size=12, color=color, max_width=inner - 70)
        close = pygame.Rect(rect.right - 34, rect.y + 10, 24, 24)
        if close.collidepoint(f.mouse):
            rounded(screen, close, HOVER_FILL, 12)
        label(screen, texts, "×", close.center, size=18, color=TEXT_2, anchor="center")
        f.hits.add(close, "close")
    y += 66

    # --- Maintenant -----------------------------------------------------------------------
    task = agent.task
    if not measure:
        y = _section(f, "Maintenant", x0, y)
        label(
            screen,
            texts,
            agent.status_text(),
            (x0, y),
            size=14,
            weight=Weight.SEMIBOLD,
            max_width=inner,
        )
        if task is not None:
            label(
                screen, texts, task.label, (x0, y + 20), size=12, color=TEXT_2, max_width=inner - 70
            )
            if task.phase is Phase.PERFORM and task.step_ends > task.step_started:
                done = (sim.ctx.now_exact - task.step_started) / (
                    task.step_ends - task.step_started
                )
                bar(screen, pygame.Rect(rect.right - PAD - 60, y + 26, 60, 5), done, color)
    else:
        y += 18
    y += 46

    # --- Sections repliables (clic sur le titre) -------------------------------------------
    def need_rows(top: int) -> None:
        for k, need in enumerate(NeedKind):
            row_y = top + 20 * k
            value = f.smoothed(agent.id, need, agent.needs[need])
            label(screen, texts, need.label, (x0, row_y), size=12, color=TEXT_2)
            need_color = NEED_COLORS[need] if value >= 20 else DANGER
            bar(screen, pygame.Rect(x0 + 70, row_y + 6, inner - 110, 6), value / 100, need_color)
            label(
                screen,
                texts,
                f"{value:.0f}",
                (rect.right - PAD, row_y),
                size=12,
                weight=Weight.MEDIUM,
                anchor="topright",
            )

    y = _fold(f, "besoins", "Besoins", x0, y, inner, measure, 20 * len(NeedKind), need_rows)

    # Envies et délibération : ce que son IA a pesé pour sa journée.
    reasoning = _reasoning_lines(f, agent, inner)

    def reasoning_rows(top: int) -> None:
        for k, (text, tone) in enumerate(reasoning):
            label(screen, texts, text, (x0, top + 17 * k), size=12, color=tone)

    if reasoning:
        y = _fold(
            f,
            "reflexion",
            "Réflexion : pour et contre",
            x0,
            y,
            inner,
            measure,
            17 * len(reasoning),
            reasoning_rows,
        )

    items = sim.config.actions.items
    owned = [items[i].label if i in items else i for i in agent.possessions]

    def bag_rows(top: int) -> None:
        cx = x0
        if not agent.inventory:
            label(screen, texts, "rien sur soi", (x0, top), size=12, color=MUTED)
        for item, count in agent.inventory.items():
            name = items[item].label if item in items else item
            text = name if count == 1 else f"{name} ×{count}"
            cx = chip(screen, texts, text, (cx, top - 2)).right + 6
        if owned:
            label(
                screen,
                texts,
                "Possède : " + ", ".join(owned),
                (x0, top + 24),
                size=12,
                color=TEXT_2,
                max_width=inner,
            )

    y = _fold(f, "sac", "Sac et biens", x0, y, inner, measure, 26 + (20 if owned else 0), bag_rows)

    relations = sim.relations.of(agent.id)[:5]

    def relation_rows(top: int) -> None:
        for k, (other_id, relation) in enumerate(relations):
            row_y = top + 22 * k
            other = sim.agents[other_id]
            other_color = hex_to_rgb(other.profile.color)
            f.avatars.draw(screen, other.profile.sprite, (x0 + 10, row_y + 9), 10, other_color)
            label(
                screen, texts, other.first_name, (x0 + 26, row_y + 1), size=12, weight=Weight.MEDIUM
            )
            stage = relation.stage + (" · flirt" if relation.flirts else "")
            label(screen, texts, stage, (x0 + 100, row_y + 1), size=12, color=TEXT_2)
            affinity = (relation.affinity + 100) / 200
            bar(screen, pygame.Rect(rect.right - PAD - 70, row_y + 7, 70, 5), affinity, ACCENT)

    if relations:
        y = _fold(
            f, "relations", "Relations", x0, y, inner, measure, 22 * len(relations), relation_rows
        )

    memories = _shown_memories(agent)

    def memory_rows(top: int) -> None:
        for k, memory in enumerate(memories):
            reflection = memory.kind is MemoryKind.REFLECTION
            text = f"« {memory.text} »" if reflection else memory.text
            label(
                screen,
                texts,
                text,
                (x0, top + 20 * k),
                size=12,
                color=ACCENT if reflection else TEXT_2,
                max_width=inner,
            )

    if memories:
        y = _fold(f, "memoire", "En tête", x0, y, inner, measure, 20 * len(memories), memory_rows)

    plan = agent.plan
    blocks = plan.blocks if plan is not None else ()
    current = agent.block_index

    def plan_rows(top: int) -> None:
        for index, block in enumerate(blocks):
            row_y = top + 19 * index
            is_current = index == current
            if is_current:
                rounded(screen, pygame.Rect(x0 - 6, row_y - 2, inner + 12, 19), ACTIVE_FILL, 6)
            tone = TEXT if is_current else (MUTED if index < current else TEXT_2)
            label(
                screen,
                texts,
                format_hhmm(block.start % (24 * 60)),
                (x0, row_y),
                size=12,
                color=tone,
                weight=Weight.MEDIUM,
            )
            place = sim.world.places[block.place_id].name
            label(
                screen,
                texts,
                f"{block.label} · {place}",
                (x0 + 46, row_y),
                size=12,
                color=tone,
                max_width=inner - 46,
            )

    if blocks:
        source = "programme choisi par son IA" if _ai_planned(agent, sim) else "programme"
        y = _fold(
            f, "plan", f"Aujourd'hui · {source}", x0, y, inner, measure, 19 * len(blocks), plan_rows
        )

    # --- Suivre ----------------------------------------------------------------------------------
    if not measure:
        button = pygame.Rect(x0, y, inner, 30)
        following = f.state.follow
        rounded(screen, button, ACTIVE_FILL if following else HOVER_FILL, 15)
        text = "Caméra : suit l'habitant (F)" if following else "Suivre avec la caméra (F)"
        label(
            screen,
            texts,
            text,
            button.center,
            size=12,
            color=ACCENT if following else TEXT,
            weight=Weight.MEDIUM,
            anchor="center",
        )
        f.hits.add(button, "follow")
    y += 30 + PAD
    return y - rect.y


# --------------------------------------------------------------------------- #
# Fiche d'un lieu (à droite, quand aucun habitant n'est sélectionné)
# --------------------------------------------------------------------------- #
def place_card(f: UiFrame, place_id: str, slide: float) -> pygame.Rect:
    sim = f.sim
    place = sim.world.places[place_id]
    clock = sim.clock
    x = f.width - 12 - CARD_WIDTH + round((1.0 - slide) * 48)
    occupants = [sim.agents[a] for a in place.occupants if a in sim.agents]
    containers = [furn for furn in place.furniture if furn.container is not None]
    desks = sim.ctx.desks_in(place.id)
    height = (
        104 + 22 + max(1, len(occupants)) * 22 + (30 + 20 * len(containers) if containers else 0)
    )
    height += 26 * len(desks) + PAD
    rect = pygame.Rect(x, 72, CARD_WIDTH, min(height, f.height - 84))
    f.glass.panel(f.screen, rect)
    screen, texts = f.screen, f.texts
    x0, inner = rect.x + PAD, rect.width - 2 * PAD
    y = rect.y + PAD
    label(screen, texts, place.name, (x0, y), size=17, weight=Weight.SEMIBOLD, max_width=inner - 30)
    close = pygame.Rect(rect.right - 34, rect.y + 10, 24, 24)
    label(screen, texts, "×", close.center, size=18, color=TEXT_2, anchor="center")
    f.hits.add(close, "close")
    y += 28
    open_now = place.hours.is_open(clock.weekday.number, clock.minute_of_day)
    state_chip = chip(
        screen,
        texts,
        "ouvert" if open_now else "fermé",
        (x0, y),
        fill=(*(SUCCESS if open_now else DANGER), 50),
        color=SUCCESS if open_now else DANGER,
    )
    label(
        screen,
        texts,
        f"{PLACE_KIND_LABELS.get(place.kind, place.kind.value)} · {place.hours.describe()}",
        (state_chip.right + 8, y + 3),
        size=12,
        color=TEXT_2,
        max_width=inner - state_chip.width - 8,
    )
    y += 36
    revenue = f.sim.economy.revenue.get(place.id)
    rent = f.sim.config.place(place.id).rent
    money_text = None
    if revenue:
        money_text = f"Recettes : {revenue:.2f} € · {f.sim.economy.sales[place.id]} ventes"
    elif rent:
        money_text = f"Loyer : {rent:.0f} € par jour"
    if money_text is not None:
        label(screen, texts, money_text, (x0, y - 6), size=12, color=TEXT_2)
        y += 20
    y = _section(f, f"Présents ({len(occupants)})", x0, y)
    if not occupants:
        label(screen, texts, "personne", (x0, y), size=12, color=MUTED)
        y += 22
    for occupant in occupants:
        row = pygame.Rect(x0 - 6, y - 2, inner + 12, 20)
        if row.collidepoint(f.mouse):
            rounded(screen, row, HOVER_FILL, 6)
        f.avatars.draw(
            screen, occupant.profile.sprite, (x0 + 9, y + 8), 9, hex_to_rgb(occupant.profile.color)
        )
        label(screen, texts, occupant.first_name, (x0 + 26, y), size=12, weight=Weight.MEDIUM)
        label(
            screen,
            texts,
            occupant.status_text(),
            (x0 + 96, y),
            size=12,
            color=TEXT_2,
            max_width=inner - 96,
        )
        f.hits.add(row, f"agent:{occupant.id}")
        y += 22
    items = sim.config.actions.items
    if containers:
        y += 8
        y = _section(f, "Stocks", x0, y)
        for furniture in containers:
            assert furniture.container is not None
            for item, count in furniture.container.items.items():
                name = items[item].label if item in items else item
                quantity = "illimité" if count < 0 else f"{count} / {furniture.container.capacity}"
                label(screen, texts, f"{name} ({furniture.label})", (x0, y), size=12, color=TEXT_2)
                label(
                    screen,
                    texts,
                    quantity,
                    (rect.right - PAD, y),
                    size=12,
                    weight=Weight.MEDIUM,
                    anchor="topright",
                )
                y += 20
    for desk in desks:
        y += 6
        queue = len(desk.queue)
        text = f"Comptoir : {queue} en file · {desk.served} servis"
        label(screen, texts, text, (x0, y), size=12, color=TEXT_2)
        y += 20
    return rect


# --------------------------------------------------------------------------- #
# Journal (en bas à gauche)
# --------------------------------------------------------------------------- #
JOURNAL_LINES = 7


def journal_height(f: UiFrame) -> int:
    return 40 + JOURNAL_LINES * 20 + 10 if "journal" not in f.state.collapsed else 40


def journal_panel(f: UiFrame) -> pygame.Rect:
    width = min(600, max(380, int(f.width * 0.44)))
    height = journal_height(f)
    rect = pygame.Rect(12, f.height - 12 - height, width, height)
    f.glass.panel(f.screen, rect)
    screen, texts = f.screen, f.texts
    x0 = rect.x + PAD
    opened = "journal" not in f.state.collapsed
    header = pygame.Rect(rect.x + 4, rect.y + 6, 80, 28)
    if header.collidepoint(f.mouse):
        rounded(screen, header, HOVER_FILL, 10)
    chevron(screen, (x0 + 3, rect.y + 20), opened, TEXT_2)
    label(screen, texts, "Journal", (x0 + 13, rect.y + 12), size=14, weight=Weight.SEMIBOLD)
    f.hits.add(header, "fold:journal")
    tabs = [("all", "Tout"), ("talk", "Dialogues")]
    selected = f.state.selected_agent
    if selected is not None:
        tabs.append(("agent", f.sim.agents[selected].first_name))
    tx = x0 + 86
    for mode, text in tabs:
        surface = texts.render(text, 12, TEXT, Weight.MEDIUM)
        tab = pygame.Rect(tx, rect.y + 9, surface.get_width() + 18, 24)
        active = f.state.journal_mode == mode
        if active:
            rounded(screen, tab, ACTIVE_FILL, 12)
        elif tab.collidepoint(f.mouse):
            rounded(screen, tab, HOVER_FILL, 12)
        label(
            screen,
            texts,
            text,
            tab.center,
            size=12,
            color=ACCENT if active else TEXT_2,
            weight=Weight.MEDIUM,
            anchor="center",
        )
        f.hits.add(tab, f"journal:{mode}")
        tx = tab.right + 4
    if not opened:
        return rect
    mode = f.state.journal_mode if (f.state.journal_mode != "agent" or selected) else "all"
    entries = f.feed.entries(mode, selected, JOURNAL_LINES)
    y = rect.y + 42
    for entry in entries:
        label(screen, texts, entry.stamp, (x0, y), size=12, color=MUTED, weight=Weight.MEDIUM)
        if entry.kind is EventKind.SAY:
            tone = TEXT
        elif entry.kind is EventKind.RELATION:
            tone = ACCENT
        elif entry.kind in (EventKind.TASK_FAILED, EventKind.NEED_CRITICAL, EventKind.STOCK_EMPTY):
            tone = WARNING
        else:
            tone = TEXT_2
        label(
            screen,
            texts,
            entry.text,
            (x0 + 46, y),
            size=12,
            color=tone,
            max_width=rect.width - 2 * PAD - 46,
        )
        y += 20
    if not entries:
        label(screen, texts, "Rien pour l'instant…", (x0, y), size=12, color=MUTED)
    return rect


def help_hint(f: UiFrame) -> pygame.Rect:
    text = (
        "Clic : choisir · glisser : déplacer · molette : zoom · "
        "Espace : pause · 1-4 : vitesse · H : masquer"
    )
    surface = f.texts.render(
        f.texts.fit(text, 11, max(200, f.width - 680)), 11, TEXT_2, Weight.MEDIUM
    )
    rect = surface.get_rect(bottomright=(f.width - 22, f.height - 18)).inflate(20, 10)
    rounded(f.screen, rect, (16, 18, 28, 170), rect.height // 2)
    f.screen.blit(surface, surface.get_rect(center=rect.center))
    return rect
