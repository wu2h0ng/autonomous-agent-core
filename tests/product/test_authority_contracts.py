from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ApprovalDecision,
    ApprovalDisposition,
    ArtifactLocationClass,
    ArtifactRef,
    CandidateExclusion,
    CandidateGenerationEnvelope,
    CapabilityGrant,
    CapabilityGrantStatus,
    CapabilitySpec,
    CorrectionEpochVector,
    CorrectionScope,
    CorrectionSnapshot,
    CorrectionState,
    PrincipalIdentity,
    PrincipalRole,
    ResourceBudget,
    SideEffectGuarantee,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _budget(**updates: Any) -> ResourceBudget:
    values: dict[str, Any] = {
        "max_cost_usd": Decimal("1.00"),
        "max_duration_seconds": 300,
        "max_provider_tokens": 2_000,
        "max_tool_calls": 4,
    }
    values.update(updates)
    return ResourceBudget(**values)


def _principal(**updates: Any) -> PrincipalIdentity:
    values: dict[str, Any] = {
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "role": PrincipalRole.PRINCIPAL,
        "authenticated_at": NOW,
    }
    values.update(updates)
    return PrincipalIdentity(**values)


def _envelope(**updates: Any) -> CandidateGenerationEnvelope:
    values: dict[str, Any] = {
        "envelope_id": "envelope-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "generator_id": "rule-generator",
        "generator_version": "1",
        "allowed_capability_ids": ("workspace.read", "workspace.apply_patch"),
        "resource_budget": _budget(),
        "candidate_ids": ("candidate-patch", "candidate-no-action"),
        "exclusions": (
            CandidateExclusion(
                candidate_class="general-shell",
                reason="not allowed in SPINE-0",
            ),
        ),
        "coverage_evidence_refs": ("evidence:candidate-scan",),
        "has_abstain": True,
        "has_ask": True,
        "has_no_action": True,
        "created_at": NOW,
    }
    values.update(updates)
    return CandidateGenerationEnvelope(**values)


def _action(**updates: Any) -> ActionContract:
    values: dict[str, Any] = {
        "action_id": "action-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "node_id": "patch",
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "capability_id": "workspace.apply_patch",
        "capability_version": "1",
        "arguments_json": '{"patch":"change"}',
        "risk_tier": 2,
        "idempotency_key": "action-key-1",
        "estimated_budget": _budget(max_tool_calls=1),
        "policy_version": "policy-1",
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        "expected_outcome_id": "expected-1",
        "candidate_envelope_id": "envelope-1",
        "created_at": NOW,
    }
    values.update(updates)
    return ActionContract(**values)


def _correction(
    scope: CorrectionScope,
    scope_id: str,
    **updates: Any,
) -> CorrectionState:
    values: dict[str, Any] = {
        "correction_id": f"correction-{scope.value.lower()}",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "scope": scope,
        "scope_id": scope_id,
        "epoch": 0,
        "halted": False,
        "reason": "initial active state",
        "written_by": "system:bootstrap",
        "written_at": NOW,
    }
    values.update(updates)
    return CorrectionState(**values)


def _snapshot(**updates: Any) -> CorrectionSnapshot:
    values: dict[str, Any] = {
        "task": _correction(CorrectionScope.TASK, "task-1"),
        "run": _correction(CorrectionScope.RUN, "run-1"),
        "capability": _correction(
            CorrectionScope.CAPABILITY,
            "workspace.apply_patch",
        ),
    }
    values.update(updates)
    return CorrectionSnapshot(**values)


def _permit(action: ActionContract, **updates: Any) -> ActionPermit:
    values: dict[str, Any] = {
        "permit_id": "permit-1",
        "action_id": action.action_id,
        "action_digest": action.action_digest(),
        "principal_id": action.principal_id,
        "tenant_id": action.tenant_id,
        "workspace_id": action.workspace_id,
        "policy_decision_id": "decision-1",
        "grant_id": "grant-1",
        "correction_epochs": action.observed_correction_epochs,
        "lease_fence": 0,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(updates)
    return ActionPermit(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("principal_id", "principal-2"),
        ("capability_id", "workspace.read"),
        ("policy_version", "policy-2"),
        ("idempotency_key", "action-key-2"),
        ("expected_outcome_id", "expected-2"),
        ("candidate_envelope_id", "envelope-2"),
    ),
)
def test_action_digest_changes_for_every_authority_field(
    field: str,
    value: str,
) -> None:
    action = _action()

    assert action.action_digest() != action.model_copy(
        update={field: value}
    ).action_digest()


