from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os_contracts import content_digest
from agent_os_core.responsibility_loop import (
    HcwEvaluatorRoot,
    HcwMeasurementStatus,
    OperatorWorkEventKind,
    ResponsibilityLoopBinding,
    SQLiteResponsibilityLoopStore,
)
from agent_os_core.selfdev_hcw_provenance import (
    CLAIM_CEILING,
    CountOnlyHcwProvenance,
    CountOnlyHcwProvenanceError,
    record_count_only_hcw_provenance,
    verify_count_only_hcw_provenance,
)


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)


def _binding(root: Path) -> ResponsibilityLoopBinding:
    return ResponsibilityLoopBinding(
        mandate_id="mandate:admit-selfdev",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        repository_root=str(root),
        repository_head="a" * 40,
        correction_epoch=0,
        configuration_digest="b" * 64,
        lease_ttl_seconds=30,
    )


def _evaluator_root() -> HcwEvaluatorRoot:
    return HcwEvaluatorRoot(
        evaluator_root_id="hcw:count-only",
        measurement_policy_digest="c" * 64,
        capture_surface="operator-work-events",
        idle_cutoff_seconds=600,
    )


def _store(tmp_path: Path) -> SQLiteResponsibilityLoopStore:
    return SQLiteResponsibilityLoopStore(
        tmp_path / "agent-os.sqlite3",
        clock=lambda: NOW,
    )


def _insert_synthetic_receipt(
    database: Path,
    binding: ResponsibilityLoopBinding,
    *,
    cycle_id: str,
    intervention: int,
    help_count: int,
    active_seconds: float | None,
    accepted: int,
) -> str:
    payload = {
        "binding_digest": binding.digest,
        "cycle_id": cycle_id,
        "evaluator_root_id": "hcw:count-only",
        "measurement_policy_digest": "c" * 64,
        "status": "HCW_INSUFFICIENT_DATA",
        "operator_intervention_count": intervention,
        "help_response_count": help_count,
        "active_operator_seconds": active_seconds,
        "accepted_outcome_count": accepted,
        "operator_minutes_per_accepted_outcome": None,
        "measured_at": NOW,
    }
    digest = content_digest(payload)
    encoded = json.dumps(payload, default=str, sort_keys=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO hcw_measurement_receipts VALUES (?,?,?,?)",
            (digest, binding.digest, cycle_id, encoded),
        )
        connection.commit()
    finally:
        connection.close()
    return digest


def test_empty_store_records_honest_zero_counts_and_insufficient_data(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    task_dir = tmp_path / ".agent_runs" / "admit-selfdev-live-20260814"

    record = record_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
        clock=lambda: NOW,
    )

    assert record.intervention_count == 0
    assert record.help_event_count == 0
    assert record.outcome_event_count == 0
    assert record.operator_minutes is None
    assert record.measurement_status == HcwMeasurementStatus.HCW_INSUFFICIENT_DATA.value
    assert record.claim_ceiling == CLAIM_CEILING
    assert record.source_receipt_digests == ()
    assert record.recorded_at == NOW.isoformat()


def test_recorder_derives_counts_from_real_measurement_receipts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    store.ensure_hcw_evaluator_root(_evaluator_root())
    store.append_operator_work_event(
        binding,
        event_id="operator-event:user-input",
        kind=OperatorWorkEventKind.USER_INPUT,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.append_operator_work_event(
        binding,
        event_id="operator-event:help-response",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.append_operator_work_event(
        binding,
        event_id="operator-event:correction",
        kind=OperatorWorkEventKind.CORRECTION,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    receipt = store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id="hcw:count-only",
        measured_at=NOW,
    )
    assert receipt.operator_intervention_count == 3
    assert receipt.help_response_count == 1
    assert receipt.accepted_outcome_count == 0

    task_dir = tmp_path / ".agent_runs" / "admit-selfdev-live-20260814"
    record = record_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
        clock=lambda: NOW,
    )

    assert record.intervention_count == 3
    assert record.help_event_count == 1
    assert record.outcome_event_count == 0
    assert record.source_receipt_digests == (receipt.receipt_digest,)
    path = task_dir / "admit-selfdev-live-20260814.hcw_provenance.json"
    assert path.is_file()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["intervention_count"] == 3
    assert persisted["record_digest"] == record.record_digest


def test_verifier_recomputes_and_passes_for_real_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    store.ensure_hcw_evaluator_root(_evaluator_root())
    store.append_operator_work_event(
        binding,
        event_id="operator-event:help-response",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id="hcw:count-only",
        measured_at=NOW,
    )
    task_dir = tmp_path / ".agent_runs" / "admit-selfdev-live-20260814"
    recorded = record_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
        clock=lambda: NOW,
    )

    verified = verify_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
    )

    assert verified.to_dict() == recorded.to_dict()


