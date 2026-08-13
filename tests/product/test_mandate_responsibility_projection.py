from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from agent_os_contracts import (
    AgentRun,
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    MandateResponsibilityViewStatus,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    MandateWorkspaceRecord,
    ObservedOutcome,
    OutcomeStatus,
    NodeKind,
    NodeSpec,
    ResourceBudget,
    ResponsibilityAttentionReason,
    ResponsibilityItemState,
    RunStatus,
    RatifiedMandateRef,
    TaskEventDraft,
    TaskEventType,
    TaskStatus,
    WaitCondition,
    WorkflowGraph,
    canonical_json,
    content_digest,
)
from agent_os_core import (
    MandateResponsibilityDenied,
    MandateResponsibilityPersistenceConflict,
    MandateResponsibilityProjector,
    SQLiteMandateResponsibilityStore,
    SQLiteTaskEventStore,
    TaskAggregate,
    TaskService,
)
from tests.product.test_mandate_responsibility_store import NOW, _connection, _setup


def _goal() -> Goal:
    return Goal(
        goal_id="goal-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="principal:owner",
        created_at=NOW,
        statement="Keep responsibility visible",
    )


def _commitment(*, expires_at=None) -> Commitment:
    return Commitment(
        commitment_id="commitment-1",
        task_id="task-1",
        goal_id="goal-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("view",),
        acceptance_criteria=("truthful",),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1"),
            max_duration_seconds=3600,
            max_provider_tokens=1000,
            max_tool_calls=10,
        ),
        risk_tier=1,
        exit_conditions=("verified",),
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def _expected(*, evaluator_type: str = "pytest") -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id="task-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type=evaluator_type,
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("non-zero exit",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )


def _outcome(status: OutcomeStatus) -> ObservedOutcome:
    return ObservedOutcome(
        observed_outcome_id=f"outcome:{status.value}",
        expected_outcome_id="expected-1",
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=status,
        score=1.0 if status is OutcomeStatus.VERIFIED else None,
        confidence=1.0,
        evidence_refs=("artifact:test",) if status is OutcomeStatus.VERIFIED else (),
        unresolved_gaps=("missing",) if status is OutcomeStatus.UNRESOLVED else (),
        observed_at=NOW + timedelta(seconds=30),
    )


def _aggregate(
    task_status: TaskStatus,
    run_status: RunStatus | None,
    *,
    outcome_status: OutcomeStatus | None = None,
    wait_condition: WaitCondition | None = None,
    expires_at=None,
    evaluator_type: str = "pytest",
) -> TaskAggregate:
    run = (
        None
        if run_status is None
        else AgentRun(
            run_id="run-1",
            task_id="task-1",
            commitment_id="commitment-1",
            workflow_id="workflow-1",
            workflow_version=1,
            workflow_digest="workflow-digest",
            expected_outcome_id="expected-1",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            status=run_status,
            created_at=NOW,
            wait_condition=wait_condition,
        )
    )
    outcome = None if outcome_status is None else _outcome(outcome_status)
    return TaskAggregate(
        task_id="task-1",
        sequence=4,
        status=task_status,
        goal=_goal(),
        commitment=_commitment(expires_at=expires_at),
        expected_outcome=_expected(evaluator_type=evaluator_type),
        run=run,
        observed_outcome=outcome,
        last_event_id="event-4",
    )


