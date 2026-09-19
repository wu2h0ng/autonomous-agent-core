"""A session whose turn owner died is recoverable, honestly and by decision.

Defect (operator dead-end sweep, F4 - reproduced on a real daemon before this
change): kill the runtime mid-turn and restart it against the same database.
`noem session show` still answers `ACTIVE`, but every later turn is refused -
`SurfaceTurnInProgress` at `begin_turn`, `run_turn`'s "session already has an
open durable turn" - because the durable truth is a `SESSION_TURN_STARTED`
whose `SESSION_TURN_COMPLETED` died with the process that owed it. There is no
route back: `AgentLoop.resume_turn` (the kernel's in-process recovery) has no
app-layer caller, and neither `pause` nor `resume` touches the turn.

What recovery means here, from the codebase's own concepts: the turn is DEAD,
not resumable - the provider call that would have produced its outcome died
with its process. So it is closed exactly the way the repository already closes
an ambiguous outcome (`UNKNOWN_REQUIRES_REVIEW`): never as a success, with the
reason named. The operator declares it dead; the runtime records who declared
it, on what evidence (the owner generation durable in the start event), and
refuses when this generation still owns the turn.

These tests pin:

  * the bricked state and both refusals on a restarted application instance;
  * the recovery: typed durable record, `unknown_requires_review`, no receipt,
    no dispatch, no Run transition, session usable again;
  * the live-turn guard (a turn this generation is executing is never closed);
  * a parked approval stays the human's decision;
  * convergence: nothing accumulates and no second open turn is ever created.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    PrincipalIdentity,
    PrincipalRole,
    ProviderToolProposal,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceOpenSessionCommand,
    SurfaceStreamBinding,
    SurfaceTurnCommand,
    SurfaceTurnRecoveryCommand,
    TaskEventType,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SessionProjector,
    SurfaceTurnInProgress,
    SurfaceTurnOwnedByLiveRuntime,
)

from apps.api_server.app import AgentOSApplication


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="cli-ts:dead-turn",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:dead-turn",
    )


class ProcessDeathProvider(DeterministicProvider):
    """A provider call that never returns.

    A killed process leaves the same durable record as a provider call that
    never comes back: `SESSION_TURN_STARTED` and nothing after it. Raising a
    BaseException (not an Exception) is what the loop sees when the process
    dies inside the call - no catch in the turn path may convert it into a
    completed turn.
    """

    def complete_streaming(self, request, **kwargs):  # type: ignore[override]
        raise KeyboardInterrupt("runtime process died during the provider call")


class GatedProvider(DeterministicProvider):
    """A live provider call that blocks until the test releases it."""

    def __init__(self, *, scripted, invocation_binding, gate: threading.Event) -> None:
        super().__init__(scripted=scripted, invocation_binding=invocation_binding)
        self._gate = gate
        self.entered = threading.Event()

    def complete_streaming(self, request, **kwargs):  # type: ignore[override]
        self.entered.set()
        if not self._gate.wait(timeout=10):
            raise RuntimeError("gated provider was never released")
        return super().complete_streaming(request, **kwargs)


def _app(root: Path) -> AgentOSApplication:
    return AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)


def _open(app: AgentOSApplication, *, statement: str = "dead turn session"):
    return app.surface.open_session(
        SurfaceOpenSessionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            statement=statement,
            idempotency_key=f"idem:dead-turn:open:{statement}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _turn(app: AgentOSApplication, session_id: str, text: str, key: str):
    snapshot = app.surface.get_session(session_id)
    return app.surface.run_turn(
        SurfaceTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text=text,
            expected_event_sequence=snapshot.event_sequence,
            idempotency_key=key,
            requested_at=datetime.now(timezone.utc),
        )
    )


def _recovery_command(
    app: AgentOSApplication,
    session_id: str,
    turn_id: str,
    *,
    reason: str = "the runtime was killed mid-turn and restarted",
    key: str = "idem:dead-turn:recover",
) -> SurfaceTurnRecoveryCommand:
    snapshot = app.surface.get_session(session_id)
    return SurfaceTurnRecoveryCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        turn_id=turn_id,
        reason=reason,
        expected_event_sequence=snapshot.event_sequence,
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _recover(
    app: AgentOSApplication,
    session_id: str,
    turn_id: str,
    *,
    reason: str = "the runtime was killed mid-turn and restarted",
    key: str = "idem:dead-turn:recover",
):
    return app.surface.recover_unknown_turn(
        _recovery_command(app, session_id, turn_id, reason=reason, key=key)
    )


def _events(app: AgentOSApplication, task_id: str) -> list:
    return list(app.store.read(task_id))


def _event_types(app: AgentOSApplication, task_id: str) -> list[str]:
    return [event.event_type.value for event in _events(app, task_id)]


def _turn_payloads(app: AgentOSApplication, task_id: str, event_type) -> list[dict]:
    return [
        json.loads(event.payload_json)
        for event in _events(app, task_id)
        if event.event_type is event_type
    ]


def _kill_mid_turn(root: Path) -> tuple[AgentOSApplication, str, str, str]:
    """Leave exactly the durable state a runtime killed mid-turn leaves.

    Returns (restarted app, session_id, task_id, dead turn_id): the first app
    instance is the process that died; the second is the restart against the
    same database (a fresh runtime generation with no in-flight ownership).
    """

    dying = _app(root)
    dying.provider = ProcessDeathProvider(
        scripted=(("never delivered", ()),),
        invocation_binding=dying.provider.invocation_binding,
    )
    dying.provider_configured = True
    opened = _open(dying)
    session_id = opened.session.session_id
    task_id = opened.session.task_id
    with pytest.raises(KeyboardInterrupt):
        _turn(dying, session_id, "inspect the fixture", "idem:dead-turn:dying-turn")

    starts = _turn_payloads(dying, task_id, TaskEventType.SESSION_TURN_STARTED)
    assert len(starts) == 1
    turn_id = starts[0]["turn_id"]
    assert starts[0]["runtime_boot_id"] == dying.runtime_boot_id
    assert starts[0]["runtime_pid"] > 0
    assert _turn_payloads(dying, task_id, TaskEventType.SESSION_TURN_COMPLETED) == []

    restarted = _app(root)
    restarted.provider = DeterministicProvider(
        scripted=(("the session works again", ()),),
        invocation_binding=restarted.provider.invocation_binding,
    )
    restarted.provider_configured = True
    return restarted, session_id, task_id, turn_id


def test_a_dead_turn_bricks_every_route_until_it_is_closed(tmp_path: Path) -> None:
    """The reproduced state: ACTIVE, one dangling turn, every turn refused."""

    restarted, session_id, task_id, turn_id = _kill_mid_turn(tmp_path)

    assert restarted.surface.get_session(session_id).status.value == "ACTIVE"
    assert restarted.surface_has_uncommitted_turn(session_id) is True
    assert restarted.surface_open_turn_id(session_id) == turn_id

    with pytest.raises(ValueError, match="already has an open durable turn"):
        _turn(restarted, session_id, "carry on", "idem:dead-turn:refused-turn")

    # The begin-turn path refuses before the provider is ever started, and the
    # refusal names the turn and the one route out.
    with pytest.raises(SurfaceTurnInProgress) as caught:
        restarted.surface.begin_turn(
            SurfaceBeginTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=_client_ref(),
                session_id=session_id,
                text="carry on",
                stream=SurfaceStreamBinding(
                    runtime_boot_id=restarted.runtime_boot_id,
                    stream_id=restarted.surface.subscribe_stream(session_id),
                ),
                expected_event_sequence=restarted.surface.get_session(
                    session_id
                ).event_sequence,
                idempotency_key="idem:dead-turn:refused-begin",
                requested_at=datetime.now(timezone.utc),
            )
        )
    assert turn_id in str(caught.value)
    assert "recover-turn" in str(caught.value)


def test_recovery_records_an_unknown_outcome_and_restores_the_session(
    tmp_path: Path,
) -> None:
    restarted, session_id, task_id, turn_id = _kill_mid_turn(tmp_path)
    run_before = restarted.tasks.get_task(task_id).run
    assert run_before is not None

    response = _recover(restarted, session_id, turn_id)

    # The response is the notice: typed, naming the turn, the owner generation
    # and the decision.
    recovery = response.recovery
    assert recovery.turn_id == turn_id
    assert recovery.reason_code == "TURN_OWNER_PROCESS_GONE"
    assert recovery.declared_by == "user:local"
    assert recovery.recovered_by_runtime_boot_id == restarted.runtime_boot_id
    assert recovery.owner_runtime_boot_id is not None
    assert recovery.owner_runtime_boot_id != restarted.runtime_boot_id
    assert recovery.counters_recorded is False
    assert turn_id in response.notice
    assert "unknown_requires_review" in response.notice

    # Durable truth: the turn is closed, never as a success.
    completed = _turn_payloads(restarted, task_id, TaskEventType.SESSION_TURN_COMPLETED)
    assert len(completed) == 1
    assert completed[0]["turn_id"] == turn_id
    assert completed[0]["stop_reason"] == "unknown_requires_review"
    assert completed[0]["stop_reason"] != "completed"
    block = completed[0]["dead_turn_recovery"]
    assert block["turn_id"] == turn_id
    assert block["reason_code"] == "TURN_OWNER_PROCESS_GONE"
    assert block["declared_by"] == "user:local"
    assert block["started_sequence"] == min(
        event.sequence
        for event in _events(restarted, task_id)
        if event.event_type is TaskEventType.SESSION_TURN_STARTED
    )
    assert block["started_event_id"]
    assert block["recovered_by_runtime_boot_id"] == restarted.runtime_boot_id

    # Effect receipts are untouched: the dead turn never dispatched anything, so
    # nothing is recorded as succeeded or as cleanly failed.
    assert _turn_payloads(restarted, task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
    assert _turn_payloads(restarted, task_id, TaskEventType.ACTION_PROPOSED) == []
    # The Run state is not a recovery input or output; it is left exactly as the
    # dead process left it.
    assert restarted.tasks.get_task(task_id).run.status is run_before.status

    # The session is usable again, and the projection agrees the turn is closed.
    assert restarted.surface_has_uncommitted_turn(session_id) is False
    assert restarted.surface_open_turn_id(session_id) is None
    assert response.snapshot.status.value == "ACTIVE"

    follow_up = _turn(restarted, session_id, "carry on", "idem:dead-turn:next-turn")
    assert follow_up.stop_reason == "completed"
    assert restarted.surface_has_uncommitted_turn(session_id) is False
    assert (
        len(_turn_payloads(restarted, task_id, TaskEventType.SESSION_TURN_COMPLETED)) == 2
    )


def test_recovery_of_a_live_turn_is_refused(tmp_path: Path) -> None:
    """A turn this generation is executing is never closed from under itself."""

    root = tmp_path
    app = _app(root)
    gate = threading.Event()
    provider = GatedProvider(
        scripted=(("the live turn's answer", ()),),
        invocation_binding=app.provider.invocation_binding,
        gate=gate,
    )
    app.provider = provider
    app.provider_configured = True
    opened = _open(app, statement="live turn session")
    session_id = opened.session.session_id
    task_id = opened.session.task_id

    snapshot = app.surface.get_session(session_id)
    stream_id = app.surface.subscribe_stream(session_id)
    begin = app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text="long turn",
            stream=SurfaceStreamBinding(
                runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
            ),
            expected_event_sequence=snapshot.event_sequence,
            idempotency_key="idem:dead-turn:live-begin",
            requested_at=datetime.now(timezone.utc),
        )
    )
    assert provider.entered.wait(timeout=10)
    assert app.surface_turn_in_flight(session_id) is True

    with pytest.raises(SurfaceTurnOwnedByLiveRuntime):
        _recover(
            app,
            session_id,
            begin.turn_id,
            reason="operator tries to close a running turn",
            key="idem:dead-turn:live-recover",
        )
    assert _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_COMPLETED) == []

    gate.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not app.surface_has_uncommitted_turn(session_id):
            break
        time.sleep(0.02)
    assert app.surface_has_uncommitted_turn(session_id) is False
    assert app.surface_turn_in_flight(session_id) is False
    completed = _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_COMPLETED)
    assert [payload["stop_reason"] for payload in completed] == ["completed"]
    assert "dead_turn_recovery" not in completed[0]


def test_a_parked_approval_stays_the_humans_decision(tmp_path: Path) -> None:
    """An open turn that a human APPROVE/REJECT owns is not recoverable."""

    root = tmp_path
    app = _app(root)
    app.provider = DeterministicProvider(
        scripted=(
            (
                "",
                (
                    ProviderToolProposal(
                        proposal_id="call-edit",
                        capability_id="workspace.edit",
                        arguments_json=json.dumps(
                            {
                                "path": "fixture.txt",
                                "old_string": "stable\n",
                                "new_string": "fixed\n",
                            }
                        ),
                    ),
                ),
            ),
            ("edited", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    opened = _open(app, statement="parked approval session")
    session_id = opened.session.session_id
    task_id = opened.session.task_id
    session, loop = app.restore_chat_session(session_id, DeferredApprovalGateway())
    first = loop.run_turn(session, "edit the fixture")
    assert first.stop_reason == "approval_required"

    projected = SessionProjector(app.store).project(task_id, session_id)
    assert projected.resumable_turn_id is not None
    assert projected.pending_continuation is not None

    with pytest.raises(
        InvalidTransitionError, match="a pending approval owns this turn"
    ):
        _recover(
            app,
            session_id,
            projected.resumable_turn_id,
            reason="operator tries to abandon a parked approval",
            key="idem:dead-turn:parked-recover",
        )
    assert _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_COMPLETED) == []


def test_an_already_completed_turn_is_never_closed_again(tmp_path: Path) -> None:
    """The named turn must be the OPEN one, not merely a turn that once existed.

    A session that ran a turn to completion and then lost a later turn has two
    turns in its stream: the old (closed) one and the open one. Declaring the
    closed one dead must be refused - closing it again would append a second
    completion for the same turn, and the projector rejects a completion with no
    exact open turn, which would leave the whole session unreadable.
    """

    root = tmp_path
    app = _app(root)
    app.provider = DeterministicProvider(
        scripted=(("the first turn's answer", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    opened = _open(app, statement="two-turn session")
    session_id = opened.session.session_id
    task_id = opened.session.task_id
    finished = _turn(app, session_id, "first turn", "idem:dead-turn:first")
    assert finished.stop_reason == "completed"

    app.provider = ProcessDeathProvider(
        scripted=(("never delivered", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    with pytest.raises(KeyboardInterrupt):
        _turn(app, session_id, "second turn dies", "idem:dead-turn:second")
    starts = _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_STARTED)
    closed_turn_id, dead_turn_id = starts[0]["turn_id"], starts[1]["turn_id"]
    assert closed_turn_id != dead_turn_id

    before = len(_events(app, task_id))
    with pytest.raises(InvalidTransitionError, match="one open durable turn"):
        _recover(
            app,
            session_id,
            closed_turn_id,
            reason="declaring the turn that already finished",
            key="idem:dead-turn:already-closed",
        )
    assert len(_events(app, task_id)) == before

    accepted = _recover(
        app,
        session_id,
        dead_turn_id,
        reason="the runtime died during the second turn",
        key="idem:dead-turn:open-one",
    )
    assert accepted.recovery.turn_id == dead_turn_id
    assert [
        payload["turn_id"]
        for payload in _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_COMPLETED)
    ] == [closed_turn_id, dead_turn_id]


def test_recovery_does_not_run_away(tmp_path: Path) -> None:
    """Repeat attempts converge: one closure, then typed refusals, no new state."""

    restarted, session_id, task_id, turn_id = _kill_mid_turn(tmp_path)
    command = _recovery_command(restarted, session_id, turn_id)
    first = restarted.surface.recover_unknown_turn(command)
    assert first.recovery.turn_id == turn_id
    after_first = len(_events(restarted, task_id))

    # A second, independent attempt (fresh idempotency key) cannot close the
    # same turn twice: there is no open turn left to bind.
    with pytest.raises(InvalidTransitionError, match="one open durable turn"):
        _recover(
            restarted,
            session_id,
            turn_id,
            reason="a second attempt at the same dead turn",
            key="idem:dead-turn:recover-again",
        )
    # An unrelated turn id is refused the same way, not closed.
    with pytest.raises(InvalidTransitionError, match="one open durable turn"):
        _recover(
            restarted,
            session_id,
            "turn-that-never-existed",
            reason="invented turn",
            key="idem:dead-turn:invented",
        )
    assert len(_events(restarted, task_id)) == after_first

    # And a replay of the exact same command is idempotent: the stored response,
    # no new event.
    replay = restarted.surface.recover_unknown_turn(command)
    assert replay.recovery.turn_id == turn_id
    assert len(_events(restarted, task_id)) == after_first

    assert _kill_mid_turn_convergence(restarted, session_id, task_id, turn_id)


def _kill_mid_turn_convergence(
    app: AgentOSApplication, session_id: str, task_id: str, turn_id: str
) -> bool:
    """One started turn, one completion, one open-turn slot - never two."""

    starts = _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_STARTED)
    completions = _turn_payloads(app, task_id, TaskEventType.SESSION_TURN_COMPLETED)
    assert [payload["turn_id"] for payload in starts] == [turn_id]
    assert [payload["turn_id"] for payload in completions] == [turn_id]
    assert app.surface_open_turn_id(session_id) is None
    return True


def test_dead_turn_recovery_requires_principal_authority(tmp_path: Path) -> None:
    restarted, session_id, _task_id, turn_id = _kill_mid_turn(tmp_path)
    restarted.principal = PrincipalIdentity(
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=PrincipalRole.WORKER,
        authenticated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(PermissionError, match="principal authority"):
        _recover(
            restarted,
            session_id,
            turn_id,
            reason="a worker tries to close the operator's turn",
            key="idem:dead-turn:worker-recover",
        )


def test_unstarted_turn_recovery_is_refused(tmp_path: Path) -> None:
    """A session with no open turn has nothing to recover."""

    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("hello", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    opened = _open(app, statement="idle session")
    with pytest.raises(InvalidTransitionError, match="one open durable turn"):
        _recover(
            app,
            opened.session.session_id,
            "turn-that-never-started",
            reason="nothing to recover",
            key="idem:dead-turn:idle",
        )