def test_verifier_rejects_forged_intervention_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    store.ensure_hcw_evaluator_root(_evaluator_root())
    store.append_operator_work_event(
        binding,
        event_id="operator-event:help-response",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id="hcw:count-only",
        measured_at=NOW,
    )
    task_dir = tmp_path / ".agent_runs" / "admit-selfdev-live-20260814"
    record_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
        clock=lambda: NOW,
    )

    path = task_dir / "admit-selfdev-live-20260814.hcw_provenance.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["intervention_count"] = 999
    tampered["record_digest"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(CountOnlyHcwProvenanceError):
        verify_count_only_hcw_provenance(
            store=store,
            binding=binding,
            slice_id="admit-selfdev-live-20260814",
            task_dir=task_dir,
        )


def test_verifier_rejects_missing_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    with pytest.raises(CountOnlyHcwProvenanceError, match="missing"):
        verify_count_only_hcw_provenance(
            store=store,
            binding=binding,
            slice_id="admit-selfdev-live-20260814",
            task_dir=tmp_path / "absent",
        )


def test_receipt_digest_drift_is_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    store.ensure_hcw_evaluator_root(_evaluator_root())
    store.append_operator_work_event(
        binding,
        event_id="operator-event:help-response",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id="hcw:count-only",
        measured_at=NOW,
    )
    connection = sqlite3.connect(tmp_path / "agent-os.sqlite3")
    try:
        row = connection.execute(
            "SELECT payload FROM hcw_measurement_receipts"
        ).fetchone()
        assert row is not None
        tampered = json.loads(str(row[0]))
        tampered["operator_intervention_count"] = 999
        connection.execute(
            "UPDATE hcw_measurement_receipts SET payload = ?",
            (json.dumps(tampered),),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CountOnlyHcwProvenanceError, match="digest drift"):
        CountOnlyHcwProvenance.build(
            store=store,
            binding=binding,
            slice_id="admit-selfdev-live-20260814",
            clock=lambda: NOW,
        )


def test_operator_minutes_derived_from_active_seconds(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    _insert_synthetic_receipt(
        tmp_path / "agent-os.sqlite3",
        binding,
        cycle_id="cycle:1",
        intervention=3,
        help_count=1,
        active_seconds=120.0,
        accepted=0,
    )
    _insert_synthetic_receipt(
        tmp_path / "agent-os.sqlite3",
        binding,
        cycle_id="cycle:2",
        intervention=1,
        help_count=0,
        active_seconds=60.0,
        accepted=1,
    )

    record = CountOnlyHcwProvenance.build(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        clock=lambda: NOW,
    )

    assert record.operator_minutes == pytest.approx(3.0)
    assert record.intervention_count == 4
    assert record.help_event_count == 1
    assert record.outcome_event_count == 1


def test_verifier_rejects_forged_counts_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    store.ensure_hcw_evaluator_root(_evaluator_root())
    store.append_operator_work_event(
        binding,
        event_id="operator-event:help-response",
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id="cycle:1",
        task_id="task:1",
        run_id="run:1",
        occurred_at=NOW,
    )
    store.measure_hcw(
        binding,
        cycle_id="cycle:1",
        evaluator_root_id="hcw:count-only",
        measured_at=NOW,
    )
    task_dir = tmp_path / ".agent_runs" / "admit-selfdev-live-20260814"
    record_count_only_hcw_provenance(
        store=store,
        binding=binding,
        slice_id="admit-selfdev-live-20260814",
        task_dir=task_dir,
        clock=lambda: NOW,
    )

    path = task_dir / "admit-selfdev-live-20260814.hcw_provenance.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["intervention_count"] = 999
    tampered["record_digest"] = content_digest(
        {key: value for key, value in tampered.items() if key != "record_digest"}
    )
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(
        CountOnlyHcwProvenanceError,
        match="does not match the real persisted events",
    ):
        verify_count_only_hcw_provenance(
            store=store,
            binding=binding,
            slice_id="admit-selfdev-live-20260814",
            task_dir=task_dir,
        )


@pytest.mark.parametrize(
    "slice_id",
    ("../escape", "a/b", "a\\b", ".hidden", "..", "/absolute", "trailing/"),
)
def test_slice_id_rejects_path_unsafe_slugs(tmp_path: Path, slice_id: str) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    with pytest.raises(CountOnlyHcwProvenanceError, match="path-safe slug"):
        record_count_only_hcw_provenance(
            store=store,
            binding=binding,
            slice_id=slice_id,
            task_dir=tmp_path,
            clock=lambda: NOW,
        )


def test_record_write_failure_is_typed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    binding = _binding(tmp_path)
    not_a_directory = tmp_path / "not-a-dir"
    not_a_directory.write_text("block", encoding="utf-8")
    with pytest.raises(CountOnlyHcwProvenanceError, match="failed to write"):
        record_count_only_hcw_provenance(
            store=store,
            binding=binding,
            slice_id="admit-selfdev-live-20260814",
            task_dir=not_a_directory,
            clock=lambda: NOW,
        )


def test_from_dict_rejects_malformed_payload() -> None:
    payload = {
        "schema_version": "1.0",
        "slice_id": "admit-selfdev-live-20260814",
        "mandate_id": "mandate:x",
        "binding_digest": "a" * 64,
        "measurement_status": "HCW_INSUFFICIENT_DATA",
        "intervention_count": "not-an-int",
        "operator_minutes": None,
        "outcome_event_count": 0,
        "help_event_count": 0,
        "source_receipt_digests": [],
        "recorded_at": "2026-08-14T10:00:00+00:00",
        "claim_ceiling": CLAIM_CEILING,
    }
    payload["record_digest"] = content_digest(payload)
    with pytest.raises(CountOnlyHcwProvenanceError, match="malformed"):
        CountOnlyHcwProvenance.from_dict(payload)
