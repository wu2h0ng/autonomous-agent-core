"""Direct, typed Responses API actor candidate for R-STATE-CREDIT-1.

This module contains a real stdlib HTTP transport, but importing it performs no
credential lookup or network operation.  Connectivity remains an explicit later
canary.  The project transport is direct HTTP; arkcli is never imported or used.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol

from experiments.r_state_credit_1.contracts import (
    ContractViolation,
    ProbeAction,
    canonical_json,
)
from experiments.r_state_credit_1.run_contracts import (
    ActorBinding,
    ActorCost,
    ActorCostStatus,
    ActorRequest,
    ActorResponse,
    ActorTransport,
    ActorUsage,
    ExecutionDependencyFailure,
)


ARK_AGENT_PLAN_BASE_PROFILE = "https://ark.cn-beijing.volces.com/api/plan/v3"
ARK_RESPONSES_PATH = "/responses"
ARK_MODEL_ALIAS = "ark-code-latest"
ARK_CREDENTIAL_ENV_REF = "ARK_API_KEY"
CONNECTIVITY_CANARY_STATUS = "UNRUN"

_MAX_RESPONSE_BYTES = 1_048_576


class ActorFailureCategory(str, Enum):
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"


class ActorClientFailure(ExecutionDependencyFailure):
    """Secret-free, digest-only failure from a direct Responses request."""

    def __init__(
        self,
        *,
        category: ActorFailureCategory,
        error_code: str,
        request_sha256: str | None,
        response_sha256: str | None,
        http_status: int | None,
        timed_out: bool,
        timeout_seconds: float,
    ) -> None:
        super().__init__(f"{category.value}:{error_code}")
        self.category = category
        self.error_code = error_code
        self.request_sha256 = request_sha256
        self.response_sha256 = response_sha256
        self.http_status = http_status
        self.timed_out = timed_out
        self.timeout_seconds = timeout_seconds


@dataclass(frozen=True, slots=True)
class ResponsesHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, int)
            or isinstance(self.status, bool)
            or not 100 <= self.status <= 599
        ):
            raise ContractViolation("HTTP status must be in [100, 599]")
        if not isinstance(self.headers, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.headers.items()
        ):
            raise ContractViolation("HTTP headers must be a text mapping")
        if not isinstance(self.body, bytes):
            raise ContractViolation("HTTP body must be bytes")
        if len(self.body) > _MAX_RESPONSE_BYTES:
            raise ContractViolation("HTTP body exceeds the bounded response size")


class ResponsesHttpTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> ResponsesHttpResponse: ...


class StdlibResponsesHttpTransport:
    """Direct urllib transport. No CLI, SDK or provider call occurs at import."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> ResponsesHttpResponse:
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - exact HTTPS URL is binding-validated
                response_body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(response_body) > _MAX_RESPONSE_BYTES:
                    raise OSError("bounded response size exceeded")
                return ResponsesHttpResponse(
                    status=int(response.status),
                    headers={key: value for key, value in response.headers.items()},
                    body=response_body,
                )
        except urllib.error.HTTPError as exc:
            response_body = exc.read(_MAX_RESPONSE_BYTES + 1)
            if len(response_body) > _MAX_RESPONSE_BYTES:
                response_body = response_body[:_MAX_RESPONSE_BYTES]
            return ResponsesHttpResponse(
                status=exc.code,
                headers={key: value for key, value in exc.headers.items()},
                body=response_body,
            )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a mapping")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


