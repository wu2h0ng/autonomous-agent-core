"""M1 S4: deterministic context compaction, recorded durably as an event."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ProviderMessage,
    ProviderMessageRole,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import AgentLoopConfig, DeferredApprovalGateway, DeterministicProvider
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _msg(
    role: ProviderMessageRole, content: str, *, tool_call_id: str | None = None
) -> ProviderMessage:
    return ProviderMessage(role=role, content=content, tool_call_id=tool_call_id)


def _todo_script() -> tuple:
    def proposal(call_id: str):
        return ProviderToolProposal(
            proposal_id=call_id,
            capability_id="session.todo_write",
            arguments_json=json.dumps(
                {"todos": [{"id": "1", "content": "x", "status": "pending"}]}
            ),
        )

    return (
        ("", (proposal("c1"),)),
        ("done 1", ()),
        ("", (proposal("c2"),)),
        ("done 2", ()),
    )


def _wait_for(predicate, description: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"{description} did not occur within {timeout}s")


def _run_turn(app: AgentOSApplication, session_id: str, text: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    completed_before = len(
        [
            e
            for e in app.store.read(task_id)
            if e.event_type is TaskEventType.SESSION_TURN_COMPLETED
        ]
    )
    stream_id = app.subscribe_stream(session_id)
    app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text=text,
            stream=SurfaceStreamBinding(
                runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
            ),
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"turn:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )

    def _done():
        completed = [
            e
            for e in app.store.read(task_id)
            if e.event_type is TaskEventType.SESSION_TURN_COMPLETED
        ]
        return completed if len(completed) > completed_before else None

    _wait_for(_done, "turn completion")


def _set_workspace_mode(app: AgentOSApplication, session_id: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    app.surface.set_permission_mode(
        SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            mode="ACCEPT_IN_WORKSPACE",
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"mode:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _compaction_events(app: AgentOSApplication, task_id: str) -> list[dict]:
    return [
        json.loads(event.payload_json)
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.SESSION_CONTEXT_COMPACTED
    ]


def _open(root: Path, *, max_context_chars: int):
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=_todo_script(), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    session, loop = app.open_chat_session(
        "hi",
        DeferredApprovalGateway(),
        loop_config=AgentLoopConfig(system_prompt="SYS", max_context_chars=max_context_chars),
    )
    return app, session, loop


# ---------------------------------------------------------------------------
# Unit: the compaction algorithm
# ---------------------------------------------------------------------------


def test_compaction_drops_oldest_turn_and_keeps_the_active_request(tmp_path: Path) -> None:
    _, _, loop = _open(tmp_path, max_context_chars=1000)
    loop._history = [
        _msg(ProviderMessageRole.SYSTEM, "S"),
        _msg(ProviderMessageRole.USER, "u1" + "x" * 60),
        _msg(ProviderMessageRole.ASSISTANT, "a1"),
        _msg(ProviderMessageRole.USER, "u2" + "y" * 60),
        _msg(ProviderMessageRole.ASSISTANT, "a2"),
        _msg(ProviderMessageRole.USER, "u3" + "z" * 60),
    ]
    loop._config = AgentLoopConfig(system_prompt="S", max_context_chars=120)
    kept, payload = loop._compact_history()
    assert payload is not None
    assert int(payload["dropped_messages"]) >= 1  # type: ignore[arg-type]
    assert kept[0].role is ProviderMessageRole.SYSTEM
    # the active (last) USER request survives
    assert kept[-1].content == "u3" + "z" * 60
    assert len(str(payload["retained_digest"])) == 64


def test_compaction_never_splits_a_tool_group(tmp_path: Path) -> None:
    _, _, loop = _open(tmp_path, max_context_chars=1000)
    loop._history = [
        _msg(ProviderMessageRole.SYSTEM, "S"),
        _msg(ProviderMessageRole.USER, "u1" + "x" * 40),
        _msg(ProviderMessageRole.ASSISTANT, "a1" + "y" * 40),
        _msg(ProviderMessageRole.TOOL, "t1" + "z" * 40, tool_call_id="call-1"),
        _msg(ProviderMessageRole.USER, "u2"),
    ]
    loop._config = AgentLoopConfig(system_prompt="S", max_context_chars=60)
    kept, payload = loop._compact_history()
    assert payload is not None
    # no orphan TOOL message without its preceding turn
    assert kept[-1].content == "u2"


def test_no_compaction_when_within_budget(tmp_path: Path) -> None:
    _, _, loop = _open(tmp_path, max_context_chars=1_000_000)
    kept, payload = loop._compact_history()
    assert payload is None
    assert kept == loop._history


# ---------------------------------------------------------------------------
# Integration: the event is recorded through the real turn path
# ---------------------------------------------------------------------------


def test_single_turn_records_no_compaction_event(tmp_path: Path) -> None:
    # The active request is never dropped, so a single over-budget turn is NOT a
    # compaction and must not be recorded as one (evidence honesty).
    app, session, _loop = _open(tmp_path, max_context_chars=1)
    _set_workspace_mode(app, session.session_id)
    _run_turn(app, session.session_id, "one")
    assert _compaction_events(app, session.task_id) == []


def test_compaction_digest_is_deterministic(tmp_path: Path) -> None:
    def digest() -> str:
        _, _, loop = _open(tmp_path, max_context_chars=1000)
        loop._history = [
            _msg(ProviderMessageRole.SYSTEM, "S"),
            _msg(ProviderMessageRole.USER, "u1" + "x" * 80),
            _msg(ProviderMessageRole.ASSISTANT, "a1"),
            _msg(ProviderMessageRole.USER, "u2" + "y" * 80),
        ]
        loop._config = AgentLoopConfig(system_prompt="S", max_context_chars=120)
        _, payload = loop._compact_history()
        assert payload is not None
        return str(payload["retained_digest"])

    first = digest()
    second = digest()
    assert first == second
    assert len(first) == 64


def test_maybe_record_compaction_writes_exactly_one_event(tmp_path: Path) -> None:
    app, session, loop = _open(tmp_path, max_context_chars=1_000_000)
    payload = {
        "chars_before": 100,
        "chars_after": 40,
        "dropped_messages": 2,
        "kept_from_index": 3,
        "retained_digest": "a" * 64,
    }
    loop._maybe_record_compaction(session, payload)
    loop._maybe_record_compaction(session, payload)
    assert _compaction_events(app, session.task_id) == [payload]


def test_projection_ignores_a_recorded_compaction(tmp_path: Path) -> None:
    # Replay safety: a durable SESSION_CONTEXT_COMPACTED event must not break the
    # session projection (it carries no projected state).
    app, session, loop = _open(tmp_path, max_context_chars=1_000_000)
    loop._maybe_record_compaction(
        session,
        {
            "chars_before": 100,
            "chars_after": 40,
            "dropped_messages": 2,
            "kept_from_index": 3,
            "retained_digest": "b" * 64,
        },
    )
    projected = app.tasks.project_session(session.task_id, session.session_id)
    assert projected.ref.session_id == session.session_id


def test_two_distinct_compactions_are_both_recorded(tmp_path: Path) -> None:
    app, session, loop = _open(tmp_path, max_context_chars=1_000_000)
    base = {"kept_from_index": 3, "dropped_messages": 2, "chars_before": 100}
    loop._maybe_record_compaction(
        session, {**base, "chars_after": 40, "retained_digest": "a" * 64}
    )
    loop._maybe_record_compaction(
        session, {**base, "chars_after": 45, "retained_digest": "c" * 64}
    )
    assert len(_compaction_events(app, session.task_id)) == 2


def test_no_compaction_event_for_a_large_budget(tmp_path: Path) -> None:
    app, session, _loop = _open(tmp_path, max_context_chars=1_000_000)
    _set_workspace_mode(app, session.session_id)
    _run_turn(app, session.session_id, "one")
    assert _compaction_events(app, session.task_id) == []
