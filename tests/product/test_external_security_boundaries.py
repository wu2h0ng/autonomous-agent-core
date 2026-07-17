from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    ActionContract,
    BoundaryDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    CapabilitySpec,
    CorrectionEpochVector,
    CredentialRef,
    CredentialStatus,
    ExternalExecutionResourceRef,
    ExternalPolicyQuery,
    PrincipalIdentity,
    PrincipalRole,
    ResourceBudget,
    SideEffectGuarantee,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    TaskStatus,
)
from agent_os_core import (
    CorrectionAuthority,
    DurableExecutionBoundary,
    InMemoryTaskEventStore,
    PolicyInput,
    PolicyKernel,
    TaskService,
    TraceExportBoundary,
)
from tests.product.test_task_service import DeterministicIdFactory, _goal


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


class _ExecutionBackend:
    backend_id = "durable-backend:test"
    version = 1

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def load_checkpoint(self, resource: ExternalExecutionResourceRef) -> object:
        del resource
        return self.payload


class _PolicyBackend:
    backend_id = "policy-backend:test"
    version = 1

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    def evaluate(self, query: object) -> object:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if callable(self.response):
            return self.response(query)
        return self.response


class _TraceExporter:
    exporter_id = "otel:test"
    version = 1

    def __init__(self) -> None:
        self.records: list[object] = []

    def export(self, record: object) -> None:
        self.records.append(record)


def _principal(**updates: str) -> PrincipalIdentity:
    values = {
        "principal_id": "user-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
    }
    values.update(updates)
    return PrincipalIdentity.model_validate(
        {**values, "role": PrincipalRole.PRINCIPAL, "authenticated_at": NOW}
    )


def _task_service() -> tuple[TaskService, str]:
    service = TaskService(
        InMemoryTaskEventStore(),
        id_factory=DeterministicIdFactory(),
        clock=lambda: NOW,
    )
    task = service.create_task(_goal())
    return service, task.task_id


def _resource(task_id: str, **updates: str) -> ExternalExecutionResourceRef:
    values = {
        "resource_id": "checkpoint:external-1",
        "backend_id": "durable-backend:test",
        "backend_version": 1,
        "task_id": task_id,
        "principal_id": "user-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
    }
    values.update(updates)
    return ExternalExecutionResourceRef(**values)


def _checkpoint(task_id: str, **updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "checkpoint_id": "checkpoint:external-1",
        "backend_id": "durable-backend:test",
        "backend_version": 1,
        "task_id": task_id,
        "run_id": "run:external-1",
        "principal_id": "user-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "history_digest": "a" * 64,
        "resume_cursor": "cursor:external-1",
        "payload_digest": "b" * 64,
        "recorded_at": NOW,
    }
    values.update(updates)
    return values


def test_external_checkpoint_cannot_activate_or_write_authority_or_truth() -> None:
    tasks, task_id = _task_service()
    malicious = _checkpoint(
        task_id,
        task_status="ACTIVE",
        capability_grant={"capability_id": "shell"},
        observed_outcome_status="VERIFIED",
    )
    boundary = DurableExecutionBoundary(tasks, _ExecutionBackend(malicious))

    receipt = boundary.mirror_checkpoint(_resource(task_id), _principal())

    aggregate = tasks.get_task(task_id)
    assert receipt.disposition is BoundaryDisposition.DENIED
    assert "MALFORMED" in receipt.reason_code
    assert aggregate.status is TaskStatus.DRAFT
    assert aggregate.run is None
    assert aggregate.observed_outcome is None


def test_external_checkpoint_is_candidate_only_and_cross_tenant_fails_closed() -> None:
    tasks, task_id = _task_service()
    backend = _ExecutionBackend(_checkpoint(task_id))
    boundary = DurableExecutionBoundary(tasks, backend)

    mirrored = boundary.mirror_checkpoint(_resource(task_id), _principal())
    denied = tuple(
        boundary.mirror_checkpoint(_resource(task_id, **scope), _principal())
        for scope in (
            {"principal_id": "user-other"},
            {"tenant_id": "tenant-other"},
            {"workspace_id": "workspace-other"},
        )
    )

    assert mirrored.disposition is BoundaryDisposition.CANDIDATE_MIRRORED
    assert mirrored.checkpoint_candidate is not None
    assert mirrored.checkpoint_candidate.resume_cursor == "cursor:external-1"
    assert mirrored.activation_authorized is False
    assert mirrored.capability_grant_authorized is False
    assert mirrored.outcome_verification_authorized is False
    assert all(item.disposition is BoundaryDisposition.DENIED for item in denied)
    assert tasks.get_task(task_id).status is TaskStatus.DRAFT


