"""Public-application protocol primitives for LH-RECOVERY-1A Task 7.

This module drives an injected Agent OS application only through the frozen
public surface.  It does not materialize the Task 8 timing phases or produce a
formal result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from typing import Any, Protocol

from agent_os_contracts import WorkflowGraph

from product_evals.common.artifacts import canonical_sha256

from .combined_contract import ARM_CASE_INPUT_FIELDS, ArmCaseInput
from .fixed_baseline import instantiate_fixed_baseline_dag
from .evaluator import (
    APPROVAL_MAX_AGE_INCLUSIVE_SECONDS,
    CheckpointEvidence,
    RestartEvidence,
)
from .regimes import (
    FAILURE_MODES,
    FAILURE_INJECTORS,
    REGIMES,
    REGIME_SPECS,
    TIMING_CONTRACT,
    change_notice_for,
)
from .templates import (
    BudgetCeiling,
    CommonInformationEnvelope,
    TOPOLOGY_SELECTION_HUMAN_MINUTES,
    budget_ceiling_for,
    common_information_envelope,
    instantiate_candidate_for,
    instantiate_candidate_initial,
    restart_template_for,
)


ARMS = ("C", "F", "R", "K")


class PublicApplication(Protocol):
    def create_task(self, payload: dict[str, object]) -> object: ...

    def commit_task(self, task_id: str, payload: dict[str, object]) -> object: ...

    def signal_task(self, task_id: str, payload: dict[str, object]) -> object: ...

    def pause_task(self, task_id: str) -> object: ...

    def replan_task(self, task_id: str, payload: dict[str, object]) -> object: ...

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, object],
        **kwargs: object,
    ) -> object: ...

    def task_json(self, task_id: str) -> dict[str, object]: ...

    def evidence_json(self, task_id: str) -> list[dict[str, object]]: ...

    def recovery_json(self, task_id: str) -> dict[str, object]: ...

    def record_approval(self, task_id: str, payload: dict[str, object]) -> object: ...


class ProtocolEvidenceError(ValueError):
    """Raised when public projections cannot prove a required protocol state."""


@dataclass(frozen=True, slots=True)
class EpisodeContract:
    arm: str
    regime: str
    failure: str
    case: dict[str, object]
    change_notice: dict[str, object]
    goal: dict[str, object]
    commitment: dict[str, object]
    initial_workflow: dict[str, object]
    recovery_workflow: dict[str, object]
    expected_outcome: dict[str, object]
    inputs: dict[str, object]
    common_information: CommonInformationEnvelope
    budget_ceiling: BudgetCeiling
    topology_selection_human_minutes: float


@dataclass(frozen=True, slots=True)
class SecondaryWaitEvidence:
    regime: str
    task_id: str
    run_id: str
    disposition: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveRestartReceipt:
    old_task_id: str
    new_task_id: str
    evidence: RestartEvidence
    public_calls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckpointApproval:
    action_digest: str
    decided_at: datetime

    def __post_init__(self) -> None:
        _require_sha256(self.action_digest, "action_digest")
        if type(self.decided_at) is not datetime or self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CheckpointApprovalReceipt:
    action_digest: str
    approval_age_seconds: int
    recorded_after_change: bool

    def __post_init__(self) -> None:
        _require_sha256(self.action_digest, "action_digest")
        if type(self.approval_age_seconds) is not int or self.approval_age_seconds < 0:
            raise ValueError("approval_age_seconds must be a non-negative int")
        if type(self.recorded_after_change) is not bool:
            raise TypeError("recorded_after_change must be a bool")


class CheckpointApprovalRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FailureProof:
    failure: str
    task_id: str
    run_id: str
    required_public_proofs: tuple[str, ...]
    observed_public_proofs: tuple[str, ...]
    supporting_event_ids: tuple[str, ...]
    process_boundary_proven: bool
    duplicate_logical_effects: int

    @property
    def valid(self) -> bool:
        return (
            self.process_boundary_proven
            and self.observed_public_proofs == self.required_public_proofs
            and self.duplicate_logical_effects == 0
        )


@dataclass(frozen=True, slots=True)
class ChangePhaseReceipt:
    arm: str
    regime: str
    task_id: str
    public_calls: tuple[str, ...]
    secondary_wait: SecondaryWaitEvidence | None


def _require_mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{field_name} must be an exact object")
    return dict(value)


def _require_sha256(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256 text")
    return value


def _arm_case_values(case: ArmCaseInput) -> dict[str, object]:
    if type(case) is not ArmCaseInput:
        raise TypeError("case must be an exact ArmCaseInput")
    projected = asdict(case)
    if tuple(projected) != ARM_CASE_INPUT_FIELDS:
        raise ValueError("case fields do not match the frozen arm projection")
    values = {name: projected[name] for name in ARM_CASE_INPUT_FIELDS[:-1]}
    if canonical_sha256(values) != projected["projection_sha256"]:
        raise ValueError("case projection_sha256 does not match public fields")
    return projected


def _goal_text(value: object) -> str:
    if type(value) is str and value.strip():
        return value.strip()
    rendered = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if not rendered:
        raise ValueError("requirement must be nonempty canonical JSON")
    return rendered


def _instantiate_restart_workflow(regime: str, case_id: str) -> WorkflowGraph:
    workflow = restart_template_for(regime).workflow
    nodes = tuple(
        node.model_copy(
            update={
                "wait_correlation_key": node.wait_correlation_key.replace(
                    "{case_id}", case_id
                )
            }
        )
        if node.wait_correlation_key and "{case_id}" in node.wait_correlation_key
        else node
        for node in workflow.nodes
    )
    return workflow.model_copy(update={"nodes": nodes})


def _zero_replan_workflow(workflow: WorkflowGraph, arm: str) -> WorkflowGraph:
    return workflow.model_copy(
        update={
            "workflow_id": f"lh1a-{arm.lower()}-{workflow.workflow_id}",
            "max_replans": 0,
        }
    )


def build_episode_contract(
    case: ArmCaseInput,
    *,
    arm: str,
    regime: str,
    failure: str,
    contract_time: datetime,
) -> EpisodeContract:
    """Build exact Product contracts from the arm-safe D1 projection."""

    if arm not in ARMS:
        raise ValueError(f"undeclared arm: {arm}")
    if regime not in REGIMES:
        raise ValueError(f"undeclared regime: {regime}")
    if failure not in FAILURE_MODES:
        raise ValueError(f"undeclared failure: {failure}")
    if type(contract_time) is not datetime or contract_time.tzinfo is None:
        raise ValueError("contract_time must be timezone-aware")
    case_values = _arm_case_values(case)
    notice = change_notice_for(
        regime,
        case_id=case.case_id,
        change_id=f"change:{case.case_id}",
        goal_v2=_goal_text(case.requirement_v2),
    ).model_dump(mode="json")
    candidate_initial = instantiate_candidate_initial(case.case_id).workflow
    if arm == "F":
        initial = instantiate_fixed_baseline_dag(case.case_id).workflow
        recovery = initial
    elif arm == "C":
        initial = candidate_initial
        recovery = instantiate_candidate_for(regime, case_id=case.case_id).workflow
    elif arm == "R":
        initial = _zero_replan_workflow(candidate_initial, arm)
        recovery = _instantiate_restart_workflow(regime, case.case_id)
    else:
        initial = _zero_replan_workflow(candidate_initial, arm)
        recovery = initial
    goal_id = f"goal:lh1a:{case.case_id}:{arm.lower()}"
    task_ref = f"task:lh1a:{case.case_id}:{arm.lower()}"
    expires_at = contract_time + timedelta(
        seconds=TIMING_CONTRACT.commitment_ttl_seconds
    )
    goal = {
        "goal_id": goal_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "created_by": "user:local",
        "created_at": contract_time.isoformat(),
        "statement": _goal_text(case.requirement_v1),
    }
    commitment = {
        "commitment_id": f"commitment:lh1a:{case.case_id}:{arm.lower()}",
        "task_id": task_ref,
        "goal_id": goal_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "accepted_by": "user:local",
        "accepted_at": contract_time.isoformat(),
        "deliverables": ["subject.py patch"],
        "acceptance_criteria": ["python -m pytest exits 0"],
        "authority_scopes": ["workspace:read", "workspace:write"],
        "budget": {
            "max_cost_usd": "10",
            "max_duration_seconds": TIMING_CONTRACT.commitment_ttl_seconds,
            "max_provider_tokens": budget_ceiling_for(arm).max_provider_tokens,
            "max_tool_calls": budget_ceiling_for(arm).max_tool_calls,
        },
        "risk_tier": 1,
        "exit_conditions": ["verified", "typed failure"],
        "expires_at": expires_at.isoformat(),
    }
    expected_outcome = {
        "expected_outcome_id": f"expected:lh1a:{case.case_id}:{arm.lower()}",
        "task_id": task_ref,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": [
            "pytest-report",
            "apply-receipt",
            "final-workspace-digest",
            "failure-proof",
        ],
        "failure_semantics": [
            "non-zero pytest exit",
            "missing evidence",
            "final digest mismatch",
            "unproven failure injection",
        ],
        "threshold": 1.0,
        "observation_window_seconds": TIMING_CONTRACT.commitment_ttl_seconds,
        "frozen_at": contract_time.isoformat(),
    }
    inputs = {
        "target_path": "subject.py",
        "test_command": "python -m pytest",
        "prompt": case.prompt,
        "change_notice": notice,
    }
    return EpisodeContract(
        arm=arm,
        regime=regime,
        failure=failure,
        case=case_values,
        change_notice=notice,
        goal=goal,
        commitment=commitment,
        initial_workflow=initial.model_dump(mode="json"),
        recovery_workflow=recovery.model_dump(mode="json"),
        expected_outcome=expected_outcome,
        inputs=inputs,
        common_information=common_information_envelope(arm, regime),
        budget_ceiling=budget_ceiling_for(arm),
        topology_selection_human_minutes=TOPOLOGY_SELECTION_HUMAN_MINUTES,
    )


def serialize_episode_contract(contract: EpisodeContract) -> str:
    if type(contract) is not EpisodeContract:
        raise TypeError("contract must be an exact EpisodeContract")
    return json.dumps(
        asdict(contract),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _public_events(task: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw = task.get("events")
    if type(raw) is not list:
        raise ProtocolEvidenceError("task_json.events must be a list")
    events: list[dict[str, object]] = []
    for index, event in enumerate(raw):
        if type(event) is not dict:
            raise ProtocolEvidenceError(f"event {index} must be an object")
        if type(event.get("event_id")) is not str or not event["event_id"]:
            raise ProtocolEvidenceError(f"event {index} lacks an event_id")
        events.append(event)
    return tuple(events)


def _secondary_wait_from_projections(
    task: dict[str, object],
    recovery: dict[str, object],
    task_id: str,
    regime: str,
) -> SecondaryWaitEvidence:
    if regime not in REGIMES:
        raise ValueError(f"undeclared regime: {regime}")
    if type(task) is not dict or type(recovery) is not dict:
        raise ProtocolEvidenceError("public projections must be exact objects")
    run = task.get("run")
    if type(run) is not dict:
        raise ProtocolEvidenceError("task_json.run must be an object")
    run_id = run.get("run_id")
    status = run.get("status")
    if type(run_id) is not str or not run_id:
        raise ProtocolEvidenceError("public run_id is missing")
    if task.get("task_id") != task_id or recovery.get("task_id") != task_id:
        raise ProtocolEvidenceError("public task identity mismatch")
    if recovery.get("run_id") != run_id:
        raise ProtocolEvidenceError("public run identity mismatch")
    events = _public_events(task)
    if status == "WAITING_EVENT":
        raise ProtocolEvidenceError("WAITING_EVENT is not terminalized")
    secondary_node = REGIME_SPECS[regime].secondary_wait_node_id
    if secondary_node is None:
        if status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ProtocolEvidenceError("R0 lacks a terminal public run state")
        terminal = tuple(
            str(event["event_id"])
            for event in events
            if event.get("event_type")
            in {"RUN_SUCCEEDED", "RUN_FAILED", "RUN_CANCELLED"}
        )
        if not terminal:
            raise ProtocolEvidenceError("R0 lacks a terminal public event")
        return SecondaryWaitEvidence(
            regime, task_id, run_id, "TERMINAL_NO_SECONDARY", terminal
        )
    satisfied = tuple(
        str(event["event_id"])
        for event in events
        if event.get("event_type") == "WAIT_SATISFIED"
        and type(event.get("payload")) is dict
        and event["payload"].get("node_id") == secondary_node
    )
    timed_out = tuple(
        str(event["event_id"])
        for event in events
        if event.get("event_type") == "WAIT_TIMED_OUT"
        and type(event.get("payload")) is dict
        and event["payload"].get("node_id") == secondary_node
    )
    if satisfied and not timed_out:
        count = recovery.get("signal_satisfied_count")
        if type(count) is not int or count < 1:
            raise ProtocolEvidenceError("delivery lacks recovery projection")
        return SecondaryWaitEvidence(regime, task_id, run_id, "DELIVERED", satisfied)
    if timed_out and not satisfied and status == "FAILED":
        return SecondaryWaitEvidence(
            regime, task_id, run_id, "TIMED_OUT_TERMINAL", timed_out
        )
    raise ProtocolEvidenceError("secondary wait lacks one exact terminal disposition")


def capture_secondary_wait(
    app: PublicApplication,
    task_id: str,
    regime: str,
) -> SecondaryWaitEvidence:
    """Classify delivery, typed timeout, or no-secondary terminalization."""

    task = app.task_json(task_id)
    recovery = app.recovery_json(task_id)
    return _secondary_wait_from_projections(task, recovery, task_id, regime)


def _projection_refs(
    task: dict[str, object], evidence: list[dict[str, object]]
) -> tuple[str, ...]:
    raw_events = task.get("events")
    if type(raw_events) is not list or type(evidence) is not list:
        raise ProtocolEvidenceError("restart public projections are malformed")
    refs: list[str] = []
    for row in (*raw_events, *evidence):
        if type(row) is not dict:
            raise ProtocolEvidenceError("restart evidence row must be an object")
        event_id = row.get("event_id")
        if type(event_id) is str and event_id and event_id not in refs:
            refs.append(event_id)
    if not refs:
        raise ProtocolEvidenceError("restart projections need public evidence refs")
    return tuple(refs)


def _projection_identity(
    task: dict[str, object], recovery: dict[str, object], task_id: str
) -> str:
    if task.get("task_id") != task_id or recovery.get("task_id") != task_id:
        raise ProtocolEvidenceError("restart task identity mismatch")
    run = task.get("run")
    if type(run) is not dict:
        raise ProtocolEvidenceError("restart task lacks a public run")
    run_id = run.get("run_id")
    if type(run_id) is not str or not run_id or recovery.get("run_id") != run_id:
        raise ProtocolEvidenceError("restart run identity mismatch")
    return run_id


def execute_adaptive_restart(
    app: PublicApplication,
    old_task_id: str,
    contract: EpisodeContract,
) -> AdaptiveRestartReceipt:
    """Recreate R through public task APIs and derive exact parity evidence."""

    if type(contract) is not EpisodeContract or contract.arm != "R":
        raise ValueError("adaptive restart requires an R EpisodeContract")
    calls: list[str] = []
    old_task = app.task_json(old_task_id)
    calls.append("task_json")
    old_evidence = app.evidence_json(old_task_id)
    calls.append("evidence_json")
    old_recovery = app.recovery_json(old_task_id)
    calls.append("recovery_json")
    if (
        type(old_task) is not dict
        or type(old_evidence) is not list
        or type(old_recovery) is not dict
    ):
        raise ProtocolEvidenceError("old restart projections are malformed")
    old_run_id = _projection_identity(old_task, old_recovery, old_task_id)
    sidecar_refs = _projection_refs(old_task, old_evidence)

    created = app.create_task(dict(contract.goal))
    calls.append("create_task")
    try:
        new_task_id = created.task_id
    except AttributeError as exc:
        raise ProtocolEvidenceError(
            "create_task did not return a public task identity"
        ) from exc
    if type(new_task_id) is not str or not new_task_id:
        raise ProtocolEvidenceError("create_task did not return a public task identity")
    if new_task_id == old_task_id:
        raise ProtocolEvidenceError("adaptive restart requires a fresh task identity")
    commitment = {**contract.commitment, "task_id": new_task_id}
    expected_outcome = {**contract.expected_outcome, "task_id": new_task_id}
    app.commit_task(
        new_task_id,
        {
            "commitment": commitment,
            "workflow": contract.recovery_workflow,
            "expected_outcome": expected_outcome,
        },
    )
    calls.append("commit_task")
    app.run_task(new_task_id, dict(contract.inputs))
    calls.append("run_task")

    new_task = app.task_json(new_task_id)
    calls.append("task_json")
    new_evidence = app.evidence_json(new_task_id)
    calls.append("evidence_json")
    new_recovery = app.recovery_json(new_task_id)
    calls.append("recovery_json")
    if (
        type(new_task) is not dict
        or type(new_evidence) is not list
        or type(new_recovery) is not dict
    ):
        raise ProtocolEvidenceError("new restart projections are malformed")
    new_run_id = _projection_identity(new_task, new_recovery, new_task_id)
    new_refs = _projection_refs(new_task, new_evidence)
    encoded_new = json.dumps(
        {"task": new_task, "evidence": new_evidence, "recovery": new_recovery},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    references_disjoint = set(sidecar_refs).isdisjoint(new_refs)
    private_state_reused = (
        not references_disjoint
        or old_task_id in encoded_new
        or old_run_id in encoded_new
    )
    charge_half_minutes = int(TOPOLOGY_SELECTION_HUMAN_MINUTES * 2)
    evidence = RestartEvidence(
        old_task_id=old_task_id,
        new_task_id=new_task_id,
        old_run_id=old_run_id,
        new_run_id=new_run_id,
        private_state_reused=private_state_reused,
        episode1_evidence_location="RETAINED_SIDECAR_NOT_INJECTED",
        sidecar_evidence_refs=sidecar_refs,
        new_task_evidence_refs=new_refs,
        change_notice_matches=(
            contract.inputs.get("change_notice") == contract.change_notice
        ),
        template_matches=new_task.get("workflow") == contract.recovery_workflow,
        topology_information_matches=(
            common_information_envelope("C", contract.regime)
            == common_information_envelope("R", contract.regime)
        ),
        topology_selection_charge_c_half_minutes=charge_half_minutes,
        topology_selection_charge_r_half_minutes=charge_half_minutes,
    )
    return AdaptiveRestartReceipt(
        old_task_id=old_task_id,
        new_task_id=new_task_id,
        evidence=evidence,
        public_calls=tuple(calls),
    )


def record_checkpoint_approval(
    app: PublicApplication,
    task_id: str,
    approval: CheckpointApproval,
    *,
    change_occurred_at: datetime,
    now: datetime,
) -> CheckpointApprovalReceipt:
    """Record K approval only after freshness and pending-action SHA checks."""

    if type(approval) is not CheckpointApproval:
        raise TypeError("approval must be an exact CheckpointApproval")
    if (
        type(change_occurred_at) is not datetime
        or change_occurred_at.tzinfo is None
        or type(now) is not datetime
        or now.tzinfo is None
    ):
        raise ValueError("checkpoint times must be timezone-aware")
    task = app.task_json(task_id)
    if type(task) is not dict or task.get("task_id") != task_id:
        raise ProtocolEvidenceError("checkpoint task projection mismatch")
    proposed = task.get("proposed_action")
    if type(proposed) is not dict:
        raise ProtocolEvidenceError("checkpoint lacks a public proposed action")
    pending_digest = _require_sha256(
        proposed.get("action_digest"), "proposed_action.action_digest"
    )
    age = int((now - approval.decided_at).total_seconds())
    recorded_after_change = approval.decided_at >= change_occurred_at
    if approval.action_digest != pending_digest:
        raise CheckpointApprovalRejected("ACTION_SHA_MISMATCH")
    if age < 0 or age > APPROVAL_MAX_AGE_INCLUSIVE_SECONDS or not recorded_after_change:
        raise CheckpointApprovalRejected("STALE_APPROVAL")
    app.record_approval(
        task_id,
        {
            "disposition": "APPROVE",
            "reason": "LH1A fresh checkpoint approval",
        },
    )
    return CheckpointApprovalReceipt(
        action_digest=approval.action_digest,
        approval_age_seconds=age,
        recorded_after_change=recorded_after_change,
    )


def capture_checkpoint_evidence(
    app: PublicApplication,
    task_id: str,
    approval: CheckpointApprovalReceipt,
    *,
    workspace_digest_before: str,
    workspace_digest_after: str,
) -> CheckpointEvidence:
    """Derive K's expected-SHA rejection and zero-effect proof publicly."""

    if type(approval) is not CheckpointApprovalReceipt:
        raise TypeError("approval must be a CheckpointApprovalReceipt")
    task = app.task_json(task_id)
    evidence = app.evidence_json(task_id)
    recovery = app.recovery_json(task_id)
    if (
        type(task) is not dict
        or type(evidence) is not list
        or type(recovery) is not dict
        or task.get("task_id") != task_id
        or recovery.get("task_id") != task_id
    ):
        raise ProtocolEvidenceError("checkpoint public projections mismatch")
    rejection_ids = tuple(
        str(event["event_id"])
        for event in _public_events(task)
        if event.get("event_type") == "RUN_FAILED"
        and type(event.get("payload")) is dict
        and event["payload"].get("error_code") == "EXPECTED_SHA_MISMATCH"
    )
    if len(rejection_ids) != 1:
        raise ProtocolEvidenceError("EXPECTED_SHA_MISMATCH must be proven exactly once")
    successful_apply_receipts = 0
    for row in evidence:
        if type(row) is not dict or row.get("event_type") != "ACTION_RECEIPT_RECORDED":
            continue
        payload = row.get("payload")
        receipt = payload.get("receipt") if type(payload) is dict else None
        if (
            type(receipt) is dict
            and receipt.get("connector_id") == "workspace.apply_patch"
            and receipt.get("status") == "SUCCEEDED"
        ):
            successful_apply_receipts += 1
    logical_effects = recovery.get("unique_logical_action_count")
    if type(logical_effects) is not int or logical_effects < 0:
        raise ProtocolEvidenceError("checkpoint logical-effect count is invalid")
    return CheckpointEvidence(
        approval_recorded_after_change=approval.recorded_after_change,
        approval_age_seconds=approval.approval_age_seconds,
        approval_fresh=(
            approval.approval_age_seconds <= APPROVAL_MAX_AGE_INCLUSIVE_SECONDS
        ),
        expected_sha_stale=True,
        rejection_code="EXPECTED_SHA_MISMATCH",
        workspace_digest_before=_require_sha256(
            workspace_digest_before, "workspace_digest_before"
        ),
        workspace_digest_after=_require_sha256(
            workspace_digest_after, "workspace_digest_after"
        ),
        successful_apply_receipts=successful_apply_receipts,
        logical_effects=logical_effects,
    )


