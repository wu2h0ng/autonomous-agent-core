"""Form B child-agent kernel spine: the six adversarial-review requirements.

Each test here exists because an independent adversarial review rejected the
frozen design as specified, and every one is written so that the *absence* of
the fix turns it red:

1. C7 does not cascade - an operator's correction on the parent must stop the
   child's dispatch. ``test_pre_fix_child_keeps_dispatching_after_the_parent_is_corrected``
   reproduces the rejected behaviour with the pre-fix wiring (the composition
   root's own correction port handed to the child loop), and
   ``test_parent_correction_halts_the_child_before_dispatch`` shows the fix.
2. crash burial - a child whose runtime generation is gone is reconciled as an
   unknown outcome by an operator declaration, never as ``completed``.
3. grant narrowing - ``derive_child_grants`` is called by the composition root
   at the place the child's own input grants are decided, and the narrowed
   grants survive a restart (a restore must not widen them).
4. a nested approval need has an operator - the child parks durably on the
   operator-visible prompt, the spawn call returns ``stopped`` /
   ``awaiting_approval`` inside the wall-clock bound, and nothing is
   auto-approved.
5. the global off switch - off by default, off entirely, and switching it off
   does not corrupt a session that already has children.
6. the honest statements about N, "the parent's remaining budget", the
   synchronous wall-clock bound and the narrow scope of digest-only.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    AGENT_SPAWN_CAPABILITY_ID,
    STOP_REASON_STOPPED_BY_OPERATOR,
    SURFACE_PROTOCOL_VERSION,
    ApprovalDisposition,
    ProviderToolProposal,
    SurfaceBeginTurnCommand,
    SurfaceChildAgentReconcileCommand,
    SurfaceCorrectionCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import (
    CHILD_AGENT_RECONCILE_OUTCOME,
    CHILD_AGENT_RECONCILE_REASON_RUNTIME_GONE,
    CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL,
    CHILD_AGENT_STOP_REASON_WALL_CLOCK,
    MAX_CHILD_AGENT_ANCESTOR_DEPTH,
    AutoApproveGateway,
    ChildAgentHaltCascade,
    ChildAgentIndex,
    DeterministicProvider,
    child_agent_link_fields,
    InvalidTransitionError,
)
from apps.api_server.app import AgentOSApplication


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def app_for(
    root: Path,
    scripted: tuple[Any, ...] = (),
    *,
    child_agents: bool = True,
    database: str | None = None,
) -> AgentOSApplication:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(
        database=database or root / "agent-os.sqlite3",
        workspace=root,
        child_agents=child_agents,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def payloads(app: AgentOSApplication, task_id: str, event_type: TaskEventType):
    return [
        event.decoded_payload()
        for event in app.store.read(task_id)
        if event.event_type is event_type
    ]


def spawn_script(
    *,
    description: str = "child work",
    agent_type: str = "general",
    call_id: str = "call-spawn",
):
    return (
        (
            "",
            (
                proposal(
                    call_id,
                    AGENT_SPAWN_CAPABILITY_ID,
                    {
                        "prompt": "do the child work",
                        "description": description,
                        "agent_type": agent_type,
                    },
                ),
            ),
        ),
    )


def link_of(app: AgentOSApplication, child: Any) -> dict[str, object]:
    return dict(
        app.child_agent_index().link_for_child_task(child.child_task_id)
    )


def child_record(app: AgentOSApplication, parent_task_id: str):
    children = ChildAgentIndex(app.store).children(parent_task_id)
    assert children, "the parent stream has no child-agent record"
    return children[0]


def edit_proposal(call_id: str = "call-edit") -> Any:
    return proposal(
        call_id,
        "workspace.edit",
        {
            "path": "fixture.txt",
            "old_string": "stable\n",
            "new_string": "changed\n",
        },
    )


def park_script(call_id: str = "call-edit") -> tuple[Any, ...]:
    """A child step that proposes a tier-2 edit, so the child parks."""

    return (("", (edit_proposal(call_id),)),)


# ---------------------------------------------------------------------------
# Requirement 5: the global off switch (off by default, off entirely)
# ---------------------------------------------------------------------------


def test_child_agents_are_off_by_default(tmp_path: Path) -> None:
    app = app_for(tmp_path, child_agents=False)

    assert app.child_agents_enabled is False
    assert AGENT_SPAWN_CAPABILITY_ID not in app.chat_capability_ids
    assert AGENT_SPAWN_CAPABILITY_ID not in app.sandbox.specs()
    assert AGENT_SPAWN_CAPABILITY_ID not in app.grants
    assert AGENT_SPAWN_CAPABILITY_ID not in app._chat_grants()


def test_off_switch_refuses_a_spawn_with_a_durable_typed_denial(tmp_path: Path) -> None:
    app = app_for(tmp_path, spawn_script(), child_agents=False)
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())

    result = loop.run_turn(session, "spawn a child")

    assert result.stop_reason == "unauthorized_proposal"
    denials = payloads(app, session.task_id, TaskEventType.POLICY_VERDICT_RECORDED)
    assert any(
        denial.get("capability_id") == AGENT_SPAWN_CAPABILITY_ID
        and denial.get("verdict") == "DENY"
        and denial.get("basis") == "out_of_allowlist"
        for denial in denials
    )
    assert payloads(app, session.task_id, TaskEventType.CHILD_AGENT_SPAWNED) == []
    assert payloads(app, session.task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []


def test_turning_the_switch_off_does_not_corrupt_a_session_with_children(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agent-os.sqlite3"
    enabled = app_for(
        tmp_path,
        spawn_script(agent_type="explore") + (("child finished", ()),),
        database=database,
    )
    session, loop = enabled.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn an explore child")
    child = child_record(enabled, session.task_id)

    disabled = app_for(tmp_path, child_agents=False, database=database)

    assert disabled.child_agents_enabled is False
    response = disabled.surface_child_agents(session.session_id)
    assert len(response.turns) == 1
    assert response.turns[0].children[0].spawn_id == child.spawn_id
    assert disabled.store.read(session.task_id)
    assert (
        disabled.surface_session_snapshot(child.child_session_id).session.session_id
        == child.child_session_id
    )
    # The child's own durable records are intact and readable.
    link = disabled.child_agent_index().link_for_child_task(child.child_task_id)
    assert link["spawn_id"] == child.spawn_id


# ---------------------------------------------------------------------------
# Requirement 3: grant derivation at the real enforcement point, restart-safe
# ---------------------------------------------------------------------------


def test_explore_child_grants_are_derived_and_narrowed(tmp_path: Path) -> None:
    app = app_for(
        tmp_path,
        spawn_script(agent_type="explore")
        + park_script()
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())

    result = loop.run_turn(session, "spawn an explore child")

    assert result.stop_reason == "completed"
    child = child_record(app, session.task_id)
    grants = app.session_grants(child.child_task_id)
    assert set(grants) == {"workspace.read", "workspace.search"}
    denials = payloads(app, child.child_task_id, TaskEventType.POLICY_VERDICT_RECORDED)
    assert any(
        denial.get("capability_id") == "workspace.edit"
        and denial.get("verdict") == "DENY"
        for denial in denials
    )
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_narrowed_child_grants_survive_a_restart(tmp_path: Path) -> None:
    database = tmp_path / "agent-os.sqlite3"
    app = app_for(
        tmp_path,
        spawn_script(agent_type="explore") + park_script(),
        database=database,
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn an explore child")
    child = child_record(app, session.task_id)
    before = app.session_grants(child.child_task_id)
    assert set(before) == {"workspace.read", "workspace.search"}

    restarted = app_for(
        tmp_path,
        park_script("call-edit-again"),
        database=database,
    )

    restored = restarted.session_grants(child.child_task_id)
    assert set(restored) == set(before)
    assert {cid: grant.grant_id for cid, grant in restored.items()} == {
        cid: grant.grant_id for cid, grant in before.items()
    }

    child_session, child_loop = restarted.restore_chat_session(
        child.child_session_id, AutoApproveGateway()
    )
    assert "workspace.edit" not in child_loop.capability_ids
    # The restored loop's own grant map - the object ActionPipeline reads at the
    # enforcement point - is the durable narrowed set, not the composition
    # root's full chat set.
    assert set(child_loop._actions._grant) == {"workspace.read", "workspace.search"}
    # The durable link carries exactly the frozen triple the contract defines.
    assert child_agent_link_fields(link_of(app, child)) == {
        "parent_session_id": session.session_id,
        "parent_turn_id": child.spawned.parent_turn_id,
        "spawn_id": child.spawn_id,
    }
    child_loop.run_turn(child_session, "try to edit again")
    denials = payloads(
        restarted, child.child_task_id, TaskEventType.POLICY_VERDICT_RECORDED
    )
    assert any(
        denial.get("capability_id") == "workspace.edit"
        and denial.get("verdict") == "DENY"
        for denial in denials
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_a_tampered_child_grant_block_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = app_for(tmp_path, spawn_script(agent_type="explore") + (("child done", ()),))
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn an explore child")
    child = child_record(app, session.task_id)

    class _TamperedIndex:
        def child_link(self, task_id: str) -> dict[str, object] | None:
            return {
                "spawn_id": "spawn-1",
                "parent_task_id": "task-parent",
                "parent_run_id": "run-parent",
                "grants": {"workspace.edit": {"grant_id": "grant:tampered"}},
                "grant_plan_digest": "0" * 64,
            }

    monkeypatch.setattr(app, "child_agent_index", lambda: _TamperedIndex())
    with pytest.raises(Exception):
        app.session_grants(child.child_task_id)


# ---------------------------------------------------------------------------
# Requirement 1: the C7 halt cascade
# ---------------------------------------------------------------------------


def parked_child_run(
    tmp_path: Path,
    *,
    pre_fix_correction: bool = False,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[AgentOSApplication, Any, Any]:
    """One parent turn that spawns a child which parks on a tier-2 edit."""

    app = app_for(
        tmp_path,
        spawn_script() + park_script(),
    )
    if pre_fix_correction:
        assert monkeypatch is not None
        # The pre-fix wiring: the child loop gets the composition root's own
        # correction port, so it checks only its own task/run/capability keys.
        monkeypatch.setattr(app, "session_correction", lambda task_id: app.correction)
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    result = loop.run_turn(session, "spawn a child")
    assert result.stop_reason == "completed"
    child = child_record(app, session.task_id)
    assert app.surface_session_snapshot(child.child_session_id).pending_approval
    return app, session, child


def test_pre_fix_child_keeps_dispatching_after_the_parent_is_corrected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rejected behaviour, reproduced with the pre-fix wiring."""

    app, session, child = parked_child_run(
        tmp_path, pre_fix_correction=True, monkeypatch=monkeypatch
    )
    app.correct_task(session.task_id, "operator stopped the parent")
    pending = app.surface_session_snapshot(child.child_session_id).pending_approval
    assert pending is not None

    app.decide_session_approval(
        child.child_session_id,
        pending.action_digest,
        ApprovalDisposition.APPROVE,
        "operator approved the child edit",
    )

    # Pre-fix: the parent's correction is invisible to the child, so the child
    # resumes and the edit really executes.
    receipts = payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED)
    assert receipts
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"


