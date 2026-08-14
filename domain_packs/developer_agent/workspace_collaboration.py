from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from agent_os_contracts import (
    ActionContract,
    CollaborationDisposition,
    ResourceScope,
    WorkLease,
    WorkspaceEvent,
    WorkspaceEventBatch,
    WorkspaceEventImpact,
    WorkspaceWriteDecision,
)

from agent_os_core.capability import ExecutionLease


class WorkspaceFenceUnavailable(RuntimeError):
    """The coordination fence could not be read to authorize a write."""


class WorkspaceEventSequenceConflict(RuntimeError):
    """An append attempted to replace or skip an authoritative event sequence."""


class WorkspaceCommitFencePort(Protocol):
    """Coordination-only store: lease, event, cursor, decision.

    Holds no external-effect truth (no PREPARED/COMMITTED/UNKNOWN) and never
    dispatches. External-effect reservation/outcome/UNKNOWN belong to the
    ADR-0059 `DurableActionOutcomeRepository + CapabilityBroker` only.
    """

    def install_lease(self, lease: WorkLease) -> None: ...

    def append_event(self, event: WorkspaceEvent) -> None: ...

    def read_coordination(
        self, workspace_id: str
    ) -> WorkspaceCoordinationSnapshot: ...


@dataclass(frozen=True)
class WorkspaceCoordinationSnapshot:
    """An atomic, same-transaction read of lease + complete event batch."""

    lease: WorkLease | None
    batch: WorkspaceEventBatch


def _file_scope_from_action(action: ActionContract) -> tuple[ResourceScope, ...]:
    import json as _json

    try:
        args = _json.loads(action.arguments_json)
    except Exception:
        return ()
    if not isinstance(args, dict):
        return ()
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return ()
    return (ResourceScope(resource_uri=f"file:///ws/{path}"),)


def _batch_digest(
    workspace_id: str, after_cursor: int, through_cursor: int, events: tuple[WorkspaceEvent, ...]
) -> str:
    payload = {
        "workspace_id": workspace_id,
        "after_cursor": after_cursor,
        "through_cursor": through_cursor,
        "events": [event.model_dump(mode="json") for event in events],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_batch(
    workspace_id: str,
    after_cursor: int,
    events: tuple[WorkspaceEvent, ...],
    *,
    source_id: str,
    read_at: datetime,
) -> WorkspaceEventBatch:
    """Build a provenance-bound batch and validate contiguity.

    The batch is `complete=True` only when the event sequences are exactly
    contiguous from `after_cursor + 1` through the high-water mark. Any gap,
    duplicate, or out-of-order sequence yields `complete=False`, which the
    preflight must treat as fail-closed.
    """
    sequences = tuple(event.sequence for event in events)
    through = max(sequences, default=after_cursor)
    expected = tuple(range(after_cursor + 1, through + 1))
    contiguous = sequences == expected
    return WorkspaceEventBatch(
        workspace_id=workspace_id,
        after_cursor=after_cursor,
        through_cursor=through,
        events=events,
        source_id=source_id,
        provenance_ref=_batch_digest(workspace_id, after_cursor, through, events),
        read_at=read_at,
        complete=contiguous,
    )


class WorkspaceCollaborationPreflight:
    """Concrete `CollaborationPreflightPort` over a coordination fence.

    Reads the current lease and complete event batch from the fence using only
    `action` and `claim`; never trusts caller-supplied lease/event data. A
    non-CONTINUE decision blocks dispatch before any reservation. Any
    incomplete batch, unresolvable scope, or identity mismatch fails closed.
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
        try:
            snapshot = self._fence.read_coordination(action.workspace_id)
        except Exception as exc:
            # A coordination-store failure cannot be distinguished from a
            # missing authoritative snapshot; fail closed rather than continue.
            return self._decision(
                action,
                None,
                CollaborationDisposition.CANCEL,
                now,
                f"coordination fence unavailable: {type(exc).__name__}",
            )
        lease = snapshot.lease
        if lease is None:
            return self._decision(action, lease, CollaborationDisposition.CANCEL, now, "no coordination lease")

        identity_mismatch = (
            claim.run_id != lease.run_id
            or action.run_id != lease.run_id
            or action.task_id != lease.task_id
            or action.tenant_id != lease.tenant_id
            or action.workspace_id != lease.workspace_id
            or action.principal_id != lease.holder_id
        )
        # Note on `claim.owner` (P2 debt): `ExecutionLease.owner` is the
        # physical worker identity (e.g. `worker:<uuid>` issued per dispatch by
        # RunCoordinator); `WorkLease.holder_id` is the coordination principal.
        # These are intentionally distinct authority axes: the work lease binds
        # the principal (action.principal_id) to the resource scopes, while the
        # execution lease owner proves current physical custody. They are
        # reconciled through the shared `run_id` on every dispatch, not by
        # equating owner with holder. Revisit before multi-principal
        # collaboration, where a holder→worker mapping may need to be typed.
        if identity_mismatch:
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "action/claim identity does not bind the work lease"
            )
        if lease.expires_at <= now:
            return self._decision(action, lease, CollaborationDisposition.CANCEL, now, "work lease expired")

        write_scopes = self._scope_resolver(action)
        if not write_scopes:
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "no resolvable write scope"
            )
        if not all(
            any(allowed.covers(scope) for allowed in lease.scopes)
            for scope in write_scopes
        ):
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "write scope outside lease"
            )

        batch = snapshot.batch
        if not batch.complete:
            return self._decision(
                action, lease, CollaborationDisposition.CANCEL, now, "incomplete event batch"
            )

        relevant: list[str] = []
        disposition = CollaborationDisposition.CONTINUE
        for event in batch.events:
            if not any(
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
            elif disposition not in {
                CollaborationDisposition.CONFLICT,
                CollaborationDisposition.CANCEL,
            }:
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
    """In-memory coordination fence. Lease/event/cursor only, append-only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, WorkLease] = {}
        self._events: dict[str, list[WorkspaceEvent]] = {}

    def install_lease(self, lease: WorkLease) -> None:
        with self._lock:
            self._leases[lease.workspace_id] = lease

    def append_event(self, event: WorkspaceEvent) -> None:
        with self._lock:
            existing = self._events.setdefault(event.workspace_id, [])
            sequences = {existing_event.sequence for existing_event in existing}
            if event.sequence in sequences:
                raise WorkspaceEventSequenceConflict(
                    f"event sequence {event.sequence} already appended"
                )
            existing.append(event)

    def read_coordination(self, workspace_id: str) -> WorkspaceCoordinationSnapshot:
        with self._lock:
            lease = self._leases.get(workspace_id)
            after = lease.event_cursor if lease is not None else 0
            events = tuple(
                event
                for event in self._events.get(workspace_id, ())
                if event.sequence > after
            )
            batch = build_batch(
                workspace_id,
                after,
                events,
                source_id="memory",
                read_at=datetime.now(timezone.utc),
            )
            return WorkspaceCoordinationSnapshot(lease=lease, batch=batch)


