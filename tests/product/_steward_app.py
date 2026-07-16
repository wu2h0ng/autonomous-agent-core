"""Test-only composition of the real receipt-required application spine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    EnvironmentEventAdmissionReceipt,
    LedgerAccessScope,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    ProviderRelevancePolicy,
    content_digest,
    environment_event_admission_receipt_digest,
)
from agent_os_core import (
    MandateRelevanceContextReader,
    MandateSteward,
    OperationalProposalService,
    ProviderPort,
    ProviderRelevanceAssessor,
    RelevanceAssessorPort,
    SituationalTrustDenied,
    SituationalTrustResolver,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from agent_os_core.srl_event_store import _create_event_admission_store
from apps.api_server.app import AgentOSApplication


def admitted_application(
    *,
    database: Path,
    workspace: Path,
    trust: SituationalTrustResolver,
    control: SQLiteSituatedAssessmentStore,
    event_id: str,
    projection_id: str,
    clock: Callable[[], datetime],
    principal: PrincipalIdentity | None = None,
    assessor: RelevanceAssessorPort | None = None,
    provider_policy: ProviderRelevancePolicy | None = None,
    contexts: MandateRelevanceContextReader | None = None,
    provider: ProviderPort | None = None,
    provider_profile: ProviderProfile | None = None,
    data_agent_reports: Any | None = None,
) -> tuple[AgentOSApplication, EnvironmentEventAdmissionReceipt]:
    if assessor is None:
        if None in (provider_policy, contexts, provider, provider_profile):
            raise ValueError("test provider composition is incomplete")
        assessor = ProviderRelevanceAssessor(
            provider=provider,  # type: ignore[arg-type]
            provider_profile=provider_profile,  # type: ignore[arg-type]
            policy=provider_policy,  # type: ignore[arg-type]
            trust=trust,
            contexts=contexts,  # type: ignore[arg-type]
        )
    event = trust.resolve_event(event_id)
    projection = trust.resolve_projection(projection_id)
    if event is None or projection is None:
        raise ValueError("test trust registry lacks event or projection")
    if principal is None:
        mandate, _ = control.resolve_active(
            event.mandate_id,
            event.environment_binding_id,
            principal_id="user:local",
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            evaluated_at=clock(),
        )
        principal = PrincipalIdentity(
            principal_id=mandate.owner_principal_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=clock(),
        )
    scope = LedgerAccessScope(
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    mandate, binding = control.resolve_active(
        event.mandate_id,
        event.environment_binding_id,
        principal_id=scope.principal_id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        evaluated_at=clock(),
    )
    proposal = OperationalProposalService(
        trust=trust,
        control=control,
        assessor=assessor,
        principal_id=scope.principal_id,
    )
    admission_reader, admission_writer = _create_event_admission_store(
        database.with_name(f"{database.name}.admission.sqlite3"), scope=scope
    )
    payload: dict[str, Any] = {
        "schema_version": "1.1",
        "environment_event_id": event_id,
        "event_digest": content_digest(event),
        "event_origin_digest": "1" * 64,
        "credential_lease_digest": "2" * 64,
        "payload_attestation_digest": "3" * 64,
        "admission_policy_digest": "4" * 64,
        "mandate_id": mandate.mandate_id,
        "environment_binding_id": binding.environment_binding_id,
        "environment_binding_version": binding.version,
        "environment_binding_digest": binding.binding_digest,
        "correction_epoch": mandate.correction_epoch,
        "principal_id": scope.principal_id,
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "admitted_at": clock(),
        "issued_by": "event-admission-service/v1",
        "grants_authority": False,
        "authorizes_effects": False,
    }
    digest = environment_event_admission_receipt_digest(payload)
    receipt = EnvironmentEventAdmissionReceipt(
        receipt_id=f"event-admission:{digest}", receipt_digest=digest, **payload
    )
    admission_writer.persist_receipt(receipt)
    steward = MandateSteward(
        trust=trust,
        authority=control.scoped_reader(scope),
        proposal_service=proposal,
        admission_reader=admission_reader,
        trace_writer=admission_writer,
        principal_id=scope.principal_id,
        clock=clock,
    )
    application = AgentOSApplication._with_mandate_steward(
        mandate_steward=steward,
        database=database,
        workspace=workspace,
        principal=principal,
        clock=clock,
        situational_trust=trust,
        data_agent_reports=data_agent_reports,
    )
    return application, receipt


class DeferredAdmittedApplication:
    """Test harness that admits the selected trusted event before each call."""

    def __init__(self, **composition: Any) -> None:
        self._composition = composition
        self._base = AgentOSApplication(
            database=composition["database"],
            workspace=composition["workspace"],
            principal=composition.get("principal"),
            clock=composition["clock"],
            situational_trust=composition.get("trust"),
            data_agent_reports=composition.get("data_agent_reports"),
        )

    @property
    def store(self):  # type: ignore[no-untyped-def]
        return self._base.store

    @property
    def principal(self):  # type: ignore[no-untyped-def]
        return self._base.principal

    def observe_data_agent_report(self, trace_id: str):  # type: ignore[no-untyped-def]
        return self._base.observe_data_agent_report(trace_id)

    def propose_situated_work(
        self, event_id: str, projection_id: str
    ):  # type: ignore[no-untyped-def]
        try:
            application, receipt = admitted_application(
                event_id=event_id,
                projection_id=projection_id,
                **self._composition,
            )
        except ValueError as error:
            if str(error) == "test trust registry lacks event or projection":
                raise SituationalTrustDenied(
                    "admitted event or projection is unavailable"
                ) from None
            raise
        return application.propose_situated_work(
            event_id, projection_id, receipt.receipt_id
        )