def test_action_digest_changes_for_correction_epoch_vector() -> None:
    action = _action()
    changed = action.observed_correction_epochs.model_copy(update={"run_epoch": 1})

    assert action.action_digest() != action.model_copy(
        update={"observed_correction_epochs": changed}
    ).action_digest()


def test_action_arguments_are_canonical_and_object_only() -> None:
    action = _action(arguments_json=' { "b": 2, "a": 1 } ')

    assert action.arguments_json == '{"a":1,"b":2}'
    with pytest.raises(ValidationError, match="object"):
        _action(arguments_json='["unsafe"]')


def test_candidate_envelope_normalizes_set_like_fields() -> None:
    envelope = _envelope(
        candidate_ids=("candidate-no-action", "candidate-patch", "candidate-patch"),
        allowed_capability_ids=("workspace.read", "workspace.apply_patch", "workspace.read"),
    )

    assert envelope.candidate_ids == ("candidate-no-action", "candidate-patch")
    assert envelope.allowed_capability_ids == (
        "workspace.apply_patch",
        "workspace.read",
    )


def test_correction_snapshot_requires_exact_scope_order_and_shared_scope() -> None:
    with pytest.raises(ValidationError, match="task correction"):
        _snapshot(task=_correction(CorrectionScope.RUN, "task-1"))
    with pytest.raises(ValidationError, match="scope mismatch"):
        _snapshot(
            capability=_correction(
                CorrectionScope.CAPABILITY,
                "workspace.apply_patch",
                tenant_id="tenant-2",
            )
        )


def test_correction_snapshot_produces_epoch_vector() -> None:
    snapshot = _snapshot(
        task=_correction(CorrectionScope.TASK, "task-1", epoch=1),
        run=_correction(CorrectionScope.RUN, "run-1", epoch=2),
        capability=_correction(
            CorrectionScope.CAPABILITY,
            "workspace.apply_patch",
            epoch=3,
        ),
    )

    assert snapshot.epoch_vector() == CorrectionEpochVector(
        task_epoch=1,
        run_epoch=2,
        capability_epoch=3,
    )


def test_permit_binds_principal_and_action_digest() -> None:
    action = _action()
    permit = _permit(action)

    assert permit.matches(action)
    assert not permit.matches(action.model_copy(update={"principal_id": "principal-2"}))
    assert not permit.matches(action.model_copy(update={"arguments_json": '{"patch":"other"}'}))


def test_permit_expiry_must_follow_issue_time() -> None:
    action = _action()
    with pytest.raises(ValidationError, match="expires_at"):
        _permit(action, expires_at=NOW)


def test_approval_must_be_principal_authored_and_future_bound() -> None:
    with pytest.raises(ValidationError, match="principal"):
        ApprovalDecision(
            approval_id="approval-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            action_digest=_action().action_digest(),
            actor_id="worker-1",
            actor_role=PrincipalRole.WORKER,
            disposition=ApprovalDisposition.APPROVE,
            reason="approve",
            decided_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_capability_grant_requires_future_expiry() -> None:
    with pytest.raises(ValidationError, match="expires_at"):
        CapabilityGrant(
            grant_id="grant-1",
            principal_id="principal-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            capability_id="workspace.apply_patch",
            capability_version="1",
            max_risk_tier=2,
            budget_limit=_budget(),
            status=CapabilityGrantStatus.ACTIVE,
            granted_by="admin-1",
            granted_at=NOW,
            expires_at=NOW,
        )


def test_sandbox_capability_requires_idempotency_cancel_and_compensation() -> None:
    with pytest.raises(ValidationError, match="sandbox"):
        CapabilitySpec(
            capability_id="workspace.apply_patch",
            version="1",
            display_name="Apply patch",
            input_contract="contract:patch:1",
            output_contract="contract:artifact:1",
            side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE,
            idempotency_supported=False,
            credential_class="NONE",
            data_boundary="workspace",
            risk_tier=2,
            timeout_seconds=60,
            cancellation_supported=True,
            compensation_supported=True,
            audit_policy="full",
            created_by="system",
            created_at=NOW,
        )


def test_artifact_requires_sha256_digest() -> None:
    with pytest.raises(ValidationError, match="content_digest"):
        ArtifactRef(
            artifact_id="artifact-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            content_digest="not-a-sha256",
            media_type="text/plain",
            location_class=ArtifactLocationClass.WORKSPACE_LOCAL,
            location_ref="artifacts/result.txt",
            acl_scopes=("principal:principal-1",),
            retention_policy="task-lifetime",
            created_by="worker-1",
            created_at=NOW,
        )


def test_principal_identity_is_scope_bound() -> None:
    principal = _principal()

    assert principal.tenant_id == "tenant-1"
    assert principal.workspace_id == "workspace-1"
