"""Single-session stop / graceful shutdown for surface chat sessions.

Defect (a) of the 2026-09-18 failure-path rounds: a surface session's Run is
durable from `open_session` at QUEUED, and the surface turn path never moves it
to RUNNING, so `noem session pause` answered
`cannot move run from QUEUED to PAUSED` (409) - the operator could not stop a
session at all, and an in-flight turn could not be stopped at any point.

These tests pin both halves of the fix:

* the `QUEUED -> PAUSED` edge, plus the transitions that must stay closed;
* the cooperative mid-turn stop: once the operator's pause is durable, the loop
  ends the turn truthfully (`stop_reason=stopped_by_operator`) without starting
  another provider call or dispatching another capability, and the session stays
  resumable.

They are also bypass detectors: restoring the old transition set or removing the
loop's stop checks turns them red.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    RunStatus,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceSessionStatus,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBinding,
    TaskEventDraft,
    TaskEventType,
)
from agent_os_core import (
    ConcurrentWriteError,
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SurfaceScopeError,
    SurfaceSequenceConflict,
)
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication

STOP_REASON = "stopped_by_operator"


class _Gate:
    """A one-shot hold the test opens after it has issued the pause."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()


class _GatedProvider(DeterministicProvider):
    """Deterministic provider that holds selected calls open until released."""

    def __init__(self, gate: _Gate, hold_calls: tuple[int, ...], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._gate = gate
        self._hold_calls = hold_calls
        self.calls = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1
        if self.calls in self._hold_calls:
            self._gate.entered.set()
            if not self._gate.release.wait(timeout=10):
                raise AssertionError("provider gate was never released")
        return super().complete(request)


class _GatedConnector:
    """Delegating capability port that can hold one dispatch open."""

    def __init__(self, inner: Any, gate: _Gate, capability_id: str) -> None:
        self._inner = inner
        self._gate = gate
        self._capability_id = capability_id

    def execute(self, action: Any) -> Any:
        if action.capability_id == self._capability_id:
            self._gate.entered.set()
            if not self._gate.release.wait(timeout=10):
                raise AssertionError("connector gate was never released")
        return self._inner.execute(action)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


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


def chat_app(root: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _mode_command(
    app: AgentOSApplication,
    session_id: str,
    mode: str,
    *,
    key: str = "idem:mode:1",
) -> SurfaceSetPermissionModeCommand:
    return SurfaceSetPermissionModeCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        mode=mode,  # type: ignore[arg-type]
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _pause_command(
    app: AgentOSApplication,
    session_id: str,
    *,
    key: str = "idem:pause:1",
) -> SurfaceCorrectionCommand:
    return SurfaceCorrectionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        reason="operator stop",
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _resume_command(
    app: AgentOSApplication,
    session_id: str,
    *,
    key: str = "idem:resume:1",
) -> SurfaceCorrectionCommand:
    return _pause_command(app, session_id, key=key)


def _begin_turn(
    app: AgentOSApplication,
    session_id: str,
    stream_id: str,
    *,
    text: str = "do the work",
    key: str = "idem:turn:1",
) -> SurfaceBeginTurnCommand:
    return SurfaceBeginTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        text=text,
        stream=SurfaceStreamBinding(
            runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
        ),
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _run_status(app: AgentOSApplication, task_id: str) -> RunStatus:
    run = app.tasks.get_task(task_id).run
    assert run is not None
    return run.status


def _turn_completion(
    app: AgentOSApplication,
    task_id: str,
    turn_id: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in app.store.read(task_id):
            if event.event_type is not TaskEventType.SESSION_TURN_COMPLETED:
                continue
            payload = json.loads(event.payload_json)
            if payload.get("turn_id") == turn_id:
                return payload
        time.sleep(0.01)
    raise AssertionError(f"turn {turn_id} did not complete within {timeout}s")


def _event_count(
    app: AgentOSApplication,
    task_id: str,
    event_type: TaskEventType,
) -> int:
    return sum(event.event_type is event_type for event in app.store.read(task_id))


def _tool_replies(app: AgentOSApplication, task_id: str) -> list[str]:
    replies: list[str] = []
    for event in app.store.read(task_id):
        if event.event_type is not TaskEventType.SESSION_MESSAGE_RECORDED:
            continue
        message = json.loads(event.payload_json).get("message") or {}
        if message.get("role") == "TOOL":
            replies.append(str(message.get("content")))
    return replies


# --------------------------------------------------------------------------
# The QUEUED -> PAUSED edge
# --------------------------------------------------------------------------


def test_surface_pause_stops_a_session_whose_run_is_queued(tmp_path: Path) -> None:
    """A surface session's Run is QUEUED; pausing it must work (defect (a))."""

    app = chat_app(tmp_path)
    session, _ = app.open_chat_session("stop me", DeferredApprovalGateway())
    assert _run_status(app, session.task_id) is RunStatus.QUEUED
    assert app.surface.get_session(session.session_id).status is (
        SurfaceSessionStatus.ACTIVE
    )

    paused = app.surface.pause(_pause_command(app, session.session_id))

    assert paused.status is SurfaceSessionStatus.PAUSED
    assert _run_status(app, session.task_id) is RunStatus.PAUSED
    assert _event_count(app, session.task_id, TaskEventType.RUN_PAUSED) == 1
    assert app.surface.get_session(session.session_id).status is (
        SurfaceSessionStatus.PAUSED
    )

    resumed = app.surface.resume(_resume_command(app, session.session_id))
    assert resumed.status is SurfaceSessionStatus.ACTIVE
    assert _run_status(app, session.task_id) is RunStatus.RUNNING

    stream_id = app.subscribe_stream(session.session_id)
    begun = app.surface.begin_turn(
        _begin_turn(app, session.session_id, stream_id, text="second request")
    )
    completed = _turn_completion(app, session.task_id, begun.turn_id)
    assert completed["stop_reason"] == "completed"


def test_paused_session_refuses_a_new_turn_until_resumed(tmp_path: Path) -> None:
    """The stop is binding: a paused session starts no provider work."""

    app = chat_app(tmp_path, scripted=(("must not run", ()),))
    session, _ = app.open_chat_session("stop me", DeferredApprovalGateway())
    app.surface.pause(_pause_command(app, session.session_id))

    stream_id = app.subscribe_stream(session.session_id)
    with pytest.raises(InvalidTransitionError, match="runnable Run"):
        app.surface.begin_turn(
            _begin_turn(app, session.session_id, stream_id, text="too late")
        )

    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_STARTED) == 0


def test_run_transition_table_allows_queued_to_paused_only(tmp_path: Path) -> None:
    """Kernel-level bypass detector for the transition edge.

    Restoring `QUEUED: {RUNNING, CANCELLED}` makes the first call raise; making
    the table permissive makes the refusals stop raising.
    """

    app = chat_app(tmp_path)
    session, _ = app.open_chat_session("transition", DeferredApprovalGateway())
    task_id = session.task_id

    paused = app.tasks.update_run_status(
        task_id, RunStatus.PAUSED, event_type=TaskEventType.RUN_PAUSED
    )
    assert paused.run is not None
    assert paused.run.status is RunStatus.PAUSED

    with pytest.raises(InvalidTransitionError, match="cannot move run"):
        app.tasks.update_run_status(
            task_id, RunStatus.PAUSED, event_type=TaskEventType.RUN_PAUSED
        )

    app.tasks.update_run_status(
        task_id, RunStatus.RUNNING, event_type=TaskEventType.RUN_RESUMED
    )
    with pytest.raises(InvalidTransitionError, match="cannot move run"):
        app.tasks.update_run_status(
            task_id, RunStatus.QUEUED, event_type=TaskEventType.RUN_RESUMED
        )
    app.tasks.update_run_status(
        task_id, RunStatus.CANCELLED, event_type=TaskEventType.RUN_CANCELLED
    )
    with pytest.raises(InvalidTransitionError, match="cannot move run"):
        app.tasks.update_run_status(
            task_id, RunStatus.PAUSED, event_type=TaskEventType.RUN_PAUSED
        )


def test_pause_keeps_its_scope_and_sequence_failure_paths(tmp_path: Path) -> None:
    """The stop must not become a way around scope, sequence or contract checks."""

    app = chat_app(tmp_path)
    session, _ = app.open_chat_session("guarded", DeferredApprovalGateway())
    command = _pause_command(app, session.session_id)

    foreign = command.model_copy(
        update={
            "client": _client_ref().model_copy(update={"tenant_id": "tenant:other"}),
            "idempotency_key": "idem:pause:foreign",
        }
    )
    with pytest.raises(SurfaceScopeError):
        app.surface.pause(foreign)

    stale = command.model_copy(
        update={
            "expected_event_sequence": command.expected_event_sequence + 3,
            "idempotency_key": "idem:pause:stale",
        }
    )
    with pytest.raises(SurfaceSequenceConflict):
        app.surface.pause(stale)

    assert _run_status(app, session.task_id) is RunStatus.QUEUED
    assert _event_count(app, session.task_id, TaskEventType.RUN_PAUSED) == 0


def test_pause_survives_a_lost_append_race_with_the_turn_it_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-flight turn appends to the same optimistic stream the pause
    writes to, so a pause can lose the sequence race against the very turn it is
    stopping. The operator command must absorb that bounded conflict."""

    app = chat_app(tmp_path)
    session, _ = app.open_chat_session("racy", DeferredApprovalGateway())
    original_append = app.store.append
    conflicts = {"count": 0}

    def losing_append(
        task_id: str,
        *,
        expected_sequence: int,
        drafts: tuple[TaskEventDraft, ...],
    ) -> Any:
        if any(draft.event_type is TaskEventType.RUN_PAUSED for draft in drafts):
            if conflicts["count"] == 0:
                conflicts["count"] += 1
                raise ConcurrentWriteError("injected concurrent append")
        return original_append(
            task_id, expected_sequence=expected_sequence, drafts=drafts
        )

    monkeypatch.setattr(app.store, "append", losing_append)

    paused = app.surface.pause(_pause_command(app, session.session_id))

    assert conflicts["count"] == 1
    assert paused.status is SurfaceSessionStatus.PAUSED
    assert _run_status(app, session.task_id) is RunStatus.PAUSED
    assert _event_count(app, session.task_id, TaskEventType.RUN_PAUSED) == 1


# --------------------------------------------------------------------------
# The in-flight turn
# --------------------------------------------------------------------------


def test_pause_during_a_provider_call_stops_before_any_dispatch(
    tmp_path: Path,
) -> None:
    """A stop that lands while the provider is thinking is honoured before the
    model's proposals can run: no receipt, no workspace effect, one call only."""

    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    gate = _Gate()
    app = chat_app(tmp_path)
    app.provider = _GatedProvider(
        gate,
        hold_calls=(1,),
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
                            "new_string": "edited\n",
                        },
                    ),
                ),
            ),
            ("must not be reached", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    session, _ = app.open_chat_session("edit fixture", DeferredApprovalGateway())
    stream_id = app.subscribe_stream(session.session_id)
    begun = app.surface.begin_turn(
        _begin_turn(app, session.session_id, stream_id, text="edit the fixture")
    )

    assert gate.entered.wait(timeout=10)
    paused = app.surface.pause(_pause_command(app, session.session_id))
    assert paused.status is SurfaceSessionStatus.PAUSED
    gate.release.set()

    completed = _turn_completion(app, session.task_id, begun.turn_id)
    assert completed["stop_reason"] == STOP_REASON
    # The provider round already ran when the stop landed; no further step did.
    assert completed["steps"] == 1

    assert isinstance(app.provider, _GatedProvider)
    assert app.provider.calls == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _event_count(app, session.task_id, TaskEventType.ACTION_PROPOSED) == 0
    assert (
        _event_count(app, session.task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == 0
    )
    assert any(
        "not executed" in reply and STOP_REASON in reply
        for reply in _tool_replies(app, session.task_id)
    )
    assert _run_status(app, session.task_id) is RunStatus.PAUSED
    assert app.surface.get_session(session.session_id).status is (
        SurfaceSessionStatus.PAUSED
    )
    assert app.surface_has_uncommitted_turn(session.session_id) is False

    # The session is stopped, not wedged: resume, then the same work runs.
    assert app.surface.resume(_resume_command(app, session.session_id)).status is (
        SurfaceSessionStatus.ACTIVE
    )
    # ACCEPT_IN_WORKSPACE so the retried edit is auto-allowed rather than parked
    # for approval: the point here is that the session is usable again.
    assert (
        app.surface.set_permission_mode(
            _mode_command(app, session.session_id, "ACCEPT_IN_WORKSPACE")
        ).permission_mode
        == "ACCEPT_IN_WORKSPACE"
    )
    assert app.provider is not None
    app.provider = DeterministicProvider(
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-edit-2",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "edited\n",
                        },
                    ),
                ),
            ),
            ("edited reply", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    second = app.surface.begin_turn(
        _begin_turn(
            app,
            session.session_id,
            app.subscribe_stream(session.session_id),
            text="edit the fixture",
            key="idem:turn:2",
        )
    )
    assert _turn_completion(app, session.task_id, second.turn_id)["stop_reason"] == (
        "completed"
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "edited\n"


def test_pause_during_a_dispatch_stops_before_the_next_provider_call(
    tmp_path: Path,
) -> None:
    """A capability already dispatched is not aborted (bounded), but the turn
    ends there and the next provider call never happens.

    The durable Run transition is issued through the kernel while the dispatch is
    still in flight, because the *surface* pause command cannot land during a
    dispatch: the C7 effect guard linearizes it behind the effect (covered by
    `test_pause_during_a_provider_call_stops_before_any_dispatch` and the
    daemon-level evidence). Both write the same `RUN_PAUSED` truth.
    """

    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    gate = _Gate()
    app = chat_app(tmp_path)
    app.provider = _GatedProvider(
        gate,
        hold_calls=(),
        scripted=(
            (
                "",
                (proposal("call-read", "workspace.read", {"path": "fixture.txt"}),),
            ),
            ("must not be reached", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    # Delegating wrapper: only execute() is gated, every other capability-port
    # call is forwarded to the real adapter.
    app.sandbox = _GatedConnector(  # type: ignore[assignment]
        app.sandbox, gate, "workspace.read"
    )
    session, _ = app.open_chat_session("read fixture", DeferredApprovalGateway())
    stream_id = app.subscribe_stream(session.session_id)
    begun = app.surface.begin_turn(
        _begin_turn(app, session.session_id, stream_id, text="read the fixture")
    )

    assert gate.entered.wait(timeout=10)
    app.pause_task(session.task_id)
    gate.release.set()

    completed = _turn_completion(app, session.task_id, begun.turn_id)
    assert completed["stop_reason"] == STOP_REASON
    assert completed["steps"] == 1
    assert isinstance(app.provider, _GatedProvider)
    assert app.provider.calls == 1
    assert (
        _event_count(app, session.task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == 1
    )
    assert _run_status(app, session.task_id) is RunStatus.PAUSED


def test_pause_between_proposals_answers_the_rest_as_not_executed(
    tmp_path: Path,
) -> None:
    """A stop observed while a message still has unanswered proposals answers
    them with `not executed`, so the transcript stays valid for the next turn."""

    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    gate = _Gate()
    app = chat_app(tmp_path)
    app.provider = _GatedProvider(
        gate,
        hold_calls=(1,),
        scripted=(
            (
                "",
                (
                    proposal("call-read-1", "workspace.read", {"path": "fixture.txt"}),
                    proposal("call-read-2", "workspace.read", {"path": "fixture.txt"}),
                ),
            ),
            ("must not be reached", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    session, _ = app.open_chat_session("two reads", DeferredApprovalGateway())
    begun = app.surface.begin_turn(
        _begin_turn(
            app,
            session.session_id,
            app.subscribe_stream(session.session_id),
            text="read the fixture twice",
        )
    )

    assert gate.entered.wait(timeout=10)
    assert app.surface.pause(_pause_command(app, session.session_id)).status is (
        SurfaceSessionStatus.PAUSED
    )
    gate.release.set()

    completed = _turn_completion(app, session.task_id, begun.turn_id)
    assert completed["stop_reason"] == STOP_REASON
    assert app.provider.calls == 1
    assert (
        _event_count(app, session.task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == 0
    )
    replies = _tool_replies(app, session.task_id)
    assert len(replies) == 2
    assert all("not executed" in reply and STOP_REASON in reply for reply in replies)
    assert _run_status(app, session.task_id) is RunStatus.PAUSED
    assert app.surface_has_uncommitted_turn(session.session_id) is False


def test_pausing_one_session_leaves_another_session_running(
    tmp_path: Path,
) -> None:
    """The stop is per-session: the other session's turn still runs and ends."""

    app = chat_app(tmp_path, scripted=(("first reply", ()), ("second reply", ())))
    stopped, _ = app.open_chat_session("stop this one", DeferredApprovalGateway())
    other, _ = app.open_chat_session("keep this one", DeferredApprovalGateway())

    assert app.surface.pause(_pause_command(app, stopped.session_id)).status is (
        SurfaceSessionStatus.PAUSED
    )

    assert app.surface.get_session(other.session_id).status is (
        SurfaceSessionStatus.ACTIVE
    )
    assert _run_status(app, other.task_id) is RunStatus.QUEUED
    assert _run_status(app, stopped.task_id) is RunStatus.PAUSED
    assert _event_count(app, other.task_id, TaskEventType.RUN_PAUSED) == 0

    begun = app.surface.begin_turn(
        _begin_turn(
            app,
            other.session_id,
            app.subscribe_stream(other.session_id),
            text="keep going",
        )
    )
    assert _turn_completion(app, other.task_id, begun.turn_id)["stop_reason"] == (
        "completed"
    )
    assert app.surface.get_session(other.session_id).status is (
        SurfaceSessionStatus.ACTIVE
    )
    assert app.surface.get_session(stopped.session_id).status is (
        SurfaceSessionStatus.PAUSED
    )
