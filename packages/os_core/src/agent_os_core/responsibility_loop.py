from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, TypeVar

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


T = TypeVar("T")


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

    def __init__(self, database: str | Path) -> None:
        self._database = Path(database)
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS responsibility_loop_leases (
                    binding_digest TEXT PRIMARY KEY,
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
                CREATE TABLE IF NOT EXISTS responsibility_loop_checkpoints (
                    checkpoint_digest TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responsibility_loop_effects (
                    effect_key TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    cycle_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    operation_slot TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    applied_at TEXT
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
        now = _utc(now)
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM responsibility_loop_leases WHERE binding_digest = ?",
                (binding.digest,),
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
                INSERT INTO responsibility_loop_leases
                (binding_digest,binding_json,process_instance_id,fencing_token,acquired_at,expires_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(binding_digest) DO UPDATE SET
                  process_instance_id=excluded.process_instance_id,
                  fencing_token=excluded.fencing_token,
                  acquired_at=excluded.acquired_at,
                  expires_at=excluded.expires_at
                """,
                (
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

    def _assert_fence(
        self,
        connection: sqlite3.Connection,
        binding: ResponsibilityLoopBinding,
        lease: ResponsibilityLoopLease,
        at: datetime,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM responsibility_loop_leases WHERE binding_digest = ?",
            (binding.digest,),
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
        heartbeat_at = _utc(heartbeat_at)
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, heartbeat_at)
            expires_at = heartbeat_at + timedelta(seconds=binding.lease_ttl_seconds)
            connection.execute(
                "UPDATE responsibility_loop_leases SET expires_at=? WHERE binding_digest=?",
                (_stamp(expires_at), binding.digest),
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
        released_at = _utc(released_at)
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, released_at)
            connection.execute(
                "UPDATE responsibility_loop_leases SET process_instance_id=NULL, "
                "expires_at=? WHERE binding_digest=?",
                (_stamp(released_at), binding.digest),
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
    ) -> ResponsibilityLoopCheckpoint:
        recorded_at = _utc(recorded_at)
        payload = {
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
            connection.execute(
                "INSERT OR IGNORE INTO responsibility_loop_checkpoints VALUES (?,?,?,?,?)",
                (
                    digest,
                    binding.digest,
                    lease.fencing_token,
                    json.dumps(payload, default=str, sort_keys=True),
                    _stamp(recorded_at),
                ),
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
            row = connection.execute(
                "SELECT * FROM responsibility_loop_checkpoints WHERE binding_digest=? "
                "ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
                (binding.digest,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
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
                "binding_digest": binding.digest,
                "mandate_id": binding.mandate_id,
                "cycle_id": cycle_id,
                "task_id": task_id,
                "operation_slot": operation_slot,
                "intent_digest": intent_digest,
            }
        )

    def _effect_from_row(self, row: sqlite3.Row) -> ResponsibilityEffectRecord:
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
        prepared_at = _utc(prepared_at)
        key = self._effect_key(
            binding, cycle_id, task_id, operation_slot, intent_digest
        )
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, prepared_at)
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects WHERE effect_key=?", (key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO responsibility_loop_effects VALUES (?,?,?,?,?,?,?,?,?)",
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
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM responsibility_loop_effects WHERE effect_key=?", (key,)
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
        effect: Callable[[], T],
        executed_at: datetime,
    ) -> ResponsibilityEffectRecord:
        executed_at = _utc(executed_at)
        key = self._effect_key(
            binding, cycle_id, task_id, operation_slot, intent_digest
        )
        with self._effect_lock(), self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, executed_at)
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects WHERE effect_key=?", (key,)
            ).fetchone()
            if row is not None:
                existing = self._effect_from_row(row)
                connection.commit()
                if existing.status == "PREPARED":
                    raise ResponsibilityLoopEffectUnknown(
                        "prepared effect outcome is unknown; reconciliation required"
                    )
                return existing
            connection.execute(
                "INSERT INTO responsibility_loop_effects VALUES (?,?,?,?,?,?,?,?,?)",
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
                ),
            )
            connection.commit()
            try:
                effect()
            except BaseException as exc:
                raise ResponsibilityLoopEffectUnknown(
                    "effect failed after durable preparation; outcome is unknown"
                ) from exc
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, binding, lease, executed_at)
            connection.execute(
                "UPDATE responsibility_loop_effects SET status='APPLIED', applied_at=? "
                "WHERE effect_key=? AND status='PREPARED'",
                (_stamp(executed_at), key),
            )
            row = connection.execute(
                "SELECT * FROM responsibility_loop_effects WHERE effect_key=?", (key,)
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

    def _accepted_outcomes(self, connection: sqlite3.Connection, cycle_id: str) -> int:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='mandate_outcome_settlements'"
        ).fetchone()
        if table is None:
            return 0
        rows = connection.execute(
            "SELECT payload FROM mandate_outcome_settlements"
        ).fetchall()
        accepted = 0
        for row in rows:
            payload = json.loads(str(row["payload"]))
            if (
                payload.get("resulting_state") == "SETTLED_MET"
                and payload.get("cycle_id", cycle_id) == cycle_id
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
        measured_at = _utc(measured_at)
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
            accepted = self._accepted_outcomes(connection, cycle_id)
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
