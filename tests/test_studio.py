"""Étape 4 : le studio (scénarios, préréglages, validation) et ses écrans."""

from __future__ import annotations

import random
from collections.abc import Iterator
from pathlib import Path

import pygame
import pytest

from pixelcity.config.loader import ConfigError, GameConfig
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.studio import scenario as sc
from pixelcity.studio.presets import JOBS, slugify


def test_slugify() -> None:
    assert slugify("Léa Martin") == "lea_martin"
    assert slugify("  2 Chats ! ") == "h_2_chats"


def test_les_habitants_d_origine_sont_valides(config: GameConfig) -> None:
    scenario = sc.default_scenario(config)
    models, errors = sc.validate(scenario, config)
    assert errors == []
    assert [m.id for m in models] == [
        "marcel_dupont",
        "lea_martin",
        "karim_benali",
        "sofia_rossi",
        "hugo_lambert",
        "paul_girard",
        "zoe_moreau",
        "theo_leroy",
    ]
    sofia = next(m for m in models if m.name == "Sofia Rossi")
    assert sofia.job == "Caissière"  # l'intitulé personnalisé est conservé
    assert sofia.speech_style and sofia.romance


def test_les_erreurs_sont_lisibles(config: GameConfig) -> None:
    scenario = sc.default_scenario(config)
    scenario.agents[1].home = scenario.agents[0].home
    scenario.agents[2].name = "  "
    _models, errors = sc.validate(scenario, config)
    assert any("un seul lit" in e for e in errors)
    assert any("pas de nom" in e for e in errors)


def test_pas_de_flirt_pour_un_mineur(config: GameConfig) -> None:
    draft = sc.AgentDraft(name="Tom Petit", age=16, job="etudiant", home="appart_1", romance=True)
    assert draft.to_model("tom").romance is False


def test_enregistrer_puis_relire(config: GameConfig, tmp_path: Path) -> None:
    scenario = sc.default_scenario(config)
    scenario.name = "Quartier d'été"
    scenario.agents[0].ideology = "écologiste convaincu"
    path = sc.save(scenario, tmp_path)
    assert path.name == "quartier_d_ete.yaml"
    again = sc.load(path)
    assert again.name == "Quartier d'été"
    assert again.agents == scenario.agents
    assert [s.name for s in sc.list_scenarios(tmp_path)] == ["Quartier d'été"]
    assert sc.find("Quartier d'été", tmp_path).path == path
    (tmp_path / "abime.yaml").write_text("pas: [un scénario", encoding="utf-8")
    assert len(sc.list_scenarios(tmp_path)) == 1  # un fichier abîmé est ignoré


def test_un_scenario_invalide_est_refuse(config: GameConfig) -> None:
    with pytest.raises(ConfigError):
        sc.apply(sc.Scenario("vide", []), config)


@pytest.mark.parametrize("seed", [0, 1])
def test_une_ville_tiree_au_hasard_vit_une_semaine(config: GameConfig, seed: int) -> None:
    """Chaque métier, sept habitants : personne ne s'effondre, rien ne tourne en boucle."""
    rng = random.Random(seed)
    scenario = sc.Scenario("hasard", [])
    for index in range(7):
        draft = sc.random_draft(scenario, config, rng)
        draft.job = JOBS[(index + 7 * seed) % len(JOBS)].key
        scenario.agents.append(draft)
    sim = Simulation(sc.apply(scenario, config))
    sim.run_days(7)
    failures = [e for e in sim.events if e.kind is EventKind.TASK_FAILED]
    assert len(failures) < 60, failures[:5]
    for agent in sim.agents.values():
        assert min(agent.needs.values.values()) > 5, (agent.id, agent.needs.snapshot())


def test_un_commerce_sans_employe_reste_ferme(config: GameConfig) -> None:
    scenario = sc.Scenario(
        "sans boulanger",
        [
            sc.AgentDraft(name="Ana Roux", job="retraite", home="appart_1"),
            sc.AgentDraft(name="Max Roux", job="caissier", home="appart_2"),
        ],
    )
    sim = Simulation(sc.apply(scenario, config))
    assert "boulangerie" in sim.closed_for_lack_of_staff
    assert "supermarche" not in sim.closed_for_lack_of_staff
    assert not sim.world.places["boulangerie"].hours.is_open(0, 10 * 60)


# --------------------------------------------------------------------------- #
# Écrans (pilote vidéo factice)
# --------------------------------------------------------------------------- #
@pytest.fixture
def display(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pygame.Surface]:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PIXELCITY_DATA", str(tmp_path))
    pygame.display.init()
    pygame.font.init()
    yield pygame.display.set_mode((1280, 720))
    pygame.quit()


def _click(pos: tuple[int, int]) -> list[pygame.event.Event]:
    return [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)]


def test_saisie_de_texte(display: pygame.Surface) -> None:
    from pixelcity.ui.forms import Form
    from pixelcity.ui.theme import Fonts, TextCache

    form = Form(TextCache(Fonts()))
    field = pygame.Rect(10, 10, 200, 30)
    value = "Lea"
    for events in (
        _click(field.center),
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0)],
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0)],
        [pygame.event.Event(pygame.TEXTINPUT, text="éa")],
    ):
        form.begin(events)
        value = form.text(display, field, "nom", value)
        form.end()
    assert value == "Léa"
    form.begin(_click((600, 600)))  # clic ailleurs : fin de la saisie
    form.text(display, field, "nom", value)
    form.end()
    assert form.focus is None


def test_le_studio_cree_un_habitant_au_hasard(config: GameConfig, display: pygame.Surface) -> None:
    from pixelcity.engine.screens import Backdrop, Shared, StudioScreen
    from pixelcity.llm.settings import LlmSettings

    shared = Shared(config, LlmSettings(enabled=False))
    shared.backdrop = Backdrop(config)
    studio = StudioScreen(shared, None)
    studio.frame(display, [], 0.016)
    before = len(studio.scenario.agents)
    studio.frame(display, _click((220, 629)), 0.016)  # bouton « Au hasard »
    assert len(studio.scenario.agents) == before + 1
    assert studio.selected == before
    choice = studio.frame(
        display, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)], 0.016
    )
    assert choice is not None and choice.action == "menu"


def test_le_lanceur_s_ouvre_et_se_ferme(config: GameConfig, display: pygame.Surface) -> None:
    from pixelcity.engine.launcher import run_launcher
    from pixelcity.llm.settings import LlmSettings

    run_launcher(config, LlmSettings(enabled=False), max_frames=3)
