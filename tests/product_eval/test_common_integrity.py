"""Counterexample integrity tests for the SPINE-E2E-1 phase-evidence kernel.

These tests fail against the plan-only commit because the hardened kernel in
``product_evals/common/artifacts.py`` does not yet exist.  They exercise every
security property described in the Task 1 brief: frozen-artifact integrity,
context-bound hash-chained phase ledger, internally-sampled clock/identity,
write-once atomic JSON, and exclusive/shared file locking.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from product_evals.common.artifacts import (
    ClockSample,
    ElapsedGate,
    canonical_sha256,
    load_frozen_json,
    phase_context_sha256,
    phase_guard,
    read_phases,
    sha256_file,
    write_json_atomic,
    write_json_once,
)

# Reused frozen values ---------------------------------------------------------

FROZEN_BINDINGS: dict[str, str] = {
    "schema": "agent-os-phase-ledger-v1",
    "experiment_id": "SPINE-E2E-1",
    "run_id": "spine-e2e-1-20260712",
    "target_head": "d8db06fe1bc3dc59cccb03538ed908a86d729165",
    "prereg_lock_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "spec_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
    "mechanism_manifest_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "corpus_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
    "provider_bank_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
    "evaluator_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
    "runner_common_dir": "/tmp/spine-e2e-runner/common",
    "runner_head": "804c8d54bf5b78d9d850edb452db4affe3c1cd22",
    "request_row_sha256": "6666666666666666666666666666666666666666666666666666666666666666",
    "approval_row_sha256": "7777777777777777777777777777777777777777777777777777777777777777",
}

VALID_CONTEXT = phase_context_sha256(FROZEN_BINDINGS)


# Helpers ----------------------------------------------------------------------


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _write_raw(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _valid_payload_digest() -> str:
    return canonical_sha256({"ok": True})


def _wait_for_file(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise TimeoutError(f"{path} did not appear")


# Canonical hashing ------------------------------------------------------------


def test_canonical_sha256_is_stable_and_sensitive() -> None:
    a = canonical_sha256({"b": 2, "a": 1})
    b = canonical_sha256({"a": 1, "b": 2})
    c = canonical_sha256({"a": 1, "b": 3})
    assert a == b
    assert a != c
    assert len(a) == 64
    assert a == a.lower()


def test_sha256_file_matches_streaming_digest(tmp_path: Path) -> None:
    data = b"frozen artifact bytes"
    path = tmp_path / "artifact.bin"
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_file(path) == expected


# Frozen JSON loading ----------------------------------------------------------


def test_load_frozen_json_rejects_toctou(tmp_path: Path) -> None:
    path = tmp_path / "frozen.json"
    original: dict[str, object] = {"value": 1}
    write_json_atomic(path, original)
    expected = canonical_sha256(original)
    # Attacker mutates file after digest was recorded.
    path.write_text('{"value": 2}')
    with pytest.raises(ValueError):
        load_frozen_json(path, expected)


def test_load_frozen_json_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("not json")
    with pytest.raises(ValueError):
        load_frozen_json(path, "0" * 64)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_load_frozen_json_rejects_non_finite_numbers(
    tmp_path: Path, token: str
) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text('{"value":' + token + "}")
    with pytest.raises(ValueError):
        load_frozen_json(path, sha256_file(path))


def test_load_frozen_json_rejects_duplicate_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"value":1,"value":2}')
    with pytest.raises(ValueError, match="duplicate"):
        load_frozen_json(path, sha256_file(path))


def test_load_frozen_json_binds_exact_source_bytes(tmp_path: Path) -> None:
    path = tmp_path / "frozen.json"
    path.write_bytes(b'{"a":1,"b":2}\n')
    expected = sha256_file(path)
    assert load_frozen_json(path, expected) == {"a": 1, "b": 2}
    path.write_bytes(b'{ "b": 2, "a": 1 }\n')
    with pytest.raises(ValueError, match="digest"):
        load_frozen_json(path, expected)


# Context derivation -----------------------------------------------------------


def test_phase_context_sha256_is_deterministic() -> None:
    a = phase_context_sha256(FROZEN_BINDINGS)
    b = phase_context_sha256(dict(reversed(list(FROZEN_BINDINGS.items()))))
    assert a == b
    assert len(a) == 64


def test_phase_context_sha256_rejects_caller_selected_digests() -> None:
    # The public helper derives from the mapping; it does not allow a caller to
    # pass a pre-computed digest as authority.
    tampered = dict(FROZEN_BINDINGS)
    tampered["run_id"] = "evil-run"
    assert phase_context_sha256(tampered) != VALID_CONTEXT


# Atomic and write-once JSON ---------------------------------------------------


def test_write_json_atomic_uses_same_directory_replace(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "data.json"
    write_json_atomic(path, {"x": 1})
    assert path.exists()
    assert json.loads(path.read_text()) == {"x": 1}


def test_write_json_atomic_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    write_json_atomic(path, {"x": 1})
    write_json_atomic(path, {"x": 2})
    assert json.loads(path.read_text()) == {"x": 2}


def test_write_json_once_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "once.json"
    digest = write_json_once(path, {"x": 1})
    assert len(digest) == 64
    with pytest.raises(FileExistsError):
        write_json_once(path, {"x": 2})


def test_write_json_once_returns_canonical_digest(tmp_path: Path) -> None:
    value = {"a": 1, "b": [2, 3]}
    path = tmp_path / "once.json"
    digest = write_json_once(path, value)
    assert digest == canonical_sha256(value)


def test_atomic_write_fsyncs_regular_file_and_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    write_json_atomic(tmp_path / "value.json", {"ok": True})
    assert any(stat.S_ISREG(mode) for mode in observed)
    assert any(stat.S_ISDIR(mode) for mode in observed)


def test_atomic_cleanup_unlink_fsyncs_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_fsyncs = 0
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        write_json_atomic(tmp_path / "value.json", {"ok": True})
    assert not list(tmp_path.glob(".value.json.*"))
    assert directory_fsyncs >= 1


def test_write_once_cleanup_unlink_fsyncs_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_fsyncs = 0
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "write", lambda *_: 0)
    path = tmp_path / "once.json"
    with pytest.raises(OSError):
        write_json_once(path, {"ok": True})
    assert not path.exists()
    assert directory_fsyncs >= 1


# Phase ledger core ------------------------------------------------------------


def test_read_phases_empty_ledger_returns_empty_tuple(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    ledger.write_text("")
    assert read_phases(ledger, VALID_CONTEXT) == ()


def test_phase_guard_records_started_then_completed(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    digest = _valid_payload_digest()
    with phase_guard(ledger, "prepare", digest, VALID_CONTEXT):
        pass
    records = read_phases(ledger, VALID_CONTEXT)
    assert len(records) == 2
    assert records[0].phase == "prepare_started"
    assert records[1].phase == "prepare_completed"
    assert records[1].payload_sha256 == digest


def test_phase_guard_chain_links_records(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    with phase_guard(ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT):
        pass
    records = read_phases(ledger, VALID_CONTEXT)
    assert records[1].record_sha256 == records[2].previous_record_sha256


@pytest.mark.parametrize("phase", ["deny_probe", "correct_task", "verify"])
def test_phase_guard_rejects_lh_phase_pollution(tmp_path: Path, phase: str) -> None:
    with pytest.raises(ValueError, match="unknown phase"):
        with phase_guard(
            tmp_path / "phases.jsonl",
            phase,
            _valid_payload_digest(),
            VALID_CONTEXT,
        ):
            pass


def test_spine_phase_closed_map_accepts_probe_active_lease(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    with phase_guard(ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT):
        pass
    with phase_guard(
        ledger, "probe_active_lease", _valid_payload_digest(), VALID_CONTEXT
    ):
        pass


# Schema and format hardening --------------------------------------------------


def test_read_phases_rejects_blank_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    ledger.write_text("\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_missing_final_newline(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    ledger.write_text('{"schema_version":"agent-os-phase-ledger-v1"}')
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_non_lowercase_digest(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    bad = (
        '{"schema_version":"agent-os-phase-ledger-v1","phase":"prepare_started",'
        '"ordinal":0,"payload_sha256":"AB"}'
    )
    ledger.write_text(bad + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_invalid_digest_length(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    bad = (
        '{"schema_version":"agent-os-phase-ledger-v1","phase":"prepare_started",'
        '"ordinal":0,"payload_sha256":"deadbeef"}'
    )
    ledger.write_text(bad + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_bool_as_int_ordinal(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    bad = (
        '{"schema_version":"agent-os-phase-ledger-v1","phase":"prepare_started",'
        '"ordinal":true,"payload_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
        '"chain_context_sha256":"' + VALID_CONTEXT + '",'
        '"clock":{"mono_before_ns":1,"utc_ns":2,"mono_after_ns":3,"clock_impl":"c",'
        '"adjustability":"n","resolution":"1e-09","boot_hash":"00","host_hash":"00"},'
        '"previous_record_sha256":"' + VALID_CONTEXT + '"}'
    )
    ledger.write_text(bad + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_non_positive_utc(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    bad = (
        '{"schema_version":"agent-os-phase-ledger-v1","phase":"prepare_started",'
        '"ordinal":0,"payload_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
        '"chain_context_sha256":"' + VALID_CONTEXT + '",'
        '"clock":{"mono_before_ns":1,"utc_ns":0,"mono_after_ns":3,"clock_impl":"c",'
        '"adjustability":"n","resolution":"1e-09","boot_hash":"00","host_hash":"00"},'
        '"previous_record_sha256":"' + VALID_CONTEXT + '"}'
    )
    ledger.write_text(bad + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


@pytest.mark.parametrize("field", ["clock_impl", "adjustability", "resolution"])
@pytest.mark.parametrize("bad_value", ["", 1, None])
def test_read_phases_rejects_invalid_clock_metadata(
    tmp_path: Path, field: str, bad_value: object
) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[0]["clock"][field] = bad_value
    unsigned = dict(rows[0])
    unsigned.pop("record_sha256")
    rows[0]["record_sha256"] = canonical_sha256(unsigned)
    ledger.write_text(_canonical_json(rows[0]) + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_read_phases_rejects_damaged_ordinal(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    # prepare_started must be ordinal 0, not 99.
    bad = (
        '{"schema_version":"agent-os-phase-ledger-v1","phase":"prepare_started",'
        '"ordinal":99,"payload_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
        '"chain_context_sha256":"' + VALID_CONTEXT + '",'
        '"clock":{"mono_before_ns":1,"utc_ns":2,"mono_after_ns":3,"clock_impl":"c",'
        '"adjustability":"n","resolution":"1e-09","boot_hash":"00","host_hash":"00"},'
        '"previous_record_sha256":"' + VALID_CONTEXT + '"}'
    )
    ledger.write_text(bad + "\n")
    with pytest.raises(ValueError):
        read_phases(ledger, VALID_CONTEXT)


def test_phase_guard_rejects_duplicate_phase(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    with pytest.raises(ValueError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass


def test_phase_guard_started_without_terminal_is_invalid_partial(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "phases.jsonl"
    try:
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            raise RuntimeError("abort before completion")
    except RuntimeError:
        pass
    # A second started record for the next Product phase must fail because the
    # previous phase is only started, not terminal.
    with pytest.raises(ValueError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass


def test_phase_guard_failed_phase_blocks_later_phases(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    try:
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            raise RuntimeError("classified failure")
    except RuntimeError:
        pass
    with pytest.raises(ValueError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass


# Context/boot binding ---------------------------------------------------------


def test_read_phases_rejects_transplanted_ledger_context(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    other_bindings = dict(FROZEN_BINDINGS)
    other_bindings["run_id"] = "other"
    other_context = phase_context_sha256(other_bindings)
    with pytest.raises(ValueError):
        read_phases(ledger, other_context)


def test_phase_guard_rejects_boot_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def bad_boot_host(context: str) -> tuple[str, str]:
        return "00" * 32, "11" * 32

    monkeypatch.setattr(
        "product_evals.common.artifacts._boot_host_hashes", bad_boot_host
    )
    with pytest.raises(ValueError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass


def test_phase_guard_rejects_host_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def bad_boot_host(context: str) -> tuple[str, str]:
        return canonical_sha256("boot")[:64], canonical_sha256("host")[:64]

    monkeypatch.setattr(
        "product_evals.common.artifacts._boot_host_hashes", bad_boot_host
    )
    # First call establishes the boot/host hashes in the ledger.
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass

    def other_host(context: str) -> tuple[str, str]:
        return canonical_sha256("boot")[:64], canonical_sha256("other-host")[:64]

    monkeypatch.setattr("product_evals.common.artifacts._boot_host_hashes", other_host)
    with pytest.raises(ValueError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass


# Clock anti-tampering ---------------------------------------------------------


def test_phase_guard_rejects_non_positive_utc_before_yield(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def forged_clock() -> ClockSample:
        return ClockSample(
            mono_before_ns=0,
            utc_ns=0,
            mono_after_ns=0,
            clock_impl="forged",
            adjustability="none",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", forged_clock)
    with pytest.raises(ValueError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass


def test_phase_guard_rejects_rollback_clock_between_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"
    base = time.monotonic_ns()

    def good_clock() -> ClockSample:
        now = time.monotonic_ns()
        return ClockSample(
            mono_before_ns=now,
            utc_ns=time.time_ns(),
            mono_after_ns=now + 1,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", good_clock)
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass

    def rolled_back() -> ClockSample:
        return ClockSample(
            mono_before_ns=base - 10_000_000_000,
            utc_ns=time.time_ns(),
            mono_after_ns=base - 9_999_999_999,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", rolled_back)
    with pytest.raises(ValueError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass


def test_phase_guard_detects_clock_impl_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def impl_a() -> ClockSample:
        return ClockSample(
            mono_before_ns=time.monotonic_ns(),
            utc_ns=time.time_ns(),
            mono_after_ns=time.monotonic_ns(),
            clock_impl="impl-a",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", impl_a)
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass

    def impl_b() -> ClockSample:
        return ClockSample(
            mono_before_ns=time.monotonic_ns(),
            utc_ns=time.time_ns(),
            mono_after_ns=time.monotonic_ns(),
            clock_impl="impl-b",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", impl_b)
    with pytest.raises(ValueError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass


# Timing gates -----------------------------------------------------------------


@pytest.mark.parametrize("bound", [True, "1", float("nan"), float("inf")])
def test_elapsed_gate_rejects_non_finite_or_non_numeric_bounds(bound: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ElapsedGate(anchor_phase="prepare", anchor_record="started", min_seconds=bound)  # type: ignore[arg-type]


def test_phase_guard_enforces_maximum_gate_before_yield(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def fast_anchor() -> ClockSample:
        now = time.monotonic_ns()
        return ClockSample(
            mono_before_ns=now,
            utc_ns=time.time_ns(),
            mono_after_ns=now + 1,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", fast_anchor)
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass

    def too_late() -> ClockSample:
        # Anchor mono_before was ~0, upper bound uses current mono_after.
        return ClockSample(
            mono_before_ns=70_000_000_000,
            utc_ns=time.time_ns(),
            mono_after_ns=70_000_000_001,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", too_late)
    with pytest.raises(ValueError):
        with phase_guard(
            ledger,
            "interrupt_batch",
            _valid_payload_digest(),
            VALID_CONTEXT,
            elapsed_gates=(
                ElapsedGate(
                    anchor_phase="prepare", anchor_record="started", max_seconds=60
                ),
            ),
        ):
            pass


def test_phase_guard_zero_mutation_when_minimum_gate_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def now_clock() -> ClockSample:
        t = time.monotonic_ns()
        return ClockSample(
            mono_before_ns=t,
            utc_ns=time.time_ns(),
            mono_after_ns=t + 1,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", now_clock)
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass

    # interrupt_batch requires at least 360s from prepare_completed, but we are
    # at the same time, so no mutation may occur.
    with pytest.raises(ValueError):
        with phase_guard(
            ledger,
            "interrupt_batch",
            _valid_payload_digest(),
            VALID_CONTEXT,
            elapsed_gates=(
                ElapsedGate(
                    anchor_phase="prepare", anchor_record="completed", min_seconds=360
                ),
            ),
        ):
            pass
    # No started record may have been written for interrupt_batch.
    records = read_phases(ledger, VALID_CONTEXT)
    assert all(r.phase != "interrupt_batch_started" for r in records)


def test_phase_guard_rechecks_maximum_gate_before_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def entry_clock() -> ClockSample:
        t = time.monotonic_ns()
        return ClockSample(
            mono_before_ns=t,
            utc_ns=time.time_ns(),
            mono_after_ns=t + 1,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", entry_clock)

    class JumpOnCompletion:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> ClockSample:
            self.calls += 1
            if self.calls == 1:
                t = time.monotonic_ns()
            else:
                t = time.monotonic_ns() + 70_000_000_000
            return ClockSample(
                mono_before_ns=t,
                utc_ns=time.time_ns(),
                mono_after_ns=t + 1,
                clock_impl="monotonic",
                adjustability="non-adjustable",
                resolution="1e-09",
                boot_hash="00" * 32,
                host_hash="00" * 32,
            )

    monkeypatch.setattr(
        "product_evals.common.artifacts._sample_clock", JumpOnCompletion()
    )
    with pytest.raises(ValueError):
        with phase_guard(
            ledger,
            "prepare",
            _valid_payload_digest(),
            VALID_CONTEXT,
            elapsed_gates=(
                ElapsedGate(
                    anchor_phase="prepare", anchor_record="started", max_seconds=60
                ),
            ),
        ):
            pass


# Locking and concurrency ------------------------------------------------------


def _hold_exclusive_ledger_lock(path: Path, signal: Path, token: Path) -> None:
    from product_evals.common.artifacts import _ledger_lock

    with _ledger_lock(Path(path), exclusive=True):
        Path(signal).write_text("locked")
        _wait_for_file(Path(token))


def _read_under_shared_ledger_lock(path: Path, result: Path) -> None:
    """Spawn-safe reader helper (macOS multiprocessing defaults to spawn)."""
    from product_evals.common.artifacts import _ledger_lock

    with _ledger_lock(Path(path), exclusive=False):
        Path(result).write_text("read")


def _hold_phase_lock(path: Path, acquired: Path, token: Path) -> None:
    from product_evals.common.artifacts import _phase_wide_lock

    with _phase_wide_lock(Path(path)):
        Path(acquired).write_text("locked")
        _wait_for_file(Path(token))


def _attempt_phase_guard(path: Path, context: str, result: Path) -> None:
    try:
        with phase_guard(Path(path), "prepare", _valid_payload_digest(), context):
            pass
    except BaseException as exc:
        Path(result).write_text(type(exc).__name__)
    else:
        Path(result).write_text("MUTATED")


def _hold_partial_append_then_rollback(path: Path, acquired: Path, token: Path) -> None:
    from product_evals.common.artifacts import _ledger_lock

    ledger = Path(path)
    with _ledger_lock(ledger, exclusive=True):
        fd = os.open(ledger, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.write(fd, b'{"partial":')
            os.fsync(fd)
            Path(acquired).write_text("partial")
            _wait_for_file(Path(token))
            os.ftruncate(fd, 0)
            os.fsync(fd)
        finally:
            os.close(fd)


def _read_phases_and_record(path: Path, context: str, result: Path) -> None:
    records = read_phases(Path(path), context)
    Path(result).write_text(str(len(records)))


def test_ledger_shared_lock_blocks_behind_exclusive_holder(tmp_path: Path) -> None:
    """A reader trying to acquire a shared ledger lock must wait until the
    exclusive writer releases.
    """
    ledger = tmp_path / "phases.jsonl"
    ledger.write_text("")
    signal = tmp_path / "signal"
    token = tmp_path / "token"
    result = tmp_path / "result"

    writer = multiprocessing.Process(
        target=_hold_exclusive_ledger_lock,
        args=(str(ledger), str(signal), str(token)),
    )
    writer.start()
    try:
        _wait_for_file(signal)

        thread = multiprocessing.Process(
            target=_read_under_shared_ledger_lock,
            args=(str(ledger), str(result)),
        )
        thread.start()
        # The reader should still be blocked because the writer holds the lock.
        time.sleep(0.1)
        assert not result.exists()
        token.write_text("go")
        thread.join(timeout=5)
        assert result.read_text() == "read"
    finally:
        if writer.is_alive():
            token.write_text("go")
            writer.terminate()
            writer.join()


def test_reader_cannot_observe_inflight_partial_append(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    acquired = tmp_path / "partial"
    token = tmp_path / "rollback"
    result = tmp_path / "result"
    writer = multiprocessing.Process(
        target=_hold_partial_append_then_rollback,
        args=(str(ledger), str(acquired), str(token)),
    )
    reader = multiprocessing.Process(
        target=_read_phases_and_record,
        args=(str(ledger), VALID_CONTEXT, str(result)),
    )
    writer.start()
    try:
        _wait_for_file(acquired)
        reader.start()
        time.sleep(0.1)
        assert not result.exists()
        token.write_text("go")
        writer.join(timeout=5)
        reader.join(timeout=5)
        assert result.read_text() == "0"
    finally:
        token.write_text("go")
        for process in (writer, reader):
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join()


def _hold_exclusive_ledger_lock_and_signal(
    path: Path, acquired: Path, token: Path
) -> None:
    from product_evals.common.artifacts import _ledger_lock

    with _ledger_lock(Path(path), exclusive=True):
        Path(acquired).write_text("yes")
        _wait_for_file(Path(token))


def test_two_writer_contention_one_wins(tmp_path: Path) -> None:
    """Only one exclusive ledger writer may proceed at a time."""
    ledger = tmp_path / "phases.jsonl"
    acquired1 = tmp_path / "acquired1"
    token1 = tmp_path / "token1"
    acquired2 = tmp_path / "acquired2"
    token2 = tmp_path / "token2"

    proc1 = multiprocessing.Process(
        target=_hold_exclusive_ledger_lock_and_signal,
        args=(str(ledger), str(acquired1), str(token1)),
    )
    proc2 = multiprocessing.Process(
        target=_hold_exclusive_ledger_lock_and_signal,
        args=(str(ledger), str(acquired2), str(token2)),
    )
    proc1.start()
    proc2.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not (
            acquired1.exists() or acquired2.exists()
        ):
            time.sleep(0.01)
        assert acquired1.exists() != acquired2.exists()
        first_token = token1 if acquired1.exists() else token2
        second_acquired = acquired2 if acquired1.exists() else acquired1
        second_token = token2 if acquired1.exists() else token1
        first_process = proc1 if acquired1.exists() else proc2
        second_process = proc2 if acquired1.exists() else proc1
        first_token.write_text("go")
        first_process.join(timeout=5)
        _wait_for_file(second_acquired)
        second_token.write_text("go")
        second_process.join(timeout=5)
    finally:
        for p in (proc1, proc2):
            if p.is_alive():
                p.terminate()
                p.join()


def test_phase_guard_lock_order_phase_before_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that phase.lock is acquired before the ledger lock."""
    ledger = tmp_path / "phases.jsonl"
    order: list[str] = []

    @contextmanager
    def tracking_phase_lock(ledger_path: Path) -> Iterator[None]:
        assert ledger_path == ledger
        order.append("phase")
        yield

    @contextmanager
    def tracking_ledger_lock(ledger_path: Path, *, exclusive: bool) -> Iterator[None]:
        order.append("ledger")
        yield

    monkeypatch.setattr(
        "product_evals.common.artifacts._phase_wide_lock", tracking_phase_lock
    )
    monkeypatch.setattr(
        "product_evals.common.artifacts._ledger_lock", tracking_ledger_lock
    )
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    assert order == ["phase", "ledger"]


