from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilitySpec,
    ReceiptStatus,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    CorrectionAuthority,
)


class SpyCapabilityPort:
    def __init__(self) -> None:
        self.execute_count = 0

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> dict[str, CapabilitySpec]:
        return {}

    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={"artifact_ids": ("artifact:" + "a" * 64,)},
            error_code="error:none",
            detail_ref="detail:spy",
        )


class FailingSpyCapabilityPort(SpyCapabilityPort):
    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.FAILED,
            output={"error": "CapabilityDenied"},
            error_code="CapabilityDenied",
            detail_ref="detail:spy-failure",
        )


def action_and_permit(
    correction: CorrectionAuthority,
) -> tuple[ActionContract, ActionPermit]:
    now = datetime.now(timezone.utc)
    epochs = correction.snapshot("task:boundary", "run:boundary", "capability:spy")
    action = ActionContract(
        action_id="action:boundary",
        task_id="task:boundary",
        run_id="run:boundary",
        node_id="node:boundary",
        principal_id="principal:boundary",
        tenant_id="tenant:boundary",
        workspace_id="workspace:boundary",
        capability_id="capability:spy",
        capability_version="1",
        arguments_json="{}",
        risk_tier=0,
        idempotency_key="idempotency:boundary",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected:boundary",
        candidate_envelope_id="envelope:boundary",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:boundary",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:boundary",
        grant_id="grant:boundary",
        correction_epochs=epochs,
        lease_fence=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return action, permit


def test_broker_creates_receipt_after_one_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)

    result = CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 1
    assert result.receipt.action_digest == action.action_digest()
    assert result.receipt.permit_id == permit.permit_id
    assert result.receipt.connector_id == action.capability_id
    assert result.receipt.idempotency_key == action.idempotency_key
    assert result.receipt.status is ReceiptStatus.SUCCEEDED
    assert result.receipt.output_artifact_ids == ("artifact:" + "a" * 64,)
    assert result.receipt.detail_ref == "detail:spy"


def test_broker_creates_one_failed_receipt_for_failed_effect() -> None:
    correction = CorrectionAuthority()
    port = FailingSpyCapabilityPort()
    action, permit = action_and_permit(correction)

    result = CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 1
    assert result.receipt.status is ReceiptStatus.FAILED
    assert result.receipt.error_code == "CapabilityDenied"
    assert result.receipt.detail_ref == "detail:spy-failure"
    assert result.receipt.output_artifact_ids == ()


def test_broker_rejects_digest_mismatch_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    forged = permit.model_copy(update={"action_digest": "0" * 64})

    with pytest.raises(CapabilityDenied, match="digest mismatch"):
        CapabilityBroker(port, correction).invoke(action, forged)

    assert port.execute_count == 0


def test_broker_rejects_expired_permit_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    expired = permit.model_copy(
        update={
            "issued_at": permit.issued_at - timedelta(minutes=10),
            "expires_at": permit.issued_at - timedelta(minutes=5),
        }
    )

    with pytest.raises(CapabilityDenied, match="expired"):
        CapabilityBroker(port, correction).invoke(action, expired)

    assert port.execute_count == 0


def test_broker_rejects_c7_halt_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    correction.correct("task", action.task_id, "operator halt")

    with pytest.raises(CapabilityDenied, match="halted"):
        CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 0


def test_broker_rejects_stale_epoch_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    correction.correct("run", action.run_id, "epoch advance")
    correction.resume("run", action.run_id)

    with pytest.raises(CapabilityDenied, match="stale correction epoch"):
        CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 0
