"""Batch-2A hermetic development-environment guards.

These tests qualify development plumbing only. They do not run Stage A, compare
arm performance, generate a winner, or create research evidence.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from experiments.r_state_credit_1.contracts import (
    ArmId,
    ArmInput,
    ArmOutput,
    ContractViolation,
    EventKind,
    EvidenceStatus,
    ExecutionStatus,
    ObservableEvent,
    ProbeAction,
    QualificationCheck,
    RetrievalQuery,
    RetrievalRequest,
    ResourceBudget,
    ScenarioFamily,
    ScenarioFixture,
    deterministic_token_proxy,
    sha256_digest,
)
from experiments.r_state_credit_1.arms import (
    A0FullLogArm,
    A1RollingSummaryArm,
    A2FrozenRetrievalArm,
    A3TypedStateArm,
)
from experiments.r_state_credit_1.scenarios import build_development_fixtures
from experiments.r_state_credit_1.qualifier import (
    QualificationError,
    qualify_development_environment,
)


NOW = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def _budget(
    *,
    max_observable_bytes: int = 100_000,
    max_representation_bytes: int = 100_000,
) -> ResourceBudget:
    return ResourceBudget(
        max_observable_bytes=max_observable_bytes,
        max_representation_bytes=max_representation_bytes,
        max_steps=256,
        max_tool_calls=8,
        max_wall_clock_units=512,
    )


def _event(
    sequence: int,
    *,
    scenario_id: str = "scenario:test",
    event_id: str | None = None,
    kind: EventKind = EventKind.ENTITY_OBSERVED,
    subject_ref: str = "visible:client",
) -> ObservableEvent:
    return ObservableEvent(
        scenario_id=scenario_id,
        sequence=sequence,
        event_id=event_id or f"event:{sequence}",
        observed_at=NOW + timedelta(minutes=sequence),
        kind=kind,
        subject_ref=subject_ref,
        object_version="v1",
        evidence_refs=(f"visible:evidence:{sequence}",),
    )


def test_observable_event_contract_rejects_oracle_fields() -> None:
    with pytest.raises(ContractViolation, match="unknown field.*oracle_reason"):
        ObservableEvent.from_mapping(
            {
                "scenario_id": "scenario:test",
                "sequence": 1,
                "event_id": "event:1",
                "observed_at": NOW,
                "kind": EventKind.ENTITY_OBSERVED,
                "subject_ref": "visible:client",
                "oracle_reason": "hidden answer",
            }
        )


def test_arm_input_rejects_future_event_leak() -> None:
    with pytest.raises(ContractViolation, match="FUTURE_EVENT_LEAK"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(_event(1), _event(2)),
            visible_through_sequence=1,
            budget=_budget(),
        )


def test_arm_input_rejects_future_event_reference_leak() -> None:
    leaking = replace(
        _event(1),
        depends_on_event_ids=("event:2",),
    )

    with pytest.raises(ContractViolation, match="FUTURE_EVENT_LEAK"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(leaking,),
            visible_through_sequence=1,
            budget=_budget(),
        )


def test_arm_input_rejects_assertion_dependency_on_entity_event() -> None:
    entity = _event(1)
    assertion = replace(
        _event(2),
        kind=EventKind.ASSERTION_OBSERVED,
        predicate="visible:status",
        value="ready",
        valid_from=NOW,
        depends_on_event_ids=(entity.event_id,),
    )

    with pytest.raises(ContractViolation, match="REFERENCE_KIND_MISMATCH"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(entity, assertion),
            visible_through_sequence=2,
            budget=_budget(),
        )


def test_arm_input_rejects_assertion_superseding_entity_event() -> None:
    entity = _event(1)
    assertion = replace(
        _event(2),
        kind=EventKind.ASSERTION_OBSERVED,
        predicate="visible:status",
        value="ready",
        valid_from=NOW,
        supersedes_event_id=entity.event_id,
    )

    with pytest.raises(ContractViolation, match="REFERENCE_KIND_MISMATCH"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(entity, assertion),
            visible_through_sequence=2,
            budget=_budget(),
        )


def test_arm_input_rejects_commitment_targeting_non_assertion_event() -> None:
    entity = _event(1)
    commitment = replace(
        _event(2),
        kind=EventKind.COMMITMENT_OBSERVED,
        value="visible:deliverable",
        target_event_ids=(entity.event_id,),
    )

    with pytest.raises(ContractViolation, match="REFERENCE_KIND_MISMATCH"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(entity, commitment),
            visible_through_sequence=2,
            budget=_budget(),
        )


def test_arm_input_rejects_effect_linked_to_non_dispatch_event() -> None:
    non_dispatch = replace(_event(1), action_ref="visible:deploy")
    effect = replace(
        _event(2),
        kind=EventKind.ACTION_EFFECT_OBSERVED,
        action_ref="visible:deploy",
        receipt_ref="visible:receipt",
    )

    with pytest.raises(ContractViolation, match="REFERENCE_KIND_MISMATCH"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(non_dispatch, effect),
            visible_through_sequence=2,
            budget=_budget(),
        )


def test_arm_input_rejects_ragged_event_feed() -> None:
    with pytest.raises(ContractViolation, match="RAGGED_EVENT_FEED"):
        ArmInput(
            scenario_id="scenario:test",
            observable_events=(_event(1), _event(3)),
            visible_through_sequence=3,
            budget=_budget(),
        )


def test_hidden_referee_key_cannot_enter_actor_visible_event() -> None:
    hidden_key = "hidden:canonical-client-42"
    with pytest.raises(ContractViolation, match="HIDDEN_REFEREE_LEAK"):
        ScenarioFixture(
            scenario_id="scenario:test",
            family=ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT,
            evidence_status=EvidenceStatus.NOT_EVIDENCE,
            observable_events=(_event(1, subject_ref=hidden_key),),
            hidden_entity_key=hidden_key,
            oracle_label="TRACK_SAME_ENTITY",
            oracle_reason="same object behind two visible aliases",
            expected_outcome="preserve identity across v1 to v2",
        )


def test_seven_scenario_families_are_deterministic_not_evidence_fixtures() -> None:
    first = build_development_fixtures()
    second = build_development_fixtures()

    assert first == second
    assert len(first) == 7
    assert {fixture.family for fixture in first} == set(ScenarioFamily)
    assert all(
        fixture.evidence_status is EvidenceStatus.NOT_EVIDENCE
        for fixture in first
    )
    assert all(fixture.observable_events for fixture in first)
    assert len({fixture.digest() for fixture in first}) == 7


def test_fixture_exposes_only_prefix_bound_actor_input() -> None:
    fixture = build_development_fixtures()[0]
    actor_input = fixture.actor_input(
        budget=_budget(),
        visible_through_sequence=2,
    )

    assert actor_input.observable_events == fixture.observable_events[:2]
    assert actor_input.visible_through_sequence == 2
    rendered = actor_input.canonical_observable_json()
    assert fixture.hidden_entity_key not in rendered
    assert fixture.oracle_label not in rendered
    assert fixture.oracle_reason not in rendered


def test_all_arms_receive_identical_observable_feed_and_resource_schema() -> None:
    fixture = next(
        item
        for item in build_development_fixtures()
        if item.family is ScenarioFamily.CONTRADICTION
    )
    arm_input = fixture.actor_input(budget=_budget())
    arms = (
        A0FullLogArm(),
        A1RollingSummaryArm(),
        A2FrozenRetrievalArm(
            RetrievalRequest(query=RetrievalQuery.ASSERTION_EVENTS)
        ),
        A3TypedStateArm(),
    )

    outputs = tuple(arm.consume(arm_input) for arm in arms)

    assert {output.arm_id for output in outputs} == set(ArmId)
    assert {output.receipt.observable_digest for output in outputs} == {
        arm_input.observable_digest()
    }
    assert {output.receipt.input_bytes for output in outputs} == {
        len(arm_input.canonical_observable_json().encode("utf-8"))
    }
    assert all(
        output.receipt.evidence_status is EvidenceStatus.NOT_EVIDENCE
        and output.receipt.status is ExecutionStatus.OK
        for output in outputs
    )
    receipt_mapping = {
        field.name: getattr(outputs[0].receipt, field.name)
        for field in fields(outputs[0].receipt)
    }
    receipt_mapping["winner"] = ArmId.A3_TYPED_STATE
    with pytest.raises(ContractViolation, match="unknown field.*winner"):
        type(outputs[0].receipt).from_mapping(receipt_mapping)


def test_a0_is_exact_full_log_and_fails_instead_of_truncating() -> None:
    fixture = build_development_fixtures()[0]
    arm = A0FullLogArm()
    generous_input = fixture.actor_input(budget=_budget())
    exact = arm.consume(generous_input)

    assert exact.representation == generous_input.canonical_observable_json()
    assert exact.receipt.output_bytes == len(
        exact.representation.encode("utf-8")
    )

    constrained = fixture.actor_input(
        budget=_budget(
            max_representation_bytes=exact.receipt.output_bytes - 1
        )
    )
    rejected = arm.consume(constrained)

    assert rejected.receipt.status is ExecutionStatus.INPUT_BUDGET_EXCEEDED
    assert rejected.representation == ""
    assert rejected.receipt.omitted_event_count == 0


def test_a1_summary_has_hard_bound_and_covers_entire_feed_by_digest() -> None:
    scenario_id = "scenario:summary-growth"
    events = tuple(
        _event(
            sequence,
            scenario_id=scenario_id,
            event_id=f"event:{sequence:04d}",
            subject_ref=f"visible:entity:{sequence:04d}",
        )
        for sequence in range(1, 201)
    )
    arm_input = ArmInput(
        scenario_id=scenario_id,
        observable_events=events,
        visible_through_sequence=len(events),
        budget=_budget(
            max_observable_bytes=2_000_000,
            max_representation_bytes=1_024,
        ),
    )

    output = A1RollingSummaryArm().consume(arm_input)
    summary = json.loads(output.representation)

    assert output.receipt.status is ExecutionStatus.OK
    assert output.receipt.output_bytes <= 1_024
    assert summary["event_count"] == 200
    assert summary["observable_digest"] == arm_input.observable_digest()
    assert summary["last_sequence"] == 200
    assert summary["compacted_event_count"] > 0
    assert summary["compacted_prefix_digest"] != sha256_digest(())
    assert summary["recent_events"]
    assert summary["recent_events"][-1]["sequence"] == 200


def test_a2_retrieval_accepts_only_frozen_query_enum() -> None:
    with pytest.raises(ContractViolation, match="query must be RetrievalQuery"):
        RetrievalRequest(query="ORACLE_REASON")  # type: ignore[arg-type]

    fixture = next(
        item
        for item in build_development_fixtures()
        if item.family is ScenarioFamily.CONTRADICTION
    )
    arm_input = fixture.actor_input(budget=_budget())
    output = A2FrozenRetrievalArm(
        RetrievalRequest(query=RetrievalQuery.ASSERTION_EVENTS)
    ).consume(arm_input)
    retrieved = json.loads(output.representation)

    assert len(retrieved) == 2
    assert {item["kind"] for item in retrieved} == {
        EventKind.ASSERTION_OBSERVED.value
    }


def test_a3_uses_visible_state_only_and_surfaces_protected_overflow() -> None:
    fixtures = build_development_fixtures()
    contradiction = next(
        item
        for item in fixtures
        if item.family is ScenarioFamily.CONTRADICTION
    )
    typed = A3TypedStateArm().consume(
        contradiction.actor_input(budget=_budget())
    )

    assert typed.receipt.status is ExecutionStatus.OK
    assert "CONFLICTED" in typed.representation
    assert '"epistemic_class":"UNIDENTIFIED"' in typed.representation
    assert '"epistemic_class":"FACT"' not in typed.representation
    assert contradiction.hidden_entity_key not in typed.representation
    assert contradiction.oracle_label not in typed.representation
    assert contradiction.oracle_reason not in typed.representation

    overflow = next(
        item
        for item in fixtures
        if item.family is ScenarioFamily.BOUNDED_OVERFLOW_RECOVERY
    )
    rejected = A3TypedStateArm().consume(
        overflow.actor_input(
            budget=_budget(max_representation_bytes=256)
        )
    )

    assert rejected.receipt.status is ExecutionStatus.STATE_OVERFLOW
    assert rejected.representation == ""
    assert rejected.receipt.omitted_event_count == 0


def _qualified_arms():
    return (
        A0FullLogArm(),
        A1RollingSummaryArm(),
        A2FrozenRetrievalArm(
            RetrievalRequest(query=RetrievalQuery.ASSERTION_EVENTS)
        ),
        A3TypedStateArm(),
    )


def _mutate_output(
    output: ArmOutput,
    *,
    representation: str | None = None,
    probe_action: ProbeAction | None = None,
) -> ArmOutput:
    rendered = output.representation if representation is None else representation
    output_bytes = len(rendered.encode("utf-8"))
    receipt = replace(
        output.receipt,
        representation_digest=sha256_digest(rendered),
        output_bytes=output_bytes,
        output_token_proxy=deterministic_token_proxy(output_bytes),
    )
    return ArmOutput(
        arm_id=output.arm_id,
        scenario_id=output.scenario_id,
        representation=rendered,
        probe_action=(
            output.probe_action if probe_action is None else probe_action
        ),
        receipt=receipt,
    )


class _MutatingArm:
    def __init__(self, base, mutation) -> None:
        self.arm_id = base.arm_id
        self._base = base
        self._mutation = mutation

    def consume(self, arm_input: ArmInput) -> ArmOutput:
        return self._mutation(self._base.consume(arm_input), arm_input)


def test_qualifier_is_deterministic_and_contains_no_winner_or_statistics() -> None:
    fixtures = build_development_fixtures()
    arms = _qualified_arms()

    first = qualify_development_environment(fixtures, arms, _budget())
    second = qualify_development_environment(fixtures, arms, _budget())

    assert first == second
    assert first.evidence_status is EvidenceStatus.NOT_EVIDENCE
    assert first.qualified is True
    assert set(first.checks) == set(QualificationCheck)
    assert not hasattr(first, "winner")
    assert not hasattr(first, "p_value")
    assert not hasattr(first, "effect_size")


def test_qualifier_rejects_weakened_full_log_baseline() -> None:
    weakened = _MutatingArm(
        A0FullLogArm(),
        lambda output, _arm_input: _mutate_output(
            output,
            representation=output.representation[:-1],
        ),
    )
    arms = (weakened,) + _qualified_arms()[1:]

    with pytest.raises(QualificationError, match="A0_FULL_LOG_WEAKENED"):
        qualify_development_environment(
            build_development_fixtures(), arms, _budget()
        )


def test_qualifier_rejects_a3_hidden_referee_output() -> None:
    fixtures = build_development_fixtures()
    hidden_by_scenario = {
        fixture.scenario_id: fixture.hidden_entity_key for fixture in fixtures
    }
    leaking = _MutatingArm(
        A3TypedStateArm(),
        lambda output, arm_input: _mutate_output(
            output,
            representation=(
                output.representation + hidden_by_scenario[arm_input.scenario_id]
            ),
        ),
    )
    arms = _qualified_arms()[:3] + (leaking,)

    with pytest.raises(QualificationError, match="HIDDEN_REFEREE_LEAK"):
        qualify_development_environment(fixtures, arms, _budget())


def test_qualifier_rejects_constant_probe_action() -> None:
    constant = _MutatingArm(
        A1RollingSummaryArm(),
        lambda output, _arm_input: _mutate_output(
            output,
            probe_action=ProbeAction.CONTINUE,
        ),
    )
    arms = (A0FullLogArm(), constant) + _qualified_arms()[2:]

    with pytest.raises(QualificationError, match="CONSTANT_PROBE_ACTION"):
        qualify_development_environment(
            build_development_fixtures(), arms, _budget()
        )


def test_qualifier_rejects_replay_nondeterminism() -> None:
    calls = {"count": 0}

    def mutate(output: ArmOutput, _arm_input: ArmInput) -> ArmOutput:
        calls["count"] += 1
        return _mutate_output(
            output,
            representation=output.representation + str(calls["count"]),
        )

    nondeterministic = _MutatingArm(A2FrozenRetrievalArm(
        RetrievalRequest(query=RetrievalQuery.ASSERTION_EVENTS)
    ), mutate)
    arms = _qualified_arms()[:2] + (nondeterministic,) + _qualified_arms()[3:]

    with pytest.raises(QualificationError, match="REPLAY_NONDETERMINISM"):
        qualify_development_environment(
            build_development_fixtures(), arms, _budget()
        )
