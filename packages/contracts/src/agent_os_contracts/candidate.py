from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest
from .workflow import WorkflowGraph


def procedure_candidate_digest(payload: Mapping[str, Any]) -> str:
    if "candidate_digest" in payload:
        raise ValueError(
            "candidate_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class ProcedureCandidate(ContractModel):
    """Versioned workflow/procedure change proposal.

    Named consumer: candidate lifecycle.
    Fail-closed: sealed only (``sealed_by``/``sealed_at`` and a self-consistent
    ``candidate_digest`` are required); same-run consumption is forbidden
    (``same_run_consumption`` pinned to ``"FORBIDDEN"``; the consumer compares
    ``generating_task_id``/``generating_run_id``).
    """

    candidate_id: NonEmptyStr
    candidate_version: int = Field(ge=1)
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    base_workflow_digest: Sha256Digest | None = None
    proposed_workflow: WorkflowGraph
    proposed_workflow_digest: Sha256Digest
    rationale: NonEmptyStr
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    generating_task_id: NonEmptyStr
    generating_run_id: NonEmptyStr
    sealed_by: NonEmptyStr
    sealed_at: UtcDateTime
    same_run_consumption: Literal["FORBIDDEN"] = "FORBIDDEN"
    candidate_digest: Sha256Digest

    @field_validator("evidence_refs", mode="after")
    @classmethod
    def _normalize_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_candidate(self) -> ProcedureCandidate:
        if (
            self.proposed_workflow.tenant_id != self.tenant_id
            or self.proposed_workflow.workspace_id != self.workspace_id
        ):
            raise ValueError("procedure candidate workflow scope mismatch")
        if self.proposed_workflow_digest != self.proposed_workflow.canonical_digest():
            raise ValueError("proposed workflow digest mismatch")
        payload = self.model_dump(mode="json", exclude={"candidate_digest"})
        if self.candidate_digest != procedure_candidate_digest(payload):
            raise ValueError(
                "candidate_digest does not match canonical candidate payload"
            )
        return self


class RollbackEffectReconciliation(ContractModel):
    effect_ref: NonEmptyStr
    status: Literal["RESOLVED", "UNRESOLVED"]
    detail: NonEmptyStr


def rollback_receipt_digest(payload: Mapping[str, Any]) -> str:
    if "rollback_digest" in payload:
        raise ValueError("rollback_digest must be excluded from its own digest payload")
    return content_digest(payload)


class RollbackReceipt(ContractModel):
    """Exact canary rollback action with resulting state/effect
    reconciliation.

    Named consumer: operator / promotion ledger.
    Fail-closed: any ``UNRESOLVED`` effect keeps the candidate disabled
    (``resulting_candidate_state`` must be ``"DISABLED"``).
    """

    rollback_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    candidate_digest: Sha256Digest
    promotion_digest: Sha256Digest
    action_ref: NonEmptyStr
    action_digest: Sha256Digest
    effects: tuple[RollbackEffectReconciliation, ...] = Field(min_length=1)
    resulting_candidate_state: Literal["DISABLED", "ACTIVE"]
    executed_by: NonEmptyStr
    executed_at: UtcDateTime
    rollback_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_receipt(self) -> RollbackReceipt:
        effect_refs = tuple(effect.effect_ref for effect in self.effects)
        if len(effect_refs) != len(set(effect_refs)):
            raise ValueError("rollback effect refs must be unique")
        if (
            any(effect.status == "UNRESOLVED" for effect in self.effects)
            and self.resulting_candidate_state != "DISABLED"
        ):
            raise ValueError("unresolved rollback effects keep candidate disabled")
        payload = self.model_dump(mode="json", exclude={"rollback_digest"})
        if self.rollback_digest != rollback_receipt_digest(payload):
            raise ValueError("rollback_digest does not match canonical receipt payload")
        return self
