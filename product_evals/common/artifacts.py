"""Durable, context-bound artifact and phase-ledger primitives.

This module deliberately exposes no clock or identity injection in its public
API.  Tests may replace private samplers to exercise fail-closed paths.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import numbers
import os
import platform
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Mapping

SCHEMA = "agent-os-phase-ledger-v1"
_HEX = frozenset("0123456789abcdef")
_PHASES = (
    "prepare",
    "interrupt_batch",
    "probe_active_lease",
    "resume",
    "adjudicate",
)
_ORDINALS = {
    f"{phase}_{suffix}": index * 2 + terminal
    for index, phase in enumerate(_PHASES)
    for terminal, suffix in enumerate(("started", "completed"))
}
_ACTIVE_LEDGERS = threading.local()
_REQUIRED_CONTEXT_KEYS = frozenset(
    {
        "schema",
        "experiment_id",
        "run_id",
        "target_head",
        "prereg_lock_sha256",
        "spec_sha256",
        "mechanism_manifest_sha256",
        "corpus_sha256",
        "provider_bank_sha256",
        "evaluator_sha256",
        "runner_common_dir",
        "runner_head",
        "request_row_sha256",
        "approval_row_sha256",
    }
)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value)
    )


def _require_digest(value: object, field: str) -> str:
    if not _valid_digest(value):
        raise ValueError(f"invalid {field}")
    return value


def load_frozen_json(path: Path, expected_sha256: str) -> object:
    _require_digest(expected_sha256, "expected_sha256")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid frozen JSON") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("frozen JSON digest mismatch")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def phase_context_sha256(bindings: Mapping[str, str]) -> str:
    if not isinstance(bindings, Mapping) or not bindings:
        raise ValueError("context bindings must be non-empty")
    if set(bindings) != _REQUIRED_CONTEXT_KEYS:
        raise ValueError("invalid context binding schema")
    if bindings.get("schema") != SCHEMA:
        raise ValueError("invalid context binding schema value")
    normalized: dict[str, str] = {}
    for key, value in bindings.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
        ):
            raise ValueError("context bindings must be non-blank strings")
        if key.endswith("_sha256"):
            _require_digest(value, key)
        elif key in {"target_head", "runner_head"} and not (
            len(value) == 40 and all(char in _HEX for char in value)
        ):
            raise ValueError(f"invalid {key}")
        normalized[key] = value
    return canonical_sha256(normalized)


def _fsync_parent(path: Path) -> None:
    fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json_atomic(path: Path, value: object) -> None:
    data = _canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_parent(path)
    except BaseException:
        try:
            temporary_path.unlink()
            _fsync_parent(path)
        except FileNotFoundError:
            pass
        raise


def _write_exact(fd: int, data: bytes) -> None:
    written = os.write(fd, data)
    if written != len(data):
        raise OSError("short durable write")


def write_json_once(path: Path, value: object) -> str:
    data = _canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_exact(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            path.unlink()
            _fsync_parent(path)
        except FileNotFoundError:
            pass
        raise
    else:
        os.close(fd)
        _fsync_parent(path)
    return canonical_sha256(value)


@dataclass(frozen=True)
class ClockSample:
    mono_before_ns: int
    utc_ns: int
    mono_after_ns: int
    clock_impl: str
    adjustability: str
    resolution: str
    boot_hash: str
    host_hash: str


@dataclass(frozen=True)
class PhaseRecord:
    schema_version: str
    phase: str
    ordinal: int
    payload_sha256: str
    chain_context_sha256: str
    clock: ClockSample
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True)
class ElapsedGate:
    anchor_phase: str
    anchor_record: str
    min_seconds: float | None = None
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.anchor_phase not in _PHASES or self.anchor_record not in {
            "started",
            "completed",
        }:
            raise ValueError("invalid elapsed-gate anchor")
        if self.min_seconds is None and self.max_seconds is None:
            raise ValueError("elapsed gate has no bound")
        for bound in (self.min_seconds, self.max_seconds):
            if bound is not None and (
                isinstance(bound, bool)
                or not isinstance(bound, numbers.Real)
                or not math.isfinite(bound)
                or bound < 0
            ):
                raise ValueError("invalid elapsed-gate bound")


def _raw_identities() -> tuple[str, str]:
    system = platform.system()
    if system == "Darwin":
        boot = subprocess.check_output(
            ["sysctl", "-n", "kern.bootsessionuuid"], text=True
        ).strip()
        host = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True
        )
        marker = '"IOPlatformUUID" = "'
        if marker not in host:
            raise ValueError("host identity unavailable")
        host = host.split(marker, 1)[1].split('"', 1)[0]
    elif system == "Linux":
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        host = Path("/etc/machine-id").read_text().strip()
    else:
        raise ValueError("unsupported identity platform")
    if not boot or not host:
        raise ValueError("identity unavailable")
    return boot, host


def _boot_host_hashes(context: str) -> tuple[str, str]:
    _require_digest(context, "context")
    boot, host = _raw_identities()
    salt = bytes.fromhex(context)
    return (
        hashlib.sha256(salt + b"\0boot\0" + boot.encode()).hexdigest(),
        hashlib.sha256(salt + b"\0host\0" + host.encode()).hexdigest(),
    )


def _sample_clock() -> ClockSample:
    before = time.monotonic_ns()
    utc = time.time_ns()
    after = time.monotonic_ns()
    info = time.get_clock_info("monotonic")
    # Identity is filled by phase_guard because its digest requires context.
    return ClockSample(
        before,
        utc,
        after,
        info.implementation,
        "adjustable" if info.adjustable else "non-adjustable",
        repr(info.resolution),
        "0" * 64,
        "0" * 64,
    )


def _validated_sample(context: str) -> ClockSample:
    sample = _sample_clock()
    if (
        isinstance(sample.mono_before_ns, bool)
        or not isinstance(sample.mono_before_ns, int)
        or isinstance(sample.utc_ns, bool)
        or not isinstance(sample.utc_ns, int)
        or isinstance(sample.mono_after_ns, bool)
        or not isinstance(sample.mono_after_ns, int)
        or sample.utc_ns <= 0
        or sample.mono_before_ns < 0
        or sample.mono_after_ns < sample.mono_before_ns
        or not sample.clock_impl
        or not sample.adjustability
        or not sample.resolution
    ):
        raise ValueError("invalid clock sample")
    boot, host = _boot_host_hashes(context)
    _require_digest(boot, "boot_hash")
    _require_digest(host, "host_hash")
    if boot == "0" * 64 or host == "0" * 64:
        raise ValueError("invalid machine identity")
    # Private test clocks may provide placeholders; production sampling never
    # accepts caller identity and always replaces them with derived values.
    return ClockSample(
        sample.mono_before_ns,
        sample.utc_ns,
        sample.mono_after_ns,
        sample.clock_impl,
        sample.adjustability,
        sample.resolution,
        boot,
        host,
    )


def _genesis(context: str) -> str:
    return hashlib.sha256(
        b"agent-os-phase-ledger-v1\0" + bytes.fromhex(context)
    ).hexdigest()


@contextmanager
def _ledger_lock(ledger_path: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def _phase_wide_lock(ledger_path: Path) -> Iterator[None]:
    path = ledger_path.with_suffix(ledger_path.suffix + ".phase.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _record_dict(
    record: PhaseRecord, *, include_digest: bool = True
) -> dict[str, object]:
    value = asdict(record)
    if not include_digest:
        value.pop("record_sha256")
    return value


def _parse_record(value: object, expected_context: str, position: int) -> PhaseRecord:
    required = {
        "schema_version",
        "phase",
        "ordinal",
        "payload_sha256",
        "chain_context_sha256",
        "clock",
        "previous_record_sha256",
        "record_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("non-exact phase schema")
    clock_value = value["clock"]
    clock_fields = {
        "mono_before_ns",
        "utc_ns",
        "mono_after_ns",
        "clock_impl",
        "adjustability",
        "resolution",
        "boot_hash",
        "host_hash",
    }
    if not isinstance(clock_value, dict) or set(clock_value) != clock_fields:
        raise ValueError("non-exact clock schema")
    clock = ClockSample(**clock_value)
    phase = value["phase"]
    ordinal = value["ordinal"]
    allowed_phases = set(_ORDINALS) | {
        name.replace("_completed", "_failed")
        for name in _ORDINALS
        if name.endswith("_completed")
    }
    if not isinstance(phase, str) or phase not in allowed_phases:
        raise ValueError("invalid phase")
    base_ordinal = _ORDINALS.get(
        phase, _ORDINALS.get(phase.replace("_failed", "_completed"))
    )
    if (
        isinstance(ordinal, bool)
        or not isinstance(ordinal, int)
        or ordinal != base_ordinal
    ):
        raise ValueError("invalid ordinal")
    if (
        value["schema_version"] != SCHEMA
        or value["chain_context_sha256"] != expected_context
    ):
        raise ValueError("phase context mismatch")
    for field in (
        "payload_sha256",
        "chain_context_sha256",
        "previous_record_sha256",
        "record_sha256",
    ):
        _require_digest(value[field], field)
    for field in ("boot_hash", "host_hash"):
        _require_digest(clock_value[field], field)
    if any(
        not isinstance(getattr(clock, field), str) or not getattr(clock, field)
        for field in ("clock_impl", "adjustability", "resolution")
    ):
        raise ValueError("invalid clock metadata")
    if (
        isinstance(clock.utc_ns, bool)
        or not isinstance(clock.utc_ns, int)
        or clock.utc_ns <= 0
        or isinstance(clock.mono_before_ns, bool)
        or not isinstance(clock.mono_before_ns, int)
        or isinstance(clock.mono_after_ns, bool)
        or not isinstance(clock.mono_after_ns, int)
        or clock.mono_before_ns < 0
        or clock.mono_after_ns < clock.mono_before_ns
    ):
        raise ValueError("invalid clock")
    record = PhaseRecord(clock=clock, **{k: value[k] for k in required - {"clock"}})
    if (
        canonical_sha256(_record_dict(record, include_digest=False))
        != record.record_sha256
    ):
        raise ValueError("record digest mismatch")
    return record


def _read_phases_unlocked(path: Path, expected_context: str) -> tuple[PhaseRecord, ...]:
    _require_digest(expected_context, "expected_context_sha256")
    if not path.exists():
        return ()
    raw = path.read_bytes()
    if not raw:
        return ()
    if not raw.endswith(b"\n") or b"\n\n" in raw or raw.startswith(b"\n"):
        raise ValueError("invalid ledger framing")
    records: list[PhaseRecord] = []
    previous = _genesis(expected_context)
    seen: set[str] = set()
    identity: tuple[str, str, str, str, str] | None = None
    last_mono = -1
    for position, line in enumerate(raw.splitlines()):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid ledger JSON") from exc
        record = _parse_record(value, expected_context, position)
        if record.previous_record_sha256 != previous or record.phase in seen:
            raise ValueError("broken phase chain")
        current_identity = (
            record.clock.boot_hash,
            record.clock.host_hash,
            record.clock.clock_impl,
            record.clock.adjustability,
            record.clock.resolution,
        )
        if identity is not None and current_identity != identity:
            raise ValueError("clock or identity drift")
        if record.clock.mono_before_ns < last_mono:
            raise ValueError("monotonic rollback")
        identity = current_identity
        last_mono = record.clock.mono_after_ns
        previous = record.record_sha256
        seen.add(record.phase)
        records.append(record)
    for index, record in enumerate(records):
        if record.ordinal != index:
            raise ValueError("non-contiguous phase ordinal")
    return tuple(records)


def read_phases(path: Path, expected_context_sha256: str) -> tuple[PhaseRecord, ...]:
    active = getattr(_ACTIVE_LEDGERS, "paths", set())
    if path.resolve() in active:
        return _read_phases_unlocked(path, expected_context_sha256)
    with _ledger_lock(path, exclusive=False):
        return _read_phases_unlocked(path, expected_context_sha256)


def _append_record(path: Path, record: PhaseRecord) -> None:
    data = _canonical_bytes(_record_dict(record)) + b"\n"
    created = not path.exists()
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    original = os.lseek(fd, 0, os.SEEK_END)
    try:
        _write_exact(fd, data)
        os.fsync(fd)
    except BaseException:
        os.ftruncate(fd, original)
        os.fsync(fd)
        os.close(fd)
        _fsync_parent(path)
        raise
    else:
        os.close(fd)
        if created:
            _fsync_parent(path)


def _new_record(
    phase: str,
    payload_digest: str,
    context: str,
    clock: ClockSample,
    previous: str,
) -> PhaseRecord:
    ordinal = _ORDINALS.get(
        phase, _ORDINALS.get(phase.replace("_failed", "_completed"))
    )
    if ordinal is None:
        raise ValueError("unknown phase")
    partial = PhaseRecord(
        SCHEMA, phase, ordinal, payload_digest, context, clock, previous, ""
    )
    return PhaseRecord(
        **{
            **_record_dict(partial, include_digest=False),
            "clock": clock,
            "record_sha256": canonical_sha256(
                _record_dict(partial, include_digest=False)
            ),
        }
    )


def _check_state(records: tuple[PhaseRecord, ...], phase: str) -> None:
    if any(record.phase.endswith("_failed") for record in records):
        raise ValueError("INVALID_PARTIAL_PHASE")
    if records and records[-1].phase.endswith("_started"):
        raise ValueError("INVALID_PARTIAL_PHASE")
    if any(record.phase.startswith(f"{phase}_") for record in records):
        raise ValueError("duplicate phase")
    expected = _ORDINALS[f"{phase}_started"]
    if len(records) != expected:
        raise ValueError("phase order violation")


def _check_elapsed(
    records: tuple[PhaseRecord, ...],
    current: ClockSample,
    gates: tuple[ElapsedGate, ...],
    *,
    maximum_only: bool = False,
) -> None:
    by_phase = {record.phase: record for record in records}
    for gate in gates:
        anchor = by_phase.get(f"{gate.anchor_phase}_{gate.anchor_record}")
        # A phase may use its just-written started record as its own anchor.
        if (
            anchor is None
            and maximum_only is False
            and _ORDINALS[f"{gate.anchor_phase}_started"] == len(records)
        ):
            # A current-phase started anchor does not exist until after entry
            # checks; its maximum is enforced at terminal sampling.
            continue
        if anchor is None:
            raise ValueError("elapsed anchor missing")
        if not maximum_only and gate.min_seconds is not None:
            lower = current.mono_before_ns - anchor.clock.mono_after_ns
            if lower < gate.min_seconds * 1_000_000_000:
                raise ValueError("elapsed minimum not met")
        if gate.max_seconds is not None:
            upper = current.mono_after_ns - anchor.clock.mono_before_ns
            if upper > gate.max_seconds * 1_000_000_000:
                raise ValueError("elapsed maximum exceeded")


class PhaseGuard:
    def __init__(
        self,
        path: Path,
        phase: str,
        payload: str,
        context: str,
        gates: tuple[ElapsedGate, ...],
        require_bound_payload: bool,
    ) -> None:
        self.path, self.phase, self.payload, self.context, self.gates = (
            path,
            phase,
            payload,
            context,
            gates,
        )
        self._stack = None
        self._bound_payload: str | None = None
        self._require_bound_payload = require_bound_payload

    def bind_payload(self, payload_sha256: str) -> None:
        """Bind a payload created after the phase's started record."""
        _require_digest(payload_sha256, "payload_sha256")
        if self._stack is None:
            raise ValueError("phase guard is not active")
        if self._bound_payload is not None:
            raise ValueError("phase payload already bound")
        self._bound_payload = payload_sha256

    def __enter__(self) -> PhaseGuard:
        from contextlib import ExitStack

        _require_digest(self.payload, "payload_sha256")
        _require_digest(self.context, "expected_context_sha256")
        if self.phase not in _PHASES:
            raise ValueError("unknown phase")
        stack = ExitStack()
        stack.enter_context(_phase_wide_lock(self.path))
        stack.enter_context(_ledger_lock(self.path, exclusive=True))
        self._stack = stack
        active = set(getattr(_ACTIVE_LEDGERS, "paths", set()))
        active.add(self.path.resolve())
        _ACTIVE_LEDGERS.paths = active
        try:
            records = _read_phases_unlocked(self.path, self.context)
            _check_state(records, self.phase)
            clock = _validated_sample(self.context)
            if records:
                _validate_continuity(records[-1].clock, clock)
            _check_elapsed(records, clock, self.gates)
            pending = hashlib.sha256(
                b"SPINE-PENDING-v1\0"
                + self.phase.encode()
                + bytes.fromhex(self.context)
            ).hexdigest()
            previous = records[-1].record_sha256 if records else _genesis(self.context)
            _append_record(
                self.path,
                _new_record(
                    f"{self.phase}_started", pending, self.context, clock, previous
                ),
            )
            return self
        except BaseException:
            self._close()
            raise

    def __exit__(
        self, exc_type: object, exc: BaseException | None, traceback: object
    ) -> bool:
        synthetic_failure = False
        try:
            records = _read_phases_unlocked(self.path, self.context)
            previous = records[-1].record_sha256
            if exc is None and self._require_bound_payload and self._bound_payload is None:
                exc = ValueError("INVALID_WRITE_ONCE")
                synthetic_failure = True
            if exc is None:
                clock = _validated_sample(self.context)
                _validate_continuity(records[-1].clock, clock)
                _check_elapsed(records, clock, self.gates, maximum_only=True)
                _append_record(
                    self.path,
                    _new_record(
                        f"{self.phase}_completed",
                        self._bound_payload or self.payload,
                        self.context,
                        clock,
                        previous,
                    ),
                )
            else:
                payload = {
                    "schema_version": SCHEMA,
                    "phase": self.phase,
                    "error_code": _error_code(exc),
                }
                digest = write_json_once(
                    self.path.parent / f"{self.phase}.failure.json", payload
                )
                clock = _validated_sample(self.context)
                _append_record(
                    self.path,
                    _new_record(
                        f"{self.phase}_failed", digest, self.context, clock, previous
                    ),
                )
                if synthetic_failure:
                    raise exc
        finally:
            self._close()
        return False

    def _close(self) -> None:
        active = set(getattr(_ACTIVE_LEDGERS, "paths", set()))
        active.discard(self.path.resolve())
        _ACTIVE_LEDGERS.paths = active
        if self._stack is not None:
            self._stack.close()
            self._stack = None


