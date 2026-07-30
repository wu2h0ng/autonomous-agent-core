from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .common import ContractModel, NonEmptyStr, UtcDateTime


class ProcedureCandidate(ContractModel):
    """Versioned workflow/procedure change proposal — sealed only, same-run consumption forbidden."""

    candidate_id: str = ""
    task_id: str
    generator_id: NonEmptyStr
    generator_version: NonEmptyStr
    proposal_type: Literal["WORKFLOW", "PROCEDURE", "POLICY", "CAPABILITY"] = "PROCEDURE"
    payload_digest: NonEmptyStr
    source_route_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    status: Literal["SEALED", "REJECTED"] = "SEALED"
    created_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.candidate_id:
            object.__setattr__(self, "candidate_id", f"procedure-candidate-{uuid4()}")


class OutcomeAttributionCandidate(ContractModel):
    """Evidence-bound hypothesis about which state/action/change contributed to outcome."""

    candidate_id: str = ""
    task_id: str
    run_id: str
    outcome_ref: NonEmptyStr
    attributed_action_ids: tuple[str, ...] = ()
    attributed_state_refs: tuple[str, ...] = ()
    confidence: float
    is_identifiable: bool = True
    evidence_refs: tuple[str, ...] = ()
    created_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.candidate_id:
            object.__setattr__(
                self, "candidate_id", f"attribution-candidate-{uuid4()}"
            )


class PromotionDecision(ContractModel):
    """External policy decision over exact candidate and receipts — no self-approval."""

    decision_id: str = ""
    candidate_ref: NonEmptyStr
    evaluator_id: NonEmptyStr
    disposition: Literal["PROMOTE", "PARK", "REJECT"]
    reason: NonEmptyStr
    receipt_digests: tuple[str, ...] = ()
    authority_id: NonEmptyStr
    grant_scope: tuple[str, ...] = ()
    created_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.decision_id:
            object.__setattr__(
                self, "decision_id", f"promotion-decision-{uuid4()}"
            )


class RollbackReceipt(ContractModel):
    """Exact canary rollback action and resulting state/effect reconciliation."""

    receipt_id: str = ""
    task_id: str
    run_id: str
    promotion_decision_id: NonEmptyStr
    candidate_ref: NonEmptyStr
    status: Literal["ROLLED_BACK", "FAILED_ROLLBACK", "UNRESOLVED_EFFECTS"] = "ROLLED_BACK"
    unresolved_effect_refs: tuple[str, ...] = ()
    reconciled_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.receipt_id:
            object.__setattr__(
                self, "receipt_id", f"rollback-receipt-{uuid4()}"
            )
