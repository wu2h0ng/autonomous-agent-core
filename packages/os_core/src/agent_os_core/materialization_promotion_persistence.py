from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from agent_os_contracts import (
    CandidateEvaluationReceipt,
    CandidatePromotionCommand,
    CandidatePromotionDecision,
    CandidatePromotionDisposition,
    CandidatePromotionResult,
    CandidateWriteChannel,
    CorrectionEpochVector,
    DomainCandidate,
    DomainPriorArtifact,
    MaterializationOutcome,
    candidate_promotion_decision_digest,
    content_digest,
    domain_prior_artifact_digest,
)

from .errors import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateScopeMismatch,
)
from .materialization_ledger import SQLiteAdaptationLedger
from .materialization_promotion_policy import (
    ProductPromotionPolicy,
    PromotionPolicyRegistry,
    PromotionReduction,
)


RECEIPT_CHAIN_SCHEMA = "ADM-P3-RECEIPT-CHAIN-V1"
BOUND_PAYLOAD_SCHEMA = "ADM-P3-BOUND-PAYLOAD-V1"
IDEMPOTENCY_SCHEMA = "ADM-P3-IDEMPOTENCY-V1"
PRIOR_BOUND_PAYLOAD_SCHEMA = "ADM-P3-PRIOR-BOUND-PAYLOAD-V1"


def candidate_receipt_chain_digest(
    candidate_digest: str,
    receipts: tuple[CandidateEvaluationReceipt, ...],
) -> str:
    return content_digest(
        {
            "schema": RECEIPT_CHAIN_SCHEMA,
            "candidate_digest": candidate_digest,
            "receipts": receipts,
        }
    )


def _reduction_payload(reduction: PromotionReduction) -> dict[str, object]:
    return {
        "disposition": reduction.disposition.value,
        "reason_codes": reduction.reason_codes,
    }


def candidate_promotion_payload_digest(
    command: CandidatePromotionCommand,
    candidate: DomainCandidate,
    receipt_chain_digest: str,
    policy_version: str,
    policy_digest: str,
    reduction: PromotionReduction,
    decided_by: str,
) -> str:
    return content_digest(
        {
            "schema": BOUND_PAYLOAD_SCHEMA,
            "command": command,
            "candidate": candidate,
            "receipt_chain_digest": receipt_chain_digest,
            "policy_version": policy_version,
            "policy_digest": policy_digest,
            "reduction": _reduction_payload(reduction),
            "decided_by": decided_by,
        }
    )


def candidate_promotion_idempotency_key(
    command: CandidatePromotionCommand,
    policy_version: str,
    policy_digest: str,
    decided_by: str,
) -> str:
    return content_digest(
        {
            "schema": IDEMPOTENCY_SCHEMA,
            "tenant_id": command.tenant_id,
            "workspace_id": command.workspace_id,
            "candidate_digest": command.candidate_digest,
            "promotion_task_id": command.promotion_task_id,
            "promotion_run_id": command.promotion_run_id,
            "evaluation_head": command.expected_evaluation_head_digest,
            "parent_promotion": command.expected_parent_promotion_digest,
            "policy_version": policy_version,
            "policy_digest": policy_digest,
            "decided_by": decided_by,
            "contract_schema_version": command.schema_version,
        }
    )


@dataclass(frozen=True, slots=True)
class CandidatePromotionRecordRequest:
    command: CandidatePromotionCommand
    candidate: DomainCandidate
    receipt_chain_digest: str
    policy_version: str
    policy_digest: str
    reduction: PromotionReduction
    payload_digest: str
    idempotency_key: str
    decided_by: str
    decided_at: datetime
    observed_correction_epochs: CorrectionEpochVector


class CandidatePromotionStore(Protocol):
    def append(
        self,
        request: CandidatePromotionRecordRequest,
    ) -> CandidatePromotionResult: ...

    def list_decisions(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]: ...

    def list_priors(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]: ...