def _policy_material() -> tuple[
    ActionContract, PolicyInput, CorrectionAuthority
]:
    correction = CorrectionAuthority()
    principal = _principal()
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
    budget = ResourceBudget(
        max_cost_usd=Decimal("1"),
        max_duration_seconds=30,
        max_provider_tokens=0,
        max_tool_calls=1,
    )
    grant = CapabilityGrant(
        grant_id="grant-1",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=budget,
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
        idempotency_key="key-1",
        estimated_budget=budget,
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected-1",
        candidate_envelope_id="candidate-1",
        created_at=NOW,
    )
    return action, PolicyInput(principal, grant, capability, now=NOW), correction


def _allow_advice(query: ExternalPolicyQuery) -> dict[str, object]:
    return {
        "backend_id": "policy-backend:test",
        "backend_version": 1,
        "action_id": query.action_id,
        "principal_id": query.principal_id,
        "tenant_id": query.tenant_id,
        "workspace_id": query.workspace_id,
        "policy_query_digest": query.query_digest(),
        "policy_request_id": query.policy_request_id,
        "nonce": query.nonce,
        "verdict": "ALLOW",
        "reason_codes": ["EXTERNAL_ADMITTED"],
        "issued_at": query.issued_at,
        "expires_at": query.expires_at,
    }


def test_external_policy_is_fail_closed_and_cannot_expand_or_validate_outcome() -> None:
    action, context, correction = _policy_material()
    timeout_backend = _PolicyBackend(error=TimeoutError("late"))
    malformed_backend = _PolicyBackend(
        response=lambda query: {
            **_allow_advice(query),
            "capability_grant": {"capability_id": "shell"},
            "observed_outcome_status": "VERIFIED",
        }
    )

    timeout = PolicyKernel(correction, external_backend=timeout_backend).decide(
        action, context
    )
    malformed = PolicyKernel(correction, external_backend=malformed_backend).decide(
        action, context
    )

    assert timeout.verdict.value == "DENY"
    assert timeout.reason_codes == ("EXTERNAL_POLICY_UNAVAILABLE",)
    assert malformed.verdict.value == "DENY"
    assert malformed.reason_codes == ("EXTERNAL_POLICY_MALFORMED",)


def test_external_policy_allow_cannot_override_internal_scope_denial() -> None:
    action, context, correction = _policy_material()
    backend = _PolicyBackend(response=_allow_advice)
    foreign_action = action.model_copy(update={"tenant_id": "tenant-other"})

    decision = PolicyKernel(correction, external_backend=backend).decide(
        foreign_action, context
    )

    assert decision.verdict.value == "DENY"
    assert decision.reason_codes == ("SCOPE_MISMATCH",)
    assert backend.calls == 0


def test_external_policy_advice_cannot_replay_across_action_digest_change() -> None:
    action, context, correction = _policy_material()

    class _ReplayBackend:
        backend_id = "policy-backend:test"
        version = 1

        def __init__(self) -> None:
            self.cached: dict[str, object] | None = None

        def evaluate(self, query: ExternalPolicyQuery) -> object:
            if self.cached is None:
                self.cached = _allow_advice(query)
            return self.cached

    backend = _ReplayBackend()
    policy = PolicyKernel(correction, external_backend=backend)
    first = policy.decide(action, context)
    changed = action.model_copy(
        update={"arguments_json": '{"path":"other"}', "idempotency_key": "key-2"}
    )
    replay = policy.decide(changed, context)

    assert first.verdict.value == "ALLOW"
    assert replay.verdict.value == "DENY"
    assert replay.reason_codes == ("EXTERNAL_POLICY_BINDING_MISMATCH",)