class SQLiteWorkspaceCommitFence:
    """Single-host SQLite coordination fence with POSIX flock linearization.

    Append-only events (no INSERT OR REPLACE), atomic lease+event snapshot in a
    single consistency transaction, and a POSIX advisory lock serializing
    cross-process appends and reads.
    """

    def __init__(self, database: str | Path) -> None:
        self._db_path = str(database)
        self._lock_path = self._db_path + ".lock"
        self._thread_lock = threading.Lock()
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

    def _flock(self):
        return _FileLock(self._lock_path)

    def install_lease(self, lease: WorkLease) -> None:
        with self._thread_lock, self._flock(), self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workspace_leases(workspace_id, lease_json) "
                "VALUES (?, ?)",
                (lease.workspace_id, lease.model_dump_json()),
            )

    def append_event(self, event: WorkspaceEvent) -> None:
        with self._thread_lock, self._flock(), self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM workspace_events WHERE workspace_id = ? AND sequence = ?",
                (event.workspace_id, event.sequence),
            ).fetchone()
            if row is not None:
                raise WorkspaceEventSequenceConflict(
                    f"event sequence {event.sequence} already appended"
                )
            conn.execute(
                "INSERT INTO workspace_events(workspace_id, sequence, event_json) "
                "VALUES (?, ?, ?)",
                (event.workspace_id, event.sequence, event.model_dump_json()),
            )

    def read_coordination(self, workspace_id: str) -> WorkspaceCoordinationSnapshot:
        try:
            with self._thread_lock, self._flock(), self._connect() as conn:
                lease_row = conn.execute(
                    "SELECT lease_json FROM workspace_leases WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
                lease = (
                    WorkLease.model_validate_json(lease_row[0])
                    if lease_row is not None
                    else None
                )
                after = lease.event_cursor if lease is not None else 0
                rows = conn.execute(
                    "SELECT event_json FROM workspace_events WHERE workspace_id = ? AND sequence > ? "
                    "ORDER BY sequence",
                    (workspace_id, after),
                ).fetchall()
                events = tuple(WorkspaceEvent.model_validate_json(row[0]) for row in rows)
                batch = build_batch(
                    workspace_id,
                    after,
                    events,
                    source_id=self._db_path,
                    read_at=datetime.now(timezone.utc),
                )
                return WorkspaceCoordinationSnapshot(lease=lease, batch=batch)
        except Exception as exc:
            raise WorkspaceFenceUnavailable(
                f"coordination fence read failed for {workspace_id!r}: "
                f"{type(exc).__name__}"
            ) from exc


class _FileLock:
    """POSIX advisory lock over a sidecar lock file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._fd = None

    def __enter__(self) -> _FileLock:
        fd = open(self._path, "a+")
        self._fd = fd
        fcntl.flock(fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        fd = self._fd
        if fd is not None:
            self._fd = None
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()


__all__ = [
    "SQLiteWorkspaceCommitFence",
    "WorkspaceCollaborationPreflight",
    "WorkspaceCommitFence",
    "WorkspaceCommitFencePort",
    "WorkspaceCoordinationSnapshot",
    "WorkspaceEventSequenceConflict",
    "WorkspaceFenceUnavailable",
    "build_batch",
]
