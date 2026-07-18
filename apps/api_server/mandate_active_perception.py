from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    HelpRequest,
    SituatedAssessmentRecord,
    TaskDraftProposal,
    content_digest,
)

from . import data_agent_report_adapter as _report_adapter_module
from .data_agent_report_adapter import (
    DataAgentReportAdapter,
)


Clock = Callable[[], datetime]
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("active perception timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


class ActivePerceptionDisposition(str, Enum):
    COMPLETED = "COMPLETED"
    NOT_DUE = "NOT_DUE"
    LEASE_HELD = "LEASE_HELD"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class MandateActivePerceptionConfig:
    schedule_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    mandate_id: str
    environment_binding_id: str
    interval_seconds: int
    budget_window_seconds: int
    wake_budget_per_window: int
    query_budget_per_window: int
    feed_limit: int
    lease_seconds: int

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.schedule_id,
                self.principal_id,
                self.tenant_id,
                self.workspace_id,
                self.mandate_id,
                self.environment_binding_id,
            )
        ):
            raise ValueError("active perception identity fields must be nonempty")
        if (
            isinstance(self.interval_seconds, bool)
            or self.interval_seconds < 1
            or isinstance(self.budget_window_seconds, bool)
            or self.budget_window_seconds < self.interval_seconds
            or isinstance(self.wake_budget_per_window, bool)
            or self.wake_budget_per_window < 1
            or isinstance(self.query_budget_per_window, bool)
            or self.query_budget_per_window < 1
            or isinstance(self.feed_limit, bool)
            or not 1 <= self.feed_limit <= 100
            or isinstance(self.lease_seconds, bool)
            or self.lease_seconds < 1
        ):
            raise ValueError("active perception bounds are invalid")

    @property
    def config_digest(self) -> str:
        return content_digest(
            {
                "schedule_id": self.schedule_id,
                "principal_id": self.principal_id,
                "tenant_id": self.tenant_id,
                "workspace_id": self.workspace_id,
                "mandate_id": self.mandate_id,
                "environment_binding_id": self.environment_binding_id,
                "interval_seconds": self.interval_seconds,
                "budget_window_seconds": self.budget_window_seconds,
                "wake_budget_per_window": self.wake_budget_per_window,
                "query_budget_per_window": self.query_budget_per_window,
                "feed_limit": self.feed_limit,
                "lease_seconds": self.lease_seconds,
            }
        )


@dataclass(frozen=True)
class ActivePerceptionLease:
    schedule_id: str
    config_digest: str
    worker_id: str
    fence: int
    acquired_at: datetime
    expires_at: datetime
    query_debited: bool


@dataclass(frozen=True)
class ActivePerceptionReceipt:
    receipt_id: str
    receipt_digest: str
    schedule_id: str
    config_digest: str
    disposition: ActivePerceptionDisposition
    worker_id: str
    lease_fence: int
    observed_count: int
    proposal_count: int
    pending_remaining: int
    completed_at: datetime
    activation_authorized: bool = False
    capability_grant_authorized: bool = False
    external_effects_authorized: bool = False


class ActivePerceptionRuntime(Protocol):
    def assert_observation_authority(self) -> str: ...

    def admit_event(self, event_id: str) -> EnvironmentEventAdmissionReceipt: ...

    def propose(
        self, event_id: str, projection_id: str, receipt_id: str
    ) -> TaskDraftProposal | HelpRequest | None: ...

    def propose_record(
        self, event_id: str, projection_id: str, receipt_id: str
    ) -> SituatedAssessmentRecord: ...

    def resolve_assessment_record(
        self, assessment_record_id: str
    ) -> SituatedAssessmentRecord | None: ...