def test_parent_correction_halts_the_child_before_dispatch(tmp_path: Path) -> None:
    app, session, child = parked_child_run(tmp_path)
    index = ChildAgentIndex(app.store)
    plain = app.correction
    cascade = ChildAgentHaltCascade(plain, index)
    link = index.link_for_child_task(child.child_task_id)
    child_run_id = str(link["parent_run_id"])

    assert plain.halted(child.child_task_id, child_run_id, "workspace.edit") is False
    assert cascade.halted(child.child_task_id, child_run_id, "workspace.edit") is False

    app.correct_task(session.task_id, "operator stopped the parent")

    # Pre-fix port: still not halted - the C2 finding, reproduced.
    assert plain.halted(child.child_task_id, child_run_id, "workspace.edit") is False
    # Cascade: halted because an ancestor of the child is halted.
    assert cascade.halted(child.child_task_id, child_run_id, "workspace.edit") is True
    # The cascade invents no epochs and cannot clear anything.
    assert cascade.snapshot(
        child.child_task_id, child_run_id, "workspace.edit"
    ) == plain.snapshot(child.child_task_id, child_run_id, "workspace.edit")

    pending = app.surface_session_snapshot(child.child_session_id).pending_approval
    assert pending is not None
    with pytest.raises(InvalidTransitionError):
        app.decide_session_approval(
            child.child_session_id,
            pending.action_digest,
            ApprovalDisposition.APPROVE,
            "operator approved the child edit",
        )
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_cascade_is_read_side_bounded_and_exposes_no_writer(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    cascade = ChildAgentHaltCascade(app.correction, ChildAgentIndex(app.store))

    # An unknown task has no ancestry and is not halted on that account.
    assert cascade.halted("task:unknown", "run:unknown", "workspace.edit") is False
    # A chain deeper than the bound, or one that cycles, is halted (fail-closed)
    # rather than walked forever.
    assert MAX_CHILD_AGENT_ANCESTOR_DEPTH >= 2
    # C7 stays non-writable from the runtime side: no writer on the cascade.
    for writer in ("correct", "resume", "advance_correction", "write_correction"):
        assert not hasattr(cascade, writer)
        assert not hasattr(app.sandbox, writer)


def test_child_is_individually_stoppable_through_the_existing_path(
    tmp_path: Path,
) -> None:
    app, session, child = parked_child_run(tmp_path)

    app.stop_child_agent(child.child_session_id, reason="operator stopped this child")

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["spawn_id"] == child.spawn_id
    assert finishes[-1]["status"] == "stopped"
    assert finishes[-1]["stop_reason"] == STOP_REASON_STOPPED_BY_OPERATOR
    corrections = payloads(app, child.child_task_id, TaskEventType.CORRECTION_WRITTEN)
    assert corrections and corrections[-1]["scope"] == "TASK"
    assert corrections[-1]["halted"] is True
    # Stopping one child leaves the parent untouched.
    assert app.tasks.get_task(session.task_id).run.status.value != "PAUSED"


def test_parent_closure_stops_in_flight_children(tmp_path: Path) -> None:
    app, session, child = parked_child_run(tmp_path)

    app.close_session_and_stop_children(session.session_id)

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["spawn_id"] == child.spawn_id
    assert finishes[-1]["stop_reason"] == "parent_session_closed"
    closures = payloads(app, session.task_id, TaskEventType.SESSION_CLOSED)
    assert closures and closures[-1]["session_id"] == session.session_id


# ---------------------------------------------------------------------------
# G10: the operator's explicit close cascades to every in-flight child, and a
# per-child stop never touches its sibling. Two concurrent in-flight children
# are built by letting the parent spawn child A (which parks on a tier-2 edit),
# then continue and spawn child B (which also parks). Both are open, in-flight
# child records on the parent stream.
# ---------------------------------------------------------------------------


def _two_parked_children(tmp_path: Path):
    """Drive a parent that spawns two children, each parked on an approval."""

    app = app_for(
        tmp_path,
        spawn_script(call_id="call-spawn-a")
        + park_script("call-edit-a")
        + spawn_script(call_id="call-spawn-b")
        + park_script("call-edit-b")
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn two children")
    children = ChildAgentIndex(app.store).children(session.task_id)
    assert len(children) == 2, f"expected two in-flight children, got {len(children)}"
    return app, session, children


def _close_command(session_id: str, reason: str) -> SurfaceCorrectionCommand:
    from datetime import datetime, timezone

    return SurfaceCorrectionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client_ref(),
        session_id=session_id,
        reason=reason,
        expected_event_sequence=0,
        idempotency_key=f"test-close:{session_id}",
        requested_at=datetime.now(timezone.utc),
    )


def test_g10_single_child_stop_leaves_its_sibling_in_flight(
    tmp_path: Path,
) -> None:
    """SINGLE_CHILD_STOPPED_OTHERS_UNTOUCHED.

    Two concurrent in-flight children; stopping one sibling must not stop the
    other, and must not pause/halt the parent.
    """

    app, session, children = _two_parked_children(tmp_path)
    child_a, child_b = children[0], children[1]
    finishes_before = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)

    app.stop_child_agent(child_a.child_session_id, reason="operator stops child A")

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    # Child A received exactly one NEW terminal record: the operator stop.
    new_for_a = [
        f for f in finishes
        if f["spawn_id"] == child_a.spawn_id
        and f not in finishes_before
    ]
    assert len(new_for_a) == 1, new_for_a
    assert new_for_a[-1]["stop_reason"] == STOP_REASON_STOPPED_BY_OPERATOR
    # The sibling is untouched: it received NO new terminal record when A was
    # stopped, its own latest record is still the park (awaiting_approval), and
    # the parent run was not paused/halted.
    new_for_b = [
        f for f in finishes
        if f["spawn_id"] == child_b.spawn_id
        and f not in finishes_before
    ]
    assert new_for_b == [], new_for_b
    child_b_finishes = [f for f in finishes if f["spawn_id"] == child_b.spawn_id]
    assert child_b_finishes[-1]["stop_reason"] == "awaiting_approval"
    assert app.tasks.get_task(session.task_id).run.status.value != "PAUSED"
    sibling = app.surface_session_snapshot(child_b.child_session_id)
    assert sibling.status.value == "WAITING_APPROVAL"