def _event_sequence(event: dict[str, object]) -> int | None:
    sequence = event.get("sequence")
    return sequence if type(sequence) is int and sequence > 0 else None


def _matching_events(
    events: tuple[dict[str, object], ...],
    event_type: str,
) -> tuple[dict[str, object], ...]:
    return tuple(event for event in events if event.get("event_type") == event_type)


def _apply_receipts(
    evidence: list[dict[str, object]],
) -> tuple[tuple[dict[str, object], dict[str, object]], ...]:
    receipts: list[tuple[dict[str, object], dict[str, object]]] = []
    for event in evidence:
        if (
            type(event) is not dict
            or event.get("event_type") != "ACTION_RECEIPT_RECORDED"
        ):
            continue
        payload = event.get("payload")
        receipt = payload.get("receipt") if type(payload) is dict else None
        if (
            type(receipt) is dict
            and receipt.get("connector_id") == "workspace.apply_patch"
            and receipt.get("status") == "SUCCEEDED"
        ):
            receipts.append((event, receipt))
    return tuple(receipts)


def _single_event_sequence(
    events: tuple[dict[str, object], ...],
    event_type: str,
    predicate: Any,
) -> tuple[int | None, str | None]:
    matches = [
        event
        for event in events
        if event.get("event_type") == event_type and predicate(event)
    ]
    if len(matches) != 1:
        return None, None
    sequence = _event_sequence(matches[0])
    event_id = matches[0].get("event_id")
    return sequence, event_id if type(event_id) is str else None


