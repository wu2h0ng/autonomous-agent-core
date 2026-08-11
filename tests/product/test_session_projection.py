from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    ActionContract,
    AgentRun,
    Commitment,
    CorrectionEpochVector,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolCall,
    ProviderToolProposal,
    ResourceBudget,
    SessionRef,
    TaskEventDraft,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import (
    InvalidTransitionError,
    SQLiteTaskEventStore,
    SessionProjectionError,
    SessionProjector,
    TaskAggregate,
    TaskService,
)
from agent_os_core.session_projection import SessionLoopConfig


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
LOOP_CONFIG = SessionLoopConfig(
    max_steps_per_turn=7,
    max_provider_retries=1,
    max_turn_tokens=9_000,
    max_context_chars=4_000,
    loop_detection_threshold=2,
    system_prompt="frozen session prompt",
)


class DeterministicIdFactory:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, kind: str) -> str:
        self._next += 1
        return f"{kind}:{self._next}"


def committed_running_task(
    tmp_path: Path,
) -> tuple[
    SQLiteTaskEventStore,
    TaskService,
    TaskAggregate,
    AgentRun,
    ExpectedOutcome,
]:
    store = SQLiteTaskEventStore(tmp_path / "sessions.sqlite3")
    tasks = TaskService(
        store,
        id_factory=DeterministicIdFactory(),
        clock=lambda: NOW,
    )
    goal = Goal(
        goal_id="goal:1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="principal:local",
        created_at=NOW,
        statement="Maintain one durable supervised session",
    )
    task = tasks.create_task(goal)
    commitment = Commitment(
        commitment_id="commitment:1",
        task_id=task.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("durable transcript",),
        acceptance_criteria=("restart restores exact history",),
        authority_scopes=("workspace:read",),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("session closed",),
        expires_at=NOW + timedelta(hours=1),
    )
    workflow = WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:1",
        version=1,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        created_by=goal.created_by,
        created_at=NOW,
        policy_version="policy:1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="inspect",
                kind=NodeKind.TOOL,
                capability="workspace.read",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="inspect", target="done"),),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:1",
        task_id=task.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    tasks.commit_task(task.task_id, commitment, workflow, expected)
    running = tasks.start_run(task.task_id)
    assert running.run is not None
    return store, tasks, task, running.run, expected


def _ref(task_id: str, run_id: str) -> SessionRef:
    return SessionRef(
        session_id="session:1",
        task_id=task_id,
        run_id=run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )


def _append(
    store: SQLiteTaskEventStore,
    task_id: str,
    event_type: TaskEventType,
    payload: dict[str, object],
) -> None:
    events = store.read(task_id)
    store.append(
        task_id,
        expected_sequence=len(events),
        drafts=(
            TaskEventDraft.build(
                event_id=f"malformed:{len(events) + 1}",
                task_id=task_id,
                event_type=event_type,
                payload=payload,
                occurred_at=NOW,
                correlation_id=str(payload.get("session_id", task_id)),
                causation_id=events[-1].event_id,
            ),
        ),
    )


def _opened_stream(
    tmp_path: Path,
) -> tuple[SQLiteTaskEventStore, TaskService, SessionRef]:
    store, tasks, task, run, expected = committed_running_task(tmp_path)
    ref = _ref(task.task_id, run.run_id)
    tasks.open_session(
        ref,
        "envelope:1",
        expected.expected_outcome_id,
        loop_config=LOOP_CONFIG,
    )
    return store, tasks, ref


def malformed_session_stream(
    tmp_path: Path,
    *,
    message_indexes: tuple[int, ...],
) -> SQLiteTaskEventStore:
    store, tasks, ref = _opened_stream(tmp_path)
    for message_index in message_indexes:
        _append(
            store,
            ref.task_id,
            TaskEventType.SESSION_MESSAGE_RECORDED,
            {
                "session_id": ref.session_id,
                "message_index": message_index,
                "message": ProviderMessage(
                    role=ProviderMessageRole.USER,
                    content=f"message {message_index}",
                ).model_dump(mode="json"),
                "turn_id": f"turn:{message_index}",
            },
        )
    return store


