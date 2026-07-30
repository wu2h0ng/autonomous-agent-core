from __future__ import annotations

import json
import multiprocessing
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_core.responsibility_loop import (
    HcwEvaluatorRoot,
    HcwMeasurementStatus,
    OperatorWorkEventKind,
    ResponsibilityCycleState,
    ResponsibilityLoopEffectUnknown,
    ResponsibilityLoopBindingDrift,
    ResponsibilityLoopError,
    ResponsibilityLoopBinding,
    ResponsibilityLoopLeaseHeld,
    ResponsibilityLoopStaleFence,
    SQLiteResponsibilityLoopStore,
)
from agent_os_contracts import (
    OutcomePortfolio,
    PersistentCommitment,
    SettlementRecord,
    content_digest,
)


NOW = datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


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


def _effect_receipt(receipt_id: str = "effect-receipt:1") -> dict[str, str]:
    return {
        "receipt_id": receipt_id,
        "resource_ref": "repo:file.txt",
        "evidence_digest": "a" * 64,
    }


def _insert_verified_settlement(
    database: Path,
    binding: ResponsibilityLoopBinding,
    *,
    settlement_id: str,
    task_id: str,
) -> str:
    portfolio_payload = {
        "schema_version": "1.0",
        "portfolio_id": "portfolio:1",
        "principal_id": binding.principal_id,
        "tenant_id": binding.tenant_id,
        "workspace_id": binding.workspace_id,
        "mandate_id": binding.mandate_id,
        "desired_outcomes": ["outcome:1"],
        "workspace_record_digest": "1" * 64,
        "operational_mandate_ref_digest": "2" * 64,
        "correction_epoch": binding.correction_epoch,
        "created_by": binding.principal_id,
        "created_at": NOW,
        "command_digest": "3" * 64,
        "task_activation_authorized": False,
        "capability_grant_authorized": False,
        "external_effects_authorized": False,
    }
    portfolio_digest = content_digest(portfolio_payload)
    portfolio = OutcomePortfolio.model_validate(
        {**portfolio_payload, "record_digest": portfolio_digest}
    )
    commitment_payload = {
        "schema_version": "1.0",
        "commitment_record_id": f"commitment:{task_id}",
        "portfolio_id": portfolio.portfolio_id,
        "principal_id": binding.principal_id,
        "tenant_id": binding.tenant_id,
        "workspace_id": binding.workspace_id,
        "mandate_id": binding.mandate_id,
        "task_id": task_id,
        "commitment_digest": "4" * 64,
        "expected_outcome_digest": "d" * 64,
        "state": "SETTLED_MET",
        "workspace_record_digest": portfolio.workspace_record_digest,
        "operational_mandate_ref_digest": portfolio.operational_mandate_ref_digest,
        "correction_epoch": binding.correction_epoch,
        "attached_by": binding.principal_id,
        "attached_at": NOW,
        "command_digest": "5" * 64,
        "task_activation_authorized": False,
        "capability_grant_authorized": False,
        "external_effects_authorized": False,
    }
    commitment_digest = content_digest(commitment_payload)
    commitment = PersistentCommitment.model_validate(
        {**commitment_payload, "record_digest": commitment_digest}
    )
    settlement_payload = {
        "schema_version": "1.0",
        "settlement_id": settlement_id,
        "commitment_record_id": f"commitment:{task_id}",
        "portfolio_id": "portfolio:1",
        "mandate_id": binding.mandate_id,
        "task_id": task_id,
        "expected_outcome_digest": "d" * 64,
        "observed_outcome_digest": "e" * 64,
        "observed_status": "VERIFIED",
        "resulting_state": "SETTLED_MET",
        "settled_by": binding.principal_id,
        "settled_at": NOW,
        "command_digest": "f" * 64,
        "task_activation_authorized": False,
        "capability_grant_authorized": False,
        "external_effects_authorized": False,
    }
    record_digest = content_digest(settlement_payload)
    settlement = SettlementRecord.model_validate(
        {**settlement_payload, "record_digest": record_digest}
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS mandate_outcome_portfolios (
                portfolio_id TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                record_digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mandate_persistent_commitments (
                commitment_record_id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                mandate_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                record_digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mandate_outcome_settlements (
                settlement_id TEXT PRIMARY KEY,
                commitment_record_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                record_digest TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO mandate_outcome_portfolios VALUES (?,?,?,?,?,?,?)",
            (
                portfolio.portfolio_id,
                portfolio.mandate_id,
                portfolio.tenant_id,
                portfolio.workspace_id,
                portfolio.principal_id,
                portfolio.model_dump_json(),
                portfolio.record_digest,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO mandate_persistent_commitments "
            "VALUES (?,?,?,?,?,?,?)",
            (
                commitment.commitment_record_id,
                commitment.portfolio_id,
                commitment.mandate_id,
                commitment.task_id,
                commitment.state.value,
                commitment.model_dump_json(),
                commitment.record_digest,
            ),
        )
        connection.execute(
            "INSERT INTO mandate_outcome_settlements VALUES (?,?,?,?,?)",
            (
                settlement_id,
                f"commitment:{task_id}",
                "portfolio:1",
                settlement.model_dump_json(),
                record_digest,
            ),
        )
    return record_digest


def _wall_clock() -> datetime:
    return datetime.now(timezone.utc)


def _long_effect_worker(
    database: str,
    repository_root: str,
    queue: Any,
) -> None:
    store = SQLiteResponsibilityLoopStore(database, clock=_wall_clock)
    binding = replace(_binding(Path(repository_root)), lease_ttl_seconds=1)
    lease = store.acquire_lease(
        binding,
        process_instance_id="process:A",
        now=NOW,
    )
    queue.put(("A_ACQUIRED", lease.fencing_token))

    def effect() -> dict[str, str]:
        queue.put(("EFFECT_STARTED", lease.fencing_token))
        time.sleep(2)
        return _effect_receipt()

    try:
        store.execute_effect(
            binding,
            lease,
            cycle_id="cycle:mp",
            task_id="task:mp",
            operation_slot="workspace-edit:mp",
            intent_digest="d" * 64,
            effect=effect,
            executed_at=NOW,
        )
    except ResponsibilityLoopEffectUnknown:
        queue.put(("A_UNKNOWN", lease.fencing_token))
    else:
        queue.put(("A_APPLIED", lease.fencing_token))


def _takeover_worker(
    database: str,
    repository_root: str,
    queue: Any,
) -> None:
    store = SQLiteResponsibilityLoopStore(database, clock=_wall_clock)
    binding = replace(_binding(Path(repository_root)), lease_ttl_seconds=1)
    lease = store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW,
    )
    queue.put(("B_ACQUIRED", lease.fencing_token))


def test_unexpired_loop_lease_blocks_second_process_and_expiry_fences_first(
    tmp_path: Path,
) -> None:
    """Removing live-lease rejection would permit duplicate responsibility execution."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)

    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    clock.now = NOW + timedelta(seconds=29)
    with pytest.raises(ResponsibilityLoopLeaseHeld):
        store.acquire_lease(
            binding,
            process_instance_id="process:B",
            now=NOW + timedelta(seconds=29),
        )

    clock.now = NOW + timedelta(seconds=31)
    second = store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )
    assert first.fencing_token == 1
    assert second.fencing_token == 2
    assert second.takeover is True
    assert store.list_audit_events(binding)[-1].event_type == "LOOP_LEASE_TAKEOVER"


def test_same_scope_binding_drift_cannot_create_a_second_live_lease(
    tmp_path: Path,
) -> None:
    """Keying the lease by the full binding digest would allow authority drift to fork."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
    original = _binding(tmp_path)
    changed = replace(original, repository_head="c" * 40, correction_epoch=1)
    store.acquire_lease(original, process_instance_id="process:A", now=NOW)

    with pytest.raises(ResponsibilityLoopError):
        store.acquire_lease(
            changed,
            process_instance_id="process:B",
            now=NOW + timedelta(seconds=1),
        )


def test_repository_path_change_is_binding_drift_not_a_new_lease_scope(
    tmp_path: Path,
) -> None:
    """A path alias or repository move must not fork one Mandate/workspace lease."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
    original = _binding(tmp_path / "checkout-a")
    moved = replace(original, repository_root=str(tmp_path / "checkout-b"))
    store.acquire_lease(original, process_instance_id="process:A", now=NOW)
    with pytest.raises(ResponsibilityLoopError):
        store.acquire_lease(moved, process_instance_id="process:B", now=NOW)


def test_nonempty_v1_lease_ledger_requires_explicit_migration(tmp_path: Path) -> None:
    """A version upgrade must never silently ignore a prior live owner."""
    database = tmp_path / "agent-os.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE responsibility_loop_leases (
                binding_digest TEXT PRIMARY KEY,
                binding_json TEXT NOT NULL,
                process_instance_id TEXT,
                fencing_token INTEGER NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO responsibility_loop_leases VALUES (?,?,?,?,?,?)",
            ("a" * 64, "{}", "process:legacy", 7, NOW.isoformat(), NOW.isoformat()),
        )
    with pytest.raises(ResponsibilityLoopError):
        SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))


def test_stale_process_cannot_checkpoint_after_takeover(tmp_path: Path) -> None:
    """Removing the checkpoint fence check would let stale Process A overwrite B."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    clock.now = NOW + timedelta(seconds=31)
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
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    clock.now = NOW + timedelta(seconds=31)
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
            effect=lambda: (applied.append("applied"), _effect_receipt())[1],
            executed_at=NOW + timedelta(seconds=32),
        )
    assert applied == []


def test_stable_logical_effect_key_executes_at_most_once(tmp_path: Path) -> None:
    """Generating a new key after restart would duplicate an already applied effect."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
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
        effect=lambda: (applied.append("applied"), _effect_receipt())[1],
        executed_at=NOW + timedelta(seconds=1),
    )
    replay = store.execute_effect(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        effect=lambda: (applied.append("duplicate"), _effect_receipt("duplicate"))[1],
        executed_at=NOW + timedelta(seconds=2),
    )
    assert applied == ["applied"]
    assert replay == first
    assert replay.status == "APPLIED"
    assert replay.effect_receipt_digest == content_digest(
        {
            "effect_key": replay.effect_key,
            "intent_digest": "d" * 64,
            "adapter_receipt": _effect_receipt(),
        }
    )


def test_prepared_effect_survives_restart_as_unknown_instead_of_reexecution(
    tmp_path: Path,
) -> None:
    """Forgetting a crash-window reservation would silently repeat an unknown effect."""
    database = tmp_path / "agent-os.sqlite3"
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(database, clock=clock)
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

    restarted = SQLiteResponsibilityLoopStore(database, clock=clock)
    clock.now = NOW + timedelta(seconds=31)
    takeover = restarted.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW + timedelta(seconds=31),
    )

    def must_not_repeat() -> dict[str, str]:
        pytest.fail("unknown effect must not be repeated")

    with pytest.raises(ResponsibilityLoopEffectUnknown):
        restarted.execute_effect(
            binding,
            takeover,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=must_not_repeat,
            executed_at=NOW + timedelta(seconds=32),
        )


def test_effect_crossing_trusted_clock_ttl_cannot_be_marked_applied(
    tmp_path: Path,
) -> None:
    """An old caller timestamp must not authorize completion after real lease expiry."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3",
        clock=clock,
    )
    binding = _binding(tmp_path)
    lease = store.acquire_lease(
        binding,
        process_instance_id="process:A",
        now=NOW - timedelta(days=1),
    )

    def long_effect() -> dict[str, str]:
        clock.now = NOW + timedelta(seconds=31)
        return {
            "receipt_id": "effect-receipt:1",
            "resource_ref": "repo:file.txt",
            "evidence_digest": "a" * 64,
        }

    with pytest.raises(ResponsibilityLoopEffectUnknown):
        store.execute_effect(
            binding,
            lease,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=long_effect,
            executed_at=NOW - timedelta(days=1),
        )
    takeover = store.acquire_lease(
        binding,
        process_instance_id="process:B",
        now=NOW,
    )
    with pytest.raises(ResponsibilityLoopEffectUnknown):
        store.execute_effect(
            binding,
            takeover,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=lambda: pytest.fail("UNKNOWN effect must be reconciled, not replayed"),
            executed_at=NOW,
        )


@pytest.mark.parametrize("tampered_field", ["task_id", "intent_digest"])
def test_applied_effect_replay_rejects_ledger_identity_tampering(
    tmp_path: Path,
    tampered_field: str,
) -> None:
    """A self-consistent receipt cannot authenticate a mutated effect ledger row."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    store.execute_effect(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        effect=_effect_receipt,
        executed_at=NOW,
    )
    replacement = "task:tampered" if tampered_field == "task_id" else "e" * 64
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE responsibility_loop_effects_v2 SET {tampered_field}=?",
            (replacement,),
        )

    with pytest.raises(ResponsibilityLoopBindingDrift):
        store.execute_effect(
            binding,
            lease,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=lambda: pytest.fail("APPLIED effect must not execute again"),
            executed_at=NOW,
        )


def test_real_process_can_take_over_while_prior_effect_becomes_unknown(
    tmp_path: Path,
) -> None:
    """The external callback must not hold the takeover lock across its duration."""
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    database = str(tmp_path / "agent-os.sqlite3")
    repository_root = str(tmp_path)
    first = context.Process(
        target=_long_effect_worker,
        args=(database, repository_root, queue),
    )
    first.start()
    assert queue.get(timeout=5) == ("A_ACQUIRED", 1)
    assert queue.get(timeout=5) == ("EFFECT_STARTED", 1)
    time.sleep(1.2)

    second = context.Process(
        target=_takeover_worker,
        args=(database, repository_root, queue),
    )
    second.start()
    assert queue.get(timeout=5) == ("B_ACQUIRED", 2)
    assert queue.get(timeout=5) == ("A_UNKNOWN", 1)
    first.join(timeout=5)
    second.join(timeout=5)
    assert first.exitcode == 0
    assert second.exitcode == 0


def test_matching_clean_release_allows_immediate_reacquire(tmp_path: Path) -> None:
    """Leaking a clean-exit lease would wedge normal restart until its TTL."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)
    first = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    clock.now = NOW + timedelta(seconds=1)
    store.release_lease(binding, first, released_at=NOW + timedelta(seconds=1))

    clock.now = NOW + timedelta(seconds=2)
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


def test_inactive_scope_requires_explicit_binding_rebind(tmp_path: Path) -> None:
    """Authority changes must be explicit even after the prior owner releases."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    original = _binding(tmp_path)
    changed = replace(original, repository_head="c" * 40, correction_epoch=1)
    lease = store.acquire_lease(original, process_instance_id="process:A", now=NOW)
    store.write_checkpoint(
        original,
        lease,
        state=ResponsibilityCycleState.WAITING_EVENT,
        active_task_id=None,
        active_run_id=None,
        last_event_sequence=1,
        next_transition="WAIT",
        recorded_at=NOW,
    )
    store.release_lease(original, lease, released_at=NOW)

    with pytest.raises(ResponsibilityLoopError):
        store.acquire_lease(changed, process_instance_id="process:B", now=NOW)
    store.rebind_inactive_scope(
        original,
        changed,
        actor_principal_id="founder:1",
        reason="approved correction epoch transition",
        authority_ref="approval:rebind-1",
    )
    audit = store.list_audit_events(changed)[-1]
    assert audit.event_type == "LOOP_BINDING_REBOUND"
    assert audit.process_instance_id == "founder:1"
    with sqlite3.connect(tmp_path / "agent-os.sqlite3") as connection:
        receipt = connection.execute(
            "SELECT previous_binding_digest, replacement_binding_digest, "
            "actor_principal_id, reason, authority_ref "
            "FROM responsibility_loop_rebind_receipts"
        ).fetchone()
    assert receipt == (
        original.digest,
        changed.digest,
        "founder:1",
        "approved correction epoch transition",
        "approval:rebind-1",
    )
    rebound = store.acquire_lease(changed, process_instance_id="process:B", now=NOW)
    assert rebound.fencing_token == 2
    assert store.latest_checkpoint(changed) is None


def test_rebind_cannot_change_logical_key_and_replay_unknown_effect(
    tmp_path: Path,
) -> None:
    """Repository/configuration evolution must preserve prior effect reservations."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    original = _binding(tmp_path)
    changed = replace(original, repository_head="c" * 40, correction_epoch=1)
    lease = store.acquire_lease(original, process_instance_id="process:A", now=NOW)
    store.prepare_effect(
        original,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        operation_slot="workspace-edit:1",
        intent_digest="d" * 64,
        prepared_at=NOW,
    )
    store.release_lease(original, lease, released_at=NOW)
    store.rebind_inactive_scope(
        original,
        changed,
        actor_principal_id="founder:1",
        reason="approved repository transition",
        authority_ref="approval:rebind-2",
    )
    rebound = store.acquire_lease(changed, process_instance_id="process:B", now=NOW)
    repeated: list[str] = []

    with pytest.raises(ResponsibilityLoopEffectUnknown):
        store.execute_effect(
            changed,
            rebound,
            cycle_id="cycle:1",
            task_id="task:1",
            operation_slot="workspace-edit:1",
            intent_digest="d" * 64,
            effect=lambda: (
                repeated.append("replayed"),
                _effect_receipt("replayed"),
            )[1],
            executed_at=NOW,
        )
    assert repeated == []


def test_checkpoint_restores_from_sqlite_without_session_projection(
    tmp_path: Path,
) -> None:
    """Depending on terminal JSON instead of SQLite would break A-to-B recovery."""
    database = tmp_path / "agent-os.sqlite3"
    binding = _binding(tmp_path)
    clock = MutableClock(NOW)
    first_store = SQLiteResponsibilityLoopStore(database, clock=clock)
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

    restarted = SQLiteResponsibilityLoopStore(database, clock=clock)
    restored = restarted.latest_checkpoint(binding)
    assert restored is not None
    assert restored == written
    assert restored.active_task_id == "task:1"
    assert restored.last_event_sequence == 7
    assert restored.next_transition == "HELP_RESPONSE"


def test_checkpoint_rejects_event_sequence_rollback(tmp_path: Path) -> None:
    """A later timestamp must not make an older responsibility state authoritative."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=10,
        next_transition="OBSERVE",
        recorded_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(ResponsibilityLoopError):
        store.write_checkpoint(
            binding,
            lease,
            state=ResponsibilityCycleState.RUNNING,
            active_task_id="task:1",
            active_run_id="run:1",
            last_event_sequence=1,
            next_transition="EXECUTE",
            recorded_at=NOW + timedelta(seconds=2),
        )


def test_checkpoint_head_compare_and_swap_rejects_sibling_writer(
    tmp_path: Path,
) -> None:
    """A matching fence alone must not allow two sibling projections to advance."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    first = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="OBSERVE",
        recorded_at=NOW,
        expected_prior_digest=None,
    )
    second = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=2,
        next_transition="EXECUTE",
        recorded_at=NOW,
        expected_prior_digest=first.checkpoint_digest,
    )
    with pytest.raises(ResponsibilityLoopError):
        store.write_checkpoint(
            binding,
            lease,
            state=ResponsibilityCycleState.RUNNING,
            active_task_id="task:1",
            active_run_id="run:1",
            last_event_sequence=3,
            next_transition="SETTLE",
            recorded_at=NOW,
            expected_prior_digest=first.checkpoint_digest,
        )
    assert store.latest_checkpoint(binding) == second