def capture_failure_proof(
    app: PublicApplication,
    task_id: str,
    failure: str,
    *,
    before_process_id: str,
    after_process_id: str,
) -> FailureProof:
    """Derive the assigned failure proof from public event projections only."""

    injector = FAILURE_INJECTORS.get(failure)
    if injector is None:
        raise ValueError(f"undeclared failure: {failure}")
    if (
        type(before_process_id) is not str
        or not before_process_id
        or type(after_process_id) is not str
        or not after_process_id
    ):
        raise ValueError("process identities must be nonblank strings")
    process_boundary = before_process_id != after_process_id
    task = app.task_json(task_id)
    evidence = app.evidence_json(task_id)
    recovery = app.recovery_json(task_id)
    if (
        type(task) is not dict
        or type(evidence) is not list
        or type(recovery) is not dict
        or task.get("task_id") != task_id
        or recovery.get("task_id") != task_id
    ):
        raise ProtocolEvidenceError("failure public projections mismatch")
    run = task.get("run")
    if type(run) is not dict:
        raise ProtocolEvidenceError("failure task lacks a public run")
    run_id = run.get("run_id")
    if type(run_id) is not str or not run_id or recovery.get("run_id") != run_id:
        raise ProtocolEvidenceError("failure public run identity mismatch")
    events = _public_events(task)
    receipts = _apply_receipts(evidence)
    receipt_keys = tuple(receipt.get("idempotency_key") for _, receipt in receipts)
    if any(type(key) is not str or not key for key in receipt_keys):
        raise ProtocolEvidenceError("apply receipt lacks a logical identity")
    duplicate_effects = max(0, len(receipt_keys) - 1)
    observed: set[str] = set()
    support: list[str] = []

    if failure == "PRE_CONSEQUENCE_PROCESS_EXIT":
        checkpoint_seq, checkpoint_id = _single_event_sequence(
            events,
            "NODE_COMPLETED",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("node_id") == "read_v2"
            ),
        )
        resume_seq, resume_id = _single_event_sequence(
            events,
            "RUN_RESUMED",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("recover_stale_lease") is False
            ),
        )
        if process_boundary:
            observed.add("fresh_process_exits")
        if (
            checkpoint_seq is not None
            and resume_seq is not None
            and checkpoint_seq < resume_seq
            and recovery.get("run_resumed_count") == 1
        ):
            observed.add("no_live_lease_remains")
        if checkpoint_seq is not None and resume_seq is not None and not receipts:
            observed.add("injection_event_is_publicly_proven")
        support.extend(item for item in (checkpoint_id, resume_id) if item is not None)

    elif failure == "POST_APPLY_WORKER_INTERRUPTED":
        apply_seq, apply_id = _single_event_sequence(
            events,
            "NODE_COMPLETED",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("node_id") == "apply"
            ),
        )
        resume_seq, resume_id = _single_event_sequence(
            events,
            "RUN_RESUMED",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("recover_stale_lease") is False
            ),
        )
        evidence_ids = {
            event.get("event_id") for event, _ in receipts if event.get("event_id")
        }
        task_receipt_ids = {
            event.get("event_id")
            for event in _matching_events(events, "ACTION_RECEIPT_RECORDED")
            if event.get("event_id")
        }
        if apply_seq is not None and len(receipts) >= 1:
            observed.add("stop_after_node_apply")
        if evidence_ids and evidence_ids <= task_receipt_ids:
            observed.add("durable_logical_receipt_exists")
        if (
            process_boundary
            and apply_seq is not None
            and resume_seq is not None
            and apply_seq < resume_seq
            and recovery.get("run_resumed_count") == 1
        ):
            observed.add("fresh_process_reacquires_without_stale_lease_override")
        if len(receipts) == 1 and duplicate_effects == 0:
            observed.add("duplicate_effect_count_is_zero")
        support.extend(item for item in (apply_id, resume_id) if item is not None)
        support.extend(str(value) for value in evidence_ids)

    else:
        halt_seq, halt_id = _single_event_sequence(
            events,
            "CORRECTION_WRITTEN",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("halted") is True
            ),
        )
        denial_seq, denial_id = _single_event_sequence(
            events,
            "POLICY_DECIDED",
            lambda event: (
                type(event.get("payload")) is dict
                and type(event["payload"].get("decision")) is dict
                and event["payload"]["decision"].get("verdict") == "DENY"
                and "CORRECTION_HALTED"
                in event["payload"]["decision"].get("reason_codes", [])
            ),
        )
        resume_seq, resume_id = _single_event_sequence(
            events,
            "CORRECTION_WRITTEN",
            lambda event: (
                type(event.get("payload")) is dict
                and event["payload"].get("halted") is False
            ),
        )
        approvals = _matching_events(events, "APPROVAL_RECORDED")
        fresh_post_resume = tuple(
            event
            for event in approvals
            if resume_seq is not None
            and _event_sequence(event) is not None
            and _event_sequence(event) > resume_seq
            and type(event.get("payload")) is dict
            and event["payload"].get("fresh") is True
            and type(event["payload"].get("age_seconds")) is int
            and event["payload"]["age_seconds"] <= APPROVAL_MAX_AGE_INCLUSIVE_SECONDS
        )
        receipt_sequences = tuple(
            sequence
            for event, _ in receipts
            if (sequence := _event_sequence(event)) is not None
        )
        if halt_seq is not None:
            observed.add("authorized_correction_is_publicly_recorded")
        if (
            halt_seq is not None
            and denial_seq is not None
            and resume_seq is not None
            and halt_seq < denial_seq < resume_seq
            and not any(
                halt_seq < sequence < resume_seq for sequence in receipt_sequences
            )
        ):
            observed.add("halted_action_is_denied_with_zero_effect")
        if process_boundary and denial_seq is not None and resume_seq is not None:
            observed.add("resume_occurs_after_recovery_gate")
        if len(fresh_post_resume) == 1 and receipt_sequences:
            approval_seq = _event_sequence(fresh_post_resume[0])
            if approval_seq is not None and approval_seq < min(receipt_sequences):
                observed.add("post_resume_approval_is_fresh")
        support.extend(
            item for item in (halt_id, denial_id, resume_id) if item is not None
        )
        support.extend(str(event["event_id"]) for event in fresh_post_resume)

    required = injector.required_public_proofs
    ordered_observed = tuple(proof for proof in required if proof in observed)
    return FailureProof(
        failure=failure,
        task_id=task_id,
        run_id=run_id,
        required_public_proofs=required,
        observed_public_proofs=ordered_observed,
        supporting_event_ids=tuple(dict.fromkeys(support)),
        process_boundary_proven=process_boundary,
        duplicate_logical_effects=duplicate_effects,
    )