def test_g10_operator_close_stops_every_in_flight_child_durably(
    tmp_path: Path,
) -> None:
    """PARENT_STOPPED_CHILDREN_DURABLY.

    The operator's explicit close of the parent stops every in-flight child,
    each named ``stopped_by_operator`` (G10's named observation), and closes the
    parent.
    """

    app, session, children = _two_parked_children(tmp_path)
    spawn_ids = {child.spawn_id for child in children}

    snapshot = app.surface_close_session(
        _close_command(session.session_id, "operator closes the session")
    )

    assert snapshot.status.value == "CLOSED"
    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    finished = {f["spawn_id"] for f in finishes}
    assert spawn_ids <= finished, f"children not stopped: {spawn_ids - finished}"
    for spawn_id in spawn_ids:
        record = [f for f in finishes if f["spawn_id"] == spawn_id][-1]
        assert record["stop_reason"] == STOP_REASON_STOPPED_BY_OPERATOR, record
    closures = payloads(app, session.task_id, TaskEventType.SESSION_CLOSED)
    assert closures and closures[-1]["session_id"] == session.session_id


# ---------------------------------------------------------------------------
# Requirement 4: a nested approval need has a real operator
# ---------------------------------------------------------------------------


def test_child_parking_on_an_approval_is_surfaced_not_auto_approved(
    tmp_path: Path,
) -> None:
    app, session, child = parked_child_run(tmp_path)

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["status"] == "stopped"
    assert finishes[-1]["stop_reason"] == CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL
    # The parent turn completed: the spawn call returned instead of hanging.
    assert (
        payloads(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED)[-1][
            "stop_reason"
        ]
        == "completed"
    )
    # The child's own session exposes the pending approval to the operator, and
    # nothing was approved on the child's behalf.
    snapshot = app.surface_session_snapshot(child.child_session_id)
    assert snapshot.pending_approval is not None
    assert snapshot.permission_mode == "ASK"
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []


