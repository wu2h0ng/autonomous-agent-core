from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Protocol

from agent_os_contracts import (
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
    CorrectionEpochVector,
    candidate_evaluation_receipt_digest,
    content_digest,
)

from .errors import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateScopeMismatch,
)


BOUND_PAYLOAD_SCHEMA = "ADM-P2-BOUND-PAYLOAD-V1"
EVALUATION_CONTRACT_SCHEMA = "ADM-P2-EVALUATION-CONTRACT-V1"
EVALUATION_IDEMPOTENCY_SCHEMA = "ADM-P2-IDEMPOTENCY-V1"


def candidate_evaluation_payload_digest(
    draft: CandidateEvaluationDraft,
    evaluation_contract_digest: str,
    recorded_by: str,
) -> str:
    return content_digest(
        {
            "schema": BOUND_PAYLOAD_SCHEMA,
            "draft": draft,
            "evaluation_contract_digest": evaluation_contract_digest,
            "recorded_by": recorded_by,
        }
    )


def candidate_evaluation_idempotency_key(
    draft: CandidateEvaluationDraft,
    evaluation_contract_digest: str,
    recorded_by: str,
) -> str:
    return content_digest(
        {
            "schema": EVALUATION_IDEMPOTENCY_SCHEMA,
            "tenant_id": draft.tenant_id,
            "workspace_id": draft.workspace_id,
            "candidate_digest": draft.candidate_digest,
            "evaluation_task_id": draft.evaluation_task_id,
            "evaluation_run_id": draft.evaluation_run_id,
            "evaluator_identity_digest": content_digest(draft.evaluator),
            "evaluation_contract_schema": EVALUATION_CONTRACT_SCHEMA,
            "evaluation_contract_digest": evaluation_contract_digest,
            "evidence_bundle_digest": draft.evidence_bundle_digest,
            "parent_evaluation_digest": draft.parent_evaluation_digest,
            "recorded_by": recorded_by,
            "contract_schema_version": draft.schema_version,
        }
    )


@dataclass(frozen=True, slots=True)
class CandidateEvaluationRecordRequest:
    evaluation_id: str
    tenant_id: str
    workspace_id: str
    candidate_digest: str
    idempotency_key: str
    payload_digest: str
    recorded_by: str
    recorded_at: datetime
    observed_correction_epochs: CorrectionEpochVector
    evaluation_contract_digest: str
    draft: CandidateEvaluationDraft


class CandidateEvaluationStore(Protocol):
    def get_by_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        key: str,
    ) -> CandidateEvaluationReceipt | None: ...

    def latest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> CandidateEvaluationReceipt | None: ...

    def append(
        self,
        request: CandidateEvaluationRecordRequest,
        *,
        expected_parent_digest: str | None,
    ) -> CandidateEvaluationReceipt: ...

    def list_for_candidate(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]: ...


