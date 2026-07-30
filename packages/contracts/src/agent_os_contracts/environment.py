from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from .evaluator import Uncertainty
from .evidence import Sha256Digest


class EnvironmentEntity(ContractModel):
    entity_id: NonEmptyStr
    entity_kind: NonEmptyStr
    state_digest: Sha256Digest
    observed_at: UtcDateTime


class EnvironmentRelation(ContractModel):
    subject_entity_id: NonEmptyStr
    predicate: NonEmptyStr
    object_entity_id: NonEmptyStr


class EnvironmentDynamic(ContractModel):
    dynamic_id: NonEmptyStr
    subject_entity_id: NonEmptyStr
    change_kind: NonEmptyStr
    observed_at: UtcDateTime


class EnvironmentSourceCoverage(ContractModel):
    source_id: NonEmptyStr
    source_ref: NonEmptyStr
    covered_entity_ids: tuple[NonEmptyStr, ...] = ()
    observed_at: UtcDateTime

    @field_validator("covered_entity_ids", mode="after")
    @classmethod
    def _normalize_covered_entities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class EnvironmentModelSnapshot(ContractModel):
    """Versioned task-relevant entities, relations, dynamics, source coverage
    and uncertainty.

    Named consumer: work compiler / evaluator.
    Fail-closed: stale scope (``valid_until`` elapsed or before
    ``captured_at``), unknown provenance (empty ``sources`` or coverage of
    undeclared entities) and incompatible schema (``schema_version`` drift)
    are rejected.
    """

    snapshot_id: NonEmptyStr
    snapshot_version: int = Field(ge=1)
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    task_id: NonEmptyStr
    entities: tuple[EnvironmentEntity, ...] = Field(min_length=1)
    relations: tuple[EnvironmentRelation, ...] = ()
    dynamics: tuple[EnvironmentDynamic, ...] = ()
    sources: tuple[EnvironmentSourceCoverage, ...] = Field(min_length=1)
    uncertainty: Uncertainty
    captured_at: UtcDateTime
    valid_until: UtcDateTime

    @model_validator(mode="after")
    def _validate_snapshot(self) -> EnvironmentModelSnapshot:
        if self.valid_until <= self.captured_at:
            raise ValueError("valid_until must be after captured_at")
        entity_ids = tuple(entity.entity_id for entity in self.entities)
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("environment entity ids must be unique")
        known = set(entity_ids)
        for relation in self.relations:
            if (
                relation.subject_entity_id not in known
                or relation.object_entity_id not in known
            ):
                raise ValueError("environment relation references unknown entity")
        for dynamic in self.dynamics:
            if dynamic.subject_entity_id not in known:
                raise ValueError("environment dynamic references unknown entity")
        for source in self.sources:
            if any(entity_id not in known for entity_id in source.covered_entity_ids):
                raise ValueError("source coverage references unknown entity")
        return self

    def canonical_digest(self) -> Sha256Digest:
        return content_digest(self)
