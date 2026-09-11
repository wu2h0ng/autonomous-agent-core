"""E3 cost-honesty contract (M2, test-first).

Frozen source: GC/E3 — token counts are accurate; cost is UNKNOWN unless a
versioned pricing source exists; zero cost without a pricing source is
forbidden; legacy v1 usage payloads (estimated_cost_usd present, no
cost_status) decode to UNKNOWN + None without rewriting stored events.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderResponse,
    ProviderUsage,
    SURFACE_PROTOCOL_VERSION,
)
from agent_os_core import (
    DeterministicProvider,
    EnvCredentialBroker,
    OpenAICompatibleProvider,
)
from agent_os_core.provider import ProviderRequest
from pydantic import ValidationError


def _usage(**overrides: Any) -> ProviderUsage:
    base: dict[str, Any] = {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }
    base.update(overrides)
    return ProviderUsage(**base)


def test_usage_defaults_to_unknown_with_no_cost() -> None:
    usage = _usage()
    assert usage.cost_status == "UNKNOWN"
    assert usage.estimated_cost_usd is None
    assert usage.pricing_source_ref is None
    assert usage.schema_version == "2.0"


def test_known_requires_amount_and_pricing_source() -> None:
    with pytest.raises(ValidationError):
        _usage(cost_status="KNOWN")
    with pytest.raises(ValidationError):
        _usage(
            cost_status="KNOWN",
            estimated_cost_usd="0.01",
            pricing_source_ref=None,
        )


def test_known_zero_allowed_only_with_pricing_source() -> None:
    # A genuinely free model may be KNOWN + 0, but only with a source.
    with pytest.raises(ValidationError):
        _usage(cost_status="KNOWN", estimated_cost_usd="0")
    usage = _usage(
        cost_status="KNOWN",
        estimated_cost_usd="0",
        pricing_source_ref="pricing:free-model@v1",
    )
    assert usage.estimated_cost_usd is not None
    assert usage.estimated_cost_usd == 0


def test_unknown_forbids_amount_and_source_ref() -> None:
    with pytest.raises(ValidationError):
        _usage(cost_status="UNKNOWN", estimated_cost_usd="0.01")
    with pytest.raises(ValidationError):
        _usage(cost_status="UNKNOWN", pricing_source_ref="pricing:x@v1")


def test_legacy_v1_zero_payload_decodes_unknown_none() -> None:
    legacy = {
        "schema_version": "1.0",
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
        "estimated_cost_usd": "0",
    }
    usage = ProviderUsage.model_validate(legacy)
    assert usage.cost_status == "UNKNOWN"
    assert usage.estimated_cost_usd is None
    assert usage.pricing_source_ref is None
    # Legacy amounts carry no pricing source: they are never trusted.
    legacy_positive = dict(legacy, estimated_cost_usd="12.34")
    usage_positive = ProviderUsage.model_validate(legacy_positive)
    assert usage_positive.cost_status == "UNKNOWN"
    assert usage_positive.estimated_cost_usd is None


def test_v2_known_roundtrip_preserves_cost() -> None:
    usage = _usage(
        cost_status="KNOWN",
        estimated_cost_usd="0.42",
        pricing_source_ref="pricing:openai@gpt-4o-2024-08-06",
    )
    payload = json.loads(usage.model_dump_json())
    reparsed = ProviderUsage.model_validate(payload)
    assert reparsed.cost_status == "KNOWN"
    assert reparsed.estimated_cost_usd is not None
    assert reparsed.estimated_cost_usd == Decimal("0.42")
    assert reparsed.pricing_source_ref == "pricing:openai@gpt-4o-2024-08-06"


def test_deterministic_provider_marks_cost_unknown() -> None:
    provider = DeterministicProvider(text="hello")
    request = _request()
    response = provider.complete(request)
    assert isinstance(response, ProviderResponse)
    assert response.usage.cost_status == "UNKNOWN"
    assert response.usage.estimated_cost_usd is None
    streamed = provider.complete_streaming(request)
    assert isinstance(streamed, ProviderResponse)
    assert streamed.usage.cost_status == "UNKNOWN"
    assert streamed.usage.estimated_cost_usd is None


def test_openai_provider_tokens_accurate_cost_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_OS_TEST_STREAM_SECRET", "stream-secret")
    payload = {
        "id": "cmpl-cost",
        "choices": [
            {
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }

    class _JsonResponse:
        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self) -> "_JsonResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def _opener(_request: object, *, timeout: int) -> _JsonResponse:
        del timeout
        return _JsonResponse()

    provider = OpenAICompatibleProvider(
        base_url="http://fake.local",
        model="test-model",
        credential=_credential("credential-cost"),
        credentials=EnvCredentialBroker(),
        opener=_opener,
    )
    response = provider.complete(_request())
    assert isinstance(response, ProviderResponse)
    # Tokens come from the provider payload and stay exact.
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.total_tokens == 18
    # Cost has no pricing source: honest UNKNOWN, never a pseudo-zero.
    assert response.usage.cost_status == "UNKNOWN"
    assert response.usage.estimated_cost_usd is None


def test_openai_sse_usage_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OS_TEST_STREAM_SECRET", "stream-secret")
    lines = [
        b'data: {"id":"resp-cost","choices":[{"delta":{"content":"hi"}}]}\n',
        b'data: {"id":"resp-cost","choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b"data: [DONE]\n",
    ]

    class _SseStream:
        def __init__(self) -> None:
            self._lines = iter(lines)

        def readline(self) -> bytes:
            try:
                return next(self._lines)
            except StopIteration:
                return b""

        def __enter__(self) -> "_SseStream":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def _opener(_request: object, *, timeout: int) -> _SseStream:
        del timeout
        return _SseStream()

    provider = OpenAICompatibleProvider(
        base_url="http://fake.local",
        model="test-model",
        credential=_credential("credential-cost-sse"),
        credentials=EnvCredentialBroker(),
        opener=_opener,
    )
    response = provider.complete_streaming(_request(), on_text_delta=None)
    assert isinstance(response, ProviderResponse)
    assert response.usage.cost_status == "UNKNOWN"
    assert response.usage.estimated_cost_usd is None


def test_surface_protocol_bumped_for_usage_v2() -> None:
    assert SURFACE_PROTOCOL_VERSION == "1.1"


def _credential(credential_id: str) -> CredentialRef:
    now = datetime.now(timezone.utc)
    return CredentialRef(
        credential_ref_id=credential_id,
        owner_principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        provider_id="openai-compatible",
        resolver_key="AGENT_OS_TEST_STREAM_SECRET",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _request() -> ProviderRequest:
    from agent_os_contracts import ProviderMessage, ProviderMessageRole

    return ProviderRequest(
        request_id="request-cost",
        task_id="task-cost",
        run_id="run-cost",
        provider_profile_id="profile-cost",
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hello"),),
        allowed_capability_ids=(),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )
