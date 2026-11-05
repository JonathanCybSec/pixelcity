"""Un client HTTP minimal pour Ollama (bibliothèque standard uniquement).

Ollama expose une API REST locale : POST /api/chat avec la liste des
messages. Le champ `format` accepte un schéma JSON : le modèle est alors
CONTRAINT à répondre avec un JSON valide de cette forme (décodage guidé),
ce qui évite de « parser » du texte libre au petit bonheur.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class LlmError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str, timeout_s: float) -> None:
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    def _post(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LlmError(f"Ollama injoignable sur {self.host} : {exc}") from exc
        if not isinstance(data, dict):
            raise LlmError("réponse d'Ollama inattendue")
        return data

    def models(self, timeout: float = 2.0) -> list[str]:
        """Les modèles installés (`ollama list`). Lève LlmError si Ollama ne répond pas."""
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LlmError(f"Ollama injoignable sur {self.host} : {exc}") from exc
        return [str(m.get("name", "")) for m in data.get("models", []) if isinstance(m, dict)]

    def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.8,
        seed: int | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature, "num_predict": 400}
        if seed is not None:
            options["seed"] = seed
        data = self._post(
            "/api/chat",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": schema,
                "stream": False,
                "options": options,
                "keep_alive": "30m",  # garde le modèle en mémoire vidéo entre deux répliques
            },
            self.timeout_s,
        )
        if "error" in data:
            raise LlmError(str(data["error"]))
        content = data.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise LlmError(f"JSON invalide renvoyé par {model}") from exc
        if not isinstance(parsed, dict):
            raise LlmError("le modèle n'a pas renvoyé un objet JSON")
        return parsed
