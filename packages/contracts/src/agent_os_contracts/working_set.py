from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, content_digest
from .evidence import Sha256Digest


class ExternalStateCandidateRef(ContractModel):
    candidate_id: NonEmptyStr
    source_kind: Literal["SESSION", "MEMORY", "LEARNED_GRAPH", "EXTERNAL_STATE"]
    source_adapter_id: NonEmptyStr
    source_adapter_version: int = Field(ge=1)
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    authorization_scope_digest: Sha256Digest
    observed_correction_epoch: int = Field(ge=0)
    media_type: Literal["application/json"] = "application/json"
    content_digest: Sha256Digest
    epistemic_status: Literal["INFERRED"] = "INFERRED"
    validation_status: Literal["CANDIDATE"] = "CANDIDATE"


class WorkingSetRequest(ContractModel):
    request_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    authorization_scope_digest: Sha256Digest
    mandate_id: NonEmptyStr
    mandate_version: int = Field(ge=1)
    mandate_digest: Sha256Digest
    admission_receipt_id: NonEmptyStr
    admission_receipt_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    relevance_policy_digest: Sha256Digest
    selection_policy_digest: Sha256Digest


class SelectionManifest(ContractModel):
    manifest_id: NonEmptyStr
    manifest_digest: Sha256Digest
    adapter_bindings: tuple[NonEmptyStr, ...]
    candidate_digests: tuple[Sha256Digest, ...]
    selected_candidate_ids: tuple[NonEmptyStr, ...]
    selected_reasons: tuple[NonEmptyStr, ...]
    excluded_reasons: tuple[NonEmptyStr, ...]
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    authorization_scope_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    selection_policy_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_seal(self) -> SelectionManifest:
        payload = self.model_dump(
            mode="json", exclude={"manifest_id", "manifest_digest"}
        )
        expected = content_digest(payload)
        if self.manifest_digest != expected:
            raise ValueError("selection manifest digest mismatch")
        if self.manifest_id != f"selection-manifest:{expected}":
            raise ValueError("selection manifest id mismatch")
        if len(set(self.selected_candidate_ids)) != len(self.selected_candidate_ids):
            raise ValueError("selected candidate ids must be unique")
        if len(self.selected_candidate_ids) != len(self.selected_reasons):
            raise ValueError("selected candidates and reasons must align")
        return self


class SelectionReceipt(ContractModel):
    receipt_id: NonEmptyStr
    receipt_digest: Sha256Digest
    working_set_request_digest: Sha256Digest
    selection_manifest_digest: Sha256Digest
    selected_payload_digest: Sha256Digest
    selected_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_seal(self) -> SelectionReceipt:
        payload = self.model_dump(
            mode="json", exclude={"receipt_id", "receipt_digest"}
        )
        expected = content_digest(payload)
        if self.receipt_digest != expected:
            raise ValueError("selection receipt digest mismatch")
        if self.receipt_id != f"selection-receipt:{expected}":
            raise ValueError("selection receipt id mismatch")
        return self


class TrustedWorkingSet(ContractModel):
    request: WorkingSetRequest
    manifest: SelectionManifest
    receipt: SelectionReceipt
    selected_candidates: tuple[ExternalStateCandidateRef, ...]
    selected_candidate_bytes: tuple[bytes, ...]

    @model_validator(mode="after")
    def validate_bindings(self) -> TrustedWorkingSet:
        if len(self.selected_candidates) != len(self.selected_candidate_bytes):
            raise ValueError("selected references and bytes must align")
        selected_ids = tuple(item.candidate_id for item in self.selected_candidates)
        if selected_ids != self.manifest.selected_candidate_ids:
            raise ValueError("selected candidates do not match manifest")
        for candidate, payload in zip(
            self.selected_candidates, self.selected_candidate_bytes, strict=True
        ):
            if hashlib.sha256(payload).hexdigest() != candidate.content_digest:
                raise ValueError("selected candidate bytes do not match digest")
        if content_digest(self.request) != self.receipt.working_set_request_digest:
            raise ValueError("selection receipt request binding mismatch")
        if content_digest(self.manifest) != self.receipt.selection_manifest_digest:
            raise ValueError("selection receipt manifest binding mismatch")
        if self.receipt.selected_count != len(self.selected_candidates):
            raise ValueError("selection receipt count mismatch")
        selected_payload_digest = content_digest(
            {
                "candidate_digests": tuple(
                    content_digest(item) for item in self.selected_candidates
                ),
                "payload_digests": tuple(
                    hashlib.sha256(payload).hexdigest()
                    for payload in self.selected_candidate_bytes
                ),
            }
        )
        if self.receipt.selected_payload_digest != selected_payload_digest:
            raise ValueError("selection receipt payload binding mismatch")
        return self
