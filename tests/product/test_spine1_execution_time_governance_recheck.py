"""SPINE-1 (ADR-0005): execution-time governance recheck (C7) before any capability side-effect.

A correction halt (or epoch change) BETWEEN the authority that approved an action and the actual
capability dispatch must block the real effect. This is the monorepo parity test for the invariant
already implemented in ``CapabilityBroker.invoke`` / ``ActionPipeline.execute`` — it would FAIL if
that gate were removed or bypassed.

Every "blocked" assertion checks the sandbox never dispatched; the positive control proves the gate
is not over-blocking a genuinely unchanged correction authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    ActionContract,
    PolicyVerdict,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    ExecutionLease,
    PolicyInput,
)
from apps.api_server.app import AgentOSApplication
from domain_packs.developer_agent import WorkspaceSandbox

_CAPABILITY_ID = "workspace.read"
_TASK_ID = "task:recheck"
_RUN_ID = "run:recheck"
_OWNER = "test:worker"


class _DispatchCountingSandbox(WorkspaceSandbox):
    def __init__(self, root: Path, *, idempotency_store: object) -> None:
        super().__init__(root, idempotency_store=idempotency_store)
        self.dispatch_count = 0

    def _dispatch(self, capability_id: str, args: dict[str, object], action_key: str) -> dict[str, object]:
        self.dispatch_count += 1
        return super()._dispatch(capability_id, args, action_key)


def _app(tmp_path: Path) -> AgentOSApplication:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    return AgentOSApplication(database=tmp_path / "state.sqlite3", workspace=tmp_path)


def _action(app: AgentOSApplication) -> ActionContract:
    principal = app.principal
    return ActionContract(
        action_id="action:recheck",
        task_id=_TASK_ID,
        run_id=_RUN_ID,
        node_id="node:recheck",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        capability_id=_CAPABILITY_ID,
        capability_version="1",
        arguments_json=json.dumps({"path": "fixture.txt"}),
        risk_tier=0,
        idempotency_key=f"{_RUN_ID}:node:recheck",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=60,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version=app.policy.policy_version,
        observed_correction_epochs=app.correction.snapshot(_TASK_ID, _RUN_ID, _CAPABILITY_ID),
        expected_outcome_id="outcome:recheck",
        candidate_envelope_id="envelope:recheck",
        created_at=datetime.now(timezone.utc),
    )


def _lease(app: AgentOSApplication) -> ExecutionLease:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    fence = app.store.acquire_lease(_RUN_ID, _OWNER, expiry.isoformat())
    return ExecutionLease(run_id=_RUN_ID, owner=_OWNER, fence=fence, expires_at=expiry)


def _permit(app: AgentOSApplication, action: ActionContract, fence: int):
    grant = app.grants[action.capability_id]
    spec = app.sandbox.specs()[action.capability_id]
    decision = app.policy.decide(
        action, PolicyInput(principal=app.principal, grant=grant, capability=spec)
    )
    assert decision.verdict is PolicyVerdict.ALLOW, decision.reason_codes
    return app.policy.permit(action, decision, grant, lease_fence=fence)


def _broker(app: AgentOSApplication, tmp_path: Path) -> tuple[CapabilityBroker, _DispatchCountingSandbox]:
    sandbox = _DispatchCountingSandbox(tmp_path, idempotency_store=app.store)
    return CapabilityBroker(sandbox, app.correction), sandbox


def test_correction_halt_between_approval_and_dispatch_blocks_the_effect(tmp_path: Path) -> None:
    app = _app(tmp_path)
    lease = _lease(app)
    action = _action(app)
    permit = _permit(app, action, lease.fence)
    broker, sandbox = _broker(app, tmp_path)

    # State change AFTER the execution authority was issued, BEFORE dispatch.
    app.correction_admin.correct("task", _TASK_ID, "operator stop")

    with pytest.raises(CapabilityDenied, match="halted"):
        broker.invoke(action, permit, execution_claim=lease)

    assert sandbox.dispatch_count == 0


def test_correction_epoch_change_between_approval_and_dispatch_blocks_the_effect(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    lease = _lease(app)
    action = _action(app)
    permit = _permit(app, action, lease.fence)
    broker, sandbox = _broker(app, tmp_path)

    # Advance the epoch without leaving a halt in place: correct + resume => not halted, stale epoch.
    app.correction_admin.correct("task", _TASK_ID, "operator stop")
    app.correction_admin.resume("task", _TASK_ID, "resumed")

    with pytest.raises(CapabilityDenied, match="stale correction epoch"):
        broker.invoke(action, permit, execution_claim=lease)

    assert sandbox.dispatch_count == 0


def test_unchanged_correction_authority_allows_the_effect(tmp_path: Path) -> None:
    app = _app(tmp_path)
    lease = _lease(app)
    action = _action(app)
    permit = _permit(app, action, lease.fence)
    broker, sandbox = _broker(app, tmp_path)

    result = broker.invoke(action, permit, execution_claim=lease)

    assert result.receipt.status.value == "SUCCEEDED"
    assert sandbox.dispatch_count == 1


def test_policy_kernel_denies_while_halted(tmp_path: Path) -> None:
    """The halt is also visible at policy time, so a later execution cannot get a fresh permit."""
    app = _app(tmp_path)
    action = _action(app)
    app.correction_admin.correct("task", _TASK_ID, "operator stop")

    decision = app.policy.decide(
        action,
        PolicyInput(
            principal=app.principal,
            grant=app.grants[action.capability_id],
            capability=app.sandbox.specs()[action.capability_id],
        ),
    )

    assert decision.verdict is PolicyVerdict.DENY