def test_phase_lock_contention_is_nonblocking_and_has_zero_ledger_mutation(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "phases.jsonl"
    acquired = tmp_path / "acquired"
    token = tmp_path / "token"
    result = tmp_path / "result"
    holder = multiprocessing.Process(
        target=_hold_phase_lock,
        args=(str(ledger), str(acquired), str(token)),
    )
    contender = multiprocessing.Process(
        target=_attempt_phase_guard,
        args=(str(ledger), VALID_CONTEXT, str(result)),
    )
    holder.start()
    try:
        _wait_for_file(acquired)
        contender.start()
        contender.join(timeout=5)
        assert result.read_text() == "BlockingIOError"
        assert not ledger.exists()
    finally:
        token.write_text("go")
        for process in (holder, contender):
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join()


# Append rollback --------------------------------------------------------------


def test_phase_guard_rolls_back_after_short_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"
    original_write = os.write
    calls: list[int] = []

    def short_write(fd: int, data: bytes) -> int:
        calls.append(len(data))
        if len(calls) == 1:
            # Return a short write for the started record.
            n = max(1, len(data) // 2)
            return original_write(fd, data[:n])
        return original_write(fd, data)

    monkeypatch.setattr(os, "write", short_write)
    with pytest.raises(OSError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass
    # Ledger must be rolled back to empty.
    assert ledger.read_text() == ""


def test_phase_guard_rolls_back_after_zero_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"

    def zero_write(fd: int, data: bytes) -> int:
        return 0

    monkeypatch.setattr(os, "write", zero_write)
    with pytest.raises(OSError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass
    assert ledger.read_text() == ""


def test_phase_append_fsyncs_ledger_file_and_parent_on_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    with phase_guard(
        tmp_path / "phases.jsonl", "prepare", _valid_payload_digest(), VALID_CONTEXT
    ):
        pass
    assert any(stat.S_ISREG(mode) for mode in observed)
    assert any(stat.S_ISDIR(mode) for mode in observed)


def test_failed_append_rollback_fsyncs_file_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "write", lambda *_: 0)
    ledger = tmp_path / "phases.jsonl"
    with pytest.raises(OSError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            pass
    assert ledger.read_bytes() == b""
    assert any(stat.S_ISREG(mode) for mode in observed)
    assert any(stat.S_ISDIR(mode) for mode in observed)


def test_phase_guard_rolls_back_existing_ledger_to_original_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "phases.jsonl"
    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        pass
    original = ledger.read_bytes()
    monkeypatch.setattr(os, "write", lambda *_: 0)
    with pytest.raises(OSError):
        with phase_guard(
            ledger, "interrupt_batch", _valid_payload_digest(), VALID_CONTEXT
        ):
            pass
    assert ledger.read_bytes() == original


# Failure record semantics -----------------------------------------------------


def test_phase_guard_failed_record_has_no_freeform_text(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    try:
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            raise RuntimeError("sensitive details must not leak")
    except RuntimeError:
        pass
    records = read_phases(ledger, VALID_CONTEXT)
    failed = records[-1]
    assert failed.phase == "prepare_failed"
    # The real fixed failure payload contains only the restricted schema.
    expected_payload = {
        "schema_version": "agent-os-phase-ledger-v1",
        "phase": "prepare",
        "error_code": "INVALID_INTERNAL_ERROR",
    }
    assert failed.payload_sha256 == canonical_sha256(expected_payload)
    failure_path = tmp_path / "prepare.failure.json"
    assert json.loads(failure_path.read_text()) == expected_payload
    assert "sensitive details" not in failure_path.read_text()


def test_phase_guard_failure_payload_refuses_overwrite(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    failure_path = tmp_path / "prepare.failure.json"
    failure_path.write_text("attacker-controlled")
    with pytest.raises(FileExistsError):
        with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
            raise RuntimeError("classified")
    assert failure_path.read_text() == "attacker-controlled"


# Production context derivation ------------------------------------------------


def test_context_derivation_refuses_runner_head_drift() -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings["runner_head"] = "bb3337f000000000000000000000000000000000"
    ctx = phase_context_sha256(bindings)
    assert ctx != VALID_CONTEXT


def test_context_derivation_refuses_request_row_digest_drift() -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings["request_row_sha256"] = "z" * 64  # invalid hex too
    with pytest.raises(ValueError):
        phase_context_sha256(bindings)


def test_context_derivation_refuses_blank_binding_value() -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings["run_id"] = ""
    with pytest.raises(ValueError):
        phase_context_sha256(bindings)


@pytest.mark.parametrize("removed", ["schema", "run_id", "runner_head"])
def test_phase_context_sha256_rejects_missing_binding(removed: str) -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings.pop(removed)
    with pytest.raises(ValueError, match="schema"):
        phase_context_sha256(bindings)


def test_phase_context_sha256_rejects_extra_binding() -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings["caller_authority"] = "forbidden"
    with pytest.raises(ValueError, match="schema"):
        phase_context_sha256(bindings)


def test_phase_context_sha256_requires_exact_schema_value() -> None:
    bindings = dict(FROZEN_BINDINGS)
    bindings["schema"] = "agent-os-phase-ledger-v2"
    with pytest.raises(ValueError, match="schema"):
        phase_context_sha256(bindings)


# Misc -------------------------------------------------------------------------


def test_phase_guard_yields_before_product_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The started record must exist before the guarded body runs."""
    ledger = tmp_path / "phases.jsonl"
    observed: list[str] = []

    def now_clock() -> ClockSample:
        t = time.monotonic_ns()
        return ClockSample(
            mono_before_ns=t,
            utc_ns=time.time_ns(),
            mono_after_ns=t + 1,
            clock_impl="monotonic",
            adjustability="non-adjustable",
            resolution="1e-09",
            boot_hash="00" * 32,
            host_hash="00" * 32,
        )

    monkeypatch.setattr("product_evals.common.artifacts._sample_clock", now_clock)

    with phase_guard(ledger, "prepare", _valid_payload_digest(), VALID_CONTEXT):
        records = read_phases(ledger, VALID_CONTEXT)
        observed.append(records[0].phase)

    assert observed == ["prepare_started"]


def test_phase_guard_can_bind_a_payload_created_after_start(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    planned = _valid_payload_digest()
    actual = hashlib.sha256(b"actual-write-once-payload").hexdigest()

    with phase_guard(ledger, "prepare", planned, VALID_CONTEXT) as guard:
        assert [record.phase for record in read_phases(ledger, VALID_CONTEXT)] == [
            "prepare_started"
        ]
        guard.bind_payload(actual)

    records = read_phases(ledger, VALID_CONTEXT)
    assert records[-1].phase == "prepare_completed"
    assert records[-1].payload_sha256 == actual


def test_phase_guard_required_binding_fails_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "phases.jsonl"
    with pytest.raises(ValueError, match="INVALID_WRITE_ONCE"):
        with phase_guard(
            ledger,
            "prepare",
            _valid_payload_digest(),
            VALID_CONTEXT,
            require_bound_payload=True,
        ):
            pass
    records = read_phases(ledger, VALID_CONTEXT)
    assert [record.phase for record in records] == [
        "prepare_started",
        "prepare_failed",
    ]
    assert json.loads((tmp_path / "prepare.failure.json").read_text())["error_code"] == (
        "INVALID_WRITE_ONCE"
    )