def execute_change_phase(
    app: PublicApplication,
    *,
    arm: str,
    regime: str,
    task_id: str,
    change_signal: dict[str, object],
    secondary_signal: dict[str, object] | None,
    rebound_workflow: dict[str, object] | None,
    inputs: dict[str, object],
) -> ChangePhaseReceipt:
    """Deliver the arm-neutral change and execute the frozen arm transition."""

    if arm not in ARMS:
        raise ValueError(f"undeclared arm: {arm}")
    if regime not in REGIMES:
        raise ValueError(f"undeclared regime: {regime}")
    if type(task_id) is not str or not task_id:
        raise ValueError("task_id must be a nonblank string")
    change = _require_mapping(change_signal, "change_signal")
    run_inputs = _require_mapping(inputs, "inputs")
    calls: list[str] = []
    secondary_wait: SecondaryWaitEvidence | None = None

    app.signal_task(task_id, dict(change))
    calls.append("signal_task")
    app.signal_task(task_id, dict(change))
    calls.append("signal_task")

    if arm == "C" and regime != "R0_DIRECT_REFRESH":
        workflow = _require_mapping(rebound_workflow, "rebound_workflow")
        secondary = _require_mapping(secondary_signal, "secondary_signal")
        app.pause_task(task_id)
        calls.append("pause_task")
        app.replan_task(
            task_id,
            {
                "workflow": workflow,
                "reason": f"LH1A frozen topology selection for {regime}",
            },
        )
        calls.append("replan_task")
        app.run_task(task_id, dict(run_inputs))
        calls.append("run_task")
        app.signal_task(task_id, secondary)
        calls.append("signal_task")
        task = app.task_json(task_id)
        recovery = app.recovery_json(task_id)
        secondary_wait = _secondary_wait_from_projections(
            task, recovery, task_id, regime
        )
        calls.extend(("task_json", "recovery_json"))

    app.run_task(task_id, dict(run_inputs))
    calls.append("run_task")
    return ChangePhaseReceipt(
        arm=arm,
        regime=regime,
        task_id=task_id,
        public_calls=tuple(calls),
        secondary_wait=secondary_wait,
    )
