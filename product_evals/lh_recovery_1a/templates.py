"""Frozen LH-RECOVERY-1A candidate, restart, and budget templates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agent_os_contracts import NodeKind, WorkflowGraph
from agent_os_contracts.workflow import EdgeSpec, NodeSpec

from product_evals.lh_recovery_1a.regimes import REGIME_SPECS


CANDIDATE_WORKFLOW_ID = "lh1a-candidate"
POLICY_VERSION = "lh1a-d1e-v1"
CREATED_BY = "lh1a-d1e-environment"
CREATED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
EVALUATOR_REFS = ("evaluator:lh1a:1",)
CASE_PLACEHOLDER = "{case_id}"

ARMS = ("C", "F", "R", "K")

COMPLETED_PREFIX = ("read_v1", "provider_v1", "wait_change")
REGIME_SUFFIXES: dict[str, tuple[str, ...]] = {
    "R0_DIRECT_REFRESH": (
        "read_v2",
        "provider_v2",
        "approval",
        "apply",
        "test",
        "evaluate",
        "done",
    ),
    "R1_DEPENDENCY_BEFORE_PROVIDER": (
        "read_v2",
        "wait_dependency",
        "provider_v2",
        "approval",
        "apply",
        "test",
        "evaluate",
        "done",
    ),
    "R2_RELEASE_BEFORE_APPLY": (
        "read_v2",
        "provider_v2",
        "wait_release",
        "approval",
        "apply",
        "test",
        "evaluate",
        "done",
    ),
}


def _node(
    node_id: str, kind: str, input_contract: str, output_contract: str, **extra: object
) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        kind=kind,
        input_contract=input_contract,
        output_contract=output_contract,
        **extra,
    )


NODE_TEMPLATES: dict[str, NodeSpec] = {
    "read_v1": _node(
        "read_v1",
        "tool",
        "contract:lh1a-case-fixture:1",
        "contract:lh1a-workspace-snapshot-v1:1",
        capability="workspace.read",
        idempotency="idempotent",
    ),
    "provider_v1": _node(
        "provider_v1",
        "provider",
        "contract:lh1a-workspace-snapshot-v1:1",
        "contract:lh1a-provider-response-v1:1",
        capability="provider.chat",
        timeout_seconds=120,
        idempotency="idempotent",
    ),
    "wait_change": _node(
        "wait_change",
        "wait_event",
        "contract:lh1a-provider-response-v1:1",
        "contract:lh1a-change-notice:1",
        timeout_seconds=21600,
        wait_signal_name="requirement.changed",
        wait_correlation_key=f"case:{CASE_PLACEHOLDER}:change",
    ),
    "read_v2": _node(
        "read_v2",
        "tool",
        "contract:lh1a-change-notice:1",
        "contract:lh1a-provider-context-v2:1",
        capability="workspace.read",
        idempotency="idempotent",
    ),
    "wait_dependency": _node(
        "wait_dependency",
        "wait_event",
        "contract:lh1a-provider-context-v2:1",
        "contract:lh1a-provider-context-v2:1",
        timeout_seconds=300,
        wait_signal_name="dependency.ready",
        wait_correlation_key=f"case:{CASE_PLACEHOLDER}:dependency",
    ),
    "provider_v2": _node(
        "provider_v2",
        "provider",
        "contract:lh1a-provider-context-v2:1",
        "contract:lh1a-action-proposal-v2:1",
        capability="provider.chat",
        timeout_seconds=120,
        idempotency="idempotent",
    ),
    "wait_release": _node(
        "wait_release",
        "wait_event",
        "contract:lh1a-action-proposal-v2:1",
        "contract:lh1a-action-proposal-v2:1",
        timeout_seconds=300,
        wait_signal_name="release.ready",
        wait_correlation_key=f"case:{CASE_PLACEHOLDER}:release",
    ),
    "approval": _node(
        "approval",
        "approval",
        "contract:lh1a-action-proposal-v2:1",
        "contract:lh1a-approval-decision:1",
        timeout_seconds=600,
        risk_tier=1,
    ),
    "apply": _node(
        "apply",
        "tool",
        "contract:lh1a-approval-decision:1",
        "contract:lh1a-apply-receipt:1",
        capability="workspace.apply_patch",
        timeout_seconds=120,
        risk_tier=1,
        idempotency="compensatable",
    ),
    "test": _node(
        "test",
        "tool",
        "contract:lh1a-apply-receipt:1",
        "contract:lh1a-test-result:1",
        capability="workspace.run_tests",
        timeout_seconds=300,
        idempotency="idempotent",
    ),
    "evaluate": _node(
        "evaluate",
        "evaluation",
        "contract:lh1a-test-result:1",
        "contract:lh1a-episode-score:1",
    ),
    "done": _node(
        "done",
        "terminal",
        "contract:lh1a-episode-score:1",
        "contract:lh1a-terminal-receipt:1",
    ),
}


@dataclass(frozen=True, slots=True)
class BudgetCeiling:
    max_nodes: int
    max_retries_per_node: int
    max_context_tokens: int
    max_provider_tokens: int
    max_tool_calls: int
    max_synthetic_cost_units: int


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    node_count: int
    retries_per_node: int
    context_tokens: int
    provider_tokens: int
    tool_calls: int
    synthetic_cost_units: int


@dataclass(frozen=True, slots=True)
class HumanCharges:
    approval_minutes: float
    topology_selection_minutes: float
    correction_resume_minutes: float
    task_recreate_additional_minutes: float


@dataclass(frozen=True, slots=True)
class SyntheticRateUnits:
    provider_token_units: int
    tool_call_units: int


@dataclass(frozen=True, slots=True)
class CommonInformationEnvelope:
    fixture_schema: str
    change_notice_schema: str
    event_journal_schema: str
    provider_response_channel: str
    retry_ceiling: int
    context_ceiling: int
    tool_ceiling: int
    token_ceiling: int
    synthetic_cost_ceiling: int
    evaluator_contract: str
    failure_declaration: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InformationEnvelope:
    budget_ceiling: BudgetCeiling
    topology_selection_human_minutes: float
    budget_usage: BudgetUsage


@dataclass(frozen=True, slots=True)
class CandidateTemplate:
    workflow: WorkflowGraph
    budget_ceiling: BudgetCeiling
    completed_prefix: tuple[str, ...]
    post_change_nodes: tuple[str, ...]
    required_replans: int
    base_version: int
    version_increment: int


@dataclass(frozen=True, slots=True)
class RestartTemplate:
    workflow: WorkflowGraph
    budget_ceiling: BudgetCeiling


@dataclass(frozen=True, slots=True)
class InstantiatedCandidate:
    workflow: WorkflowGraph


FIXED_CEILING = BudgetCeiling(
    max_nodes=11,
    max_retries_per_node=1,
    max_context_tokens=8192,
    max_provider_tokens=4096,
    max_tool_calls=4,
    max_synthetic_cost_units=10000,
)
BUDGET_CEILINGS: dict[str, BudgetCeiling] = {
    "C": FIXED_CEILING,
    "F": FIXED_CEILING,
    "R": FIXED_CEILING,
    "K": FIXED_CEILING,
}

HUMAN_CHARGES = HumanCharges(
    approval_minutes=0.5,
    topology_selection_minutes=2.0,
    correction_resume_minutes=1.0,
    task_recreate_additional_minutes=0.0,
)
SYNTHETIC_RATE_UNITS = SyntheticRateUnits(
    provider_token_units=1,
    tool_call_units=1000,
)
TOPOLOGY_SELECTION_HUMAN_MINUTES = 2.0

_HUMAN_CHARGE_KEYS = {
    "APPROVAL": "approval_minutes",
    "TOPOLOGY_SELECTION": "topology_selection_minutes",
    "CORRECTION_RESUME": "correction_resume_minutes",
    "TASK_RECREATE": "task_recreate_additional_minutes",
}


def _require_regime(regime: str) -> tuple[str, ...]:
    suffix = REGIME_SUFFIXES.get(regime)
    if suffix is None:
        raise ValueError(f"undeclared regime: {regime}")
    return suffix


def _sequential_edges(node_ids: tuple[str, ...]) -> tuple[EdgeSpec, ...]:
    return tuple(
        EdgeSpec(source=source, target=target)
        for source, target in zip(node_ids, node_ids[1:])
    )


def _build_workflow(
    *,
    workflow_id: str,
    version: int,
    max_replans: int,
    node_ids: tuple[str, ...],
) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=workflow_id,
        version=version,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by=CREATED_BY,
        created_at=CREATED_AT,
        policy_version=POLICY_VERSION,
        evaluator_refs=EVALUATOR_REFS,
        nodes=tuple(NODE_TEMPLATES[node_id] for node_id in node_ids),
        edges=_sequential_edges(node_ids),
        max_replans=max_replans,
    )


def budget_ceiling_for(arm: str) -> BudgetCeiling:
    ceiling = BUDGET_CEILINGS.get(arm)
    if ceiling is None:
        raise ValueError(f"undeclared arm: {arm}")
    return ceiling


def candidate_template_for(regime: str) -> CandidateTemplate:
    suffix = _require_regime(regime)
    is_initial = regime == "R0_DIRECT_REFRESH"
    version = 1 if is_initial else 2
    node_ids = COMPLETED_PREFIX + suffix
    workflow = _build_workflow(
        workflow_id=CANDIDATE_WORKFLOW_ID,
        version=version,
        max_replans=1,
        node_ids=node_ids,
    )
    return CandidateTemplate(
        workflow=workflow,
        budget_ceiling=budget_ceiling_for("C"),
        completed_prefix=COMPLETED_PREFIX,
        post_change_nodes=suffix,
        required_replans=0 if is_initial else 1,
        base_version=1,
        version_increment=version - 1,
    )


def candidate_initial_template() -> CandidateTemplate:
    return candidate_template_for("R0_DIRECT_REFRESH")


def restart_template_for(regime: str) -> RestartTemplate:
    suffix = _require_regime(regime)
    workflow_id = "lh1a-restart-" + regime.lower().replace("_", "-")
    workflow = _build_workflow(
        workflow_id=workflow_id,
        version=1,
        max_replans=0,
        node_ids=suffix,
    )
    return RestartTemplate(workflow=workflow, budget_ceiling=budget_ceiling_for("R"))


def _instantiate_nodes(node_ids: tuple[str, ...], case_id: str) -> tuple[NodeSpec, ...]:
    instantiated = []
    for node_id in node_ids:
        node = NODE_TEMPLATES[node_id]
        if node.kind is NodeKind.WAIT_EVENT:
            node = node.model_copy(
                update={
                    "wait_correlation_key": node.wait_correlation_key.replace(
                        CASE_PLACEHOLDER, case_id
                    )
                }
            )
        instantiated.append(node)
    return tuple(instantiated)


def _instantiate_workflow(
    *,
    workflow_id: str,
    version: int,
    max_replans: int,
    node_ids: tuple[str, ...],
    case_id: str,
) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=workflow_id,
        version=version,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by=CREATED_BY,
        created_at=CREATED_AT,
        policy_version=POLICY_VERSION,
        evaluator_refs=EVALUATOR_REFS,
        nodes=_instantiate_nodes(node_ids, case_id),
        edges=_sequential_edges(node_ids),
        max_replans=max_replans,
    )


def instantiate_candidate_for(regime: str, *, case_id: str) -> InstantiatedCandidate:
    suffix = _require_regime(regime)
    version = 1 if regime == "R0_DIRECT_REFRESH" else 2
    node_ids = COMPLETED_PREFIX + suffix
    workflow = _instantiate_workflow(
        workflow_id=CANDIDATE_WORKFLOW_ID,
        version=version,
        max_replans=1,
        node_ids=node_ids,
        case_id=case_id,
    )
    return InstantiatedCandidate(workflow=workflow)


def instantiate_candidate_initial(case_id: str) -> InstantiatedCandidate:
    return instantiate_candidate_for("R0_DIRECT_REFRESH", case_id=case_id)


def validate_instantiated_workflow(
    workflow: WorkflowGraph,
    *,
    case_id: str,
) -> tuple[str, ...]:
    codes: list[str] = []
    for node in workflow.nodes:
        if node.kind is not NodeKind.WAIT_EVENT:
            continue
        key = node.wait_correlation_key or ""
        if "{" in key or "}" in key:
            codes.append("UNRESOLVED_PLACEHOLDER")
            continue
        parts = key.split(":")
        if len(parts) >= 2 and parts[0] == "case" and parts[1] != case_id:
            codes.append("CORRELATION_CASE_MISMATCH")
    return tuple(codes)


def fixed_ceiling_from_candidate_templates(
    workflows: tuple[object, ...],
) -> BudgetCeiling:
    if not workflows:
        raise ValueError("at least one candidate workflow is required")
    max_nodes = max(len(workflow.nodes) for workflow in workflows)
    if max_nodes > FIXED_CEILING.max_nodes:
        raise ValueError("candidate template exceeds the fixed node ceiling")
    return FIXED_CEILING


def budget_disposition(usage: BudgetUsage, ceiling: BudgetCeiling) -> str:
    checks = (
        (usage.node_count, ceiling.max_nodes),
        (usage.retries_per_node, ceiling.max_retries_per_node),
        (usage.context_tokens, ceiling.max_context_tokens),
        (usage.provider_tokens, ceiling.max_provider_tokens),
        (usage.tool_calls, ceiling.max_tool_calls),
        (usage.synthetic_cost_units, ceiling.max_synthetic_cost_units),
    )
    for value, limit in checks:
        if value < 0 or value > limit:
            return "DENY"
    return "ALLOW"


def _budget_usage_for(regime: str) -> BudgetUsage:
    node_count = len(candidate_template_for(regime).workflow.nodes)
    provider_tokens = FIXED_CEILING.max_provider_tokens
    tool_calls = FIXED_CEILING.max_tool_calls
    return BudgetUsage(
        node_count=node_count,
        retries_per_node=FIXED_CEILING.max_retries_per_node,
        context_tokens=FIXED_CEILING.max_context_tokens,
        provider_tokens=provider_tokens,
        tool_calls=tool_calls,
        synthetic_cost_units=synthetic_cost_units(
            provider_tokens, tool_calls, rates=SYNTHETIC_RATE_UNITS
        ),
    )


def common_information_envelope(arm: str, regime: str) -> CommonInformationEnvelope:
    budget_ceiling_for(arm)
    _require_regime(regime)
    return CommonInformationEnvelope(
        fixture_schema="contract:lh1a-case-fixture:1",
        change_notice_schema="lh1a-change-notice-v1",
        event_journal_schema="lh1a-event-journal-v1",
        provider_response_channel="contract:lh1a-provider-response-v1:1",
        retry_ceiling=FIXED_CEILING.max_retries_per_node,
        context_ceiling=FIXED_CEILING.max_context_tokens,
        tool_ceiling=FIXED_CEILING.max_tool_calls,
        token_ceiling=FIXED_CEILING.max_provider_tokens,
        synthetic_cost_ceiling=FIXED_CEILING.max_synthetic_cost_units,
        evaluator_contract="evaluator:lh1a:1",
        failure_declaration=tuple(REGIME_SPECS),
    )


def information_envelope(arm: str, regime: str) -> InformationEnvelope:
    _require_regime(regime)
    return InformationEnvelope(
        budget_ceiling=budget_ceiling_for(arm),
        topology_selection_human_minutes=TOPOLOGY_SELECTION_HUMAN_MINUTES,
        budget_usage=_budget_usage_for(regime),
    )


def human_charge_minutes(charge: str) -> float:
    attribute = _HUMAN_CHARGE_KEYS.get(charge)
    if attribute is None:
        raise ValueError(f"undeclared human charge: {charge}")
    return getattr(HUMAN_CHARGES, attribute)


def human_minutes_for(
    *,
    approvals: int,
    topology_selections: int,
    correction_resumes: int,
    task_recreates: int,
    charges: HumanCharges,
) -> float:
    counts = (approvals, topology_selections, correction_resumes, task_recreates)
    if any(count < 0 for count in counts):
        raise ValueError("human charge counts must be non-negative")
    return (
        approvals * charges.approval_minutes
        + topology_selections * charges.topology_selection_minutes
        + correction_resumes * charges.correction_resume_minutes
        + task_recreates * charges.task_recreate_additional_minutes
    )


def synthetic_cost_units(
    provider_tokens: int,
    tool_calls: int,
    *,
    rates: SyntheticRateUnits,
) -> int:
    if provider_tokens < 0 or tool_calls < 0:
        raise ValueError("synthetic cost inputs must be non-negative")
    return (
        provider_tokens * rates.provider_token_units
        + tool_calls * rates.tool_call_units
    )
