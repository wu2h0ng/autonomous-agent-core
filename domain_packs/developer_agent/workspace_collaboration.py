from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from agent_os_contracts import (
    ActionContract,
    CollaborationDisposition,
    ResourceScope,
    WorkLease,
    WorkspaceEvent,
    WorkspaceEventImpact,
    WorkspaceWriteDecision,
)

from agent_os_core.capability import ExecutionLease


class WorkspaceFenceUnavailable(RuntimeError):
    """The coordination fence could not be read to authorize a write."""


class WorkspaceCommitFencePort(Protocol):
    """Coordination-only store: lease, event, cursor, decision.

    Holds no external-effect truth (no PREPARED/COMMITTED/UNKNOWN) and never
    dispatches. External-effect reservation/outcome/UNKNOWN belong to the
    ADR-0059 `DurableActionOutcomeRepository + CapabilityBroker` only.
    """

    def install_lease(self, lease: WorkLease) -> None: ...

    def append_event(self, event: WorkspaceEvent) -> None: ...

    def current_lease(self, workspace_id: str) -> WorkLease | None: ...

    def read_after(self, workspace_id: str, after_cursor: int) -> tuple[WorkspaceEvent, ...]: ...


def _file_scope_from_action(action: ActionContract) -> tuple[ResourceScope, ...]:
    import json

    try:
        args = json.loads(action.arguments_json)
    except Exception:
        return ()
    path = args.get("path") if isinstance(args, dict) else None
    if not isinstance(path, str) or not path:
        return ()
    return (ResourceScope(resource_uri=f"file:///ws/{path}"),)


class WorkspaceCollaborationPreflight:
    """Concrete `CollaborationPreflightPort` over a coordination fence.

    Reads the current lease and events from the fence using only `action` and
    `claim`; never trusts caller-supplied lease/event data. A non-CONTINUE
    decision blocks dispatch before any reservation.
    """

    def __init__(
        self,
        fence: WorkspaceCommitFencePort,
        scope_resolver: Callable[[ActionContract], tuple[ResourceScope, ...]]
        | None = None,
    ) -> None:
        self._fence = fence
        self._scope_resolver = scope_resolver or _file_scope_from_action

    def preflight(
        self, action: ActionContract, claim: ExecutionLease
    ) -> WorkspaceWriteDecision:
        now = datetime.now(timezone.utc)
        lease = self._fence.current_lease(action.workspace_id)
        if lease is None:
            return self._decision(action, lease, CollaborationDisposition.CANCEL, now, "no coordination lease")
        if (
            claim.run_id != lease.run_id
            or claim.owner != lease.holder_id
            or claim.fence != lease.fence_token
        ):
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "execution claim does not bind the work lease"
            )
        if lease.expires_at <= now:
            return self._decision(action, lease, CollaborationDisposition.CANCEL, now, "work lease expired")

        write_scopes = self._scope_resolver(action)
        if write_scopes and not all(
            any(allowed.covers(scope) for allowed in lease.scopes)
            for scope in write_scopes
        ):
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "write scope outside lease"
            )

        events = self._fence.read_after(action.workspace_id, lease.event_cursor)
        relevant: list[str] = []
        disposition = CollaborationDisposition.CONTINUE
        for event in events:
            if write_scopes and not any(
                scope.overlaps(affected)
                for scope in write_scopes
                for affected in event.affected_scopes
            ):
                continue
            relevant.append(event.event_id)
            if event.impact is WorkspaceEventImpact.WRITE_CONFLICT:
                disposition = CollaborationDisposition.CONFLICT
            elif event.impact is WorkspaceEventImpact.WORK_CANCELLED:
                disposition = CollaborationDisposition.CANCEL
            elif disposition is not CollaborationDisposition.CONFLICT:
                disposition = CollaborationDisposition.REPLAN

        return self._decision(
            action,
            lease,
            disposition,
            now,
            "relevant events" if relevant else "no relevant events",
            relevant=tuple(relevant),
            write_scopes=write_scopes,
        )

    def _decision(
        self,
        action: ActionContract,
        lease: WorkLease | None,
        disposition: CollaborationDisposition,
        now: datetime,
        reason: str,
        *,
        relevant: tuple[str, ...] = (),
        write_scopes: tuple[ResourceScope, ...] | None = None,
    ) -> WorkspaceWriteDecision:
        return WorkspaceWriteDecision(
            lease_id=lease.lease_id if lease is not None else "lease:none",
            action_id=action.action_id,
            plan_version=lease.plan_version if lease is not None else 1,
            disposition=disposition,
            checked_event_cursor=lease.event_cursor if lease is not None else 0,
            relevant_event_ids=relevant,
            event_batch_provenance_ref="coordination-store",
            write_scopes=write_scopes or (ResourceScope(resource_uri="file:///ws/unknown"),),
            fence_id="local",
            fence_version=lease.fence_token if lease is not None else None,
            reason=reason,
            decided_at=now,
        )


class WorkspaceCommitFence:
    """In-memory coordination fence. Lease/event/cursor only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, WorkLease] = {}
        self._events: dict[str, list[WorkspaceEvent]] = {}

    def install_lease(self, lease: WorkLease) -> None:
        with self._lock:
            self._leases[lease.workspace_id] = lease

    def append_event(self, event: WorkspaceEvent) -> None:
        with self._lock:
            self._events.setdefault(event.workspace_id, []).append(event)

    def current_lease(self, workspace_id: str) -> WorkLease | None:
        with self._lock:
            return self._leases.get(workspace_id)

    def read_after(self, workspace_id: str, after_cursor: int) -> tuple[WorkspaceEvent, ...]:
        with self._lock:
            return tuple(
                event
                for event in self._events.get(workspace_id, ())
                if event.sequence > after_cursor
            )


class SQLiteWorkspaceCommitFence:
    """Single-host SQLite coordination fence. Lease/event/cursor only."""

    def __init__(self, database: str | Path) -> None:
        self._db_path = str(database)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspace_leases ("
                " workspace_id TEXT PRIMARY KEY,"
                " lease_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspace_events ("
                " workspace_id TEXT NOT NULL,"
                " sequence INTEGER NOT NULL,"
                " event_json TEXT NOT NULL,"
                " PRIMARY KEY (workspace_id, sequence))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def install_lease(self, lease: WorkLease) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workspace_leases(workspace_id, lease_json) "
                "VALUES (?, ?)",
                (lease.workspace_id, lease.model_dump_json()),
            )

    def append_event(self, event: WorkspaceEvent) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workspace_events(workspace_id, sequence, event_json) "
                "VALUES (?, ?, ?)",
                (event.workspace_id, event.sequence, event.model_dump_json()),
            )

    def current_lease(self, workspace_id: str) -> WorkLease | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT lease_json FROM workspace_leases WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkLease.model_validate_json(row[0])

    def read_after(self, workspace_id: str, after_cursor: int) -> tuple[WorkspaceEvent, ...]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json FROM workspace_events WHERE workspace_id = ? AND sequence > ? "
                "ORDER BY sequence",
                (workspace_id, after_cursor),
            ).fetchall()
        return tuple(WorkspaceEvent.model_validate_json(row[0]) for row in rows)


__all__ = [
    "SQLiteWorkspaceCommitFence",
    "WorkspaceCollaborationPreflight",
    "WorkspaceCommitFence",
    "WorkspaceCommitFencePort",
    "WorkspaceFenceUnavailable",
]
