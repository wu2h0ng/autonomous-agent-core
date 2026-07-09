"""Real LLM Orientation Organ — HTTP API call for causal direction proposals.

Supports OpenAI-compatible APIs (Kimi, DeepSeek, Ollama, etc).
For Sachs: sends protein names + undirected edges → LLM returns causal directions
based on biology knowledge → intervention verifier confirms/falsifies.

Usage:
    from aac.llm_organ import LLMAPIBackend
    backend = LLMAPIBackend(
        api_url="https://api.moonshot.cn/v1/chat/completions",
        api_key="sk-kimi-...",
    )
    organ = LanguageOrientationOrgan(backend, protein_names)
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Mapping

from .prior_organ_llm import LLMBackend


class LLMAPIBackend:
    """Real LLM backend via HTTP API (OpenAI-compatible endpoint)."""

    def __init__(self, api_url: str = "https://api.kimi.com/coding/v1/chat/completions",
                 api_key: str = "", model: str = "kimi-k2.6",
                 temperature: float | None = None, timeout: int = 60):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def propose(self, prompt: str) -> Mapping[str, Any]:
        payload_dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": (
                    "You are a causal discovery assistant in molecular biology. "
                    "Given protein names and undirected edges from the Sachs protein "
                    "signaling network, propose causal directions based on known biology. "
                    "Return ONLY a valid JSON object with an 'orientations' array. "
                    "Each element: {\"i\": int, \"j\": int, \"direction\": \"i→j\", \"score\": 0.0-1.0}. "
                    "Direction format: e.g. \"0→1\" means node i=0 causes node j=1."
                )},
                {"role": "user", "content": prompt},
            ],
        }
        if self.temperature is not None:
            payload_dict["temperature"] = self.temperature
        payload = json.dumps(payload_dict).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = urllib.request.Request(self.api_url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_json = json.loads(resp.read().decode())
                content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                return json.loads(content)
        except json.JSONDecodeError:
            return {}
        except Exception as e:
            return {"error": str(e)}