class SQLiteCandidateEvaluationStore:
    """Append-only external evaluation receipt ledger."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_evaluations (
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              candidate_digest TEXT NOT NULL,
              evaluation_version INTEGER NOT NULL,
              evaluation_digest TEXT NOT NULL UNIQUE,
              parent_evaluation_digest TEXT,
              idempotency_key TEXT NOT NULL,
              payload_digest TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              PRIMARY KEY (
                tenant_id, workspace_id, candidate_digest, evaluation_version
              ),
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
    ) -> CandidateEvaluationReceipt | None:
        with self._lock:
            row = self._db.execute(
                "SELECT receipt_json FROM candidate_evaluations "
                "WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?",
                (tenant_id, workspace_id, key),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def latest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> CandidateEvaluationReceipt | None:
        with self._lock:
            row = self._db.execute(
                "SELECT receipt_json FROM candidate_evaluations "
                "WHERE tenant_id = ? AND workspace_id = ? AND candidate_digest = ? "
                "ORDER BY evaluation_version DESC LIMIT 1",
                (tenant_id, workspace_id, candidate_digest),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def append(
        self,
        request: CandidateEvaluationRecordRequest,
        *,
        expected_parent_digest: str | None,
    ) -> CandidateEvaluationReceipt:
        self._validate_request(request)
        if request.draft.parent_evaluation_digest != expected_parent_digest:
            raise CandidateConcurrentWrite(
                "evaluation request parent does not match expected parent"
            )
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing_row = self._db.execute(
                    "SELECT receipt_json FROM candidate_evaluations "
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
                            "same evaluation key has different payload"
                        )
                    self._db.rollback()
                    return existing

                latest_row = self._db.execute(
                    "SELECT evaluation_version, evaluation_digest "
                    "FROM candidate_evaluations WHERE tenant_id = ? "
                    "AND workspace_id = ? AND candidate_digest = ? "
                    "ORDER BY evaluation_version DESC LIMIT 1",
                    (
                        request.tenant_id,
                        request.workspace_id,
                        request.candidate_digest,
                    ),
                ).fetchone()
                actual_parent = (
                    str(latest_row["evaluation_digest"])
                    if latest_row is not None
                    else None
                )
                if actual_parent != expected_parent_digest:
                    raise CandidateConcurrentWrite(
                        "evaluation parent changed before append"
                    )
                version = (
                    int(latest_row["evaluation_version"]) + 1
                    if latest_row is not None
                    else 1
                )
                payload = self._final_payload(request, version)
                receipt = CandidateEvaluationReceipt.model_validate(
                    {
                        **payload,
                        "evaluation_digest": candidate_evaluation_receipt_digest(
                            payload
                        ),
                    }
                )
                self._db.execute(
                    "INSERT INTO candidate_evaluations "
                    "(tenant_id, workspace_id, candidate_digest, "
                    "evaluation_version, evaluation_digest, "
                    "parent_evaluation_digest, idempotency_key, payload_digest, "
                    "receipt_json, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request.tenant_id,
                        request.workspace_id,
                        request.candidate_digest,
                        receipt.evaluation_version,
                        receipt.evaluation_digest,
                        expected_parent_digest,
                        request.idempotency_key,
                        request.payload_digest,
                        receipt.model_dump_json(),
                        request.recorded_at.isoformat(),
                    ),
                )
                self._db.commit()
                return receipt
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
                            "same evaluation key has different payload"
                        ) from exc
                    return existing
                raise CandidateConcurrentWrite(
                    "evaluation append lost a concurrent write"
                ) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def list_for_candidate(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT receipt_json FROM candidate_evaluations "
                "WHERE tenant_id = ? AND workspace_id = ? AND candidate_digest = ? "
                "ORDER BY evaluation_version",
                (tenant_id, workspace_id, candidate_digest),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    @staticmethod
    def _decode(row: sqlite3.Row) -> CandidateEvaluationReceipt:
        return CandidateEvaluationReceipt.model_validate_json(str(row["receipt_json"]))

    @staticmethod
    def _validate_request(request: CandidateEvaluationRecordRequest) -> None:
        draft = request.draft
        if (
            request.tenant_id != draft.tenant_id
            or request.workspace_id != draft.workspace_id
            or request.candidate_digest != draft.candidate_digest
        ):
            raise CandidateScopeMismatch("evaluation record request scope mismatch")
        expected_payload = candidate_evaluation_payload_digest(
            draft,
            request.evaluation_contract_digest,
            request.recorded_by,
        )
        if request.payload_digest != expected_payload:
            raise CandidateIdempotencyConflict(
                "evaluation record request payload digest mismatch"
            )
        expected_key = candidate_evaluation_idempotency_key(
            draft,
            request.evaluation_contract_digest,
            request.recorded_by,
        )
        if request.idempotency_key != expected_key:
            raise CandidateIdempotencyConflict(
                "evaluation record request idempotency key mismatch"
            )

    @staticmethod
    def _final_payload(
        request: CandidateEvaluationRecordRequest,
        version: int,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "evaluation_id": request.evaluation_id,
            "evaluation_version": version,
            "payload_digest": request.payload_digest,
            "idempotency_key": request.idempotency_key,
            "recorded_by": request.recorded_by,
            "recorded_at": request.recorded_at,
            "observed_correction_epochs": request.observed_correction_epochs,
            "evaluation_contract_digest": request.evaluation_contract_digest,
            "draft": request.draft,
        }
