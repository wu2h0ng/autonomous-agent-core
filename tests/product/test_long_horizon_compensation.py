from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import ActionContract, ActionPermit, ResourceBudget
from agent_os_core import (
    CapabilityDenied,
    CorrectionAuthority,
    SQLiteTaskEventStore,
    WorkspaceSandbox,
)


def _action(
    correction: CorrectionAuthority,
    now: datetime,
    *,
    action_id: str = "action:artifact",
    idempotency_key: str = "run:artifact",
) -> ActionContract:
    return ActionContract(
        action_id=action_id,
        task_id="task:long",
        run_id="run:long",
        node_id="artifact",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id="artifact.write",
        capability_version="1",
        arguments_json=json.dumps({"content": "must not be written"}),
        risk_tier=1,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=correction.snapshot(
            "task:long", "run:long", "artifact.write"
        ),
        expected_outcome_id="expected:long",
        candidate_envelope_id="envelope:long",
        created_at=now,
    )


def _permit(
    action: ActionContract,
    *,
    issued_at: datetime,
    expires_at: datetime,
) -> ActionPermit:
    return ActionPermit(
        permit_id=f"permit:{action.action_id}",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:long",
        grant_id="grant:artifact.write",
        correction_epochs=action.observed_correction_epochs,
        lease_fence=0,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def test_second_authority_observes_external_halt_without_restart(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert not second.halted("task:long", "run:long", "artifact.write")

    first.correct("task", "task:long", "external principal halt")

    assert second.halted("task:long", "run:long", "artifact.write")
    assert second.snapshot(
        "task:long", "run:long", "artifact.write"
    ).task_epoch == 1


def test_stale_authorities_advance_correction_epoch_monotonically(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    first = CorrectionAuthority(SQLiteTaskEventStore(database))
    second = CorrectionAuthority(SQLiteTaskEventStore(database))
    first.snapshot("task:long", "run:long", "artifact.write")
    second.snapshot("task:long", "run:long", "artifact.write")

    assert first.correct("task", "task:long", "first halt") == 1
    assert second.correct("task", "task:long", "second halt") == 2

    reloaded = CorrectionAuthority(SQLiteTaskEventStore(database))
    assert reloaded.snapshot(
        "task:long", "run:long", "artifact.write"
    ).task_epoch == 2


def test_connector_rejects_expired_permit_before_side_effect(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    correction = CorrectionAuthority()
    action = _action(correction, now)
    permit = _permit(
        action,
        issued_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    sandbox = WorkspaceSandbox(tmp_path)
    before = tuple(sandbox.artifacts.iterdir())

    with pytest.raises(CapabilityDenied, match="expired"):
        sandbox.invoke(action, permit, correction)

    assert tuple(sandbox.artifacts.iterdir()) == before


def test_forged_current_epoch_permit_cannot_bypass_halt(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    correction = CorrectionAuthority()
    correction.correct("task", "task:long", "principal halt")
    action = _action(correction, now)
    permit = _permit(
        action,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(CapabilityDenied, match="halted"):
        sandbox.invoke(action, permit, correction)

    assert not any(sandbox.artifacts.iterdir())
