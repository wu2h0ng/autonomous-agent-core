from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    CoordinationAuthorityContext,
    ResourceScope,
    WorkLease,
)
from apps.api_server.app import AgentOSApplication


def _authority(now: datetime) -> CoordinationAuthorityContext:
    return CoordinationAuthorityContext(
        authorization_id="auth:1",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        authorized_scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),),
        evidence_refs=("ev:1",),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _lease(now: datetime) -> WorkLease:
    return WorkLease(
        lease_id="lease:1",
        lease_version=1,
        fence_token=1,
        task_id="task:local",
        run_id="run:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        holder_id="user:local",
        plan_version=1,
        event_cursor=0,
        scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),),
        authority_context=_authority(now),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def test_production_registry_marks_write_capabilities_collaboration_required(
    tmp_path: Path,
) -> None:
    app = AgentOSApplication(database=":memory:", workspace=tmp_path)
    specs = app.sandbox.specs()
    assert specs["workspace.edit"].collaboration_required is True
    assert specs["workspace.apply_patch"].collaboration_required is True
    assert specs["workspace.read"].collaboration_required is False
    assert specs["workspace.run_tests"].collaboration_required is False
    assert specs["workspace.shell"].collaboration_required is False


def test_production_composition_root_wires_a_collaboration_preflight(
    tmp_path: Path,
) -> None:
    app = AgentOSApplication(database=":memory:", workspace=tmp_path)
    assert app.collaboration_preflight is not None
    assert app.workspace_fence is not None


def test_collaboration_required_write_without_lease_fails_closed(
    tmp_path: Path,
) -> None:
    from agent_os_contracts import (
        ActionContract,
        ActionPermit,
        CorrectionEpochVector,
        ResourceBudget,
    )
    from agent_os_core import CapabilityBroker, CapabilityDenied, ExecutionLease

    app = AgentOSApplication(database=":memory:", workspace=tmp_path)
    now = datetime.now(timezone.utc)
    action = ActionContract(
        action_id="action:edit",
        task_id="task:local",
        run_id="run:local",
        node_id="node:edit",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id="workspace.edit",
        capability_version="1",
        arguments_json=json.dumps({"path": "a.txt"}),
        risk_tier=2,
        idempotency_key="run:edit",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:1",
        candidate_envelope_id="envelope:1",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:action:edit",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:1",
        grant_id="grant:1",
        correction_epochs=action.observed_correction_epochs,
        lease_fence=1,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    claim = ExecutionLease(
        run_id="run:local",
        owner="user:local",
        fence=1,
        expires_at=now + timedelta(minutes=5),
    )
    broker = CapabilityBroker(
        app.sandbox, app.correction, collaboration_preflight=app.collaboration_preflight
    )
    with pytest.raises(CapabilityDenied):
        broker.invoke(action, permit, execution_claim=claim)


def test_collaboration_required_write_with_lease_reaches_connector(
    tmp_path: Path,
) -> None:
    from agent_os_contracts import (
        ActionContract,
        CollaborationDisposition,
        CorrectionEpochVector,
        ResourceBudget,
    )
    from agent_os_core import ExecutionLease

    app = AgentOSApplication(database=":memory:", workspace=tmp_path)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    app.workspace_fence.install_lease(_lease(now))
    action = ActionContract(
        action_id="action:edit2",
        task_id="task:local",
        run_id="run:local",
        node_id="node:edit",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id="workspace.edit",
        capability_version="1",
        arguments_json=json.dumps(
            {"path": "a.txt", "old_string": "hello\n", "new_string": "hi\n"}
        ),
        risk_tier=2,
        idempotency_key="run:edit2",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:1",
        candidate_envelope_id="envelope:1",
        created_at=now,
    )
    claim = ExecutionLease(
        run_id="run:local",
        owner="user:local",
        fence=1,
        expires_at=now + timedelta(minutes=5),
    )
    decision = app.collaboration_preflight.preflight(action, claim)
    assert decision.disposition is CollaborationDisposition.CONTINUE