def _action(ref: SessionRef) -> ActionContract:
    return ActionContract(
        action_id="action:1",
        task_id=ref.task_id,
        run_id=ref.run_id,
        node_id="turn:1-step:1-tool:1",
        principal_id="principal:local",
        tenant_id=ref.tenant_id,
        workspace_id=ref.workspace_id,
        capability_id="workspace.read",
        capability_version="1",
        arguments_json='{"path":"README.md"}',
        risk_tier=1,
        idempotency_key="action:1",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0.10"),
            max_duration_seconds=30,
            max_provider_tokens=1,
            max_tool_calls=1,
        ),
        policy_version="policy:1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        expected_outcome_id="expected:1",
        candidate_envelope_id="envelope:1",
        created_at=NOW,
    )


def _append_assistant_tool_call(
    store: SQLiteTaskEventStore,
    ref: SessionRef,
) -> None:
    _append_started_turn(store, ref)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 1,
            "message": ProviderMessage(
                role=ProviderMessageRole.ASSISTANT,
                content="",
                tool_calls=(
                    ProviderToolCall(
                        tool_call_id="proposal:1",
                        capability_id="workspace.read",
                        arguments_json='{"path":"README.md"}',
                    ),
                ),
            ).model_dump(mode="json"),
            "turn_id": "turn:1",
        },
    )


def _append_started_turn(
    store: SQLiteTaskEventStore,
    ref: SessionRef,
    *,
    user_text: str = "read the file",
) -> None:
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 0,
            "message": ProviderMessage(
                role=ProviderMessageRole.USER,
                content=user_text,
            ).model_dump(mode="json"),
            "turn_id": "turn:1",
        },
    )
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_TURN_STARTED,
        {
            "session_id": ref.session_id,
            "turn_id": "turn:1",
            "user_text": user_text,
        },
    )


def _append_pending(
    store: SQLiteTaskEventStore,
    ref: SessionRef,
    *,
    action_digest: str | None = None,
) -> None:
    action = _action(ref)
    proposal = ProviderToolProposal(
        proposal_id="proposal:1",
        capability_id="workspace.read",
        arguments_json='{"path":"README.md"}',
    )
    fingerprint = hashlib.sha256(
        f"{proposal.capability_id}\n{proposal.arguments_json}".encode("utf-8")
    ).hexdigest()
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_APPROVAL_PENDING,
        {
            "session_id": ref.session_id,
            "task_id": ref.task_id,
            "run_id": ref.run_id,
            "tenant_id": ref.tenant_id,
            "workspace_id": ref.workspace_id,
            "turn_id": "turn:1",
            "provider_proposal": proposal.model_dump(mode="json"),
            "action": action.model_dump(mode="json"),
            "preview": "Read README.md",
            "action_digest": action_digest or action.action_digest(),
            "assistant_message_index": 1,
            "proposal_index": 0,
            "steps": 1,
            "total_tokens": 10,
            "seen_action_digests": {fingerprint: 1},
            "configuration_snapshot_id": "snapshot:1",
            "configuration_snapshot_digest": "1" * 64,
            "provider_profile_id": "provider:1",
            "provider_profile_digest": "2" * 64,
            "c7_epochs": action.observed_correction_epochs.model_dump(mode="json"),
            "requested_at": NOW.isoformat(),
        },
    )


def _append_resolution(
    store: SQLiteTaskEventStore,
    ref: SessionRef,
    *,
    action_digest: str | None = None,
) -> None:
    action = _action(ref)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
        {
            "session_id": ref.session_id,
            "task_id": ref.task_id,
            "run_id": ref.run_id,
            "tenant_id": ref.tenant_id,
            "workspace_id": ref.workspace_id,
            "turn_id": "turn:1",
            "action_digest": action_digest or action.action_digest(),
            "proposal_id": "proposal:1",
            "approval_id": "approval:1",
            "disposition": "APPROVE",
            "tool_message_index": 2,
            "resolved_at": NOW.isoformat(),
        },
    )