class SQLiteMandateActivePerceptionStore:
    """One narrow durable schedule, budget and lease-fence store."""

    def __init__(self, database: str | Path) -> None:
        database_value = str(database)
        normalized = database_value.strip().lower()
        self._canonical_database_path = (
            None
            if not normalized
            or normalized == ":memory:"
            or normalized.startswith("file:")
            or "mode=memory" in normalized
            else Path(database_value).expanduser().resolve()
        )
        self._database = (
            database_value
            if self._canonical_database_path is None
            else str(self._canonical_database_path)
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mandate_active_perception_schedule (
                        schedule_id TEXT NOT NULL PRIMARY KEY,
                        config_digest TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        mandate_id TEXT NOT NULL,
                        environment_binding_id TEXT NOT NULL,
                        interval_seconds INTEGER NOT NULL,
                        budget_window_seconds INTEGER NOT NULL,
                        wake_budget_per_window INTEGER NOT NULL,
                        query_budget_per_window INTEGER NOT NULL,
                        feed_limit INTEGER NOT NULL,
                        lease_seconds INTEGER NOT NULL,
                        next_wake_at TEXT NOT NULL,
                        window_started_at TEXT NOT NULL,
                        wake_used INTEGER NOT NULL,
                        query_used INTEGER NOT NULL,
                        lease_owner TEXT,
                        lease_fence INTEGER NOT NULL,
                        lease_expires_at TEXT
                    )
                    """
                )
        except sqlite3.Error:
            raise RuntimeError(
                "active perception schedule store is unavailable"
            ) from None

    @property
    def canonical_database_path(self) -> Path | None:
        return self._canonical_database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _immutable(config: MandateActivePerceptionConfig) -> tuple[object, ...]:
        return (
            config.config_digest,
            config.principal_id,
            config.tenant_id,
            config.workspace_id,
            config.mandate_id,
            config.environment_binding_id,
            config.interval_seconds,
            config.budget_window_seconds,
            config.wake_budget_per_window,
            config.query_budget_per_window,
            config.feed_limit,
            config.lease_seconds,
        )

    @staticmethod
    def _parse_time(value: object) -> datetime:
        try:
            return _utc(datetime.fromisoformat(str(value)))
        except (TypeError, ValueError):
            raise RuntimeError(
                "active perception schedule timestamp is invalid"
            ) from None

    def _read_validated(
        self,
        connection: sqlite3.Connection,
        config: MandateActivePerceptionConfig,
    ) -> tuple[Any, ...]:
        row = connection.execute(
            "SELECT * FROM mandate_active_perception_schedule WHERE schedule_id = ?",
            (config.schedule_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("active perception schedule is unavailable")
        if tuple(row[1:13]) != self._immutable(config):
            raise RuntimeError("active perception schedule binding is invalid")
        self._parse_time(row[13])
        self._parse_time(row[14])
        if row[19] is not None:
            self._parse_time(row[19])
        if (
            type(row[15]) is not int
            or type(row[16]) is not int
            or type(row[18]) is not int
            or row[15] < 0
            or row[16] < 0
            or row[18] < 0
        ):
            raise RuntimeError("active perception schedule counters are invalid")
        return row

    def ensure(
        self,
        config: MandateActivePerceptionConfig,
        *,
        first_wake_at: datetime,
    ) -> None:
        first = _utc(first_wake_at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO mandate_active_perception_schedule (
                        schedule_id, config_digest, principal_id, tenant_id,
                        workspace_id, mandate_id, environment_binding_id,
                        interval_seconds, budget_window_seconds,
                        wake_budget_per_window, query_budget_per_window,
                        feed_limit, lease_seconds, next_wake_at,
                        window_started_at, wake_used, query_used, lease_owner,
                        lease_fence, lease_expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0,
                              NULL, 0, NULL)
                    ON CONFLICT(schedule_id) DO NOTHING
                    """,
                    (
                        config.schedule_id,
                        *self._immutable(config),
                        first.isoformat(),
                        first.isoformat(),
                    ),
                )
                self._read_validated(connection, config)
        except sqlite3.Error:
            raise RuntimeError(
                "active perception schedule store is unavailable"
            ) from None

    def reschedule(
        self,
        config: MandateActivePerceptionConfig,
        *,
        next_wake_at: datetime,
    ) -> None:
        target = _utc(next_wake_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._read_validated(connection, config)
            if row[17] is not None:
                raise RuntimeError("active perception schedule lease is held")
            connection.execute(
                "UPDATE mandate_active_perception_schedule SET next_wake_at = ? "
                "WHERE schedule_id = ?",
                (target.isoformat(), config.schedule_id),
            )

    def acquire_due_lease(
        self,
        config: MandateActivePerceptionConfig,
        *,
        worker_id: str,
        now: datetime,
        force_pending: bool = False,
        debit_query: bool = False,
    ) -> ActivePerceptionLease | ActivePerceptionDisposition:
        if not worker_id.strip():
            raise ValueError("active perception worker id must be nonempty")
        current_time = _utc(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease_authority_time = _utc(_report_adapter_module._system_utc_now())
            row = self._read_validated(connection, config)
            next_wake = self._parse_time(row[13])
            window_started = self._parse_time(row[14])
            wake_used = int(row[15])
            query_used = int(row[16])
            owner = None if row[17] is None else str(row[17])
            fence = int(row[18])
            lease_expires = None if row[19] is None else self._parse_time(row[19])
            if (
                owner is not None
                and lease_expires is not None
                and lease_expires > lease_authority_time
            ):
                return ActivePerceptionDisposition.LEASE_HELD
            if not force_pending and current_time < next_wake:
                return ActivePerceptionDisposition.NOT_DUE
            if current_time >= window_started + timedelta(
                seconds=config.budget_window_seconds
            ):
                window_started = current_time
                wake_used = 0
                query_used = 0
            if wake_used >= config.wake_budget_per_window or (
                debit_query and query_used >= config.query_budget_per_window
            ):
                return ActivePerceptionDisposition.BUDGET_EXHAUSTED
            fence += 1
            expires = lease_authority_time + timedelta(
                seconds=config.lease_seconds
            )
            connection.execute(
                """
                UPDATE mandate_active_perception_schedule
                SET window_started_at = ?, wake_used = ?, query_used = ?,
                    lease_owner = ?, lease_fence = ?, lease_expires_at = ?
                WHERE schedule_id = ?
                """,
                (
                    window_started.isoformat(),
                    wake_used + 1,
                    query_used + (1 if debit_query else 0),
                    worker_id,
                    fence,
                    expires.isoformat(),
                    config.schedule_id,
                ),
            )
        return ActivePerceptionLease(
            schedule_id=config.schedule_id,
            config_digest=config.config_digest,
            worker_id=worker_id,
            fence=fence,
            acquired_at=lease_authority_time,
            expires_at=expires,
            query_debited=debit_query,
        )

    def finish(
        self,
        config: MandateActivePerceptionConfig,
        lease: ActivePerceptionLease,
        *,
        next_wake_at: datetime,
    ) -> None:
        target = _utc(next_wake_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._read_validated(connection, config)
            changed = connection.execute(
                """
                UPDATE mandate_active_perception_schedule
                SET next_wake_at = ?, lease_owner = NULL, lease_expires_at = NULL
                WHERE schedule_id = ? AND config_digest = ?
                  AND lease_owner = ? AND lease_fence = ?
                """,
                (
                    target.isoformat(),
                    lease.schedule_id,
                    lease.config_digest,
                    lease.worker_id,
                    lease.fence,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("active perception lease fence is stale")

    def fail(
        self,
        config: MandateActivePerceptionConfig,
        lease: ActivePerceptionLease,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._read_validated(connection, config)
            changed = connection.execute(
                """
                UPDATE mandate_active_perception_schedule
                SET lease_owner = NULL, lease_expires_at = NULL
                WHERE schedule_id = ? AND config_digest = ?
                  AND lease_owner = ? AND lease_fence = ?
                """,
                (
                    lease.schedule_id,
                    lease.config_digest,
                    lease.worker_id,
                    lease.fence,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("active perception lease fence is stale")


class MandateActivePerceptionService:
    """One-shot active perception over the existing trusted admission spine."""

    def __init__(
        self,
        *,
        config: MandateActivePerceptionConfig,
        store: SQLiteMandateActivePerceptionStore,
        adapter: DataAgentReportAdapter,
        runtime: ActivePerceptionRuntime,
        clock: Clock,
    ) -> None:
        report_database = adapter.active_perception_database_path
        if report_database is None or store.canonical_database_path is None:
            raise TypeError(
                "active perception requires SQLite file-backed report state"
            )
        if report_database != store.canonical_database_path:
            raise TypeError(
                "active perception report and schedule database must be identical"
            )
        if adapter.principal_scope != (
            config.principal_id,
            config.tenant_id,
            config.workspace_id,
        ):
            raise TypeError("active perception scope does not match report adapter")
        self.config = config
        self.store = store
        self._adapter = adapter
        self._runtime = runtime
        self._clock = clock

    def ensure_schedule(self, *, first_wake_at: datetime) -> None:
        self.store.ensure(self.config, first_wake_at=first_wake_at)

    def reschedule(self, *, next_wake_at: datetime) -> None:
        self.store.reschedule(self.config, next_wake_at=next_wake_at)

    def _receipt(
        self,
        disposition: ActivePerceptionDisposition,
        *,
        worker_id: str,
        fence: int = 0,
        observed_count: int = 0,
        proposal_count: int = 0,
        pending_remaining: int = 0,
    ) -> ActivePerceptionReceipt:
        completed_at = _utc(self._clock())
        payload = {
            "schedule_id": self.config.schedule_id,
            "config_digest": self.config.config_digest,
            "disposition": disposition.value,
            "worker_id": worker_id,
            "lease_fence": fence,
            "observed_count": observed_count,
            "proposal_count": proposal_count,
            "pending_remaining": pending_remaining,
            "completed_at": completed_at,
            "activation_authorized": False,
            "capability_grant_authorized": False,
            "external_effects_authorized": False,
        }
        digest = content_digest(payload)
        return ActivePerceptionReceipt(
            receipt_id=f"active-perception:{digest}",
            receipt_digest=digest,
            disposition=disposition,
            **{key: value for key, value in payload.items() if key != "disposition"},
        )

    @staticmethod
    def _outcome(
        result: TaskDraftProposal | HelpRequest | None,
    ) -> tuple[str, str]:
        if isinstance(result, TaskDraftProposal):
            kind = "TASK_DRAFT"
        elif isinstance(result, HelpRequest):
            kind = "HELP_REQUEST"
        else:
            kind = "NO_PROPOSAL"
        return kind, content_digest({"outcome_kind": kind, "proposal": result})

    def _assert_same_authority(self, expected: str | None = None) -> str:
        current = self._runtime.assert_observation_authority()
        if not isinstance(current, str) or _DIGEST.fullmatch(current) is None:
            raise RuntimeError("active perception authority snapshot is invalid")
        if expected is not None and current != expected:
            raise RuntimeError("active perception authority changed during run")
        return current

    def run_due_once(self, *, worker_id: str) -> ActivePerceptionReceipt:
        now = _utc(self._clock())
        pending = self._adapter.pending_dispatches()
        needs_query = not pending
        claim = self.store.acquire_due_lease(
            self.config,
            worker_id=worker_id,
            now=now,
            force_pending=bool(pending),
            debit_query=needs_query,
        )
        if isinstance(claim, ActivePerceptionDisposition):
            return self._receipt(claim, worker_id=worker_id)
        lease = claim
        observed_count = 0
        proposal_count = 0
        try:
            authority = self._assert_same_authority()
            if needs_query:
                poll = self._adapter.poll_once(limit=self.config.feed_limit)
                observed_count = len(poll.bundles)
                self._assert_same_authority(authority)
                pending = self._adapter.pending_dispatches()
            for dispatch in pending:
                self._assert_same_authority(authority)
                admission = self._runtime.admit_event(dispatch.environment_event_id)
                self._assert_same_authority(authority)
                outcome_record = self._runtime.propose_record(
                    dispatch.environment_event_id,
                    dispatch.projection_id,
                    admission.receipt_id,
                )
                self._assert_same_authority(authority)
                self._adapter.complete_active_perception_dispatch(
                    dispatch,
                    outcome_record=outcome_record,
                    schedule_id=self.config.schedule_id,
                    config_digest=self.config.config_digest,
                    worker_id=lease.worker_id,
                    lease_fence=lease.fence,
                    completed_at=_utc(self._clock()),
                    authority_snapshot_digest=authority,
                )
                proposal_count += 1
            remaining = len(self._adapter.pending_dispatches())
            self.store.finish(
                self.config,
                lease,
                next_wake_at=now + timedelta(seconds=self.config.interval_seconds),
            )
            return self._receipt(
                ActivePerceptionDisposition.COMPLETED,
                worker_id=worker_id,
                fence=lease.fence,
                observed_count=observed_count,
                proposal_count=proposal_count,
                pending_remaining=remaining,
            )
        except Exception:
            self.store.fail(self.config, lease)
            raise


__all__ = [
    "ActivePerceptionDisposition",
    "ActivePerceptionLease",
    "ActivePerceptionReceipt",
    "MandateActivePerceptionConfig",
    "MandateActivePerceptionService",
    "SQLiteMandateActivePerceptionStore",
]
