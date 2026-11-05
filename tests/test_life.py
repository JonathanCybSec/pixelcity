"""Étape 6 bis : la vraie vie (décisions, dettes, expulsion, travail, vol, manche)."""

from __future__ import annotations

from collections.abc import Callable

from pixelcity.config.loader import GameConfig
from pixelcity.llm.prompts import intention_schema, parse_intentions
from pixelcity.llm.types import IntentionRequest, Intentions, Option, Persona
from pixelcity.sim.events import EventKind
from pixelcity.sim.simulation import Simulation
from pixelcity.sim.types import NeedKind
from pixelcity.studio import scenario as sc

from .helpers import events_of, run_to

MONDAY = 0


def _persona() -> Persona:
    return Persona(
        "noah", "Noah N", 23, "Étudiant", "réservé", (), "", "", "flâne", "fauché", None, None
    )


def test_le_programme_de_l_ia_est_filtre() -> None:
    req = IntentionRequest(
        _persona(),
        (),
        "mardi",
        "Bureaux, 09:00-17:30",
        (Option("phone", "téléphone (420 €)"),),
        (Option("casino", "casino"), Option("park", "parc"), Option("work", "travail")),
    )
    schema = intention_schema(req)
    assert schema["properties"]["plan"]["items"]["properties"]["activite"]["enum"] == [
        "casino",
        "park",
        "work",
        "phone",
    ]
    got = parse_intentions(
        req,
        {
            "pour_contre": [
                {"choix": "Sécher le boulot", "pour": "Le casino !", "contre": "Pas payé"}
            ],
            "plan": [
                {"heure": "15:00", "activite": "casino"},
                {"heure": "10h", "activite": "phone"},
                {"heure": "11:00", "activite": "braquer_la_banque"},
            ],
            "budget_casino": 80,
            "pensee": "Aujourd'hui, je tente ma chance.",
        },
        "test",
    )
    assert got.schedule == ((600, "phone"), (900, "casino"))
    assert got.work is False and got.purchases == ("phone",) and got.casino_budget == 80
    assert got.pros_cons[0].choice == "Sécher le boulot"


