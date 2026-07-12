from __future__ import annotations

from collections.abc import Sequence

from agent_os_contracts import RunRecoverySnapshot, TaskEvent, TaskEventType


def build_recovery_snapshot(
    events: Sequence[TaskEvent],
) -> RunRecoverySnapshot:
    """Project durable recovery counters without inferring physical exactly-once."""

    if not events:
        raise ValueError("recovery projection requires at least one event")
    task_ids = {event.task_id for event in events}
    if len(task_ids) != 1:
        raise ValueError("recovery projection requires one task stream")
    sequences = [event.sequence for event in events]
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise ValueError("recovery projection requires ordered unique sequences")

    run_id: str | None = None
    run_resumed_count = 0
    wait_registered_count = 0
    signal_satisfied_count = 0
    replan_count = 0
    compensation_count = 0
    action_receipt_count = 0
    logical_action_keys: set[str] = set()
    outcome_status: str | None = None

    for event in events:
        payload = event.decoded_payload()
        run_payload = payload.get("run")
        if isinstance(run_payload, dict):
            candidate = run_payload.get("run_id")
            if isinstance(candidate, str) and candidate:
                run_id = run_id or candidate
        if event.event_type is TaskEventType.RUN_RESUMED:
            run_resumed_count += 1
        elif event.event_type is TaskEventType.WAIT_REGISTERED:
            wait_registered_count += 1
        elif event.event_type is TaskEventType.WAIT_SATISFIED:
            signal_satisfied_count += 1
        elif event.event_type is TaskEventType.RUN_PLAN_REBOUND:
            replan_count += 1
        elif event.event_type is TaskEventType.ACTION_COMPENSATED:
            compensation_count += 1
            compensation = payload.get("compensation")
            if isinstance(compensation, dict):
                candidate = compensation.get("run_id")
                if isinstance(candidate, str) and candidate:
                    run_id = run_id or candidate
        elif event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED:
            action_receipt_count += 1
            receipt = payload.get("receipt")
            if isinstance(receipt, dict):
                key = receipt.get("idempotency_key")
                if isinstance(key, str) and key:
                    logical_action_keys.add(key)
        elif event.event_type is TaskEventType.OUTCOME_OBSERVED:
            outcome = payload.get("outcome")
            if isinstance(outcome, dict):
                status = outcome.get("status")
                candidate = outcome.get("run_id")
                if isinstance(status, str) and status:
                    outcome_status = status
                if isinstance(candidate, str) and candidate:
                    run_id = run_id or candidate

    if run_id is None:
        raise ValueError("recovery projection could not derive a run_id")
    return RunRecoverySnapshot(
        task_id=events[0].task_id,
        run_id=run_id,
        event_sequence=events[-1].sequence,
        run_resumed_count=run_resumed_count,
        wait_registered_count=wait_registered_count,
        signal_satisfied_count=signal_satisfied_count,
        replan_count=replan_count,
        compensation_count=compensation_count,
        action_receipt_count=action_receipt_count,
        unique_logical_action_count=len(logical_action_keys),
        outcome_status=outcome_status,
    )
