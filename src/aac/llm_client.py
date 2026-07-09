"""LLM backend adapters for strong-locus Stage 3.

Provides Anthropic and OpenAI chat-completion backends using only stdlib
(urllib.request + ssl). Reads API keys from environment variables and falls
back to the deterministic stub from `aac.organ_tools` when no key is present.
Responses are cached on disk so re-runs are cheap.

All backends implement:

    call(prompt: str, tools: list[dict] | None) -> Mapping[str, Any]

Expected return shapes:
- Tool turn:  {"tool_call": {"name": ..., "arguments": ...}}
- Final turn: {"final_answer": {"edges": [[i, j, confidence], ...]}}

PlumbingInstrument integration logs `truncated`, `timeout`, and `unparseable`
events without ever pooling them with reasoning scores.

Pure stdlib. No new pip dependencies.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

try:
    from .organ_tools import DeterministicStubBackend
    from .plumbing_instrument import PlumbingInstrument
except ImportError:
    from organ_tools import DeterministicStubBackend
    from plumbing_instrument import PlumbingInstrument


DEFAULT_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


def _api_url(provider: str) -> str:
    """Return the API endpoint URL, allowing env-var override for proxy/compatibility layers."""
    env_var = f"{provider.upper()}_API_URL"
    return os.environ.get(env_var, DEFAULT_ANTHROPIC_API_URL if provider == "anthropic" else DEFAULT_OPENAI_API_URL)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_file_path(
    prompt: str,
    tools: list[dict] | None,
    provider: str,
    cache_dir: str = ".cache/llm_calls",
) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    key = json.dumps(
        {"prompt": prompt, "tools": tools, "provider": provider},
        sort_keys=True,
        separators=(",", ":"),
    )
    return os.path.join(cache_dir, f"{_sha256(key)}.json")


def _load_cache(path: str) -> Mapping[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, Mapping) and "response" in data:
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _save_cache(path: str, response: Mapping[str, Any], raw: Mapping[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"response": dict(response), "raw": dict(raw)}, fh, indent=2, sort_keys=True)


def _http_post(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
) -> bytes:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _has_event(instrument: PlumbingInstrument | None, kind: str) -> bool:
    if instrument is None:
        return False
    return any(event.kind == kind for event in instrument.events)


@dataclass
class AnthropicBackend:
    """Stdlib Anthropic Messages API backend with response caching."""

    api_key: str
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"))
    temperature: float = field(default_factory=lambda: float(os.environ.get("ANTHROPIC_TEMPERATURE", "0.0")))
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 2
    instrument: PlumbingInstrument | None = None
    cache_dir: str = ".cache/llm_calls"
    provider: str = "anthropic"
    stub_only: bool = False

    def call(
        self, prompt: str, tools: list[dict] | None = None
    ) -> Mapping[str, Any]:
        cache_path = _cache_file_path(prompt, tools, self.provider, self.cache_dir)
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached["response"]

        system = (
            "You are a causal discovery assistant. "
            "Return only the requested JSON structure with no markdown or commentary."
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = [_anthropic_tool_schema(t) for t in tools]
            payload["tool_choice"] = {"type": "any"}

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        raw_bytes: bytes | None = None
        url = _api_url("anthropic")
        for attempt in range(self.max_retries + 1):
            try:
                raw_bytes = _http_post(url, headers, body, self.timeout)
                break
            except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
                if self.instrument is not None:
                    self.instrument.log_timeout(
                        "anthropic_http",
                        f"attempt {attempt}: {exc}",
                        {"attempt": attempt, "url": url},
                    )
                if attempt == self.max_retries:
                    return {"_plumbing_failure": "timeout"}
                time.sleep(1.0 * (attempt + 1))

        assert raw_bytes is not None
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if self.instrument is not None and not _has_event(self.instrument, "unparseable"):
                self.instrument.log_unparseable(
                    "anthropic_json",
                    str(exc),
                    {
                        "raw_prefix": raw_bytes[:200].decode("utf-8", errors="replace"),
                    },
                )
            return {"_plumbing_failure": "unparseable"}

        response = self._extract_response(data, tools)
        _save_cache(cache_path, response, data)
        return response

    def _extract_response(
        self, data: Mapping[str, Any], tools: list[dict] | None
    ) -> Mapping[str, Any]:
        if not isinstance(data, Mapping):
            if self.instrument is not None:
                self.instrument.log_unparseable("anthropic_extract", "response is not a JSON object")
            return {"_plumbing_failure": "unparseable"}

        if data.get("error"):
            msg = data["error"].get("message", "api error") if isinstance(data["error"], Mapping) else str(data["error"])
            if self.instrument is not None:
                self.instrument.log_unparseable("anthropic_api_error", msg)
            return {"_plumbing_failure": "unparseable"}

        stop_reason = data.get("stop_reason")
        content = data.get("content", [])
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text"
        ]
        text = "\n".join(text_blocks)

        if stop_reason == "max_tokens":
            if self.instrument is not None:
                self.instrument.log_truncated(
                    "anthropic_extract",
                    "stop_reason=max_tokens",
                    {"text_length": len(text), "max_tokens": self.max_tokens},
                )
        elif len(text) >= self.max_tokens * 0.95:
            if self.instrument is not None:
                self.instrument.log_truncated(
                    "anthropic_extract",
                    "response length near max_tokens",
                    {"text_length": len(text), "max_tokens": self.max_tokens},
                )

        if tools:
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "tool_use":
                    return {
                        "tool_call": {
                            "name": block.get("name"),
                            "arguments": block.get("input", {}),
                        }
                    }

        parsed = _parse_json_text(text)
        if parsed is None:
            if self.instrument is not None and not _has_event(self.instrument, "unparseable"):
                self.instrument.log_unparseable(
                    "anthropic_extract",
                    "could not parse JSON from text block",
                    {"text_prefix": text[:200]},
                )
            return {"_plumbing_failure": "unparseable"}
        return parsed


@dataclass
class OpenAIBackend:
    """Stdlib OpenAI chat-completion backend with response caching."""

    api_key: str
    model: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o-2024-08-06"))
    temperature: float = field(default_factory=lambda: float(os.environ.get("OPENAI_TEMPERATURE", "0.0")))
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 2
    instrument: PlumbingInstrument | None = None
    cache_dir: str = ".cache/llm_calls"
    provider: str = "openai"
    stub_only: bool = False

    def call(
        self, prompt: str, tools: list[dict] | None = None
    ) -> Mapping[str, Any]:
        cache_path = _cache_file_path(prompt, tools, self.provider, self.cache_dir)
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached["response"]

        system = (
            "You are a causal discovery assistant. "
            "Return only the requested JSON structure with no markdown or commentary."
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if tools:
            payload["tools"] = [_openai_tool_schema(t) for t in tools]
            payload["tool_choice"] = "required"

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

        raw_bytes: bytes | None = None
        url = _api_url("openai")
        for attempt in range(self.max_retries + 1):
            try:
                raw_bytes = _http_post(url, headers, body, self.timeout)
                break
            except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
                if self.instrument is not None:
                    self.instrument.log_timeout(
                        "openai_http",
                        f"attempt {attempt}: {exc}",
                        {"attempt": attempt, "url": url},
                    )
                if attempt == self.max_retries:
                    return {"_plumbing_failure": "timeout"}
                time.sleep(1.0 * (attempt + 1))

        assert raw_bytes is not None
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if self.instrument is not None and not _has_event(self.instrument, "unparseable"):
                self.instrument.log_unparseable(
                    "openai_json",
                    str(exc),
                    {
                        "raw_prefix": raw_bytes[:200].decode("utf-8", errors="replace"),
                    },
                )
            return {"_plumbing_failure": "unparseable"}

        response = self._extract_response(data, tools)
        _save_cache(cache_path, response, data)
        return response

    def _extract_response(
        self, data: Mapping[str, Any], tools: list[dict] | None
    ) -> Mapping[str, Any]:
        if not isinstance(data, Mapping):
            if self.instrument is not None:
                self.instrument.log_unparseable("openai_extract", "response is not a JSON object")
            return {"_plumbing_failure": "unparseable"}

        if data.get("error"):
            msg = data["error"].get("message", "api error") if isinstance(data["error"], Mapping) else str(data["error"])
            if self.instrument is not None:
                self.instrument.log_unparseable("openai_api_error", msg)
            return {"_plumbing_failure": "unparseable"}

        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            if self.instrument is not None:
                self.instrument.log_unparseable("openai_extract", "no choices in response")
            return {"_plumbing_failure": "unparseable"}

        message = choices[0].get("message", {}) if isinstance(choices[0], Mapping) else {}
        finish_reason = choices[0].get("finish_reason")
        text = message.get("content", "") or ""

        if finish_reason == "length":
            if self.instrument is not None:
                self.instrument.log_truncated(
                    "openai_extract",
                    "finish_reason=length",
                    {"text_length": len(text), "max_tokens": self.max_tokens},
                )
        elif len(text) >= self.max_tokens * 0.95:
            if self.instrument is not None:
                self.instrument.log_truncated(
                    "openai_extract",
                    "response length near max_tokens",
                    {"text_length": len(text), "max_tokens": self.max_tokens},
                )

        if tools:
            tool_calls = message.get("tool_calls", [])
            if isinstance(tool_calls, list) and tool_calls:
                tc = tool_calls[0]
                if isinstance(tc, Mapping):
                    arguments = tc.get("function", {}).get("arguments", "{}")
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                    return {
                        "tool_call": {
                            "name": tc.get("function", {}).get("name"),
                            "arguments": arguments,
                        }
                    }

        parsed = _parse_json_text(text)
        if parsed is None:
            if self.instrument is not None and not _has_event(self.instrument, "unparseable"):
                self.instrument.log_unparseable(
                    "openai_extract",
                    "could not parse JSON from content",
                    {"text_prefix": text[:200]},
                )
            return {"_plumbing_failure": "unparseable"}
        return parsed


@dataclass
class StubFallbackBackend(DeterministicStubBackend):
    """Deterministic stub with Stage 3 plumbing/metadata support."""

    stub_only: bool = True
    instrument: PlumbingInstrument | None = None


def _anthropic_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Adapt a generic tool schema to Anthropic's tool format."""
    return {
        "name": tool.get("name", "tool"),
        "description": tool.get("description", ""),
        "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
    }