def test_checkpoint_head_is_not_selected_by_wall_clock_order(
    tmp_path: Path,
) -> None:
    """A trusted clock rollback must not hide a successfully CAS-advanced checkpoint."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    first = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="OBSERVE",
        recorded_at=NOW,
        expected_prior_digest=None,
    )
    clock.now = NOW - timedelta(seconds=10)
    second = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.WAITING_EVENT,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=2,
        next_transition="WAIT",
        recorded_at=NOW,
        expected_prior_digest=first.checkpoint_digest,
    )
    assert store.latest_checkpoint(binding) == second


def test_takeover_fence_cannot_seal_prior_owner_checkpoint(tmp_path: Path) -> None:
    """A recovery owner must checkpoint under its own fence before sealing a cycle."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = replace(_binding(tmp_path), lease_ttl_seconds=1)
    first_lease = store.acquire_lease(
        binding, process_instance_id="process:A", now=NOW
    )
    checkpoint = store.write_checkpoint(
        binding,
        first_lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    clock.now = NOW + timedelta(seconds=2)
    takeover = store.acquire_lease(
        binding, process_instance_id="process:B", now=clock.now
    )

    with pytest.raises(ResponsibilityLoopStaleFence):
        store.seal_cycle_receipt(
            binding,
            takeover,
            cycle_id="cycle:1",
            task_id="task:1",
            run_id="run:1",
            checkpoint_digest=checkpoint.checkpoint_digest,
        )


def test_cycle_receipt_retry_returns_committed_receipt(tmp_path: Path) -> None:
    """A response-lost retry must be idempotent across trusted-clock movement."""
    clock = MutableClock(NOW)
    store = SQLiteResponsibilityLoopStore(tmp_path / "agent-os.sqlite3", clock=clock)
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    first = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    clock.now = NOW + timedelta(seconds=1)
    replay = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    assert replay == first


def test_hcw_receipt_uses_durable_events_and_accepted_outcome_denominator(
    tmp_path: Path,
) -> None:
    """Guessing duration or caller-supplying the denominator would create fake HCW."""
    store = SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3", clock=MutableClock(NOW)
    )
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


