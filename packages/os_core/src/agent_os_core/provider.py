from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderErrorCode,
    ProviderFailure,
    ProviderDecisionRequest,
    ProviderInvocationBinding,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
    content_digest,
)


_WORKSPACE_TOOL_PARAMETERS: dict[str, dict[str, object]] = {
    "workspace.read": {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"],
        "additionalProperties": False,
    },
    "workspace.search": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["ls", "glob", "grep"]},
            "path": {"type": "string"},
            "pattern": {"type": "string"},
        },
        "required": ["mode"],
        "additionalProperties": False,
    },
    "workspace.edit": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "old_string": {"type": "string", "minLength": 1},
            "new_string": {"type": "string"},
            "expected_sha256": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    },
    "workspace.apply_patch": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "content": {"type": "string"},
            "expected_sha256": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    "workspace.run_tests": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["pytest", "python -m pytest", "python3 -m pytest"],
            },
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    "workspace.shell": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "minLength": 1},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    "session.todo_write": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "content": {"type": "string", "minLength": 1},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "done"],
                        },
                    },
                    "required": ["id", "content", "status"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["todos"],
        "additionalProperties": False,
    },
}


class CredentialUnavailable(PermissionError):
    pass


def _optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _optional_float_env(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_pricing_table() -> dict[str, dict[str, object]]:
    """Load an optional local pricing table for cost honesty (E3).

    Source: ``AGENT_OS_PRICING_FILE`` or ``~/.agent-os/pricing.json`` with shape
    ``{"models": {"<model_id>": {"input_per_1k_usd": <num>,
    "output_per_1k_usd": <num>, "source": "<ref>"}}}``. Models without a complete
    entry are simply absent, so cost stays UNKNOWN — never a pseudo-zero.
    """

    override = os.environ.get("AGENT_OS_PRICING_FILE")
    path = Path(override) if override else Path.home() / ".agent-os" / "pricing.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, dict):
        return {}
    table: dict[str, dict[str, object]] = {}
    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        input_rate = entry.get("input_per_1k_usd")
        output_rate = entry.get("output_per_1k_usd")
        if not isinstance(source, str) or not source:
            continue
        try:
            input_value = float(input_rate)  # type: ignore[arg-type]
            output_value = float(output_rate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(input_value)
            or not math.isfinite(output_value)
            or input_value < 0
            or output_value < 0
        ):
            continue
        table[str(model_id)] = {
            "input": input_value,
            "output": output_value,
            "source": source,
        }
    return table


class EnvCredentialBroker:
    """Local/CI resolver. It returns secret bytes only to an adapter call."""

    def resolve(self, ref: CredentialRef) -> str:
        if ref.status is not CredentialStatus.ACTIVE:
            raise CredentialUnavailable("credential is revoked")
        if datetime.now(timezone.utc) >= ref.expires_at:
            raise CredentialUnavailable("credential is expired")
        if "chat" not in ref.scopes:
            raise CredentialUnavailable("credential lacks chat scope")
        value = os.environ.get(ref.resolver_key)
        if not value:
            raise CredentialUnavailable("credential is unavailable")
        return value


class ProviderPort(ABC):
    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        raise RuntimeError("provider invocation binding is unavailable")

    @abstractmethod
    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        raise NotImplementedError

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        """Default: non-streaming complete; subclasses may stream deltas.

        `on_reasoning_delta` (if a provider exposes transient reasoning) is
        display-only and must never be merged into `ProviderResponse.text`.
        """
        result = self.complete(request)
        if (
            on_text_delta is not None
            and isinstance(result, ProviderResponse)
            and result.text
        ):
            on_text_delta(result.text)
        return result

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        raise NotImplementedError


class DeterministicProvider(ProviderPort):
    """Hermetic provider used by CI; it follows the same typed port as live calls."""

    def __init__(
        self,
        text: str = "provider-ok",
        tool_proposals: tuple[ProviderToolProposal, ...] = (),
        invocation_binding: ProviderInvocationBinding | None = None,
        scripted: tuple[tuple[str, tuple[ProviderToolProposal, ...]], ...] = (),
    ) -> None:
        self.text = text
        self.tool_proposals = tool_proposals
        self.requests: list[ProviderRequest] = []
        self.decision_requests: list[ProviderDecisionRequest] = []
        self._invocation_binding = invocation_binding
        self._scripted = list(scripted)

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        if self._invocation_binding is None:
            return super().invocation_binding
        return self._invocation_binding

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return self._response(request)

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        response = self.complete(request)
        if isinstance(response, ProviderFailure):
            # A failure is mode-independent: streaming must propagate it
            # unchanged instead of touching response-only fields.
            return response
        if on_text_delta is not None and response.text:
            chunk_size = 8
            for offset in range(0, len(response.text), chunk_size):
                on_text_delta(response.text[offset : offset + chunk_size])
        return response

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        self.decision_requests.append(request)
        if (
            request.expected_invocation_binding_digest
            != self.invocation_binding.digest()
        ):
            return self._failure(request, ProviderErrorCode.MALFORMED)
        return self._response(request)

    @staticmethod
    def _failure(
        request: ProviderDecisionRequest, code: ProviderErrorCode
    ) -> ProviderFailure:
        return ProviderFailure(
            failure_id=f"failure-{uuid4()}",
            request_id=request.request_id,
            code=code,
            retryable=False,
            safe_message="provider invocation binding mismatch",
            occurred_at=datetime.now(timezone.utc),
        )

    def _response(
        self, request: ProviderRequest | ProviderDecisionRequest
    ) -> ProviderResponse:
        if self._scripted:
            text, tool_proposals = self._scripted.pop(0)
        else:
            text, tool_proposals = self.text, self.tool_proposals
        return ProviderResponse(
            response_id=f"response-{uuid4()}",
            request_id=request.request_id,
            text=text,
            tool_proposals=tool_proposals,
            usage=ProviderUsage(
                input_tokens=sum(
                    len(message.content.split()) for message in request.messages
                ),
                output_tokens=len(text.split()),
                total_tokens=sum(
                    len(message.content.split()) for message in request.messages
                )
                + len(text.split()),
                # E3: no pricing source in the hermetic provider — cost is
                # honestly UNKNOWN, never a pseudo-zero.
                cost_status="UNKNOWN",
            ),
            finish_reason="stop",
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )


class OpenAICompatibleProvider(ProviderPort):
    """OpenAI-compatible chat/completions transport.

    The three transport hooks (``_request_body``, ``_transport_headers``,
    ``_parse_completion``) plus ``DEFAULT_ENDPOINT_PATH`` are the seam that
    native-protocol subclasses override; the invocation-binding, credential and
    failure machinery is shared and unchanged.
    """

    DEFAULT_ENDPOINT_PATH = "/chat/completions"
    EXPECTED_ENDPOINT_CLASS = "openai-compatible"
    ADAPTER_KIND = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        credential: CredentialRef,
        credentials: EnvCredentialBroker | None = None,
        timeout_seconds: int = 60,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        opener: Callable[..., object] | None = None,
        provider_profile: ProviderProfile | None = None,
    ) -> None:
        normalized_base_url = base_url.rstrip("/")
        resolved_temperature = (
            temperature
            if temperature is not None
            else float(
                os.environ.get(
                    "AGENT_OS_PROVIDER_TEMPERATURE",
                    os.environ.get("OPENAI_TEMPERATURE", "1.0"),
                )
            )
        )
        env_max_tokens = _optional_int_env("AGENT_OS_PROVIDER_MAX_TOKENS")
        resolved_max_tokens = max_tokens if max_tokens is not None else env_max_tokens
        if resolved_max_tokens is not None and resolved_max_tokens < 1:
            resolved_max_tokens = None
        env_max_retries = _optional_int_env("AGENT_OS_PROVIDER_MAX_RETRIES")
        env_retry_base = _optional_float_env("AGENT_OS_PROVIDER_RETRY_BASE_SECONDS")
        self._base_url = normalized_base_url
        self._model = model
        self._credential = credential
        self._credentials = credentials or EnvCredentialBroker()
        self._timeout_seconds = timeout_seconds
        self._temperature = resolved_temperature
        self._max_tokens = resolved_max_tokens
        # Explicit 0 must be honored (disable retries / zero backoff); only an
        # absent value falls back to the default.
        self._max_retries = (
            max_retries
            if max_retries is not None
            else env_max_retries
            if env_max_retries is not None
            else 2
        )
        self._retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else env_retry_base
            if env_retry_base is not None
            else 0.5
        )
        self._pricing = load_pricing_table()
        self._opener = opener or urllib.request.urlopen
        self._invocation_binding: ProviderInvocationBinding | None = None
        if provider_profile is not None:
            if credential.status is not CredentialStatus.ACTIVE:
                raise ValueError("provider credential must be active")
            if datetime.now(timezone.utc) >= credential.expires_at:
                raise ValueError("provider credential must be unexpired")
            if "chat" not in credential.scopes:
                raise ValueError("provider credential must grant chat scope")
            if (
                provider_profile.model_id != self._model
                or provider_profile.provider_id != credential.provider_id
                or provider_profile.credential_ref_id != credential.credential_ref_id
                or provider_profile.endpoint_class != self.EXPECTED_ENDPOINT_CLASS
            ):
                raise ValueError(
                    "provider profile does not match the adapter endpoint class"
                )
            self._invocation_binding = ProviderInvocationBinding(
                provider_profile=provider_profile,
                provider_id=credential.provider_id,
                endpoint_class=self.EXPECTED_ENDPOINT_CLASS,
                credential_ref_id=credential.credential_ref_id,
                credential_ref_digest=content_digest(credential),
                max_context_tokens=provider_profile.max_context_tokens,
                adapter_kind=self.ADAPTER_KIND,
                transport="https-json",
                base_url=self._base_url,
                endpoint_path=self.DEFAULT_ENDPOINT_PATH,
                model_id=self._model,
                request_timeout_seconds=self._timeout_seconds,
                temperature=Decimal(str(self._temperature)),
            )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    @property
    def credential(self) -> CredentialRef:
        return self._credential

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @property
    def temperature(self) -> float:
        return self._temperature

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        if self._invocation_binding is None:
            return super().invocation_binding
        return self._invocation_binding

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        return self._invoke_with_retry(
            request, allowed_capability_ids=request.allowed_capability_ids
        )

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        return self._invoke_with_retry(
            request,
            allowed_capability_ids=request.allowed_capability_ids,
            stream=True,
            on_text_delta=on_text_delta,
            on_reasoning_delta=on_reasoning_delta,
        )

    def _invoke_with_retry(
        self,
        request: ProviderRequest | ProviderDecisionRequest,
        *,
        allowed_capability_ids: tuple[str, ...],
        stream: bool = False,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        """Bounded retry for retryable failures (429/5xx/timeout).

        A stream that has already emitted a delta is never retried: replaying
        would duplicate output. Read-only completions carry no side effects, so
        retrying before any output is safe.
        """

        attempts = max(1, int(self._max_retries) + 1)
        emitted = False

        def _text_delta(chunk: str) -> None:
            nonlocal emitted
            emitted = True
            if on_text_delta is not None:
                on_text_delta(chunk)

        def _reasoning_delta(chunk: str) -> None:
            nonlocal emitted
            emitted = True
            if on_reasoning_delta is not None:
                on_reasoning_delta(chunk)

        result: ProviderResponse | ProviderFailure | None = None
        for attempt in range(attempts):
            result = self._invoke(
                request,
                allowed_capability_ids=allowed_capability_ids,
                stream=stream,
                on_text_delta=_text_delta if stream else on_text_delta,
                on_reasoning_delta=_reasoning_delta if stream else on_reasoning_delta,
            )
            if isinstance(result, ProviderResponse):
                return result
            if not result.retryable or emitted or attempt >= attempts - 1:
                return result
            time.sleep(self._retry_base_seconds * (2**attempt))
        assert result is not None
        return result

    def _request_body(
        self,
        request: ProviderRequest | ProviderDecisionRequest,
        *,
        model_id: str,
        temperature: float,
        allowed_capability_ids: tuple[str, ...],
        stream: bool,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": model_id,
            "messages": [
                _serialize_message(message) for message in request.messages
            ],
            "temperature": temperature,
        }
        if self._max_tokens is not None:
            body["max_tokens"] = self._max_tokens
        if allowed_capability_ids:
            body["tools"] = [
                _tool_definition(capability_id)
                for capability_id in allowed_capability_ids
            ]
            body["tool_choice"] = "auto"
        if stream:
            body["stream"] = True
            # Ask the provider to emit a final usage chunk so the SSE path
            # reports exact token counts like the JSON path (E3).
            body["stream_options"] = {"include_usage": True}
        return body

    def _transport_headers(self, secret: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

    def _endpoint_path(
        self,
        invocation: ProviderInvocationBinding | None,
        model_id: str,
        stream: bool = False,
    ) -> str:
        """Path after ``base_url``; native protocols may embed the model id."""
        if invocation is not None:
            return invocation.endpoint_path
        return self.DEFAULT_ENDPOINT_PATH

    def _usage(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int | None = None,
    ) -> ProviderUsage:
        """Exact tokens; cost KNOWN only when a local pricing source covers the model."""

        total = (
            total_tokens
            if total_tokens is not None and total_tokens > 0
            else input_tokens + output_tokens
        )
        entry = self._pricing.get(self._model)
        if entry is None:
            return ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total,
                cost_status="UNKNOWN",
            )
        cost = (
            Decimal(input_tokens) * Decimal(str(entry["input"]))
            + Decimal(output_tokens) * Decimal(str(entry["output"]))
        ) / Decimal(1000)
        return ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            cost_status="KNOWN",
            pricing_source_ref=str(entry["source"]),
        )

    def _parse_completion(
        self,
        payload: dict[str, Any],
        request: ProviderRequest | ProviderDecisionRequest,
    ) -> ProviderResponse:
        choice = payload["choices"][0]  # type: ignore[index]
        message = choice["message"]  # type: ignore[index]
        proposals = tuple(
            self._proposal(item) for item in message.get("tool_calls", ())
        )
        usage = payload.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        return ProviderResponse(
            response_id=str(payload.get("id", f"response-{uuid4()}")),
            request_id=request.request_id,
            text=str(message.get("content") or ""),
            tool_proposals=proposals,
            usage=self._usage(
                input_tokens,
                output_tokens,
                int(usage.get("total_tokens", 0)),
            ),
            finish_reason=str(choice.get("finish_reason", "stop")),
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        try:
            if (
                request.expected_invocation_binding_digest
                != self.invocation_binding.digest()
            ):
                return self._failure(
                    request,
                    ProviderErrorCode.MALFORMED,
                    "provider invocation binding mismatch",
                    False,
                )
        except RuntimeError:
            return self._failure(
                request,
                ProviderErrorCode.MALFORMED,
                "provider invocation binding unavailable",
                False,
            )
        return self._invoke_with_retry(request, allowed_capability_ids=())

    def _invoke(
        self,
        request: ProviderRequest | ProviderDecisionRequest,
        *,
        allowed_capability_ids: tuple[str, ...],
        stream: bool = False,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        try:
            invocation = self._invocation_binding
            if (
                invocation is not None
                and content_digest(self._credential) != invocation.credential_ref_digest
            ):
                return self._failure(
                    request,
                    ProviderErrorCode.AUTHENTICATION_FAILED,
                    "provider credential binding drifted",
                    False,
                )
            secret = self._credentials.resolve(self._credential)
            model_id = invocation.model_id if invocation is not None else self._model
            temperature = (
                float(invocation.temperature)
                if invocation is not None
                else self._temperature
            )
            base_url = invocation.base_url if invocation is not None else self._base_url
            endpoint_path = self._endpoint_path(invocation, model_id, stream)
            runtime_timeout_seconds = (
                invocation.request_timeout_seconds
                if invocation is not None
                else self._timeout_seconds
            )
            body = self._request_body(
                request,
                model_id=model_id,
                temperature=temperature,
                allowed_capability_ids=allowed_capability_ids,
                stream=stream,
            )
            encoded = json.dumps(body).encode("utf-8")
            http_request = urllib.request.Request(
                f"{base_url}{endpoint_path}",
                data=encoded,
                headers=self._transport_headers(secret),
                method="POST",
            )
            with self._opener(
                http_request,
                timeout=min(runtime_timeout_seconds, request.timeout_seconds),
            ) as response:  # type: ignore[call-arg]
                if stream:
                    return self._parse_sse_stream(
                        response,
                        request=request,
                        on_text_delta=on_text_delta,
                        on_reasoning_delta=on_reasoning_delta,
                    )
                payload = json.loads(response.read().decode("utf-8"))
            # A refusal is a failure, not an empty answer: the contract has
            # REFUSED for exactly this, and rendering it as "" left the operator
            # with a turn that said nothing and never said why. OpenAI-compatible
            # transports put it in `message.refusal` (content stays null) and
            # moderation blocks set finish_reason=content_filter.
            refusal: str | None = None
            choices = payload.get("choices") or []
            if choices:
                if str(choices[0].get("finish_reason") or "") == "content_filter":
                    refusal = "provider reported a content filter"
                else:
                    raw_refusal = (choices[0].get("message") or {}).get("refusal")
                    if isinstance(raw_refusal, str) and raw_refusal.strip():
                        refusal = raw_refusal.strip()
            if refusal is not None:
                return self._failure(
                    request,
                    ProviderErrorCode.REFUSED,
                    f"provider refused: {refusal[:300]}",
                    False,
                )
            return self._parse_completion(payload, request)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                code = ProviderErrorCode.AUTHENTICATION_FAILED
            elif exc.code == 429:
                code = ProviderErrorCode.RATE_LIMITED
            elif exc.code in {408, 425}:
                code = ProviderErrorCode.UNAVAILABLE
            elif 400 <= exc.code < 500:
                # Other 4xx (bad request/not found/unprocessable) are client
                # errors: retrying cannot help.
                code = ProviderErrorCode.MALFORMED
            else:
                code = ProviderErrorCode.UNAVAILABLE
            # The message becomes the turn's final text, i.e. the only thing the
            # operator reads. A bare "provider HTTP 401" names the symptom and
            # nothing else, so the most common real failure - a missing, wrong or
            # expired key - looked like an unexplained failure. Name the cause and
            # the next step; never the credential value itself (safe_message is
            # durable and must stay secret-free).
            if code is ProviderErrorCode.AUTHENTICATION_FAILED:
                message = (
                    f"provider rejected the credential (HTTP {exc.code}) - "
                    "check the configured provider key or re-run /provider"
                )
            elif code is ProviderErrorCode.RATE_LIMITED:
                message = f"provider rate limited (HTTP {exc.code}) - retrying"
            elif code is ProviderErrorCode.UNAVAILABLE:
                message = f"provider unavailable (HTTP {exc.code}) - retrying"
            else:
                message = f"provider rejected the request (HTTP {exc.code})"
            return self._failure(
                request,
                code,
                message,
                code in {ProviderErrorCode.RATE_LIMITED, ProviderErrorCode.UNAVAILABLE},
            )
        except TimeoutError:
            return self._failure(
                request, ProviderErrorCode.TIMEOUT, "provider request timed out", True
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(
                request,
                ProviderErrorCode.MALFORMED,
                f"provider response malformed: {type(exc).__name__}",
                False,
            )
        except CredentialUnavailable:
            return self._failure(
                request,
                ProviderErrorCode.AUTHENTICATION_FAILED,
                "credential unavailable",
                False,
            )
        except Exception as exc:
            return self._failure(
                request,
                ProviderErrorCode.UNAVAILABLE,
                f"provider unavailable: {type(exc).__name__}",
                True,
            )

    def _parse_sse_stream(
        self,
        response: object,
        *,
        request: ProviderRequest | ProviderDecisionRequest,
        on_text_delta: Callable[[str], None] | None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        text_parts: list[str] = []
        refusal_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        usage_payload: dict[str, Any] = {}
        response_id = f"response-{uuid4()}"
        finish_reason = "stop"
        readline = getattr(response, "readline", None)
        while True:
            raw_line = readline() if callable(readline) else b""
            if raw_line in (b"", ""):
                break
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8")
            else:
                line = str(raw_line)
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
            else:
                data = line
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return self._failure(
                    request,
                    ProviderErrorCode.MALFORMED,
                    "provider response malformed: JSONDecodeError",
                    False,
                )
            response_id = str(payload.get("id") or response_id)
            # The final usage block arrives in a frame whose choices list is
            # empty, so it must be captured before the choices guard below.
            usage = payload.get("usage")
            if isinstance(usage, dict):
                usage_payload.update(usage)
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = str(choice.get("finish_reason") or finish_reason)
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                text_parts.append(str(content))
                if on_text_delta is not None:
                    on_text_delta(str(content))
            # A refusal can also arrive as its own delta field; collect it so the
            # stream ends as a REFUSED failure rather than an empty reply.
            refusal_delta = delta.get("refusal")
            if refusal_delta:
                refusal_parts.append(str(refusal_delta))
            # Transient reasoning (DeepSeek `reasoning_content`): display-only,
            # never appended to text_parts / the durable response.
            reasoning = delta.get("reasoning_content")
            if reasoning and on_reasoning_delta is not None:
                on_reasoning_delta(str(reasoning))
            for tool_delta in delta.get("tool_calls") or []:
                index = int(tool_delta.get("index", 0))
                bucket = tool_calls.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                if tool_delta.get("id"):
                    bucket["id"] = str(tool_delta["id"])
                function = tool_delta.get("function") or {}
                if function.get("name"):
                    bucket["name"] = str(function["name"])
                if function.get("arguments"):
                    bucket["arguments"] += str(function["arguments"])
        proposals = tuple(
            ProviderToolProposal(
                proposal_id=item["id"] or f"proposal-{uuid4()}",
                capability_id=item["name"].replace("__", "."),
                arguments_json=item["arguments"] or "{}",
            )
            for _, item in sorted(tool_calls.items())
            if item["name"]
        )
        text_out = "".join(text_parts)
        if refusal_parts or finish_reason == "content_filter":
            refusal_text = "".join(refusal_parts).strip() or (
                "provider reported a content filter"
            )
            return self._failure(
                request,
                ProviderErrorCode.REFUSED,
                f"provider refused: {refusal_text[:300]}",
                False,
            )
        input_tokens = int(usage_payload.get("prompt_tokens") or 0)
        output_tokens = int(usage_payload.get("completion_tokens") or 0)
        total_tokens = int(usage_payload.get("total_tokens") or 0)
        return ProviderResponse(
            response_id=response_id,
            request_id=request.request_id,
            text=text_out,
            tool_proposals=proposals,
            usage=self._usage(input_tokens, output_tokens, total_tokens),
            finish_reason=finish_reason or "stop",
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )

    @staticmethod
    def _proposal(item: dict[str, object]) -> ProviderToolProposal:
        function = item.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool call function missing")
        return ProviderToolProposal(
            proposal_id=str(item.get("id", f"proposal-{uuid4()}")),
            capability_id=str(function["name"]).replace("__", "."),
            arguments_json=str(function.get("arguments", "{}")),
        )

    @staticmethod
    def _failure(
        request: ProviderRequest | ProviderDecisionRequest,
        code: ProviderErrorCode,
        message: str,
        retryable: bool,
    ) -> ProviderFailure:
        return ProviderFailure(
            failure_id=f"failure-{uuid4()}",
            request_id=request.request_id,
            code=code,
            retryable=retryable,
            safe_message=message,
            occurred_at=datetime.now(timezone.utc),
        )


def _serialize_message(message: ProviderMessage) -> dict[str, object]:
    """Map a typed ProviderMessage onto the OpenAI chat message wire shape."""
    if message.role is ProviderMessageRole.TOOL:
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    if message.role is ProviderMessageRole.ASSISTANT:
        body: dict[str, object] = {
            "role": "assistant",
            "content": message.content or None,
        }
        if message.tool_calls:
            body["tool_calls"] = [
                {
                    "id": tool_call.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.capability_id.replace(".", "__"),
                        "arguments": tool_call.arguments_json,
                    },
                }
                for tool_call in message.tool_calls
            ]
        return body
    return {"role": message.role.value.lower(), "content": message.content}


# Factual per-tool descriptions carried to the model on every transport
# (OpenAI tools, Anthropic tools, Gemini functionDeclarations). Each entry
# states what the capability does, where its arguments live and which result
# fields it returns -- including the truncation diagnostics of
# ``workspace.search``, which are worthless to the model if the tool list does
# not say they exist. The effect class and risk tier restate the domain pack's
# ``CapabilitySpec`` and the frozen ``ACTION_RISK_TIERS`` allowlist; no policy is
# added here. A capability with no entry keeps the generic fallback sentence.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "workspace.read": (
        "Read one UTF-8 text file from the workspace. Argument: `path` "
        "(required, workspace-relative; absolute paths, symlink paths and the "
        "agent state directory are denied). Result: `path`, `content` (the "
        "complete file text) and `sha256` (digest of `content`). "
        "workspace.edit and workspace.apply_patch check their optional "
        "`expected_sha256` against the target file before writing and deny on "
        "mismatch. READ_ONLY, risk tier 1, no confirmation. A result "
        "whose serialized JSON exceeds 8000 characters arrives as "
        "`{truncated: true, preview: ...}`."
    ),
    "workspace.search": (
        "Search the workspace in one of three modes, selected by the required "
        "`mode` argument, under `path` (default \".\"). Mode \"ls\" lists one "
        "directory and returns `entries`. Mode \"glob\" matches the glob "
        "`pattern` and returns `matches`. Mode \"grep\" matches the regular "
        "expression `pattern` (a file `path` searches that file) and returns "
        "`matches` as \"relpath:lineno:line\", lines cut at 500 characters. "
        ".git, node_modules, __pycache__, .venv, .agent-os-artifacts and "
        ".agent_os are never searched. Results carry `truncated` (bool) and "
        "`truncated_reason`: null when the search was complete, otherwise "
        "\"scan_cap\" (only the first 1000 candidate files were read), "
        "\"result_cap\" (the 200-entry result list is full) or \"output_cap\" (the "
        "20000-character output budget was reached). grep also reports "
        "`scanned_files` and `unexamined_files` (candidate files whose "
        "contents were not read, e.g. those left behind by the scan cap). "
        "`matches: []` with `truncated_reason: \"scan_cap\"` means the tree "
        "was not searched exhaustively, so it does not establish that no match "
        "exists. READ_ONLY, risk tier 1, no confirmation."
    ),
    "workspace.edit": (
        "Replace one exact string in an existing workspace file. Arguments: "
        "`path` (required), `old_string` (required; must occur exactly once in "
        "the current file, otherwise the call is denied), `new_string` "
        "(required) and optional `expected_sha256` (denied on mismatch instead "
        "of overwriting a file that changed). Result: `path`, `sha256` and "
        "`applied_sha256` (digest after the write), `before_sha256`, "
        "`compensation_ref` and `manifest_sha256` (the durable snapshot that "
        "backs compensation) and `replayed` (true when an identical prior "
        "patch was already applied). SANDBOX_COMPENSATABLE, risk tier 2: "
        "auto-allowed only when the session permission mode is "
        "ACCEPT_IN_WORKSPACE, otherwise a human approval decision is required."
    ),
    "workspace.apply_patch": (
        "Write a whole file in the workspace -- full-content replacement, or "
        "creation of a new file. Arguments: `path` (required), `content` "
        "(required, the complete new file text) and optional `expected_sha256` "
        "(denied on mismatch). Result: `path`, `sha256` and `applied_sha256`, "
        "`before_sha256`, `compensation_ref`, `manifest_sha256` and "
        "`replayed`, the same durable snapshot binding workspace.edit returns. "
        "SANDBOX_COMPENSATABLE, risk tier 2: auto-allowed only when the "
        "session permission mode is ACCEPT_IN_WORKSPACE, otherwise a human "
        "approval decision is required."
    ),
    "workspace.run_tests": (
        "Run the project test suite inside the workspace. Arguments: `command` "
        "(required; one of \"pytest\", \"python -m pytest\", "
        "\"python3 -m pytest\") and optional `timeout_seconds` (1-120). "
        "Result: `exit_code`, `digest` and `artifact_ids`; stdout and stderr "
        "are not inline -- the full \"test-report.v1\" report (command, "
        "exit_code, stdout, stderr) is stored content-addressed and named by "
        "`artifact_ids`. Commands outside the allowlist are denied. "
        "SANDBOX_IDEMPOTENT, risk tier 1, no confirmation."
    ),
    "workspace.shell": (
        "Run an allowlisted shell command inside the workspace. Arguments: "
        "`command` (required, allowlisted) and optional `timeout_seconds` "
        "(1-300). Result: `exit_code`, `stdout` and `stderr`, each the last "
        "4000 characters of its stream, plus `digest` and `artifact_ids` for "
        "the full \"shell-report.v1\" report. Commands outside the allowlist "
        "are denied. SANDBOX_IDEMPOTENT, risk tier 3: a human approval "
        "decision is required and it is never auto-approved."
    ),
    "artifact.write": (
        "Store string content as a content-addressed artifact. Argument: "
        "`content` (this capability is declared with additionalProperties: "
        "true, so no argument schema is published). Result: `artifact_ids` "
        "(e.g. \"artifact:<sha256>\") and `digest` (sha256 of the content); "
        "rewriting identical content is idempotent and writes nothing. "
        "SANDBOX_IDEMPOTENT with CapabilitySpec risk tier 1, but "
        "artifact.write is not in the permission gate's E2 allowlist "
        "(ACTION_RISK_TIERS), which denies a capability outside that allowlist "
        "in every permission mode without executing it."
    ),
    "session.todo_write": (
        "Replace the session task list. Argument: `todos` (required array of "
        "at most 100 items, each `{id, content, status}` with status one of "
        "pending, in_progress, done) -- full-replace semantics, the submitted "
        "list is the entire new list. Result: `ok`, `todos` (the normalized "
        "stored list) and `count`. Session scratchpad only: no file, process "
        "or network effect. TRANSACTIONAL_INTERNAL, risk tier 1, no "
        "confirmation."
    ),
}

_GENERIC_TOOL_DESCRIPTION = "Propose typed capability {capability_id}"


def _tool_definition(capability_id: str) -> dict[str, object]:
    parameters = _WORKSPACE_TOOL_PARAMETERS.get(
        capability_id,
        {
            "type": "object",
            "additionalProperties": True,
        },
    )
    return {
        "type": "function",
        "function": {
            "name": capability_id.replace(".", "__"),
            "description": _TOOL_DESCRIPTIONS.get(
                capability_id,
                _GENERIC_TOOL_DESCRIPTION.format(capability_id=capability_id),
            ),
            "parameters": parameters,
        },
    }


class AnthropicMessagesProvider(OpenAICompatibleProvider):
    """Native Anthropic Messages transport (``POST {base_url}/v1/messages``).

    Reuses the shared invocation-binding, credential and failure machinery from
    ``OpenAICompatibleProvider`` and overrides only the transport hooks. Token
    streaming is native via ``_parse_sse_stream`` (the Messages SSE dialect);
    cost remains UNKNOWN (no pricing source), token counts are exact.
    """

    DEFAULT_ENDPOINT_PATH = "/v1/messages"
    EXPECTED_ENDPOINT_CLASS = "anthropic-messages"
    ADAPTER_KIND = "anthropic-messages"
    ANTHROPIC_VERSION = "2023-06-01"
    DEFAULT_MAX_TOKENS = 4096

    def _transport_headers(self, secret: str) -> dict[str, str]:
        return {
            "x-api-key": secret,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _request_body(
        self,
        request: ProviderRequest | ProviderDecisionRequest,
        *,
        model_id: str,
        temperature: float,
        allowed_capability_ids: tuple[str, ...],
        stream: bool,
    ) -> dict[str, object]:
        system_parts = [
            str(message.content)
            for message in request.messages
            if message.role is ProviderMessageRole.SYSTEM
        ]
        body: dict[str, object] = {
            "model": model_id,
            "max_tokens": self._max_tokens or self.DEFAULT_MAX_TOKENS,
            "messages": [
                _anthropic_message(message)
                for message in request.messages
                if message.role is not ProviderMessageRole.SYSTEM
            ],
        }
        if stream:
            body["stream"] = True
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if temperature is not None:
            body["temperature"] = temperature
        if allowed_capability_ids:
            body["tools"] = [
                _anthropic_tool(capability_id)
                for capability_id in allowed_capability_ids
            ]
        return body

    def _parse_completion(
        self,
        payload: dict[str, Any],
        request: ProviderRequest | ProviderDecisionRequest,
    ) -> ProviderResponse:
        blocks = payload.get("content", [])
        if not isinstance(blocks, list):
            raise ValueError("anthropic response content must be a list")
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        proposals = tuple(
            ProviderToolProposal(
                proposal_id=str(block.get("id", f"proposal-{uuid4()}")),
                capability_id=str(block.get("name", "")).replace("__", "."),
                arguments_json=json.dumps(block.get("input", {})),
            )
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
        usage = payload.get("usage", {})
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        raw_finish = payload.get("stop_reason")
        finish_reason = str(raw_finish) if raw_finish else "stop"
        return ProviderResponse(
            response_id=str(payload.get("id", f"response-{uuid4()}")),
            request_id=request.request_id,
            text=text,
            tool_proposals=proposals,
            usage=self._usage(input_tokens, output_tokens),
            finish_reason=finish_reason,
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )

    def _parse_sse_stream(
        self,
        response: object,
        *,
        request: ProviderRequest | ProviderDecisionRequest,
        on_text_delta: Callable[[str], None] | None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        """Parse the Anthropic Messages SSE dialect into one response.

        Handles message_start / content_block_start / content_block_delta
        (text_delta + input_json_delta) / message_delta. Text deltas are streamed
        to ``on_text_delta``; tool inputs are accumulated and normalized.
        """

        text_parts: list[str] = []
        blocks: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        response_id = f"response-{uuid4()}"
        finish_reason = "stop"
        readline = getattr(response, "readline", None)
        while True:
            raw_line = readline() if callable(readline) else b""
            if raw_line in (b"", ""):
                break
            line = (
                raw_line.decode("utf-8")
                if isinstance(raw_line, bytes)
                else str(raw_line)
            ).strip()
            if not line or line.startswith("event:") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return self._failure(
                    request,
                    ProviderErrorCode.MALFORMED,
                    "provider response malformed: JSONDecodeError",
                    False,
                )
            event_type = payload.get("type")
            if event_type == "message_start":
                message = payload.get("message") or {}
                response_id = str(message.get("id") or response_id)
                start_usage = message.get("usage")
                if isinstance(start_usage, dict):
                    usage.update(start_usage)
            elif event_type == "content_block_start":
                index = int(payload.get("index", 0))
                block = payload.get("content_block") or {}
                if block.get("type") == "tool_use":
                    blocks[index] = {
                        "id": str(block.get("id", "")),
                        "name": str(block.get("name", "")),
                        "arguments": "",
                    }
            elif event_type == "content_block_delta":
                index = int(payload.get("index", 0))
                delta = payload.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = str(delta.get("text", ""))
                    if text:
                        text_parts.append(text)
                        if on_text_delta is not None:
                            on_text_delta(text)
                elif delta.get("type") == "input_json_delta":
                    bucket = blocks.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    bucket["arguments"] += str(delta.get("partial_json", ""))
                elif delta.get("type") == "thinking_delta":
                    # Transient reasoning is display-only and never merged into
                    # the durable response text.
                    thinking = str(delta.get("thinking", ""))
                    if thinking and on_reasoning_delta is not None:
                        on_reasoning_delta(thinking)
            elif event_type == "message_delta":
                delta = payload.get("delta") or {}
                if delta.get("stop_reason"):
                    finish_reason = str(delta["stop_reason"])
                delta_usage = payload.get("usage")
                if isinstance(delta_usage, dict):
                    usage.update(delta_usage)
        proposals = tuple(
            ProviderToolProposal(
                proposal_id=item["id"] or f"proposal-{uuid4()}",
                capability_id=item["name"].replace("__", "."),
                arguments_json=item["arguments"] or "{}",
            )
            for _, item in sorted(blocks.items())
            if item["name"]
        )
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return ProviderResponse(
            response_id=response_id,
            request_id=request.request_id,
            text="".join(text_parts),
            tool_proposals=proposals,
            usage=self._usage(input_tokens, output_tokens),
            finish_reason=finish_reason,
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )


def _anthropic_message(message: ProviderMessage) -> dict[str, object]:
    """Map a typed ProviderMessage onto the Anthropic Messages wire shape."""
    if message.role is ProviderMessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": str(message.tool_call_id),
                    "content": message.content,
                }
            ],
        }
    if message.role is ProviderMessageRole.ASSISTANT and message.tool_calls:
        blocks: list[dict[str, object]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for tool_call in message.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call.tool_call_id,
                    "name": tool_call.capability_id.replace(".", "__"),
                    "input": _safe_json_object(tool_call.arguments_json),
                }
            )
        return {"role": "assistant", "content": blocks}
    role = "assistant" if message.role is ProviderMessageRole.ASSISTANT else "user"
    return {"role": role, "content": message.content}