@pytest.mark.parametrize(
    ("task_status", "run_status", "outcome_status", "expected_state", "reason"),
    [
        (TaskStatus.DRAFT, None, None, ResponsibilityItemState.TRACKED, None),
        (TaskStatus.COMMITTED, None, None, ResponsibilityItemState.TRACKED, None),
        (TaskStatus.RUNNING, RunStatus.RUNNING, None, ResponsibilityItemState.TRACKED, None),
        (TaskStatus.VERIFYING, RunStatus.VERIFYING, None, ResponsibilityItemState.TRACKED, None),
        (TaskStatus.PAUSED, RunStatus.PAUSED, None, ResponsibilityItemState.NEEDS_ATTENTION, ResponsibilityAttentionReason.TASK_PAUSED),
        (TaskStatus.FAILED, RunStatus.FAILED, None, ResponsibilityItemState.NEEDS_ATTENTION, ResponsibilityAttentionReason.TASK_FAILED),
        (TaskStatus.CANCELLED, RunStatus.CANCELLED, None, ResponsibilityItemState.NEEDS_ATTENTION, ResponsibilityAttentionReason.TASK_CANCELLED),
        (TaskStatus.WAITING, RunStatus.WAITING_APPROVAL, None, ResponsibilityItemState.NEEDS_ATTENTION, ResponsibilityAttentionReason.WAITING_APPROVAL),
        (TaskStatus.COMPLETED, RunStatus.SUCCEEDED, OutcomeStatus.VERIFIED, ResponsibilityItemState.DONE_VERIFIED, None),
    ],
)
def test_closed_task_run_classification(
    task_status,
    run_status,
    outcome_status,
    expected_state,
    reason,
) -> None:
    state, reasons = MandateResponsibilityProjector.classify(
        _aggregate(task_status, run_status, outcome_status=outcome_status),
        None if outcome_status is None else _outcome(outcome_status),
        computed_at=NOW + timedelta(minutes=1),
        completed_at=NOW + timedelta(seconds=45),
    )
    assert state is expected_state
    assert reason is None or reason in reasons


@pytest.mark.parametrize(
    ("outcome_status", "reason"),
    [
        (OutcomeStatus.NOT_MET, ResponsibilityAttentionReason.OUTCOME_NOT_MET),
        (OutcomeStatus.UNRESOLVED, ResponsibilityAttentionReason.OUTCOME_UNRESOLVED),
        (OutcomeStatus.INVALID, ResponsibilityAttentionReason.OUTCOME_INVALID),
    ],
)
def test_outcome_failures_take_attention_precedence(outcome_status, reason) -> None:
    aggregate = _aggregate(
        TaskStatus.RUNNING,
        RunStatus.RUNNING,
        outcome_status=outcome_status,
    )
    state, reasons = MandateResponsibilityProjector.classify(
        aggregate,
        _outcome(outcome_status),
        computed_at=NOW + timedelta(minutes=1),
        completed_at=None,
    )
    assert state is ResponsibilityItemState.NEEDS_ATTENTION
    assert reason in reasons


def test_waiting_deadline_and_missing_condition_are_closed() -> None:
    condition = WaitCondition(
        node_id="wait",
        signal_name="external",
        correlation_key="key",
        registered_at=NOW,
        deadline=NOW + timedelta(minutes=5),
    )
    pre_state, pre_reasons = MandateResponsibilityProjector.classify(
        _aggregate(TaskStatus.WAITING, RunStatus.WAITING_EVENT, wait_condition=condition),
        None,
        computed_at=NOW + timedelta(minutes=4),
        completed_at=None,
    )
    boundary_state, boundary_reasons = MandateResponsibilityProjector.classify(
        _aggregate(TaskStatus.WAITING, RunStatus.WAITING_EVENT, wait_condition=condition),
        None,
        computed_at=condition.deadline,
        completed_at=None,
    )
    missing_state, missing_reasons = MandateResponsibilityProjector.classify(
        _aggregate(TaskStatus.WAITING, RunStatus.WAITING_EVENT),
        None,
        computed_at=NOW + timedelta(minutes=1),
        completed_at=None,
    )
    assert (pre_state, pre_reasons) == (ResponsibilityItemState.TRACKED, ())
    assert boundary_state is ResponsibilityItemState.NEEDS_ATTENTION
    assert ResponsibilityAttentionReason.WAIT_DEADLINE_ARRIVED in boundary_reasons
    assert missing_state is ResponsibilityItemState.UNKNOWN
    assert ResponsibilityAttentionReason.WAIT_CONDITION_MISSING in missing_reasons


