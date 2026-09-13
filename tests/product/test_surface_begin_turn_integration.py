"""E1 begin-turn integration over the real composition root (M2, test-first).

Frozen source: GC §E1 turn-start protocol, exercised end to end through
`AgentOSApplication` + durable Task event stream (SESSION_TURN_STARTED /
SESSION_TURN_COMPLETED are the durable turn boundary; the transient stream is
bound in the session-stream registry).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ApprovalDisposition,
    PrincipalIdentity,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    TaskEventType,
)

from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    SurfaceTurnInProgress,
)
from agent_os_core.provider import ProviderToolProposal

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
    expected_event_sequence: int | None = None,
) -> SurfaceBeginTurnCommand:
    return SurfaceBeginTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(),
        session_id=session_id,
        text=text,
        stream=binding,
        expected_event_sequence=(
            expected_event_sequence
            if expected_event_sequence is not None
            else app.surface_current_sequence(
                app.surface_task_for_session(session_id)
            )
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _payload(event: Any) -> dict[str, Any]:
    return json.loads(event.payload_json)


def _turn_events(app: AgentOSApplication, task_id: str, turn_id: str) -> dict[str, int]:
    counts = {"started": 0, "completed": 0}
    for event in app.store.read(task_id):
        payload = _payload(event)
        if payload.get("turn_id") != turn_id:
            continue
        if event.event_type is TaskEventType.SESSION_TURN_STARTED:
            counts["started"] += 1
        elif event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
            counts["completed"] += 1
    return counts


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


class TestBeginTurnIntegration:
    def test_begin_turn_returns_authoritative_ids_and_durable_start(
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

        assert response.turn_id
        assert response.stream_id == stream_id
        counts = _turn_events(app, session.task_id, response.turn_id)
        assert counts["started"] == 1
        completed = _wait_for_completion(app, session.task_id, response.turn_id)
        assert completed["stop_reason"] == "completed"
        assert app.surface_has_uncommitted_turn(session.session_id) is False

    def test_begin_turn_replay_same_key_returns_same_turn_without_restart(
        self, tmp_path: Path
    ) -> None:
        app = chat_app(tmp_path, scripted=(("streamed reply", ()),))
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        at = datetime.now(timezone.utc)
        pinned = app.surface_current_sequence(
            app.surface_task_for_session(session.session_id)
        )
        first = app.surface.begin_turn(
            _begin_turn(
                app,
                session.session_id,
                "hello",
                key="key-1",
                binding=binding,
                expected_event_sequence=pinned,
            ).model_copy(update={"requested_at": at})
        )
        _wait_for_completion(app, session.task_id, first.turn_id)
        replay = app.surface.begin_turn(
            _begin_turn(
                app,
                session.session_id,
                "hello",
                key="key-1",
                binding=binding,
                expected_event_sequence=pinned,
            ).model_copy(update={"requested_at": at})
        )
        assert replay == first
        counts = _turn_events(app, session.task_id, first.turn_id)
        assert counts["started"] == 1
        assert counts["completed"] == 1

    def test_begin_turn_unknown_stream_fails_and_never_starts_turn(
        self, tmp_path: Path
    ) -> None:
        app = chat_app(tmp_path, scripted=(("must not run", ()),))
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        app.subscribe_stream(session.session_id)
        events_before = len(app.store.read(session.task_id))
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id="never-subscribed"
        )
        from agent_os_core import SurfaceStreamGone

        with pytest.raises(SurfaceStreamGone):
            app.surface.begin_turn(
                _begin_turn(app, session.session_id, "hello", key="key-1", binding=binding)
            )
        assert len(app.store.read(session.task_id)) == events_before

    def test_uncommitted_approval_paused_turn_blocks_second_begin(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
        app = chat_app(
            tmp_path,
            scripted=(
                (
                    "",
                    (
                        proposal(
                            "call-edit",
                            "workspace.edit",
                            {
                                "path": "fixture.txt",
                                "old_string": "stable\n",
                                "new_string": "fixed\n",
                            },
                        ),
                    ),
                ),
                ("edited reply", ()),
            ),
        )
        session, loop = app.open_chat_session("edit", DeferredApprovalGateway())
        waiting = loop.run_turn(session, "edit fixture")
        assert waiting.stop_reason == "approval_required"
        assert app.surface_has_uncommitted_turn(session.session_id) is True

        stream_id = app.subscribe_stream(session.session_id)
        binding = SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        )
        with pytest.raises(SurfaceTurnInProgress):
            app.surface.begin_turn(
                _begin_turn(app, session.session_id, "second", key="key-2", binding=binding)
            )

        projected = app.tasks.project_session(session.task_id, session.session_id)
        pending = projected.pending_continuation
        assert pending is not None
        app.decide_session_approval(
            session.session_id,
            action_digest=pending.action.action_digest(),
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )
        assert app.surface_has_uncommitted_turn(session.session_id) is False

        second = app.surface.begin_turn(
            _begin_turn(app, session.session_id, "second", key="key-3", binding=binding)
        )
        assert second.turn_id
        assert second.turn_id != waiting.turn_id
        completed = _wait_for_completion(app, session.task_id, second.turn_id)
        assert completed["stop_reason"] == "completed"

    def test_stale_generation_stream_fails_stream_gone(self, tmp_path: Path) -> None:
        app = chat_app(tmp_path, scripted=(("must not run", ()),))
        session, _ = app.open_chat_session("hi", DeferredApprovalGateway())
        stream_id = app.subscribe_stream(session.session_id)
        events_before = len(app.store.read(session.task_id))
        binding = SurfaceStreamBinding(runtime_boot_id="boot-stale", stream_id=stream_id)
        from agent_os_core import SurfaceStreamGone

        with pytest.raises(SurfaceStreamGone):
            app.surface.begin_turn(
                _begin_turn(app, session.session_id, "hello", key="key-1", binding=binding)
            )
        assert len(app.store.read(session.task_id)) == events_before
