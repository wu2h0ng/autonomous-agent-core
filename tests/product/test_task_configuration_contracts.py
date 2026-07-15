from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    AgentRun,
    CandidateProvenance,
    CapabilityGrant,
    CapabilityGrantStatus,
    CorrectionEpochVector,
    DomainPriorBinding,
    DomainPriorSelector,
    EdgeSpec,
    ExpectedOutcome,
    NodeKind,
    NodeSpec,
    ProviderProfile,
    PriorEvaluationSource,
    ResourceBudget,
    RunStatus,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    WorkflowGraph,
    content_digest,
    domain_prior_provenance_digest,
    task_configuration_grants_digest,
    task_configuration_seal_request_digest,
    task_configuration_snapshot_digest,
)


NOW = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=10,
    )


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow:consumer",
        version=1,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by="principal:consumer",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="read",
                kind=NodeKind.TOOL,
                capability="workspace.read",
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="read", target="done"),),
    )


def _expected() -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="outcome:consumer",
        task_id="task:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("NOT_MET",),
        threshold=1.0,
        observation_window_seconds=300,
        frozen_at=NOW,
    )


def _provider_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="provider-profile:consumer",
        provider_id="deterministic",
        model_id="deterministic-v1",
        endpoint_class="test",
        credential_ref_id="credential:none",
        capabilities=("chat",),
        max_context_tokens=16_000,
        request_timeout_seconds=60,
        created_at=NOW,
    )


def _grant(
    *, status: CapabilityGrantStatus = CapabilityGrantStatus.ACTIVE
) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id="grant:workspace.read",
        principal_id="principal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=_budget(),
        status=status,
        granted_by="system",
        granted_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _snapshot(
    *, grant: CapabilityGrant | None = None
) -> TaskConfigurationSnapshot:
    workflow = _workflow()
    expected = _expected()
    provider = _provider_profile()
    grants = (grant or _grant(),)
    command = TaskConfigurationSnapshotCommand()
    payload = {
        "snapshot_id": "task-configuration:1",
        "snapshot_version": 1,
        "seal_request_digest": task_configuration_seal_request_digest(
            "task:consumer", command
        ),
        "consumer_task_id": "task:consumer",
        "reserved_run_id": "run:consumer",
        "commitment_id": "commitment:consumer",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "principal_id": "principal:consumer",
        "workflow": workflow,
        "workflow_digest": workflow.canonical_digest(),
        "policy_version": "policy-1",
        "policy_digest": "a" * 64,
        "provider_profile": provider,
        "provider_profile_digest": content_digest(provider),
        "execution_grants": grants,
        "execution_grants_digest": task_configuration_grants_digest(grants),
        "expected_outcome": expected,
        "expected_outcome_digest": content_digest(expected),
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        "optional_prior": None,
        "sealed_by": "system:task-configuration-sealer:v1",
        "sealed_at": NOW,
        "state": "SEALED",
        "prior_consumption_mode": "REFERENCE_ONLY",
    }
    return TaskConfigurationSnapshot(
        **payload,
        snapshot_digest=task_configuration_snapshot_digest(payload),
    )


def _prior_binding() -> DomainPriorBinding:
    provenance = (
        CandidateProvenance(
            source_id="source:contract",
            source_ref="artifact:contract",
            source_type="test",
            source_digest="1" * 64,
            accessed_at=NOW,
            effective_at=NOW - timedelta(minutes=1),
            license_or_terms_id="terms:test",
            permitted_use="test",
            redistribution_allowed=False,
            output_patch_digest="2" * 64,
            expires_at=NOW + timedelta(hours=1),
        ),
    )
    receipt_digest = "3" * 64
    return DomainPriorBinding(
        prior_artifact_id="prior:contract",
        prior_version=1,
        prior_digest="4" * 64,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        candidate_id="candidate:contract",
        candidate_task_id="task:candidate",
        materialization_run_id="run:candidate",
        candidate_digest="5" * 64,
        candidate_payload_digest="6" * 64,
        promotion_id="promotion:contract",
        promotion_task_id="task:promotion",
        promotion_run_id="run:promotion",
        promotion_digest="7" * 64,
        evaluation_head_digest=receipt_digest,
        evaluation_receipt_digests=(receipt_digest,),
        receipt_chain_digest="8" * 64,
        evaluation_sources=(
            PriorEvaluationSource(
                evaluation_task_id="task:evaluation",
                evaluation_run_id="run:evaluation",
                evaluation_digest=receipt_digest,
                evaluator_id="principal:evaluator",
                recorded_by="principal:recorder",
            ),
        ),
        representation_patch_digest="2" * 64,
        provenance=provenance,
        provenance_digest=domain_prior_provenance_digest(provenance),
        policy_digest="9" * 64,
    )


def test_snapshot_command_rejects_authoritative_and_activation_fields() -> None:
    selector = DomainPriorSelector(
        candidate_task_id="task:source",
        candidate_digest="b" * 64,
        prior_artifact_id="prior:1",
    )
    assert TaskConfigurationSnapshotCommand(prior_selector=selector).prior_selector == selector

    for field, value in (
        ("snapshot_id", "task-configuration:caller"),
        ("consumer_task_id", "task:caller"),
        ("reserved_run_id", "run:caller"),
        ("workflow", {}),
        ("workflow_digest", "c" * 64),
        ("policy_version", "policy-caller"),
        ("policy_digest", "d" * 64),
        ("provider_profile", {}),
        ("provider_profile_digest", "e" * 64),
        ("execution_grants", []),
        ("execution_grants_digest", "f" * 64),
        ("expected_outcome", {}),
        ("expected_outcome_digest", "1" * 64),
        ("observed_correction_epochs", {}),
        ("optional_prior", {}),
        ("sealed_by", "caller"),
        ("sealed_at", NOW.isoformat()),
        ("snapshot_digest", "2" * 64),
        ("activation", True),
        ("prior_digest", "3" * 64),
    ):
        with pytest.raises(ValidationError):
            TaskConfigurationSnapshotCommand.model_validate(
                {"prior_selector": selector.model_dump(mode="json"), field: value}
            )