class ArkResponsesActorClient:
    """Fail-closed candidate ActorClient for the ARK Agent Plan data plane."""

    def __init__(
        self,
        *,
        binding: ActorBinding,
        system_prompt: str,
        tool_schema: Mapping[str, object],
        transport: ResponsesHttpTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(binding, ActorBinding):
            raise ContractViolation("binding must be ActorBinding")
        if binding.transport is not ActorTransport.API_ONLY:
            raise ContractViolation("ARK actor requires API_ONLY transport")
        if binding.base_profile != ARK_AGENT_PLAN_BASE_PROFILE:
            raise ContractViolation("ARK Agent Plan base profile drift")
        if binding.responses_path != ARK_RESPONSES_PATH:
            raise ContractViolation("ARK Responses path drift")
        if binding.credential_env_ref != ARK_CREDENTIAL_ENV_REF:
            raise ContractViolation("ARK credential environment reference drift")
        if binding.model_id != ARK_MODEL_ALIAS:
            raise ContractViolation("ARK model alias drift")
        if not isinstance(system_prompt, str) or not system_prompt:
            raise ContractViolation("system_prompt must be non-empty text")
        if not isinstance(tool_schema, Mapping):
            raise ContractViolation("tool_schema must be a mapping")
        try:
            canonical_tool_schema = canonical_json(tool_schema)
        except (TypeError, ValueError) as exc:
            raise ContractViolation("tool_schema must be canonical JSON") from exc
        if _sha256_bytes(system_prompt.encode("utf-8")) != binding.system_prompt_sha256:
            raise ContractViolation("system_prompt hash drift")
        if (
            _sha256_bytes(canonical_tool_schema.encode("utf-8"))
            != binding.tool_schema_sha256
        ):
            raise ContractViolation("tool_schema hash drift")
        self.binding = binding
        self._system_prompt = system_prompt
        self._tool_schema = json.loads(canonical_tool_schema)
        self._transport = transport or StdlibResponsesHttpTransport()
        self._environ = os.environ if environ is None else environ

    def _request_body(self, request: ActorRequest) -> bytes:
        if request.tool_schema_sha256 != self.binding.tool_schema_sha256:
            raise ActorClientFailure(
                category=ActorFailureCategory.SCHEMA_ERROR,
                error_code="TOOL_SCHEMA_BINDING_DRIFT",
                request_sha256=request.digest(),
                response_sha256=None,
                http_status=None,
                timed_out=False,
                timeout_seconds=float(self.binding.request_timeout_seconds),
            )
        actor_input = canonical_json(
            {
                "schema_version": "r-state-credit-1-actor-input-v1",
                "system_prompt": self._system_prompt,
                "request": request.to_mapping(),
                "response_schema": self._tool_schema,
            }
        )
        provider_request = {
            "model": self.binding.model_id,
            "input": actor_input,
            "temperature": self.binding.temperature,
            "top_p": self.binding.top_p,
            "max_output_tokens": self.binding.max_output_tokens,
            "stream": False,
        }
        return canonical_json(provider_request).encode("utf-8")

    def _failure(
        self,
        *,
        category: ActorFailureCategory,
        error_code: str,
        request_sha256: str | None,
        response_sha256: str | None = None,
        http_status: int | None = None,
        timed_out: bool = False,
    ) -> ActorClientFailure:
        return ActorClientFailure(
            category=category,
            error_code=error_code,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
            http_status=http_status,
            timed_out=timed_out,
            timeout_seconds=float(self.binding.request_timeout_seconds),
        )

    def _http_error_code(self, body: bytes, status: int) -> str:
        try:
            payload = _strict_mapping(json.loads(body), "HTTP error")
            error = _strict_mapping(payload.get("error"), "HTTP error.error")
            code = error.get("code")
            if isinstance(code, str) and code.strip():
                return code
        except (UnicodeError, json.JSONDecodeError, ValueError):
            pass
        return f"HTTP_{status}"

    def _parse_success(
        self,
        *,
        request: ActorRequest,
        request_body: bytes,
        response: ResponsesHttpResponse,
        latency_ms: int,
    ) -> ActorResponse:
        response_sha256 = _sha256_bytes(response.body)
        request_sha256 = _sha256_bytes(request_body)
        try:
            payload = _strict_mapping(json.loads(response.body), "response")
            response_id = payload.get("id")
            if not isinstance(response_id, str) or not response_id.strip():
                raise ValueError("response.id must be non-empty text")
            if payload.get("status") != "completed":
                raise ValueError("response status must be completed")
            if payload.get("error") is not None:
                raise ValueError("completed response must not contain an error")
            if payload.get("model") != self.binding.model_id:
                raise self._failure(
                    category=ActorFailureCategory.SCHEMA_ERROR,
                    error_code="MODEL_IDENTITY_DRIFT",
                    request_sha256=request_sha256,
                    response_sha256=response_sha256,
                    http_status=response.status,
                )
            output = payload.get("output")
            if not isinstance(output, list) or not output:
                raise ValueError("response.output must be a non-empty list")
            texts: list[str] = []
            for raw_item in output:
                item = _strict_mapping(raw_item, "response.output item")
                if item.get("type") != "message":
                    continue
                if item.get("role") != "assistant" or item.get("status") != "completed":
                    raise ValueError("message output identity/status drift")
                content = item.get("content")
                if not isinstance(content, list):
                    raise ValueError("message content must be a list")
                for raw_content in content:
                    content_item = _strict_mapping(raw_content, "message content")
                    if content_item.get("type") == "output_text":
                        text = content_item.get("text")
                        if not isinstance(text, str):
                            raise ValueError("output_text.text must be text")
                        texts.append(text)
            if len(texts) != 1:
                raise ValueError("response must contain exactly one output_text")
            action_payload = _strict_mapping(json.loads(texts[0]), "action output")
            if set(action_payload) != {"action"}:
                raise ValueError("action output must be a closed one-field mapping")
            if canonical_json(action_payload) != texts[0]:
                raise ValueError("action output must use canonical JSON bytes")
            action = ProbeAction(action_payload["action"])
            if action not in request.allowed_actions:
                raise ValueError("action is outside the request grammar")
            usage_payload = _strict_mapping(payload.get("usage"), "usage")
            input_tokens = _nonnegative_int(
                usage_payload.get("input_tokens"), "usage.input_tokens"
            )
            output_tokens = _nonnegative_int(
                usage_payload.get("output_tokens"), "usage.output_tokens"
            )
            total_tokens = _nonnegative_int(
                usage_payload.get("total_tokens"), "usage.total_tokens"
            )
            usage = ActorUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
            raw_cost = payload.get("cost")
            if raw_cost is None:
                cost = ActorCost(
                    status=ActorCostStatus.UNAVAILABLE_NOT_GUESSED,
                    amount_microunits=None,
                    currency=None,
                )
            else:
                cost_payload = _strict_mapping(raw_cost, "cost")
                if set(cost_payload) != {"amount_microunits", "currency"}:
                    raise ValueError("cost must use the closed provider-cost schema")
                cost = ActorCost(
                    status=ActorCostStatus.PROVIDER_REPORTED,
                    amount_microunits=_nonnegative_int(
                        cost_payload["amount_microunits"], "cost.amount_microunits"
                    ),
                    currency=(
                        cost_payload["currency"]
                        if isinstance(cost_payload["currency"], str)
                        else ""
                    ),
                )
            return ActorResponse(
                response_id=response_id,
                request_id=request.request_id,
                provider=self.binding.provider,
                model_id=self.binding.model_id,
                model_revision_or_snapshot=self.binding.model_revision_or_snapshot,
                action=action,
                actor_request_sha256=request.digest(),
                provider_request_sha256=request_sha256,
                provider_response_sha256=response_sha256,
                raw_output_sha256=_sha256_bytes(texts[0].encode("utf-8")),
                usage=usage,
                cost=cost,
                latency_ms=latency_ms,
                timeout_seconds=float(self.binding.request_timeout_seconds),
                error_code=None,
                timed_out=False,
            )
        except ActorClientFailure:
            raise
        except (
            ContractViolation,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._failure(
                category=ActorFailureCategory.SCHEMA_ERROR,
                error_code="RESPONSE_SCHEMA_VIOLATION",
                request_sha256=request_sha256,
                response_sha256=response_sha256,
                http_status=response.status,
            ) from exc

    def complete(self, request: ActorRequest) -> ActorResponse:
        if not isinstance(request, ActorRequest):
            raise ContractViolation("request must be ActorRequest")
        credential = self._environ.get(self.binding.credential_env_ref)
        if not isinstance(credential, str) or not credential:
            raise self._failure(
                category=ActorFailureCategory.CREDENTIAL_MISSING,
                error_code="ARK_API_KEY_MISSING",
                request_sha256=request.digest(),
            )
        request_body = self._request_body(request)
        request_sha256 = _sha256_bytes(request_body)
        started = time.monotonic_ns()
        try:
            response = self._transport.post(
                url=f"{self.binding.base_profile}{self.binding.responses_path}",
                headers={
                    "Authorization": f"Bearer {credential}",
                    "Content-Type": "application/json",
                },
                body=request_body,
                timeout_seconds=float(self.binding.request_timeout_seconds),
            )
        except (TimeoutError, socket.timeout) as exc:
            raise self._failure(
                category=ActorFailureCategory.TIMEOUT,
                error_code="RESPONSES_TIMEOUT",
                request_sha256=request_sha256,
                timed_out=True,
            ) from exc
        except urllib.error.URLError as exc:
            category = (
                ActorFailureCategory.TIMEOUT
                if isinstance(exc.reason, (TimeoutError, socket.timeout))
                else ActorFailureCategory.TRANSPORT_ERROR
            )
            raise self._failure(
                category=category,
                error_code=(
                    "RESPONSES_TIMEOUT"
                    if category is ActorFailureCategory.TIMEOUT
                    else "RESPONSES_TRANSPORT_ERROR"
                ),
                request_sha256=request_sha256,
                timed_out=category is ActorFailureCategory.TIMEOUT,
            ) from exc
        except OSError as exc:
            raise self._failure(
                category=ActorFailureCategory.TRANSPORT_ERROR,
                error_code="RESPONSES_TRANSPORT_ERROR",
                request_sha256=request_sha256,
            ) from exc
        latency_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        response_sha256 = _sha256_bytes(response.body)
        if not 200 <= response.status < 300:
            raise self._failure(
                category=ActorFailureCategory.HTTP_ERROR,
                error_code=self._http_error_code(response.body, response.status),
                request_sha256=request_sha256,
                response_sha256=response_sha256,
                http_status=response.status,
            )
        return self._parse_success(
            request=request,
            request_body=request_body,
            response=response,
            latency_ms=latency_ms,
        )