class SQLiteCandidatePromotionStore:
    """Append-only promotion and inert-prior ledger over the shared ADM tables."""

    def __init__(
        self,
        ledger: SQLiteAdaptationLedger | None = None,
        policies: PromotionPolicyRegistry | None = None,
        *,
        path: str | Path = ":memory:",
    ) -> None:
        if policies is None:
            raise ValueError("promotion policy registry is required")
        self._owns_ledger = ledger is None
        self._ledger = ledger or SQLiteAdaptationLedger(path)
        self.path = self._ledger.path
        self._lock = self._ledger.lock
        self._db = self._ledger.connection
        self._policies = policies
        with self._lock:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_promotions (
                  tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  candidate_digest TEXT NOT NULL,
                  promotion_version INTEGER NOT NULL,
                  promotion_digest TEXT NOT NULL UNIQUE,
                  parent_promotion_digest TEXT,
                  evaluation_head_digest TEXT,
                  idempotency_key TEXT NOT NULL,
                  payload_digest TEXT NOT NULL,
                  decision_json TEXT NOT NULL,
                  decided_at TEXT NOT NULL,
                  PRIMARY KEY (
                    tenant_id, workspace_id, candidate_digest, promotion_version
                  ),
                  UNIQUE (tenant_id, workspace_id, idempotency_key)
                )
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_prior_artifacts (
                  tenant_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  candidate_digest TEXT NOT NULL,
                  prior_version INTEGER NOT NULL,
                  prior_digest TEXT NOT NULL UNIQUE,
                  parent_prior_digest TEXT,
                  promotion_digest TEXT NOT NULL UNIQUE,
                  payload_digest TEXT NOT NULL,
                  prior_json TEXT NOT NULL,
                  published_at TEXT NOT NULL,
                  PRIMARY KEY (
                    tenant_id, workspace_id, candidate_digest, prior_version
                  )
                )
                """
            )
            self._db.commit()

    @property
    def ledger(self) -> SQLiteAdaptationLedger:
        return self._ledger

    def close(self) -> None:
        if self._owns_ledger:
            self._ledger.close()

    def append(
        self,
        request: CandidatePromotionRecordRequest,
    ) -> CandidatePromotionResult:
        self._validate_request(request)
        command = request.command
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing_row = self._db.execute(
                    "SELECT decision_json FROM candidate_promotions "
                    "WHERE tenant_id = ? AND workspace_id = ? "
                    "AND idempotency_key = ?",
                    (
                        command.tenant_id,
                        command.workspace_id,
                        request.idempotency_key,
                    ),
                ).fetchone()
                if existing_row is not None:
                    existing = self._decode_decision(existing_row)
                    if existing.payload_digest != request.payload_digest:
                        raise CandidateIdempotencyConflict(
                            "same promotion key has different payload"
                        )
                    prior = self._prior_for_promotion(existing.promotion_digest)
                    result = CandidatePromotionResult(
                        decision=existing,
                        prior=prior,
                    )
                    self._db.rollback()
                    return result

                receipts = self._load_and_validate_receipts(request)
                actual_chain_digest = candidate_receipt_chain_digest(
                    command.candidate_digest,
                    receipts,
                )
                if actual_chain_digest != request.receipt_chain_digest:
                    raise CandidateConcurrentWrite(
                        "evaluation receipt chain changed before promotion append"
                    )
                actual_head = receipts[-1].evaluation_digest if receipts else None
                if command.expected_evaluation_head_digest != actual_head:
                    raise CandidateConcurrentWrite(
                        "evaluation head changed before promotion append"
                    )

                latest_row = self._db.execute(
                    "SELECT promotion_version, promotion_digest, "
                    "evaluation_head_digest FROM candidate_promotions "
                    "WHERE tenant_id = ? AND workspace_id = ? "
                    "AND candidate_digest = ? "
                    "ORDER BY promotion_version DESC LIMIT 1",
                    (
                        command.tenant_id,
                        command.workspace_id,
                        command.candidate_digest,
                    ),
                ).fetchone()
                actual_parent = (
                    str(latest_row["promotion_digest"])
                    if latest_row is not None
                    else None
                )
                if command.expected_parent_promotion_digest != actual_parent:
                    raise CandidateConcurrentWrite(
                        "promotion parent changed before append"
                    )
                if latest_row is not None:
                    latest_head = latest_row["evaluation_head_digest"]
                    if latest_head == actual_head:
                        raise CandidateConcurrentWrite(
                            "a new promotion decision requires a new receipt head"
                        )

                policy = self._resolve_policy(request)
                recomputed = policy.reduce(request.candidate, receipts)
                if recomputed != request.reduction:
                    raise CandidateIdempotencyConflict(
                        "promotion reduction does not match registered policy"
                    )
                if (
                    recomputed.disposition is CandidatePromotionDisposition.PROMOTE
                    and not receipts
                ):
                    raise CandidateConcurrentWrite(
                        "empty receipt chain cannot be promoted"
                    )

                promotion_version = (
                    int(latest_row["promotion_version"]) + 1
                    if latest_row is not None
                    else 1
                )
                promotion_id = (
                    f"candidate-promotion:{command.candidate_digest}:"
                    f"{promotion_version}"
                )
                prior_artifact_id = (
                    f"domain-prior:{command.candidate_digest}:{promotion_version}"
                    if recomputed.disposition is CandidatePromotionDisposition.PROMOTE
                    else None
                )
                decision_payload: dict[str, object] = {
                    "schema_version": "1.0",
                    "promotion_id": promotion_id,
                    "promotion_version": promotion_version,
                    "payload_digest": request.payload_digest,
                    "idempotency_key": request.idempotency_key,
                    "candidate_digest": command.candidate_digest,
                    "candidate_task_id": command.candidate_task_id,
                    "promotion_task_id": command.promotion_task_id,
                    "promotion_run_id": command.promotion_run_id,
                    "tenant_id": command.tenant_id,
                    "workspace_id": command.workspace_id,
                    "evaluation_head_digest": actual_head,
                    "evaluation_receipt_digests": tuple(
                        receipt.evaluation_digest for receipt in receipts
                    ),
                    "receipt_chain_digest": actual_chain_digest,
                    "disposition": recomputed.disposition,
                    "reason_codes": recomputed.reason_codes,
                    "policy_version": request.policy_version,
                    "policy_digest": request.policy_digest,
                    "decided_by": request.decided_by,
                    "decided_at": request.decided_at,
                    "observed_correction_epochs": request.observed_correction_epochs,
                    "parent_promotion_digest": actual_parent,
                    "prior_artifact_id": prior_artifact_id,
                }
                decision = CandidatePromotionDecision.model_validate(
                    {
                        **decision_payload,
                        "promotion_digest": candidate_promotion_decision_digest(
                            decision_payload
                        ),
                    }
                )
                self._insert_decision(decision)

                prior = (
                    self._build_and_insert_prior(request, decision)
                    if recomputed.disposition is CandidatePromotionDisposition.PROMOTE
                    else None
                )
                result = CandidatePromotionResult(decision=decision, prior=prior)
                self._db.commit()
                return result
            except sqlite3.IntegrityError as exc:
                if self._db.in_transaction:
                    self._db.rollback()
                existing = self._get_by_idempotency(
                    command.tenant_id,
                    command.workspace_id,
                    request.idempotency_key,
                )
                if existing is not None:
                    if existing.payload_digest != request.payload_digest:
                        raise CandidateIdempotencyConflict(
                            "same promotion key has different payload"
                        ) from exc
                    return CandidatePromotionResult(
                        decision=existing,
                        prior=self._prior_for_promotion(existing.promotion_digest),
                    )
                raise CandidateConcurrentWrite(
                    "promotion append lost a concurrent write"
                ) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def list_decisions(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT decision_json FROM candidate_promotions "
                "WHERE tenant_id = ? AND workspace_id = ? "
                "AND candidate_digest = ? ORDER BY promotion_version",
                (tenant_id, workspace_id, candidate_digest),
            ).fetchall()
        return tuple(self._decode_decision(row) for row in rows)

    def list_priors(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT prior_json FROM domain_prior_artifacts "
                "WHERE tenant_id = ? AND workspace_id = ? "
                "AND candidate_digest = ? ORDER BY prior_version",
                (tenant_id, workspace_id, candidate_digest),
            ).fetchall()
        return tuple(self._decode_prior(row) for row in rows)

    def _load_and_validate_receipts(
        self,
        request: CandidatePromotionRecordRequest,
    ) -> tuple[CandidateEvaluationReceipt, ...]:
        command = request.command
        rows = self._db.execute(
            "SELECT evaluation_version, evaluation_digest, "
            "parent_evaluation_digest, receipt_json "
            "FROM candidate_evaluations WHERE tenant_id = ? "
            "AND workspace_id = ? AND candidate_digest = ? "
            "ORDER BY evaluation_version",
            (
                command.tenant_id,
                command.workspace_id,
                command.candidate_digest,
            ),
        ).fetchall()
        receipts: list[CandidateEvaluationReceipt] = []
        parent: str | None = None
        for expected_version, row in enumerate(rows, start=1):
            try:
                receipt = CandidateEvaluationReceipt.model_validate_json(
                    str(row["receipt_json"])
                )
            except Exception as exc:
                raise CandidateConcurrentWrite(
                    "evaluation receipt chain contains invalid bytes"
                ) from exc
            if (
                int(row["evaluation_version"]) != expected_version
                or receipt.evaluation_version != expected_version
            ):
                raise CandidateConcurrentWrite(
                    "evaluation receipt chain has a version gap or reorder"
                )
            if (
                str(row["evaluation_digest"]) != receipt.evaluation_digest
                or row["parent_evaluation_digest"] != parent
                or receipt.draft.parent_evaluation_digest != parent
            ):
                raise CandidateConcurrentWrite(
                    "evaluation receipt chain has a digest or parent break"
                )
            draft = receipt.draft
            if (
                draft.candidate_digest != command.candidate_digest
                or draft.candidate_task_id != command.candidate_task_id
                or draft.tenant_id != command.tenant_id
                or draft.workspace_id != command.workspace_id
            ):
                raise CandidateConcurrentWrite(
                    "evaluation receipt chain has a scope mismatch"
                )
            if (
                draft.evaluation_task_id == command.promotion_task_id
                or draft.evaluation_run_id == command.promotion_run_id
            ):
                raise CandidateConcurrentWrite(
                    "promotion Task/Run must differ from every evaluation Task/Run"
                )
            receipts.append(receipt)
            parent = receipt.evaluation_digest
        return tuple(receipts)

    def _resolve_policy(
        self,
        request: CandidatePromotionRecordRequest,
    ) -> ProductPromotionPolicy:
        try:
            return self._policies.resolve(
                request.policy_version,
                request.policy_digest,
            )
        except KeyError as exc:
            raise CandidateIdempotencyConflict(
                "promotion policy version/digest is not registered"
            ) from exc

    def _build_and_insert_prior(
        self,
        request: CandidatePromotionRecordRequest,
        decision: CandidatePromotionDecision,
    ) -> DomainPriorArtifact:
        candidate = request.candidate
        patch = candidate.draft.representation_patch
        if patch is None or not candidate.draft.provenance:
            raise CandidateScopeMismatch(
                "promoted candidate requires an R patch and provenance"
            )
        latest_row = self._db.execute(
            "SELECT prior_version, prior_digest FROM domain_prior_artifacts "
            "WHERE tenant_id = ? AND workspace_id = ? AND candidate_digest = ? "
            "ORDER BY prior_version DESC LIMIT 1",
            (
                decision.tenant_id,
                decision.workspace_id,
                decision.candidate_digest,
            ),
        ).fetchone()
        prior_version = (
            int(latest_row["prior_version"]) + 1 if latest_row is not None else 1
        )
        parent_prior_digest = (
            str(latest_row["prior_digest"]) if latest_row is not None else None
        )
        prior_payload_digest = content_digest(
            {
                "schema": PRIOR_BOUND_PAYLOAD_SCHEMA,
                "decision": decision,
                "candidate": candidate,
                "prior_version": prior_version,
                "parent_prior_digest": parent_prior_digest,
            }
        )
        assert decision.evaluation_head_digest is not None
        prior_payload: dict[str, object] = {
            "schema_version": "1.0",
            "prior_artifact_id": decision.prior_artifact_id,
            "prior_version": prior_version,
            "payload_digest": prior_payload_digest,
            "parent_prior_digest": parent_prior_digest,
            "candidate_digest": decision.candidate_digest,
            "candidate_payload_digest": candidate.payload_digest,
            "promotion_digest": decision.promotion_digest,
            "evaluation_head_digest": decision.evaluation_head_digest,
            "evaluation_receipt_digests": decision.evaluation_receipt_digests,
            "receipt_chain_digest": decision.receipt_chain_digest,
            "tenant_id": decision.tenant_id,
            "workspace_id": decision.workspace_id,
            "representation_patch": patch,
            "provenance": candidate.draft.provenance,
            "policy_digest": decision.policy_digest,
            "published_by": decision.decided_by,
            "published_at": decision.decided_at,
            "observed_correction_epochs": decision.observed_correction_epochs,
            "state": "INERT",
            "activation_authority": "NONE",
            "uncertainty_behavior": "PRESERVE",
        }
        prior = DomainPriorArtifact.model_validate(
            {
                **prior_payload,
                "prior_digest": domain_prior_artifact_digest(prior_payload),
            }
        )
        self._db.execute(
            "INSERT INTO domain_prior_artifacts "
            "(tenant_id, workspace_id, candidate_digest, prior_version, "
            "prior_digest, parent_prior_digest, promotion_digest, payload_digest, "
            "prior_json, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                prior.tenant_id,
                prior.workspace_id,
                prior.candidate_digest,
                prior.prior_version,
                prior.prior_digest,
                prior.parent_prior_digest,
                prior.promotion_digest,
                prior.payload_digest,
                prior.model_dump_json(),
                prior.published_at.isoformat(),
            ),
        )
        return prior

    def _insert_decision(self, decision: CandidatePromotionDecision) -> None:
        self._db.execute(
            "INSERT INTO candidate_promotions "
            "(tenant_id, workspace_id, candidate_digest, promotion_version, "
            "promotion_digest, parent_promotion_digest, evaluation_head_digest, "
            "idempotency_key, payload_digest, decision_json, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.tenant_id,
                decision.workspace_id,
                decision.candidate_digest,
                decision.promotion_version,
                decision.promotion_digest,
                decision.parent_promotion_digest,
                decision.evaluation_head_digest,
                decision.idempotency_key,
                decision.payload_digest,
                decision.model_dump_json(),
                decision.decided_at.isoformat(),
            ),
        )

    def _get_by_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        key: str,
    ) -> CandidatePromotionDecision | None:
        row = self._db.execute(
            "SELECT decision_json FROM candidate_promotions "
            "WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?",
            (tenant_id, workspace_id, key),
        ).fetchone()
        return self._decode_decision(row) if row is not None else None

    def _prior_for_promotion(
        self,
        promotion_digest: str,
    ) -> DomainPriorArtifact | None:
        row = self._db.execute(
            "SELECT prior_json FROM domain_prior_artifacts WHERE promotion_digest = ?",
            (promotion_digest,),
        ).fetchone()
        return self._decode_prior(row) if row is not None else None

    @staticmethod
    def _decode_decision(row: sqlite3.Row) -> CandidatePromotionDecision:
        return CandidatePromotionDecision.model_validate_json(str(row["decision_json"]))

    @staticmethod
    def _decode_prior(row: sqlite3.Row) -> DomainPriorArtifact:
        return DomainPriorArtifact.model_validate_json(str(row["prior_json"]))

    @staticmethod
    def _validate_request(request: CandidatePromotionRecordRequest) -> None:
        command = request.command
        candidate = request.candidate
        draft = candidate.draft
        if (
            command.candidate_digest != candidate.candidate_digest
            or command.candidate_task_id != draft.task_id
            or command.tenant_id != draft.tenant_id
            or command.workspace_id != draft.workspace_id
        ):
            raise CandidateScopeMismatch("promotion record request scope mismatch")
        if (
            draft.outcome is not MaterializationOutcome.CANDIDATE
            or draft.requested_channel is not CandidateWriteChannel.R
            or draft.representation_patch is None
            or not draft.provenance
        ):
            raise CandidateScopeMismatch(
                "promotion record requires an R-channel CANDIDATE"
            )
        expected_payload = candidate_promotion_payload_digest(
            command,
            candidate,
            request.receipt_chain_digest,
            request.policy_version,
            request.policy_digest,
            request.reduction,
            request.decided_by,
        )
        if request.payload_digest != expected_payload:
            raise CandidateIdempotencyConflict(
                "promotion record request payload digest mismatch"
            )
        expected_key = candidate_promotion_idempotency_key(
            command,
            request.policy_version,
            request.policy_digest,
            request.decided_by,
        )
        if request.idempotency_key != expected_key:
            raise CandidateIdempotencyConflict(
                "promotion record request idempotency key mismatch"
            )