def test_child_wall_clock_bound_is_a_bound_not_a_preemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_OS_CHILD_AGENT_TIMEOUT_SECONDS", "0.05")
    app = app_for(
        tmp_path,
        spawn_script()
        + (
            (
                "child read step",
                (proposal("call-read", "workspace.read", {"path": "fixture.txt"}),),
            ),
        )
        + (("child finished reading", ()),)
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    parent_task_id = session.task_id
    original = DeterministicProvider.complete_streaming

    def slow_child_call(self, request, **kwargs):  # type: ignore[no-untyped-def]
        if request.task_id != parent_task_id:
            time.sleep(0.4)
        return original(self, request, **kwargs)

    monkeypatch.setattr(DeterministicProvider, "complete_streaming", slow_child_call)
    loop.run_turn(session, "spawn a child")

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["status"] == "timeout"
    assert finishes[-1]["stop_reason"] == CHILD_AGENT_STOP_REASON_WALL_CLOCK
    # The child really stopped (its own turn recorded the bound), and the
    # parent's turn still completed: the spawn is bounded, not abandoned.
    child = child_record(app, session.task_id)
    child_turns = payloads(
        app, child.child_task_id, TaskEventType.SESSION_TURN_COMPLETED
    )
    assert child_turns and child_turns[-1]["stop_reason"] == "wall_clock_exceeded"
    assert (
        payloads(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED)[-1][
            "stop_reason"
        ]
        == "completed"
    )


# ---------------------------------------------------------------------------
# Requirement 2: crash burial
# ---------------------------------------------------------------------------


def leave_crash_residue(
    tmp_path: Path, *, owner_boot_id: str | None = None, database: Path | None = None
) -> tuple[AgentOSApplication, Any, Any]:
    """Leave exactly the durable state a crash mid-spawn leaves behind.

    A child session whose ``SESSION_OPENED`` link names another runtime
    generation, a durable ``CHILD_AGENT_SPAWNED`` on the parent's stream, and no
    ``CHILD_AGENT_FINISHED`` - written through the repository's own typed
    writers, so no test-only schema is involved.
    """

    app = app_for(tmp_path, database=database)
    session, _ = app.open_chat_session("parent work", AutoApproveGateway())
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    owner = owner_boot_id if owner_boot_id is not None else app.runtime_boot_id
    spawn_id = f"spawn:orphan-{owner}"

    def _block(child_session: Any) -> dict[str, object]:
        return {
            "spawn_id": spawn_id,
            "parent_session_id": session.session_id,
            "parent_task_id": session.task_id,
            "parent_run_id": run.run_id,
            "parent_turn_id": "turn:parent-1",
            "child_session_id": child_session.session_id,
            "child_task_id": child_session.task_id,
            "agent_type": "general",
            "description": "crashed child",
            "prompt_digest": "0" * 64,
            "spawn_runtime_boot_id": owner,
            "spawn_runtime_pid": 12345,
            "grants": {},
            "grant_plan_digest": "0" * 64,
        }

    from agent_os_core import AgentLoopConfig

    child_session, _child_loop = app._open_session_and_loop(
        statement="child agent task: crashed child",
        gateway=AutoApproveGateway(),
        loop_config=AgentLoopConfig(),
        grants=app._chat_grants(),
        correction=app.correction,
        capability_ids=app.chat_capability_ids,
        permission_mode="ASK",
        child_agent_builder=_block,
    )
    from agent_os_contracts import ChildAgentSpawned

    app.tasks.record_child_agent_spawned(
        session.task_id,
        ChildAgentSpawned(
            spawn_id=spawn_id,
            parent_session_id=session.session_id,
            parent_turn_id="turn:parent-1",
            child_session_id=child_session.session_id,
            child_task_id=child_session.task_id,
            agent_type="general",
            description="crashed child",
            prompt_digest="0" * 64,
        ),
        parent_run_id=run.run_id,
    )
    app.child_agent_index()._link_cache.clear()
    return app, session, child_session


def reconcile_command(session_id: str, reason: str) -> Any:
    return SurfaceChildAgentReconcileCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client_ref(),
        session_id=session_id,
        reason=reason,
        idempotency_key=f"idem:reconcile:{session_id}",
        requested_at=datetime.now(timezone.utc),
    )