def test_hcw_does_not_assign_unbound_historical_settlement_to_current_cycle(
    tmp_path: Path,
) -> None:
    """Missing cycle provenance must mean insufficient data, never implicit membership."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    evaluator = HcwEvaluatorRoot(
        evaluator_root_id="hcw-evaluator:v1",
        measurement_policy_digest="c" * 64,
        capture_surface="agent-cli",
        idle_cutoff_seconds=60,
    )
    store.ensure_hcw_evaluator_root(evaluator)
    _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:historical",
        task_id="task:historical",
    )

    receipt = store.measure_hcw(
        binding,
        cycle_id="cycle:new",
        evaluator_root_id=evaluator.evaluator_root_id,
        measured_at=NOW + timedelta(seconds=1),
    )
    assert receipt.accepted_outcome_count == 0
    assert receipt.status is HcwMeasurementStatus.HCW_INSUFFICIENT_DATA


def test_hcw_counts_only_explicitly_bound_canonical_cycle_settlement(
    tmp_path: Path,
) -> None:
    """The denominator must be a verified join, not a caller-supplied number."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    evaluator = HcwEvaluatorRoot(
        evaluator_root_id="hcw-evaluator:v1",
        measurement_policy_digest="c" * 64,
        capture_surface="agent-cli",
        idle_cutoff_seconds=60,
    )
    store.ensure_hcw_evaluator_root(evaluator)
    lease = store.acquire_lease(
        binding,
        process_instance_id="process:A",
        now=NOW,
    )
    checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    cycle_receipt = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    digest = _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:cycle-1",
        task_id="task:1",
    )
    store.bind_cycle_settlement(
        binding,
        cycle_id="cycle:1",
        task_id="task:1",
        settlement_id="settlement:cycle-1",
        expected_settlement_digest=digest,
        cycle_receipt_digest=cycle_receipt.receipt_digest,
    )

    receipt = store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id=evaluator.evaluator_root_id,
        measured_at=NOW,
    )
    assert receipt.accepted_outcome_count == 1