def test_la_journee_suit_le_programme_de_l_ia(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    run_to(sim, MONDAY, 21.1)  # après la décision du soir (ici : les règles de secours)
    # Mardi : son « IA » ne prévoit pas le travail, mais du shopping et le casino.
    lea.intentions[1] = Intentions(
        work=False,
        schedule=((10 * 60 + 30, "clothes"), (15 * 60, "casino")),
        thought="Je prends ma journée.",
        source="test",
        casino_budget=60,
    )
    run_to(sim, MONDAY + 1, 0.2)
    labels = [block.label for block in lea.plan.blocks] if lea.plan else []
    assert "travail" not in labels
    assert "casino" in labels and any("vêtements" in label for label in labels)
    run_to(sim, MONDAY + 1, 18.0)
    assert "clothes" in lea.possessions
    assert events_of(sim, EventKind.GAMBLED, "lea")


def test_gagner_au_casino_donne_envie_d_y_retourner(make_sim: Callable[..., Simulation]) -> None:
    from pixelcity.sim.life import _Session

    sim = make_sim()
    paul = sim.agents["paul"]
    sim.life._sessions["paul"] = _Session(budget=50, net=300, rounds=5)
    sim.life._end_session(sim.ctx, paul)
    after_win = paul.cravings["casino"]
    assert after_win > 0.3
    sim.life._sessions["paul"] = _Session(budget=50, net=-80, rounds=8, chased=True)
    sim.life._end_session(sim.ctx, paul)
    assert paul.cravings["casino"] > after_win  # « il faut que je me refasse »
    assert any("refaire" in m.text for m in paul.memory.memories)


def _broke_scenario(config: GameConfig, money: float = -200.0) -> Simulation:
    scenario = sc.default_scenario(config)
    scenario.agents.append(
        sc.AgentDraft(name="Noah Nguyen", age=23, job="sans_emploi", home="mimosas_2", money=money)
    )
    return Simulation(sc.apply(scenario, config))


def test_trois_nuits_de_dette_et_c_est_l_expulsion(config: GameConfig) -> None:
    sim = _broke_scenario(config)
    noah = sim.agents["noah_nguyen"]
    run_to(sim, MONDAY + 3, 9.0)  # trois nuits à découvert, l'huissier passe à 08:00
    assert events_of(sim, EventKind.EVICTED, "noah_nguyen")
    assert noah.homeless and noah.home == "parc"
    assert any("expulsé" in m.text for m in noah.memory.memories)
    run_to(sim, MONDAY + 4, 3.0)
    assert noah.plan is not None and noah.plan.blocks[0].recipe == "sleep_rough"
    assert noah.place_id == "parc"


def test_trois_absences_et_c_est_le_licenciement(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    lea = sim.agents["lea"]
    lea.intentions[0] = Intentions(work=False, thought="Pas envie.")
    rules = sim.life.rule_intentions
    # Les soirs suivants, son « IA » (ici les règles, forcées) refuse encore d'y aller.
    sim.life.rule_intentions = lambda ctx, agent: (  # type: ignore[method-assign]
        Intentions(work=False, thought="Pas envie.") if agent is lea else rules(ctx, agent)
    )
    run_to(sim, MONDAY + 3, 0.5)
    assert events_of(sim, EventKind.FIRED, "lea")
    assert lea.profile.work is None and lea.profile.wage == 0
    assert lea.profile.allowance > 0  # le chômage


def test_chercher_un_emploi_peut_aboutir(config: GameConfig) -> None:
    sim = _broke_scenario(config, money=50)
    noah = sim.agents["noah_nguyen"]
    for _ in range(30):
        sim.life._job_search(sim.ctx, noah)
        if noah.profile.work is not None:
            break
    assert noah.profile.work is not None and noah.profile.wage > 0
    assert events_of(sim, EventKind.HIRED, "noah_nguyen")


def test_voler_sous_les_yeux_du_personnel(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    run_to(sim, MONDAY, 11.0)  # Sofia tient la caisse du supermarché
    thief = sim.agents["hugo"]
    sofia = sim.agents["sofia"]
    assert sofia.place_id == "supermarche"
    thief.place_id = "supermarche"
    for _ in range(20):
        sim.life._steal(sim.ctx, thief, "supermarche", "snack")
        if "supermarche" in thief.banned:
            break
    assert "supermarche" in thief.banned
    assert any("voler" in m.text for m in sofia.memory.memories)
    relation = sim.relations.get("hugo", "sofia")
    assert relation is not None and relation.affinity < 0
    thefts = events_of(sim, EventKind.THEFT, "hugo")
    assert thefts[-1].data["caught"] is True


def test_faim_sans_le_sou_l_habitant_decide(config: GameConfig) -> None:
    sim = _broke_scenario(config, money=0)
    noah = sim.agents["noah_nguyen"]
    run_to(sim, MONDAY, 10.0)
    noah.needs.values[NeedKind.HUNGER] = 5.0
    noah.money = 0.0
    fridge = sim.world.places["mimosas_2"].container_with("provisions")
    assert fridge is not None
    fridge.take("provisions", fridge.count("provisions"))
    sim.run_ticks(sim.clock.ticks_per_minute * 20)
    assert events_of(sim, EventKind.DECISION, "noah_nguyen")
    assert any(t.recipe_id in ("beg", "steal_food", "rest_hungry") for t in noah.tasks)


def test_l_argent_vient_de_quelqu_un(make_sim: Callable[..., Simulation]) -> None:
    sim = make_sim()
    sim.run_days(2)
    flows = sim.economy.flows
    assert flows[("Bureaux Horizon", "habitants")] > 0  # le salaire de Léa
    assert flows[("habitants", "le bailleur")] > 0  # les loyers
    assert flows[("l'État", "habitants")] > 0  # la retraite de Paul
    assert flows[("la clientèle extérieure", "Boulangerie du Coin")] > 0
    assert sim.economy.accounts["boulangerie"] > 0


# --------------------------------------------------------------------------- #
# Avec une « IA » : un faux serveur Ollama qui compose des journées
# --------------------------------------------------------------------------- #
def test_avec_l_ia_chaque_habitant_compose_sa_journee(config: GameConfig) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from typing import Any

    from pixelcity.llm.backends import OllamaBackend, ScriptedBackend
    from pixelcity.llm.settings import LlmSettings

    class FakeMind(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._send({"models": [{"name": "fake:latest"}]})

        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            schema = request["format"]["properties"]
            if "plan" in schema:  # une journée : la flemme, puis le casino
                reply: dict[str, Any] = {
                    "pour_contre": [
                        {
                            "choix": "Aller au casino",
                            "pour": "Je peux gagner gros",
                            "contre": "Je peux tout perdre",
                        }
                    ],
                    "plan": [
                        {"heure": "10:00", "activite": "park"},
                        {"heure": "15:00", "activite": "casino"},
                    ],
                    "budget_casino": 40,
                    "pensee": "Demain, je me fais plaisir.",
                }
            elif "choice" in schema:
                reply = {"choice": schema["choice"]["enum"][0], "thought": "Bon."}
            elif "insights" in schema:
                reply = {"insights": ["Je crois que j'aime le risque."]}
            else:
                prompt = request["messages"][1]["content"]
                ids = [part.split("»")[0] for part in prompt.split("(id « ")[1:]]
                reply = {
                    "lines": [
                        {"speaker": ids[0], "text": "Salut !"},
                        {"speaker": ids[1], "text": "Salut, ça va ?"},
                    ],
                    "affinity_delta": 1,
                    "flirt": False,
                    "summary": "Bonjour.",
                }
            content = json.dumps(reply)
            self._send({"message": {"role": "assistant", "content": content}})

    server = HTTPServer(("127.0.0.1", 0), FakeMind)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        host = f"http://127.0.0.1:{server.server_address[1]}"
        backend = OllamaBackend(
            LlmSettings(host=host, model="fake", timeout_s=5),
            ScriptedBackend(config.dialogues),
            blocking=True,
        )
        sim = Simulation(config, dialogue=backend)
        run_to(sim, MONDAY + 1, 16.0)
    finally:
        server.shutdown()
        sim.close()
    lea = sim.agents["lea"]
    tuesday = lea.intentions[1]
    assert tuesday.source == "fake" and tuesday.work is False  # la flemme : pas de travail
    assert lea.deliberation[0].pros == "Je peux gagner gros"
    labels = [b.label for b in lea.plan.blocks] if lea.plan else []
    assert "casino" in labels and "travail" not in labels
    assert events_of(sim, EventKind.INTENTION, "lea")[0].data["source"] == "fake"