def test_projector_restores_exact_ordered_transcript(tmp_path: Path) -> None:
    store, tasks, task, run, expected = committed_running_task(tmp_path)
    ref = SessionRef(
        session_id="session:durable",
        task_id=task.task_id,
        run_id=run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    tasks.open_session(
        ref,
        "envelope:1",
        expected.expected_outcome_id,
        loop_config=LOOP_CONFIG,
    )
    tasks.record_session_message(
        task.task_id,
        ref.session_id,
        0,
        ProviderMessage(role=ProviderMessageRole.SYSTEM, content="system"),
        turn_id=None,
    )
    tasks.record_session_message(
        task.task_id,
        ref.session_id,
        1,
        ProviderMessage(role=ProviderMessageRole.USER, content="inspect"),
        turn_id="turn:1",
    )
    tasks.append_event(
        task.task_id,
        TaskEventType.SESSION_TURN_STARTED,
        {
            "session_id": ref.session_id,
            "turn_id": "turn:1",
            "user_text": "inspect",
        },
        correlation_id=ref.session_id,
    )

    restarted = SQLiteTaskEventStore(store.path)
    projected = SessionProjector(restarted).project(task.task_id, ref.session_id)

    assert projected.ref == ref
    assert projected.loop_config == LOOP_CONFIG
    assert projected.resumable_turn_id == "turn:1"
    assert [message.content for message in projected.history] == ["system", "inspect"]
    assert projected.next_message_index == 2
    assert projected.opened_sequence == 4
    assert projected.last_sequence == 7
    assert projected.closed is False
    assert projected.pending_approval is None
    restarted.close()
    store.close()


def test_projector_rejects_message_index_gap(tmp_path: Path) -> None:
    store = malformed_session_stream(tmp_path, message_indexes=(0, 2))
    with pytest.raises(SessionProjectionError, match="contiguous"):
        SessionProjector(store).project("task:1", "session:1")


def test_projector_rejects_duplicate_open(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    first_open = store.read(ref.task_id)[-1].decoded_payload()
    _append(store, ref.task_id, TaskEventType.SESSION_OPENED, first_open)

    with pytest.raises(SessionProjectionError, match="duplicate open"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_open_config_with_unknown_field(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    opened = store.read(ref.task_id)[-1]
    payload = opened.decoded_payload()
    payload["agent_loop_config"]["unknown"] = True
    replacement = TaskEventDraft.build(
        event_id=opened.event_id,
        task_id=opened.task_id,
        event_type=opened.event_type,
        payload=payload,
        occurred_at=opened.occurred_at,
        correlation_id=opened.correlation_id,
        causation_id=opened.causation_id,
    )
    store._db.execute(  # noqa: SLF001 - deliberate durable corruption fixture
        "UPDATE task_events SET payload_json = ? WHERE event_id = ?",
        (replacement.payload_json, opened.event_id),
    )
    store._db.commit()  # noqa: SLF001 - deliberate durable corruption fixture

    with pytest.raises(SessionProjectionError, match="configuration fields"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_open_config_digest_mismatch(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    opened = store.read(ref.task_id)[-1]
    payload = opened.decoded_payload()
    payload["agent_loop_config_digest"] = "0" * 64
    replacement = TaskEventDraft.build(
        event_id=opened.event_id,
        task_id=opened.task_id,
        event_type=opened.event_type,
        payload=payload,
        occurred_at=opened.occurred_at,
        correlation_id=opened.correlation_id,
        causation_id=opened.causation_id,
    )
    store._db.execute(  # noqa: SLF001 - deliberate durable corruption fixture
        "UPDATE task_events SET payload_json = ? WHERE event_id = ?",
        (replacement.payload_json, opened.event_id),
    )
    store._db.commit()  # noqa: SLF001 - deliberate durable corruption fixture

    with pytest.raises(SessionProjectionError, match="configuration digest"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_two_open_turns(tmp_path: Path) -> None:
    store, tasks, ref = _opened_stream(tmp_path)
    for message_index, turn_id in enumerate(("turn:1", "turn:2")):
        text = f"request {message_index}"
        tasks.record_session_message(
            ref.task_id,
            ref.session_id,
            message_index,
            ProviderMessage(role=ProviderMessageRole.USER, content=text),
            turn_id=turn_id,
        )
        tasks.append_event(
            ref.task_id,
            TaskEventType.SESSION_TURN_STARTED,
            {
                "session_id": ref.session_id,
                "turn_id": turn_id,
                "user_text": text,
            },
            correlation_id=ref.session_id,
        )

    with pytest.raises(SessionProjectionError, match="more than one open turn"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_orphan_user_turn(tmp_path: Path) -> None:
    store, tasks, ref = _opened_stream(tmp_path)
    tasks.record_session_message(
        ref.task_id,
        ref.session_id,
        0,
        ProviderMessage(role=ProviderMessageRole.USER, content="orphan"),
        turn_id="turn:orphan",
    )

    with pytest.raises(SessionProjectionError, match="no matching turn start"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_system_message_with_turn_binding(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 0,
            "message": ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content="system",
            ).model_dump(mode="json"),
            "turn_id": "turn:1",
        },
    )

    with pytest.raises(SessionProjectionError, match="system message.*turn binding"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_assistant_message_without_turn_binding(
    tmp_path: Path,
) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_started_turn(store, ref)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 1,
            "message": ProviderMessage(
                role=ProviderMessageRole.ASSISTANT,
                content="done",
            ).model_dump(mode="json"),
            "turn_id": None,
        },
    )

    with pytest.raises(SessionProjectionError, match="assistant message.*turn binding"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_tool_message_without_turn_binding(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 2,
            "message": ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="result",
                tool_call_id="proposal:1",
            ).model_dump(mode="json"),
            "turn_id": None,
        },
    )

    with pytest.raises(SessionProjectionError, match="tool message.*turn binding"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_open_scope_mismatch(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    events = store.read(ref.task_id)
    opened = events[-1]
    payload = opened.decoded_payload()
    payload["session"] = ref.model_copy(update={"run_id": "run:forged"}).model_dump(
        mode="json"
    )
    replacement = TaskEventDraft.build(
        event_id=opened.event_id,
        task_id=opened.task_id,
        event_type=opened.event_type,
        payload=payload,
        occurred_at=opened.occurred_at,
        correlation_id=opened.correlation_id,
        causation_id=opened.causation_id,
    )
    store._db.execute(  # noqa: SLF001 - deliberate durable corruption fixture
        "UPDATE task_events SET payload_json = ? WHERE event_id = ?",
        (replacement.payload_json, opened.event_id),
    )
    store._db.commit()  # noqa: SLF001 - deliberate durable corruption fixture

    with pytest.raises(SessionProjectionError, match="scope mismatch"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_invalid_provider_message(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 0,
            "message": {"role": "TOOL", "content": "orphan"},
            "turn_id": "turn:1",
        },
    )

    with pytest.raises(SessionProjectionError, match="invalid message"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_orphan_tool_message(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 0,
            "message": ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="result",
                tool_call_id="proposal:missing",
            ).model_dump(mode="json"),
            "turn_id": "turn:1",
        },
    )

    with pytest.raises(SessionProjectionError, match="tool binding"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_multiple_unresolved_approvals(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append_pending(store, ref)
    _append_pending(store, ref)

    with pytest.raises(SessionProjectionError, match="unresolved pending approval"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_pending_action_digest_mismatch(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append_pending(store, ref, action_digest="0" * 64)

    with pytest.raises(SessionProjectionError, match="action digest"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_close_and_turn_completion_cannot_bypass_pending_approval(
    tmp_path: Path,
) -> None:
    store, tasks, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append_pending(store, ref)

    with pytest.raises(InvalidTransitionError, match="unresolved pending"):
        tasks.close_session(ref.task_id, ref.session_id)

    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_TURN_COMPLETED,
        {
            "session_id": ref.session_id,
            "turn_id": "turn:1",
            "stop_reason": "forged",
            "steps": 1,
            "total_tokens": 10,
        },
    )
    with pytest.raises(SessionProjectionError, match="unresolved approval"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_projector_rejects_resolution_without_pending(tmp_path: Path) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append_resolution(store, ref)

    with pytest.raises(SessionProjectionError, match="no exact pending"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_public_writer_cannot_append_pending_or_resolution_events(
    tmp_path: Path,
) -> None:
    store, tasks, ref = _opened_stream(tmp_path)

    for event_type in (
        TaskEventType.SESSION_APPROVAL_PENDING,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    ):
        with pytest.raises(InvalidTransitionError, match="typed writer"):
            tasks.append_event(
                ref.task_id,
                event_type,
                {"session_id": ref.session_id},
                correlation_id=ref.run_id,
            )


def test_projector_rejects_resolution_with_wrong_action_digest(
    tmp_path: Path,
) -> None:
    store, _, ref = _opened_stream(tmp_path)
    _append_assistant_tool_call(store, ref)
    _append_pending(store, ref)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 2,
            "message": ProviderMessage(
                role=ProviderMessageRole.TOOL,
                content="result",
                tool_call_id="proposal:1",
            ).model_dump(mode="json"),
            "turn_id": "turn:1",
        },
    )
    _append_resolution(store, ref, action_digest="0" * 64)

    with pytest.raises(SessionProjectionError, match="resolution binding"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


def test_pending_approval_is_aggregate_provenance_only(tmp_path: Path) -> None:
    store, tasks, ref = _opened_stream(tmp_path)
    before = tasks.get_task(ref.task_id)
    _append_assistant_tool_call(store, ref)
    _append_pending(store, ref)

    rehydrated = tasks.get_task(ref.task_id)

    assert rehydrated.status is before.status
    assert rehydrated.run == before.run
    assert rehydrated.workflow == before.workflow
    assert rehydrated.expected_outcome == before.expected_outcome
    assert rehydrated.sequence == before.sequence + 4


def test_projector_rejects_message_after_close(tmp_path: Path) -> None:
    store, tasks, ref = _opened_stream(tmp_path)
    tasks.close_session(ref.task_id, ref.session_id)
    _append(
        store,
        ref.task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": ref.session_id,
            "message_index": 0,
            "message": ProviderMessage(
                role=ProviderMessageRole.USER,
                content="too late",
            ).model_dump(mode="json"),
            "turn_id": "turn:late",
        },
    )

    with pytest.raises(SessionProjectionError, match="after close"):
        SessionProjector(store).project(ref.task_id, ref.session_id)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "run:forged"),
        ("tenant_id", "tenant:forged"),
        ("workspace_id", "workspace:forged"),
    ),
)
def test_open_writer_rejects_scope_mismatch_before_append(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    store, tasks, task, run, expected = committed_running_task(tmp_path)
    ref = _ref(task.task_id, run.run_id).model_copy(update={field: value})
    before = len(store.read(task.task_id))

    with pytest.raises(InvalidTransitionError, match="session scope mismatch"):
        tasks.open_session(
            ref,
            "envelope:1",
            expected.expected_outcome_id,
            loop_config=LOOP_CONFIG,
        )

    assert len(store.read(task.task_id)) == before


def test_close_writer_marks_session_closed(tmp_path: Path) -> None:
    store, tasks, ref = _opened_stream(tmp_path)

    tasks.close_session(ref.task_id, ref.session_id)

    projected = SessionProjector(store).project(ref.task_id, ref.session_id)
    assert projected.closed is True
    assert projected.last_sequence == 5
