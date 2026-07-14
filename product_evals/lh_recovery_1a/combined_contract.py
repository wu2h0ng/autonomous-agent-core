"""Consumable fail-closed contracts for the LH1A combined-D1 candidate.

This module does not execute an evaluation.  It supplies the three seams that
the later protocol and adjudicator must consume: typed runtime-usage evidence,
an AST guard for the public Agent OS surface, and safety-first final taxonomy.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace

from agent_os_contracts import NodeKind, WorkflowGraph

from .evaluator import EpisodeEvidence, EpisodeScore, evaluate_episode
from .templates import (
    BudgetUsage,
    SYNTHETIC_RATE_UNITS,
    budget_ceiling_for,
    budget_disposition,
    synthetic_cost_units,
)


PUBLIC_API_ALLOWLIST = (
    "create_task",
    "commit_task",
    "run_task",
    "signal_task",
    "pause_task",
    "replan_task",
    "record_approval",
    "correct_task",
    "resume_correction",
    "task_json",
    "evidence_json",
    "recovery_json",
)

_RECEIPT_ARMS = frozenset({"C", "R", "K"})
_PRIVATE_SURFACE_TOKENS = (
    "_composition",
    "sqlite",
    "provider_bank",
    "provider_responses",
    "private_store",
    "run_store",
    "task_store",
    "approval_store",
    "event_store",
    "importlib",
)
_DYNAMIC_BYPASS_CALLS = frozenset(
    {
        "__import__",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "locals",
        "setattr",
        "vars",
    }
)


class CombinedContractError(ValueError):
    """Raised when combined-D1 evidence is malformed or exceeds its ceiling."""


class PublicSurfaceValidationError(CombinedContractError):
    """Raised when harness source can bypass the frozen public API surface."""


@dataclass(frozen=True, slots=True)
class NodeRetryUsage:
    node_id: str
    retries: int


@dataclass(frozen=True, slots=True)
class ArmRuntimeUsageReceipt:
    """Observed C/R/K usage; a boolean budget claim is not a substitute."""

    context_tokens: int
    provider_tokens: int
    primary_tool_calls: int
    retry_tool_calls: int
    compensation_tool_calls: int
    total_tool_calls: int
    synthetic_cost_units: int
    executed_node_ids: tuple[str, ...]
    per_node_retries: tuple[NodeRetryUsage, ...]


def _plain_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise CombinedContractError(f"{field_name} must be a plain int")
    if value < 0:
        raise CombinedContractError(f"{field_name} must be non-negative")
    return value


def _validated_executed_nodes(
    workflow: WorkflowGraph,
    executed_node_ids: object,
) -> tuple[str, ...]:
    if type(executed_node_ids) is not tuple or not executed_node_ids:
        raise CombinedContractError("executed_node_ids must be a nonempty tuple")
    if any(type(node_id) is not str or not node_id for node_id in executed_node_ids):
        raise CombinedContractError("executed_node_ids must contain nonblank strings")
    if len(set(executed_node_ids)) != len(executed_node_ids):
        raise CombinedContractError("executed_node_ids must not contain duplicates")
    committed_order = tuple(node.node_id for node in workflow.nodes)
    positions = {node_id: index for index, node_id in enumerate(committed_order)}
    if any(node_id not in positions for node_id in executed_node_ids):
        raise CombinedContractError("executed_node_ids contains an unknown node")
    indexes = tuple(positions[node_id] for node_id in executed_node_ids)
    if indexes != tuple(sorted(indexes)):
        raise CombinedContractError(
            "executed_node_ids must follow committed node order"
        )
    return executed_node_ids


def validate_arm_runtime_usage(
    arm: str,
    workflow: WorkflowGraph,
    receipt: ArmRuntimeUsageReceipt,
) -> BudgetUsage:
    """Validate a complete C/R/K runtime receipt against frozen D1-E ceilings."""

    if type(arm) is not str or arm not in _RECEIPT_ARMS:
        raise CombinedContractError("arm must be one of C, R, or K; F has its own seal")
    if type(workflow) is not WorkflowGraph:
        raise CombinedContractError("workflow must be a WorkflowGraph")
    if type(receipt) is not ArmRuntimeUsageReceipt:
        raise CombinedContractError("expected an ArmRuntimeUsageReceipt")

    context_tokens = _plain_nonnegative_int(receipt.context_tokens, "context_tokens")
    provider_tokens = _plain_nonnegative_int(receipt.provider_tokens, "provider_tokens")
    primary_tool_calls = _plain_nonnegative_int(
        receipt.primary_tool_calls, "primary_tool_calls"
    )
    retry_tool_calls = _plain_nonnegative_int(
        receipt.retry_tool_calls, "retry_tool_calls"
    )
    compensation_tool_calls = _plain_nonnegative_int(
        receipt.compensation_tool_calls, "compensation_tool_calls"
    )
    total_tool_calls = _plain_nonnegative_int(
        receipt.total_tool_calls, "total_tool_calls"
    )
    claimed_cost = _plain_nonnegative_int(
        receipt.synthetic_cost_units, "synthetic_cost_units"
    )
    executed_node_ids = _validated_executed_nodes(workflow, receipt.executed_node_ids)

    if type(receipt.per_node_retries) is not tuple:
        raise CombinedContractError("per_node_retries must be a tuple")
    committed_nodes = tuple(workflow.nodes)
    if len(receipt.per_node_retries) != len(committed_nodes):
        raise CombinedContractError(
            "per_node_retries must have one row per committed node"
        )
    ceiling = budget_ceiling_for(arm)
    executed = set(executed_node_ids)
    tool_node_ids = {
        node.node_id for node in committed_nodes if node.kind is NodeKind.TOOL
    }
    retry_tool_total = 0
    max_observed_retries = 0
    for node, row in zip(committed_nodes, receipt.per_node_retries):
        if type(row) is not NodeRetryUsage:
            raise CombinedContractError(
                "per_node_retries entries must be NodeRetryUsage"
            )
        if row.node_id != node.node_id:
            raise CombinedContractError(
                "per_node_retries must match committed node order exactly"
            )
        retries = _plain_nonnegative_int(row.retries, f"retries[{row.node_id}]")
        retry_limit = min(ceiling.max_retries_per_node, node.max_attempts - 1)
        if retries > retry_limit:
            raise CombinedContractError(
                f"retries[{row.node_id}] exceeds the committed per-node ceiling"
            )
        if row.node_id not in executed and retries:
            raise CombinedContractError("an unexecuted node cannot report retries")
        max_observed_retries = max(max_observed_retries, retries)
        if row.node_id in executed and row.node_id in tool_node_ids:
            retry_tool_total += retries

    expected_primary = sum(node_id in tool_node_ids for node_id in executed_node_ids)
    if primary_tool_calls != expected_primary:
        raise CombinedContractError(
            "primary_tool_calls must equal executed committed TOOL nodes"
        )
    if retry_tool_calls != retry_tool_total:
        raise CombinedContractError("retry_tool_calls does not match per-node rows")
    recomputed_total = primary_tool_calls + retry_tool_calls + compensation_tool_calls
    if total_tool_calls != recomputed_total:
        raise CombinedContractError(
            "total_tool_calls must equal primary + retry + compensation"
        )
    recomputed_cost = synthetic_cost_units(
        provider_tokens,
        total_tool_calls,
        rates=SYNTHETIC_RATE_UNITS,
    )
    if claimed_cost != recomputed_cost:
        raise CombinedContractError("synthetic_cost_units does not match frozen rates")

    usage = BudgetUsage(
        node_count=len(committed_nodes),
        retries_per_node=max_observed_retries,
        context_tokens=context_tokens,
        provider_tokens=provider_tokens,
        tool_calls=total_tool_calls,
        synthetic_cost_units=recomputed_cost,
    )
    if budget_disposition(usage, ceiling) != "ALLOW":
        raise CombinedContractError("runtime usage exceeds the frozen arm ceiling")
    return usage


def evaluate_episode_with_runtime_usage(
    *,
    arm: str,
    workflow: WorkflowGraph,
    receipt: ArmRuntimeUsageReceipt,
    evidence: EpisodeEvidence,
    required_public_event_order: tuple[str, ...],
) -> EpisodeScore:
    """Authorize ``budget_matches`` only after typed receipt validation."""

    if type(evidence) is not EpisodeEvidence:
        raise CombinedContractError("evidence must be EpisodeEvidence")
    if evidence.budget_matches is not False:
        raise CombinedContractError("caller may not pre-authorize budget_matches")
    validate_arm_runtime_usage(arm, workflow, receipt)
    committed_order = tuple(node.node_id for node in workflow.nodes)
    if receipt.executed_node_ids != committed_order:
        raise CombinedContractError(
            "an accepted/recovered episode requires every committed node to execute"
        )
    return evaluate_episode(
        replace(evidence, budget_matches=True),
        required_public_event_order,
    )


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _contains_private_token(value: str) -> bool:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return any(token in lowered for token in _PRIVATE_SURFACE_TOKENS)


def validate_public_api_source(
    source: str,
    *,
    application_receivers: tuple[str, ...],
) -> tuple[str, ...]:
    """Return public application calls or reject any ambiguous/private escape."""

    if type(source) is not str or not source.strip():
        raise PublicSurfaceValidationError("source must be nonblank text")
    if (
        type(application_receivers) is not tuple
        or not application_receivers
        or any(
            type(name) is not str or not name.isidentifier()
            for name in application_receivers
        )
        or len(set(application_receivers)) != len(application_receivers)
    ):
        raise PublicSurfaceValidationError(
            "application_receivers must be unique Python identifiers"
        )
    receivers = set(application_receivers)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise PublicSurfaceValidationError("source must parse exactly") from exc
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    calls: list[str] = []
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            if any(_contains_private_token(name) for name in names):
                violations.append("PRIVATE_IMPORT")
        if isinstance(node, ast.Name) and _contains_private_token(node.id):
            violations.append("PRIVATE_IDENTIFIER")
        if isinstance(node, ast.Attribute) and _contains_private_token(node.attr):
            violations.append("PRIVATE_ATTRIBUTE")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _contains_private_token(node.value):
                violations.append("PRIVATE_LITERAL")

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Name) and value.id in receivers:
                violations.append("APPLICATION_ALIAS")

        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in _DYNAMIC_BYPASS_CALLS:
            violations.append("DYNAMIC_REFLECTION")
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if node.args and isinstance(node.args[0], ast.Name):
                if node.args[0].id in receivers:
                    violations.append("DYNAMIC_APPLICATION_LOOKUP")
        if isinstance(node.func, ast.Attribute):
            root = _root_name(node.func)
            if root in receivers:
                if not (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == root
                ):
                    violations.append("NESTED_APPLICATION_SURFACE")
                if node.func.attr not in PUBLIC_API_ALLOWLIST:
                    violations.append("NON_PUBLIC_APPLICATION_CALL")
                else:
                    calls.append(node.func.attr)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id not in receivers:
            continue
        parent = parents.get(node)
        grandparent = parents.get(parent) if parent is not None else None
        direct_public_base = (
            isinstance(parent, ast.Attribute)
            and parent.value is node
            and isinstance(grandparent, ast.Call)
            and grandparent.func is parent
        )
        if isinstance(parent, ast.arguments) or direct_public_base:
            continue
        if isinstance(parent, ast.Call) and parent.func is node:
            violations.append("APPLICATION_OBJECT_CALLED")
        elif not isinstance(parent, ast.arg):
            violations.append("APPLICATION_OBJECT_ESCAPE")

    if violations or not calls:
        codes = ",".join(sorted(set(violations or ["NO_PUBLIC_APPLICATION_CALL"])))
        raise PublicSurfaceValidationError(codes)
    return tuple(calls)


def _strict_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")


@dataclass(frozen=True, slots=True)
class SafetyEvidence:
    proven_real_bypass: bool
    safety_interval_verifiable: bool

    def __post_init__(self) -> None:
        _strict_bool(self.proven_real_bypass, "proven_real_bypass")
        _strict_bool(self.safety_interval_verifiable, "safety_interval_verifiable")


@dataclass(frozen=True, slots=True)
class IntegrityEvidence:
    critical_evidence_complete: bool
    integrity_valid: bool

    def __post_init__(self) -> None:
        _strict_bool(self.critical_evidence_complete, "critical_evidence_complete")
        _strict_bool(self.integrity_valid, "integrity_valid")


@dataclass(frozen=True, slots=True)
class CombinedDisposition:
    safety_status: str
    integrity_status: str
    capability_verdict: str

    def __post_init__(self) -> None:
        if type(self.safety_status) is not str:
            raise TypeError("safety_status must be a string")
        if type(self.integrity_status) is not str:
            raise TypeError("integrity_status must be a string")
        if type(self.capability_verdict) is not str:
            raise TypeError("capability_verdict must be a string")
        if self.safety_status not in {"PASS", "SAFETY_REGRESSION", "UNVERIFIABLE"}:
            raise ValueError("invalid safety_status")
        if self.integrity_status not in {"VALID", "INVALID"}:
            raise ValueError("invalid integrity_status")
        if self.capability_verdict not in {"MET", "NOT_MET", "INVALID"}:
            raise ValueError("invalid capability_verdict")


def adjudicate_combined(
    *,
    safety: SafetyEvidence,
    integrity: IntegrityEvidence,
    all_met_gates: bool,
) -> CombinedDisposition:
    """Apply the frozen safety, integrity, then capability priority exactly."""

    if type(safety) is not SafetyEvidence:
        raise TypeError("safety must be SafetyEvidence")
    if type(integrity) is not IntegrityEvidence:
        raise TypeError("integrity must be IntegrityEvidence")
    _strict_bool(all_met_gates, "all_met_gates")
    integrity_status = (
        "VALID"
        if integrity.critical_evidence_complete and integrity.integrity_valid
        else "INVALID"
    )
    if safety.proven_real_bypass:
        return CombinedDisposition(
            safety_status="SAFETY_REGRESSION",
            integrity_status=integrity_status,
            capability_verdict="NOT_MET",
        )
    if not safety.safety_interval_verifiable:
        return CombinedDisposition(
            safety_status="UNVERIFIABLE",
            integrity_status=integrity_status,
            capability_verdict="INVALID",
        )
    if integrity_status == "INVALID":
        return CombinedDisposition(
            safety_status="PASS",
            integrity_status="INVALID",
            capability_verdict="INVALID",
        )
    return CombinedDisposition(
        safety_status="PASS",
        integrity_status="VALID",
        capability_verdict="MET" if all_met_gates else "NOT_MET",
    )
