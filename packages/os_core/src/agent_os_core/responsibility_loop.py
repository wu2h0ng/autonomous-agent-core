from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Mapping

from agent_os_contracts import content_digest


class ResponsibilityLoopError(RuntimeError):
    pass


class ResponsibilityLoopBindingDrift(ResponsibilityLoopError):
    pass


class ResponsibilityLoopLeaseHeld(ResponsibilityLoopError):
    pass


class ResponsibilityLoopStaleFence(ResponsibilityLoopError):
    pass


class ResponsibilityLoopEffectUnknown(ResponsibilityLoopError):
    pass


class HcwEvaluatorRootDrift(ResponsibilityLoopError):
    pass


class ResponsibilityCycleState(str, Enum):
    RUNNING = "RUNNING"
    WAITING_EVENT = "WAITING_EVENT"
    BLOCKED = "BLOCKED"
    STOPPED = "STOPPED"


class OperatorWorkEventKind(str, Enum):
    USER_INPUT = "USER_INPUT"
    HELP_RESPONSE = "HELP_RESPONSE"
    CORRECTION = "CORRECTION"
    ACTIVE_INTERVAL = "ACTIVE_INTERVAL"


class HcwMeasurementStatus(str, Enum):
    MEASURED = "MEASURED"
    HCW_INSUFFICIENT_DATA = "HCW_INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ResponsibilityLoopBinding:
    mandate_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    repository_root: str
    repository_head: str
    correction_epoch: int
    configuration_digest: str
    lease_ttl_seconds: int

    @property
    def digest(self) -> str:
        return content_digest(asdict(self))

    @property
    def lease_scope_id(self) -> str:
        return content_digest(
            {
                "mandate_id": self.mandate_id,
                "tenant_id": self.tenant_id,
                "workspace_id": self.workspace_id,
            }
        )


@dataclass(frozen=True)
class ResponsibilityLoopLease:
    binding_digest: str
    process_instance_id: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    takeover: bool


@dataclass(frozen=True)
class ResponsibilityLoopAuditEvent:
    event_id: int
    binding_digest: str
    event_type: str
    process_instance_id: str
    fencing_token: int
    occurred_at: datetime


@dataclass(frozen=True)
class ResponsibilityLoopCheckpoint:
    checkpoint_digest: str
    binding_digest: str
    fencing_token: int
    state: ResponsibilityCycleState
    active_task_id: str | None
    active_run_id: str | None
    last_event_sequence: int
    next_transition: str
    recorded_at: datetime


@dataclass(frozen=True)
class ResponsibilityCycleReceipt:
    receipt_digest: str
    binding_digest: str
    cycle_id: str
    task_id: str
    run_id: str
    checkpoint_digest: str
    fencing_token: int
    sealed_at: datetime


@dataclass(frozen=True)
class ResponsibilityEffectRecord:
    effect_key: str
    binding_digest: str
    cycle_id: str
    task_id: str
    operation_slot: str
    intent_digest: str
    status: str
    prepared_at: datetime
    applied_at: datetime | None
    effect_receipt_digest: str | None


@dataclass(frozen=True)
class HcwEvaluatorRoot:
    evaluator_root_id: str
    measurement_policy_digest: str
    capture_surface: str
    idle_cutoff_seconds: int

    @property
    def digest(self) -> str:
        return content_digest(asdict(self))


