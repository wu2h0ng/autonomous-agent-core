from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
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
        self._base_url = normalized_base_url
        self._model = model
        self._credential = credential
        self._credentials = credentials or EnvCredentialBroker()
        self._timeout_seconds = timeout_seconds
        self._temperature = resolved_temperature
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
        return self._invoke(
            request, allowed_capability_ids=request.allowed_capability_ids
        )

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
    ) -> ProviderResponse | ProviderFailure:
        return self._invoke(
            request,
            allowed_capability_ids=request.allowed_capability_ids,
            stream=True,
            on_text_delta=on_text_delta,
            on_reasoning_delta=on_reasoning_delta,
        )

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
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(
                    usage.get("total_tokens", input_tokens + output_tokens)
                ),
                # E3: token counts are exact from the provider payload; cost has
                # no pricing source here — UNKNOWN, never zero.
                cost_status="UNKNOWN",
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
        return self._invoke(request, allowed_capability_ids=())

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
            return self._parse_completion(payload, request)
        except urllib.error.HTTPError as exc:
            code = (
                ProviderErrorCode.AUTHENTICATION_FAILED
                if exc.code in {401, 403}
                else ProviderErrorCode.RATE_LIMITED
                if exc.code == 429
                else ProviderErrorCode.UNAVAILABLE
            )
            return self._failure(
                request,
                code,
                f"provider HTTP {exc.code}",
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
        input_tokens = int(usage_payload.get("prompt_tokens") or 0)
        output_tokens = int(usage_payload.get("completion_tokens") or 0)
        total_tokens = int(usage_payload.get("total_tokens") or 0)
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        return ProviderResponse(
            response_id=response_id,
            request_id=request.request_id,
            text=text_out,
            tool_proposals=proposals,
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                # E3: streamed frames carry usage counters (stream_options.
                # include_usage) but still no pricing source — cost is
                # UNKNOWN, never a pseudo-zero.
                cost_status="UNKNOWN",
            ),
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
            "description": f"Propose typed capability {capability_id}",
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
            "max_tokens": self.DEFAULT_MAX_TOKENS,
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
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                # E3: exact tokens from the provider payload; no pricing source
                # here — cost is UNKNOWN, never zero.
                cost_status="UNKNOWN",
            ),
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
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_status="UNKNOWN",
            ),
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
        if temperature is not None:
            body["generationConfig"] = {"temperature": temperature}
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
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(
                    usage.get("totalTokenCount", input_tokens + output_tokens)
                ),
                # E3: exact tokens; no pricing source — cost UNKNOWN.
                cost_status="UNKNOWN",
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
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(
                    usage.get("totalTokenCount") or (input_tokens + output_tokens)
                ),
                cost_status="UNKNOWN",
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
