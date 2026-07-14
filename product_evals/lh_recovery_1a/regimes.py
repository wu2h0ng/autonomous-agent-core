"""Frozen LH-RECOVERY-1A regime, timing, and failure declarations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from json import dumps
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from agent_os_contracts import ExternalSignal
from agent_os_contracts.workflow import NodeSpec


REGIMES = (
    "R0_DIRECT_REFRESH",
    "R1_DEPENDENCY_BEFORE_PROVIDER",
    "R2_RELEASE_BEFORE_APPLY",
)
FAILURE_MODES = (
    "PRE_CONSEQUENCE_PROCESS_EXIT",
    "POST_APPLY_WORKER_INTERRUPTED",
    "CORRECTION_HALT_BEFORE_APPLY",
)
NO_RESCUE_RULES = (
    "NO_SEED_CHANGE",
    "NO_CASE_REMOVAL_OR_REPLACEMENT",
    "NO_BASELINE_WEAKENING",
    "NO_THRESHOLD_MOVEMENT",
    "NO_ENVIRONMENT_CHANGE",
    "NO_METRIC_SUBSTITUTION",
    "NO_RERUN",
    "NO_RESCUE",
)

RegimeName = Literal[
    "R0_DIRECT_REFRESH",
    "R1_DEPENDENCY_BEFORE_PROVIDER",
    "R2_RELEASE_BEFORE_APPLY",
]
NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

CHANGE_NOTICE_SCHEMA_VERSION = "lh1a-change-notice-v1"
CHANGE_SIGNAL_NAME = "requirement.changed"


@dataclass(frozen=True, slots=True)
class RegimeSpec:
    regime: str
    required_gate_position: str
    required_post_change_event_order: tuple[str, ...]
    change_wait_node_id: str
    change_signal_name: str
    change_correlation_suffix: str
    secondary_wait_node_id: str | None
    secondary_signal_name: str | None
    secondary_correlation_suffix: str | None


REGIME_SPECS: dict[str, RegimeSpec] = {
    "R0_DIRECT_REFRESH": RegimeSpec(
        regime="R0_DIRECT_REFRESH",
        required_gate_position="AFTER_CHANGE_BEFORE_READ_V2",
        required_post_change_event_order=(
            "change",
            "read_v2",
            "provider",
            "approval",
            "apply",
            "test",
        ),
        change_wait_node_id="wait_change",
        change_signal_name="requirement.changed",
        change_correlation_suffix="change",
        secondary_wait_node_id=None,
        secondary_signal_name=None,
        secondary_correlation_suffix=None,
    ),
    "R1_DEPENDENCY_BEFORE_PROVIDER": RegimeSpec(
        regime="R1_DEPENDENCY_BEFORE_PROVIDER",
        required_gate_position="AFTER_READ_V2_BEFORE_PROVIDER_V2",
        required_post_change_event_order=(
            "change",
            "dependency_wait_satisfied",
            "provider",
            "approval",
            "apply",
        ),
        change_wait_node_id="wait_change",
        change_signal_name="requirement.changed",
        change_correlation_suffix="change",
        secondary_wait_node_id="wait_dependency",
        secondary_signal_name="dependency.ready",
        secondary_correlation_suffix="dependency",
    ),
    "R2_RELEASE_BEFORE_APPLY": RegimeSpec(
        regime="R2_RELEASE_BEFORE_APPLY",
        required_gate_position="AFTER_PROVIDER_V2_BEFORE_APPROVAL",
        required_post_change_event_order=(
            "change",
            "provider",
            "release_wait_satisfied",
            "approval",
            "apply",
        ),
        change_wait_node_id="wait_change",
        change_signal_name="requirement.changed",
        change_correlation_suffix="change",
        secondary_wait_node_id="wait_release",
        secondary_signal_name="release.ready",
        secondary_correlation_suffix="release",
    ),
}


CHANGE_NOTICE_FIELDS = (
    "schema_version",
    "case_id",
    "change_id",
    "goal_v2",
    "regime",
    "required_gate_position",
    "signal_name",
    "correlation_key",
)


class ChangeNotice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["lh1a-change-notice-v1"] = "lh1a-change-notice-v1"
    case_id: NonBlankStr
    change_id: NonBlankStr
    goal_v2: NonBlankStr
    regime: RegimeName
    required_gate_position: NonBlankStr
    signal_name: Literal["requirement.changed"] = "requirement.changed"
    correlation_key: NonBlankStr

    @model_validator(mode="after")
    def _validate_regime_coupling(self) -> ChangeNotice:
        spec = REGIME_SPECS[self.regime]
        if self.required_gate_position != spec.required_gate_position:
            raise ValueError(
                "required_gate_position does not match the declared regime"
            )
        expected_key = f"case:{self.case_id}:{spec.change_correlation_suffix}"
        if self.correlation_key != expected_key:
            raise ValueError("correlation_key does not match case and regime")
        return self


@dataclass(frozen=True, slots=True)
class TimingContract:
    prepare_to_change_min_seconds: int
    change_to_recovery_min_seconds: int
    prepare_to_adjudicate_min_seconds: int
    wait_change_timeout_seconds: int
    secondary_wait_timeout_seconds: int
    commitment_ttl_seconds: int
    approval_ttl_seconds: int
    max_approval_to_apply_seconds: int
    stale_lease_seconds: int


TIMING_CONTRACT = TimingContract(
    prepare_to_change_min_seconds=7200,
    change_to_recovery_min_seconds=360,
    prepare_to_adjudicate_min_seconds=7560,
    wait_change_timeout_seconds=21600,
    secondary_wait_timeout_seconds=300,
    commitment_ttl_seconds=28800,
    approval_ttl_seconds=600,
    max_approval_to_apply_seconds=120,
    stale_lease_seconds=300,
)


@dataclass(frozen=True, slots=True)
class FailureInjector:
    failure: str
    checkpoint: str
    required_public_proofs: tuple[str, ...]


FAILURE_INJECTORS: dict[str, FailureInjector] = {
    "PRE_CONSEQUENCE_PROCESS_EXIT": FailureInjector(
        failure="PRE_CONSEQUENCE_PROCESS_EXIT",
        checkpoint="matched_post_change_pre_consequence_checkpoint",
        required_public_proofs=(
            "fresh_process_exits",
            "no_live_lease_remains",
            "injection_event_is_publicly_proven",
        ),
    ),
    "POST_APPLY_WORKER_INTERRUPTED": FailureInjector(
        failure="POST_APPLY_WORKER_INTERRUPTED",
        checkpoint="immediately_after_apply",
        required_public_proofs=(
            "stop_after_node_apply",
            "durable_logical_receipt_exists",
            "fresh_process_reacquires_without_stale_lease_override",
            "duplicate_effect_count_is_zero",
        ),
    ),
    "CORRECTION_HALT_BEFORE_APPLY": FailureInjector(
        failure="CORRECTION_HALT_BEFORE_APPLY",
        checkpoint="after_fresh_approval_before_apply",
        required_public_proofs=(
            "authorized_correction_is_publicly_recorded",
            "halted_action_is_denied_with_zero_effect",
            "resume_occurs_after_recovery_gate",
            "post_resume_approval_is_fresh",
        ),
    ),
}


CANDIDATE_PUBLIC_CALL_SEQUENCES: dict[str, tuple[str, ...]] = {
    "R0_DIRECT_REFRESH": (
        "signal_change_once",
        "repeat_identical_signal_id_and_payload",
        "run_committed_direct_suffix",
        "reach_assigned_failure_checkpoint",
    ),
    "R1_DEPENDENCY_BEFORE_PROVIDER": (
        "signal_change_once",
        "repeat_identical_signal_id_and_payload",
        "pause_task",
        "replan_task_exactly_once",
        "run_to_dependency_waiting_event",
        "deliver_matching_dependency_signal_once",
        "persist_dependency_wait_satisfied_projection",
        "reach_assigned_failure_checkpoint",
    ),
    "R2_RELEASE_BEFORE_APPLY": (
        "signal_change_once",
        "repeat_identical_signal_id_and_payload",
        "pause_task",
        "replan_task_exactly_once",
        "run_to_release_waiting_event",
        "deliver_matching_release_signal_once",
        "persist_release_wait_satisfied_projection",
        "reach_assigned_failure_checkpoint",
    ),
}


def events_for_regime(regime: str) -> tuple[str, ...]:
    return REGIME_SPECS[regime].required_post_change_event_order


def change_notice_for(
    regime: str,
    *,
    case_id: str,
    change_id: str,
    goal_v2: str,
) -> ChangeNotice:
    spec = REGIME_SPECS.get(regime)
    if spec is None:
        raise ValueError(f"undeclared regime: {regime}")
    return ChangeNotice(
        case_id=case_id,
        change_id=change_id,
        goal_v2=goal_v2,
        regime=regime,
        required_gate_position=spec.required_gate_position,
        correlation_key=f"case:{case_id}:{spec.change_correlation_suffix}",
    )


def waiting_recovery_disposition(
    *,
    elapsed_seconds: int,
    typed_timeout_or_failure_present: bool,
) -> str:
    if elapsed_seconds < TIMING_CONTRACT.secondary_wait_timeout_seconds:
        return "WAITING_UNTIL_FROZEN_DEADLINE"
    if typed_timeout_or_failure_present:
        return "TERMINAL_TYPED_TIMEOUT_OR_FAILURE"
    return "INVALID_PROTOCOL"


def external_signal_for_wait(
    *,
    regime: str,
    case_id: str,
    wait_node: NodeSpec,
    notice: ChangeNotice,
    task_id: str,
    run_id: str,
    tenant_id: str,
    workspace_id: str,
    occurred_at: datetime,
) -> ExternalSignal:
    spec = REGIME_SPECS.get(regime)
    if spec is None:
        raise ValueError(f"undeclared regime: {regime}")
    if notice.regime != regime:
        raise ValueError("change notice regime does not match the requested regime")
    if notice.case_id != case_id:
        raise ValueError("change notice case does not match the requested case")

    node_id = wait_node.node_id
    if node_id == spec.change_wait_node_id:
        expected_signal = spec.change_signal_name
        expected_suffix = spec.change_correlation_suffix
        if wait_node.wait_signal_name != notice.signal_name:
            raise ValueError("change wait node signal disagrees with the notice")
        if wait_node.wait_correlation_key != notice.correlation_key:
            raise ValueError("change wait node correlation disagrees with the notice")
    elif node_id == spec.secondary_wait_node_id:
        expected_signal = spec.secondary_signal_name
        expected_suffix = spec.secondary_correlation_suffix
    else:
        raise ValueError(f"node {node_id} is not a wait node for regime {regime}")

    expected_correlation = f"case:{case_id}:{expected_suffix}"
    if wait_node.wait_signal_name != expected_signal:
        raise ValueError("wait node signal disagrees with the regime declaration")
    if wait_node.wait_correlation_key != expected_correlation:
        raise ValueError("wait node correlation disagrees with the regime declaration")

    payload_json = dumps(
        {"change_notice": notice.model_dump(mode="json")},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ExternalSignal(
        signal_id=f"signal:{case_id}:{node_id}:{notice.change_id}",
        task_id=task_id,
        run_id=run_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        signal_name=wait_node.wait_signal_name,
        correlation_key=wait_node.wait_correlation_key,
        payload_json=payload_json,
        occurred_at=occurred_at,
    )
