"""Matched-information representation arms for Batch-2A development checks."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Protocol

from aac.persistent_task_state import (
    Assertion,
    AssertionStatus,
    CommitmentState,
    CommitmentStatus,
    DecisionRecord,
    EntityState,
    EpistemicClass,
    StateOverflowError,
    StatePatchCandidate,
    StateValidationError,
    TaskStateReducer,
    TaskStateSnapshot,
)
from experiments.r_state_credit_1.contracts import (
    ArmId,
    ArmInput,
    ArmOutput,
    ArmResourceReceipt,
    ContractViolation,
    EventKind,
    EvidenceStatus,
    ExecutionStatus,
    ObservableEvent,
    ProbeAction,
    RetrievalQuery,
    RetrievalRequest,
    canonical_json,
    deterministic_token_proxy,
    sha256_digest,
)


class ArmAdapter(Protocol):
    arm_id: ArmId

    def consume(self, arm_input: ArmInput) -> ArmOutput: ...


class A0FullLogArm:
    arm_id = ArmId.A0_FULL_LOG

    def consume(self, arm_input: ArmInput) -> ArmOutput:
        precheck = _precheck(self.arm_id, arm_input)
        if precheck is not None:
            return precheck
        representation = arm_input.canonical_observable_json()
        if len(representation.encode("utf-8")) > arm_input.budget.max_representation_bytes:
            return _output(
                self.arm_id,
                arm_input,
                representation="",
                status=ExecutionStatus.INPUT_BUDGET_EXCEEDED,
            )
        return _output(self.arm_id, arm_input, representation=representation)


class A1RollingSummaryArm:
    arm_id = ArmId.A1_ROLLING_SUMMARY

    def consume(self, arm_input: ArmInput) -> ArmOutput:
        precheck = _precheck(self.arm_id, arm_input)
        if precheck is not None:
            return precheck
        kind_counts = {
            kind.value: sum(
                event.kind is kind for event in arm_input.observable_events
            )
            for kind in EventKind
        }
        recent_events: list[dict[str, object]] = []
        compacted_event_count = 0
        compacted_prefix_digest = sha256_digest(())

        def render() -> str:
            return canonical_json(
                {
                    "compacted_event_count": compacted_event_count,
                    "compacted_prefix_digest": compacted_prefix_digest,
                    "event_count": len(arm_input.observable_events),
                    "kind_counts": kind_counts,
                    "last_event_digest": (
                        sha256_digest(arm_input.observable_events[-1])
                        if arm_input.observable_events
                        else sha256_digest(())
                    ),
                    "last_sequence": arm_input.visible_through_sequence,
                    "observable_digest": arm_input.observable_digest(),
                    "recent_events": recent_events,
                    "scenario_id": arm_input.scenario_id,
                }
            )

        for event in arm_input.observable_events:
            recent_events.append(_summary_event(event))
            representation = render()
            while (
                len(representation.encode("utf-8"))
                > arm_input.budget.max_representation_bytes
                and recent_events
            ):
                evicted = recent_events.pop(0)
                compacted_event_count += 1
                compacted_prefix_digest = sha256_digest(
                    (compacted_prefix_digest, evicted)
                )
                representation = render()
        representation = render()
        if len(representation.encode("utf-8")) > arm_input.budget.max_representation_bytes:
            return _output(
                self.arm_id,
                arm_input,
                representation="",
                status=ExecutionStatus.INPUT_BUDGET_EXCEEDED,
            )
        return _output(self.arm_id, arm_input, representation=representation)


def _summary_event(event: ObservableEvent) -> dict[str, object]:
    return {
        "action_ref": event.action_ref,
        "depends_on_event_ids": event.depends_on_event_ids,
        "kind": event.kind,
        "object_version": event.object_version,
        "predicate": event.predicate,
        "related_ref": event.related_ref,
        "sequence": event.sequence,
        "subject_ref": event.subject_ref,
        "supersedes_event_id": event.supersedes_event_id,
        "target_event_ids": event.target_event_ids,
        "value": event.value,
    }


class A2FrozenRetrievalArm:
    arm_id = ArmId.A2_FROZEN_RETRIEVAL

    def __init__(self, request: RetrievalRequest) -> None:
        if not isinstance(request, RetrievalRequest):
            raise ContractViolation("A2 requires a typed RetrievalRequest")
        self._request = request

    def consume(self, arm_input: ArmInput) -> ArmOutput:
        precheck = _precheck(self.arm_id, arm_input, tool_calls=1)
        if precheck is not None:
            return precheck
        selected = _retrieve(self._request.query, arm_input.observable_events)
        representation = canonical_json(selected)
        if len(representation.encode("utf-8")) > arm_input.budget.max_representation_bytes:
            return _output(
                self.arm_id,
                arm_input,
                representation="",
                status=ExecutionStatus.INPUT_BUDGET_EXCEEDED,
                tool_calls=1,
            )
        return _output(
            self.arm_id,
            arm_input,
            representation=representation,
            tool_calls=1,
            omitted_event_count=len(arm_input.observable_events) - len(selected),
        )


class A3TypedStateArm:
    arm_id = ArmId.A3_TYPED_STATE

    def consume(self, arm_input: ArmInput) -> ArmOutput:
        precheck = _precheck(self.arm_id, arm_input)
        if precheck is not None:
            return precheck
        try:
            snapshot = _compile_visible_state(arm_input)
            projection = TaskStateReducer.project(
                snapshot,
                max_records=max(1, arm_input.budget.max_steps * 4),
                max_bytes=arm_input.budget.max_representation_bytes,
            )
        except StateOverflowError:
            return _output(
                self.arm_id,
                arm_input,
                representation="",
                status=ExecutionStatus.STATE_OVERFLOW,
            )
        except StateValidationError as exc:
            raise ContractViolation(
                f"A3_VISIBLE_COMPILATION_ERROR: {exc}"
            ) from exc
        representation = canonical_json(
            {
                "projection": projection,
                "recovery_directive": TaskStateReducer.recovery_directive(
                    snapshot
                ),
            }
        )
        if len(representation.encode("utf-8")) > arm_input.budget.max_representation_bytes:
            return _output(
                self.arm_id,
                arm_input,
                representation="",
                status=ExecutionStatus.STATE_OVERFLOW,
            )
        return _output(self.arm_id, arm_input, representation=representation)


def _retrieve(
    query: RetrievalQuery,
    events: tuple[ObservableEvent, ...],
) -> tuple[ObservableEvent, ...]:
    if query is RetrievalQuery.ALL_EVENTS:
        return events
    if query is RetrievalQuery.LATEST_EVENT:
        return events[-1:] if events else ()
    if query is RetrievalQuery.ASSERTION_EVENTS:
        return tuple(
            event
            for event in events
            if event.kind
            in {EventKind.ASSERTION_OBSERVED, EventKind.ASSERTION_REFUTED}
        )
    if query is RetrievalQuery.RECOVERY_EVENTS:
        return tuple(
            event
            for event in events
            if event.kind
            in {
                EventKind.ACTION_DISPATCHED,
                EventKind.ACTION_EFFECT_OBSERVED,
                EventKind.INTERRUPTION_OBSERVED,
                EventKind.RECOVERY_REQUESTED,
            }
        )
    raise ContractViolation("unsupported frozen retrieval query")


def _precheck(
    arm_id: ArmId,
    arm_input: ArmInput,
    *,
    tool_calls: int = 0,
) -> ArmOutput | None:
    if not isinstance(arm_input, ArmInput):
        raise ContractViolation("arm requires typed ArmInput")
    input_bytes = len(arm_input.canonical_observable_json().encode("utf-8"))
    if input_bytes > arm_input.budget.max_observable_bytes:
        return _output(
            arm_id,
            arm_input,
            representation="",
            status=ExecutionStatus.INPUT_BUDGET_EXCEEDED,
            tool_calls=tool_calls,
        )
    steps = len(arm_input.observable_events)
    wall_clock_units = steps + tool_calls
    if (
        steps > arm_input.budget.max_steps
        or tool_calls > arm_input.budget.max_tool_calls
        or wall_clock_units > arm_input.budget.max_wall_clock_units
    ):
        return _output(
            arm_id,
            arm_input,
            representation="",
            status=ExecutionStatus.RESOURCE_BUDGET_EXCEEDED,
            tool_calls=tool_calls,
        )
    return None


def _output(
    arm_id: ArmId,
    arm_input: ArmInput,
    *,
    representation: str,
    status: ExecutionStatus = ExecutionStatus.OK,
    tool_calls: int = 0,
    omitted_event_count: int = 0,
) -> ArmOutput:
    input_bytes = len(arm_input.canonical_observable_json().encode("utf-8"))
    output_bytes = len(representation.encode("utf-8"))
    receipt = ArmResourceReceipt(
        arm_id=arm_id,
        scenario_id=arm_input.scenario_id,
        evidence_status=EvidenceStatus.NOT_EVIDENCE,
        status=status,
        observable_digest=arm_input.observable_digest(),
        representation_digest=sha256_digest(representation),
        input_bytes=input_bytes,
        input_token_proxy=deterministic_token_proxy(input_bytes),
        output_bytes=output_bytes,
        output_token_proxy=deterministic_token_proxy(output_bytes),
        steps=len(arm_input.observable_events),
        tool_calls=tool_calls,
        wall_clock_units=len(arm_input.observable_events) + tool_calls,
        omitted_event_count=omitted_event_count,
    )
    return ArmOutput(
        arm_id=arm_id,
        scenario_id=arm_input.scenario_id,
        representation=representation,
        probe_action=_probe_action(arm_input.observable_events),
        receipt=receipt,
    )


def _probe_action(events: tuple[ObservableEvent, ...]) -> ProbeAction:
    if not events:
        return ProbeAction.ABSTAIN
    if events[-1].kind is EventKind.RECOVERY_REQUESTED:
        return ProbeAction.VERIFY_EFFECT
    if events[-1].kind is EventKind.ASSERTION_REFUTED:
        return ProbeAction.REVIEW
    return ProbeAction.CONTINUE


def _compile_visible_state(arm_input: ArmInput) -> TaskStateSnapshot:
    snapshot = TaskStateReducer.empty(arm_input.scenario_id)
    alias_map, alias_groups = _visible_aliases(arm_input.observable_events)
    assertion_ids: dict[str, str] = {}
    commitment_ids: dict[str, str] = {}
    decisions_by_action: dict[str, str] = {}
    for event in arm_input.observable_events:
        if event.kind is EventKind.ENTITY_OBSERVED:
            visible_root = alias_map.get(event.subject_ref, event.subject_ref)
            entity_id = _visible_entity_id(visible_root)
            current = next(
                (
                    entity
                    for entity in snapshot.entities
                    if entity.entity_id == entity_id
                ),
                None,
            )
            entity = EntityState(
                entity_id=entity_id,
                kind="visible_observed_entity",
                object_version=event.object_version or "visible:unknown-version",
                revision=1 if current is None else current.revision + 1,
                observed_keys=(event.subject_ref,),
                aliases=alias_groups.get(visible_root, (event.subject_ref,)),
                evidence_refs=event.evidence_refs,
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="entity",
                entities=(entity,),
            )
            continue
        if event.kind is EventKind.ALIAS_OBSERVED:
            continue
        if event.kind is EventKind.ASSERTION_OBSERVED:
            visible_root = alias_map.get(event.subject_ref, event.subject_ref)
            entity_id = _visible_entity_id(visible_root)
            entity = next(
                (
                    candidate
                    for candidate in snapshot.entities
                    if candidate.entity_id == entity_id
                ),
                None,
            )
            if entity is None:
                raise StateValidationError(
                    f"assertion lacks visible entity event: {event.event_id}"
                )
            assertion_id = f"visible-assertion:{event.event_id}"
            assertion_ids[event.event_id] = assertion_id
            assertion = Assertion(
                assertion_id=assertion_id,
                entity_id=entity_id,
                entity_version=event.object_version or entity.object_version,
                predicate=event.predicate or "visible:unknown-predicate",
                value=event.value or "visible:unknown-value",
                epistemic_class=EpistemicClass.UNIDENTIFIED,
                confidence=1.0,
                status=AssertionStatus.ACTIVE,
                valid_from=event.valid_from or event.observed_at,
                valid_to=event.valid_to,
                transaction_time=event.observed_at,
                evidence_refs=event.evidence_refs,
                provenance_refs=(event.event_id,),
                depends_on_assertion_ids=tuple(
                    assertion_ids[item]
                    for item in event.depends_on_event_ids
                ),
                supersedes_assertion_id=(
                    assertion_ids[event.supersedes_event_id]
                    if event.supersedes_event_id is not None
                    else None
                ),
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="assertion",
                assertions=(assertion,),
            )
            continue
        if event.kind is EventKind.ASSERTION_REFUTED:
            snapshot = _apply(
                snapshot,
                event,
                suffix="refute",
                refute_assertion_ids=tuple(
                    assertion_ids[item] for item in event.target_event_ids
                ),
            )
            continue
        if event.kind is EventKind.COMMITMENT_OBSERVED:
            commitment_id = f"visible-commitment:{event.event_id}"
            commitment_ids[event.event_id] = commitment_id
            commitment = CommitmentState(
                commitment_id=commitment_id,
                revision=1,
                deliverable=event.value or event.subject_ref,
                status=CommitmentStatus.PENDING,
                precondition_assertion_ids=tuple(
                    assertion_ids[item] for item in event.target_event_ids
                ),
                postconditions=(f"visible:postcondition:{event.event_id}",),
                evidence_requirements=(
                    event.evidence_refs or (f"visible:evidence:{event.event_id}",)
                ),
                depends_on_commitment_ids=tuple(
                    commitment_ids[item]
                    for item in event.depends_on_event_ids
                ),
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="commitment",
                commitments=(commitment,),
            )
            continue
        if event.kind is EventKind.ACTION_DISPATCHED:
            action_ref = event.action_ref or "visible:unknown-action"
            decision_id = f"visible-decision:{event.event_id}"
            decisions_by_action[action_ref] = decision_id
            decision = DecisionRecord(
                decision_id=decision_id,
                revision=1,
                state_snapshot_digest=snapshot.digest(),
                alternatives=(action_ref, "ABSTAIN"),
                selected_action=action_ref,
                relied_on_assertion_ids=(),
                predicted_postconditions=(
                    event.value or f"visible:effect:{action_ref}",
                ),
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="decision-record",
                decisions=(decision,),
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="decision-dispatch",
                decisions=(replace(decision, revision=2, dispatched=True),),
            )
            continue
        if event.kind is EventKind.ACTION_EFFECT_OBSERVED:
            action_ref = event.action_ref or "visible:unknown-action"
            decision_id = decisions_by_action[action_ref]
            decision = next(
                item for item in snapshot.decisions if item.decision_id == decision_id
            )
            snapshot = _apply(
                snapshot,
                event,
                suffix="decision-effect",
                decisions=(
                    replace(
                        decision,
                        revision=decision.revision + 1,
                        receipt_ref=event.receipt_ref,
                        effect_verified=True,
                    ),
                ),
            )
    return snapshot


def _apply(
    snapshot: TaskStateSnapshot,
    event: ObservableEvent,
    *,
    suffix: str,
    entities: tuple[EntityState, ...] = (),
    assertions: tuple[Assertion, ...] = (),
    commitments: tuple[CommitmentState, ...] = (),
    decisions: tuple[DecisionRecord, ...] = (),
    refute_assertion_ids: tuple[str, ...] = (),
) -> TaskStateSnapshot:
    patch = StatePatchCandidate(
        patch_id=f"visible-patch:{event.event_id}:{suffix}",
        task_id=snapshot.task_id,
        base_version=snapshot.version,
        base_digest=snapshot.digest(),
        transaction_time=event.observed_at,
        entities=entities,
        assertions=assertions,
        commitments=commitments,
        decisions=decisions,
        refute_assertion_ids=refute_assertion_ids,
    )
    return TaskStateReducer.apply(snapshot, patch)


def _visible_aliases(
    events: tuple[ObservableEvent, ...],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        parent[high] = low

    for event in events:
        find(event.subject_ref)
        if event.kind is EventKind.ALIAS_OBSERVED and event.related_ref is not None:
            union(event.subject_ref, event.related_ref)
    groups: dict[str, list[str]] = {}
    for value in sorted(parent):
        groups.setdefault(find(value), []).append(value)
    alias_map = {
        value: root for root, values in groups.items() for value in values
    }
    alias_groups = {
        root: tuple(values) for root, values in groups.items()
    }
    return alias_map, alias_groups


def _visible_entity_id(visible_root: str) -> str:
    digest = hashlib.sha256(visible_root.encode("utf-8")).hexdigest()[:16]
    return f"visible-entity:{digest}"
