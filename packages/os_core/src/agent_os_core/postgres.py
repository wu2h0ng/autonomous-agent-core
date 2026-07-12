"""PostgreSQL adapter for the same event/lease/idempotency ports.

The local product uses SQLite for zero-setup development. Deployments select this
adapter with a PostgreSQL DSN; no domain code changes when the authority moves.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from agent_os_contracts import TaskEvent, TaskEventDraft

from .errors import ConcurrentWriteError, DuplicateEventError, EventStreamError


class PostgresTaskEventStore:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # pragma: no cover - exercised in deployment image
            raise RuntimeError("PostgresTaskEventStore requires psycopg") from exc
        self._psycopg = psycopg
        self._dsn = dsn
        self._initialize()

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def _initialize(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                  task_id TEXT NOT NULL, sequence BIGINT NOT NULL,
                  event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                  payload_json JSONB NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
                  correlation_id TEXT, causation_id TEXT,
                  UNIQUE(task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                  scope TEXT NOT NULL, key TEXT NOT NULL, response_json JSONB NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(scope, key)
                );
                CREATE TABLE IF NOT EXISTS run_leases (
                  run_id TEXT PRIMARY KEY, fence BIGINT NOT NULL, owner TEXT NOT NULL,
                  expires_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS correction_epochs (
                  scope TEXT NOT NULL, scope_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL, epoch BIGINT NOT NULL, halted BOOLEAN NOT NULL,
                  reason TEXT NOT NULL, written_by TEXT NOT NULL, written_at TIMESTAMPTZ NOT NULL,
                  PRIMARY KEY(scope, scope_id)
                )
                """
            )

    def read(self, task_id: str) -> tuple[TaskEvent, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT task_id, sequence, event_id, event_type, payload_json, occurred_at, correlation_id, causation_id "
                "FROM task_events WHERE task_id=%s ORDER BY sequence", (task_id,)
            )
            rows = cur.fetchall()
        return tuple(TaskEvent(**self._event_row(row)) for row in rows)

    def list_task_ids(self) -> tuple[str, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT task_id, MAX(sequence) AS last_sequence FROM task_events "
                "GROUP BY task_id ORDER BY last_sequence DESC"
            )
            rows = cur.fetchall()
        return tuple(str(row[0]) for row in rows)

    @staticmethod
    def _event_row(row: tuple[Any, ...]) -> dict[str, Any]:
        task_id, sequence, event_id, event_type, payload, occurred_at, correlation_id, causation_id = row
        return {
            "task_id": task_id, "sequence": sequence, "event_id": event_id,
            "event_type": event_type, "payload_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            "occurred_at": occurred_at, "correlation_id": correlation_id, "causation_id": causation_id,
        }

    def append(self, task_id: str, *, expected_sequence: int, drafts: Sequence[TaskEventDraft]) -> tuple[TaskEvent, ...]:
        if not drafts:
            raise EventStreamError("append requires at least one event draft")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (task_id,))
            cur.execute("SELECT COALESCE(MAX(sequence), 0) FROM task_events WHERE task_id=%s", (task_id,))
            row = cur.fetchone()
            actual = int(row[0]) if row is not None else 0
            if actual != expected_sequence:
                raise ConcurrentWriteError(f"expected sequence {expected_sequence}, actual {actual}")
            events: list[TaskEvent] = []
            for offset, draft in enumerate(drafts, start=1):
                if draft.task_id != task_id:
                    raise EventStreamError("event belongs to another task stream")
                sequence = expected_sequence + offset
                try:
                    cur.execute(
                        "INSERT INTO task_events(task_id, sequence, event_id, event_type, payload_json, occurred_at, correlation_id, causation_id) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                        (task_id, sequence, draft.event_id, draft.event_type.value, draft.payload_json, draft.occurred_at, draft.correlation_id, draft.causation_id),
                    )
                except self._psycopg.errors.UniqueViolation as exc:
                    raise DuplicateEventError(f"duplicate event id: {draft.event_id}") from exc
                events.append(TaskEvent(**draft.model_dump(), sequence=sequence))
        return tuple(events)

    def get_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT response_json FROM idempotency_keys WHERE scope=%s AND key=%s", (scope, key))
            row = cur.fetchone()
        return dict(row[0]) if row else None

    def put_idempotency(self, scope: str, key: str, response: dict[str, Any], created_at: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO idempotency_keys(scope,key,response_json,created_at) VALUES (%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                (scope, key, json.dumps(response, sort_keys=True), created_at),
            )
            return cur.rowcount == 1

    def acquire_lease(self, run_id: str, owner: str, expires_at: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT fence, owner, expires_at FROM run_leases WHERE run_id=%s FOR UPDATE", (run_id,))
            row = cur.fetchone()
            now = datetime.now(timezone.utc)
            if row and row[2] > now and row[1] != owner:
                raise ConcurrentWriteError(f"run {run_id} is leased by another worker")
            fence = int(row[0]) + 1 if row else 1
            cur.execute(
                "INSERT INTO run_leases(run_id,fence,owner,expires_at) VALUES (%s,%s,%s,%s) ON CONFLICT(run_id) DO UPDATE SET fence=EXCLUDED.fence,owner=EXCLUDED.owner,expires_at=EXCLUDED.expires_at",
                (run_id, fence, owner, expires_at),
            )
            return fence

    def recover_lease(self, run_id: str, owner: str, expires_at: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT fence FROM run_leases WHERE run_id=%s FOR UPDATE", (run_id,))
            row = cur.fetchone()
            fence = int(row[0]) + 1 if row else 1
            cur.execute(
                "INSERT INTO run_leases(run_id,fence,owner,expires_at) VALUES (%s,%s,%s,%s) ON CONFLICT(run_id) DO UPDATE SET fence=EXCLUDED.fence,owner=EXCLUDED.owner,expires_at=EXCLUDED.expires_at",
                (run_id, fence, owner, expires_at),
            )
            return fence

    def release_lease(self, run_id: str, owner: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE run_leases SET expires_at=%s WHERE run_id=%s AND owner=%s",
                (datetime.now(timezone.utc), run_id, owner),
            )
            return cur.rowcount == 1

    def lease_fence(self, run_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT fence FROM run_leases WHERE run_id=%s", (run_id,))
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def read_correction(self, scope: str, scope_id: str) -> tuple[int, bool, str] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT epoch, halted, reason FROM correction_epochs WHERE scope=%s AND scope_id=%s", (scope, scope_id))
            row = cur.fetchone()
        return (int(row[0]), bool(row[1]), str(row[2])) if row else None

    def write_correction(self, scope: str, scope_id: str, tenant_id: str, workspace_id: str, epoch: int, halted: bool, reason: str, written_by: str, written_at: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO correction_epochs(scope,scope_id,tenant_id,workspace_id,epoch,halted,reason,written_by,written_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(scope,scope_id) DO UPDATE SET epoch=EXCLUDED.epoch,halted=EXCLUDED.halted,reason=EXCLUDED.reason,written_by=EXCLUDED.written_by,written_at=EXCLUDED.written_at",
                (scope, scope_id, tenant_id, workspace_id, epoch, halted, reason, written_by, written_at),
            )

    def advance_correction(
        self,
        scope: str,
        scope_id: str,
        tenant_id: str,
        workspace_id: str,
        halted: bool,
        reason: str,
        written_by: str,
        written_at: str,
    ) -> tuple[int, bool, str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO correction_epochs(scope,scope_id,tenant_id,workspace_id,"
                "epoch,halted,reason,written_by,written_at) "
                "VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s) "
                "ON CONFLICT(scope,scope_id) DO UPDATE SET "
                "tenant_id=EXCLUDED.tenant_id,workspace_id=EXCLUDED.workspace_id,"
                "epoch=correction_epochs.epoch+1,halted=EXCLUDED.halted,"
                "reason=EXCLUDED.reason,written_by=EXCLUDED.written_by,"
                "written_at=EXCLUDED.written_at RETURNING epoch,halted,reason",
                (
                    scope,
                    scope_id,
                    tenant_id,
                    workspace_id,
                    halted,
                    reason,
                    written_by,
                    written_at,
                ),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - PostgreSQL RETURNING contract
            raise RuntimeError("correction advance returned no row")
        return int(row[0]), bool(row[1]), str(row[2])
