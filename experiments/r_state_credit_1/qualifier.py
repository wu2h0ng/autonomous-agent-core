"""Non-result qualification checks for the Batch-2A development environment."""

from __future__ import annotations

from experiments.r_state_credit_1.arms import ArmAdapter
from experiments.r_state_credit_1.contracts import (
    ArmId,
    ArmOutput,
    EvidenceStatus,
    ExecutionStatus,
    QualificationCheck,
    QualificationReceipt,
    ResourceBudget,
    ScenarioFamily,
    ScenarioFixture,
    deterministic_token_proxy,
)


class QualificationError(RuntimeError):
    """Raised when development plumbing fails a fail-closed qualifier check."""


def qualify_development_environment(
    fixtures: tuple[ScenarioFixture, ...],
    arms: tuple[ArmAdapter, ...],
    budget: ResourceBudget,
) -> QualificationReceipt:
    """Qualify plumbing only; compute no task score, winner, or statistic."""
    _validate_interfaces(fixtures, arms, budget)
    representation_digests = {arm_id: set() for arm_id in ArmId}
    probe_actions = {arm_id: set() for arm_id in ArmId}
    for fixture in fixtures:
        arm_input = fixture.actor_input(budget=budget)
        expected_input_bytes = len(
            arm_input.canonical_observable_json().encode("utf-8")
        )
        first_outputs: dict[ArmId, ArmOutput] = {}
        for arm in arms:
            first = arm.consume(arm_input)
            second = arm.consume(arm_input)
            if not isinstance(first, ArmOutput) or not isinstance(second, ArmOutput):
                raise QualificationError("CLOSED_INTERFACE: arm output is untyped")
            if first != second:
                raise QualificationError(
                    f"REPLAY_NONDETERMINISM: {arm.arm_id.value}"
                )
            if first.arm_id is not arm.arm_id:
                raise QualificationError("CLOSED_INTERFACE: arm identity mismatch")
            if first.scenario_id != fixture.scenario_id:
                raise QualificationError(
                    "CLOSED_INTERFACE: scenario identity mismatch"
                )
            if first.receipt.status is not ExecutionStatus.OK:
                raise QualificationError(
                    "RESOURCE_BUDGET: qualification budget rejected "
                    f"{arm.arm_id.value} with {first.receipt.status.value}"
                )
            if first.receipt.observable_digest != arm_input.observable_digest():
                raise QualificationError("MATCHED_INFORMATION: observable digest drift")
            if (
                first.receipt.input_bytes != expected_input_bytes
                or first.receipt.input_token_proxy
                != deterministic_token_proxy(expected_input_bytes)
                or first.receipt.steps != len(arm_input.observable_events)
            ):
                raise QualificationError("RESOURCE_BUDGET: input receipt mismatch")
            if (
                first.receipt.output_bytes > budget.max_representation_bytes
                or first.receipt.steps > budget.max_steps
                or first.receipt.tool_calls > budget.max_tool_calls
                or first.receipt.wall_clock_units > budget.max_wall_clock_units
            ):
                raise QualificationError("RESOURCE_BUDGET: receipt exceeds cap")
            rendered = first.representation
            for secret in (
                fixture.hidden_entity_key,
                fixture.oracle_label,
                fixture.oracle_reason,
                fixture.expected_outcome,
            ):
                if secret in rendered:
                    raise QualificationError(
                        f"HIDDEN_REFEREE_LEAK: {arm.arm_id.value}"
                    )
            first_outputs[arm.arm_id] = first
            representation_digests[arm.arm_id].add(
                first.receipt.representation_digest
            )
            probe_actions[arm.arm_id].add(first.probe_action)

        a0 = first_outputs[ArmId.A0_FULL_LOG]
        if a0.representation != arm_input.canonical_observable_json():
            raise QualificationError(
                "A0_FULL_LOG_WEAKENED: raw observable feed changed"
            )
        if {output.receipt.observable_digest for output in first_outputs.values()} != {
            arm_input.observable_digest()
        }:
            raise QualificationError("MATCHED_INFORMATION: arms saw different feeds")

    for arm_id in ArmId:
        if len(representation_digests[arm_id]) <= 1:
            raise QualificationError(f"CONSTANT_REPRESENTATION: {arm_id.value}")
        if len(probe_actions[arm_id]) <= 1:
            raise QualificationError(f"CONSTANT_PROBE_ACTION: {arm_id.value}")

    return QualificationReceipt(
        qualification_id="R-STATE-CREDIT-1-BATCH-2A",
        evidence_status=EvidenceStatus.NOT_EVIDENCE,
        qualified=True,
        checks=tuple(QualificationCheck),
        scenario_digests=tuple(fixture.digest() for fixture in fixtures),
        arm_ids=tuple(arm.arm_id for arm in arms),
    )


def _validate_interfaces(
    fixtures: tuple[ScenarioFixture, ...],
    arms: tuple[ArmAdapter, ...],
    budget: ResourceBudget,
) -> None:
    if not isinstance(fixtures, tuple) or any(
        not isinstance(fixture, ScenarioFixture) for fixture in fixtures
    ):
        raise QualificationError("CLOSED_INTERFACE: fixtures must be typed tuple")
    if {fixture.family for fixture in fixtures} != set(ScenarioFamily):
        raise QualificationError("CLOSED_INTERFACE: seven scenario families required")
    if len({fixture.scenario_id for fixture in fixtures}) != len(fixtures):
        raise QualificationError("CLOSED_INTERFACE: duplicate scenario_id")
    if not isinstance(arms, tuple):
        raise QualificationError("CLOSED_INTERFACE: arms must be tuple")
    try:
        arm_ids = tuple(arm.arm_id for arm in arms)
    except AttributeError as exc:
        raise QualificationError("CLOSED_INTERFACE: arm_id missing") from exc
    if set(arm_ids) != set(ArmId) or len(arm_ids) != len(set(arm_ids)):
        raise QualificationError("CLOSED_INTERFACE: exactly one A0-A3 arm required")
    if any(not isinstance(arm_id, ArmId) for arm_id in arm_ids):
        raise QualificationError("CLOSED_INTERFACE: arm_id must be ArmId")
    if not isinstance(budget, ResourceBudget):
        raise QualificationError("CLOSED_INTERFACE: budget must be ResourceBudget")