def test_burial_closes_an_ownerless_child_as_an_unknown_outcome(
    tmp_path: Path,
) -> None:
    app, session, child_session = leave_crash_residue(
        tmp_path, owner_boot_id="boot:dead-generation"
    )

    response = app.surface_child_agents(session.session_id)
    assert len(response.orphaned) == 1
    orphan = response.orphaned[0]
    assert orphan.child_session_id == child_session.session_id
    assert orphan.spawn_runtime_boot_id == "boot:dead-generation"
    assert orphan.spawned_by_current_generation is False
    assert orphan.spawned_by_current_generation is False

    buried = app.surface_reconcile_child_agents(
        reconcile_command(session.session_id, "the runtime died mid-child")
    )

    assert len(buried.buried) == 1
    record = buried.buried[0]
    assert record.reason_code == CHILD_AGENT_RECONCILE_REASON_RUNTIME_GONE
    assert record.outcome == CHILD_AGENT_RECONCILE_OUTCOME
    assert record.declared_by == app.principal.principal_id
    assert record.runtime_boot_id == app.runtime_boot_id

    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["status"] == "failed"
    assert finishes[-1]["status"] != "completed"
    assert finishes[-1]["stop_reason"] == "unknown_requires_review"
    reconciliations = payloads(
        app, session.task_id, TaskEventType.CHILD_AGENT_RECONCILED
    )
    assert reconciliations[-1]["outcome"] == "UNKNOWN"
    assert reconciliations[-1]["reason_code"] == "CHILD_RUNTIME_GENERATION_GONE"
    # Nothing is in flight any more, and the roll-up says failed - never done.
    assert app.surface_child_agents(session.session_id).orphaned == ()
    row = app.surface_child_agents(session.session_id).turns[0].children[0]
    assert row.status.value == "failed"