def test_cycle_settlement_binding_recomputes_canonical_record_digest(
    tmp_path: Path,
) -> None:
    """A self-consistent rewritten digest field must not authenticate tampered payload."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    cycle_receipt = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    digest = _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:tampered",
        task_id="task:1",
    )
    with sqlite3.connect(database) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload FROM mandate_outcome_settlements "
                "WHERE settlement_id='settlement:tampered'"
            ).fetchone()[0]
        )
        payload["resulting_state"] = "SETTLED_NOT_MET"
        connection.execute(
            "UPDATE mandate_outcome_settlements SET payload=? "
            "WHERE settlement_id='settlement:tampered'",
            (json.dumps(payload),),
        )

    with pytest.raises(ResponsibilityLoopBindingDrift):
        store.bind_cycle_settlement(
            binding,
            cycle_id="cycle:1",
            task_id="task:1",
            settlement_id="settlement:tampered",
            expected_settlement_digest=digest,
            cycle_receipt_digest=cycle_receipt.receipt_digest,
        )


def test_cycle_settlement_rejects_not_met_record_disguised_as_met(
    tmp_path: Path,
) -> None:
    """A syntactically valid but semantically impossible settlement is not accepted."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    cycle_receipt = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    digest = _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:false-met",
        task_id="task:1",
    )
    with sqlite3.connect(database) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload FROM mandate_outcome_settlements "
                "WHERE settlement_id='settlement:false-met'"
            ).fetchone()[0]
        )
        payload["observed_status"] = "NOT_MET"
        unsigned = dict(payload)
        unsigned.pop("record_digest", None)
        replacement_digest = content_digest(unsigned)
        payload["record_digest"] = replacement_digest
        connection.execute(
            "UPDATE mandate_outcome_settlements SET payload=?, record_digest=? "
            "WHERE settlement_id='settlement:false-met'",
            (json.dumps(payload), replacement_digest),
        )

    with pytest.raises(ResponsibilityLoopBindingDrift):
        store.bind_cycle_settlement(
            binding,
            cycle_id="cycle:1",
            task_id="task:1",
            settlement_id="settlement:false-met",
            expected_settlement_digest=replacement_digest,
            cycle_receipt_digest=cycle_receipt.receipt_digest,
        )
    assert digest != replacement_digest