def _anthropic_tool(capability_id: str) -> dict[str, object]:
    definition = _tool_definition(capability_id)
    function = definition["function"]  # type: ignore[index]
    return {
        "name": function["name"],  # type: ignore[index]
        "description": function.get("description", ""),  # type: ignore[union-attr]
        "input_schema": function["parameters"],  # type: ignore[index]
    }


def _safe_json_object(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class GeminiGenerativeProvider(OpenAICompatibleProvider):
    """Native Google Gemini generateContent transport.

    ``POST {base_url}/v1beta/models/{model}:generateContent`` with an
    ``x-goog-api-key`` header. Reuses the shared invocation/credential/failure
    machinery. Token streaming is native via ``_parse_sse_stream``
    (``streamGenerateContent?alt=sse``); token usage is exact, cost UNKNOWN.
    """

    DEFAULT_ENDPOINT_PATH = "/v1beta/models"
    EXPECTED_ENDPOINT_CLASS = "google-generative"
    ADAPTER_KIND = "google-generative"

    def _transport_headers(self, secret: str) -> dict[str, str]:
        return {
            "x-goog-api-key": secret,
            "Content-Type": "application/json",
        }

    def _endpoint_path(
        self,
        invocation: ProviderInvocationBinding | None,
        model_id: str,
        stream: bool = False,
    ) -> str:
        # The model id is embedded in the path; it is not carried by the
        # invocation binding, so it must always be built here (otherwise a
        # provider_profile would yield a model-less path). Streaming uses
        # streamGenerateContent with SSE (alt=sse).
        method = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"/v1beta/models/{model_id}:{method}"

    def _request_body(
        self,
        request: ProviderRequest | ProviderDecisionRequest,
        *,
        model_id: str,
        temperature: float,
        allowed_capability_ids: tuple[str, ...],
        stream: bool,
    ) -> dict[str, object]:
        system_parts = [
            str(message.content)
            for message in request.messages
            if message.role is ProviderMessageRole.SYSTEM
        ]
        tool_names = {
            str(tool_call.tool_call_id): str(tool_call.capability_id).replace(
                ".", "__"
            )
            for message in request.messages
            if message.role is ProviderMessageRole.ASSISTANT
            for tool_call in message.tool_calls
        }
        body: dict[str, object] = {
            "contents": [
                _gemini_content(message, tool_names)
                for message in request.messages
                if message.role is not ProviderMessageRole.SYSTEM
            ]
        }
        if system_parts:
            body["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }
        generation_config: dict[str, object] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if self._max_tokens is not None:
            generation_config["maxOutputTokens"] = self._max_tokens
        if generation_config:
            body["generationConfig"] = generation_config
        if allowed_capability_ids:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        _gemini_tool(capability_id)
                        for capability_id in allowed_capability_ids
                    ]
                }
            ]
        return body

    def _parse_completion(
        self,
        payload: dict[str, Any],
        request: ProviderRequest | ProviderDecisionRequest,
    ) -> ProviderResponse:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("gemini response has no candidates")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ValueError("gemini candidate must be an object")
        content = candidate.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ValueError("gemini candidate content must carry parts")
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict)
            and "text" in part
            and not part.get("thought")
        )
        proposals: list[ProviderToolProposal] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            call = part.get("functionCall")
            if not isinstance(call, dict):
                continue
            proposals.append(
                ProviderToolProposal(
                    proposal_id=f"proposal-{uuid4()}",
                    capability_id=str(call.get("name", "")).replace("__", "."),
                    arguments_json=json.dumps(call.get("args", {})),
                )
            )
        usage = payload.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount", 0))
        output_tokens = int(usage.get("candidatesTokenCount", 0))
        raw_finish = candidate.get("finishReason")
        return ProviderResponse(
            response_id=str(payload.get("responseId", f"response-{uuid4()}")),
            request_id=request.request_id,
            text=text,
            tool_proposals=tuple(proposals),
            usage=self._usage(
                input_tokens, output_tokens, int(usage.get("totalTokenCount", 0))
            ),
            finish_reason=str(raw_finish).lower() if raw_finish else "stop",
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )

    def _parse_sse_stream(
        self,
        response: object,
        *,
        request: ProviderRequest | ProviderDecisionRequest,
        on_text_delta: Callable[[str], None] | None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        """Parse the Gemini ``streamGenerateContent`` SSE dialect.

        With ``alt=sse`` each ``data:`` line is a GenerateContentResponse chunk;
        text parts are streamed, functionCalls are mapped, usageMetadata is
        accumulated and the model's finishReason is taken from the last chunk.
        """

        text_parts: list[str] = []
        proposals: list[ProviderToolProposal] = []
        usage: dict[str, Any] = {}
        response_id = f"response-{uuid4()}"
        finish_reason = "stop"
        readline = getattr(response, "readline", None)
        while True:
            raw_line = readline() if callable(readline) else b""
            if raw_line in (b"", ""):
                break
            line = (
                raw_line.decode("utf-8")
                if isinstance(raw_line, bytes)
                else str(raw_line)
            ).strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return self._failure(
                    request,
                    ProviderErrorCode.MALFORMED,
                    "provider response malformed: JSONDecodeError",
                    False,
                )
            response_id = str(payload.get("responseId") or response_id)
            chunk_usage = payload.get("usageMetadata")
            if isinstance(chunk_usage, dict):
                usage.update(chunk_usage)
            candidates = payload.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                continue
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                continue
            if candidate.get("finishReason"):
                finish_reason = str(candidate["finishReason"]).lower()
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            for part in parts or []:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if text:
                    if part.get("thought"):
                        # Transient reasoning (thought) is display-only; never
                        # merged into the durable response text.
                        if on_reasoning_delta is not None:
                            on_reasoning_delta(str(text))
                    else:
                        text_parts.append(str(text))
                        if on_text_delta is not None:
                            on_text_delta(str(text))
                call = part.get("functionCall")
                if isinstance(call, dict):
                    proposals.append(
                        ProviderToolProposal(
                            proposal_id=f"proposal-{uuid4()}",
                            capability_id=str(call.get("name", "")).replace(
                                "__", "."
                            ),
                            arguments_json=json.dumps(call.get("args", {})),
                        )
                    )
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        return ProviderResponse(
            response_id=response_id,
            request_id=request.request_id,
            text="".join(text_parts),
            tool_proposals=tuple(proposals),
            usage=self._usage(
                input_tokens, output_tokens, int(usage.get("totalTokenCount") or 0)
            ),
            finish_reason=finish_reason,
            received_at=datetime.now(timezone.utc),
            invocation_binding_digest=(
                self._invocation_binding.digest()
                if self._invocation_binding is not None
                else None
            ),
        )


def _gemini_content(
    message: ProviderMessage,
    tool_names: dict[str, str],
) -> dict[str, object]:
    if message.role is ProviderMessageRole.TOOL:
        name = tool_names.get(str(message.tool_call_id))
        if name is None:
            # A tool result with no matching declared function cannot be mapped
            # onto a valid Gemini functionResponse; fail closed as malformed.
            raise ValueError("gemini tool result has no matching function call")
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": name,
                        "response": {"content": message.content},
                    }
                }
            ],
        }
    if message.role is ProviderMessageRole.ASSISTANT:
        parts: list[dict[str, object]] = []
        if message.content:
            parts.append({"text": message.content})
        for tool_call in message.tool_calls:
            parts.append(
                {
                    "functionCall": {
                        "name": tool_call.capability_id.replace(".", "__"),
                        "args": _safe_json_object(tool_call.arguments_json),
                    }
                }
            )
        return {"role": "model", "parts": parts or [{"text": ""}]}
    return {"role": "user", "parts": [{"text": message.content}]}


