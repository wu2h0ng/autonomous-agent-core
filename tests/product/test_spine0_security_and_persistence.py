from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilityGrant,
    CapabilityGrantStatus,
    CorrectionEpochVector,
    PrincipalIdentity,
    PrincipalRole,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CorrectionAuthority,
    PolicyInput,
    PolicyKernel,
    SQLiteTaskEventStore,
)
from domain_packs.developer_agent import DeveloperWorkspaceAdapter


NOW = datetime.now(timezone.utc)


def test_sqlite_idempotency_survives_reopen(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(path)
    assert first.put_idempotency("scope", "key", {"value": "one"}, NOW.isoformat())
    first.close()
    second = SQLiteTaskEventStore(path)
    assert second.get_idempotency("scope", "key") == {"value": "one"}
    assert not second.put_idempotency("scope", "key", {"value": "two"}, NOW.isoformat())


def test_workspace_denies_path_escape_and_unallowlisted_command(tmp_path) -> None:
    sandbox = DeveloperWorkspaceAdapter(tmp_path)
    with pytest.raises(PermissionError):
        sandbox._safe_path("../outside")
    with pytest.raises(PermissionError):
        sandbox._dispatch("workspace.run_tests", {"command": "sh -c id"}, "key")


def test_workspace_compensation_removes_a_new_file(tmp_path) -> None:
    sandbox = DeveloperWorkspaceAdapter(tmp_path)
    sandbox._dispatch(
        "workspace.apply_patch", {"path": "new.txt", "content": "created"}, "action:new"
    )
    assert (tmp_path / "new.txt").exists()
    sandbox.compensate("action:new", "new.txt")
    assert not (tmp_path / "new.txt").exists()


def test_correction_epoch_blocks_a_previously_observed_action() -> None:
    correction = CorrectionAuthority()
    initial = correction.snapshot("task-1", "run-1", "workspace.read")
    correction.correct("task", "task-1", "principal pause")
    assert correction.snapshot("task-1", "run-1", "workspace.read") != initial
    assert correction.halted("task-1", "run-1", "workspace.read")


def test_correction_epoch_survives_authority_restart(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    store = SQLiteTaskEventStore(path)
    first = CorrectionAuthority(store)
    first.correct("task", "task-1", "stop")
    second = CorrectionAuthority(SQLiteTaskEventStore(path))
    assert second.halted("task-1", "run-1", "workspace.read")
    assert second.snapshot("task-1", "run-1", "workspace.read").task_epoch == 1


def test_correction_after_permit_blocks_actual_dispatch(tmp_path) -> None:
    sandbox = DeveloperWorkspaceAdapter(tmp_path)
    correction = CorrectionAuthority()
    now = NOW
    epochs = correction.snapshot("task-1", "run-1", "workspace.read")
    action = ActionContract(
        action_id="action:race",
        task_id="task-1",
        run_id="run-1",
        node_id="read",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        arguments_json='{"path":"fixture.txt"}',
        risk_tier=0,
        idempotency_key="race-key",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected-1",
        candidate_envelope_id="envelope-1",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:race",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:race",
        grant_id="grant:race",
        correction_epochs=epochs,
        lease_fence=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    correction.correct("task", "task-1", "operator pause")
    with pytest.raises(CapabilityDenied, match="halted"):
        CapabilityBroker(sandbox, correction).invoke(action, permit)


def test_policy_denies_budget_and_scope_mismatch() -> None:
    correction = CorrectionAuthority()
    policy = PolicyKernel(correction)
    principal = PrincipalIdentity(
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    from agent_os_contracts import CapabilitySpec, SideEffectGuarantee

    capability = CapabilitySpec(
        capability_id="workspace.read",
        version="1",
        display_name="read",
        input_contract="json",
        output_contract="json",
        side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
        idempotency_supported=True,
        credential_class="none",
        data_boundary="workspace",
        risk_tier=1,
        timeout_seconds=30,
        cancellation_supported=True,
        compensation_supported=False,
        audit_policy="all",
        created_by="system",
        created_at=NOW,
    )
    grant = CapabilityGrant(
        grant_id="grant-1",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=0,
        ),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="system",
        granted_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    action = ActionContract(
        action_id="action-1",
        task_id="task-1",
        run_id="run-1",
        node_id="read",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        arguments_json="{}",
        risk_tier=1,
        idempotency_key="key",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=2,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected-1",
        candidate_envelope_id="envelope-1",
        created_at=NOW,
    )
    decision = policy.decide(
        action,
        PolicyInput(principal=principal, grant=grant, capability=capability, now=NOW),
    )
    assert decision.verdict.value == "DENY"
    assert "BUDGET_EXCEEDED" in decision.reason_codes
