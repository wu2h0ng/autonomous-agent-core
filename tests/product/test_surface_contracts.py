from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ApprovalDisposition,
    PendingSurfaceApproval,
    ProviderMessage,
    ProviderMessageRole,
    SURFACE_PROTOCOL_VERSION,
    SessionRef,
    SurfaceApprovalCommand,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceEventBatch,
    SurfaceOpenSessionCommand,
    SurfaceSessionSnapshot,
    SurfaceSessionStatus,
    SurfaceTurnCommand,
    SurfaceTurnResponse,
    TaskEvent,
    TaskEventType,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:cli:1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:mac:1",
    )


def event(*, task_id: str, sequence: int) -> TaskEvent:
    return TaskEvent(
        event_id=f"event:{sequence}",
        task_id=task_id,
        event_type=TaskEventType.SESSION_MESSAGE_RECORDED,
        payload_json="{}",
        occurred_at=NOW,
        sequence=sequence,
    )


def snapshot() -> SurfaceSessionSnapshot:
    return SurfaceSessionSnapshot(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        session=SessionRef(
            session_id="session:1",
            task_id="task:1",
            run_id="run:1",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
        ),
        envelope_id="envelope:1",
        expected_outcome_id="outcome:1",
        status=SurfaceSessionStatus.WAITING_APPROVAL,
        event_sequence=3,
        message_count=2,
        pending_approval=PendingSurfaceApproval(
            action_digest="digest:1",
            capability_id="capability:1",
            proposal_id="proposal:1",
            preview="write the report",
            requested_at=NOW,
        ),
        updated_at=NOW,
    )


def test_surface_turn_requires_version_sequence_and_idempotency() -> None:
    command = SurfaceTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        session_id="session:1",
        text="inspect the failing test",
        expected_event_sequence=12,
        idempotency_key="idem:turn:1",
        requested_at=NOW,
    )
    assert command.expected_event_sequence == 12
    with pytest.raises(ValidationError):
        SurfaceTurnCommand.model_validate(
            command.model_dump() | {"protocol_version": "2.0"}
        )


def test_surface_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SurfaceClientRef.model_validate(client().model_dump() | {"admin": True})


def test_surface_contracts_instantiate_remaining_required_fields() -> None:
    open_command = SurfaceOpenSessionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        statement="inspect task state",
        idempotency_key="idem:open:1",
        requested_at=NOW,
    )
    approval = SurfaceApprovalCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        session_id="session:1",
        action_digest="digest:1",
        disposition=ApprovalDisposition.APPROVE,
        reason="approved after review",
        expected_event_sequence=3,
        idempotency_key="idem:approval:1",
        requested_at=NOW,
    )
    correction = SurfaceCorrectionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        session_id="session:1",
        reason="stop and correct",
        expected_event_sequence=3,
        idempotency_key="idem:correction:1",
        requested_at=NOW,
    )
    response = SurfaceTurnResponse(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        snapshot=snapshot(),
        turn_id="turn:1",
        text="approval is pending",
        steps=(ProviderMessage(role=ProviderMessageRole.ASSISTANT, content="review"),),
        stop_reason="WAITING_APPROVAL",
        total_tokens=42,
    )

    assert open_command.statement == "inspect task state"
    assert approval.disposition is ApprovalDisposition.APPROVE
    assert correction.reason == "stop and correct"
    assert response.snapshot.pending_approval is not None


def test_surface_approval_rejects_revise_disposition() -> None:
    with pytest.raises(ValidationError):
        SurfaceApprovalCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=client(),
            session_id="session:1",
            action_digest="digest:1",
            disposition=ApprovalDisposition.REVISE,
            reason="needs changes",
            expected_event_sequence=3,
            idempotency_key="idem:approval:revise",
            requested_at=NOW,
        )


@pytest.mark.parametrize(
    ("events", "after_sequence"),
    [
        ((event(task_id="task:2", sequence=4),), 3),
        ((event(task_id="task:1", sequence=4), event(task_id="task:1", sequence=4)), 3),
        ((event(task_id="task:1", sequence=5), event(task_id="task:1", sequence=4)), 3),
        ((event(task_id="task:1", sequence=3),), 3),
    ],
)
def test_surface_event_batch_rejects_invalid_ownership_or_sequence(
    events: tuple[TaskEvent, ...], after_sequence: int
) -> None:
    with pytest.raises(ValidationError):
        SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id="task:1",
            after_sequence=after_sequence,
            next_sequence=4,
            events=events,
        )


def test_surface_event_batch_requires_next_sequence_to_match_last_event() -> None:
    with pytest.raises(ValidationError):
        SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id="task:1",
            after_sequence=3,
            next_sequence=0,
            events=(event(task_id="task:1", sequence=4),),
        )


def test_empty_surface_event_batch_requires_next_sequence_to_match_cursor() -> None:
    with pytest.raises(ValidationError):
        SurfaceEventBatch(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            task_id="task:1",
            after_sequence=3,
            next_sequence=4,
            events=(),
        )
