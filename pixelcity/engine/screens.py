"""Écrans hors partie : le menu d'accueil et le studio de création d'habitants.

Chaque écran a la même forme : `frame(events, dt)` dessine une image et
renvoie éventuellement une décision (« jouer ce scénario », « retour »...).
C'est le lanceur (`launcher.py`) qui enchaîne les écrans : une petite
machine à états, comme le menu d'une console de jeu.

Derrière, la ville défile doucement (`Backdrop`) : c'est une vraie
simulation figée à midi, rendue par le même moteur que la partie.
"""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass, field

import pygame

from pixelcity.config.loader import GameConfig
from pixelcity.engine.camera import Camera
from pixelcity.engine.renderer import WorldRenderer
from pixelcity.engine.sprites import IDLE_FRAME, WALK_CYCLE
from pixelcity.llm.client import LlmError, OllamaClient
from pixelcity.llm.settings import LlmSettings
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import Facing
from pixelcity.studio import scenario as sc
from pixelcity.studio.presets import ACCENT_COLORS, IDEOLOGIES, JOBS, JOBS_BY_KEY, SPEECH_STYLES
from pixelcity.ui.forms import Form
from pixelcity.ui.glass import Glass, rounded
from pixelcity.ui.theme import (
    ACCENT,
    GLASS_FILL_STRONG,
    MUTED,
    SUCCESS,
    TEXT,
    TEXT_2,
    WARNING,
    Fonts,
    TextCache,
    Weight,
    hex_to_rgb,
)
from pixelcity.ui.widgets import Avatars, label

VEIL = (10, 12, 20, 120)
TRAIT_LABELS = {
    "openness": ("Ouverture", "routinier", "curieux"),
    "conscientiousness": ("Rigueur", "bohème", "organisé"),
    "extraversion": ("Extraversion", "réservé", "bavard"),
    "agreeableness": ("Amabilité", "franc", "chaleureux"),
    "neuroticism": ("Émotivité", "calme", "anxieux"),
}
AGES = list(range(16, 91))


@dataclass(slots=True)
class Shared:
    """Ce que tous les écrans partagent : polices, verre, ville de fond."""

    config: GameConfig
    llm: LlmSettings
    fonts: Fonts = field(default_factory=Fonts)
    texts: TextCache = field(init=False)
    glass: Glass = field(default_factory=Glass)
    backdrop: Backdrop | None = None

    def __post_init__(self) -> None:
        self.texts = TextCache(self.fonts)


class Backdrop:
    """La ville en fond d'écran, la caméra en lente promenade."""

    def __init__(self, config: GameConfig) -> None:
        self.sim = Simulation(config)
        self.sim.run_ticks(round(11.5 * 60 * self.sim.clock.ticks_per_minute))
        self.renderer = WorldRenderer(self.sim)
        self.avatars = Avatars(self.renderer.bank)
        self.camera: Camera | None = None
        self.t = 0.0

    def draw(self, screen: pygame.Surface, dt: float) -> None:
        self.t += dt
        size = screen.get_size()
        if self.camera is None or (self.camera.view_width, self.camera.view_height) != size:
            self.camera = Camera.centered(size, self.renderer.world_size, 3)
        w, h = self.renderer.world_size
        # Une ellipse lente autour du centre-ville : de quoi donner vie au menu.
        self.camera.center_x = w / 2 + math.cos(self.t * 0.05) * w * 0.25
        self.camera.center_y = h / 2 + math.sin(self.t * 0.05) * h * 0.2
        self.camera.clamp()
        self.renderer.draw(screen, self.sim, self.camera, 0.0, self.t)
        veil = pygame.Surface(size, pygame.SRCALPHA)
        veil.fill(VEIL)
        screen.blit(veil, (0, 0))


def _title(
    shared: Shared, screen: pygame.Surface, text: str, pos: tuple[int, int], size: int = 22
) -> pygame.Rect:
    return label(screen, shared.texts, text, pos, size=size, weight=Weight.SEMIBOLD)


