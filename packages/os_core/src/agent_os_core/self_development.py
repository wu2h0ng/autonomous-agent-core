from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from agent_os_contracts import EdgeSpec, IdempotencyMode, NodeKind, NodeSpec, WorkflowGraph


INVALID_SELFDEV_TARGET = "INVALID_SELFDEV_TARGET"
RUN_DENIED = "RUN_DENIED"

_AGENT_OS_REPOSITORIES = frozenset({"autonomous-agent-core", "agent-os"})
_AGENT_OS_TARGET_PREFIXES = (
    "packages/os_core/src/agent_os_core/",
    "packages/contracts/src/agent_os_contracts/",
    "apps/api_server/",
    "apps/cli/",
    "tests/product/",
    "docs/product/",
    "docs/architecture/",
)
_ALLOWLISTED_VERIFIERS = frozenset(
    {
        "pytest",
        "python -m pytest",
        "python3 -m pytest",
        "ruff check",
        "pyright",
    }
)
_ROLLBACK_STRATEGIES = frozenset(
    {"compensate_task", "restore_preimage", "git_worktree_reset"}
)
_DENIED_BRANCH_NAMES = frozenset({"main", "master", "release"})


class SelfDevelopmentValidationError(ValueError):
    """Raised when a candidate self-development task is outside SELFDEV-S1."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SelfDevelopmentTaskSpec:
    """Product contract for a rollback-safe Agent OS self-development task."""

    mandate_id: str
    repository_id: str
    repository_head: str
    isolated_workspace: str
    isolated_branch: str
    target_path: str
    verifier_commands: tuple[str, ...]
    expected_outcome_id: str
    rollback_strategy: str
    operator_intervention_count: int
    hcw_minutes: float
    baseline_assignment_id: str


@dataclass(frozen=True)
class SelfDevelopmentReceipt:
    """Content-bound admission receipt for SELFDEV-S1 execution."""

    mandate_id: str
    repository_id: str
    repository_head: str
    isolated_workspace: str
    isolated_branch: str
    target_path: str
    verifier_commands: tuple[str, ...]
    expected_outcome_id: str
    rollback_strategy: str
    operator_intervention_count: int
    hcw_minutes: float
    baseline_assignment_id: str
    receipt_digest: str


@dataclass(frozen=True)
class SelfDevelopmentTaskPackage:
    """Prepared Task/Run package for the existing Agent OS execution spine."""

    admission_receipt: SelfDevelopmentReceipt
    task_commit_payload: dict[str, object]
    run_inputs: dict[str, object]


def validate_self_development_task(
    spec: SelfDevelopmentTaskSpec,
) -> SelfDevelopmentReceipt:
    """Validate and bind the first Agent OS self-development slice."""

    _require_nonempty("mandate_id", spec.mandate_id)
    if spec.repository_id not in _AGENT_OS_REPOSITORIES:
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "repository_id must identify the Agent OS repository",
        )
    _require_nonempty("repository_head", spec.repository_head)
    _require_nonempty("isolated_workspace", spec.isolated_workspace)
    _validate_isolated_branch(spec.isolated_branch)
    target_path = _validate_target_path(spec.target_path)
    verifier_commands = _validate_verifier_commands(spec.verifier_commands)
    _require_nonempty("expected_outcome_id", spec.expected_outcome_id)
    if spec.rollback_strategy not in _ROLLBACK_STRATEGIES:
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "rollback_strategy is not allowlisted for SELFDEV-S1",
        )
    if spec.operator_intervention_count < 0:
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "operator_intervention_count must be non-negative",
        )
    if spec.hcw_minutes < 0:
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "hcw_minutes must be non-negative",
        )
    _require_nonempty("baseline_assignment_id", spec.baseline_assignment_id)

    payload = {
        "mandate_id": spec.mandate_id,
        "repository_id": spec.repository_id,
        "repository_head": spec.repository_head,
        "isolated_workspace": spec.isolated_workspace,
        "isolated_branch": spec.isolated_branch,
        "target_path": target_path,
        "verifier_commands": verifier_commands,
        "expected_outcome_id": spec.expected_outcome_id,
        "rollback_strategy": spec.rollback_strategy,
        "operator_intervention_count": spec.operator_intervention_count,
        "hcw_minutes": spec.hcw_minutes,
        "baseline_assignment_id": spec.baseline_assignment_id,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return SelfDevelopmentReceipt(receipt_digest=digest, **payload)


def prepare_self_development_task_package(
    spec: SelfDevelopmentTaskSpec,
    *,
    task_id: str,
    created_at: datetime | None = None,
    statement: str | None = None,
    duration_seconds: int = 300,
    max_cost_usd: str = "1",
    max_provider_tokens: int = 1000,
    max_tool_calls: int = 10,
) -> SelfDevelopmentTaskPackage:
    """Compile a validated SELFDEV spec into the existing Task/Run contracts.

    This does not create, approve or run a task. It prepares the payload that the
    existing ``task-commit`` and ``task-run`` surfaces already consume.
    """

    _require_nonempty("task_id", task_id)
    if duration_seconds <= 0:
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "duration_seconds must be positive",
        )
    if max_provider_tokens <= 0 or max_tool_calls <= 0:
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "provider token and tool-call budgets must be positive",
        )
    receipt = validate_self_development_task(spec)
    now = created_at or datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=duration_seconds)
    goal_id = f"goal:selfdev:{receipt.receipt_digest[:12]}"
    package_statement = statement or (
        "Agent OS self-development repository task for "
        f"{receipt.target_path}"
    )
    task_commit_payload: dict[str, object] = {
        "commitment": {
            "commitment_id": f"commitment:selfdev:{receipt.receipt_digest[:12]}",
            "task_id": task_id,
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "accepted_by": "user:local",
            "accepted_at": now.isoformat(),
            "deliverables": [
                "Agent OS repository patch",
                f"SELFDEV admission receipt {receipt.receipt_digest}",
            ],
            "acceptance_criteria": [
                "admission receipt validates SELFDEV target",
                "exact-digest approval is recorded before patch effect",
                "allowlisted verifier evidence is content-bound",
                "compensation restores pre-change bytes",
            ],
            "authority_scopes": ["workspace:read", "workspace:write"],
            "budget": {
                "max_cost_usd": max_cost_usd,
                "max_duration_seconds": duration_seconds,
                "max_provider_tokens": max_provider_tokens,
                "max_tool_calls": max_tool_calls,
            },
            "risk_tier": 1,
            "exit_conditions": ["verified", "compensated on failure"],
            "expires_at": expires_at.isoformat(),
        },
        "workflow": _selfdev_workflow(now).model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": receipt.expected_outcome_id,
            "task_id": task_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "evaluator_type": "pytest",
            "evaluator_version": "1",
            "evidence_requirements": ["test-report"],
            "failure_semantics": ["non-zero exit"],
            "threshold": 1,
            "observation_window_seconds": duration_seconds,
            "frozen_at": now.isoformat(),
        },
        "selfdev_admission_receipt": _receipt_dict(receipt),
        "statement": package_statement,
    }
    return SelfDevelopmentTaskPackage(
        admission_receipt=receipt,
        task_commit_payload=task_commit_payload,
        run_inputs={
            "target_path": receipt.target_path,
            "test_command": receipt.verifier_commands[0],
        },
    )


def _selfdev_workflow(created_at: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider",
            kind=NodeKind.PROVIDER,
            capability="provider.chat",
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(
        EdgeSpec(source=source, target=target)
        for source, target in (
            ("read", "provider"),
            ("provider", "approve"),
            ("approve", "apply"),
            ("apply", "tests"),
            ("tests", "evaluate"),
            ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        workflow_id="workflow:selfdev-s2",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=created_at,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
    )


def _validate_target_path(value: str) -> str:
    _require_nonempty("target_path", value)
    if value.startswith("/") or "\\" in value:
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "target_path must be a relative POSIX path",
        )
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "target_path must not contain empty, current or parent segments",
        )
    if any(part.startswith(".") for part in path.parts):
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "target_path must not target hidden repository control state",
        )
    normalized = path.as_posix()
    if not normalized.startswith(_AGENT_OS_TARGET_PREFIXES):
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            "target_path must belong to Agent OS code, product tests or product docs",
        )
    return normalized


def _validate_verifier_commands(commands: tuple[str, ...]) -> tuple[str, ...]:
    if not commands:
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "at least one verifier command is required",
        )
    normalized: list[str] = []
    for command in commands:
        cleaned = " ".join(command.split())
        if cleaned not in _ALLOWLISTED_VERIFIERS:
            raise SelfDevelopmentValidationError(
                RUN_DENIED,
                f"verifier command is not allowlisted: {command}",
            )
        normalized.append(cleaned)
    return tuple(normalized)


def _validate_isolated_branch(value: str) -> None:
    _require_nonempty("isolated_branch", value)
    if value in _DENIED_BRANCH_NAMES or value.startswith("release"):
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "SELFDEV-S1 cannot execute on main/master/release branches",
        )


def _require_nonempty(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SelfDevelopmentValidationError(
            INVALID_SELFDEV_TARGET,
            f"{field} is required",
        )


def _receipt_dict(receipt: SelfDevelopmentReceipt) -> dict[str, object]:
    return {
        "mandate_id": receipt.mandate_id,
        "repository_id": receipt.repository_id,
        "repository_head": receipt.repository_head,
        "isolated_workspace": receipt.isolated_workspace,
        "isolated_branch": receipt.isolated_branch,
        "target_path": receipt.target_path,
        "verifier_commands": list(receipt.verifier_commands),
        "expected_outcome_id": receipt.expected_outcome_id,
        "rollback_strategy": receipt.rollback_strategy,
        "operator_intervention_count": receipt.operator_intervention_count,
        "hcw_minutes": receipt.hcw_minutes,
        "baseline_assignment_id": receipt.baseline_assignment_id,
        "receipt_digest": receipt.receipt_digest,
    }
