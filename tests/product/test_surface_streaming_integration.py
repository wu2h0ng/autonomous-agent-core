"""E1 AgentLoop streaming path integration (M2, test-first).

Frozen source: GC §E1 — AgentLoop consumes the provider stream via
`complete_streaming`; every chunk is a transient frame bound to
(runtime_boot_id, stream_id, turn_id, frame_sequence); `stream_end` (transient)
means the provider stream closed and never carries durable truth.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    PrincipalIdentity,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    SurfaceStreamFrameKind,
    TaskEventType,
)

from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    StreamCursor,
)
from agent_os_core.provider import ProviderRequest, ProviderToolProposal

from apps.api_server.app import AgentOSApplication


def proposal(
    call_id: str,
    capability_id: str,
    arguments: dict[str, object],
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def chat_app(
    root: Path,
    scripted: tuple = (),
    *,
    principal: PrincipalIdentity | None = None,
) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
        principal=principal,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


class StreamingOnlyProvider(DeterministicProvider):
    """Bypass detector: the loop must use complete_streaming; the
    non-streaming complete() path fails this provider and therefore the test.

    The streaming implementation deliberately never delegates to complete()."""

    def complete(self, request: ProviderRequest) -> Any:
        raise RuntimeError("non-streaming complete() must not be used by AgentLoop")

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Any = None,
        on_reasoning_delta: Any = None,
    ) -> Any:
        self.requests.append(request)
        response = self._response(request)
        if on_text_delta is not None and response.text:
            for offset in range(0, len(response.text), 4):
                on_text_delta(response.text[offset : offset + 4])
        return response


class ReasoningProvider(DeterministicProvider):
    """Emits transient reasoning (on_reasoning_delta) plus the answer text."""

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Any = None,
        on_reasoning_delta: Any = None,
    ) -> Any:
        response = super().complete_streaming(request, on_text_delta=on_text_delta)
        if on_reasoning_delta is not None:
            on_reasoning_delta("secret-reasoning")
        return response


def _client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _begin_turn(
    app: AgentOSApplication,
    session_id: str,
    text: str,
    *,
    key: str,
    binding: SurfaceStreamBinding,
) -> SurfaceBeginTurnCommand:
    return SurfaceBeginTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(),
        session_id=session_id,
        text=text,
        stream=binding,
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _payload(event: Any) -> dict[str, Any]:
    return json.loads(event.payload_json)


def _wait_for_completion(
    app: AgentOSApplication, task_id: str, turn_id: str, timeout: float = 5.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in app.store.read(task_id):
            if event.event_type is not TaskEventType.SESSION_TURN_COMPLETED:
                continue
            payload = _payload(event)
            if payload.get("turn_id") == turn_id:
                return payload
        time.sleep(0.01)
    raise AssertionError(f"turn {turn_id} did not complete within {timeout}s")


def _frames_until_stream_end(
    app: AgentOSApplication,
    session_id: str,
    stream_id: str,
    turn_id: str,
    timeout: float = 5.0,
) -> list[Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frames = app.stream_registry.read(
            session_id, StreamCursor(app.runtime_boot_id, stream_id, 0)
        )
        if any(f.kind is SurfaceStreamFrameKind.STREAM_END for f in frames):
            return frames
        time.sleep(0.01)
    raise AssertionError(f"stream_end for {turn_id} was never published")


class TestStreamingFrames:
    def test_begin_turn_publishes_chunk_frames_and_stream_end(
        self, tmp_path: Path
    ) -> None:
        app = chat_app(tmp_path, scripted=(("streamed reply", ()),))
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        response = app.surface.begin_turn(
            _begin_turn(app, session.session_id, "hello", key="key-1", binding=binding)
        )
        _wait_for_completion(app, session.task_id, response.turn_id)
        frames = _frames_until_stream_end(
            app, session.session_id, stream_id, response.turn_id
        )

        chunks = [f for f in frames if f.kind is SurfaceStreamFrameKind.CHUNK]
        ends = [f for f in frames if f.kind is SurfaceStreamFrameKind.STREAM_END]
        gaps = [f for f in frames if f.kind is SurfaceStreamFrameKind.GAP]
        assert gaps == []
        assert "".join(f.payload["delta"] for f in chunks) == "streamed reply"
        assert len(ends) == 1
        assert frames[-1] is ends[0]
        for frame in frames:
            assert frame.runtime_boot_id == app.runtime_boot_id
            assert frame.stream_id == stream_id
            assert frame.turn_id == response.turn_id
        sequences = [f.frame_sequence for f in frames]
        assert sequences == list(range(1, len(frames) + 1))

    def test_loop_must_use_streaming_path(self, tmp_path: Path) -> None:
        app = chat_app(tmp_path)
        app.provider = StreamingOnlyProvider(
            scripted=(("only via streaming", ()),),
            invocation_binding=app.provider.invocation_binding,
        )
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        response = app.surface.begin_turn(
            _begin_turn(app, session.session_id, "hello", key="key-1", binding=binding)
        )
        completed = _wait_for_completion(app, session.task_id, response.turn_id)
        assert completed["stop_reason"] == "completed"
        frames = _frames_until_stream_end(
            app, session.session_id, stream_id, response.turn_id
        )
        chunks = [f for f in frames if f.kind is SurfaceStreamFrameKind.CHUNK]
        assert "".join(f.payload["delta"] for f in chunks) == "only via streaming"

    def test_chunk_frames_are_not_durable_task_events(self, tmp_path: Path) -> None:
        app = chat_app(tmp_path, scripted=(("transient only", ()),))
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        response = app.surface.begin_turn(
            _begin_turn(app, session.session_id, "hello", key="key-1", binding=binding)
        )
        _wait_for_completion(app, session.task_id, response.turn_id)
        frames = _frames_until_stream_end(
            app, session.session_id, stream_id, response.turn_id
        )
        assert len(frames) > 0
        # The durable stream carries only typed turn boundary events; no chunk
        # or stream_end payload may appear as a durable Task event.
        for event in app.store.read(session.task_id):
            payload = _payload(event)
            assert "delta" not in payload
            assert payload.get("frame_sequence") is None

    def test_reasoning_frames_are_not_durable_task_events(self, tmp_path: Path) -> None:
        app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
        app.provider = ReasoningProvider(
            scripted=(("visible answer", ()),),
            invocation_binding=app.provider.invocation_binding,
        )
        app.provider_configured = True
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        response = app.surface.begin_turn(
            _begin_turn(app, session.session_id, "hello", key="key-r", binding=binding)
        )
        _wait_for_completion(app, session.task_id, response.turn_id)
        frames = _frames_until_stream_end(
            app, session.session_id, stream_id, response.turn_id
        )
        # reasoning is displayed...
        assert any(f.kind is SurfaceStreamFrameKind.REASONING for f in frames)
        assert any(f.kind is SurfaceStreamFrameKind.CHUNK for f in frames)
        # ...but never durable.
        for event in app.store.read(session.task_id):
            blob = json.dumps(_payload(event))
            assert "secret-reasoning" not in blob
            assert '"reasoning"' not in blob
