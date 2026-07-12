from __future__ import annotations

from pydantic import Field

from .common import ContractModel, NonEmptyStr, UtcDateTime


class DomainPackManifest(ContractModel):
    pack_id: NonEmptyStr
    version: NonEmptyStr
    namespace: NonEmptyStr
    capabilities: tuple[NonEmptyStr, ...] = Field(min_length=1)
    workflow_templates: tuple[NonEmptyStr, ...] = ()
    evaluator_types: tuple[NonEmptyStr, ...] = ()
    credential_classes: tuple[NonEmptyStr, ...] = ()
    created_at: UtcDateTime
