from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from agent_os_contracts import (
    OutcomePortfolio,
    OutcomeStatus,
    PersistentCommitment,
    PersistentCommitmentState,
    SettlementRecord,
    TaskEventType,
    content_digest,
)


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
class ResponsibilityLoopRebindReceipt:
    receipt_digest: str
    lease_scope_id: str
    previous_binding_digest: str
    replacement_binding_digest: str
    actor_principal_id: str
    reason: str
    authority_ref: str
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
    active_cycle_id: str | None = None
    active_link_id: str | None = None
    active_commitment_record_id: str | None = None
    responsibility_projection_digest: str | None = None
    active_help_request_id: str | None = None


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
                    lease_scope_id TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    process_instance_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_rebind_receipts (
                    receipt_digest TEXT PRIMARY KEY,
                    lease_scope_id TEXT NOT NULL,
                    previous_binding_digest TEXT NOT NULL,
                    replacement_binding_digest TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    authority_ref TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_audit_rebind_receipts (
                    audit_event_id INTEGER PRIMARY KEY,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    lease_scope_id TEXT NOT NULL
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
                CREATE TABLE IF NOT EXISTS responsibility_loop_effect_identities (
                    identity_digest TEXT PRIMARY KEY,
                    effect_key TEXT NOT NULL UNIQUE,
                    lease_scope_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    operation_slot TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    UNIQUE (
                        lease_scope_id, mandate_id, cycle_id, task_id,
                        operation_slot, intent_digest
                    )
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
                CREATE TABLE IF NOT EXISTS responsibility_cycle_settlement_reservations (
                    reservation_digest TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    cycle_receipt_digest TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    settlement_id TEXT NOT NULL,
                    settlement_digest TEXT NOT NULL,
                    UNIQUE (binding_digest, cycle_id),
                    UNIQUE (settlement_id)
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_schema_meta (
                    schema_name TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL
                );
                """
            )
            self._migrate_foundation_schema(connection)

    def _migrate_foundation_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        """Upgrade the unreleased foundation schema without losing live truth."""
        connection.execute("BEGIN IMMEDIATE")
        audit_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(responsibility_loop_audit)"
            ).fetchall()
        }
        if "lease_scope_id" not in audit_columns:
            connection.execute(
                "ALTER TABLE responsibility_loop_audit "
                "ADD COLUMN lease_scope_id TEXT"
            )
        link_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(responsibility_loop_audit_rebind_receipts)"
            ).fetchall()
        }
        if "lease_scope_id" not in link_columns:
            connection.execute(
                "ALTER TABLE responsibility_loop_audit_rebind_receipts "
                "ADD COLUMN lease_scope_id TEXT"
            )
        connection.execute(
            """
            UPDATE responsibility_loop_audit_rebind_receipts
            SET lease_scope_id = (
                SELECT r.lease_scope_id
                FROM responsibility_loop_rebind_receipts AS r
                WHERE r.receipt_digest =
                    responsibility_loop_audit_rebind_receipts.receipt_digest
            )
            WHERE lease_scope_id IS NULL
            """
        )
        connection.execute(
            """
            UPDATE responsibility_loop_audit
            SET lease_scope_id = COALESCE(
                (
                    SELECT ar.lease_scope_id
                    FROM responsibility_loop_audit_rebind_receipts AS ar
                    WHERE ar.audit_event_id = responsibility_loop_audit.event_id
                ),
                (
                    SELECT r.lease_scope_id
                    FROM responsibility_loop_rebind_receipts AS r
                    WHERE r.previous_binding_digest =
                              responsibility_loop_audit.binding_digest
                       OR r.replacement_binding_digest =
                              responsibility_loop_audit.binding_digest
                    LIMIT 1
                ),
                (
                    SELECT l.lease_scope_id
                    FROM responsibility_loop_leases_v2 AS l
                    WHERE l.binding_digest =
                              responsibility_loop_audit.binding_digest
                    LIMIT 1
                )
            )
            WHERE lease_scope_id IS NULL
            """
        )
        missing_link_scope = connection.execute(
            "SELECT 1 FROM responsibility_loop_audit_rebind_receipts "
            "WHERE lease_scope_id IS NULL LIMIT 1"
        ).fetchone()
        missing_audit_scope = connection.execute(
            "SELECT 1 FROM responsibility_loop_audit "
            "WHERE lease_scope_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_link_scope is not None or missing_audit_scope is not None:
            raise ResponsibilityLoopError(
                "responsibility foundation schema migration requires "
                "unambiguous lease scope provenance"
            )
        bridges = connection.execute(
            "SELECT * FROM responsibility_cycle_settlements_v2"
        ).fetchall()
        for bridge in bridges:
            payload = {
                "schema_version": "1.0",
                "binding_digest": str(bridge["binding_digest"]),
                "cycle_id": str(bridge["cycle_id"]),
                "cycle_receipt_digest": str(bridge["cycle_receipt_digest"]),
                "task_id": str(bridge["task_id"]),
                "settlement_id": str(bridge["settlement_id"]),
                "settlement_digest": str(bridge["settlement_digest"]),
            }
            connection.execute(
                "INSERT OR IGNORE INTO "
                "responsibility_cycle_settlement_reservations "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    content_digest(payload),
                    payload["binding_digest"],
                    payload["cycle_id"],
                    payload["cycle_receipt_digest"],
                    payload["task_id"],
                    payload["settlement_id"],
                    payload["settlement_digest"],
                ),
            )
        connection.execute(
            "INSERT INTO responsibility_loop_schema_meta VALUES (?,?) "
            "ON CONFLICT(schema_name) DO UPDATE SET schema_version=excluded.schema_version",
            ("responsibility_loop", 3),
        )
        connection.commit()

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
                "(lease_scope_id,binding_digest,event_type,process_instance_id,"
                "fencing_token,occurred_at) VALUES (?,?,?,?,?,?)",
                (
                    binding.lease_scope_id,
                    binding.digest,
                    event_type,
                    process_instance_id,
                    token,
                    _stamp(now),
                ),
            )
        return ResponsibilityLoopLease(
            binding.digest, process_instance_id, token, now, expires_at, takeover
        )

    def rebind_inactive_scope(
        self,
        previous: ResponsibilityLoopBinding,
        replacement: ResponsibilityLoopBinding,
        *,
        actor_principal_id: str,
        reason: str,
        authority_ref: str,
    ) -> None:
        if not actor_principal_id or not reason or not authority_ref:
            raise ValueError("rebind provenance fields must be non-empty")
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
            occurred_at = _utc(self._clock())
            receipt_payload = {
                "schema_version": "1.0",
                "lease_scope_id": previous.lease_scope_id,
                "previous_binding_digest": previous.digest,
                "replacement_binding_digest": replacement.digest,
                "actor_principal_id": actor_principal_id,
                "reason": reason,
                "authority_ref": authority_ref,
                "occurred_at": occurred_at,
            }
            receipt_digest = content_digest(receipt_payload)
            connection.execute(
                "INSERT INTO responsibility_loop_rebind_receipts "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    receipt_digest,
                    previous.lease_scope_id,
                    previous.digest,
                    replacement.digest,
                    actor_principal_id,
                    reason,
                    authority_ref,
                    json.dumps(receipt_payload, default=str, sort_keys=True),
                ),
            )
            audit_cursor = connection.execute(
                "INSERT INTO responsibility_loop_audit "
                "(lease_scope_id,binding_digest,event_type,process_instance_id,"
                "fencing_token,occurred_at) VALUES (?,?,?,?,?,?)",
                (
                    previous.lease_scope_id,
                    replacement.digest,
                    "LOOP_BINDING_REBOUND",
                    actor_principal_id,
                    int(row["fencing_token"]),
                    _stamp(occurred_at),
                ),
            )
            if audit_cursor.lastrowid is None:
                raise ResponsibilityLoopError("rebind audit insert did not return an id")
            connection.execute(
                "INSERT INTO responsibility_loop_audit_rebind_receipts VALUES (?,?,?)",
                (
                    int(audit_cursor.lastrowid),
                    receipt_digest,
                    previous.lease_scope_id,
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

    def assert_active_lease(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
    ) -> None:
        """Fail closed unless this exact process/fence still owns a live lease."""
        checked_at = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN")
            self._assert_fence(connection, binding, lease, checked_at)

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

    def runtime_status(
        self,
        binding: ResponsibilityLoopBinding,
    ) -> dict[str, Any]:
        checked_at = _utc(self._clock())
        with self._connect() as connection:
            lease = connection.execute(
                "SELECT * FROM responsibility_loop_leases_v2 "
                "WHERE lease_scope_id=?",
                (binding.lease_scope_id,),
            ).fetchone()
            if lease is not None:
                self._assert_binding(lease, binding)
            effect_rows = connection.execute(
                "SELECT * FROM responsibility_loop_effects_v2 "
                "WHERE binding_digest=?",
                (binding.digest,),
            ).fetchall()
            task_event_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='task_events'"
            ).fetchone()
            applied_without_task_receipt = 0
            for effect_row in effect_rows:
                if effect_row["status"] != "APPLIED":
                    continue
                try:
                    envelope = json.loads(
                        str(effect_row["effect_receipt_json"])
                    )
                    adapter_receipt = envelope["adapter_receipt"]
                    evidence_digest = adapter_receipt["evidence_digest"]
                except (
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                ):
                    raise ResponsibilityLoopBindingDrift(
                        "APPLIED effect receipt is malformed"
                    ) from None
                task_receipt_bound = False
                if task_event_table is not None:
                    task_events = connection.execute(
                        "SELECT payload_json FROM task_events "
                        "WHERE task_id=? AND event_type=?",
                        (
                            str(effect_row["task_id"]),
                            TaskEventType.ACTION_RECEIPT_RECORDED.value,
                        ),
                    ).fetchall()
                    for task_event in task_events:
                        try:
                            receipt = json.loads(
                                str(task_event["payload_json"])
                            ).get("receipt")
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if (
                            isinstance(receipt, dict)
                            and content_digest(receipt) == evidence_digest
                        ):
                            task_receipt_bound = True
                            break
                if not task_receipt_bound:
                    applied_without_task_receipt += 1
            unknown_effect_count = sum(
                row["status"] != "APPLIED" for row in effect_rows
            ) + applied_without_task_receipt
            hcw_row = connection.execute(
                "SELECT * FROM hcw_measurement_receipts "
                "WHERE binding_digest=? ORDER BY rowid DESC LIMIT 1",
                (binding.digest,),
            ).fetchone()
        last_hcw = None
        if hcw_row is not None:
            try:
                payload = json.loads(str(hcw_row["payload"]))
                measured_at = _parse(str(payload.get("measured_at")))
            except (json.JSONDecodeError, TypeError, ValueError):
                raise ResponsibilityLoopBindingDrift(
                    "HCW status receipt is malformed"
                ) from None
            if (
                content_digest({**payload, "measured_at": measured_at})
                != hcw_row["receipt_digest"]
            ):
                raise ResponsibilityLoopBindingDrift(
                    "HCW status receipt digest drift"
                )
            last_hcw = {
                "receipt_digest": str(hcw_row["receipt_digest"]),
                **payload,
            }
        return {
            "lease": {
                "owned": bool(
                    lease is not None
                    and lease["process_instance_id"] is not None
                    and _parse(str(lease["expires_at"])) > checked_at
                ),
                "process_instance_id": (
                    str(lease["process_instance_id"])
                    if lease is not None
                    and lease["process_instance_id"] is not None
                    else None
                ),
                "fencing_token": (
                    int(lease["fencing_token"])
                    if lease is not None
                    else None
                ),
                "expires_at": (
                    str(lease["expires_at"]) if lease is not None else None
                ),
            },
            "unknown_effect_count": unknown_effect_count,
            "applied_without_task_receipt_count": (
                applied_without_task_receipt
            ),
            "last_hcw_receipt": last_hcw,
        }

    def list_rebind_receipts(
        self,
        binding: ResponsibilityLoopBinding,
    ) -> list[ResponsibilityLoopRebindReceipt]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, a.event_id AS audit_event_id,
                       a.binding_digest AS audit_binding_digest,
                       a.event_type AS audit_event_type,
                       a.process_instance_id AS audit_actor,
                       a.occurred_at AS audit_occurred_at
                FROM responsibility_loop_rebind_receipts AS r
                JOIN responsibility_loop_audit_rebind_receipts AS ar
                  ON ar.receipt_digest = r.receipt_digest
                JOIN responsibility_loop_audit AS a
                  ON a.event_id = ar.audit_event_id
                WHERE ar.lease_scope_id=?
                ORDER BY a.event_id
                """,
                (binding.lease_scope_id,),
            ).fetchall()
            receipt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM responsibility_loop_rebind_receipts "
                    "WHERE lease_scope_id=?",
                    (binding.lease_scope_id,),
                ).fetchone()[0]
            )
            link_count = int(
                connection.execute(
                    "SELECT COUNT(*) "
                    "FROM responsibility_loop_audit_rebind_receipts "
                    "WHERE lease_scope_id=?",
                    (binding.lease_scope_id,),
                ).fetchone()[0]
            )
            audit_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM responsibility_loop_audit "
                    "WHERE lease_scope_id=? AND event_type='LOOP_BINDING_REBOUND'",
                    (binding.lease_scope_id,),
                ).fetchone()[0]
            )
        if (
            receipt_count != len(rows)
            or link_count != len(rows)
            or audit_count != len(rows)
        ):
            raise ResponsibilityLoopBindingDrift(
                "rebind receipt audit linkage drift"
            )
        receipts: list[ResponsibilityLoopRebindReceipt] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            occurred_at = _parse(str(payload["occurred_at"]))
            if (
                set(payload)
                != {
                    "schema_version",
                    "lease_scope_id",
                    "previous_binding_digest",
                    "replacement_binding_digest",
                    "actor_principal_id",
                    "reason",
                    "authority_ref",
                    "occurred_at",
                }
                or payload["schema_version"] != "1.0"
                or content_digest({**payload, "occurred_at": occurred_at})
                != row["receipt_digest"]
                or payload["lease_scope_id"] != row["lease_scope_id"]
                or payload["previous_binding_digest"]
                != row["previous_binding_digest"]
                or payload["replacement_binding_digest"]
                != row["replacement_binding_digest"]
                or payload["actor_principal_id"] != row["actor_principal_id"]
                or payload["reason"] != row["reason"]
                or payload["authority_ref"] != row["authority_ref"]
                or row["audit_binding_digest"]
                != row["replacement_binding_digest"]
                or row["lease_scope_id"] != binding.lease_scope_id
                or row["audit_event_type"] != "LOOP_BINDING_REBOUND"
                or row["audit_actor"] != row["actor_principal_id"]
                or _parse(str(row["audit_occurred_at"])) != occurred_at
            ):
                raise ResponsibilityLoopBindingDrift(
                    "rebind receipt provenance drift"
                )
            receipts.append(
                ResponsibilityLoopRebindReceipt(
                    str(row["receipt_digest"]),
                    str(row["lease_scope_id"]),
                    str(row["previous_binding_digest"]),
                    str(row["replacement_binding_digest"]),
                    str(row["actor_principal_id"]),
                    str(row["reason"]),
                    str(row["authority_ref"]),
                    occurred_at,
                )
            )
        return receipts

    def write_checkpoint(
        self,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        *,
        state: ResponsibilityCycleState,
        active_task_id: str | None,
        active_run_id: str | None,
        active_cycle_id: str | None = None,
        active_link_id: str | None = None,
        active_commitment_record_id: str | None = None,
        responsibility_projection_digest: str | None = None,
        active_help_request_id: str | None = None,
        last_event_sequence: int,
        next_transition: str,
        recorded_at: datetime,
        expected_prior_digest: str | None = None,
    ) -> ResponsibilityLoopCheckpoint:
        del recorded_at
        recorded_at = _utc(self._clock())
        responsibility_identity = (
            active_cycle_id,
            active_link_id,
            active_commitment_record_id,
            responsibility_projection_digest,
        )
        if any(value is not None for value in responsibility_identity):
            if not all(
                isinstance(value, str) and bool(value.strip())
                for value in responsibility_identity
            ):
                raise ResponsibilityLoopError(
                    "checkpoint responsibility identity must be complete"
                )
            if (
                responsibility_projection_digest is None
                or len(responsibility_projection_digest) != 64
            ):
                raise ResponsibilityLoopError(
                    "checkpoint responsibility projection digest is invalid"
                )
        if active_help_request_id is not None and not active_help_request_id.strip():
            raise ResponsibilityLoopError(
                "checkpoint active Help request id is invalid"
            )
        payload = {
            "schema_version": "1.2",
            "binding_digest": binding.digest,
            "fencing_token": lease.fencing_token,
            "state": state.value,
            "active_cycle_id": active_cycle_id,
            "active_link_id": active_link_id,
            "active_commitment_record_id": active_commitment_record_id,
            "responsibility_projection_digest": responsibility_projection_digest,
            "active_help_request_id": active_help_request_id,
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
            checkpoint_digest=digest,
            binding_digest=binding.digest,
            fencing_token=lease.fencing_token,
            state=state,
            active_task_id=active_task_id,
            active_run_id=active_run_id,
            last_event_sequence=last_event_sequence,
            next_transition=next_transition,
            recorded_at=recorded_at,
            active_cycle_id=active_cycle_id,
            active_link_id=active_link_id,
            active_commitment_record_id=active_commitment_record_id,
            responsibility_projection_digest=responsibility_projection_digest,
            active_help_request_id=active_help_request_id,
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
                return None
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
        if payload.get("schema_version") not in {"1.0", "1.1", "1.2"}:
            raise ResponsibilityLoopBindingDrift("unsupported checkpoint schema")
        expected = content_digest(
            {**payload, "recorded_at": _parse(str(payload["recorded_at"]))}
        )
        if expected != row["checkpoint_digest"]:
            raise ResponsibilityLoopBindingDrift("checkpoint digest drift")
        identity = (
            payload.get("active_cycle_id"),
            payload.get("active_link_id"),
            payload.get("active_commitment_record_id"),
            payload.get("responsibility_projection_digest"),
        )
        if any(value is not None for value in identity) and not all(
            isinstance(value, str) and bool(value.strip()) for value in identity
        ):
            raise ResponsibilityLoopBindingDrift(
                "checkpoint responsibility identity is incomplete"
            )
        projection_digest = payload.get("responsibility_projection_digest")
        if projection_digest is not None and len(str(projection_digest)) != 64:
            raise ResponsibilityLoopBindingDrift(
                "checkpoint responsibility projection digest is invalid"
            )
        active_help_request_id = payload.get("active_help_request_id")
        if (
            active_help_request_id is not None
            and (
                not isinstance(active_help_request_id, str)
                or not active_help_request_id.strip()
            )
        ):
            raise ResponsibilityLoopBindingDrift(
                "checkpoint active Help request id is invalid"
            )
        return ResponsibilityLoopCheckpoint(
            checkpoint_digest=str(row["checkpoint_digest"]),
            binding_digest=binding.digest,
            fencing_token=int(payload["fencing_token"]),
            state=ResponsibilityCycleState(payload["state"]),
            active_task_id=payload["active_task_id"],
            active_run_id=payload["active_run_id"],
            last_event_sequence=int(payload["last_event_sequence"]),
            next_transition=str(payload["next_transition"]),
            recorded_at=_parse(str(payload["recorded_at"])),
            active_cycle_id=payload.get("active_cycle_id"),
            active_link_id=payload.get("active_link_id"),
            active_commitment_record_id=payload.get(
                "active_commitment_record_id"
            ),
            responsibility_projection_digest=projection_digest,
            active_help_request_id=active_help_request_id,
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

    def _effect_from_row(
        self,
        row: sqlite3.Row,
        binding: ResponsibilityLoopBinding,
        *,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
    ) -> ResponsibilityEffectRecord:
        actual_identity = {
            "cycle_id": str(row["cycle_id"]),
            "task_id": str(row["task_id"]),
            "operation_slot": str(row["operation_slot"]),
            "intent_digest": str(row["intent_digest"]),
        }
        expected_identity = {
            "cycle_id": cycle_id,
            "task_id": task_id,
            "operation_slot": operation_slot,
            "intent_digest": intent_digest,
        }
        expected_key = self._effect_key(
            binding,
            actual_identity["cycle_id"],
            actual_identity["task_id"],
            actual_identity["operation_slot"],
            actual_identity["intent_digest"],
        )
        if actual_identity != expected_identity or row["effect_key"] != expected_key:
            raise ResponsibilityLoopBindingDrift("effect ledger identity drift")
        receipt_digest = (
            str(row["effect_receipt_digest"]) if row["effect_receipt_digest"] else None
        )
        receipt_json = row["effect_receipt_json"]
        if receipt_digest is not None:
            receipt_envelope = (
                json.loads(str(receipt_json)) if receipt_json is not None else None
            )
            if (
                not isinstance(receipt_envelope, dict)
                or set(receipt_envelope)
                != {"effect_key", "intent_digest", "adapter_receipt"}
                or receipt_envelope["effect_key"] != expected_key
                or receipt_envelope["intent_digest"] != intent_digest
                or not isinstance(receipt_envelope["adapter_receipt"], dict)
                or set(receipt_envelope["adapter_receipt"])
                != {"receipt_id", "resource_ref", "evidence_digest"}
                or not all(
                    isinstance(value, str) and value
                    for value in receipt_envelope["adapter_receipt"].values()
                )
                or content_digest(receipt_envelope) != receipt_digest
            ):
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

    def _effect_row_for_identity(
        self,
        connection: sqlite3.Connection,
        binding: ResponsibilityLoopBinding,
        *,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
    ) -> tuple[str, sqlite3.Row | None]:
        key = self._effect_key(
            binding, cycle_id, task_id, operation_slot, intent_digest
        )
        reservation = connection.execute(
            "SELECT * FROM responsibility_loop_effect_identities "
            "WHERE identity_digest=?",
            (key,),
        ).fetchone()
        row = connection.execute(
            "SELECT * FROM responsibility_loop_effects_v2 WHERE effect_key=?",
            (key,),
        ).fetchone()
        if reservation is None:
            if row is not None:
                raise ResponsibilityLoopBindingDrift(
                    "effect row lacks its identity reservation"
                )
            return key, None
        if (
            reservation["effect_key"] != key
            or reservation["lease_scope_id"] != binding.lease_scope_id
            or reservation["mandate_id"] != binding.mandate_id
            or reservation["cycle_id"] != cycle_id
            or reservation["task_id"] != task_id
            or reservation["operation_slot"] != operation_slot
            or reservation["intent_digest"] != intent_digest
        ):
            raise ResponsibilityLoopBindingDrift(
                "effect identity reservation drift"
            )
        if row is None:
            raise ResponsibilityLoopBindingDrift(
                "effect identity reservation target is missing"
            )
        return key, row

    def _reserve_effect_identity(
        self,
        connection: sqlite3.Connection,
        binding: ResponsibilityLoopBinding,
        *,
        key: str,
        cycle_id: str,
        task_id: str,
        operation_slot: str,
        intent_digest: str,
    ) -> None:
        connection.execute(
            "INSERT INTO responsibility_loop_effect_identities "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                key,
                key,
                binding.lease_scope_id,
                binding.mandate_id,
                cycle_id,
                task_id,
                operation_slot,
                intent_digest,
            ),
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
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, prepared_at)
            key, row = self._effect_row_for_identity(
                connection,
                binding,
                cycle_id=cycle_id,
                task_id=task_id,
                operation_slot=operation_slot,
                intent_digest=intent_digest,
            )
            if row is None:
                self._reserve_effect_identity(
                    connection,
                    binding,
                    key=key,
                    cycle_id=cycle_id,
                    task_id=task_id,
                    operation_slot=operation_slot,
                    intent_digest=intent_digest,
                )
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
            return self._effect_from_row(
                row,
                binding,
                cycle_id=cycle_id,
                task_id=task_id,
                operation_slot=operation_slot,
                intent_digest=intent_digest,
            )

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
        reconcile_idempotent: bool = False,
    ) -> ResponsibilityEffectRecord:
        del executed_at
        executed_at = _utc(self._clock())
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, executed_at)
            key, row = self._effect_row_for_identity(
                connection,
                binding,
                cycle_id=cycle_id,
                task_id=task_id,
                operation_slot=operation_slot,
                intent_digest=intent_digest,
            )
            existing: ResponsibilityEffectRecord | None = None
            if row is not None:
                existing = self._effect_from_row(
                    row,
                    binding,
                    cycle_id=cycle_id,
                    task_id=task_id,
                    operation_slot=operation_slot,
                    intent_digest=intent_digest,
                )
                connection.commit()
                if not reconcile_idempotent and existing.status != "APPLIED":
                    raise ResponsibilityLoopEffectUnknown(
                        "effect outcome is not APPLIED; reconciliation required"
                    )
                if not reconcile_idempotent:
                    return existing
                key = existing.effect_key
                existing_receipt_json = row["effect_receipt_json"]
                existing_status = existing.status
            else:
                existing_receipt_json = None
                existing_status = None
            if row is None:
                self._reserve_effect_identity(
                    connection,
                    binding,
                    key=key,
                    cycle_id=cycle_id,
                    task_id=task_id,
                    operation_slot=operation_slot,
                    intent_digest=intent_digest,
                )
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
            if existing_status == "APPLIED":
                assert existing is not None
                stored = (
                    json.loads(str(existing_receipt_json))
                    if existing_receipt_json is not None
                    else None
                )
                stored_adapter = (
                    stored.get("adapter_receipt")
                    if isinstance(stored, dict)
                    else None
                )
                if (
                    not isinstance(stored_adapter, dict)
                    or stored_adapter.get("resource_ref")
                    != receipt.get("resource_ref")
                ):
                    raise ValueError(
                        "idempotent reconciliation resource identity drifted"
                    )
                return existing
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE responsibility_loop_effects_v2 SET status='UNKNOWN' "
                    "WHERE effect_key=? AND status IN ('PREPARED','UNKNOWN')",
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
                "WHERE effect_key=? AND status IN ('PREPARED','UNKNOWN')",
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
            return self._effect_from_row(
                row,
                binding,
                cycle_id=cycle_id,
                task_id=task_id,
                operation_slot=operation_slot,
                intent_digest=intent_digest,
            )

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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            checked_at = _utc(self._clock())
            self._assert_fence(connection, binding, lease, checked_at)
            existing = connection.execute(
                "SELECT * FROM responsibility_cycle_receipts "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(str(existing["payload"]))
                if (
                    existing_payload.get("schema_version") != "1.0"
                    or existing_payload.get("binding_digest") != binding.digest
                    or existing_payload.get("cycle_id") != cycle_id
                    or existing_payload.get("task_id") != task_id
                    or existing_payload.get("run_id") != run_id
                    or existing_payload.get("checkpoint_digest")
                    != checkpoint_digest
                    or existing_payload.get("fencing_token") != lease.fencing_token
                ):
                    raise ResponsibilityLoopBindingDrift("cycle receipt was rebound")
                sealed_at = _parse(str(existing_payload["sealed_at"]))
                if (
                    content_digest({**existing_payload, "sealed_at": sealed_at})
                    != existing["receipt_digest"]
                ):
                    raise ResponsibilityLoopBindingDrift(
                        "cycle receipt content digest drift"
                    )
                return ResponsibilityCycleReceipt(
                    str(existing["receipt_digest"]),
                    binding.digest,
                    cycle_id,
                    task_id,
                    run_id,
                    checkpoint_digest,
                    lease.fencing_token,
                    sealed_at,
                )
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
                "SELECT * FROM responsibility_loop_checkpoints_v2 "
                "WHERE checkpoint_digest=?",
                (checkpoint_digest,),
            ).fetchone()
            if checkpoint is None:
                raise ResponsibilityLoopBindingDrift("cycle checkpoint is missing")
            checkpoint_payload = json.loads(str(checkpoint["payload"]))
            if (
                checkpoint_payload.get("schema_version")
                not in {"1.0", "1.1", "1.2"}
                or checkpoint_payload.get("binding_digest") != binding.digest
                or checkpoint["binding_digest"] != binding.digest
                or checkpoint["lease_scope_id"] != binding.lease_scope_id
                or checkpoint_payload.get("fencing_token") != lease.fencing_token
                or checkpoint["fencing_token"] != lease.fencing_token
            ):
                raise ResponsibilityLoopStaleFence(
                    "cycle checkpoint was not written under the active fence"
                )
            checkpoint_expected = content_digest(
                {
                    **checkpoint_payload,
                    "recorded_at": _parse(str(checkpoint_payload["recorded_at"])),
                }
            )
            if checkpoint_expected != checkpoint_digest:
                raise ResponsibilityLoopBindingDrift("cycle checkpoint digest drift")
            if (
                checkpoint_payload.get("active_task_id") != task_id
                or checkpoint_payload.get("active_run_id") != run_id
            ):
                raise ResponsibilityLoopBindingDrift(
                    "cycle task/run does not match the checkpoint"
                )
            sealed_at = checked_at
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

    def get_cycle_receipt(
        self,
        binding: ResponsibilityLoopBinding,
        cycle_id: str,
    ) -> ResponsibilityCycleReceipt | None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM responsibility_cycle_receipts "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchall()
        if len(rows) > 1:
            raise ResponsibilityLoopBindingDrift(
                "responsibility cycle receipt is ambiguous"
            )
        if not rows:
            return None
        row = rows[0]
        try:
            payload = json.loads(str(row["payload"]))
            sealed_at = _parse(str(payload.get("sealed_at")))
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ResponsibilityLoopBindingDrift(
                "responsibility cycle receipt is malformed"
            ) from None
        if (
            payload.get("schema_version") != "1.0"
            or payload.get("binding_digest") != binding.digest
            or payload.get("cycle_id") != cycle_id
            or payload.get("task_id") != row["task_id"]
            or payload.get("run_id") != row["run_id"]
            or payload.get("checkpoint_digest") != row["checkpoint_digest"]
            or payload.get("fencing_token") != row["fencing_token"]
            or content_digest({**payload, "sealed_at": sealed_at})
            != row["receipt_digest"]
        ):
            raise ResponsibilityLoopBindingDrift(
                "responsibility cycle receipt digest drift"
            )
        return ResponsibilityCycleReceipt(
            str(row["receipt_digest"]),
            binding.digest,
            cycle_id,
            str(row["task_id"]),
            str(row["run_id"]),
            str(row["checkpoint_digest"]),
            int(row["fencing_token"]),
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
            try:
                settlement = SettlementRecord.model_validate(payload)
            except Exception as exc:
                raise ResponsibilityLoopBindingDrift(
                    "settlement contract validation failed"
                ) from exc
            stored_digest = str(row["record_digest"])
            unsigned_payload = dict(payload)
            unsigned_payload.pop("record_digest", None)
            expected_state = {
                OutcomeStatus.VERIFIED: PersistentCommitmentState.SETTLED_MET,
                OutcomeStatus.NOT_MET: PersistentCommitmentState.SETTLED_NOT_MET,
                OutcomeStatus.INVALID: PersistentCommitmentState.INVALID,
                OutcomeStatus.UNRESOLVED: PersistentCommitmentState.INVALID,
            }[settlement.observed_status]
            if (
                stored_digest != expected_settlement_digest
                or settlement.record_digest != stored_digest
                or content_digest(unsigned_payload) != stored_digest
                or settlement.mandate_id != binding.mandate_id
                or settlement.task_id != task_id
                or settlement.resulting_state is not expected_state
            ):
                raise ResponsibilityLoopBindingDrift("settlement binding drift")
            scope_row = connection.execute(
                """
                SELECT c.payload AS commitment_payload,
                       c.record_digest AS commitment_digest,
                       p.payload AS portfolio_payload,
                       p.record_digest AS portfolio_digest
                FROM mandate_persistent_commitments AS c
                JOIN mandate_outcome_portfolios AS p
                  ON p.portfolio_id = c.portfolio_id
                WHERE c.commitment_record_id=? AND c.portfolio_id=?
                """,
                (settlement.commitment_record_id, settlement.portfolio_id),
            ).fetchone()
            if scope_row is None:
                raise ResponsibilityLoopBindingDrift(
                    "canonical commitment/portfolio scope is missing"
                )
            try:
                commitment = PersistentCommitment.model_validate_json(
                    str(scope_row["commitment_payload"])
                )
                portfolio = OutcomePortfolio.model_validate_json(
                    str(scope_row["portfolio_payload"])
                )
            except Exception as exc:
                raise ResponsibilityLoopBindingDrift(
                    "canonical commitment/portfolio contract validation failed"
                ) from exc
            commitment_unsigned = commitment.model_dump(
                mode="python", exclude={"record_digest"}, exclude_none=True
            )
            portfolio_unsigned = portfolio.model_dump(
                mode="python", exclude={"record_digest"}, exclude_none=True
            )
            if (
                commitment.record_digest != scope_row["commitment_digest"]
                or content_digest(commitment_unsigned) != commitment.record_digest
                or portfolio.record_digest != scope_row["portfolio_digest"]
                or content_digest(portfolio_unsigned) != portfolio.record_digest
                or commitment.portfolio_id != portfolio.portfolio_id
                or commitment.commitment_record_id
                != settlement.commitment_record_id
                or commitment.task_id != settlement.task_id
                or commitment.expected_outcome_digest
                != settlement.expected_outcome_digest
                or commitment.state is not settlement.resulting_state
                or commitment.mandate_id != binding.mandate_id
                or commitment.principal_id != binding.principal_id
                or commitment.tenant_id != binding.tenant_id
                or commitment.workspace_id != binding.workspace_id
                or portfolio.mandate_id != binding.mandate_id
                or portfolio.principal_id != binding.principal_id
                or portfolio.tenant_id != binding.tenant_id
                or portfolio.workspace_id != binding.workspace_id
                or commitment.correction_epoch != binding.correction_epoch
                or portfolio.correction_epoch != binding.correction_epoch
            ):
                raise ResponsibilityLoopBindingDrift(
                    "canonical commitment/portfolio scope drift"
                )
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
            reservation_payload = {
                "schema_version": "1.0",
                "binding_digest": binding.digest,
                "cycle_id": cycle_id,
                "cycle_receipt_digest": cycle_receipt_digest,
                "task_id": task_id,
                "settlement_id": settlement_id,
                "settlement_digest": expected_settlement_digest,
            }
            reservation_digest = content_digest(reservation_payload)
            connection.execute(
                "INSERT OR IGNORE INTO "
                "responsibility_cycle_settlement_reservations "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    reservation_digest,
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
        bridge_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM responsibility_cycle_settlements_v2 "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchone()[0]
        )
        reservations = connection.execute(
            "SELECT * FROM responsibility_cycle_settlement_reservations "
            "WHERE binding_digest=? AND cycle_id=?",
            (binding.digest, cycle_id),
        ).fetchall()
        if bridge_count != len(reservations):
            raise ResponsibilityLoopBindingDrift(
                "cycle settlement reservation drift"
            )
        for reservation in reservations:
            expected_reservation = content_digest(
                {
                    "schema_version": "1.0",
                    "binding_digest": str(reservation["binding_digest"]),
                    "cycle_id": str(reservation["cycle_id"]),
                    "cycle_receipt_digest": str(
                        reservation["cycle_receipt_digest"]
                    ),
                    "task_id": str(reservation["task_id"]),
                    "settlement_id": str(reservation["settlement_id"]),
                    "settlement_digest": str(reservation["settlement_digest"]),
                }
            )
            bridge = connection.execute(
                "SELECT * FROM responsibility_cycle_settlements_v2 "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchone()
            if (
                expected_reservation != reservation["reservation_digest"]
                or bridge is None
                or bridge["cycle_receipt_digest"]
                != reservation["cycle_receipt_digest"]
                or bridge["task_id"] != reservation["task_id"]
                or bridge["settlement_id"] != reservation["settlement_id"]
                or bridge["settlement_digest"] != reservation["settlement_digest"]
            ):
                raise ResponsibilityLoopBindingDrift(
                    "cycle settlement reservation content drift"
                )
        rows = connection.execute(
            """
            SELECT s.payload, s.record_digest, b.settlement_digest,
                   b.task_id AS bridge_task_id,
                   b.cycle_receipt_digest AS bridge_receipt_digest,
                   b.settlement_id AS bridge_settlement_id,
                   r.payload AS cycle_receipt_payload,
                   r.receipt_digest AS cycle_receipt_digest,
                   c.payload AS commitment_payload,
                   c.record_digest AS commitment_digest,
                   c.commitment_record_id AS commitment_row_id,
                   c.portfolio_id AS commitment_row_portfolio_id,
                   c.mandate_id AS commitment_row_mandate_id,
                   c.task_id AS commitment_row_task_id,
                   c.state AS commitment_row_state,
                   p.payload AS portfolio_payload,
                   p.record_digest AS portfolio_digest,
                   p.portfolio_id AS portfolio_row_id,
                   p.mandate_id AS portfolio_row_mandate_id,
                   p.tenant_id AS portfolio_row_tenant_id,
                   p.workspace_id AS portfolio_row_workspace_id,
                   p.principal_id AS portfolio_row_principal_id
            FROM responsibility_cycle_settlements_v2 AS b
            JOIN responsibility_cycle_receipts AS r
              ON r.receipt_digest = b.cycle_receipt_digest
            JOIN mandate_outcome_settlements AS s
              ON s.settlement_id = b.settlement_id
            JOIN mandate_persistent_commitments AS c
              ON c.commitment_record_id = s.commitment_record_id
             AND c.portfolio_id = s.portfolio_id
            JOIN mandate_outcome_portfolios AS p
              ON p.portfolio_id = c.portfolio_id
            WHERE b.binding_digest = ? AND b.cycle_id = ?
            """,
            (binding.digest, cycle_id),
        ).fetchall()
        if bridge_count != len(rows):
            raise ResponsibilityLoopBindingDrift(
                "cycle outcome truth linkage drift"
            )
        accepted = 0
        for row in rows:
            payload = json.loads(str(row["payload"]))
            try:
                settlement = SettlementRecord.model_validate(payload)
                commitment = PersistentCommitment.model_validate_json(
                    str(row["commitment_payload"])
                )
                portfolio = OutcomePortfolio.model_validate_json(
                    str(row["portfolio_payload"])
                )
                cycle_receipt_payload = json.loads(
                    str(row["cycle_receipt_payload"])
                )
            except Exception as exc:
                raise ResponsibilityLoopBindingDrift(
                    "outcome truth contract validation failed"
                ) from exc
            stored_digest = str(row["record_digest"])
            unsigned_payload = dict(payload)
            unsigned_payload.pop("record_digest", None)
            expected_state = {
                OutcomeStatus.VERIFIED: PersistentCommitmentState.SETTLED_MET,
                OutcomeStatus.NOT_MET: PersistentCommitmentState.SETTLED_NOT_MET,
                OutcomeStatus.INVALID: PersistentCommitmentState.INVALID,
                OutcomeStatus.UNRESOLVED: PersistentCommitmentState.INVALID,
            }[settlement.observed_status]
            commitment_unsigned = commitment.model_dump(
                mode="python", exclude={"record_digest"}, exclude_none=True
            )
            portfolio_unsigned = portfolio.model_dump(
                mode="python", exclude={"record_digest"}, exclude_none=True
            )
            cycle_receipt_expected = content_digest(
                {
                    **cycle_receipt_payload,
                    "sealed_at": _parse(str(cycle_receipt_payload["sealed_at"])),
                }
            )
            if (
                stored_digest != settlement.record_digest
                or stored_digest != row["settlement_digest"]
                or content_digest(unsigned_payload) != stored_digest
                or settlement.mandate_id != binding.mandate_id
                or settlement.resulting_state is not expected_state
                or row["bridge_task_id"] != settlement.task_id
                or row["bridge_settlement_id"] != settlement.settlement_id
                or row["bridge_receipt_digest"] != row["cycle_receipt_digest"]
                or cycle_receipt_expected != row["cycle_receipt_digest"]
                or cycle_receipt_payload.get("schema_version") != "1.0"
                or cycle_receipt_payload.get("binding_digest") != binding.digest
                or cycle_receipt_payload.get("cycle_id") != cycle_id
                or cycle_receipt_payload.get("task_id") != settlement.task_id
                or commitment.record_digest != row["commitment_digest"]
                or content_digest(commitment_unsigned) != commitment.record_digest
                or portfolio.record_digest != row["portfolio_digest"]
                or content_digest(portfolio_unsigned) != portfolio.record_digest
                or commitment.commitment_record_id
                != settlement.commitment_record_id
                or commitment.portfolio_id != settlement.portfolio_id
                or commitment.task_id != settlement.task_id
                or commitment.expected_outcome_digest
                != settlement.expected_outcome_digest
                or commitment.state is not settlement.resulting_state
                or commitment.correction_epoch != binding.correction_epoch
                or commitment.mandate_id != binding.mandate_id
                or commitment.principal_id != binding.principal_id
                or commitment.tenant_id != binding.tenant_id
                or commitment.workspace_id != binding.workspace_id
                or portfolio.mandate_id != binding.mandate_id
                or portfolio.principal_id != binding.principal_id
                or portfolio.tenant_id != binding.tenant_id
                or portfolio.workspace_id != binding.workspace_id
                or portfolio.correction_epoch != binding.correction_epoch
                or row["commitment_row_id"] != commitment.commitment_record_id
                or row["commitment_row_portfolio_id"] != commitment.portfolio_id
                or row["commitment_row_mandate_id"] != commitment.mandate_id
                or row["commitment_row_task_id"] != commitment.task_id
                or row["commitment_row_state"] != commitment.state.value
                or row["portfolio_row_id"] != portfolio.portfolio_id
                or row["portfolio_row_mandate_id"] != portfolio.mandate_id
                or row["portfolio_row_tenant_id"] != portfolio.tenant_id
                or row["portfolio_row_workspace_id"] != portfolio.workspace_id
                or row["portfolio_row_principal_id"] != portfolio.principal_id
            ):
                raise ResponsibilityLoopBindingDrift("settlement digest drift")
            if settlement.resulting_state is PersistentCommitmentState.SETTLED_MET:
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
            existing_rows = connection.execute(
                "SELECT * FROM hcw_measurement_receipts "
                "WHERE binding_digest=? AND cycle_id=?",
                (binding.digest, cycle_id),
            ).fetchall()
            matching_existing = [
                (row, json.loads(str(row["payload"])))
                for row in existing_rows
                if json.loads(str(row["payload"])).get("evaluator_root_id")
                == evaluator_root_id
            ]
            if len(matching_existing) > 1:
                raise HcwEvaluatorRootDrift(
                    "HCW cycle has ambiguous evaluator receipts"
                )
            if matching_existing:
                measured_at = _parse(
                    str(matching_existing[0][1]["measured_at"])
                )
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
            encoded_payload = json.dumps(payload, default=str, sort_keys=True)
            if matching_existing:
                existing_row, existing_payload = matching_existing[0]
                if (
                    str(existing_row["receipt_digest"]) != digest
                    or json.dumps(existing_payload, sort_keys=True)
                    != encoded_payload
                ):
                    raise HcwEvaluatorRootDrift(
                        "HCW cycle receipt drifted after measurement"
                    )
            else:
                connection.execute(
                    "INSERT INTO hcw_measurement_receipts VALUES (?,?,?,?)",
                    (
                        digest,
                        binding.digest,
                        cycle_id,
                        encoded_payload,
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