def _openai_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Adapt a generic tool schema to OpenAI's tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", "tool"),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }


def _parse_json_text(text: str) -> Mapping[str, Any] | None:
    """Extract JSON from a text block, stripping markdown fences if needed."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, Mapping) else None
    except json.JSONDecodeError:
        return None


def build_backend(
    provider: str = "anthropic",
    instrument: PlumbingInstrument | None = None,
    cache_dir: str = ".cache/llm_calls",
) -> AnthropicBackend | OpenAIBackend | StubFallbackBackend:
    """Return a real backend if an API key is available, otherwise a stub.

    The returned object always has a `stub_only` attribute: True for the stub,
    False for real backends.
    """
    if provider == "stub":
        return StubFallbackBackend(seed=0, instrument=instrument, stub_only=True)

    env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = os.environ.get(env_var)
    if not key:
        return StubFallbackBackend(seed=0, instrument=instrument, stub_only=True)

    if provider == "anthropic":
        return AnthropicBackend(
            api_key=key,
            instrument=instrument,
            cache_dir=cache_dir,
            stub_only=False,
        )
    if provider == "openai":
        return OpenAIBackend(
            api_key=key,
            instrument=instrument,
            cache_dir=cache_dir,
            stub_only=False,
        )
    raise ValueError(f"Unknown backend provider: {provider}")