def _validate_continuity(previous: ClockSample, current: ClockSample) -> None:
    if (
        previous.boot_hash,
        previous.host_hash,
        previous.clock_impl,
        previous.adjustability,
        previous.resolution,
    ) != (
        current.boot_hash,
        current.host_hash,
        current.clock_impl,
        current.adjustability,
        current.resolution,
    ) or current.mono_before_ns < previous.mono_after_ns:
        raise ValueError("clock or identity discontinuity")


def _error_code(exc: BaseException) -> str:
    allowed = {
        "INVALID_GIT_STATE",
        "INVALID_CONTEXT",
        "INVALID_BINDING",
        "INVALID_PERMISSION",
        "INVALID_RUNNER_ANCHOR",
        "INVALID_PLATFORM_IDENTITY",
        "INVALID_TIMING",
        "INVALID_PARTIAL_PHASE",
        "INVALID_PROVIDER",
        "INVALID_PRODUCT_PROTOCOL",
        "INVALID_WRITE_ONCE",
        "INVALID_INTERNAL_ERROR",
    }
    message = str(exc)
    if message in allowed:
        return message
    if isinstance(exc, FileExistsError):
        return "INVALID_WRITE_ONCE"
    return "INVALID_INTERNAL_ERROR"


def phase_guard(
    path: Path,
    phase: str,
    payload_sha256: str,
    expected_context_sha256: str,
    *,
    elapsed_gates: tuple[ElapsedGate, ...] = (),
    require_bound_payload: bool = False,
) -> PhaseGuard:
    return PhaseGuard(
        path,
        phase,
        payload_sha256,
        expected_context_sha256,
        elapsed_gates,
        require_bound_payload,
    )
