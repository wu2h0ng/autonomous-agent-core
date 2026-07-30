from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_core.responsibility_loop import (
    HcwEvaluatorRoot,
    HcwMeasurementStatus,
    OperatorWorkEventKind,
    ResponsibilityCycleState,
    ResponsibilityLoopEffectUnknown,
    ResponsibilityLoopBinding,
    ResponsibilityLoopLeaseHeld,
    ResponsibilityLoopStaleFence,
    SQLiteResponsibilityLoopStore,
)


NOW = datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc)


def _binding(root: Path) -> ResponsibilityLoopBinding:
    return ResponsibilityLoopBinding(
        mandate_id="mandate:loop-1",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        repository_root=str(root),
        repository_head="a" * 40,
        correction_epoch=0,
        configuration_digest="b" * 64,
        lease_ttl_seconds=30,
    )


def test_unexpired_loop_lease_blocks_second_process_and_expiry_fences_first(
    tmp_path: Path,
) -> None:
    """Removing live-lease rejection would permit duplicate responsibility execution."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)

    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    with pytest.raises(ResponsibilityLoopLeaseHeld):
        store.acquire_lease(
            binding,
            process_instance_id="process:B",
            now=NOW + timedelta(seconds=29),
        )

    second = store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )
    assert first.fencing_token == 1
    assert second.fencing_token == 2
    assert second.takeover is True
    assert store.list_audit_events(binding)[-1].event_type == "LOOP_LEASE_TAKEOVER"


def test_stale_process_cannot_checkpoint_after_takeover(tmp_path: Path) -> None:
    """Removing the checkpoint fence check would let stale Process A overwrite B."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )

    with pytest.raises(ResponsibilityLoopStaleFence):
        store.write_checkpoint(
            binding,
            first,
            state=ResponsibilityCycleState.RUNNING,
            active_task_id="task:1",
            active_run_id="run:1",
            last_event_sequence=1,
            next_transition="EXECUTE",
            recorded_at=NOW + timedelta(seconds=32),
        )


def test_stale_process_cannot_heartbeat_or_apply_effect_after_takeover(
    tmp_path: Path,
) -> None:
    """Checking the fence only at checkpoint would leave real effects bypassable."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )
    applied: list[str] = []

    with pytest.raises(ResponsibilityLoopStaleFence):
        store.heartbeat_lease(
            binding,
            first,
            heartbeat_at=NOW + timedelta(seconds=32),
        )
    with pytest.raises(ResponsibilityLoopStaleFence):
        store.execute_effect(
            binding,
            first,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=lambda: applied.append("applied"),
            executed_at=NOW + timedelta(seconds=32),
        )
    assert applied == []


def test_stable_logical_effect_key_executes_at_most_once(tmp_path: Path) -> None:
    """Generating a new key after restart would duplicate an already applied effect."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    applied: list[str] = []

    first = store.execute_effect(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        effect=lambda: applied.append("applied"),
        executed_at=NOW + timedelta(seconds=1),
    )
    replay = store.execute_effect(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        effect=lambda: applied.append("duplicate"),
        executed_at=NOW + timedelta(seconds=2),
    )
    assert applied == ["applied"]
    assert replay == first
    assert replay.status == "APPLIED"


def test_prepared_effect_survives_restart_as_unknown_instead_of_reexecution(
    tmp_path: Path,
) -> None:
    """Forgetting a crash-window reservation would silently repeat an unknown effect."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database)
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    prepared = store.prepare_effect(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        prepared_at=NOW + timedelta(seconds=1),
    )
    assert prepared.status == "PREPARED"

    restarted = SQLiteResponsibilityLoopStore(database)
    takeover = restarted.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )
    with pytest.raises(ResponsibilityLoopEffectUnknown):
        restarted.execute_effect(
            binding,
            takeover,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=lambda: pytest.fail("unknown effect must not be repeated"),
            executed_at=NOW + timedelta(seconds=32),
        )


def test_matching_clean_release_allows_immediate_reacquire(tmp_path: Path) -> None:
    """Leaking a clean-exit lease would wedge normal restart until its TTL."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    store.release_lease(binding, first, released_at=NOW + timedelta(seconds=1))

    second = store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=2),
    )
    assert second.fencing_token == 2
    assert second.takeover is False

    with pytest.raises(ResponsibilityLoopStaleFence):
        store.release_lease(
            binding,
            first,
            released_at=NOW + timedelta(seconds=3),
        )


def test_checkpoint_restores_from_sqlite_without_session_projection(
    tmp_path: Path,
) -> None:
    """Depending on terminal JSON instead of SQLite would break A-to-B recovery."""
    database = tmp_path / "agent-os.sqlite3"
    binding = _binding(tmp_path)
    first_store = SQLiteResponsibilityLoopStore(database)
    lease = first_store.acquire_lease(
        binding, process_instance_id="process:A", now=NOW
    )
    written = first_store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.WAITING_EVENT,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=7,
        next_transition="HELP_RESPONSE",
        recorded_at=NOW + timedelta(seconds=1),
    )

    restarted = SQLiteResponsibilityLoopStore(database)
    restored = restarted.latest_checkpoint(binding)
    assert restored is not None
    assert restored == written
    assert restored.active_task_id == "task:1"
    assert restored.last_event_sequence == 7
    assert restored.next_transition == "HELP_RESPONSE"


def test_hcw_receipt_uses_durable_events_and_accepted_outcome_denominator(
    tmp_path: Path,
) -> None:
    """Guessing duration or caller-supplying the denominator would create fake HCW."""
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3")
    binding = _binding(tmp_path)
    evaluator = HcwEvaluatorRoot(
        evaluator_root_id="hcw-evaluator:v1",
        measurement_policy_digest="c" * 64,
        capture_surface="agent-cli",
        idle_cutoff_seconds=60,
    )
    store.ensure_hcw_evaluator_root(evaluator)
    store.append_operator_work_event(
        binding,
        event_id="operator-event:1",
        kind=OperatorWorkEventKind.USER_INPUT,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.append_operator_work_event(
        binding,
        event_id="operator-event:2",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW + timedelta(seconds=30),
    )

    receipt = store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id=evaluator.evaluator_root_id,
        measured_at=NOW + timedelta(seconds=31),
    )
    assert receipt.operator_intervention_count == 2
    assert receipt.help_response_count == 1
    assert receipt.status is HcwMeasurementStatus.HCW_INSUFFICIENT_DATA
    assert receipt.active_operator_seconds is None
    assert receipt.accepted_outcome_count == 0
    assert receipt.operator_minutes_per_accepted_outcome is None
    assert receipt.measurement_policy_digest == evaluator.measurement_policy_digest