def test_snapshot_is_frozen_and_digest_bound() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValidationError):
        snapshot.principal_id = "principal:attacker"  # type: ignore[misc]

    changed = snapshot.model_dump(mode="json")
    changed["workflow_digest"] = "f" * 64
    with pytest.raises(ValidationError, match="workflow digest"):
        TaskConfigurationSnapshot.model_validate(changed)


def test_snapshot_digest_is_sensitive_to_each_authoritative_binding() -> None:
    snapshot = _snapshot()
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_digest"})
    assert task_configuration_snapshot_digest(payload) == snapshot.snapshot_digest

    mutations = (
        ("consumer_task_id", "task:mutated"),
        ("reserved_run_id", "run:mutated"),
        ("workflow_digest", "b" * 64),
        ("policy_digest", "c" * 64),
        ("provider_profile_digest", "d" * 64),
        ("execution_grants_digest", "e" * 64),
        ("expected_outcome_digest", "f" * 64),
        (
            "observed_correction_epochs",
            {"task_epoch": 1, "run_epoch": 0, "capability_epoch": 0},
        ),
        ("sealed_at", (NOW + timedelta(seconds=1)).isoformat()),
    )
    for field, value in mutations:
        changed = dict(payload)
        changed[field] = value
        assert task_configuration_snapshot_digest(changed) != snapshot.snapshot_digest


def test_snapshot_rejects_inactive_execution_grant() -> None:
    with pytest.raises(ValidationError, match="active"):
        _snapshot(grant=_grant(status=CapabilityGrantStatus.REVOKED))


def test_snapshot_rejects_multiple_grants_for_one_capability() -> None:
    first = _grant()
    second = first.model_copy(
        update={"grant_id": "grant:workspace.read:v2", "capability_version": "2"}
    )
    payload = _snapshot().model_dump(mode="json", exclude={"snapshot_digest"})
    payload["execution_grants"] = [
        first.model_dump(mode="json"),
        second.model_dump(mode="json"),
    ]
    payload["execution_grants_digest"] = task_configuration_grants_digest(
        (first, second)
    )
    payload["snapshot_digest"] = task_configuration_snapshot_digest(payload)

    with pytest.raises(ValidationError, match="duplicate capability"):
        TaskConfigurationSnapshot.model_validate(payload)


def test_agent_run_requires_snapshot_id_and_digest_as_a_pair() -> None:
    payload = {
        "run_id": "run:consumer",
        "task_id": "task:consumer",
        "commitment_id": "commitment:consumer",
        "workflow_id": "workflow:consumer",
        "workflow_version": 1,
        "workflow_digest": "a" * 64,
        "expected_outcome_id": "outcome:consumer",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "status": RunStatus.QUEUED,
        "created_at": NOW,
        "configuration_snapshot_id": "task-configuration:1",
    }

    with pytest.raises(ValidationError, match="snapshot"):
        AgentRun.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"evaluation_head_digest": "a" * 64}, "head"),
        ({"provenance_digest": "b" * 64}, "provenance"),
        ({"source_state": "ACTIVE"}, "INERT"),
        ({"source_activation_authority": "MODEL"}, "NONE"),
        ({"consumption_mode": "APPLY"}, "REFERENCE_ONLY"),
    ),
)
def test_prior_binding_rejects_lineage_or_activation_drift(
    updates: dict[str, object],
    message: str,
) -> None:
    payload = _prior_binding().model_dump(mode="json")
    payload.update(updates)

    with pytest.raises(ValidationError, match=message):
        DomainPriorBinding.model_validate(payload)


def test_prior_binding_rejects_duplicate_receipt_sources() -> None:
    payload = _prior_binding().model_dump(mode="json")
    digest = payload["evaluation_receipt_digests"][0]
    source = payload["evaluation_sources"][0]
    payload["evaluation_receipt_digests"] = [digest, digest]
    payload["evaluation_sources"] = [source, source]

    with pytest.raises(ValidationError, match="unique"):
        DomainPriorBinding.model_validate(payload)


@pytest.mark.parametrize(
    ("prior_field", "value"),
    (
        ("candidate_task_id", "task:consumer"),
        ("materialization_run_id", "run:consumer"),
        ("promotion_task_id", "task:consumer"),
        ("promotion_run_id", "run:consumer"),
    ),
)
def test_snapshot_rejects_consumer_reuse_of_prior_source_task_or_run(
    prior_field: str,
    value: str,
) -> None:
    prior = _prior_binding().model_copy(update={prior_field: value})
    payload = _snapshot().model_dump(mode="json", exclude={"snapshot_digest"})
    payload["optional_prior"] = prior.model_dump(mode="json")
    selector = DomainPriorSelector(
        candidate_task_id=prior.candidate_task_id,
        candidate_digest=prior.candidate_digest,
        prior_artifact_id=prior.prior_artifact_id,
    )
    payload["seal_request_digest"] = task_configuration_seal_request_digest(
        "task:consumer",
        TaskConfigurationSnapshotCommand(prior_selector=selector),
    )
    payload["snapshot_digest"] = task_configuration_snapshot_digest(payload)

    with pytest.raises(ValidationError, match="source"):
        TaskConfigurationSnapshot.model_validate(payload)