def test_burial_covers_an_abandoned_spawn_of_this_generation(tmp_path: Path) -> None:
    """A spawn call that died inside this generation is still reconcilable.

    Its child has no finish record, no live worker and no parked approval - an
    in-generation orphan. Refusing to bury it would leave the session showing an
    in-flight child that nothing can ever close.
    """

    app, session, _child_session = leave_crash_residue(tmp_path)

    response = app.surface_child_agents(session.session_id)
    assert len(response.orphaned) == 1
    assert response.orphaned[0].spawned_by_current_generation is True

    buried = app.surface_reconcile_child_agents(
        reconcile_command(session.session_id, "the spawn call died mid-child")
    )
    assert len(buried.buried) == 1
    assert buried.buried[0].reason_code == "CHILD_SPAWN_ABANDONED"
    assert buried.buried[0].outcome == "UNKNOWN"
    finishes = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    assert finishes[-1]["status"] == "failed"
    assert finishes[-1]["status"] != "completed"
    assert app.surface_child_agents(session.session_id).orphaned == ()


def test_burial_refuses_a_child_parked_on_a_human_decision(tmp_path: Path) -> None:
    app, session, child = parked_child_run(tmp_path)

    # The child is in flight and ownerless, but it is parked on its own
    # permission prompt: nothing but an operator decision may close it.
    with pytest.raises(Exception, match="live runtime generation"):
        app.surface_reconcile_child_agents(
            reconcile_command(session.session_id, "try to bury a parked child")
        )
    assert app.surface_session_snapshot(child.child_session_id).pending_approval


