from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    CredentialAuthorizationSnapshot,
    CredentialLeaseRef,
    EnvironmentEventAdmissionReceipt,
    LedgerAccessScope,
    PayloadAdmissionAttestation,
    EventOriginRegistration,
    TaskDraftProposal,
    HelpRequest,
    canonical_json,
    credential_lease_digest,
)
from agent_os_core import (
    CanonicalCredentialLeaseRegistry,
    CredentialAuthorizationReader,
    EnvironmentEventAdmissionService,
    MandateSteward,
    OperationalProposalService,
    RelevanceAssessorPort,
    ScopedEventAdmissionReader,
    ScopedSituatedAssessmentReader,
    SituationalTrustDenied,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from agent_os_core.srl_event_store import _create_event_admission_store
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    TrustedObservationBundle,
)
from apps.api_server.data_agent_report_admission import (
    DataAgentReportAdmissionError,
    SQLiteDataAgentReportAdmissionMaterialStore,
    _DataAgentReportAdmissionRegistrar,
)


Clock = Callable[[], datetime]
ProposalResult = TaskDraftProposal | HelpRequest | None


class _OriginReader:
    __slots__ = ("_event_id", "_origin")

    def __init__(self, origin: EventOriginRegistration) -> None:
        self._event_id = origin.environment_event_id
        self._origin = origin

    def resolve_event(self, event_id: str) -> EventOriginRegistration | None:
        return self._origin if event_id == self._event_id else None


class _AttestationReader:
    __slots__ = ("_event_id", "_attestation")

    def __init__(self, attestation: PayloadAdmissionAttestation) -> None:
        self._event_id = attestation.environment_event_id
        self._attestation = attestation

    def resolve_event(self, event_id: str) -> PayloadAdmissionAttestation | None:
        return self._attestation if event_id == self._event_id else None


@dataclass(frozen=True)
class _AdmissionState:
    registrar: _DataAgentReportAdmissionRegistrar
    trust: DataAgentReportAdapter
    authority: ScopedSituatedAssessmentReader
    credentials: CredentialAuthorizationReader
    reader: ScopedEventAdmissionReader
    writer: Any
    required_scopes: frozenset[str]
    clock: Clock


def _canonical_authorization(value: object) -> CredentialAuthorizationSnapshot:
    if type(value) is not CredentialAuthorizationSnapshot:
        raise DataAgentReportAdmissionError(
            "credential authorization is not a canonical snapshot"
        )
    if (
        set(value.__dict__) != set(CredentialAuthorizationSnapshot.model_fields)
        or value.__pydantic_extra__
        or value.__pydantic_private__
    ):
        raise DataAgentReportAdmissionError(
            "credential authorization contains unknown state"
        )
    try:
        encoded = canonical_json(value).encode("utf-8")
        frozen = CredentialAuthorizationSnapshot.model_validate_json(
            encoded, strict=True
        )
    except (TypeError, ValueError):
        raise DataAgentReportAdmissionError(
            "credential authorization is invalid"
        ) from None
    if canonical_json(frozen).encode("utf-8") != encoded or frozen != value:
        raise DataAgentReportAdmissionError("credential authorization is not canonical")
    return frozen


class DataAgentAdmissionFacade:
    """Narrow event-id-only ingress over private admission authorities."""

    __slots__ = (
        "_authority",
        "_clock",
        "_credentials",
        "_reader",
        "_registrar",
        "_required_scopes",
        "_trust",
        "_writer",
    )

    def __init__(self) -> None:
        raise TypeError("facade is created only by the situated composition root")

    @classmethod
    def _from_composition(
        cls,
        state: _AdmissionState,
    ) -> DataAgentAdmissionFacade:
        self = object.__new__(cls)
        _state = state
        if type(_state) is not _AdmissionState:
            raise TypeError("facade requires deployment-internal composition state")
        self._registrar = _state.registrar
        self._trust = _state.trust
        self._authority = _state.authority
        self._credentials = _state.credentials
        self._reader = _state.reader
        self._writer = _state.writer
        self._required_scopes = _state.required_scopes
        self._clock = _state.clock
        return self

    def admit_event(self, event_id: str) -> EnvironmentEventAdmissionReceipt:
        material = self._registrar.prepare(event_id)
        try:
            credential = _canonical_authorization(
                self._credentials.resolve_authorization(
                    material.origin.credential_ref_id
                )
            )
            mandate, binding = self._authority.resolve_active(
                material.origin.mandate_id,
                material.origin.environment_binding_id,
                evaluated_at=self._clock(),
            )
            lease_payload = {
                "schema_version": "1.0",
                "credential_ref_id": credential.credential_ref_id,
                "credential_ref_digest": credential.credential_ref_digest,
                "source_id": material.origin.source_id,
                "principal_id": credential.owner_principal_id,
                "tenant_id": credential.tenant_id,
                "workspace_id": credential.workspace_id,
                "mandate_id": mandate.mandate_id,
                "environment_binding_id": binding.environment_binding_id,
                "correction_epoch": mandate.correction_epoch,
                "issued_at": material.origin.registered_at,
                "valid_from": max(
                    material.origin.registered_at,
                    credential.created_at,
                    mandate.valid_from,
                ),
                "expires_at": min(credential.expires_at, mandate.expires_at),
                "issuer_id": "data-agent-situated-bootstrap/v1",
            }
            digest = credential_lease_digest(lease_payload)
            lease = CredentialLeaseRef(
                lease_id=f"credential-lease:{digest}",
                lease_digest=digest,
                **lease_payload,
            )
        except (DataAgentReportAdmissionError, SituationalTrustDenied):
            raise
        except Exception:
            raise SituationalTrustDenied(
                "current admission authority is unavailable"
            ) from None

        service = EnvironmentEventAdmissionService(
            trust=self._trust,
            authority=self._authority,
            origins=_OriginReader(material.origin),
            leases=CanonicalCredentialLeaseRegistry((lease,)),
            credentials=self._credentials,
            attestations=_AttestationReader(material.attestation),
            admission_reader=self._reader,
            admission_writer=self._writer,
            principal_id=lease.principal_id,
            required_credential_scopes=self._required_scopes,
        )
        return service.admit(
            event_id,
            lease.lease_id,
            admitted_at=self._clock(),
        )