def test_cycle_settlement_rejects_cross_workspace_portfolio_scope(
    tmp_path: Path,
) -> None:
    """A settlement from another workspace cannot enter this binding's HCW truth."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    cycle_receipt = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=checkpoint.checkpoint_digest,
    )
    settlement_digest = _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:foreign-workspace",
        task_id="task:1",
    )
    with sqlite3.connect(database) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload FROM mandate_outcome_portfolios "
                "WHERE portfolio_id='portfolio:1'"
            ).fetchone()[0]
        )
        payload["workspace_id"] = "workspace:foreign"
        unsigned = dict(payload)
        unsigned.pop("record_digest", None)
        digest = content_digest(unsigned)
        payload["record_digest"] = digest
        connection.execute(
            "UPDATE mandate_outcome_portfolios SET workspace_id=?, payload=?, "
            "record_digest=? WHERE portfolio_id='portfolio:1'",
            ("workspace:foreign", json.dumps(payload), digest),
        )

    with pytest.raises(ResponsibilityLoopBindingDrift):
        store.bind_cycle_settlement(
            binding,
            cycle_id="cycle:1",
            task_id="task:1",
            settlement_id="settlement:foreign-workspace",
            expected_settlement_digest=settlement_digest,
            cycle_receipt_digest=cycle_receipt.receipt_digest,
        )


def test_one_canonical_settlement_cannot_inflate_multiple_cycle_denominators(
    tmp_path: Path,
) -> None:
    """A settlement is one accepted outcome and cannot be reused across cycles."""
    database = tmp_path / "agent-os.sqlite3"
    store = SQLiteResponsibilityLoopStore(database, clock=MutableClock(NOW))
    binding = _binding(tmp_path)
    lease = store.acquire_lease(binding, process_instance_id="process:A", now=NOW)
    first_checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=1,
        next_transition="SETTLE",
        recorded_at=NOW,
    )
    first_cycle = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=first_checkpoint.checkpoint_digest,
    )
    settlement_digest = _insert_verified_settlement(
        database,
        binding,
        settlement_id="settlement:one",
        task_id="task:1",
    )
    store.bind_cycle_settlement(
        binding,
        cycle_id="cycle:1",
        task_id="task:1",
        settlement_id="settlement:one",
        expected_settlement_digest=settlement_digest,
        cycle_receipt_digest=first_cycle.receipt_digest,
    )
    second_checkpoint = store.write_checkpoint(
        binding,
        lease,
        state=ResponsibilityCycleState.RUNNING,
        active_task_id="task:1",
        active_run_id="run:1",
        last_event_sequence=2,
        next_transition="SETTLE",
        recorded_at=NOW,
        expected_prior_digest=first_checkpoint.checkpoint_digest,
    )
    second_cycle = store.seal_cycle_receipt(
        binding,
        lease,
        cycle_id="cycle:2",
        task_id="task:1",
        run_id="run:1",
        checkpoint_digest=second_checkpoint.checkpoint_digest,
    )
    with pytest.raises(ResponsibilityLoopError):
        store.bind_cycle_settlement(
            binding,
            cycle_id="cycle:2",
            task_id="task:1",
            settlement_id="settlement:one",
            expected_settlement_digest=settlement_digest,
            cycle_receipt_digest=second_cycle.receipt_digest,
        )