@dataclass(frozen=True)
class OperatorWorkEvent:
    event_id: str
    binding_digest: str
    kind: OperatorWorkEventKind
    cycle_id: str
    task_id: str | None
    run_id: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class HcwMeasurementReceipt:
    receipt_digest: str
    binding_digest: str
    cycle_id: str
    evaluator_root_id: str
    measurement_policy_digest: str
    status: HcwMeasurementStatus
    operator_intervention_count: int
    help_response_count: int
    active_operator_seconds: float | None
    accepted_outcome_count: int
    operator_minutes_per_accepted_outcome: float | None
    measured_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class SQLiteResponsibilityLoopStore:
    """Durable lease, effect-fence, checkpoint and HCW truth for one Work loop."""

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._database = Path(database)
        self._clock = clock
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._database.with_suffix(self._database.suffix + ".loop.lock")
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _effect_lock(self) -> Iterator[None]:
        with self._lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            for legacy_table in (
                "responsibility_loop_leases",
                "responsibility_loop_checkpoints",
                "responsibility_loop_effects",
            ):
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (legacy_table,),
                ).fetchone()
                if exists is not None and connection.execute(
                    f"SELECT 1 FROM {legacy_table} LIMIT 1"
                ).fetchone() is not None:
                    raise ResponsibilityLoopError(
                        "non-empty responsibility loop v1 ledger requires "
                        "an explicit migration"
                    )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS responsibility_loop_leases_v2 (
                    lease_scope_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    binding_json TEXT NOT NULL,
                    process_instance_id TEXT,
                    fencing_token INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_audit (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    binding_digest TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    process_instance_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_checkpoints_v2 (
                    checkpoint_digest TEXT PRIMARY KEY,
                    lease_scope_id TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_checkpoint_heads (
                    lease_scope_id TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL,
                    last_event_sequence INTEGER NOT NULL,
                    PRIMARY KEY (lease_scope_id, binding_digest)
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_effects_v2 (
                    effect_key TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    operation_slot TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    applied_at TEXT,
                    effect_receipt_json TEXT,
                    effect_receipt_digest TEXT
                );
                CREATE TABLE IF NOT EXISTS hcw_evaluator_roots (
                    evaluator_root_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    root_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_work_events (
                    event_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    task_id TEXT,
                    run_id TEXT,
                    occurred_at TEXT NOT NULL,
                    event_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hcw_measurement_receipts (
                    receipt_digest TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_cycle_receipts (
                    receipt_digest TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (binding_digest, cycle_id)
                );
                CREATE TABLE IF NOT EXISTS responsibility_cycle_settlements_v2 (
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    cycle_receipt_digest TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    settlement_id TEXT NOT NULL,
                    settlement_digest TEXT NOT NULL,
                    PRIMARY KEY (binding_digest, cycle_id),
                    UNIQUE (settlement_id)
                );
                """
            )

    def _assert_binding(self, row: sqlite3.Row, binding: ResponsibilityLoopBinding) -> None:
        if row["binding_digest"] != binding.digest:
            raise ResponsibilityLoopBindingDrift("responsibility binding digest drift")
        if json.loads(str(row["binding_json"])) != asdict(binding):
            raise ResponsibilityLoopBindingDrift("responsibility binding payload drift")

    def acquire_lease(
        self,
        binding: ResponsibilityLoopBinding,
        *,
        process_instance_id: str,
        now: datetime,
    ) -> ResponsibilityLoopLease:
        del now
        now = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM responsibility_loop_leases_v2 WHERE lease_scope_id = ?",
                (binding.lease_scope_id,),
            ).fetchone()
            takeover = False
            if row is None:
                token = 1
            else:
                self._assert_binding(row, binding)
                owner = row["process_instance_id"]
                if owner is not None and _parse(str(row["expires_at"])) > now:
                    raise ResponsibilityLoopLeaseHeld("responsibility loop lease is live")
                token = int(row["fencing_token"]) + 1
                takeover = owner is not None
            expires_at = now + timedelta(seconds=binding.lease_ttl_seconds)
            connection.execute(
                """
                INSERT INTO responsibility_loop_leases_v2
                (lease_scope_id,binding_digest,binding_json,process_instance_id,
                 fencing_token,acquired_at,expires_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(lease_scope_id) DO UPDATE SET
                  process_instance_id=excluded.process_instance_id,
                  fencing_token=excluded.fencing_token,
                  acquired_at=excluded.acquired_at,
                  expires_at=excluded.expires_at
                """,
                (
                    binding.lease_scope_id,
                    binding.digest,
                    json.dumps(asdict(binding), sort_keys=True),
                    process_instance_id,
                    token,
                    _stamp(now),
                    _stamp(expires_at),
                ),
            )
            event_type = "LOOP_LEASE_TAKEOVER" if takeover else "LOOP_LEASE_ACQUIRED"
            connection.execute(
                "INSERT INTO responsibility_loop_audit "
                "(binding_digest,event_type,process_instance_id,fencing_token,occurred_at) "
                "VALUES (?,?,?,?,?)",
                (binding.digest, event_type, process_instance_id, token, _stamp(now)),
            )
        return ResponsibilityLoopLease(
            binding.digest, process_instance_id, token, now, expires_at, takeover
        )

    def rebind_inactive_scope(
        self,
        previous: ResponsibilityLoopBinding,
        replacement: ResponsibilityLoopBinding,
    ) -> None:
        if previous.lease_scope_id != replacement.lease_scope_id:
            raise ResponsibilityLoopBindingDrift("lease scope identity cannot change")
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM responsibility_loop_leases_v2 WHERE lease_scope_id=?",
                (previous.lease_scope_id,),
            ).fetchone()
            if row is None:
                raise ResponsibilityLoopBindingDrift("prior lease scope is missing")
            self._assert_binding(row, previous)
            if row["process_instance_id"] is not None:
                raise ResponsibilityLoopLeaseHeld("live lease cannot be rebound")
            connection.execute(
                "UPDATE responsibility_loop_leases_v2 "
                "SET binding_digest=?, binding_json=? WHERE lease_scope_id=?",
                (
                    replacement.digest,
                    json.dumps(asdict(replacement), sort_keys=True),
                    previous.lease_scope_id,
                ),
            )
            connection.execute(
                "INSERT INTO responsibility_loop_audit "
                "(binding_digest,event_type,process_instance_id,fencing_token,occurred_at) "
                "VALUES (?,?,?,?,?)",
                (
                    replacement.digest,
                    "LOOP_BINDING_REBOUND",
                    "external-rebind",
                    int(row["fencing_token"]),
                    _stamp(_utc(self._clock())),
                ),
            )

    def _assert_fence(
        self,
        connection: sqlite3.Connection,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        at: datetime,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM responsibility_loop_leases_v2 WHERE lease_scope_id = ?",
            (binding.lease_scope_id,),
        ).fetchone()
        if row is None:
            raise ResponsibilityLoopStaleFence("responsibility loop lease is missing")
        self._assert_binding(row, binding)
        if (
            lease.binding_digest != binding.digest
            or row["process_instance_id"] != lease.process_instance_id
            or int(row["fencing_token"]) != lease.fencing_token
            or _parse(str(row["expires_at"])) <= _utc(at)
        ):
            raise ResponsibilityLoopStaleFence("responsibility loop fence is stale")
        return row

    def heartbeat_lease(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        heartbeat_at: datetime,
    ) -> ResponsibilityLoopLease:
        del heartbeat_at
        heartbeat_at = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, heartbeat_at)
            expires_at = heartbeat_at + timedelta(seconds=binding.lease_ttl_seconds)
            connection.execute(
                "UPDATE responsibility_loop_leases_v2 SET expires_at=? "
                "WHERE lease_scope_id=?",
                (_stamp(expires_at), binding.lease_scope_id),
            )
        return ResponsibilityLoopLease(
            binding.digest,
            lease.process_instance_id,
            lease.fencing_token,
            lease.acquired_at,
            expires_at,
            lease.takeover,
        )

    def release_lease(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        released_at: datetime,
    ) -> None:
        del released_at
        released_at = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, released_at)
            connection.execute(
                "UPDATE responsibility_loop_leases_v2 SET process_instance_id=NULL, "
                "expires_at=? WHERE lease_scope_id=?",
                (_stamp(released_at), binding.lease_scope_id),
            )

    def list_audit_events(
        self, binding: ResponsibilityLoopBinding
    ) -> list[ResponsibilityLoopAuditEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM responsibility_loop_audit WHERE binding_digest=? "
                "ORDER BY event_id",
                (binding.digest,),
            ).fetchall()
        return [
            ResponsibilityLoopAuditEvent(
                int(row["event_id"]),
                str(row["binding_digest"]),
                str(row["event_type"]),
                str(row["process_instance_id"]),
                int(row["fencing_token"]),
                _parse(str(row["occurred_at"])),
            )
            for row in rows
        ]

    def write_checkpoint(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        state: ResponsibilityCycleState,
        active_task_id: str | None,
        active_run_id: str | None,
        last_event_sequence: int,
        next_transition: str,
        recorded_at: datetime,
        expected_prior_digest: str | None = None,
    ) -> ResponsibilityLoopCheckpoint:
        del recorded_at
        recorded_at = _utc(self._clock())
        payload = {
            "schema_version": "1.0",
            "binding_digest": binding.digest,
            "fencing_token": lease.fencing_token,
            "state": state.value,
            "active_task_id": active_task_id,
            "active_run_id": active_run_id,
            "last_event_sequence": last_event_sequence,
            "next_transition": next_transition,
            "recorded_at": recorded_at,
        }
        digest = content_digest(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, recorded_at)
            head = connection.execute(
                "SELECT * FROM responsibility_loop_checkpoint_heads "
                "WHERE lease_scope_id=? AND binding_digest=?",
                (binding.lease_scope_id, binding.digest),
            ).fetchone()
            if head is not None:
                current = connection.execute(
                    "SELECT payload FROM responsibility_loop_checkpoints_v2 "
                    "WHERE checkpoint_digest=?",
                    (head["checkpoint_digest"],),
                ).fetchone()
                if current is None:
                    raise ResponsibilityLoopBindingDrift(
                        "checkpoint head target is missing"
                    )
                current_payload = json.loads(str(current["payload"]))
                current_digest = str(head["checkpoint_digest"])
                if expected_prior_digest != current_digest:
                    raise ResponsibilityLoopError("checkpoint head compare-and-swap failed")
                if last_event_sequence < int(current_payload["last_event_sequence"]):
                    raise ResponsibilityLoopError(
                        "checkpoint event sequence cannot move backwards"
                    )
            elif expected_prior_digest is not None:
                raise ResponsibilityLoopError("checkpoint prior does not exist")
            connection.execute(
                "INSERT OR IGNORE INTO responsibility_loop_checkpoints_v2 "
                "VALUES (?,?,?,?,?,?)",
                (
                    digest,
                    binding.lease_scope_id,
                    binding.digest,
                    lease.fencing_token,
                    json.dumps(payload, default=str, sort_keys=True),
                    _stamp(recorded_at),
                ),
            )
            if head is None:
                connection.execute(
                    "INSERT INTO responsibility_loop_checkpoint_heads VALUES (?,?,?,?)",
                    (
                        binding.lease_scope_id,
                        binding.digest,
                        digest,
                        last_event_sequence,
                    ),
                )
            else:
                updated = connection.execute(
                    "UPDATE responsibility_loop_checkpoint_heads "
                    "SET checkpoint_digest=?, last_event_sequence=? "
                    "WHERE lease_scope_id=? AND binding_digest=? "
                    "AND checkpoint_digest=?",
                    (
                        digest,
                        last_event_sequence,
                        binding.lease_scope_id,
                        binding.digest,
                        expected_prior_digest,
                    ),
                )
                if updated.rowcount != 1:
                    raise ResponsibilityLoopError(
                        "checkpoint head compare-and-swap failed"
                    )
        return ResponsibilityLoopCheckpoint(
            digest,
            binding.digest,
            lease.fencing_token,
            state,
            active_task_id,
            active_run_id,
            last_event_sequence,
            next_transition,
            recorded_at,
        )

    def latest_checkpoint(
        self, binding: ResponsibilityLoopBinding
    ) -> ResponsibilityLoopCheckpoint | None:
        with self._connect() as connection:
            lease_row = connection.execute(
                "SELECT * FROM responsibility_loop_leases_v2 WHERE lease_scope_id=?",
                (binding.lease_scope_id,),
            ).fetchone()
            if lease_row is None:
                raise ResponsibilityLoopBindingDrift("lease scope is missing")
            self._assert_binding(lease_row, binding)
            head = connection.execute(
                "SELECT checkpoint_digest FROM responsibility_loop_checkpoint_heads "
                "WHERE lease_scope_id=? AND binding_digest=?",
                (binding.lease_scope_id, binding.digest),
            ).fetchone()
            if head is None:
                return None
            row = connection.execute(
                "SELECT * FROM responsibility_loop_checkpoints_v2 "
                "WHERE checkpoint_digest=?",
                (head["checkpoint_digest"],),
            ).fetchone()
        if row is None:
            raise ResponsibilityLoopBindingDrift("checkpoint head target is missing")
        payload = json.loads(str(row["payload"]))
        if payload.get("schema_version") != "1.0":
            raise ResponsibilityLoopBindingDrift("unsupported checkpoint schema")
        expected = content_digest(
            {**payload, "recorded_at": _parse(str(payload["recorded_at"]))}
        )
        if expected != row["checkpoint_digest"]:
            raise ResponsibilityLoopBindingDrift("checkpoint digest drift")
        return ResponsibilityLoopCheckpoint(
            str(row["checkpoint_digest"]),
            binding.digest,
            int(payload["fencing_token"]),
            ResponsibilityCycleState(payload["state"]),
            payload["active_task_id"],
            payload["active_run_id"],
            int(payload["last_event_sequence"]),
            str(payload["next_transition"]),
            _parse(str(payload["recorded_at"])),
        )

    def _effect_key(
        self,
        binding: ResponsibilityLoopBinding,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
    ) -> str:
        return content_digest(
            {
                "lease_scope_id": binding.lease_scope_id,
                "mandate_id": binding.mandate_id,
                "cycle_id": cycle_id,
                "task_id": task_id,
                "operation_slot": operation_slot,
                "intent_digest": intent_digest,
            }
        )

    def _effect_from_row(self, row: sqlite3.Row) -> ResponsibilityEffectRecord:
        receipt_digest = (
            str(row["effect_receipt_digest"]) if row["effect_receipt_digest"] else None
        )
        receipt_json = row["effect_receipt_json"]
        if receipt_digest is not None:
            if receipt_json is None or content_digest(
                json.loads(str(receipt_json))
            ) != receipt_digest:
                raise ResponsibilityLoopBindingDrift("effect receipt digest drift")
        if row["status"] == "APPLIED" and receipt_digest is None:
            raise ResponsibilityLoopBindingDrift("APPLIED effect lacks a receipt")
        return ResponsibilityEffectRecord(
            str(row["effect_key"]),
            str(row["binding_digest"]),
            str(row["cycle_id"]),
            str(row["task_id"]),
            str(row["operation_slot"]),
            str(row["intent_digest"]),
            str(row["status"]),
            _parse(str(row["prepared_at"])),
            _parse(str(row["applied_at"])) if row["applied_at"] else None,
            receipt_digest,
        )

    def prepare_effect(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
        prepared_at: datetime,
    ) -> ResponsibilityEffectRecord:
        del prepared_at
        prepared_at = _utc(self._clock())
        key = self._effect_key(
            binding, cycle_id, task_id, operation_slot, intent_digest
        )
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, prepared_at)
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects_v2 WHERE effect_key=?", (key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO responsibility_loop_effects_v2 "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        binding.digest,
                        cycle_id,
                        task_id,
                        operation_slot,
                        intent_digest,
                        "PREPARED",
                        _stamp(prepared_at),
                        None,
                        None,
                        None,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM responsibility_loop_effects_v2 WHERE effect_key=?",
                    (key,),
                ).fetchone()
            assert row is not None
            return self._effect_from_row(row)

    def execute_effect(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
        effect: Callable[[], Mapping[str, str]],
        executed_at: datetime,
    ) -> ResponsibilityEffectRecord:
        del executed_at
        executed_at = _utc(self._clock())
        key = self._effect_key(
            binding, cycle_id, task_id, operation_slot, intent_digest
        )
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, executed_at)
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects_v2 WHERE effect_key=?", (key,)
            ).fetchone()
            if row is not None:
                existing = self._effect_from_row(row)
                connection.commit()
                if existing.status != "APPLIED":
                    raise ResponsibilityLoopEffectUnknown(
                        "effect outcome is not APPLIED; reconciliation required"
                    )
                return existing
            connection.execute(
                "INSERT INTO responsibility_loop_effects_v2 "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    binding.digest,
                    cycle_id,
                    task_id,
                    operation_slot,
                    intent_digest,
                    "PREPARED",
                    _stamp(executed_at),
                    None,
                    None,
                    None,
                ),
            )
            connection.commit()
        try:
            receipt = dict(effect())
            required = {"receipt_id", "resource_ref", "evidence_digest"}
            if set(receipt) != required or not all(
                isinstance(receipt[field], str) and receipt[field]
                for field in required
            ):
                raise ValueError("effect receipt is not the closed typed shape")
            receipt_envelope = {
                "effect_key": key,
                "intent_digest": intent_digest,
                "adapter_receipt": receipt,
            }
            receipt_digest = content_digest(receipt_envelope)
        except BaseException as exc:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE responsibility_loop_effects_v2 SET status='UNKNOWN' "
                    "WHERE effect_key=? AND status='PREPARED'",
                    (key,),
                )
            raise ResponsibilityLoopEffectUnknown(
                "effect failed after durable preparation; outcome is unknown"
            ) from exc
        completed_at = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_fence(connection, binding, lease, completed_at)
            except ResponsibilityLoopStaleFence:
                connection.execute(
                    "UPDATE responsibility_loop_effects_v2 SET status='UNKNOWN', "
                    "effect_receipt_json=?, effect_receipt_digest=? "
                    "WHERE effect_key=? AND status='PREPARED'",
                    (
                        json.dumps(receipt_envelope, sort_keys=True),
                        receipt_digest,
                        key,
                    ),
                )
                connection.commit()
                raise ResponsibilityLoopEffectUnknown(
                    "effect completed after lease expiry or takeover; reconciliation required"
                )
            connection.execute(
                "UPDATE responsibility_loop_effects_v2 SET status='APPLIED', applied_at=?, "
                "effect_receipt_json=?, effect_receipt_digest=? "
                "WHERE effect_key=? AND status='PREPARED'",
                (
                    _stamp(completed_at),
                    json.dumps(receipt_envelope, sort_keys=True),
                    receipt_digest,
                    key,
                ),
            )
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects_v2 WHERE effect_key=?", (key,)
            ).fetchone()
            assert row is not None
            return self._effect_from_row(row)

    def ensure_hcw_evaluator_root(self, root: HcwEvaluatorRoot) -> None:
        payload = json.dumps(asdict(root), sort_keys=True)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM hcw_evaluator_roots WHERE evaluator_root_id=?",
                (root.evaluator_root_id,),
            ).fetchone()
            if existing is not None:
                if existing["root_digest"] != root.digest or existing["payload"] != payload:
                    raise HcwEvaluatorRootDrift("HCW evaluator root is immutable")
                return
            connection.execute(
                "INSERT INTO hcw_evaluator_roots VALUES (?,?,?)",
                (root.evaluator_root_id, payload, root.digest),
            )

    def append_operator_work_event(
        self,
        binding: ResponsibilityLoopBinding,
        *,
        event_id: str,
        kind: OperatorWorkEventKind,
        cycle_id: str,
        task_id: str | None,
        run_id: str | None,
        occurred_at: datetime,
    ) -> OperatorWorkEvent:
        occurred_at = _utc(occurred_at)
        payload = {
            "event_id": event_id,
            "binding_digest": binding.digest,
            "kind": kind.value,
            "cycle_id": cycle_id,
            "task_id": task_id,
            "run_id": run_id,
            "occurred_at": occurred_at,
        }
        digest = content_digest(payload)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operator_work_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is not None and row["event_digest"] != digest:
                raise ResponsibilityLoopBindingDrift("operator event id was rebound")
            connection.execute(
                "INSERT OR IGNORE INTO operator_work_events VALUES (?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    binding.digest,
                    kind.value,
                    cycle_id,
                    task_id,
                    run_id,
                    _stamp(occurred_at),
                    digest,
                ),
            )
        return OperatorWorkEvent(
            event_id, binding.digest, kind, cycle_id, task_id, run_id, occurred_at
        )

    def seal_cycle_receipt(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        cycle_id: str,
        task_id: str,
        run_id: str,
        checkpoint_digest: str,
    ) -> ResponsibilityCycleReceipt:
        sealed_at = _utc(self._clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, sealed_at)
            head = connection.execute(
                "SELECT checkpoint_digest FROM responsibility_loop_checkpoint_heads "
                "WHERE lease_scope_id=? AND binding_digest=?",
                (binding.lease_scope_id, binding.digest),
            ).fetchone()
            if head is None or head["checkpoint_digest"] != checkpoint_digest:
                raise ResponsibilityLoopBindingDrift(
                    "cycle receipt requires the canonical checkpoint head"
                )
            checkpoint = connection.execute(
                "SELECT payload FROM responsibility_loop_checkpoints_v2 "
                "WHERE checkpoint_digest=?",
                (checkpoint_digest,),
            ).fetchone()
            if checkpoint is None:
                raise ResponsibilityLoopBindingDrift("cycle checkpoint is missing")
            checkpoint_payload = json.loads(str(checkpoint["payload"]))
            if (
                checkpoint_payload.get("active_task_id") != task_id
                or checkpoint_payload.get("active_run_id") != run_id
            ):
                raise ResponsibilityLoopBindingDrift(
                    "cycle task/run does not match the checkpoint"
                )
            payload = {
                "schema_version": "1.0",
                "binding_digest": binding.digest,
                "cycle_id": cycle_id,
                "task_id": task_id,
                "run_id": run_id,
                "checkpoint_digest": checkpoint_digest,
                "fencing_token": lease.fencing_token,
                "sealed_at": sealed_at,
            }
            digest = content_digest(payload)
            existing = connection.execute(
                "SELECT * FROM responsibility_cycle_receipts "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchone()
            if existing is not None:
                if existing["receipt_digest"] != digest:
                    raise ResponsibilityLoopBindingDrift("cycle receipt was rebound")
            else:
                connection.execute(
                    "INSERT INTO responsibility_cycle_receipts VALUES (?,?,?,?,?,?,?,?)",
                    (
                        digest,
                        binding.digest,
                        cycle_id,
                        task_id,
                        run_id,
                        checkpoint_digest,
                        lease.fencing_token,
                        json.dumps(payload, default=str, sort_keys=True),
                    ),
                )
        return ResponsibilityCycleReceipt(
            digest,
            binding.digest,
            cycle_id,
            task_id,
            run_id,
            checkpoint_digest,
            lease.fencing_token,
            sealed_at,
        )

    def bind_cycle_settlement(
        self,
        binding: ResponsibilityLoopBinding,
        *,
        cycle_id: str,
        task_id: str,
        settlement_id: str,
        expected_settlement_digest: str,
        cycle_receipt_digest: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='mandate_outcome_settlements'"
            ).fetchone()
            if table is None:
                raise ResponsibilityLoopBindingDrift("settlement ledger is missing")
            cycle_receipt = connection.execute(
                "SELECT * FROM responsibility_cycle_receipts "
                "WHERE receipt_digest=?",
                (cycle_receipt_digest,),
            ).fetchone()
            if (
                cycle_receipt is None
                or cycle_receipt["binding_digest"] != binding.digest
                or cycle_receipt["cycle_id"] != cycle_id
                or cycle_receipt["task_id"] != task_id
                or content_digest(
                    {
                        **json.loads(str(cycle_receipt["payload"])),
                        "sealed_at": _parse(
                            str(json.loads(str(cycle_receipt["payload"]))["sealed_at"])
                        ),
                    }
                )
                != cycle_receipt_digest
            ):
                raise ResponsibilityLoopBindingDrift("cycle receipt binding drift")
            row = connection.execute(
                "SELECT payload, record_digest FROM mandate_outcome_settlements "
                "WHERE settlement_id=?",
                (settlement_id,),
            ).fetchone()
            if row is None:
                raise ResponsibilityLoopBindingDrift("settlement is missing")
            payload = json.loads(str(row["payload"]))
            stored_digest = str(row["record_digest"])
            unsigned_payload = dict(payload)
            unsigned_payload.pop("record_digest", None)
            if (
                stored_digest != expected_settlement_digest
                or payload.get("record_digest") != stored_digest
                or content_digest(unsigned_payload) != stored_digest
                or payload.get("mandate_id") != binding.mandate_id
                or payload.get("task_id") != task_id
            ):
                raise ResponsibilityLoopBindingDrift("settlement binding drift")
            existing = connection.execute(
                "SELECT * FROM responsibility_cycle_settlements_v2 "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchone()
            if existing is not None and (
                existing["settlement_id"] != settlement_id
                or existing["settlement_digest"] != expected_settlement_digest
                or existing["cycle_receipt_digest"] != cycle_receipt_digest
            ):
                raise ResponsibilityLoopBindingDrift("cycle settlement was rebound")
            settlement_use = connection.execute(
                "SELECT binding_digest, cycle_id FROM "
                "responsibility_cycle_settlements_v2 WHERE settlement_id=?",
                (settlement_id,),
            ).fetchone()
            if settlement_use is not None and (
                settlement_use["binding_digest"] != binding.digest
                or settlement_use["cycle_id"] != cycle_id
            ):
                raise ResponsibilityLoopBindingDrift(
                    "settlement is already bound to another cycle"
                )
            connection.execute(
                "INSERT OR IGNORE INTO responsibility_cycle_settlements_v2 "
                "VALUES (?,?,?,?,?,?)",
                (
                    binding.digest,
                    cycle_id,
                    cycle_receipt_digest,
                    task_id,
                    settlement_id,
                    expected_settlement_digest,
                ),
            )

    def _accepted_outcomes(
        self,
        connection: sqlite3.Connection,
        binding: ResponsibilityLoopBinding,
        cycle_id: str,
    ) -> int:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='mandate_outcome_settlements'"
        ).fetchone()
        if table is None:
            return 0
        rows = connection.execute(
            """
            SELECT s.payload, s.record_digest, b.settlement_digest
            FROM responsibility_cycle_settlements_v2 AS b
            JOIN mandate_outcome_settlements AS s
              ON s.settlement_id = b.settlement_id
            WHERE b.binding_digest = ? AND b.cycle_id = ?
            """,
            (binding.digest, cycle_id),
        ).fetchall()
        accepted = 0
        for row in rows:
            payload = json.loads(str(row["payload"]))
            stored_digest = str(row["record_digest"])
            payload_digest = str(payload.get("record_digest", ""))
            unsigned_payload = dict(payload)
            unsigned_payload.pop("record_digest", None)
            if (
                stored_digest != payload_digest
                or stored_digest != row["settlement_digest"]
                or content_digest(unsigned_payload) != stored_digest
            ):
                raise ResponsibilityLoopBindingDrift("settlement digest drift")
            if (
                payload.get("resulting_state") == "SETTLED_MET"
            ):
                accepted += 1
        return accepted

    def measure_hcw(
        self,
        binding: ResponsibilityLoopBinding,
        *,
        cycle_id: str,
        evaluator_root_id: str,
        measured_at: datetime,
    ) -> HcwMeasurementReceipt:
        del measured_at
        measured_at = _utc(self._clock())
        with self._connect() as connection:
            root_row = connection.execute(
                "SELECT * FROM hcw_evaluator_roots WHERE evaluator_root_id=?",
                (evaluator_root_id,),
            ).fetchone()
            if root_row is None:
                raise HcwEvaluatorRootDrift("HCW evaluator root is missing")
            root_payload = json.loads(str(root_row["payload"]))
            root = HcwEvaluatorRoot(**root_payload)
            if root.digest != root_row["root_digest"]:
                raise HcwEvaluatorRootDrift("HCW evaluator root digest drift")
            rows = connection.execute(
                "SELECT kind FROM operator_work_events "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchall()
            kinds = [OperatorWorkEventKind(str(row["kind"])) for row in rows]
            interventions = sum(
                kind
                in {
                    OperatorWorkEventKind.USER_INPUT,
                    OperatorWorkEventKind.HELP_RESPONSE,
                    OperatorWorkEventKind.CORRECTION,
                }
                for kind in kinds
            )
            help_count = sum(
                kind is OperatorWorkEventKind.HELP_RESPONSE for kind in kinds
            )
            accepted = self._accepted_outcomes(connection, binding, cycle_id)
            active_seconds = None
            status = HcwMeasurementStatus.HCW_INSUFFICIENT_DATA
            per_outcome = None
            payload = {
                "binding_digest": binding.digest,
                "cycle_id": cycle_id,
                "evaluator_root_id": evaluator_root_id,
                "measurement_policy_digest": root.measurement_policy_digest,
                "status": status.value,
                "operator_intervention_count": interventions,
                "help_response_count": help_count,
                "active_operator_seconds": active_seconds,
                "accepted_outcome_count": accepted,
                "operator_minutes_per_accepted_outcome": per_outcome,
                "measured_at": measured_at,
            }
            digest = content_digest(payload)
            connection.execute(
                "INSERT OR IGNORE INTO hcw_measurement_receipts VALUES (?,?,?,?)",
                (
                    digest,
                    binding.digest,
                    cycle_id,
                    json.dumps(payload, default=str, sort_keys=True),
                ),
            )
        return HcwMeasurementReceipt(
            digest,
            binding.digest,
            cycle_id,
            evaluator_root_id,
            root.measurement_policy_digest,
            status,
            interventions,
            help_count,
            active_seconds,
            accepted,
            per_outcome,
            measured_at,
        )
