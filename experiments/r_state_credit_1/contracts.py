"""Closed contracts for the R-STATE-CREDIT-1 Batch-2A environment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, TypeVar, cast


class ContractViolation(ValueError):
    """Raised when data attempts to cross a closed environment boundary."""


class ScenarioFamily(str, Enum):
    ALIAS_OBJECT_VERSION_DRIFT = "ALIAS_OBJECT_VERSION_DRIFT"
    VALID_TRANSACTION_TIME = "VALID_TRANSACTION_TIME"
    CONTRADICTION = "CONTRADICTION"
    SUPERSESSION_REFUTATION_CASCADE = "SUPERSESSION_REFUTATION_CASCADE"
    COMMITMENT_BLOCKAGE = "COMMITMENT_BLOCKAGE"
    DISPATCH_EFFECT_UNCERTAINTY = "DISPATCH_EFFECT_UNCERTAINTY"
    BOUNDED_OVERFLOW_RECOVERY = "BOUNDED_OVERFLOW_RECOVERY"


class EvidenceStatus(str, Enum):
    NOT_EVIDENCE = "NOT_EVIDENCE"


class EventKind(str, Enum):
    ENTITY_OBSERVED = "ENTITY_OBSERVED"
    ALIAS_OBSERVED = "ALIAS_OBSERVED"
    ASSERTION_OBSERVED = "ASSERTION_OBSERVED"
    ASSERTION_REFUTED = "ASSERTION_REFUTED"
    COMMITMENT_OBSERVED = "COMMITMENT_OBSERVED"
    ACTION_DISPATCHED = "ACTION_DISPATCHED"
    ACTION_EFFECT_OBSERVED = "ACTION_EFFECT_OBSERVED"
    INTERRUPTION_OBSERVED = "INTERRUPTION_OBSERVED"
    RECOVERY_REQUESTED = "RECOVERY_REQUESTED"


class ArmId(str, Enum):
    A0_FULL_LOG = "A0_FULL_LOG"
    A1_ROLLING_SUMMARY = "A1_ROLLING_SUMMARY"
    A2_FROZEN_RETRIEVAL = "A2_FROZEN_RETRIEVAL"
    A3_TYPED_STATE = "A3_TYPED_STATE"


class ExecutionStatus(str, Enum):
    OK = "OK"
    INPUT_BUDGET_EXCEEDED = "INPUT_BUDGET_EXCEEDED"
    RESOURCE_BUDGET_EXCEEDED = "RESOURCE_BUDGET_EXCEEDED"
    STATE_OVERFLOW = "STATE_OVERFLOW"


class ProbeAction(str, Enum):
    CONTINUE = "CONTINUE"
    REVIEW = "REVIEW"
    VERIFY_EFFECT = "VERIFY_EFFECT"
    ABSTAIN = "ABSTAIN"


class RetrievalQuery(str, Enum):
    ALL_EVENTS = "ALL_EVENTS"
    LATEST_EVENT = "LATEST_EVENT"
    ASSERTION_EVENTS = "ASSERTION_EVENTS"
    RECOVERY_EVENTS = "RECOVERY_EVENTS"


class QualificationCheck(str, Enum):
    REPLAY_DETERMINISM = "REPLAY_DETERMINISM"
    MATCHED_INFORMATION = "MATCHED_INFORMATION"
    RESOURCE_BUDGET = "RESOURCE_BUDGET"
    NO_HIDDEN_LEAK = "NO_HIDDEN_LEAK"
    CLOSED_INTERFACE = "CLOSED_INTERFACE"
    NONCONSTANT_BASELINES = "NONCONSTANT_BASELINES"


T = TypeVar("T", bound="ClosedContract")


class ClosedContract:
    """Construct a dataclass only from its exact declared field set."""

    @classmethod
    def from_mapping(cls: type[T], value: Mapping[str, Any]) -> T:
        expected = {field.name for field in fields(cast(Any, cls))}
        unknown = sorted(set(value).difference(expected))
        if unknown:
            raise ContractViolation(
                f"unknown field(s) for {cls.__name__}: {', '.join(unknown)}"
            )
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise ContractViolation(str(exc)) from exc


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be non-empty text")


def _require_optional_text(name: str, value: str | None) -> None:
    if value is not None:
        _require_text(name, value)


def _require_positive_int(name: str, value: int, *, allow_zero: bool = False) -> None:
    floor = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < floor:
        raise ContractViolation(f"{name} must be an integer >= {floor}")


def _require_datetime(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractViolation(f"{name} must be timezone-aware")


def _require_text_tuple(name: str, value: tuple[str, ...]) -> None:
    if not isinstance(value, tuple):
        raise ContractViolation(f"{name} must be a tuple")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractViolation(f"{name} must contain non-empty text")
    if len(value) != len(set(value)):
        raise ContractViolation(f"{name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ObservableEvent(ClosedContract):
    scenario_id: str
    sequence: int
    event_id: str
    observed_at: datetime
    kind: EventKind
    subject_ref: str
    related_ref: str | None = None
    object_version: str | None = None
    predicate: str | None = None
    value: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    depends_on_event_ids: tuple[str, ...] = ()
    target_event_ids: tuple[str, ...] = ()
    supersedes_event_id: str | None = None
    action_ref: str | None = None
    receipt_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("scenario_id", self.scenario_id)
        _require_positive_int("sequence", self.sequence)
        _require_text("event_id", self.event_id)
        _require_datetime("observed_at", self.observed_at)
        if not isinstance(self.kind, EventKind):
            raise ContractViolation("kind must be EventKind")
        _require_text("subject_ref", self.subject_ref)
        for name in (
            "related_ref",
            "object_version",
            "predicate",
            "value",
            "supersedes_event_id",
            "action_ref",
            "receipt_ref",
        ):
            _require_optional_text(name, getattr(self, name))
        for name in ("valid_from", "valid_to"):
            value = getattr(self, name)
            if value is not None:
                _require_datetime(name, value)
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ContractViolation("valid_to must be after valid_from")
        _require_text_tuple("depends_on_event_ids", self.depends_on_event_ids)
        _require_text_tuple("target_event_ids", self.target_event_ids)
        _require_text_tuple("evidence_refs", self.evidence_refs)
        if self.event_id in self.depends_on_event_ids:
            raise ContractViolation("event cannot depend on itself")
        if self.kind is EventKind.ENTITY_OBSERVED and self.object_version is None:
            raise ContractViolation("ENTITY_OBSERVED requires object_version")
        if self.kind is EventKind.ALIAS_OBSERVED and self.related_ref is None:
            raise ContractViolation("ALIAS_OBSERVED requires related_ref")
        if self.kind is EventKind.ASSERTION_OBSERVED and (
            self.predicate is None
            or self.value is None
            or self.valid_from is None
        ):
            raise ContractViolation(
                "ASSERTION_OBSERVED requires predicate, value, and valid_from"
            )
        if self.kind is EventKind.ASSERTION_REFUTED and not self.target_event_ids:
            raise ContractViolation("ASSERTION_REFUTED requires target_event_ids")
        if self.kind is EventKind.ACTION_DISPATCHED and self.action_ref is None:
            raise ContractViolation("ACTION_DISPATCHED requires action_ref")
        if self.kind is EventKind.ACTION_EFFECT_OBSERVED and (
            self.action_ref is None or self.receipt_ref is None
        ):
            raise ContractViolation(
                "ACTION_EFFECT_OBSERVED requires action_ref and receipt_ref"
            )


@dataclass(frozen=True, slots=True)
class ResourceBudget(ClosedContract):
    max_observable_bytes: int
    max_representation_bytes: int
    max_steps: int
    max_tool_calls: int
    max_wall_clock_units: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_observable_bytes",
            "max_representation_bytes",
            "max_steps",
            "max_tool_calls",
            "max_wall_clock_units",
        ):
            _require_positive_int(field_name, getattr(self, field_name))


@dataclass(frozen=True, slots=True)
class RetrievalRequest(ClosedContract):
    query: RetrievalQuery

    def __post_init__(self) -> None:
        if not isinstance(self.query, RetrievalQuery):
            raise ContractViolation("query must be RetrievalQuery")


@dataclass(frozen=True, slots=True)
class ArmResourceReceipt(ClosedContract):
    arm_id: ArmId
    scenario_id: str
    evidence_status: EvidenceStatus
    status: ExecutionStatus
    observable_digest: str
    representation_digest: str
    input_bytes: int
    input_token_proxy: int
    output_bytes: int
    output_token_proxy: int
    steps: int
    tool_calls: int
    wall_clock_units: int
    omitted_event_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, ArmId):
            raise ContractViolation("arm_id must be ArmId")
        _require_text("scenario_id", self.scenario_id)
        if self.evidence_status is not EvidenceStatus.NOT_EVIDENCE:
            raise ContractViolation("arm receipt must be NOT_EVIDENCE")
        if not isinstance(self.status, ExecutionStatus):
            raise ContractViolation("status must be ExecutionStatus")
        for name in ("observable_digest", "representation_digest"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ContractViolation(f"{name} must be a lowercase SHA-256 digest")
        for name in (
            "input_bytes",
            "input_token_proxy",
            "output_bytes",
            "output_token_proxy",
            "steps",
            "tool_calls",
            "wall_clock_units",
            "omitted_event_count",
        ):
            _require_positive_int(name, getattr(self, name), allow_zero=True)


@dataclass(frozen=True, slots=True)
class ArmOutput(ClosedContract):
    arm_id: ArmId
    scenario_id: str
    representation: str
    probe_action: ProbeAction
    receipt: ArmResourceReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, ArmId):
            raise ContractViolation("arm_id must be ArmId")
        _require_text("scenario_id", self.scenario_id)
        if not isinstance(self.representation, str):
            raise ContractViolation("representation must be text")
        if not isinstance(self.probe_action, ProbeAction):
            raise ContractViolation("probe_action must be ProbeAction")
        if not isinstance(self.receipt, ArmResourceReceipt):
            raise ContractViolation("receipt must be ArmResourceReceipt")
        if self.receipt.arm_id is not self.arm_id:
            raise ContractViolation("receipt arm_id does not match output")
        if self.receipt.scenario_id != self.scenario_id:
            raise ContractViolation("receipt scenario_id does not match output")
        output_bytes = len(self.representation.encode("utf-8"))
        if self.receipt.output_bytes != output_bytes:
            raise ContractViolation("receipt output_bytes does not match representation")
        if self.receipt.output_token_proxy != deterministic_token_proxy(output_bytes):
            raise ContractViolation(
                "receipt output_token_proxy does not match representation"
            )
        if self.receipt.representation_digest != sha256_digest(
            self.representation
        ):
            raise ContractViolation(
                "receipt representation_digest does not match representation"
            )


@dataclass(frozen=True, slots=True)
class QualificationReceipt(ClosedContract):
    qualification_id: str
    evidence_status: EvidenceStatus
    qualified: bool
    checks: tuple[QualificationCheck, ...]
    scenario_digests: tuple[str, ...]
    arm_ids: tuple[ArmId, ...]

    def __post_init__(self) -> None:
        if self.qualification_id != "R-STATE-CREDIT-1-BATCH-2A":
            raise ContractViolation("unexpected qualification_id")
        if self.evidence_status is not EvidenceStatus.NOT_EVIDENCE:
            raise ContractViolation("qualification receipt must be NOT_EVIDENCE")
        if not isinstance(self.qualified, bool):
            raise ContractViolation("qualified must be bool")
        if not isinstance(self.checks, tuple) or any(
            not isinstance(check, QualificationCheck) for check in self.checks
        ):
            raise ContractViolation("checks must be QualificationCheck tuple")
        if len(self.checks) != len(set(self.checks)):
            raise ContractViolation("checks must not contain duplicates")
        _require_text_tuple("scenario_digests", self.scenario_digests)
        for digest in self.scenario_digests:
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ContractViolation(
                    "scenario_digests must contain SHA-256 digests"
                )
        if not isinstance(self.arm_ids, tuple) or any(
            not isinstance(arm_id, ArmId) for arm_id in self.arm_ids
        ):
            raise ContractViolation("arm_ids must be ArmId tuple")
        if len(self.arm_ids) != len(set(self.arm_ids)):
            raise ContractViolation("arm_ids must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ArmInput(ClosedContract):
    scenario_id: str
    observable_events: tuple[ObservableEvent, ...]
    visible_through_sequence: int
    budget: ResourceBudget

    def __post_init__(self) -> None:
        _require_text("scenario_id", self.scenario_id)
        if not isinstance(self.observable_events, tuple) or any(
            not isinstance(event, ObservableEvent) for event in self.observable_events
        ):
            raise ContractViolation(
                "observable_events must be a tuple of ObservableEvent"
            )
        _require_positive_int(
            "visible_through_sequence",
            self.visible_through_sequence,
            allow_zero=True,
        )
        if not isinstance(self.budget, ResourceBudget):
            raise ContractViolation("budget must be ResourceBudget")
        if any(event.scenario_id != self.scenario_id for event in self.observable_events):
            raise ContractViolation("event scenario_id does not match ArmInput")
        sequences = tuple(event.sequence for event in self.observable_events)
        expected = tuple(range(1, len(self.observable_events) + 1))
        if sequences != expected:
            raise ContractViolation("RAGGED_EVENT_FEED: sequences must be contiguous")
        event_ids = tuple(event.event_id for event in self.observable_events)
        if len(event_ids) != len(set(event_ids)):
            raise ContractViolation("RAGGED_EVENT_FEED: duplicate event_id")
        seen_event_ids: set[str] = set()
        for event in self.observable_events:
            references = (
                event.depends_on_event_ids
                + event.target_event_ids
                + (
                    (event.supersedes_event_id,)
                    if event.supersedes_event_id is not None
                    else ()
                )
            )
            if any(reference not in seen_event_ids for reference in references):
                raise ContractViolation(
                    "FUTURE_EVENT_LEAK: event references unseen event"
                )
            seen_event_ids.add(event.event_id)
        if any(
            sequence > self.visible_through_sequence for sequence in sequences
        ):
            raise ContractViolation(
                "FUTURE_EVENT_LEAK: event exceeds visible sequence boundary"
            )
        if sequences and sequences[-1] != self.visible_through_sequence:
            raise ContractViolation(
                "RAGGED_EVENT_FEED: visible sequence has a missing event"
            )
        if not sequences and self.visible_through_sequence != 0:
            raise ContractViolation(
                "RAGGED_EVENT_FEED: empty feed must have visible sequence zero"
            )

    def canonical_observable_json(self) -> str:
        return canonical_json(self.observable_events)

    def observable_digest(self) -> str:
        return sha256_digest(self.observable_events)


@dataclass(frozen=True, slots=True)
class ScenarioFixture(ClosedContract):
    scenario_id: str
    family: ScenarioFamily
    evidence_status: EvidenceStatus
    observable_events: tuple[ObservableEvent, ...]
    hidden_entity_key: str
    oracle_label: str
    oracle_reason: str
    expected_outcome: str

    def __post_init__(self) -> None:
        _require_text("scenario_id", self.scenario_id)
        if not isinstance(self.family, ScenarioFamily):
            raise ContractViolation("family must be ScenarioFamily")
        if self.evidence_status is not EvidenceStatus.NOT_EVIDENCE:
            raise ContractViolation("scenario fixture must be NOT_EVIDENCE")
        for name in (
            "hidden_entity_key",
            "oracle_label",
            "oracle_reason",
            "expected_outcome",
        ):
            _require_text(name, getattr(self, name))
        actor_input = ArmInput(
            scenario_id=self.scenario_id,
            observable_events=self.observable_events,
            visible_through_sequence=len(self.observable_events),
            budget=ResourceBudget(
                max_observable_bytes=2**31 - 1,
                max_representation_bytes=2**31 - 1,
                max_steps=2**31 - 1,
                max_tool_calls=2**31 - 1,
                max_wall_clock_units=2**31 - 1,
            ),
        )
        rendered = actor_input.canonical_observable_json()
        for secret in (
            self.hidden_entity_key,
            self.oracle_label,
            self.oracle_reason,
            self.expected_outcome,
        ):
            if secret in rendered:
                raise ContractViolation(
                    "HIDDEN_REFEREE_LEAK: actor-visible event contains hidden truth"
                )

    def actor_input(
        self,
        *,
        budget: ResourceBudget,
        visible_through_sequence: int | None = None,
    ) -> ArmInput:
        through = (
            len(self.observable_events)
            if visible_through_sequence is None
            else visible_through_sequence
        )
        if not isinstance(through, int) or isinstance(through, bool):
            raise ContractViolation("visible_through_sequence must be an integer")
        if not 0 <= through <= len(self.observable_events):
            raise ContractViolation("visible_through_sequence outside fixture")
        return ArmInput(
            scenario_id=self.scenario_id,
            observable_events=self.observable_events[:through],
            visible_through_sequence=through,
            budget=budget,
        )

    def digest(self) -> str:
        return sha256_digest(self)


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field.name: _canonical(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_token_proxy(byte_count: int) -> int:
    _require_positive_int("byte_count", byte_count, allow_zero=True)
    return (byte_count + 3) // 4
