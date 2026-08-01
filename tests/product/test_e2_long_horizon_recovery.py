"""Bounded E2 long-horizon recovery acceptance suite (Product Track, local slice).

These tests drive the real ``AgentOSApplication`` composition root against real
SQLite event storage and a real filesystem workspace (including a real pytest
subprocess through the evaluator). They exercise the *public* signal, replan,
correction-resume and compensation entry points and reconstruct the task from an
append-only event stream in a fresh process. They deliberately assert on event
counts and order, terminal statuses, and physical file contents so the suite
fails if the wait, rebind, compensation or C7 correction path is bypassed.

Scope boundary: this is a local Product Track acceptance of one bounded durable
long-horizon vertical. It is NOT ``LH-RECOVERY-1``, and it establishes no claim
of full autonomy, 7x24 production operation, general long-horizon advantage or
self-evolution. See
``docs/superpowers/specs/2026-07-12-agent-os-e2e-long-horizon-convergence-design.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    ActionContract,
    CompensationStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_core import (
    ConcurrentWriteError,
    DeterministicProvider,
    ReplanRejectedError,
    RunExecutionError,
    WorkerInterrupted,
)
from apps.api_server.app import AgentOSApplication

TENANT = "tenant:local"
WORKSPACE = "workspace:local"
USER = "user:local"
EVALUATOR_REF = "evaluator:pytest:1"
INPUTS = {"target_path": "fixture.txt", "test_command": "python -m pytest"}


# ---------------------------------------------------------------------------
# Local, minimal helpers (no imports from other test modules).
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_workspace(root: Path, *, expected_content: str) -> None:
    """Real workspace with a real pytest that only passes for ``expected_content``."""

    (root / "fixture.txt").write_text("before\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n"
        f"    assert open('fixture.txt').read() == {expected_content!r}\n",
        encoding="utf-8",
    )


def _apply_proposal(content: str) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=f"proposal:{content.strip() or 'empty'}",
        capability_id="workspace.apply_patch",
        arguments_json=json.dumps({"path": "fixture.txt", "content": content}),
    )


def _patch_provider(content: str) -> DeterministicProvider:
    return DeterministicProvider(text="", tool_proposals=(_apply_proposal(content),))


def _read_node() -> NodeSpec:
    return NodeSpec(
        node_id="read",
        kind=NodeKind.TOOL,
        capability="workspace.read",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )


def _wait_node() -> NodeSpec:
    return NodeSpec(
        node_id="wait",
        kind=NodeKind.WAIT_EVENT,
        wait_signal_name="build.finished",
        wait_correlation_key="build:7",
        timeout_seconds=3600,
    )


def _apply_node() -> NodeSpec:
    return NodeSpec(
        node_id="apply",
        kind=NodeKind.TOOL,
        capability="workspace.apply_patch",
        idempotency=IdempotencyMode.COMPENSATABLE,
    )


def _tests_node() -> NodeSpec:
    return NodeSpec(
        node_id="tests",
        kind=NodeKind.TOOL,
        capability="workspace.run_tests",
        idempotency=IdempotencyMode.IDEMPOTENT,
    )


def _evaluate_node() -> NodeSpec:
    return NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION)


def _done_node() -> NodeSpec:
    return NodeSpec(node_id="done", kind=NodeKind.TERMINAL)


def _graph(
    workflow_id: str,
    version: int,
    nodes: tuple[NodeSpec, ...],
    edges: tuple[tuple[str, str], ...],
    now: datetime,
) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=workflow_id,
        version=version,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        created_by=USER,
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=(EVALUATOR_REF,),
        nodes=nodes,
        edges=tuple(EdgeSpec(source=s, target=t) for s, t in edges),
        max_replans=1,
    )


def _wait_then_draft_v1(now: datetime) -> WorkflowGraph:
    """A committed v1 that reads, waits for an external signal, then stubs out."""

    nodes = (
        _read_node(),
        _wait_node(),
        NodeSpec(node_id="draft", kind=NodeKind.TRANSFORM),
        _evaluate_node(),
        _done_node(),
    )
    edges = (
        ("read", "wait"),
        ("wait", "draft"),
        ("draft", "evaluate"),
        ("evaluate", "done"),
    )
    return _graph("workflow:e2-wait", 1, nodes, edges, now)


def _wait_then_patch_v2(now: datetime) -> WorkflowGraph:
    """Authorized v2 rebind: keep the completed read+wait prefix, rebind the suffix."""

    nodes = (
        _read_node(),
        _wait_node(),
        NodeSpec(
            node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        _apply_node(),
        _tests_node(),
        _evaluate_node(),
        _done_node(),
    )
    edges = (
        ("read", "wait"),
        ("wait", "provider"),
        ("provider", "approve"),
        ("approve", "apply"),
        ("apply", "tests"),
        ("tests", "evaluate"),
        ("evaluate", "done"),
    )
    return _graph("workflow:e2-wait", 2, nodes, edges, now)


def _patch_then_verify(now: datetime) -> WorkflowGraph:
    """Golden patch-and-verify graph used for the failure/compensation scenarios."""

    nodes = (
        _read_node(),
        NodeSpec(
            node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        _apply_node(),
        _tests_node(),
        _evaluate_node(),
        _done_node(),
    )
    edges = (
        ("read", "provider"),
        ("provider", "approve"),
        ("approve", "apply"),
        ("apply", "tests"),
        ("tests", "evaluate"),
        ("evaluate", "done"),
    )
    return _graph("workflow:e2-patch", 1, nodes, edges, now)


def _commit(
    app: AgentOSApplication, now: datetime, workflow: WorkflowGraph, *, goal_id: str
) -> str:
    task = app.create_task(
        {
            "goal_id": goal_id,
            "tenant_id": TENANT,
            "workspace_id": WORKSPACE,
            "created_by": USER,
            "created_at": now,
            "statement": "bounded long-horizon recovery vertical",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": f"commitment:{goal_id}",
                "task_id": task.task_id,
                "goal_id": goal_id,
                "tenant_id": TENANT,
                "workspace_id": WORKSPACE,
                "accepted_by": USER,
                "accepted_at": now,
                "deliverables": ["verified fixture patch"],
                "acceptance_criteria": ["pytest passes"],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 3600,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 20,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": now + timedelta(hours=1),
            },
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": f"expected:{goal_id}",
                "task_id": task.task_id,
                "tenant_id": TENANT,
                "workspace_id": WORKSPACE,
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": now,
            },
        },
    )
    return task.task_id


def _configured(
    app: AgentOSApplication, provider: DeterministicProvider
) -> AgentOSApplication:
    app.provider = provider
    app.provider_configured = True
    return app


def _event_types(app: AgentOSApplication, task_id: str) -> list[TaskEventType]:
    return [event.event_type for event in app.store.read(task_id)]


def _completed_nodes(app: AgentOSApplication, task_id: str) -> list[str]:
    nodes: list[str] = []
    for event in app.store.read(task_id):
        if event.event_type is not TaskEventType.NODE_COMPLETED:
            continue
        node_id = event.decoded_payload().get("node_id")
        if isinstance(node_id, str):
            nodes.append(node_id)
    return nodes


def _apply_patch_receipts(app: AgentOSApplication, task_id: str) -> list[dict]:
    receipts: list[dict] = []
    for event in app.store.read(task_id):
        if event.event_type is not TaskEventType.ACTION_RECEIPT_RECORDED:
            continue
        receipt = event.decoded_payload().get("receipt")
        if (
            isinstance(receipt, dict)
            and receipt.get("connector_id") == "workspace.apply_patch"
        ):
            receipts.append(receipt)
    return receipts


def _run_id(app: AgentOSApplication, task_id: str) -> str:
    run = app.tasks.get_task(task_id).run
    assert run is not None
    return run.run_id


# ---------------------------------------------------------------------------
# Scenario A — success across wait, restart, signal, one authorized v2 rebind.
# ---------------------------------------------------------------------------


def test_a_wait_signal_rebind_reaches_verified(tmp_path: Path) -> None:
    _write_workspace(tmp_path, expected_content="after\n")
    database = tmp_path / "agent-os.sqlite3"
    now = _now()

    first = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        _patch_provider("after\n"),
    )
    task_id = _commit(first, now, _wait_then_draft_v1(now), goal_id="goal:e2-a")

    # v1 reads, then registers a durable wait and stops before any downstream node.
    waiting = first.run_task(task_id, INPUTS)
    assert waiting.status is TaskStatus.WAITING
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_EVENT
    assert waiting.run.wait_condition is not None
    assert _event_types(first, task_id).count(TaskEventType.WAIT_REGISTERED) == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"

    # The wait must not be bypassable: re-running with no signal is an event-stream no-op.
    before_noop = tuple(first.store.read(task_id))
    noop = first.run_task(task_id, INPUTS)
    assert noop.sequence == waiting.sequence
    assert tuple(first.store.read(task_id)) == before_noop
    assert "draft" not in _completed_nodes(first, task_id)

    # A fresh process reconstructs the task from the event store and accepts the signal.
    second = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        _patch_provider("after\n"),
    )
    assert second.task_json(task_id)["status"] == "WAITING"
    signal_payload = {
        "signal_id": "signal:build-7",
        "signal_name": "build.finished",
        "correlation_key": "build:7",
        "payload_json": json.dumps({"status": "passed"}),
        "evidence_refs": ("artifact:build-7",),
        "occurred_at": second.tasks.now(),
    }
    signalled = second.signal_task(task_id, dict(signal_payload))
    assert signalled.run is not None
    assert signalled.run.wait_condition is None
    tail = _event_types(second, task_id)[-3:]
    assert tail == [
        TaskEventType.EXTERNAL_SIGNAL_RECORDED,
        TaskEventType.WAIT_SATISFIED,
        TaskEventType.NODE_COMPLETED,
    ]
    assert _completed_nodes(second, task_id).count("wait") == 1

    # A duplicate signal is idempotent: no second wait satisfaction, no new node completion.
    duplicate = second.signal_task(task_id, dict(signal_payload))
    assert duplicate.sequence == signalled.sequence
    assert _event_types(second, task_id).count(TaskEventType.WAIT_SATISFIED) == 1

    # One authorized rebind replaces only the uncompleted suffix (read+wait preserved).
    second.pause_task(task_id)
    rebound = second.replan_task(
        task_id,
        {
            "workflow": _wait_then_patch_v2(now).model_dump(mode="json"),
            "reason": "bind the verified-build suffix after the signal",
        },
    )
    assert rebound.run is not None
    assert rebound.run.replan_count == 1
    assert rebound.run.workflow_version == 2
    assert _event_types(second, task_id).count(TaskEventType.RUN_PLAN_REBOUND) == 1

    # The rebind budget is exhausted; a second replan (still PAUSED) is rejected.
    with pytest.raises(ReplanRejectedError, match="budget"):
        second.replan_task(
            task_id,
            {
                "workflow": _wait_then_patch_v2(now).model_dump(mode="json"),
                "reason": "second replan must be rejected",
            },
        )

    # Resume through provider -> approval -> patch -> pytest -> evaluator to VERIFIED.
    proposed = second.run_task(task_id, INPUTS)
    assert proposed.run is not None
    assert proposed.run.status is RunStatus.WAITING_APPROVAL
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    second.record_approval(
        task_id, {"disposition": "APPROVE", "reason": "reviewed rebound patch"}
    )
    result = second.run_task(task_id, INPUTS)

    assert result.status is TaskStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "VERIFIED"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "after\n"
    assert set(_completed_nodes(second, task_id)) == {
        "read",
        "wait",
        "provider",
        "approve",
        "apply",
        "tests",
        "evaluate",
        "done",
    }

    # The workspace.apply_patch idempotency_key occurs exactly once in the full
    # ACTION_RECEIPT_RECORDED stream — proving logical idempotency, not just
    # that one receipt object is present.
    apply_receipts = _apply_patch_receipts(second, task_id)
    assert len(apply_receipts) == 1
    all_idem_keys = [
        event.decoded_payload().get("receipt", {}).get("idempotency_key")
        for event in second.store.read(task_id)
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    ]
    assert all_idem_keys.count(apply_receipts[0]["idempotency_key"]) == 1

    # The event-derived recovery projection agrees exactly with the stream.
    events = second.store.read(task_id)
    recovery = second.recovery_json(task_id)
    assert recovery["wait_registered_count"] == 1
    assert recovery["signal_satisfied_count"] == 1
    assert recovery["replan_count"] == 1
    assert recovery["compensation_count"] == 0
    assert recovery["outcome_status"] == "VERIFIED"
    assert recovery["event_sequence"] == events[-1].sequence
    assert (
        recovery["action_receipt_count"] >= recovery["unique_logical_action_count"] >= 1
    )


# ---------------------------------------------------------------------------
# Scenario B — failure after patch + worker interruption + restart-safe
# automatic compensation.
# ---------------------------------------------------------------------------


def _interrupt_after_bad_patch(tmp_path: Path) -> tuple[Path, str]:
    _write_workspace(
        tmp_path, expected_content="expected\n"
    )  # pytest fails for "bad\n"
    database = tmp_path / "agent-os.sqlite3"
    now = _now()
    app = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        _patch_provider("bad\n"),
    )
    task_id = _commit(app, now, _patch_then_verify(now), goal_id="goal:e2-b")

    proposed = app.run_task(task_id, INPUTS)
    assert proposed.run is not None
    assert proposed.run.status is RunStatus.WAITING_APPROVAL
    app.record_approval(
        task_id, {"disposition": "APPROVE", "reason": "exercise compensation path"}
    )

    # Interrupt after the patch physically lands but before the run reaches a terminal state.
    with pytest.raises(WorkerInterrupted):
        app.run_task(task_id, INPUTS, stop_after_node="apply")
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"
    return database, task_id


def test_literal_apply_interrupt_keeps_lease_until_natural_expiry(
    tmp_path: Path,
) -> None:
    """The public interruption seam must leave its durable lease fenced."""

    database, task_id = _interrupt_after_bad_patch(tmp_path)
    fresh = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )

    with pytest.raises(ConcurrentWriteError, match="leased"):
        fresh.run_task(task_id, INPUTS, recover_stale_lease=False)


def test_waiting_approval_normal_return_releases_lease(tmp_path: Path) -> None:
    _write_workspace(tmp_path, expected_content="after\n")
    database = tmp_path / "agent-os.sqlite3"
    now = _now()
    first = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        _patch_provider("after\n"),
    )
    task_id = _commit(
        first, now, _patch_then_verify(now), goal_id="goal:e2-lease-return"
    )

    waiting = first.run_task(task_id, INPUTS)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL

    fresh = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )
    replay = fresh.run_task(task_id, INPUTS, recover_stale_lease=False)
    assert replay.run is not None
    assert replay.run.status is RunStatus.WAITING_APPROVAL


def test_non_interrupt_failure_releases_lease(tmp_path: Path) -> None:
    _write_workspace(tmp_path, expected_content="expected\n")
    database = tmp_path / "agent-os.sqlite3"
    now = _now()
    first = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        _patch_provider("bad\n"),
    )
    task_id = _commit(
        first, now, _patch_then_verify(now), goal_id="goal:e2-lease-failure"
    )
    waiting = first.run_task(task_id, INPUTS)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    first.record_approval(
        task_id, {"disposition": "APPROVE", "reason": "exercise failure lease release"}
    )

    failed = first.run_task(task_id, INPUTS)
    assert failed.run is not None
    assert failed.run.status is RunStatus.FAILED

    fresh = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )
    # A second public call may fail for the same workflow reason, but must not
    # be rejected as an active concurrent lease.
    try:
        fresh.run_task(task_id, INPUTS, recover_stale_lease=False)
    except ConcurrentWriteError as exc:  # pragma: no cover - assertion detail
        pytest.fail(f"ordinary failure leaked its lease: {exc}")
    except RunExecutionError:
        pass


def test_b_not_met_after_restart_compensates_bad_patch(tmp_path: Path) -> None:
    database, task_id = _interrupt_after_bad_patch(tmp_path)

    restarted = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )
    result = restarted.run_task(task_id, INPUTS, recover_stale_lease=True)

    assert result.status is TaskStatus.FAILED
    assert result.run is not None
    assert result.run.status is RunStatus.FAILED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "NOT_MET"
    # Durable snapshot restored the original file from a brand-new process.
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"

    types = _event_types(restarted, task_id)
    assert types.count(TaskEventType.ACTION_COMPENSATED) == 1
    assert types.count(TaskEventType.COMPENSATION_STARTED) == 1
    # Exact durable order: original failure is preserved, then exactly one compensation
    # sequence: RUN_FAILED < COMPENSATION_STARTED < ACTION_COMPENSATED.
    assert (
        types.index(TaskEventType.RUN_FAILED)
        < types.index(TaskEventType.COMPENSATION_STARTED)
        < types.index(TaskEventType.ACTION_COMPENSATED)
    )

    compensations = [
        event.decoded_payload()["compensation"]
        for event in restarted.store.read(task_id)
        if event.event_type is TaskEventType.ACTION_COMPENSATED
    ]
    assert compensations[0]["status"] == CompensationStatus.COMPENSATED.value

    recovery = restarted.recovery_json(task_id)
    assert recovery["outcome_status"] == "NOT_MET"
    assert recovery["compensation_count"] == 1


def test_compensation_replays_exact_action_after_effect_before_receipt_crash(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_bad_patch(tmp_path)
    restarted = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )
    crashed = False

    def crash_compensation_after_effect(operation_slot, _intent_digest, effect):
        nonlocal crashed
        result = effect()
        if operation_slot.startswith("compensate:") and not crashed:
            crashed = True
            raise RuntimeError("crash after compensation broker effect")
        return result

    failed = restarted.run_task(
        task_id,
        INPUTS,
        recover_stale_lease=True,
        effect_custody=crash_compensation_after_effect,
    )
    assert failed.run is not None
    assert failed.run.status is RunStatus.FAILED
    assert crashed
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    assert not any(
        event.event_type is TaskEventType.ACTION_COMPENSATED
        for event in restarted.store.read(task_id)
    )

    restarted.compensate_task(task_id)

    compensation_actions = [
        ActionContract.model_validate(event.decoded_payload()["action"])
        for event in restarted.store.read(task_id)
        if event.event_type is TaskEventType.ACTION_PROPOSED
        and event.decoded_payload().get("action", {}).get("capability_id")
        == "workspace.compensate_patch"
    ]
    assert len(compensation_actions) == 2
    assert compensation_actions[0] == compensation_actions[1]
    assert sum(
        event.event_type is TaskEventType.ACTION_COMPENSATED
        for event in restarted.store.read(task_id)
    ) == 1


# ---------------------------------------------------------------------------
# Scenario C — C7 stays sovereign: it blocks automatic and manual compensation,
# an ordinary resume does not clear it, and only an external principal can
# resume the correction epoch and then request governed compensation.
# ---------------------------------------------------------------------------


def test_c_c7_blocks_recovery_until_principal_resumes_correction(
    tmp_path: Path,
) -> None:
    database, task_id = _interrupt_after_bad_patch(tmp_path)

    restarted = _configured(
        AgentOSApplication(database=database, workspace=tmp_path),
        DeterministicProvider(),
    )
    # External C7 correction halts the task before any recovery can run.
    restarted.correct_task(task_id, "external principal halt before recovery")

    # Resuming the run does not auto-compensate under a halt; the failure surfaces and
    # compensation is explicitly blocked, leaving the bad patch physically intact.
    with pytest.raises(RunExecutionError, match="node tests failed"):
        restarted.run_task(task_id, INPUTS, recover_stale_lease=True)
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"
    assert any(
        event.event_type is TaskEventType.COMPENSATION_BLOCKED
        for event in restarted.store.read(task_id)
    )
    assert not any(
        event.event_type is TaskEventType.ACTION_COMPENSATED
        for event in restarted.store.read(task_id)
    )

    # A manual compensation request is also blocked while C7 is halted; the block
    # produces a fresh COMPENSATION_BLOCKED entry without executing any rollback.
    blocked_count_before_manual = sum(
        1
        for e in restarted.store.read(task_id)
        if e.event_type is TaskEventType.COMPENSATION_BLOCKED
    )
    restarted.compensate_task(task_id)
    events_mid = list(restarted.store.read(task_id))
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"
    assert not any(e.event_type is TaskEventType.ACTION_COMPENSATED for e in events_mid)
    assert (
        sum(1 for e in events_mid if e.event_type is TaskEventType.COMPENSATION_BLOCKED)
        > blocked_count_before_manual
    )

    run_id = _run_id(restarted, task_id)

    # An ordinary run resume must NOT clear the correction authority.
    restarted.resume_task(task_id)
    assert restarted.correction.halted(task_id, run_id, "workspace.compensate_patch")

    # A worker principal cannot resume the correction epoch.
    worker = PrincipalIdentity(
        principal_id="worker:cannot-resume-c7",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        role=PrincipalRole.WORKER,
        authenticated_at=_now(),
    )
    with pytest.raises(PermissionError, match="principal authority"):
        restarted.resume_correction(
            task_id, "worker must not resume correction", principal=worker
        )
    assert restarted.correction.halted(task_id, run_id, "workspace.compensate_patch")
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "bad\n"

    # Only the external principal can resume the correction epoch; governed compensation
    # then restores the original file exactly once through policy/permit/broker.
    restarted.resume_correction(
        task_id, "principal resumes correction for governed rollback"
    )
    restarted.compensate_task(task_id)

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "before\n"
    final_events = list(restarted.store.read(task_id))
    assert (
        sum(e.event_type is TaskEventType.ACTION_COMPENSATED for e in final_events) == 1
    )

    # The CORRECTION_WRITTEN audit event produced by resume_correction (halted=False)
    # must precede the governed COMPENSATION_STARTED and ACTION_COMPENSATED in the
    # durable event sequence — proving the correction authority was restored before
    # any rollback could proceed.
    correction_resume_evt = next(
        e
        for e in final_events
        if e.event_type is TaskEventType.CORRECTION_WRITTEN
        and not e.decoded_payload().get("halted", True)
    )
    comp_started_evt = next(
        e for e in final_events if e.event_type is TaskEventType.COMPENSATION_STARTED
    )
    comp_done_evt = next(
        e for e in final_events if e.event_type is TaskEventType.ACTION_COMPENSATED
    )
    assert (
        correction_resume_evt.sequence
        < comp_started_evt.sequence
        < comp_done_evt.sequence
    )

    # Under a C7 halt the tests node is denied, so no NOT_MET outcome is ever observed;
    # recovery still counts exactly one governed compensation once correction is resumed.
    recovery = restarted.recovery_json(task_id)
    assert recovery["compensation_count"] == 1
    assert recovery["outcome_status"] is None
