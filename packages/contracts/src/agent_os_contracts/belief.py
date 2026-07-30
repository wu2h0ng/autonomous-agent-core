from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evidence import Sha256Digest


class BeliefStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONTESTED = "CONTESTED"
    INVALIDATED = "INVALIDATED"


class BeliefRecord(ContractModel):
    """Revisable proposition with confidence, provenance, conflict and
    validity interval.

    Named consumer: state assembler / user inspection.
    Fail-closed: conflict is preserved (``conflicting_belief_ids`` is carried,
    never auto-resolved; ``CONTESTED`` requires it); a belief can never be
    converted to authority (``authority`` is pinned to ``"NONE"``).
    """

    belief_id: NonEmptyStr
    belief_version: int = Field(ge=1)
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    proposition: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    status: BeliefStatus = BeliefStatus.ACTIVE
    conflicting_belief_ids: tuple[NonEmptyStr, ...] = ()
    provenance_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None
    recorded_at: UtcDateTime
    authority: Literal["NONE"] = "NONE"

    @field_validator("conflicting_belief_ids", "provenance_refs", mode="after")
    @classmethod
    def _normalize_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_belief(self) -> BeliefRecord:
        if self.belief_id in self.conflicting_belief_ids:
            raise ValueError("belief cannot conflict with itself")
        if self.status is BeliefStatus.CONTESTED and not self.conflicting_belief_ids:
            raise ValueError("CONTESTED belief requires preserved conflicting ids")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)


class BeliefPatchOperation(ContractModel):
    operation_id: NonEmptyStr
    operation: Literal["ADD", "REVISE", "INVALIDATE"]
    belief: BeliefRecord | None = None
    target_belief_id: NonEmptyStr | None = None
    target_belief_version: int | None = Field(default=None, ge=1)
    reason: NonEmptyStr | None = None
    grounding_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @field_validator("grounding_refs", mode="after")
    @classmethod
    def _normalize_grounding(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_operation(self) -> BeliefPatchOperation:
        if self.operation == "ADD":
            if self.belief is None:
                raise ValueError("ADD requires a belief")
            if self.belief.belief_version != 1:
                raise ValueError("ADD belief must start at version 1")
            if (
                self.target_belief_id is not None
                or self.target_belief_version is not None
                or self.reason is not None
            ):
                raise ValueError("ADD forbids target and reason fields")
        elif self.operation == "REVISE":
            if (
                self.belief is None
                or self.target_belief_id is None
                or self.target_belief_version is None
                or self.reason is None
            ):
                raise ValueError("REVISE requires belief, target and reason")
            if self.belief.belief_id != self.target_belief_id:
                raise ValueError("REVISE belief must keep the target belief id")
            if self.belief.belief_version != self.target_belief_version + 1:
                raise ValueError("REVISE belief version must follow the target version")
        else:
            if self.belief is not None:
                raise ValueError("INVALIDATE forbids a belief payload")
            if (
                self.target_belief_id is None
                or self.target_belief_version is None
                or self.reason is None
            ):
                raise ValueError("INVALIDATE requires target and reason")
        return self


class BeliefPatch(ContractModel):
    """Typed add/revise/invalidate proposal against a base belief snapshot.

    Named consumer: independent state updater.
    Contract-enforced: every operation requires ``grounding_refs``
    (ungrounded mutation is rejected) and operation ids are unique.
    Consumer-enforced: base-version drift is rejected by the state updater
    against the pinned ``base_snapshot_digest``/``base_snapshot_version``,
    not by this contract.
    """

    patch_id: NonEmptyStr
    base_snapshot_digest: Sha256Digest
    base_snapshot_version: int = Field(ge=1)
    operations: tuple[BeliefPatchOperation, ...] = Field(min_length=1)
    proposed_by: NonEmptyStr
    proposed_at: UtcDateTime

    @model_validator(mode="after")
    def _require_unique_operations(self) -> BeliefPatch:
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("belief patch operation ids must be unique")
        return self

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)