_GEMINI_SCHEMA_KEYS = frozenset(
    {"type", "description", "enum", "items", "properties", "required", "nullable", "format"}
)


def _gemini_schema(value: object) -> object:
    """Project an OpenAI-style JSON schema onto the Gemini Schema subset.

    Gemini rejects unknown keys (e.g. ``additionalProperties``, ``minLength``),
    so only the supported subset is forwarded. ``properties`` is special: its
    keys are user attribute names (not schema keywords) and must be preserved
    while each property's value is projected as a schema.
    """

    if isinstance(value, list):
        return [_gemini_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected: dict[str, object] = {}
    for key, item in value.items():
        if key == "properties" and isinstance(item, dict):
            projected["properties"] = {
                name: _gemini_schema(schema) for name, schema in item.items()
            }
        elif key in _GEMINI_SCHEMA_KEYS:
            projected[key] = _gemini_schema(item)
    return projected


def _gemini_tool(capability_id: str) -> dict[str, object]:
    definition = _tool_definition(capability_id)
    function = definition["function"]  # type: ignore[index]
    return {
        "name": function["name"],  # type: ignore[index]
        "description": function.get("description", ""),  # type: ignore[union-attr]
        "parameters": _gemini_schema(function["parameters"]),  # type: ignore[index]
    }
