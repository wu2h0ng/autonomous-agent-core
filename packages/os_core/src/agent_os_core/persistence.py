"""Small durable substrate used by the local Agent OS deployment.

SQLite is the local adapter for the PostgreSQL repository port.  The important
property here is the transaction and schema boundary, not a second domain model:
the same event-store protocol is used by the in-memory tests and by workers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from agent_os_contracts import TaskEvent, TaskEventDraft

from .errors import ConcurrentWriteError, DuplicateEventError, EventStreamError


class SQLiteTaskEventStore:
    """Crash-safe append-only task event store with lease/idempotency primitives."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_events (
              task_id TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              event_id TEXT NOT NULL UNIQUE,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              correlation_id TEXT,
              causation_id TEXT,
              PRIMARY KEY (task_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS idempotency_keys (
              scope TEXT NOT NULL,
              key TEXT NOT NULL,
              response_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (scope, key)
            );
            CREATE TABLE IF NOT EXISTS run_leases (
              run_id TEXT PRIMARY KEY,
              fence INTEGER NOT NULL,
              owner TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS correction_epochs (
              scope TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              epoch INTEGER NOT NULL,
              halted INTEGER NOT NULL,
              reason TEXT NOT NULL,
              written_by TEXT NOT NULL,
              written_at TEXT NOT NULL,
              PRIMARY KEY (scope, scope_id)
            );
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def read(self, task_id: str) -> tuple[TaskEvent, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY sequence",
                (task_id,),
            ).fetchall()
        return tuple(TaskEvent(**dict(row)) for row in rows)

    def list_task_ids(self) -> tuple[str, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT task_id, MAX(sequence) AS last_sequence FROM task_events "
                "GROUP BY task_id ORDER BY last_sequence DESC"
            ).fetchall()
        return tuple(str(row["task_id"]) for row in rows)

    def append(
        self,
        task_id: str,
        *,
        expected_sequence: int,
        drafts: Sequence[TaskEventDraft],
    ) -> tuple[TaskEvent, ...]:
        if not drafts:
            raise EventStreamError("append requires at least one event draft")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                    "FROM task_events WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                actual = int(row["sequence"])
                if actual != expected_sequence:
                    self._db.rollback()
                    raise ConcurrentWriteError(
                        f"expected sequence {expected_sequence}, actual {actual}"
                    )
                seen: set[str] = set()
                appended: list[TaskEvent] = []
                for offset, draft in enumerate(drafts, start=1):
                    if draft.task_id != task_id:
                        raise EventStreamError(
                            f"event {draft.event_id} belongs to {draft.task_id}, not {task_id}"
                        )
                    if draft.event_id in seen:
                        raise DuplicateEventError(f"duplicate event id: {draft.event_id}")
                    seen.add(draft.event_id)
                    try:
                        self._db.execute(
                            "INSERT INTO task_events "
                            "(task_id, sequence, event_id, event_type, payload_json, "
                            "occurred_at, correlation_id, causation_id) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                task_id,
                                expected_sequence + offset,
                                draft.event_id,
                                draft.event_type.value,
                                draft.payload_json,
                                draft.occurred_at.isoformat(),
                                draft.correlation_id,
                                draft.causation_id,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise DuplicateEventError(
                            f"duplicate event id: {draft.event_id}"
                        ) from exc
                    appended.append(
                        TaskEvent(**draft.model_dump(), sequence=expected_sequence + offset)
                    )
                self._db.commit()
                return tuple(appended)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def get_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT response_json FROM idempotency_keys WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
        if row is None:
            return None
        import json

        return json.loads(row["response_json"])

    def put_idempotency(self, scope: str, key: str, response: dict[str, Any], created_at: str) -> bool:
        import json

        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO idempotency_keys(scope, key, response_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (scope, key, json.dumps(response, sort_keys=True), created_at),
                )
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                self._db.rollback()
                return False

    def acquire_lease(self, run_id: str, owner: str, expires_at: str) -> int:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT fence, owner, expires_at FROM run_leases WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row is not None and row["expires_at"] > now and row["owner"] != owner:
                self._db.rollback()
                raise ConcurrentWriteError(f"run {run_id} is leased by another worker")
            fence = int(row["fence"]) + 1 if row is not None else 1
            self._db.execute(
                "INSERT INTO run_leases(run_id, fence, owner, expires_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET fence=excluded.fence, "
                "owner=excluded.owner, expires_at=excluded.expires_at",
                (run_id, fence, owner, expires_at),
            )
            self._db.commit()
            return fence

    def lease_fence(self, run_id: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT fence FROM run_leases WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row["fence"]) if row is not None else 0

    def recover_lease(self, run_id: str, owner: str, expires_at: str) -> int:
        """Explicit operator/worker recovery takeover after a confirmed dead worker."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT fence FROM run_leases WHERE run_id = ?", (run_id,)
            ).fetchone()
            fence = int(row["fence"]) + 1 if row is not None else 1
            self._db.execute(
                "INSERT INTO run_leases(run_id, fence, owner, expires_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET fence=excluded.fence, owner=excluded.owner, expires_at=excluded.expires_at",
                (run_id, fence, owner, expires_at),
            )
            self._db.commit()
            return fence

    def release_lease(self, run_id: str, owner: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "UPDATE run_leases SET expires_at = ? WHERE run_id = ? AND owner = ?",
                (datetime.now(timezone.utc).isoformat(), run_id, owner),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def read_correction(self, scope: str, scope_id: str) -> tuple[int, bool, str] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT epoch, halted, reason FROM correction_epochs WHERE scope = ? AND scope_id = ?",
                (scope, scope_id),
            ).fetchone()
        if row is None:
            return None
        return int(row["epoch"]), bool(row["halted"]), str(row["reason"])

    def write_correction(
        self,
        scope: str,
        scope_id: str,
        tenant_id: str,
        workspace_id: str,
        epoch: int,
        halted: bool,
        reason: str,
        written_by: str,
        written_at: str,
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO correction_epochs(scope, scope_id, tenant_id, workspace_id, epoch, halted, reason, written_by, written_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(scope, scope_id) DO UPDATE SET "
                "tenant_id=excluded.tenant_id, workspace_id=excluded.workspace_id, epoch=excluded.epoch, "
                "halted=excluded.halted, reason=excluded.reason, written_by=excluded.written_by, written_at=excluded.written_at",
                (scope, scope_id, tenant_id, workspace_id, epoch, int(halted), reason, written_by, written_at),
            )
            self._db.commit()