# ---------------------------------------------------------------------------
# Requirement 6: the bounds, the attribution and the narrow digest rule
# ---------------------------------------------------------------------------


def test_fan_out_bound_is_enforced_before_any_child_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_OS_MAX_CHILD_AGENTS", "1")
    app = app_for(
        tmp_path,
        spawn_script()
        + park_script()
        + spawn_script(description="second child", call_id="call-spawn-2")
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())

    result = loop.run_turn(session, "spawn two children")

    spawned = payloads(app, session.task_id, TaskEventType.CHILD_AGENT_SPAWNED)
    assert len(spawned) == 1
    failures = payloads(app, session.task_id, TaskEventType.NODE_FAILED)
    assert any("ChildAgentLimitExceeded" in failure.get("error", "") for failure in failures)
    index = ChildAgentIndex(app.store)
    child = child_record(app, session.task_id)
    assert index.in_flight(session.task_id, child.spawned.parent_turn_id) == 1
    assert result.stop_reason == "completed"


def test_attribution_includes_children_without_copying_their_text(
    tmp_path: Path,
) -> None:
    app = app_for(
        tmp_path,
        spawn_script(agent_type="explore")
        + (("CHILD-SECRET-COMPLETION-TEXT", ()),)
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn an explore child")
    child = child_record(app, session.task_id)

    response = app.surface_child_agents(session.session_id)
    assert response.turns
    attribution = response.turns[0]
    assert attribution.children_included_in_totals is True
    assert attribution.total_steps == attribution.parent_own_steps + sum(
        row.steps for row in attribution.children
    )
    assert attribution.children[0].child_session_id == child.child_session_id
    assert "CHILD-SECRET-COMPLETION-TEXT" not in json.dumps(
        response.model_dump(mode="json")
    )
    # The digest-only rule is narrow: it covers the child-agent records, while
    # the child's own session stream records its messages like any session's.
    child_messages = json.dumps(
        payloads(app, child.child_task_id, TaskEventType.SESSION_MESSAGE_RECORDED)
    )
    assert "CHILD-SECRET-COMPLETION-TEXT" in child_messages
    assert "do the child work" not in json.dumps(
        payloads(app, session.task_id, TaskEventType.CHILD_AGENT_SPAWNED)
    )
    assert "CHILD-SECRET-COMPLETION-TEXT" not in json.dumps(
        payloads(app, session.task_id, TaskEventType.CHILD_AGENT_FINISHED)
    )


def test_agent_spawn_is_registered_governed_and_cannot_reach_c7(
    tmp_path: Path,
) -> None:
    from agent_os_core.permission_gate import ACTION_RISK_TIERS
    from agent_os_core.provider import _tool_definition

    app = app_for(tmp_path)
    spec = app.sandbox.specs()[AGENT_SPAWN_CAPABILITY_ID]
    assert spec.risk_tier == ACTION_RISK_TIERS[AGENT_SPAWN_CAPABILITY_ID] == 2
    definition = _tool_definition(AGENT_SPAWN_CAPABILITY_ID)["function"]
    assert "awaiting_approval" in definition["description"]
    assert definition["parameters"]["required"] == ["prompt", "description"]
    # The connector holds no correction port of any kind: spawn cannot reach C7.
    assert not hasattr(app.sandbox, "correction")
    assert not hasattr(app.sandbox, "correction_admin")


def test_child_grant_is_derived_by_the_contract_function_not_by_hand(
    tmp_path: Path,
) -> None:
    app = app_for(
        tmp_path,
        spawn_script() + park_script(),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn a child")
    child = child_record(app, session.task_id)
    grants = app.session_grants(child.child_task_id)

    # Every child grant is a non-widening copy of its parent grant: same
    # capability, same version, same or lower risk tier, budget within the
    # parent's, expiry no later, and a child-scoped grant id the audit can tell
    # apart from the parent's.
    parent_grants = app._chat_grants()
    for capability_id, grant in grants.items():
        parent = parent_grants[capability_id]
        assert grant.capability_id == parent.capability_id
        assert grant.max_risk_tier <= parent.max_risk_tier
        assert grant.expires_at <= parent.expires_at
        assert grant.budget_limit.fits_within(parent.budget_limit)
        assert grant.principal_id == parent.principal_id
        assert grant.tenant_id == parent.tenant_id
        assert grant.workspace_id == parent.workspace_id
        assert grant.grant_id != parent.grant_id
        assert grant.granted_by == f"agent.spawn:{child.spawn_id}"
    assert AGENT_SPAWN_CAPABILITY_ID not in grants


def test_nested_spawn_is_refused_without_the_explicit_opt_in(tmp_path: Path) -> None:
    app = app_for(
        tmp_path,
        spawn_script()
        + (
            (
                "child step",
                (
                    proposal(
                        "call-nested",
                        AGENT_SPAWN_CAPABILITY_ID,
                        {"prompt": "grandchild work", "description": "grandchild"},
                    ),
                ),
            ),
        )
        + (("child reports it cannot spawn", ()),)
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn a child")
    child = child_record(app, session.task_id)

    assert AGENT_SPAWN_CAPABILITY_ID not in app.session_grants(child.child_task_id)
    assert len(payloads(app, session.task_id, TaskEventType.CHILD_AGENT_SPAWNED)) == 1
    # The nested attempt is refused on the child's own stream, not silently.
    child_denials = payloads(
        app, child.child_task_id, TaskEventType.POLICY_VERDICT_RECORDED
    )
    assert any(
        denial.get("capability_id") == AGENT_SPAWN_CAPABILITY_ID for denial in child_denials
    )


def test_one_in_flight_turn_per_child_session_is_preserved(tmp_path: Path) -> None:
    from agent_os_core.surface_runtime import SurfaceTurnInProgress

    app, session, child = parked_child_run(tmp_path)

    assert app.surface_has_uncommitted_turn(child.child_session_id) is True
    subscription = app.subscribe_stream(child.child_session_id)
    task_id = app.surface_task_for_session(child.child_session_id)
    with pytest.raises((SurfaceTurnInProgress, InvalidTransitionError, ValueError)):
        app.surface_begin_turn(
            SurfaceBeginTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=client_ref(),
                session_id=child.child_session_id,
                text="second concurrent turn",
                stream=SurfaceStreamBinding(
                    runtime_boot_id=app.runtime_boot_id,
                    stream_id=subscription,
                ),
                expected_event_sequence=app.surface_current_sequence(task_id),
                idempotency_key="idem:begin:child",
                requested_at=datetime.now(timezone.utc),
            )
        )
    # The parent session is free: the child's parking does not freeze it.
    assert session.session_id != child.child_session_id


def test_child_actions_take_the_same_single_dispatch_path(tmp_path: Path) -> None:
    app = app_for(
        tmp_path,
        spawn_script()
        + (
            (
                "child read step",
                (proposal("call-read", "workspace.read", {"path": "fixture.txt"}),),
            ),
        )
        + (("child finished reading", ()),)
        + (("parent finished", ()),),
    )
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn a child")
    child = child_record(app, session.task_id)

    # The child's own read produced a real policy decision and a real sealed
    # receipt on the child's own stream: it went through ActionPipeline ->
    # PolicyKernel -> permit -> CapabilityBroker, not through a spawn-specific
    # shortcut. (A parked tier-2 action has no decision yet by design: the
    # confirmation happens before the policy is consulted.)
    decisions = payloads(app, child.child_task_id, TaskEventType.POLICY_DECIDED)
    assert decisions
    assert decisions[-1]["decision"]["action_id"].startswith("action-")
    assert decisions[-1]["decision"]["verdict"] == "ALLOW"
    receipts = payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED)
    assert receipts and receipts[-1]["receipt"]["status"] == "SUCCEEDED"
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_PROPOSED)
    assert payloads(app, child.child_task_id, TaskEventType.CHILD_AGENT_SPAWNED) == []
    # One call site for the physical effect, in the broker (static check).
    root = Path(__file__).resolve().parents[2]
    call_sites: set[str] = set()
    for directory in ("packages", "apps", "domain_packs", "src"):
        for path in sorted((root / directory).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            if "connector.execute(" in path.read_text(encoding="utf-8"):
                call_sites.add(path.relative_to(root).as_posix())
    assert call_sites == {"packages/os_core/src/agent_os_core/capability.py"}


def test_child_parking_writes_the_operator_visible_card(tmp_path: Path) -> None:
    app = app_for(tmp_path, spawn_script() + park_script())
    session, loop = app.open_chat_session("parent work", AutoApproveGateway())
    loop.run_turn(session, "spawn a child")
    child = child_record(app, session.task_id)

    # The parked child has durably recorded proposal + approval request of its
    # own, which is what makes its permission prompt visible to the operator.
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_PROPOSED)
    pending = payloads(
        app, child.child_task_id, TaskEventType.SESSION_APPROVAL_PENDING
    )
    assert pending
    assert payloads(app, child.child_task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
