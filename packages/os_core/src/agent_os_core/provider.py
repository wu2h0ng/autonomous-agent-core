from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from uuid import uuid4

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderErrorCode,
    ProviderFailure,
    ProviderDecisionRequest,
    ProviderInvocationBinding,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
    content_digest,
)


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
    ) -> None:
        self.text = text
        self.tool_proposals = tool_proposals
        self.requests: list[ProviderRequest] = []
        self.decision_requests: list[ProviderDecisionRequest] = []
        self._invocation_binding = invocation_binding

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        if self._invocation_binding is None:
            return super().invocation_binding
        return self._invocation_binding

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return self._response(request)

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
        return ProviderResponse(
            response_id=f"response-{uuid4()}",
            request_id=request.request_id,
            text=self.text,
            tool_proposals=self.tool_proposals,
            usage=ProviderUsage(
                input_tokens=sum(
                    len(message.content.split()) for message in request.messages
                ),
                output_tokens=len(self.text.split()),
                total_tokens=sum(
                    len(message.content.split()) for message in request.messages
                )
                + len(self.text.split()),
                estimated_cost_usd=Decimal("0"),
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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.credential = credential
        self.credentials = credentials or EnvCredentialBroker()
        self.timeout_seconds = timeout_seconds
        self.temperature = (
            temperature
            if temperature is not None
            else float(
                os.environ.get(
                    "AGENT_OS_PROVIDER_TEMPERATURE",
                    os.environ.get("OPENAI_TEMPERATURE", "1.0"),
                )
            )
        )
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
                provider_profile.model_id != self.model
                or provider_profile.provider_id != credential.provider_id
                or provider_profile.credential_ref_id != credential.credential_ref_id
                or provider_profile.endpoint_class != "openai-compatible"
            ):
                raise ValueError(
                    "provider profile does not match OpenAI-compatible invocation"
                )
            self._invocation_binding = ProviderInvocationBinding(
                provider_profile=provider_profile,
                provider_id=credential.provider_id,
                endpoint_class="openai-compatible",
                credential_ref_id=credential.credential_ref_id,
                credential_ref_digest=content_digest(credential),
                max_context_tokens=provider_profile.max_context_tokens,
                adapter_kind="openai-compatible",
                transport="https-json",
                base_url=self.base_url,
                endpoint_path="/chat/completions",
                model_id=self.model,
                request_timeout_seconds=self.timeout_seconds,
                temperature=Decimal(str(self.temperature)),
            )

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        if self._invocation_binding is None:
            return super().invocation_binding
        return self._invocation_binding

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        return self._invoke(
            request, allowed_capability_ids=request.allowed_capability_ids
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
    ) -> ProviderResponse | ProviderFailure:
        try:
            secret = self.credentials.resolve(self.credential)
            body = {
                "model": self.model,
                "messages": [
                    {"role": message.role.value.lower(), "content": message.content}
                    for message in request.messages
                ],
                "temperature": self.temperature,
            }
            if allowed_capability_ids:
                body["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": capability_id.replace(".", "__"),
                            "description": f"Invoke typed capability {capability_id}",
                            "parameters": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                    }
                    for capability_id in allowed_capability_ids
                ]
                body["tool_choice"] = "auto"
            encoded = json.dumps(body).encode("utf-8")
            http_request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=encoded,
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with self._opener(
                http_request, timeout=min(self.timeout_seconds, request.timeout_seconds)
            ) as response:  # type: ignore[call-arg]
                payload = json.loads(response.read().decode("utf-8"))
            choice = payload["choices"][0]
            message = choice["message"]
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
                    estimated_cost_usd=Decimal("0"),
                ),
                finish_reason=str(choice.get("finish_reason", "stop")),
                received_at=datetime.now(timezone.utc),
                invocation_binding_digest=(
                    self._invocation_binding.digest()
                    if self._invocation_binding is not None
                    else None
                ),
            )
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