def test_evaluator_expiry_and_terminal_without_outcome_fail_closed() -> None:
    unsupported = MandateResponsibilityProjector.classify(
        _aggregate(TaskStatus.RUNNING, RunStatus.RUNNING, evaluator_type="llm-judge"),
        None,
        computed_at=NOW + timedelta(minutes=1),
        completed_at=None,
    )
    expired = MandateResponsibilityProjector.classify(
        _aggregate(
            TaskStatus.RUNNING,
            RunStatus.RUNNING,
            expires_at=NOW + timedelta(seconds=1),
        ),
        None,
        computed_at=NOW + timedelta(minutes=1),
        completed_at=None,
    )
    terminal = MandateResponsibilityProjector.classify(
        _aggregate(TaskStatus.COMPLETED, RunStatus.SUCCEEDED),
        None,
        computed_at=NOW + timedelta(minutes=1),
        completed_at=NOW + timedelta(seconds=45),
    )
    assert unsupported == (
        ResponsibilityItemState.UNKNOWN,
        (ResponsibilityAttentionReason.UNSUPPORTED_EVALUATOR,),
    )
    assert ResponsibilityAttentionReason.COMMITMENT_EXPIRED in expired[1]
    assert ResponsibilityAttentionReason.TERMINAL_WITHOUT_OUTCOME in terminal[1]


def test_bad_linked_task_remains_visible_but_broken_mandate_join_fails_view(
    tmp_path,
) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    link = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    projector = MandateResponsibilityProjector(store, admin.tasks, clock=lambda: NOW)
    first = projector.project("mandate:build-agent-os", admin.principal)
    assert first.items[0].state is ResponsibilityItemState.TRACKED

    connection = _connection(database)
    try:
        connection.execute("DELETE FROM task_events WHERE task_id = ?", (task.task_id,))
        connection.commit()
    finally:
        connection.close()
    partial = projector.project("mandate:build-agent-os", admin.principal)
    assert partial.status is MandateResponsibilityViewStatus.PARTIAL_UNKNOWN
    assert partial.items[0].link == link
    assert partial.items[0].state is ResponsibilityItemState.UNKNOWN
    assert ResponsibilityAttentionReason.TASK_SOURCE_MISSING in partial.items[0].attention_reasons

    connection = _connection(database)
    try:
        connection.execute(
            "UPDATE mandate_workspace_records SET record_digest = ?",
            ("f" * 64,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(MandateResponsibilityPersistenceConflict, match="Workspace"):
        projector.project("mandate:build-agent-os", admin.principal)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "DELETE FROM task_events WHERE task_id = ?",
            ResponsibilityAttentionReason.TASK_SOURCE_MISSING,
        ),
        (
            "UPDATE task_events SET sequence = 2 WHERE task_id = ? AND sequence = 1",
            ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,
        ),
        (
            "UPDATE task_events SET payload_json = 'not-json' "
            "WHERE task_id = ? AND sequence = 1",
            ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,
        ),
    ],
)
def test_deleted_reordered_or_malformed_task_events_never_hide_link(
    tmp_path, mutation, reason
) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    link = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    connection = _connection(database)
    try:
        connection.execute(mutation, (task.task_id,))
        connection.commit()
    finally:
        connection.close()
    view = MandateResponsibilityProjector(
        store, admin.tasks, clock=lambda: NOW
    ).project("mandate:build-agent-os", admin.principal)
    assert view.items[0].link == link
    assert view.items[0].state is ResponsibilityItemState.UNKNOWN
    assert reason in view.items[0].attention_reasons


