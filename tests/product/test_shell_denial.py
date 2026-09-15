"""S1 (descoped): every dev-shell denial carries an enumerable, typed reason."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import ActionContract, CorrectionEpochVector, ResourceBudget
from agent_os_core import CapabilityDenied
from domain_packs.developer_agent.shell_denial import (
    ShellCommandDenied,
    ShellDenialReason,
    require_allowlisted_command,
)
from domain_packs.developer_agent.workspace_capability import DeveloperWorkspaceAdapter


def _shell_action(command: str) -> ActionContract:
    now = datetime.now(timezone.utc)
    return ActionContract(
        action_id="action:denial",
        task_id="task:denial",
        run_id="run:denial",
        node_id="node:denial",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.shell",
        capability_version="1",
        arguments_json=json.dumps({"command": command}),
        risk_tier=3,
        idempotency_key="idem:denial",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=30,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:denial",
        candidate_envelope_id="envelope:denial",
        created_at=now,
    )


def test_allowlisted_command_passes(tmp_path: Path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("git status",))
    adapter.preflight("workspace.shell", {"command": "git status"}, "key-1")


def test_unlisted_command_is_denied_with_enumerable_reason(tmp_path: Path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("git status",))
    with pytest.raises(ShellCommandDenied) as excinfo:
        adapter.preflight("workspace.shell", {"command": "ls -la"}, "key-2")
    assert excinfo.value.reason_code is ShellDenialReason.NOT_IN_ALLOWLIST


def test_denial_is_still_a_capability_denied(tmp_path: Path) -> None:
    # Existing callers catch CapabilityDenied; the typed denial must remain one.
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("git status",))
    with pytest.raises(CapabilityDenied):
        adapter.preflight("workspace.shell", {"command": "ls -la"}, "key-3")


def test_denial_reason_is_machine_consumable_after_the_rewrite(tmp_path: Path) -> None:
    # Bypass-detecting: a harness reading `reason_code` must observe NOT_IN_ALLOWLIST
    # (not just a free-text message); this fails if the typed reason is dropped.
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("pytest",))
    with pytest.raises(ShellCommandDenied) as excinfo:
        adapter.preflight("workspace.shell", {"command": "echo hi"}, "key-4")
    assert excinfo.value.reason_code.value == "NOT_IN_ALLOWLIST"
    assert excinfo.value.args[0] == "command is not in the shell allowlist"


def test_execution_site_also_enforces_the_allowlist(tmp_path: Path) -> None:
    # Reaching execution without the preflight must not bypass the allowlist.
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("git status",))
    with pytest.raises(ShellCommandDenied) as excinfo:
        adapter.execute(_shell_action("ls -la"))
    assert excinfo.value.reason_code is ShellDenialReason.NOT_IN_ALLOWLIST


def test_run_tests_denial_is_enumerable(tmp_path: Path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path, shell_allowlist=("git status",))
    with pytest.raises(ShellCommandDenied) as excinfo:
        adapter.preflight(
            "workspace.run_tests", {"command": "rm -rf /"}, "key-5"
        )
    assert excinfo.value.reason_code is ShellDenialReason.NOT_IN_ALLOWLIST


def test_require_allowlisted_command_raises_the_typed_denial() -> None:
    with pytest.raises(ShellCommandDenied) as excinfo:
        require_allowlisted_command("whoami", ("git status",), "nope")
    assert excinfo.value.reason_code is ShellDenialReason.NOT_IN_ALLOWLIST