def _section(shared: Shared, screen: pygame.Surface, text: str, pos: tuple[int, int]) -> None:
    label(screen, shared.texts, text.upper(), pos, size=11, color=MUTED, weight=Weight.SEMIBOLD)


# --------------------------------------------------------------------------- #
# Menu d'accueil
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MenuChoice:
    action: str  # "play", "studio", "quit"
    scenario: sc.Scenario | None = None


class MenuScreen:
    def __init__(self, shared: Shared) -> None:
        self.shared = shared
        self.form = Form(shared.texts)
        self.scenarios = sc.list_scenarios()
        self.scroll = 0

    def frame(
        self, screen: pygame.Surface, events: list[pygame.event.Event], dt: float
    ) -> MenuChoice | None:
        shared, form = self.shared, self.form
        form.begin(events)
        if shared.backdrop is not None:
            shared.backdrop.draw(screen, dt)
        else:
            screen.fill((14, 16, 24))
        if form.escape:
            return MenuChoice("quit")
        width, height = screen.get_size()
        rows = len(self.scenarios)
        card_h = min(height - 60, 330 + max(1, rows) * 52)
        card = pygame.Rect(0, 0, 520, card_h)
        card.center = (width // 2, height // 2)
        shared.glass.panel(screen, card, radius=22, fill=GLASS_FILL_STRONG)
        x, y = card.x + 32, card.y + 28
        _title(shared, screen, "PixelCity", (x, y), 34)
        label(
            screen,
            shared.texts,
            "Une ville en pixel art, des habitants pilotés par une IA locale.",
            (x, y + 46),
            size=13,
            color=TEXT_2,
        )
        y += 86
        choice: MenuChoice | None = None
        if form.button(
            screen,
            pygame.Rect(x, y, card.width - 64, 44),
            "Jouer avec les habitants d'origine",
            primary=True,
            size=15,
        ):
            choice = MenuChoice("play", None)
        y += 62
        _section(shared, screen, "Mes scénarios", (x, y))
        y += 22
        if not self.scenarios:
            label(
                screen,
                shared.texts,
                "Aucun pour l'instant : crée tes habitants dans le studio.",
                (x, y + 8),
                size=13,
                color=MUTED,
            )
            y += 44
        list_bottom = card.bottom - 140
        visible = max(1, (list_bottom - y) // 52)
        if form.hovered(pygame.Rect(card.x, y, card.width, visible * 52)) and form.wheel:
            self.scroll = max(0, min(rows - visible, self.scroll - form.wheel))
        for scenario in self.scenarios[self.scroll : self.scroll + visible]:
            row = pygame.Rect(x, y, card.width - 64, 46)
            rounded(screen, row, (255, 255, 255, 12), 12)
            label(
                screen,
                shared.texts,
                shared.texts.fit(scenario.name, 15, 230),
                (row.x + 14, row.y + 6),
                size=15,
                weight=Weight.SEMIBOLD,
            )
            label(
                screen,
                shared.texts,
                f"{len(scenario.agents)} habitants",
                (row.x + 14, row.y + 26),
                size=12,
                color=TEXT_2,
            )
            if form.button(screen, pygame.Rect(row.right - 196, row.y + 9, 90, 28), "Modifier"):
                choice = MenuChoice("studio", scenario)
            if form.button(
                screen, pygame.Rect(row.right - 100, row.y + 9, 90, 28), "Jouer", primary=True
            ):
                choice = MenuChoice("play", scenario)
            y += 52
        y = card.bottom - 120
        if form.button(
            screen, pygame.Rect(x, y, card.width - 64, 42), "Studio : créer mes habitants", size=14
        ):
            choice = MenuChoice("studio", None)
        if form.button(screen, pygame.Rect(x, y + 52, card.width - 64, 36), "Quitter"):
            choice = MenuChoice("quit")
        llm = shared.llm
        status = (
            f"IA : Ollama · {llm.model}"
            if llm.enabled
            else "IA désactivée (.env) : répliques scriptées"
        )
        label(
            screen,
            shared.texts,
            status,
            (card.centerx, card.bottom - 14),
            size=11,
            color=MUTED,
            anchor="center",
        )
        form.end()
        return choice


# --------------------------------------------------------------------------- #
# Studio
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class StudioChoice:
    action: str  # "menu", "play"
    scenario: sc.Scenario | None = None


class StudioScreen:
    def __init__(self, shared: Shared, scenario: sc.Scenario | None) -> None:
        self.shared = shared
        self.form = Form(shared.texts)
        self.scenario = scenario or sc.default_scenario(shared.config)
        if scenario is None:
            self.scenario.name = "Ma ville"
        self.selected = 0
        self.scroll = 0
        self.rng = random.Random()
        self.message: tuple[str, tuple[int, int, int]] | None = None
        self.t = 0.0
        self.models: list[str] = []
        if shared.llm.enabled:
            threading.Thread(target=self._fetch_models, daemon=True).start()

    def _fetch_models(self) -> None:
        try:
            client = OllamaClient(self.shared.llm.host, 3.0)
            self.models = sorted(m.removesuffix(":latest") for m in client.models())
        except LlmError:
            self.models = []

    @property
    def draft(self) -> sc.AgentDraft | None:
        agents = self.scenario.agents
        if not agents:
            return None
        self.selected = max(0, min(self.selected, len(agents) - 1))
        return agents[self.selected]

    # ------------------------------------------------------------------ #
    def frame(
        self, screen: pygame.Surface, events: list[pygame.event.Event], dt: float
    ) -> StudioChoice | None:
        self.t += dt
        shared, form = self.shared, self.form
        form.begin(events)
        if shared.backdrop is not None:
            shared.backdrop.draw(screen, dt)
        else:
            screen.fill((14, 16, 24))
        if form.escape:
            return StudioChoice("menu")
        width, height = screen.get_size()
        left = pygame.Rect(16, 16, 290, height - 32)
        right = pygame.Rect(left.right + 14, 16, width - left.right - 30, height - 32)
        shared.glass.panel(screen, left, radius=18, fill=GLASS_FILL_STRONG)
        shared.glass.panel(screen, right, radius=18, fill=GLASS_FILL_STRONG)
        self._roster(screen, left)
        if self.draft is not None:
            self._editor(
                screen,
                pygame.Rect(right.x + 24, right.y + 20, right.width - 48, right.height - 100),
                self.draft,
            )
        else:
            label(
                screen,
                shared.texts,
                "Ajoute un habitant à gauche.",
                right.center,
                size=15,
                color=TEXT_2,
                anchor="center",
            )
        choice = self._footer(
            screen, pygame.Rect(right.x + 24, right.bottom - 66, right.width - 48, 50)
        )
        form.end()
        return choice

    def _roster(self, screen: pygame.Surface, rect: pygame.Rect) -> None:
        shared, form, scenario = self.shared, self.form, self.scenario
        x, y = rect.x + 18, rect.y + 18
        _title(shared, screen, "Studio", (x, y))
        y += 40
        _section(shared, screen, "Nom du scénario", (x, y))
        scenario.name = form.text(
            screen,
            pygame.Rect(x, y + 18, rect.width - 36, 34),
            "scenario",
            scenario.name,
            placeholder="Ma ville",
            max_len=40,
        )
        y += 66
        _section(shared, screen, f"Habitants ({len(scenario.agents)}/{sc.MAX_AGENTS})", (x, y))
        y += 20
        bottom = rect.bottom - 100
        visible = max(1, (bottom - y) // 54)
        if form.hovered(pygame.Rect(rect.x, y, rect.width, bottom - y)) and form.wheel:
            self.scroll = max(0, min(len(scenario.agents) - visible, self.scroll - form.wheel))
            form.wheel = 0
        for index in range(self.scroll, min(len(scenario.agents), self.scroll + visible)):
            draft = scenario.agents[index]
            row = pygame.Rect(rect.x + 10, y, rect.width - 20, 50)
            if index == self.selected:
                rounded(screen, row, (124, 196, 255, 46), 12)
            elif form.hovered(row):
                rounded(screen, row, (255, 255, 255, 14), 12)
            if shared.backdrop is not None:
                shared.backdrop.avatars.draw(
                    screen, draft.sprite, (row.x + 26, row.centery), 18, hex_to_rgb(draft.color)
                )
            label(
                screen,
                shared.texts,
                shared.texts.fit(draft.name or "(sans nom)", 14, row.width - 70),
                (row.x + 54, row.y + 7),
                size=14,
                weight=Weight.SEMIBOLD,
            )
            job = JOBS_BY_KEY.get(draft.job)
            title = draft.job_title or (job.label if job else "?")
            label(
                screen,
                shared.texts,
                f"{title} · {draft.age} ans",
                (row.x + 54, row.y + 27),
                size=12,
                color=TEXT_2,
            )
            if form._clicked(row):
                self.selected = index
            y += 54
        bx, by = rect.x + 14, rect.bottom - 92
        half = (rect.width - 34) // 2
        full = len(scenario.agents) >= sc.MAX_AGENTS
        if form.button(screen, pygame.Rect(bx, by, half, 34), "+ Nouveau", enabled=not full):
            draft = sc.AgentDraft(
                name=f"Habitant {len(scenario.agents) + 1}",
                home=sc.free_home(scenario, shared.config),
                color=self.rng.choice(ACCENT_COLORS),
            )
            self._add(draft)
        if form.button(
            screen, pygame.Rect(bx + half + 6, by, half, 34), "Au hasard", enabled=not full
        ):
            self._add(sc.random_draft(scenario, shared.config, self.rng))
        current = self.draft
        if (
            form.button(
                screen,
                pygame.Rect(bx, by + 42, half, 34),
                "Dupliquer",
                enabled=current is not None and not full,
            )
            and current is not None
        ):
            copy = sc.AgentDraft(
                **{f: getattr(current, f) for f in sc.AgentDraft.__dataclass_fields__}
            )
            copy.personality = dict(current.personality)
            copy.name = current.name + " bis"
            copy.home = sc.free_home(scenario, shared.config)
            self._add(copy)
        if (
            form.button(
                screen,
                pygame.Rect(bx + half + 6, by + 42, half, 34),
                "Supprimer",
                enabled=current is not None,
            )
            and current is not None
        ):
            scenario.agents.pop(self.selected)
            self.selected = max(0, self.selected - 1)

    def _add(self, draft: sc.AgentDraft) -> None:
        self.scenario.agents.append(draft)
        self.selected = len(self.scenario.agents) - 1

    # ------------------------------------------------------------------ #
    def _editor(self, screen: pygame.Surface, rect: pygame.Rect, draft: sc.AgentDraft) -> None:
        shared, form = self.shared, self.form
        col_w = (rect.width - 40) // 3
        a = pygame.Rect(rect.x, rect.y, col_w, rect.height)
        b = pygame.Rect(a.right + 20, rect.y, col_w, rect.height)
        c = pygame.Rect(b.right + 20, rect.y, col_w, rect.height)

        # --- Identité -----------------------------------------------------------------
        y = a.y
        _section(shared, screen, "Identité", (a.x, y))
        draft.name = form.text(
            screen,
            pygame.Rect(a.x, y + 18, a.width, 34),
            f"name:{self.selected}",
            draft.name,
            placeholder="Prénom Nom",
            max_len=40,
        )
        y += 66
        preview = pygame.Rect(a.x, y, a.width, 160)
        rounded(screen, preview, (255, 255, 255, 10), 14)
        if shared.backdrop is not None:
            sheet = shared.backdrop.renderer.bank.character(draft.sprite)
            step = WALK_CYCLE[int(self.t * 6) % len(WALK_CYCLE)]
            facing = (Facing.DOWN, Facing.RIGHT, Facing.UP, Facing.LEFT)[int(self.t / 2) % 4]
            frame = sheet.frame(facing, step if int(self.t / 2) % 2 == 0 else IDLE_FRAME)
            big = pygame.transform.scale_by(frame, 5)
            screen.blit(big, big.get_rect(center=(preview.centerx, preview.centery - 4)))
        draft.sprite = form.choice(
            screen,
            pygame.Rect(a.x, preview.bottom + 8, a.width, 32),
            [f"Apparence {i + 1} / 6" for i in range(6)],
            draft.sprite,
        )
        y = preview.bottom + 52
        swatch = (a.width - 11 * 4) // 12
        for i, color in enumerate(ACCENT_COLORS):
            cell = pygame.Rect(a.x + i * (swatch + 4), y, swatch, swatch)
            pygame.draw.rect(screen, hex_to_rgb(color), cell, border_radius=swatch // 2)
            if color == draft.color:
                pygame.draw.rect(
                    screen, TEXT, cell.inflate(4, 4), width=2, border_radius=swatch // 2 + 2
                )
            if form._clicked(cell):
                draft.color = color
        y += swatch + 18
        _section(shared, screen, "Âge", (a.x, y))
        index = AGES.index(draft.age) if draft.age in AGES else AGES.index(30)
        draft.age = AGES[
            form.choice(
                screen, pygame.Rect(a.x, y + 18, a.width, 32), [f"{age} ans" for age in AGES], index
            )
        ]
        y += 62
        _section(shared, screen, "Métier", (a.x, y))
        keys = [job.key for job in JOBS]
        job_index = keys.index(draft.job) if draft.job in keys else 0
        picked = keys[
            form.choice(
                screen,
                pygame.Rect(a.x, y + 18, a.width, 32),
                [job.label for job in JOBS],
                job_index,
            )
        ]
        if picked != draft.job:
            draft.job, draft.job_title = picked, JOBS_BY_KEY[picked].label
        job = JOBS_BY_KEY[draft.job]
        draft.job_title = form.text(
            screen,
            pygame.Rect(a.x, y + 56, a.width, 32),
            f"job_title:{self.selected}",
            draft.job_title,
            placeholder=job.label,
            max_len=40,
        )
        hours = next(iter(job.schedule.values()), "") if job.schedule else "pas d'horaires"
        workplace = shared.config.place(job.place).name if job.place else "chez soi"
        label(
            screen,
            shared.texts,
            shared.texts.fit(f"{workplace} · {hours} · lever {job.wake}", 12, a.width),
            (a.x, y + 94),
            size=12,
            color=TEXT_2,
        )

        # --- Vie et caractère ---------------------------------------------------------
        y = b.y
        _section(shared, screen, "Logement", (b.x, y))
        homes = sc.homes(shared.config)
        others = {d.home: d.name for d in self.scenario.agents if d is not draft}
        home_ids = [h for h, _ in homes]
        options = [
            name + (f"  (déjà : {others[h].split()[0]})" if h in others else "")
            for h, name in homes
        ]
        home_index = home_ids.index(draft.home) if draft.home in home_ids else 0
        draft.home = home_ids[
            form.choice(screen, pygame.Rect(b.x, y + 18, b.width, 32), options, home_index)
        ]
        y += 70
        _section(shared, screen, "Caractère (Big Five)", (b.x, y))
        y += 22
        for trait, (name, low, high) in TRAIT_LABELS.items():
            label(screen, shared.texts, name, (b.x, y), size=13, weight=Weight.MEDIUM)
            value = draft.personality[trait]
            label(
                screen,
                shared.texts,
                f"{low} · {high}",
                (b.right, y + 1),
                size=11,
                color=MUTED,
                anchor="topright",
            )
            draft.personality[trait] = round(
                form.slider(
                    screen,
                    pygame.Rect(b.x + 6, y + 22, b.width - 12, 16),
                    f"{trait}:{self.selected}",
                    value,
                ),
                2,
            )
            y += 50
        y += 6
        _section(shared, screen, "Valeurs (séparées par des virgules)", (b.x, y))
        draft.values = form.text(
            screen,
            pygame.Rect(b.x, y + 18, b.width, 34),
            f"values:{self.selected}",
            draft.values,
            placeholder="la famille, la musique",
            max_len=120,
        )

        # --- Voix et IA ---------------------------------------------------------------
        y = c.y
        draft.speech_style = self._preset_text(
            screen, c, y, "Façon de parler", "style", SPEECH_STYLES, draft.speech_style
        )
        y += 108
        draft.ideology = self._preset_text(
            screen, c, y, "Idéologie, convictions", "ideology", IDEOLOGIES, draft.ideology
        )
        y += 108
        _section(shared, screen, "Modèle d'IA (Ollama)", (c.x, y))
        models = ["par défaut (.env)", *self.models]
        if draft.llm_model and draft.llm_model not in models:
            models.append(draft.llm_model)
        model_index = models.index(draft.llm_model) if draft.llm_model in models else 0
        model_pick = form.choice(screen, pygame.Rect(c.x, y + 18, c.width, 32), models, model_index)
        draft.llm_model = "" if model_pick == 0 else models[model_pick]
        hint = (
            f"{len(self.models)} modèles installés"
            if self.models
            else "Ollama non détecté : le modèle par défaut sera utilisé"
        )
        label(screen, shared.texts, hint, (c.x, y + 56), size=11, color=MUTED)
        y += 84
        _section(shared, screen, "Vie sentimentale", (c.x, y))
        if draft.age >= 18:
            draft.romance = form.toggle(
                screen, pygame.Rect(c.x, y + 18, c.width, 30), draft.romance, "ouvert(e) au flirt"
            )
        else:
            draft.romance = False
            label(
                screen,
                shared.texts,
                "Mineur : jamais de flirt.",
                (c.x, y + 24),
                size=13,
                color=TEXT_2,
            )

    def _preset_text(
        self,
        screen: pygame.Surface,
        col: pygame.Rect,
        y: int,
        title: str,
        key: str,
        presets: tuple[str, ...],
        value: str,
    ) -> str:
        """Un choix de préréglages, et en dessous le texte libre qu'on peut retoucher."""
        shared, form = self.shared, self.form
        _section(shared, screen, title, (col.x, y))
        options = ["(personnalisé)" if not p and value else (p or "aucune") for p in presets]
        current = presets.index(value) if value in presets else 0
        if value and value not in presets:
            options = ["(personnalisé)", *options]
            current = 0
            picked = form.choice(
                screen, pygame.Rect(col.x, y + 18, col.width, 32), options, current
            )
            if picked != 0:
                value = presets[picked - 1]
        else:
            picked = form.choice(
                screen, pygame.Rect(col.x, y + 18, col.width, 32), options, current
            )
            if picked != current:
                value = presets[picked]
        return form.text(
            screen,
            pygame.Rect(col.x, y + 58, col.width, 34),
            f"{key}:{self.selected}",
            value,
            placeholder="à écrire librement…",
            max_len=140,
        )

    # ------------------------------------------------------------------ #
    def _footer(self, screen: pygame.Surface, rect: pygame.Rect) -> StudioChoice | None:
        shared, form = self.shared, self.form
        _models, errors = sc.validate(self.scenario, shared.config)
        if errors:
            text, color = (
                errors[0] + (f"  (+{len(errors) - 1})" if len(errors) > 1 else ""),
                WARNING,
            )
        elif self.message is not None:
            text, color = self.message
        else:
            text, color = "Prêt : tout est cohérent.", SUCCESS
        label(
            screen,
            shared.texts,
            shared.texts.fit(text, 13, rect.width - 520),
            (rect.x, rect.centery),
            size=13,
            color=color,
            anchor="midleft",
        )
        choice = None
        bx = rect.right - 500
        if form.button(screen, pygame.Rect(bx, rect.y + 6, 110, 38), "Retour"):
            choice = StudioChoice("menu")
        if form.button(
            screen, pygame.Rect(bx + 120, rect.y + 6, 150, 38), "Enregistrer", enabled=not errors
        ):
            path = sc.save(self.scenario)
            self.message = (f"Enregistré : {path}", ACCENT)
        if form.button(
            screen,
            pygame.Rect(bx + 280, rect.y + 6, 220, 38),
            "Enregistrer et jouer",
            primary=True,
            enabled=not errors,
        ):
            sc.save(self.scenario)
            choice = StudioChoice("play", self.scenario)
        return choice
