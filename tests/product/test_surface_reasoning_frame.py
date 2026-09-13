"""Transient REASONING frame: contract invariants + provider capture.

See ADR REASONING-TRANSIENT-FRAME. Reasoning is display-only: it must reach
the reasoning callback, never the response text or the durable transcript.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    SurfaceStreamFrame,
    SurfaceStreamFrameKind,
)
from agent_os_core import EnvCredentialBroker, OpenAICompatibleProvider


def test_reasoning_frame_requires_turn_binding() -> None:
    frame = SurfaceStreamFrame(
        kind=SurfaceStreamFrameKind.REASONING,
        runtime_boot_id="boot:1",
        stream_id="stream:1",
        turn_id="turn:1",
        frame_sequence=1,
        payload={"delta": "thinking"},
    )
    assert frame.kind is SurfaceStreamFrameKind.REASONING
    with pytest.raises(ValueError):
        SurfaceStreamFrame(
            kind=SurfaceStreamFrameKind.REASONING,
            runtime_boot_id="boot:1",
            stream_id="stream:1",
            frame_sequence=1,
            payload={"delta": "thinking"},
        )


class _FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


def _request() -> ProviderRequest:
    now = datetime.now(timezone.utc)
    return ProviderRequest(
        request_id="req:1",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="profile:1",
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hi"),),
        timeout_seconds=5,
        created_at=now,
    )


def _provider() -> OpenAICompatibleProvider:
    now = datetime.now(timezone.utc)
    ref = CredentialRef(
        credential_ref_id="credential:1",
        owner_principal_id="p:1",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        provider_id="openai-compatible",
        resolver_key="UNUSED_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    return OpenAICompatibleProvider(
        base_url="https://example.invalid",
        model="deepseek-reasoner",
        credential=ref,
        credentials=EnvCredentialBroker(),
    )


def test_provider_reasoning_is_separate_from_response_text() -> None:
    response = _FakeResponse(
        [
            b'data: {"id":"c1","choices":[{"delta":{"reasoning_content":"think A"},"finish_reason":null}]}\n',
            b'data: {"id":"c1","choices":[{"delta":{"reasoning_content":"think B"},"finish_reason":null}]}\n',
            b'data: {"id":"c1","choices":[{"delta":{"content":"42"},"finish_reason":"stop"}]}\n',
            b"data: [DONE]\n",
        ]
    )
    reasoning: list[str] = []
    text: list[str] = []
    result = _provider()._parse_sse_stream(  # noqa: SLF001 - targeted unit
        response,
        request=_request(),
        on_text_delta=text.append,
        on_reasoning_delta=reasoning.append,
    )
    assert reasoning == ["think A", "think B"]
    assert text == ["42"]
    # Reasoning must never leak into the durable response text.
    assert getattr(result, "text", None) == "42"
