from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath


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