def _trace() -> SituatedEvaluationTrace:
    return SituatedEvaluationTrace(
        trace_id="trace-1",
        admission_receipt_digest="a" * 64,
        event_id="event-1",
        projection_id="projection-1",
        mandate_id="mandate-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status=SituatedTraceStatus.COMPLETED,
        reason=SituatedTraceReason.NO_PROPOSAL,
        result_binding_digest="b" * 64,
        delegation_attempt_count=1,
        committed_provider_call_attempted=False,
        input_tokens=0,
        output_tokens=0,
        duration_ms=1,
        recorded_at=NOW,
    )


def _credential_ref() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential:test",
        owner_principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        provider_id="provider:test",
        resolver_key="env:TEST_API_KEY",
        scopes=("provider:invoke",),
        status=CredentialStatus.ACTIVE,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_trace_export_redacts_secrets_and_exports_credential_ref_only() -> None:
    exporter = _TraceExporter()
    boundary = TraceExportBoundary(exporter)

    receipt = boundary.export_situated_trace(
        _trace(),
        _principal(),
        resource_id="trace-resource-1",
        credential_ref=_credential_ref(),
        attributes={
            "event_type": "Bearer SECRET-VALUE",
            "resource_kind": "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
            "status": "COMPLETED",
        },
    )

    assert receipt.disposition is BoundaryDisposition.EXPORTED
    assert receipt.redacted_fields == ("event_type", "resource_kind")
    assert "SECRET-VALUE" not in receipt.model_dump_json()
    assert "ghp_" not in receipt.model_dump_json()
    assert len(exporter.records) == 1
    assert "SECRET-VALUE" not in exporter.records[0].model_dump_json()  # type: ignore[attr-defined]
    assert exporter.records[0].credential_ref == _credential_ref()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "secret_value",
    [
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
        "-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----",
        "Bearer bearer-secret",
    ],
)
def test_trace_allowlisted_field_still_redacts_secret_value(
    secret_value: str,
) -> None:
    exporter = _TraceExporter()
    receipt = TraceExportBoundary(exporter).export_situated_trace(
        _trace(),
        _principal(),
        resource_id="trace-resource-1",
        credential_ref=_credential_ref(),
        attributes={"status": secret_value},
    )

    assert receipt.disposition is BoundaryDisposition.EXPORTED
    assert receipt.redacted_fields == ("status",)
    assert secret_value not in receipt.model_dump_json()
    assert secret_value not in exporter.records[0].model_dump_json()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "attributes",
    [
        {"context": "free-form hidden prompt"},
        {"note": "operator private note"},
        {"unknown": "A9fK2mQ7xP4zR8vT1bN6cD3eH5jL0sW"},
    ],
)
def test_trace_unknown_attributes_are_default_denied(
    attributes: dict[str, object],
) -> None:
    exporter = _TraceExporter()
    receipt = TraceExportBoundary(exporter).export_situated_trace(
        _trace(),
        _principal(),
        resource_id="trace-resource-1",
        credential_ref=_credential_ref(),
        attributes=attributes,
    )

    assert receipt.disposition is BoundaryDisposition.DENIED
    assert receipt.reason_code == "TRACE_ATTRIBUTE_NOT_ALLOWLISTED"
    assert exporter.records == []


def test_trace_export_rejects_raw_candidate_bytes_and_cross_tenant_collision() -> None:
    exporter = _TraceExporter()
    boundary = TraceExportBoundary(exporter)

    raw = boundary.export_situated_trace(
        _trace(),
        _principal(),
        resource_id="trace-resource-1",
        credential_ref=_credential_ref(),
        attributes={"raw_candidate_bytes": b"private"},
    )
    foreign = boundary.export_situated_trace(
        _trace(),
        _principal(tenant_id="tenant-other"),
        resource_id="trace-resource-1",
        credential_ref=_credential_ref(),
        attributes={"status": "COMPLETED"},
    )
    raw_credential = boundary.export_situated_trace(
        _trace(),
        _principal(),
        resource_id="trace-resource-1",
        credential_ref="SECRET-CREDENTIAL-VALUE",  # type: ignore[arg-type]
        attributes={"status": "COMPLETED"},
    )

    assert raw.disposition is BoundaryDisposition.DENIED
    assert foreign.disposition is BoundaryDisposition.DENIED
    assert raw_credential.disposition is BoundaryDisposition.DENIED
    assert raw_credential.reason_code == "CREDENTIAL_VALUE_FORBIDDEN"
    assert exporter.records == []
