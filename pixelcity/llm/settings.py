"""Réglages du LLM, lus dans un fichier `.env` (jamais dans le code, jamais dans Git).

On cherche le `.env`, dans l'ordre :
1. le dossier courant (pratique en développement : la racine du dépôt) ;
2. le dossier de l'exécutable (à côté de `PixelCity.exe`) ;
3. `%APPDATA%/PixelCity/.env` sous Windows, `~/.config/pixelcity/.env` ailleurs.
Les variables d'environnement déjà définies l'emportent sur le fichier.

Pourquoi pas python-dotenv ? Le format est trivial (CLE=valeur) : une
dépendance de moins à empaqueter dans le .exe.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"


@dataclass(frozen=True, slots=True)
class LlmSettings:
    enabled: bool = True
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    timeout_s: float = 30.0
    source: str = "défauts"


def env_candidates() -> list[Path]:
    paths = [Path.cwd() / ".env"]
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / ".env")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "PixelCity" / ".env")
    else:
        paths.append(Path.home() / ".config" / "pixelcity" / ".env")
    return paths


def parse_env(text: str) -> dict[str, str]:
    """Lit `CLE=valeur` ligne par ligne ; ignore les commentaires et les guillemets."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.split(" #", 1)[0].strip().strip("\"'")
        values[key] = value
    return values


def load_llm_settings(
    environ: Mapping[str, str] | None = None, candidates: list[Path] | None = None
) -> LlmSettings:
    file_values: dict[str, str] = {}
    source = "défauts"
    for path in candidates if candidates is not None else env_candidates():
        if path.is_file():
            file_values = parse_env(path.read_text(encoding="utf-8"))
            source = str(path)
            break
    env = dict(file_values)
    env.update(environ if environ is not None else os.environ)

    mode = env.get("PIXELCITY_LLM", "ollama").strip().lower()
    try:
        timeout = float(env.get("OLLAMA_TIMEOUT", "30"))
    except ValueError:
        timeout = 30.0
    return LlmSettings(
        enabled=mode not in {"off", "none", "script", "0", "false"},
        host=env.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/") or DEFAULT_HOST,
        model=env.get("OLLAMA_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        timeout_s=max(2.0, timeout),
        source=source,
    )
