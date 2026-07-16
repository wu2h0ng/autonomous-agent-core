from __future__ import annotations

import copy
import importlib
import json
import os
import pickle
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    canonical_json,
    environment_event_admission_receipt_digest,
)
from agent_os_core.srl_event_store import (
    EventAdmissionPersistenceConflict,
    SQLiteEventAdmissionStore,
    _create_event_admission_store,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
DIGESTS = tuple(character * 64 for character in "abcdef0123456789")


def _receipt(**updates: Any) -> EnvironmentEventAdmissionReceipt:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "environment_event_id": "environment-event-1",
        "event_digest": DIGESTS[0],
        "event_origin_digest": DIGESTS[1],
        "credential_lease_digest": DIGESTS[2],
        "payload_attestation_digest": DIGESTS[3],
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "environment_binding_version": 4,
        "environment_binding_digest": DIGESTS[4],
        "correction_epoch": 3,
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "admitted_at": NOW,
        "issued_by": "event-admission-service/v1",
        "grants_authority": False,
        "authorizes_effects": False,
    }
    payload.update(updates)
    digest = environment_event_admission_receipt_digest(payload)
    return EnvironmentEventAdmissionReceipt(
        receipt_id=f"event-admission:{digest}",
        receipt_digest=digest,
        **payload,
    )


def _pending_trace(**updates: Any) -> SituatedEvaluationTrace:
    payload: dict[str, Any] = {
        "trace_id": "situated-trace-1",
        "admission_receipt_digest": _receipt().receipt_digest,
        "event_id": "environment-event-1",
        "projection_id": "projection-1",
        "mandate_id": "mandate-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "status": SituatedTraceStatus.PENDING,
        "reason": SituatedTraceReason.ASSESSMENT_PENDING,
        "result_binding_digest": None,
        "delegation_attempt_count": 0,
        "committed_provider_call_attempted": None,
        "input_tokens": None,
        "output_tokens": None,
        "duration_ms": 0,
        "measurement_scope": "LOCAL_CONTROLLED",
        "recorded_at": NOW,
    }
    payload.update(updates)
    return SituatedEvaluationTrace(**payload)


def _terminal_trace(
    pending: SituatedEvaluationTrace,
    *,
    status: SituatedTraceStatus = SituatedTraceStatus.COMPLETED,
    reason: SituatedTraceReason = SituatedTraceReason.TASK_DRAFT,
    result_binding_digest: str | None = DIGESTS[5],
) -> SituatedEvaluationTrace:
    return pending.model_copy(
        update={
            "status": status,
            "reason": reason,
            "result_binding_digest": result_binding_digest,
            "committed_provider_call_attempted": True,
            "input_tokens": 100,
            "output_tokens": 30,
            "duration_ms": 250,
            "recorded_at": NOW + timedelta(seconds=2),
        }
    )


def test_public_reader_is_durable_read_only_and_rejects_memory(tmp_path: Path) -> None:
    rejected = (
        "",
        "   ",
        ":memory:",
        "file::memory:",
        "file:volatile?mode=memory&cache=shared",
    )
    for database in rejected:
        with pytest.raises(ValueError, match="file-backed"):
            SQLiteEventAdmissionStore(database)

    database = tmp_path / "events.sqlite3"
    with pytest.raises(EventAdmissionPersistenceConflict, match="existing"):
        SQLiteEventAdmissionStore(database)
    assert not database.exists()

    reader, _ = _create_event_admission_store(database)
    assert reader.durable is True
    assert reader.by_receipt_id("missing") is None
    assert reader.by_event_id("missing") is None
    assert reader.by_trace_id("missing") is None
    forbidden = {
        "persist_receipt",
        "begin_trace",
        "increment_delegation_attempt",
        "transition_trace",
    }
    assert forbidden.isdisjoint(dir(reader))


