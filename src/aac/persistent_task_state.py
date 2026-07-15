"""Persistent semantic task-state primitives for R-STATE-CREDIT-1 Stage A.

This is an isolated Research Track mechanism.  It is not Product Runtime state,
does not import the R-CSL-1 commitment ledger, and carries no execution or
promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, TypeVar, cast


class TaskStateError(RuntimeError):
    """Base error for the Stage-A state mechanism."""


class UnknownFieldError(TaskStateError):
    """Raised when an untyped field tries to enter a closed state contract."""


class StateValidationError(TaskStateError):
    """Raised when a typed record violates a state invariant."""


class ConcurrentStateWrite(TaskStateError):
    """Raised when a patch does not match the snapshot CAS head."""


class StateOverflowError(TaskStateError):
    """Raised when protected records cannot fit a bounded projection."""


class EntityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TOMBSTONED = "TOMBSTONED"


class EpistemicClass(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    UNIDENTIFIED = "UNIDENTIFIED"


class AssertionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    REFUTED = "REFUTED"
    SUPERSEDED = "SUPERSEDED"


class CommitmentStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    ABANDONED = "ABANDONED"


class RecoveryDirective(str, Enum):
    RESUME = "RESUME"
    VERIFY_EFFECT = "VERIFY_EFFECT"
    ABSTAIN = "ABSTAIN"


T = TypeVar("T", bound="ClosedSchema")


class ClosedSchema:
    """Strict construction helper for already-typed internal mappings."""

    @classmethod
    def from_mapping(cls: type[T], value: Mapping[str, Any]) -> T:
        expected = {field.name for field in fields(cast(Any, cls))}
        unknown = sorted(set(value).difference(expected))
        if unknown:
            raise UnknownFieldError(
                f"unknown field(s) for {cls.__name__}: {', '.join(unknown)}"
            )
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise StateValidationError(str(exc)) from exc


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{name} must be non-empty text")


def _require_revision(name: str, value: int, *, allow_zero: bool = False) -> None:
    floor = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < floor:
        raise StateValidationError(f"{name} must be an integer >= {floor}")


def _require_datetime(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StateValidationError(f"{name} must be timezone-aware")


def _require_digest(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StateValidationError(f"{name} must be a lowercase SHA-256 digest")


def _require_text_tuple(name: str, value: tuple[str, ...]) -> None:
    if not isinstance(value, tuple):
        raise StateValidationError(f"{name} must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise StateValidationError(f"{name} must contain non-empty text")
    if len(value) != len(set(value)):
        raise StateValidationError(f"{name} must not contain duplicates")


def _require_typed_tuple(name: str, value: tuple[Any, ...], item_type: type[Any]) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, item_type) for item in value):
        raise StateValidationError(f"{name} must be a tuple of {item_type.__name__}")


@dataclass(frozen=True, slots=True)
class EntityState(ClosedSchema):
    entity_id: str
    kind: str
    object_version: str
    revision: int
    observed_keys: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    status: EntityStatus = EntityStatus.ACTIVE
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("entity_id", self.entity_id)
        _require_text("kind", self.kind)
        _require_text("object_version", self.object_version)
        _require_revision("revision", self.revision)
        _require_text_tuple("observed_keys", self.observed_keys)
        if not self.observed_keys:
            raise StateValidationError("observed_keys must not be empty")
        _require_text_tuple("aliases", self.aliases)
        _require_text_tuple("evidence_refs", self.evidence_refs)
        if not isinstance(self.status, EntityStatus):
            raise StateValidationError("status must be EntityStatus")


@dataclass(frozen=True, slots=True)
class Assertion(ClosedSchema):
    assertion_id: str
    entity_id: str
    entity_version: str
    predicate: str
    value: str
    epistemic_class: EpistemicClass
    confidence: float
    status: AssertionStatus
    valid_from: datetime
    valid_to: datetime | None
    transaction_time: datetime
    transaction_version: int = 0
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    depends_on_assertion_ids: tuple[str, ...] = ()
    supersedes_assertion_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("assertion_id", "entity_id", "entity_version", "predicate", "value"):
            _require_text(name, getattr(self, name))
        if not isinstance(self.epistemic_class, EpistemicClass):
            raise StateValidationError("epistemic_class must be EpistemicClass")
        if not isinstance(self.status, AssertionStatus):
            raise StateValidationError("status must be AssertionStatus")
        if (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise StateValidationError("confidence must be finite and within [0, 1]")
        _require_datetime("valid_from", self.valid_from)
        _require_datetime("transaction_time", self.transaction_time)
        if self.valid_to is not None:
            _require_datetime("valid_to", self.valid_to)
            if self.valid_to <= self.valid_from:
                raise StateValidationError("valid_to must be after valid_from")
        _require_revision("transaction_version", self.transaction_version, allow_zero=True)
        _require_text_tuple("evidence_refs", self.evidence_refs)
        _require_text_tuple("provenance_refs", self.provenance_refs)
        _require_text_tuple("depends_on_assertion_ids", self.depends_on_assertion_ids)
        if self.assertion_id in self.depends_on_assertion_ids:
            raise StateValidationError("assertion cannot depend on itself")
        if self.supersedes_assertion_id is not None:
            _require_text("supersedes_assertion_id", self.supersedes_assertion_id)
            if self.supersedes_assertion_id == self.assertion_id:
                raise StateValidationError("assertion cannot supersede itself")


@dataclass(frozen=True, slots=True)
class CommitmentState(ClosedSchema):
    commitment_id: str
    revision: int
    deliverable: str
    status: CommitmentStatus
    precondition_assertion_ids: tuple[str, ...]
    postconditions: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    depends_on_commitment_ids: tuple[str, ...] = ()
    wait_condition: str | None = None
    deadline: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("commitment_id", self.commitment_id)
        _require_revision("revision", self.revision)
        _require_text("deliverable", self.deliverable)
        if not isinstance(self.status, CommitmentStatus):
            raise StateValidationError("status must be CommitmentStatus")
        _require_text_tuple("precondition_assertion_ids", self.precondition_assertion_ids)
        _require_text_tuple("postconditions", self.postconditions)
        _require_text_tuple("evidence_requirements", self.evidence_requirements)
        _require_text_tuple("depends_on_commitment_ids", self.depends_on_commitment_ids)
        if not self.postconditions:
            raise StateValidationError("postconditions must not be empty")
        if not self.evidence_requirements:
            raise StateValidationError("evidence_requirements must not be empty")
        if self.commitment_id in self.depends_on_commitment_ids:
            raise StateValidationError("commitment cannot depend on itself")
        if self.wait_condition is not None:
            _require_text("wait_condition", self.wait_condition)
        if self.deadline is not None:
            _require_datetime("deadline", self.deadline)


@dataclass(frozen=True, slots=True)
class DecisionRecord(ClosedSchema):
    decision_id: str
    revision: int
    state_snapshot_digest: str
    alternatives: tuple[str, ...]
    selected_action: str
    relied_on_assertion_ids: tuple[str, ...]
    predicted_postconditions: tuple[str, ...]
    dispatched: bool = False
    receipt_ref: str | None = None
    effect_verified: bool = False

    def __post_init__(self) -> None:
        _require_text("decision_id", self.decision_id)
        _require_revision("revision", self.revision)
        _require_digest("state_snapshot_digest", self.state_snapshot_digest)
        _require_text_tuple("alternatives", self.alternatives)
        _require_text("selected_action", self.selected_action)
        _require_text_tuple("relied_on_assertion_ids", self.relied_on_assertion_ids)
        _require_text_tuple("predicted_postconditions", self.predicted_postconditions)
        if self.alternatives and self.selected_action not in self.alternatives:
            raise StateValidationError("selected_action must be one of alternatives")
        if not isinstance(self.dispatched, bool) or not isinstance(self.effect_verified, bool):
            raise StateValidationError("dispatch/effect flags must be bool")
        if self.receipt_ref is not None:
            _require_text("receipt_ref", self.receipt_ref)
            if not self.dispatched:
                raise StateValidationError("receipt_ref requires a dispatched decision")
        if self.effect_verified and self.receipt_ref is None:
            raise StateValidationError("effect_verified requires a receipt_ref")


@dataclass(frozen=True, slots=True)
class StatePatchCandidate(ClosedSchema):
    patch_id: str
    task_id: str
    base_version: int
    base_digest: str
    transaction_time: datetime
    entities: tuple[EntityState, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    commitments: tuple[CommitmentState, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    refute_assertion_ids: tuple[str, ...] = ()
    tombstone_entity_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("patch_id", self.patch_id)
        _require_text("task_id", self.task_id)
        _require_revision("base_version", self.base_version, allow_zero=True)
        _require_digest("base_digest", self.base_digest)
        _require_datetime("transaction_time", self.transaction_time)
        _require_typed_tuple("entities", self.entities, EntityState)
        _require_typed_tuple("assertions", self.assertions, Assertion)
        _require_typed_tuple("commitments", self.commitments, CommitmentState)
        _require_typed_tuple("decisions", self.decisions, DecisionRecord)
        _require_text_tuple("refute_assertion_ids", self.refute_assertion_ids)
        _require_text_tuple("tombstone_entity_ids", self.tombstone_entity_ids)
        if not any(
            (
                self.entities,
                self.assertions,
                self.commitments,
                self.decisions,
                self.refute_assertion_ids,
                self.tombstone_entity_ids,
            )
        ):
            raise StateValidationError("patch must contain at least one state operation")

    def digest(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class TaskStateSnapshot(ClosedSchema):
    task_id: str
    version: int = 0
    head_patch_id: str | None = None
    entities: tuple[EntityState, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    commitments: tuple[CommitmentState, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    applied_patch_ids: tuple[str, ...] = ()
    patch_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("task_id", self.task_id)
        _require_revision("version", self.version, allow_zero=True)
        if self.head_patch_id is not None:
            _require_text("head_patch_id", self.head_patch_id)
        _require_typed_tuple("entities", self.entities, EntityState)
        _require_typed_tuple("assertions", self.assertions, Assertion)
        _require_typed_tuple("commitments", self.commitments, CommitmentState)
        _require_typed_tuple("decisions", self.decisions, DecisionRecord)
        _require_text_tuple("applied_patch_ids", self.applied_patch_ids)
        _require_text_tuple("patch_digests", self.patch_digests)
        if len(self.applied_patch_ids) != self.version or len(self.patch_digests) != self.version:
            raise StateValidationError("snapshot version must match append-only patch history")
        for digest in self.patch_digests:
            _require_digest("patch_digest", digest)

    def digest(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class TaskStateProjection(ClosedSchema):
    task_id: str
    source_version: int
    source_digest: str
    entities: tuple[EntityState, ...]
    assertions: tuple[Assertion, ...]
    commitments: tuple[CommitmentState, ...]
    decisions: tuple[DecisionRecord, ...]
    omitted_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("task_id", self.task_id)
        _require_revision("source_version", self.source_version, allow_zero=True)
        _require_digest("source_digest", self.source_digest)
        _require_typed_tuple("entities", self.entities, EntityState)
        _require_typed_tuple("assertions", self.assertions, Assertion)
        _require_typed_tuple("commitments", self.commitments, CommitmentState)
        _require_typed_tuple("decisions", self.decisions, DecisionRecord)
        _require_text_tuple("omitted_record_ids", self.omitted_record_ids)


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class TaskStateReducer:
    """Deterministic append-only reducer; behavior is added by Stage-A tests."""

    @staticmethod
    def empty(task_id: str) -> TaskStateSnapshot:
        return TaskStateSnapshot(task_id=task_id)

    @staticmethod
    def apply(
        snapshot: TaskStateSnapshot,
        patch: StatePatchCandidate,
    ) -> TaskStateSnapshot:
        if not isinstance(snapshot, TaskStateSnapshot) or not isinstance(
            patch, StatePatchCandidate
        ):
            raise StateValidationError("apply requires typed snapshot and patch")
        if patch.task_id != snapshot.task_id:
            raise StateValidationError("patch task_id does not match snapshot")
        if patch.patch_id in snapshot.applied_patch_ids:
            raise StateValidationError(f"duplicate patch_id: {patch.patch_id}")
        if (
            patch.base_version != snapshot.version
            or patch.base_digest != snapshot.digest()
        ):
            raise ConcurrentStateWrite("patch CAS head does not match current snapshot")
        if set(patch.tombstone_entity_ids).intersection(
            entity.entity_id for entity in patch.entities
        ):
            raise StateValidationError("one patch cannot revise and tombstone the same entity")

        entities = {entity.entity_id: entity for entity in snapshot.entities}
        assertions = {
            assertion.assertion_id: assertion for assertion in snapshot.assertions
        }
        commitments = {
            commitment.commitment_id: commitment
            for commitment in snapshot.commitments
        }
        decisions = {
            decision.decision_id: decision for decision in snapshot.decisions
        }
        base_assertions = {
            assertion.assertion_id: assertion for assertion in snapshot.assertions
        }
        incoming_entity_ids = [item.entity_id for item in patch.entities]
        if len(incoming_entity_ids) != len(set(incoming_entity_ids)):
            raise StateValidationError("patch contains duplicate entity ids")
        for candidate in patch.entities:
            current = entities.get(candidate.entity_id)
            if current is None:
                if candidate.revision != 1:
                    raise StateValidationError("new entity revision must be 1")
                if candidate.status is not EntityStatus.ACTIVE:
                    raise StateValidationError("new entity must be ACTIVE")
                entities[candidate.entity_id] = candidate
                continue
            if current.status is EntityStatus.TOMBSTONED:
                raise StateValidationError("tombstoned entity cannot be revised")
            if candidate.revision != current.revision + 1:
                raise StateValidationError("entity revision must advance by exactly one")
            if candidate.kind != current.kind:
                raise StateValidationError("entity kind cannot change across revisions")
            if candidate.status is not EntityStatus.ACTIVE:
                raise StateValidationError("entity status changes require a tombstone operation")
            entities[candidate.entity_id] = replace(
                candidate,
                observed_keys=tuple(sorted(set(current.observed_keys + candidate.observed_keys))),
                aliases=tuple(sorted(set(current.aliases + candidate.aliases))),
                evidence_refs=tuple(
                    sorted(set(current.evidence_refs + candidate.evidence_refs))
                ),
            )

        for entity_id in patch.tombstone_entity_ids:
            current = entities.get(entity_id)
            if current is None:
                raise StateValidationError(f"cannot tombstone unknown entity: {entity_id}")
            if current.status is EntityStatus.TOMBSTONED:
                raise StateValidationError(f"entity already tombstoned: {entity_id}")
            entities[entity_id] = replace(
                current,
                revision=current.revision + 1,
                status=EntityStatus.TOMBSTONED,
            )

        next_version = snapshot.version + 1
        incoming_assertion_ids = [item.assertion_id for item in patch.assertions]
        if len(incoming_assertion_ids) != len(set(incoming_assertion_ids)):
            raise StateValidationError("patch contains duplicate assertion ids")
        for candidate in patch.assertions:
            if candidate.assertion_id in assertions:
                raise StateValidationError(
                    f"assertion id is append-only: {candidate.assertion_id}"
                )
            if candidate.status is not AssertionStatus.ACTIVE:
                raise StateValidationError("new assertion must enter as ACTIVE")
            if candidate.transaction_version != 0:
                raise StateValidationError("new assertion transaction_version must be 0")
            if candidate.transaction_time != patch.transaction_time:
                raise StateValidationError(
                    "assertion transaction_time must equal patch transaction_time"
                )
            entity = entities.get(candidate.entity_id)
            if entity is None or entity.status is EntityStatus.TOMBSTONED:
                raise StateValidationError(
                    f"assertion references unavailable entity: {candidate.entity_id}"
                )
            if candidate.entity_version != entity.object_version:
                raise StateValidationError(
                    "assertion entity version does not match current entity version"
                )
            assertions[candidate.assertion_id] = replace(
                candidate,
                transaction_version=next_version,
            )

        for candidate in patch.assertions:
            for dependency_id in candidate.depends_on_assertion_ids:
                if dependency_id not in assertions:
                    raise StateValidationError(
                        f"assertion dependency does not exist: {dependency_id}"
                    )
            superseded_id = candidate.supersedes_assertion_id
            if superseded_id is not None:
                prior = assertions.get(superseded_id)
                if prior is None:
                    raise StateValidationError(
                        f"superseded assertion does not exist: {superseded_id}"
                    )
                if prior.status in {
                    AssertionStatus.REFUTED,
                    AssertionStatus.SUPERSEDED,
                }:
                    raise StateValidationError(
                        f"assertion is already terminal: {superseded_id}"
                    )
                assertions[superseded_id] = replace(
                    prior, status=AssertionStatus.SUPERSEDED
                )
        _ensure_acyclic(
            {
                assertion_id: assertion.depends_on_assertion_ids
                for assertion_id, assertion in assertions.items()
            },
            label="assertion dependency",
        )

        for assertion_id in patch.refute_assertion_ids:
            current = assertions.get(assertion_id)
            if current is None:
                raise StateValidationError(
                    f"cannot refute unknown assertion: {assertion_id}"
                )
            if current.status is AssertionStatus.SUPERSEDED:
                raise StateValidationError(
                    f"cannot refute superseded assertion: {assertion_id}"
                )
            assertions[assertion_id] = replace(
                current, status=AssertionStatus.REFUTED
            )

        for assertion_id, assertion in tuple(assertions.items()):
            entity = entities.get(assertion.entity_id)
            if (
                assertion.status
                not in {AssertionStatus.REFUTED, AssertionStatus.SUPERSEDED}
                and (
                    entity is None
                    or entity.status is EntityStatus.TOMBSTONED
                    or assertion.entity_version != entity.object_version
                )
            ):
                assertions[assertion_id] = replace(
                    assertion, status=AssertionStatus.STALE
                )

        assertions = _recompute_conflicts(assertions)
        assertions = _cascade_stale_assertions(assertions)

        incoming_commitment_ids = [item.commitment_id for item in patch.commitments]
        if len(incoming_commitment_ids) != len(set(incoming_commitment_ids)):
            raise StateValidationError("patch contains duplicate commitment ids")
        for candidate in patch.commitments:
            current = commitments.get(candidate.commitment_id)
            if current is None:
                if candidate.revision != 1:
                    raise StateValidationError("new commitment revision must be 1")
            else:
                if candidate.revision != current.revision + 1:
                    raise StateValidationError(
                        "commitment revision must advance by exactly one"
                    )
                expected_revision = replace(
                    current,
                    revision=candidate.revision,
                    status=candidate.status,
                )
                if expected_revision != candidate:
                    raise StateValidationError(
                        "commitment revision may change status only"
                    )
            commitments[candidate.commitment_id] = candidate

        for commitment in commitments.values():
            for assertion_id in commitment.precondition_assertion_ids:
                if assertion_id not in assertions:
                    raise StateValidationError(
                        f"commitment precondition does not exist: {assertion_id}"
                    )
            for dependency_id in commitment.depends_on_commitment_ids:
                if dependency_id not in commitments:
                    raise StateValidationError(
                        f"commitment dependency does not exist: {dependency_id}"
                    )
        _ensure_acyclic(
            {
                commitment_id: commitment.depends_on_commitment_ids
                for commitment_id, commitment in commitments.items()
            },
            label="commitment dependency",
        )
        commitments = _block_invalid_commitments(commitments, assertions)

        incoming_decision_ids = [item.decision_id for item in patch.decisions]
        if len(incoming_decision_ids) != len(set(incoming_decision_ids)):
            raise StateValidationError("patch contains duplicate decision ids")
        for candidate in patch.decisions:
            current = decisions.get(candidate.decision_id)
            if current is None:
                if candidate.revision != 1:
                    raise StateValidationError("new decision revision must be 1")
                if candidate.state_snapshot_digest != snapshot.digest():
                    raise StateValidationError(
                        "new decision must bind the exact base snapshot digest"
                    )
                if candidate.dispatched:
                    raise StateValidationError(
                        "new decision must be recorded before dispatch"
                    )
                for assertion_id in candidate.relied_on_assertion_ids:
                    assertion = base_assertions.get(assertion_id)
                    if (
                        assertion is None
                        or assertion.status is not AssertionStatus.ACTIVE
                    ):
                        raise StateValidationError(
                            "decision may rely only on an ACTIVE assertion "
                            f"from its bound snapshot: {assertion_id}"
                        )
                decisions[candidate.decision_id] = candidate
                continue

            if candidate.revision != current.revision + 1:
                raise StateValidationError(
                    "decision revision must advance by exactly one"
                )
            expected_revision = replace(
                current,
                revision=candidate.revision,
                dispatched=candidate.dispatched,
                receipt_ref=candidate.receipt_ref,
                effect_verified=candidate.effect_verified,
            )
            if expected_revision != candidate:
                raise StateValidationError(
                    "decision revision may change execution state only"
                )
            if current.dispatched and not candidate.dispatched:
                raise StateValidationError("decision dispatch state cannot regress")
            if (
                current.receipt_ref is not None
                and candidate.receipt_ref != current.receipt_ref
            ):
                raise StateValidationError("decision receipt cannot change or disappear")
            if current.effect_verified and not candidate.effect_verified:
                raise StateValidationError("verified decision effect cannot regress")
            decisions[candidate.decision_id] = candidate

        return TaskStateSnapshot(
            task_id=snapshot.task_id,
            version=next_version,
            head_patch_id=patch.patch_id,
            entities=tuple(sorted(entities.values(), key=lambda entity: entity.entity_id)),
            assertions=tuple(
                sorted(assertions.values(), key=lambda assertion: assertion.assertion_id)
            ),
            commitments=tuple(
                sorted(
                    commitments.values(),
                    key=lambda commitment: commitment.commitment_id,
                )
            ),
            decisions=tuple(
                sorted(decisions.values(), key=lambda decision: decision.decision_id)
            ),
            applied_patch_ids=snapshot.applied_patch_ids + (patch.patch_id,),
            patch_digests=snapshot.patch_digests + (patch.digest(),),
        )

    @classmethod
    def rehydrate(
        cls,
        task_id: str,
        patches: tuple[StatePatchCandidate, ...],
    ) -> TaskStateSnapshot:
        if not isinstance(patches, tuple) or any(
            not isinstance(patch, StatePatchCandidate) for patch in patches
        ):
            raise StateValidationError("patches must be a tuple of StatePatchCandidate")
        snapshot = cls.empty(task_id)
        for patch in patches:
            snapshot = cls.apply(snapshot, patch)
        return snapshot

    @staticmethod
    def assertions_valid_at(
        snapshot: TaskStateSnapshot,
        *,
        valid_time: datetime,
    ) -> tuple[Assertion, ...]:
        """Read current epistemic assertions valid at an explicit valid time."""
        if not isinstance(snapshot, TaskStateSnapshot):
            raise StateValidationError(
                "assertions_valid_at requires a typed snapshot"
            )
        _require_datetime("valid_time", valid_time)
        current_statuses = {
            AssertionStatus.ACTIVE,
            AssertionStatus.CONFLICTED,
        }
        return tuple(
            assertion
            for assertion in snapshot.assertions
            if assertion.status in current_statuses
            and assertion.valid_from <= valid_time
            and (
                assertion.valid_to is None
                or valid_time < assertion.valid_to
            )
        )

    @staticmethod
    def recovery_directive(snapshot: TaskStateSnapshot) -> RecoveryDirective:
        """Choose a fail-closed recovery action without authorizing replay."""
        if not isinstance(snapshot, TaskStateSnapshot):
            raise StateValidationError(
                "recovery_directive requires a typed snapshot"
            )
        ambiguous = tuple(
            decision
            for decision in snapshot.decisions
            if decision.dispatched and not decision.effect_verified
        )
        if not ambiguous:
            return RecoveryDirective.RESUME
        if len(ambiguous) != 1:
            return RecoveryDirective.ABSTAIN
        decision = ambiguous[0]
        if not decision.predicted_postconditions:
            return RecoveryDirective.ABSTAIN
        assertions = {
            assertion.assertion_id: assertion for assertion in snapshot.assertions
        }
        if any(
            assertion_id not in assertions
            or assertions[assertion_id].status is not AssertionStatus.ACTIVE
            for assertion_id in decision.relied_on_assertion_ids
        ):
            return RecoveryDirective.ABSTAIN
        return RecoveryDirective.VERIFY_EFFECT

    @staticmethod
    def project(
        snapshot: TaskStateSnapshot,
        *,
        max_records: int = 128,
        max_bytes: int = 32 * 1024,
    ) -> TaskStateProjection:
        if not isinstance(snapshot, TaskStateSnapshot):
            raise StateValidationError("project requires a typed snapshot")
        if (
            not isinstance(max_records, int)
            or isinstance(max_records, bool)
            or max_records <= 0
        ):
            raise StateValidationError("max_records must be a positive integer")
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise StateValidationError("max_bytes must be a positive integer")

        nonterminal_commitments = {
            item.commitment_id
            for item in snapshot.commitments
            if item.status
            not in {CommitmentStatus.SATISFIED, CommitmentStatus.ABANDONED}
        }
        referenced_assertions = {
            dependency_id
            for assertion in snapshot.assertions
            for dependency_id in assertion.depends_on_assertion_ids
        }
        referenced_assertions.update(
            assertion_id
            for commitment in snapshot.commitments
            if commitment.commitment_id in nonterminal_commitments
            for assertion_id in commitment.precondition_assertion_ids
        )
        referenced_assertions.update(
            assertion_id
            for decision in snapshot.decisions
            if not decision.effect_verified
            for assertion_id in decision.relied_on_assertion_ids
        )

        protected_assertions = tuple(
            assertion
            for assertion in snapshot.assertions
            if assertion.status
            in {AssertionStatus.ACTIVE, AssertionStatus.CONFLICTED}
            or assertion.assertion_id in referenced_assertions
        )
        protected_entity_ids = {
            assertion.entity_id for assertion in protected_assertions
        }
        protected_entities = tuple(
            entity
            for entity in snapshot.entities
            if entity.status is EntityStatus.ACTIVE
            or entity.entity_id in protected_entity_ids
        )
        protected_commitments = tuple(
            commitment
            for commitment in snapshot.commitments
            if commitment.commitment_id in nonterminal_commitments
        )
        protected_decisions = tuple(
            decision for decision in snapshot.decisions if not decision.effect_verified
        )

        safe_records: list[EntityState | Assertion | CommitmentState | DecisionRecord] = []
        safe_records.extend(
            entity for entity in snapshot.entities if entity not in protected_entities
        )
        safe_records.extend(
            assertion
            for assertion in snapshot.assertions
            if assertion not in protected_assertions
        )
        safe_records.extend(
            commitment
            for commitment in snapshot.commitments
            if commitment not in protected_commitments
        )
        safe_records.extend(
            decision
            for decision in snapshot.decisions
            if decision not in protected_decisions
        )
        safe_records.sort(key=_record_id)

        selected_entities = list(protected_entities)
        selected_assertions = list(protected_assertions)
        selected_commitments = list(protected_commitments)
        selected_decisions = list(protected_decisions)
        omitted = [_record_id(record) for record in safe_records]

        def build_projection() -> TaskStateProjection:
            return TaskStateProjection(
                task_id=snapshot.task_id,
                source_version=snapshot.version,
                source_digest=snapshot.digest(),
                entities=tuple(sorted(selected_entities, key=lambda item: item.entity_id)),
                assertions=tuple(
                    sorted(selected_assertions, key=lambda item: item.assertion_id)
                ),
                commitments=tuple(
                    sorted(selected_commitments, key=lambda item: item.commitment_id)
                ),
                decisions=tuple(
                    sorted(selected_decisions, key=lambda item: item.decision_id)
                ),
                omitted_record_ids=tuple(sorted(omitted)),
            )

        def record_count() -> int:
            return sum(
                map(
                    len,
                    (
                        selected_entities,
                        selected_assertions,
                        selected_commitments,
                        selected_decisions,
                    ),
                )
            )

        projection = build_projection()
        if record_count() > max_records or _encoded_size(projection) > max_bytes:
            raise StateOverflowError(
                "STATE_OVERFLOW: protected semantic state exceeds projection budget"
            )

        for record in safe_records:
            if record_count() >= max_records:
                break
            target: list[Any]
            if isinstance(record, EntityState):
                target = selected_entities
            elif isinstance(record, Assertion):
                target = selected_assertions
            elif isinstance(record, CommitmentState):
                target = selected_commitments
            else:
                target = selected_decisions
            target.append(record)
            omitted.remove(_record_id(record))
            candidate = build_projection()
            if _encoded_size(candidate) > max_bytes:
                target.pop()
                omitted.append(_record_id(record))
                break
            projection = candidate
        return projection


def _record_id(
    record: EntityState | Assertion | CommitmentState | DecisionRecord,
) -> str:
    if isinstance(record, EntityState):
        return record.entity_id
    if isinstance(record, Assertion):
        return record.assertion_id
    if isinstance(record, CommitmentState):
        return record.commitment_id
    return record.decision_id


def _encoded_size(value: Any) -> int:
    return len(
        json.dumps(
            _canonical(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _intervals_overlap(left: Assertion, right: Assertion) -> bool:
    left_end = left.valid_to
    right_end = right.valid_to
    return (left_end is None or right.valid_from < left_end) and (
        right_end is None or left.valid_from < right_end
    )


def _recompute_conflicts(
    assertions: dict[str, Assertion],
) -> dict[str, Assertion]:
    result = {
        assertion_id: (
            replace(assertion, status=AssertionStatus.ACTIVE)
            if assertion.status is AssertionStatus.CONFLICTED
            else assertion
        )
        for assertion_id, assertion in assertions.items()
    }
    active = [
        assertion
        for assertion in result.values()
        if assertion.status is AssertionStatus.ACTIVE
    ]
    conflicted_ids: set[str] = set()
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            if (
                left.entity_id == right.entity_id
                and left.entity_version == right.entity_version
                and left.predicate == right.predicate
                and left.value != right.value
                and _intervals_overlap(left, right)
            ):
                conflicted_ids.update((left.assertion_id, right.assertion_id))
    for assertion_id in conflicted_ids:
        result[assertion_id] = replace(
            result[assertion_id], status=AssertionStatus.CONFLICTED
        )
    return result


def _ensure_acyclic(
    dependencies: Mapping[str, tuple[str, ...]],
    *,
    label: str,
) -> None:
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(record_id: str) -> None:
        if record_id in visiting:
            raise StateValidationError(f"{label} cycle detected at: {record_id}")
        if record_id in visited:
            return
        visiting.add(record_id)
        for dependency_id in dependencies[record_id]:
            visit(dependency_id)
        visiting.remove(record_id)
        visited.add(record_id)

    for record_id in dependencies:
        visit(record_id)


def _cascade_stale_assertions(
    assertions: dict[str, Assertion],
) -> dict[str, Assertion]:
    result = dict(assertions)
    bad = {
        AssertionStatus.STALE,
        AssertionStatus.CONFLICTED,
        AssertionStatus.REFUTED,
        AssertionStatus.SUPERSEDED,
    }
    changed = True
    while changed:
        changed = False
        for assertion_id, assertion in tuple(result.items()):
            if assertion.status is not AssertionStatus.ACTIVE:
                continue
            if any(result[dependency_id].status in bad for dependency_id in assertion.depends_on_assertion_ids):
                result[assertion_id] = replace(
                    assertion, status=AssertionStatus.STALE
                )
                changed = True
    return result


def _block_invalid_commitments(
    commitments: dict[str, CommitmentState],
    assertions: dict[str, Assertion],
) -> dict[str, CommitmentState]:
    result = dict(commitments)
    terminal = {CommitmentStatus.SATISFIED, CommitmentStatus.ABANDONED}
    acceptable_assertions = {AssertionStatus.ACTIVE}
    changed = True
    while changed:
        changed = False
        for commitment_id, commitment in tuple(result.items()):
            if commitment.status in terminal:
                continue
            assertion_blocked = any(
                assertions[assertion_id].status not in acceptable_assertions
                for assertion_id in commitment.precondition_assertion_ids
            )
            commitment_blocked = any(
                result[dependency_id].status
                in {CommitmentStatus.BLOCKED, CommitmentStatus.ABANDONED}
                for dependency_id in commitment.depends_on_commitment_ids
            )
            if (assertion_blocked or commitment_blocked) and (
                commitment.status is not CommitmentStatus.BLOCKED
            ):
                result[commitment_id] = replace(
                    commitment, status=CommitmentStatus.BLOCKED
                )
                changed = True
    return result
