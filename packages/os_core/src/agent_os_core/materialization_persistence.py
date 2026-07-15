from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Protocol

from agent_os_contracts import (
    CorrectionEpochVector,
    DomainCandidate,
    DomainCandidateDraft,
    content_digest,
    domain_candidate_digest,
)

from .errors import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateScopeMismatch,
)


@dataclass(frozen=True, slots=True)
class CandidateSealRequest:
    candidate_id: str
    tenant_id: str
    workspace_id: str
    task_id: str
    idempotency_key: str
    payload_digest: str
    sealed_by: str
    sealed_at: datetime
    observed_correction_epochs: CorrectionEpochVector
    draft: DomainCandidateDraft


class CandidateStore(Protocol):
    def get_by_digest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> DomainCandidate | None: ...

    def get_by_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        key: str,
    ) -> DomainCandidate | None: ...

    def latest(
        self,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
    ) -> DomainCandidate | None: ...

    def append(
        self,
        request: CandidateSealRequest,
        *,
        expected_parent_digest: str | None,
    ) -> DomainCandidate: ...

    def list_for_task(
        self,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
    ) -> tuple[DomainCandidate, ...]: ...


class SQLiteCandidateStore:
    """Append-only candidate ledger, separate from the Task event stream."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_candidates (
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              candidate_version INTEGER NOT NULL,
              candidate_digest TEXT NOT NULL UNIQUE,
              parent_candidate_digest TEXT,
              idempotency_key TEXT NOT NULL,
              payload_digest TEXT NOT NULL,
              candidate_json TEXT NOT NULL,
              sealed_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, workspace_id, task_id, candidate_version),
              UNIQUE (tenant_id, workspace_id, idempotency_key)
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get_by_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        key: str,
    ) -> DomainCandidate | None:
        with self._lock:
            row = self._db.execute(
                "SELECT candidate_json FROM domain_candidates "
                "WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?",
                (tenant_id, workspace_id, key),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def get_by_digest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> DomainCandidate | None:
        with self._lock:
            row = self._db.execute(
                "SELECT candidate_json FROM domain_candidates "
                "WHERE tenant_id = ? AND workspace_id = ? AND candidate_digest = ?",
                (tenant_id, workspace_id, candidate_digest),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def latest(
        self,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
    ) -> DomainCandidate | None:
        with self._lock:
            row = self._db.execute(
                "SELECT candidate_json FROM domain_candidates "
                "WHERE tenant_id = ? AND workspace_id = ? AND task_id = ? "
                "ORDER BY candidate_version DESC LIMIT 1",
                (tenant_id, workspace_id, task_id),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def append(
        self,
        request: CandidateSealRequest,
        *,
        expected_parent_digest: str | None,
    ) -> DomainCandidate:
        self._validate_request(request)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing_row = self._db.execute(
                    "SELECT candidate_json FROM domain_candidates "
                    "WHERE tenant_id = ? AND workspace_id = ? "
                    "AND idempotency_key = ?",
                    (
                        request.tenant_id,
                        request.workspace_id,
                        request.idempotency_key,
                    ),
                ).fetchone()
                if existing_row is not None:
                    existing = self._decode(existing_row)
                    if existing.payload_digest != request.payload_digest:
                        raise CandidateIdempotencyConflict(
                            "same derived key has different payload"
                        )
                    self._db.rollback()
                    return existing

                latest_row = self._db.execute(
                    "SELECT candidate_version, candidate_digest "
                    "FROM domain_candidates WHERE tenant_id = ? "
                    "AND workspace_id = ? AND task_id = ? "
                    "ORDER BY candidate_version DESC LIMIT 1",
                    (request.tenant_id, request.workspace_id, request.task_id),
                ).fetchone()
                actual_parent = (
                    str(latest_row["candidate_digest"])
                    if latest_row is not None
                    else None
                )
                if actual_parent != expected_parent_digest:
                    raise CandidateConcurrentWrite(
                        "candidate parent changed before append"
                    )
                version = (
                    int(latest_row["candidate_version"]) + 1
                    if latest_row is not None
                    else 1
                )
                payload = self._final_payload(request, version)
                candidate = DomainCandidate.model_validate(
                    {
                        **payload,
                        "candidate_digest": domain_candidate_digest(payload),
                    }
                )
                self._db.execute(
                    "INSERT INTO domain_candidates "
                    "(tenant_id, workspace_id, task_id, candidate_version, "
                    "candidate_digest, parent_candidate_digest, idempotency_key, "
                    "payload_digest, candidate_json, sealed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request.tenant_id,
                        request.workspace_id,
                        request.task_id,
                        candidate.candidate_version,
                        candidate.candidate_digest,
                        expected_parent_digest,
                        request.idempotency_key,
                        request.payload_digest,
                        candidate.model_dump_json(),
                        request.sealed_at.isoformat(),
                    ),
                )
                self._db.commit()
                return candidate
            except sqlite3.IntegrityError as exc:
                if self._db.in_transaction:
                    self._db.rollback()
                existing = self.get_by_idempotency(
                    request.tenant_id,
                    request.workspace_id,
                    request.idempotency_key,
                )
                if existing is not None:
                    if existing.payload_digest != request.payload_digest:
                        raise CandidateIdempotencyConflict(
                            "same derived key has different payload"
                        ) from exc
                    return existing
                raise CandidateConcurrentWrite(
                    "candidate append lost a concurrent write"
                ) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def list_for_task(
        self,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
    ) -> tuple[DomainCandidate, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT candidate_json FROM domain_candidates "
                "WHERE tenant_id = ? AND workspace_id = ? AND task_id = ? "
                "ORDER BY candidate_version",
                (tenant_id, workspace_id, task_id),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    @staticmethod
    def _decode(row: sqlite3.Row) -> DomainCandidate:
        return DomainCandidate.model_validate_json(str(row["candidate_json"]))

    @staticmethod
    def _validate_request(request: CandidateSealRequest) -> None:
        draft = request.draft
        if (
            request.task_id != draft.task_id
            or request.tenant_id != draft.tenant_id
            or request.workspace_id != draft.workspace_id
        ):
            raise CandidateScopeMismatch("candidate seal request scope mismatch")
        if request.payload_digest != content_digest(draft):
            raise CandidateIdempotencyConflict(
                "candidate seal request payload digest mismatch"
            )

    @staticmethod
    def _final_payload(
        request: CandidateSealRequest,
        version: int,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "candidate_id": request.candidate_id,
            "candidate_version": version,
            "payload_digest": request.payload_digest,
            "idempotency_key": request.idempotency_key,
            "sealed_by": request.sealed_by,
            "sealed_at": request.sealed_at,
            "observed_correction_epochs": request.observed_correction_epochs,
            "draft": request.draft,
        }