def test_schedule_gap_and_optimistic_mandate_guard_are_explicit(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    connection = _connection(database)
    try:
        connection.execute(
            """
            CREATE TABLE mandate_active_perception_schedule (
                schedule_id TEXT PRIMARY KEY, config_digest TEXT, principal_id TEXT,
                tenant_id TEXT, workspace_id TEXT, mandate_id TEXT,
                environment_binding_id TEXT, interval_seconds INTEGER,
                budget_window_seconds INTEGER, wake_budget_per_window INTEGER,
                query_budget_per_window INTEGER, feed_limit INTEGER,
                lease_seconds INTEGER, next_wake_at TEXT, window_started_at TEXT,
                wake_used INTEGER, query_used INTEGER, lease_owner TEXT,
                lease_fence INTEGER, lease_expires_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO mandate_active_perception_schedule VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
            (
                "schedule-1", "not-a-digest", "principal:owner", "tenant:local",
                "workspace:local", "mandate:build-agent-os", "binding-1", 60,
                600, 10, 10, 10, 30, NOW.isoformat(), NOW.isoformat(), 0, 0, 0,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    projector = MandateResponsibilityProjector(store, admin.tasks, clock=lambda: NOW)
    partial = projector.project("mandate:build-agent-os", admin.principal)
    assert partial.status is MandateResponsibilityViewStatus.PARTIAL_UNKNOWN
    assert partial.global_gaps == (
        ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,
    )

    class DriftingTaskService:
        def get_task(self, task_id: str):
            return admin.tasks.get_task(task_id)

        def current_outcome(self, task_id: str):
            connection = _connection(database)
            try:
                row = connection.execute(
                    "SELECT mandate_json FROM situated_mandates"
                ).fetchone()
                assert row is not None
                payload = __import__("json").loads(row[0])
                payload["correction_epoch"] = 1
                payload["version"] = 2
                connection.execute(
                    "UPDATE situated_mandates SET correction_epoch = 1, "
                    "mandate_version = 2, mandate_json = ?",
                    (canonical_json(payload),),
                )
                connection.commit()
            finally:
                connection.close()
            return admin.tasks.current_outcome(task_id)

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="changed"):
        MandateResponsibilityProjector(
            store, DriftingTaskService(), clock=lambda: NOW
        ).project("mandate:build-agent-os", admin.principal)


def test_projection_fails_closed_outside_operational_mandate_time_window(
    tmp_path,
) -> None:
    _, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )

    with pytest.raises(MandateResponsibilityDenied, match="active"):
        MandateResponsibilityProjector(
            store,
            admin.tasks,
            clock=lambda: NOW + timedelta(days=31),
        ).project("mandate:build-agent-os", admin.principal)


def test_same_epoch_operational_ref_digest_drift_marks_link_unknown(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    connection = _connection(database)
    try:
        row = connection.execute(
            "SELECT mandate_json FROM situated_mandates"
        ).fetchone()
        assert row is not None
        operational = RatifiedMandateRef.model_validate_json(row[0])
        drifted = operational.model_copy(update={"ratified_by": "principal:replacement"})
        connection.execute(
            "UPDATE situated_mandates SET mandate_json = ?",
            (canonical_json(drifted),),
        )
        connection.commit()
    finally:
        connection.close()

    view = MandateResponsibilityProjector(
        store, admin.tasks, clock=lambda: NOW
    ).project("mandate:build-agent-os", admin.principal)
    assert view.status is MandateResponsibilityViewStatus.PARTIAL_UNKNOWN
    assert view.items[0].state is ResponsibilityItemState.UNKNOWN
    assert view.items[0].attention_reasons == (
        ResponsibilityAttentionReason.MANDATE_AUTHORITY_MISMATCH,
    )


def test_same_epoch_workspace_record_digest_drift_marks_link_unknown(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    connection = _connection(database)
    try:
        workspace_row = connection.execute(
            "SELECT record_json FROM mandate_workspace_records"
        ).fetchone()
        operational_row = connection.execute(
            "SELECT mandate_json FROM situated_mandates"
        ).fetchone()
        assert workspace_row is not None
        assert operational_row is not None
        workspace = MandateWorkspaceRecord.model_validate_json(workspace_row[0])
        changed_mission = workspace.standing_mission.model_copy(
            update={"active_commitment_ids": ("commitment:new",)}
        )
        drifted_workspace = workspace.model_copy(
            update={"standing_mission": changed_mission}
        )
        workspace_digest = content_digest(drifted_workspace)
        operational = RatifiedMandateRef.model_validate_json(operational_row[0])
        drifted_operational = operational.model_copy(
            update={"workspace_record_digest": workspace_digest}
        )
        connection.execute(
            "UPDATE mandate_workspace_records SET record_digest = ?, record_json = ?",
            (workspace_digest, canonical_json(drifted_workspace)),
        )
        connection.execute(
            "UPDATE situated_mandates SET mandate_json = ?",
            (canonical_json(drifted_operational),),
        )
        connection.commit()
    finally:
        connection.close()

    view = MandateResponsibilityProjector(
        store, admin.tasks, clock=lambda: NOW
    ).project("mandate:build-agent-os", admin.principal)
    assert view.status is MandateResponsibilityViewStatus.PARTIAL_UNKNOWN
    assert view.items[0].attention_reasons == (
        ResponsibilityAttentionReason.MANDATE_AUTHORITY_MISMATCH,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE mandate_responsibility_revocations "
        "SET record_json = 'not-json' WHERE link_id = ?",
        "UPDATE mandate_responsibility_revocations "
        "SET record_digest = 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' "
        "WHERE link_id = ?",
        "UPDATE mandate_responsibility_revocations "
        "SET tenant_id = 'tenant:other' WHERE link_id = ?",
    ],
)
def test_corrupt_revocation_cannot_silently_hide_responsibility_link(
    tmp_path, mutation
) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    link = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    store.revoke_link(
        MandateTaskLinkRevocationCommand(
            expected_link_digest=link.record_digest,
            reason="superseded",
        ),
        "mandate:build-agent-os",
        link.link_id,
        admin.principal,
    )
    connection = _connection(database)
    try:
        connection.execute(mutation, (link.link_id,))
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="revocation"):
        MandateResponsibilityProjector(
            store, admin.tasks, clock=lambda: NOW
        ).project("mandate:build-agent-os", admin.principal)


def test_projection_rechecks_active_link_set_after_current_outcome_read(
    tmp_path,
) -> None:
    _, _, admin, task, store = _setup(tmp_path)
    link = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )

    class RevokingTaskService:
        def get_task(self, task_id: str):
            return admin.tasks.get_task(task_id)

        def current_outcome(self, task_id: str):
            outcome = admin.tasks.current_outcome(task_id)
            store.revoke_link(
                MandateTaskLinkRevocationCommand(
                    expected_link_digest=link.record_digest,
                    reason="concurrent revocation",
                ),
                "mandate:build-agent-os",
                link.link_id,
                admin.principal,
            )
            return outcome

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="source changed"):
        MandateResponsibilityProjector(
            store, RevokingTaskService(), clock=lambda: NOW
        ).project("mandate:build-agent-os", admin.principal)


def test_projection_rechecks_task_event_stream_after_current_outcome_read(
    tmp_path,
) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )

    class MutatingTaskService:
        def get_task(self, task_id: str):
            return admin.tasks.get_task(task_id)

        def current_outcome(self, task_id: str):
            outcome = admin.tasks.current_outcome(task_id)
            connection = _connection(database)
            try:
                connection.execute(
                    "UPDATE task_events SET event_id = ? "
                    "WHERE task_id = ? AND sequence = 1",
                    ("event:concurrent-replacement", task_id),
                )
                connection.commit()
            finally:
                connection.close()
            return outcome

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="source changed"):
        MandateResponsibilityProjector(
            store, MutatingTaskService(), clock=lambda: NOW
        ).project("mandate:build-agent-os", admin.principal)


def test_digest_is_restart_stable_and_changes_with_task_source(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    first = MandateResponsibilityProjector(
        store, admin.tasks, clock=lambda: NOW
    ).project("mandate:build-agent-os", admin.principal)
    restarted_store = SQLiteMandateResponsibilityStore(database, clock=lambda: NOW)
    restarted_tasks = TaskService(SQLiteTaskEventStore(database), clock=lambda: NOW)
    replay = MandateResponsibilityProjector(
        restarted_store, restarted_tasks, clock=lambda: NOW + timedelta(seconds=1)
    ).project("mandate:build-agent-os", admin.principal)
    assert replay.view_digest == first.view_digest

    connection = _connection(database)
    try:
        connection.execute(
            "UPDATE task_events SET event_id = ? WHERE task_id = ? AND sequence = 1",
            ("event:replacement", task.task_id),
        )
        connection.commit()
    finally:
        connection.close()
    changed = MandateResponsibilityProjector(
        restarted_store, restarted_tasks, clock=lambda: NOW + timedelta(seconds=1)
    ).project("mandate:build-agent-os", admin.principal)
    assert changed.items[0].state is ResponsibilityItemState.UNKNOWN
    assert ResponsibilityAttentionReason.TASK_IDENTITY_CHANGED in changed.items[0].attention_reasons
    assert changed.view_digest != first.view_digest


def test_stale_verified_demotion_timestamp_is_excluded_from_view_digest(
    tmp_path,
) -> None:
    database, owner, admin, task, store = _setup(tmp_path)
    store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    assert task.goal is not None
    commitment = Commitment(
        commitment_id="commitment:stale-proof",
        task_id=task.task_id,
        goal_id=task.goal.goal_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        accepted_by="principal:owner",
        accepted_at=NOW,
        deliverables=("view",),
        acceptance_criteria=("tests pass",),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1"),
            max_duration_seconds=3600,
            max_provider_tokens=1000,
            max_tool_calls=10,
        ),
        risk_tier=1,
        exit_conditions=("verified",),
        expires_at=NOW + timedelta(hours=1),
    )
    workflow = WorkflowGraph(
        workflow_id="workflow:stale-proof",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="principal:owner",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="verify",
                kind=NodeKind.TOOL,
                capability="test.run",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="verify", target="done"),),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:stale-proof",
        task_id=task.task_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("non-zero exit",),
        threshold=1.0,
        observation_window_seconds=120,
        frozen_at=NOW,
    )
    owner.tasks.commit_task(task.task_id, commitment, workflow, expected)
    running = owner.tasks.start_run(task.task_id)
    assert running.run is not None
    historical = ObservedOutcome(
        observed_outcome_id="outcome:historical-verified",
        expected_outcome_id=expected.expected_outcome_id,
        task_id=task.task_id,
        run_id=running.run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("artifact:now-missing",),
        observed_at=NOW + timedelta(seconds=30),
    )
    outcome_event = TaskEventDraft.build(
        event_id="event:historical-outcome",
        task_id=task.task_id,
        event_type=TaskEventType.OUTCOME_OBSERVED,
        payload={"outcome": historical.model_dump(mode="json")},
        occurred_at=NOW + timedelta(seconds=30),
        correlation_id=running.run.run_id,
        causation_id=running.last_event_id,
    )
    succeeded_run = running.run.model_copy(update={"status": RunStatus.SUCCEEDED})
    succeeded_event = TaskEventDraft.build(
        event_id="event:run-succeeded",
        task_id=task.task_id,
        event_type=TaskEventType.RUN_SUCCEEDED,
        payload={"run": succeeded_run.model_dump(mode="json")},
        occurred_at=NOW + timedelta(seconds=45),
        correlation_id=running.run.run_id,
        causation_id=outcome_event.event_id,
    )
    event_store = SQLiteTaskEventStore(database)
    event_store.append(
        task.task_id,
        expected_sequence=running.sequence,
        drafts=(outcome_event, succeeded_event),
    )
    event_store.close()

    first_tasks = TaskService(
        SQLiteTaskEventStore(database), clock=lambda: NOW + timedelta(minutes=2)
    )
    second_tasks = TaskService(
        SQLiteTaskEventStore(database), clock=lambda: NOW + timedelta(minutes=3)
    )
    first = MandateResponsibilityProjector(
        store, first_tasks, clock=lambda: NOW + timedelta(minutes=4)
    ).project("mandate:build-agent-os", admin.principal)
    second = MandateResponsibilityProjector(
        SQLiteMandateResponsibilityStore(database, clock=lambda: NOW),
        second_tasks,
        clock=lambda: NOW + timedelta(minutes=4),
    ).project("mandate:build-agent-os", admin.principal)
    assert first.items[0].current_outcome is not None
    assert second.items[0].current_outcome is not None
    assert first.items[0].current_outcome.status is OutcomeStatus.UNRESOLVED
    assert first.items[0].current_outcome.observed_at != second.items[0].current_outcome.observed_at
    assert first.items[0].historical_outcome_digest == second.items[0].historical_outcome_digest
    assert first.view_digest == second.view_digest