def test_public_reader_construction_is_byte_and_schema_read_only(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    _, writer = _create_event_admission_store(database)
    writer.persist_receipt(_receipt())
    before_bytes = database.read_bytes()
    before_mtime = database.stat().st_mtime_ns
    connection = sqlite3.connect(database)
    try:
        before_schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY name"
        ).fetchall()
    finally:
        connection.close()

    reader = SQLiteEventAdmissionStore(database)
    assert reader.by_event_id("environment-event-1") == _receipt()
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime
    connection = sqlite3.connect(database)
    try:
        after_schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY name"
        ).fetchall()
    finally:
        connection.close()
    assert after_schema == before_schema


def test_public_reader_rejects_corrupt_or_impostor_existing_schema(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="schema"):
        SQLiteEventAdmissionStore(corrupt)

    impostor = tmp_path / "impostor.sqlite3"
    connection = sqlite3.connect(impostor)
    try:
        connection.execute(
            "CREATE TABLE srl_event_admission_receipts (receipt_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE srl_situated_evaluation_traces (trace_id TEXT)"
        )
        connection.commit()
    finally:
        connection.close()
    before = impostor.read_bytes()
    with pytest.raises(EventAdmissionPersistenceConflict, match="schema"):
        SQLiteEventAdmissionStore(impostor)
    assert impostor.read_bytes() == before

    weak_schema = tmp_path / "weak-schema.sqlite3"
    connection = sqlite3.connect(weak_schema)
    try:
        connection.execute(
            """
            CREATE TABLE srl_event_admission_receipts (
                receipt_id TEXT,
                environment_event_id TEXT,
                receipt_digest TEXT,
                canonical_json BLOB
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE srl_situated_evaluation_traces (
                trace_id TEXT,
                admission_receipt_digest TEXT,
                projection_id TEXT,
                status TEXT,
                reason TEXT,
                result_binding_digest TEXT,
                delegation_attempt_count INTEGER,
                canonical_json BLOB
            )
            """
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(EventAdmissionPersistenceConflict, match="schema"):
        SQLiteEventAdmissionStore(weak_schema)


def test_relative_database_identity_is_bound_before_cwd_changes(
    tmp_path: Path,
) -> None:
    directory_a = tmp_path / "a"
    directory_b = tmp_path / "b"
    directory_a.mkdir()
    directory_b.mkdir()
    original_cwd = Path.cwd()
    try:
        os.chdir(directory_a)
        reader, writer = _create_event_admission_store("events.sqlite3")
        writer.persist_receipt(_receipt())

        os.chdir(directory_b)
        assert reader.by_event_id("environment-event-1") == _receipt()
        assert writer.persist_receipt(_receipt()) == _receipt()
        assert SQLiteEventAdmissionStore(directory_a / "events.sqlite3").by_event_id(
            "environment-event-1"
        ) == _receipt()
        assert not (directory_b / "events.sqlite3").exists()
    finally:
        os.chdir(original_cwd)


def test_sqlite_failures_are_typed_at_factory_reader_and_writer_boundaries(
    tmp_path: Path,
) -> None:
    corrupt_at_factory = tmp_path / "factory.sqlite3"
    corrupt_at_factory.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        _create_event_admission_store(corrupt_at_factory)

    reader_database = tmp_path / "reader.sqlite3"
    reader, reader_writer = _create_event_admission_store(reader_database)
    reader_writer.persist_receipt(_receipt())
    reader_database.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        reader.by_receipt_id(_receipt().receipt_id)
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        reader.by_trace_id("situated-trace-1")

    writer_database = tmp_path / "writer.sqlite3"
    _, writer = _create_event_admission_store(writer_database)
    writer_database.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        writer.persist_receipt(_receipt())
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        writer.begin_trace(_pending_trace())

    increment_database = tmp_path / "increment.sqlite3"
    _, increment_writer = _create_event_admission_store(increment_database)
    increment_writer.persist_receipt(_receipt())
    increment_writer.begin_trace(_pending_trace())
    increment_database.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        increment_writer.increment_delegation_attempt("situated-trace-1")

    transition_database = tmp_path / "transition.sqlite3"
    _, transition_writer = _create_event_admission_store(transition_database)
    transition_writer.persist_receipt(_receipt())
    pending = transition_writer.begin_trace(_pending_trace())
    transition_database.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(EventAdmissionPersistenceConflict, match="SQLite"):
        transition_writer.transition_trace(_terminal_trace(pending))


def test_receipt_restart_exact_replay_and_conflicts(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    reader, writer = _create_event_admission_store(database)
    receipt = _receipt()

    assert writer.persist_receipt(receipt) == receipt
    assert writer.persist_receipt(receipt) == receipt
    restarted = SQLiteEventAdmissionStore(database)
    assert restarted.by_receipt_id(receipt.receipt_id) == receipt
    assert restarted.by_event_id(receipt.environment_event_id) == receipt
    assert canonical_json(restarted.by_receipt_id(receipt.receipt_id)) == canonical_json(
        receipt
    )
    assert reader.by_receipt_id(receipt.receipt_id) == receipt

    changed_event = _receipt(event_digest=DIGESTS[6])
    assert changed_event.environment_event_id == receipt.environment_event_id
    with pytest.raises(EventAdmissionPersistenceConflict):
        writer.persist_receipt(changed_event)

    forged = receipt.model_copy(update={"event_digest": DIGESTS[7]})
    with pytest.raises(EventAdmissionPersistenceConflict):
        writer.persist_receipt(forged)


def test_pending_trace_increment_transition_and_terminal_replay(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    reader, writer = _create_event_admission_store(database)
    receipt = writer.persist_receipt(_receipt())
    pending = _pending_trace(admission_receipt_digest=receipt.receipt_digest)

    assert writer.begin_trace(pending) == pending
    assert writer.begin_trace(pending) == pending
    incremented = writer.increment_delegation_attempt(
        pending.trace_id, recorded_at=NOW + timedelta(seconds=1)
    )
    assert incremented.delegation_attempt_count == 1
    assert incremented.recorded_at == NOW + timedelta(seconds=1)
    assert incremented.model_copy(
        update={
            "delegation_attempt_count": pending.delegation_attempt_count,
            "recorded_at": pending.recorded_at,
        }
    ) == pending

    terminal = _terminal_trace(incremented)
    assert writer.transition_trace(terminal) == terminal
    assert writer.transition_trace(terminal) == terminal
    assert SQLiteEventAdmissionStore(database).by_trace_id(pending.trace_id) == terminal
    with pytest.raises(EventAdmissionPersistenceConflict, match="terminal"):
        writer.increment_delegation_attempt(pending.trace_id)
    with pytest.raises(EventAdmissionPersistenceConflict, match="terminal"):
        writer.begin_trace(pending)
    with pytest.raises(EventAdmissionPersistenceConflict, match="terminal"):
        writer.transition_trace(
            terminal.model_copy(update={"result_binding_digest": DIGESTS[8]})
        )


@pytest.mark.parametrize(
    ("status", "reason", "result_digest"),
    [
        (SituatedTraceStatus.COMPLETED, SituatedTraceReason.ASSESSMENT_PENDING, DIGESTS[5]),
        (SituatedTraceStatus.COMPLETED, SituatedTraceReason.PROVIDER_FAILED, DIGESTS[5]),
        (SituatedTraceStatus.COMPLETED, SituatedTraceReason.TASK_DRAFT, None),
        (SituatedTraceStatus.DENIED, SituatedTraceReason.TASK_DRAFT, None),
        (SituatedTraceStatus.DENIED, SituatedTraceReason.PROVIDER_FAILED, DIGESTS[5]),
        (SituatedTraceStatus.PENDING, SituatedTraceReason.ASSESSMENT_PENDING, None),
    ],
)
def test_illegal_terminal_transitions_fail_closed(
    tmp_path: Path,
    status: SituatedTraceStatus,
    reason: SituatedTraceReason,
    result_digest: str | None,
) -> None:
    _, writer = _create_event_admission_store(tmp_path / "events.sqlite3")
    writer.persist_receipt(_receipt())
    pending = writer.begin_trace(_pending_trace())
    with pytest.raises(EventAdmissionPersistenceConflict):
        writer.transition_trace(
            _terminal_trace(
                pending,
                status=status,
                reason=reason,
                result_binding_digest=result_digest,
            )
        )


def test_trace_binding_content_attempt_and_scope_conflicts(tmp_path: Path) -> None:
    _, writer = _create_event_admission_store(tmp_path / "events.sqlite3")
    writer.persist_receipt(_receipt())
    pending = writer.begin_trace(_pending_trace())
    changed_binding = _pending_trace(trace_id="situated-trace-2")
    with pytest.raises(EventAdmissionPersistenceConflict):
        writer.begin_trace(changed_binding)
    changed_content = pending.model_copy(update={"tenant_id": "tenant-2"})
    with pytest.raises(EventAdmissionPersistenceConflict):
        writer.begin_trace(changed_content)

    incremented = writer.increment_delegation_attempt(pending.trace_id)
    terminal = _terminal_trace(incremented).model_copy(
        update={"delegation_attempt_count": 0}
    )
    with pytest.raises(EventAdmissionPersistenceConflict, match="attempt"):
        writer.transition_trace(terminal)


def test_only_factory_writer_identity_has_write_authority(tmp_path: Path) -> None:
    _, writer = _create_event_admission_store(tmp_path / "events.sqlite3")
    receipt = _receipt()

    assert not hasattr(receipt, "persist_receipt")
    with pytest.raises(TypeError):
        copy.copy(writer)
    with pytest.raises(TypeError):
        copy.deepcopy(writer)
    with pytest.raises(TypeError):
        pickle.dumps(writer)

    writer_type = type(writer)
    caller_constructed_writer: Any = writer_type
    with pytest.raises(TypeError):
        caller_constructed_writer()

    same_field = object.__new__(writer_type)
    with pytest.raises(EventAdmissionPersistenceConflict, match="unbound"):
        same_field.persist_receipt(receipt)

    attribute_names = dir(writer)
    assert all("backend" not in name.lower() for name in attribute_names)
    assert all("token" not in name.lower() for name in attribute_names)
    assert writer.persist_receipt(receipt) == receipt


def test_module_has_no_reflectable_token_backend_or_writer_registry() -> None:
    module = importlib.import_module("agent_os_core.srl_event_store")
    forbidden_names = {
        "_FACTORY_KEY",
        "_WRITER_TOKENS",
        "_EventAdmissionBackend",
    }
    assert forbidden_names.isdisjoint(vars(module))
    assert not any("token" in name.lower() for name in vars(module))
    assert not any("registry" in name.lower() for name in vars(module))


def test_durable_decode_rejects_malformed_and_noncanonical_bytes(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    reader, writer = _create_event_admission_store(database)
    receipt = writer.persist_receipt(_receipt())

    connection = sqlite3.connect(database)
    try:
        parsed = json.loads(canonical_json(receipt))
        noncanonical = json.dumps(parsed, indent=2).encode("utf-8")
        connection.execute(
            "UPDATE srl_event_admission_receipts SET canonical_json = ?",
            (noncanonical,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(EventAdmissionPersistenceConflict, match="canonical"):
        reader.by_receipt_id(receipt.receipt_id)

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE srl_event_admission_receipts SET canonical_json = ?",
            (b"{not-json",),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(EventAdmissionPersistenceConflict, match="invalid"):
        reader.by_receipt_id(receipt.receipt_id)


def test_schema_and_rows_exclude_raw_provider_secret_and_capability_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    _, writer = _create_event_admission_store(database)
    writer.persist_receipt(_receipt())
    writer.begin_trace(_pending_trace())

    connection = sqlite3.connect(database)
    try:
        schema = " ".join(
            str(row[0])
            for row in connection.execute(
                "SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL"
            ).fetchall()
        )
        rows = " ".join(
            repr(row)
            for table in (
                "srl_event_admission_receipts",
                "srl_situated_evaluation_traces",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        )
    finally:
        connection.close()

    forbidden = (
        "observation_payload",
        "provider_text",
        "secret",
        "resolver_key",
        "exception_text",
        "capability_token",
    )
    lowered = f"{schema} {rows}".lower()
    assert all(term not in lowered for term in forbidden)
