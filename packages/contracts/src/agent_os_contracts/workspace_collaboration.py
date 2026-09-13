from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime


class WorkspaceActorKind(str, Enum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    TOOL = "TOOL"
    ENVIRONMENT = "ENVIRONMENT"


class WorkspaceEventKind(str, Enum):
    MUTATION = "MUTATION"
    DELETION = "DELETION"
    DECISION = "DECISION"
    TEST_RESULT = "TEST_RESULT"
    ENVIRONMENT_CHANGE = "ENVIRONMENT_CHANGE"


class WorkspaceEventImpact(str, Enum):
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PLAN_INVALIDATED = "PLAN_INVALIDATED"
    WRITE_CONFLICT = "WRITE_CONFLICT"
    WORK_CANCELLED = "WORK_CANCELLED"


class CollaborationDisposition(str, Enum):
    CONTINUE = "CONTINUE"
    REPLAN = "REPLAN"
    CONFLICT = "CONFLICT"
    CANCEL = "CANCEL"


class ScopeSelector(ContractModel):
    """Format-neutral refinement such as symbol, section, block, table or task intent."""

    dimension: NonEmptyStr
    value: NonEmptyStr


class ResourceScope(ContractModel):
    """A stable resource URI plus optional domain-owned selector dimensions."""

    resource_uri: NonEmptyStr
    selectors: tuple[ScopeSelector, ...] = ()

    @field_validator("selectors", mode="after")
    @classmethod
    def _unique_dimensions(
        cls, values: tuple[ScopeSelector, ...]
    ) -> tuple[ScopeSelector, ...]:
        by_dimension = {selector.dimension: selector for selector in values}
        if len(by_dimension) != len(values):
            raise ValueError("resource scope selector dimensions must be unique")
        return tuple(by_dimension[key] for key in sorted(by_dimension))

    def overlaps(self, other: ResourceScope) -> bool:
        """Return whether two scopes intersect on the resource tree.

        A directory scope (URI with no trailing file component) overlaps every
        resource beneath it; two file scopes overlap only on the same URI.
        """
        if not _uri_path_related(self.resource_uri, other.resource_uri):
            return False
        left = {selector.dimension: selector.value for selector in self.selectors}
        right = {selector.dimension: selector.value for selector in other.selectors}
        return all(left[key] == right[key] for key in left.keys() & right.keys())

    def covers(self, other: ResourceScope) -> bool:
        """Return whether this (possibly broader) scope authorizes the other scope.

        A directory scope covers every resource beneath it (path-prefix), and a
        file scope covers only its exact URI. Selectors narrow, never widen.
        """
        if not _uri_path_covers(self.resource_uri, other.resource_uri):
            return False
        allowed = {selector.dimension: selector.value for selector in self.selectors}
        requested = {selector.dimension: selector.value for selector in other.selectors}
        return all(requested.get(key) == value for key, value in allowed.items())


def _uri_path_related(a: str, b: str) -> bool:
    """True when two resource URIs intersect: equal, or one is a directory prefix of the other."""
    if a == b:
        return True
    return _uri_path_covers(a, b) or _uri_path_covers(b, a)


def _uri_path_covers(parent: str, child: str) -> bool:
    """True when `parent` is equal to `child` or a directory prefix of `child`."""
    if parent == child:
        return True
    prefix = parent if parent.endswith("/") else parent + "/"
    return child.startswith(prefix)


class CoordinationAuthorityContext(ContractModel):
    authorization_id: NonEmptyStr
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    authorized_scopes: tuple[ResourceScope, ...] = Field(min_length=1)
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    issued_at: UtcDateTime
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_window(self) -> CoordinationAuthorityContext:
        if self.expires_at <= self.issued_at:
            raise ValueError("coordination authority must expire after it is issued")
        return self


class WorkspaceEvent(ContractModel):
    event_id: NonEmptyStr
    workspace_id: NonEmptyStr
    sequence: int = Field(ge=1)
    actor_id: NonEmptyStr
    actor_kind: WorkspaceActorKind
    kind: WorkspaceEventKind
    impact: WorkspaceEventImpact
    affected_scopes: tuple[ResourceScope, ...] = Field(min_length=1)
    base_version: NonEmptyStr
    resulting_version: NonEmptyStr
    provenance_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    occurred_at: UtcDateTime

    @field_validator("provenance_refs", mode="after")
    @classmethod
    def _normalize_provenance(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _require_version_advance(self) -> WorkspaceEvent:
        if self.base_version == self.resulting_version:
            raise ValueError("workspace event must advance the resource version")
        return self


class WorkspaceEventBatch(ContractModel):
    """Complete, provenance-bound event read after a lease cursor."""

    workspace_id: NonEmptyStr
    after_cursor: int = Field(ge=0)
    through_cursor: int = Field(ge=0)
    events: tuple[WorkspaceEvent, ...] = ()
    source_id: NonEmptyStr
    provenance_ref: NonEmptyStr
    read_at: UtcDateTime
    complete: bool
    shared_version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_complete_sequence(self) -> WorkspaceEventBatch:
        if not self.complete:
            return self
        if self.through_cursor < self.after_cursor:
            raise ValueError("event batch through_cursor cannot precede after_cursor")
        sequences = tuple(event.sequence for event in self.events)
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("event batch sequences must be unique and increasing")
        if any(event.workspace_id != self.workspace_id for event in self.events):
            raise ValueError("event batch workspace mismatch")
        if any(sequence <= self.after_cursor for sequence in sequences):
            raise ValueError("event batch contains an event at or before after_cursor")
        if sequences and sequences[-1] != self.through_cursor:
            raise ValueError("event batch through_cursor must equal the last event sequence")
        if not sequences and self.through_cursor != self.after_cursor:
            raise ValueError("empty event batch cannot advance through_cursor")
        return self


class WorkLease(ContractModel):
    lease_id: NonEmptyStr
    lease_version: int = Field(default=1, ge=1)
    fence_token: int = Field(default=1, ge=1)
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    holder_id: NonEmptyStr
    plan_version: int = Field(ge=1)
    event_cursor: int = Field(ge=0)
    scopes: tuple[ResourceScope, ...] = Field(min_length=1)
    authority_context: CoordinationAuthorityContext
    issued_at: UtcDateTime
    expires_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_window(self) -> WorkLease:
        if self.expires_at <= self.issued_at:
            raise ValueError("work lease expires_at must be after issued_at")
        authority = self.authority_context
        if (
            self.holder_id != authority.principal_id
            or self.tenant_id != authority.tenant_id
            or self.workspace_id != authority.workspace_id
        ):
            raise ValueError("work lease identity must match coordination authority")
        if self.expires_at > authority.expires_at:
            raise ValueError("work lease cannot outlive coordination authority")
        if any(
            not any(allowed.covers(scope) for allowed in authority.authorized_scopes)
            for scope in self.scopes
        ):
            raise ValueError("work lease scope exceeds coordination authority")
        return self


class WorkspaceWriteDecision(ContractModel):
    lease_id: NonEmptyStr
    action_id: NonEmptyStr
    plan_version: int = Field(ge=1)
    disposition: CollaborationDisposition
    checked_event_cursor: int = Field(ge=0)
    relevant_event_ids: tuple[NonEmptyStr, ...] = ()
    event_batch_provenance_ref: NonEmptyStr
    write_scopes: tuple[ResourceScope, ...] = Field(min_length=1)
    fence_id: NonEmptyStr | None = None
    fence_version: int | None = Field(default=None, ge=0)
    shared_version: int = Field(default=0, ge=0)
    authority_context_digest: NonEmptyStr | None = None
    reason: NonEmptyStr
    decided_at: UtcDateTime

    @property
    def external_write_authorized(self) -> bool:
        return self.disposition is CollaborationDisposition.CONTINUE