class DataAgentSituatedRuntime:
    """Safe Data Agent surface: observe, admit, then propose only."""

    __slots__ = ("_admission", "_adapter", "_steward")

    def __init__(self) -> None:
        raise TypeError("runtime is created only by the situated composition root")

    @classmethod
    def _from_composition(
        cls,
        *,
        adapter: DataAgentReportAdapter,
        admission: DataAgentAdmissionFacade,
        steward: MandateSteward,
    ) -> DataAgentSituatedRuntime:
        self = object.__new__(cls)
        self._adapter = adapter
        self._admission = admission
        self._steward = steward
        return self

    def observe_report(self, trace_id: str) -> TrustedObservationBundle:
        return self._adapter.pull(trace_id)

    def admit_event(self, event_id: str) -> EnvironmentEventAdmissionReceipt:
        return self._admission.admit_event(event_id)

    def propose(
        self,
        event_id: str,
        projection_id: str,
        receipt_id: str,
    ) -> ProposalResult:
        return self._steward.observe_event(event_id, projection_id, receipt_id)


class DataAgentSituatedBootstrap:
    """Deployment-internal composition for the receipt-required Data Agent slice."""

    @staticmethod
    def compose(
        *,
        adapter: DataAgentReportAdapter,
        material_store: SQLiteDataAgentReportAdmissionMaterialStore,
        credentials: CredentialAuthorizationReader,
        control: SQLiteSituatedAssessmentStore,
        assessor: RelevanceAssessorPort,
        admission_database: str | Path,
        clock: Clock,
    ) -> DataAgentSituatedRuntime:
        if type(adapter) is not DataAgentReportAdapter:
            raise TypeError("composition requires the concrete Data Agent adapter")
        if type(material_store) is not SQLiteDataAgentReportAdmissionMaterialStore:
            raise TypeError(
                "composition requires the concrete admission material store"
            )
        if type(control) is not SQLiteSituatedAssessmentStore:
            raise TypeError("composition requires the durable situated authority store")
        principal_id, tenant_id, workspace_id = adapter.principal_scope
        scope = LedgerAccessScope(
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        authority = control.scoped_reader(scope)
        reader, writer = _create_event_admission_store(
            admission_database,
            scope=scope,
        )
        registrar = _DataAgentReportAdmissionRegistrar(
            adapter,
            material_store,
            credentials,
            clock=clock,
        )
        proposal = OperationalProposalService(
            trust=adapter,
            control=control,
            assessor=assessor,
            principal_id=principal_id,
        )
        steward = MandateSteward(
            trust=adapter,
            authority=authority,
            proposal_service=proposal,
            admission_reader=reader,
            trace_writer=writer,
            principal_id=principal_id,
            clock=clock,
        )
        admission = DataAgentAdmissionFacade._from_composition(
            _AdmissionState(
                registrar=registrar,
                trust=adapter,
                authority=authority,
                credentials=credentials,
                reader=reader,
                writer=writer,
                required_scopes=frozenset(
                    adapter.admission_policy_descriptor.required_credential_scopes
                ),
                clock=clock,
            )
        )
        return DataAgentSituatedRuntime._from_composition(
            adapter=adapter,
            admission=admission,
            steward=steward,
        )


__all__ = [
    "DataAgentAdmissionFacade",
    "DataAgentSituatedBootstrap",
    "DataAgentSituatedRuntime",
]
