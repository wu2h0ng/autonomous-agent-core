from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CapabilitySpec,
    CompensationMode,
    CompensationStatus,
    ExternalSignal,
    NodeKind,
    NodeSpec,
    PatchCompensationRecord,
    RunPlanRebound,
    SideEffectGuarantee,
    WaitCondition,
    WorkflowGraph,
)
from domain_packs.developer_agent import DeveloperWorkspaceAdapter



NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def test_wait_event_requires_signal_name_and_correlation_key() -> None:
    with pytest.raises(ValidationError, match="wait_event"):
        NodeSpec(node_id="wait", kind=NodeKind.WAIT_EVENT)


def test_non_wait_node_rejects_wait_binding() -> None:
    with pytest.raises(ValidationError, match="only for wait_event"):
        NodeSpec(
            node_id="done",
            kind=NodeKind.TERMINAL,
            wait_signal_name="build.finished",
            wait_correlation_key="build:7",
        )


def test_wait_event_uses_existing_timeout_as_deadline_budget() -> None:
    node = NodeSpec(
        node_id="wait",
        kind=NodeKind.WAIT_EVENT,
        wait_signal_name="build.finished",
        wait_correlation_key="build:7",
        timeout_seconds=90,
    )

    assert node.timeout_seconds == 90
    assert node.wait_signal_name == "build.finished"
    assert node.wait_correlation_key == "build:7"


def test_wait_condition_requires_deadline_after_registration() -> None:
    with pytest.raises(ValidationError, match="deadline"):
        WaitCondition(
            node_id="wait",
            signal_name="build.finished",
            correlation_key="build:7",
            registered_at=NOW,
            deadline=NOW,
        )


def test_external_signal_canonicalizes_object_payload() -> None:
    signal = ExternalSignal(
        signal_id="signal:7",
        task_id="task:7",
        run_id="run:7",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        signal_name="build.finished",
        correlation_key="build:7",
        payload_json='{ "ok": true, "attempt": 1 }',
        evidence_refs=("artifact:7", "artifact:7"),
        occurred_at=NOW,
    )

    assert signal.payload_json == '{"attempt":1,"ok":true}'
    assert signal.evidence_refs == ("artifact:7",)


def test_external_signal_rejects_non_object_payload() -> None:
    with pytest.raises(ValidationError, match="object"):
        ExternalSignal(
            signal_id="signal:7",
            task_id="task:7",
            run_id="run:7",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            signal_name="build.finished",
            correlation_key="build:7",
            payload_json="[]",
            occurred_at=NOW,
        )


def test_workflow_replan_budget_is_bounded() -> None:
    with pytest.raises(ValidationError):
        WorkflowGraph(
            workflow_id="workflow:7",
            version=1,
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            created_by="user:local",
            created_at=NOW,
            policy_version="policy-1",
            evaluator_refs=("evaluator:pytest:1",),
            nodes=(NodeSpec(node_id="done", kind=NodeKind.TERMINAL),),
            max_replans=4,
        )


def test_run_plan_rebound_normalizes_node_sets() -> None:
    rebound = RunPlanRebound(
        rebound_id="rebound:1",
        task_id="task:7",
        run_id="run:7",
        previous_workflow_version=1,
        previous_workflow_digest="a" * 64,
        new_workflow_version=2,
        new_workflow_digest="b" * 64,
        preserved_node_ids=("read", "read"),
        invalidated_node_ids=("wait",),
        new_node_ids=("provider", "provider"),
        requested_by="user:local",
        reason="replace the blocked suffix",
        created_at=NOW,
    )

    assert rebound.preserved_node_ids == ("read",)
    assert rebound.new_node_ids == ("provider",)


def test_sandbox_idempotent_guarantee_does_not_claim_compensation() -> None:
    spec = CapabilitySpec(
        capability_id="workspace.run_tests",
        version="1",
        display_name="Run tests",
        input_contract="json:object:1",
        output_contract="json:object:1",
        side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
        idempotency_supported=True,
        credential_class="none",
        data_boundary="workspace-local",
        risk_tier=1,
        timeout_seconds=120,
        cancellation_supported=True,
        compensation_supported=False,
        audit_policy="event-and-artifact",
        created_by="system",
        created_at=NOW,
    )

    assert spec.compensation_supported is False


def test_workspace_specs_claim_compensation_only_for_patch(tmp_path) -> None:
    specs = DeveloperWorkspaceAdapter(tmp_path).specs(NOW)

    assert specs["workspace.apply_patch"].compensation_supported is True
    assert specs["workspace.run_tests"].compensation_supported is False
    assert specs["artifact.write"].compensation_supported is False


def test_wait_deadline_can_be_capped_by_commitment_expiry() -> None:
    wait = WaitCondition(
        node_id="wait",
        signal_name="build.finished",
        correlation_key="build:7",
        registered_at=NOW,
        deadline=NOW + timedelta(seconds=30),
    )

    assert wait.deadline == NOW + timedelta(seconds=30)


def test_failed_compensation_record_requires_manual_intervention() -> None:
    with pytest.raises(ValidationError, match="manual_intervention_required"):
        PatchCompensationRecord(
            compensation_id="compensation:record-1",
            task_id="task:7",
            run_id="run:7",
            node_id="apply",
            original_action_id="action:apply",
            mode=CompensationMode.AUTOMATIC,
            status=CompensationStatus.FAILED,
            reason="snapshot missing",
            manual_intervention_required=False,
            created_at=NOW,
        )


def test_compensated_record_binds_action_snapshot_and_receipt() -> None:
    record = PatchCompensationRecord(
        compensation_id="compensation:record-1",
        task_id="task:7",
        run_id="run:7",
        node_id="apply",
        original_action_id="action:apply",
        compensation_action_id="action:compensate-apply",
        compensation_ref="compensation:" + "a" * 64,
        manifest_sha256="b" * 64,
        mode=CompensationMode.MANUAL,
        status=CompensationStatus.COMPENSATED,
        reason="principal requested governed restore",
        manual_intervention_required=False,
        receipt_id="receipt:compensate-apply",
        created_at=NOW,
    )

    assert record.status is CompensationStatus.COMPENSATED
