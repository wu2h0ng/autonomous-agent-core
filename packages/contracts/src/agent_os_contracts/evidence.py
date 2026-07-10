from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class ArtifactLocationClass(str, Enum):
    WORKSPACE_LOCAL = "WORKSPACE_LOCAL"
    OBJECT_STORE = "OBJECT_STORE"


class EvidenceSourceKind(str, Enum):
    ARTIFACT = "ARTIFACT"
    TASK_EVENT = "TASK_EVENT"
    ACTION_RECEIPT = "ACTION_RECEIPT"
    EXTERNAL_OBSERVATION = "EXTERNAL_OBSERVATION"


class ArtifactRef(ContractModel):
    artifact_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    content_digest: Sha256Digest
    media_type: NonEmptyStr
    location_class: ArtifactLocationClass
    location_ref: NonEmptyStr
    acl_scopes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    retention_policy: NonEmptyStr
    created_by: NonEmptyStr
    created_at: UtcDateTime

    @field_validator("acl_scopes", mode="after")
    @classmethod
    def _normalize_acl_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class EvidenceRef(ContractModel):
    evidence_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_kind: EvidenceSourceKind
    source_ref: NonEmptyStr
    relation: NonEmptyStr
    artifact_ids: tuple[NonEmptyStr, ...] = ()
    created_by: NonEmptyStr
    created_at: UtcDateTime

    @field_validator("artifact_ids", mode="after")
    @classmethod
    def _normalize_artifact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))
