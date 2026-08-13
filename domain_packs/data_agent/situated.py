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
    ExternalStateAuthorizationReceipt,
    LedgerAccessScope,
    PayloadAdmissionAttestation,
    EventOriginRegistration,
    TaskDraftProposal,
    HelpRequest,
    ProtocolIngressReceipt,
    SituatedAssessmentRecord,
    WorkloadIdentityRegistration,
    canonical_json,
    content_digest,
    credential_lease_digest,
)
from agent_os_core import (
    CanonicalCredentialLeaseRegistry,
    CredentialAuthorizationReader,
    EnvironmentEventAdmissionService,
    EventEnvelopeAdapter,
    ExternalStateSourceAdapter,
    InMemoryExternalStateAuthorizationRegistry,
    MandateSteward,
    OperationalProposalService,
    ProviderRelevanceAssessor,
    RelevanceAssessorPort,
    ScopedEventAdmissionReader,
    SQLiteProtocolIngressStore,
    ScopedSituatedAssessmentReader,
    SituationalTrustDenied,
    WorkloadIdentityAdapter,
    TrustedWorkingSetAssembler,
    WORKING_SET_SELECTION_POLICY_DIGEST,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from agent_os_core.srl_event_store import _create_event_admission_store
from .report_adapter import (
    DataAgentReportAdapter,
    TrustedObservationBundle,
    _active_perception_binding_digest,
)
from .report_admission import (
    DataAgentReportAdmissionError,
    SQLiteDataAgentReportAdmissionMaterialStore,
    _DataAgentReportAdmissionRegistrar,
)


Clock = Callable[[], datetime]
ProposalResult = TaskDraftProposal | HelpRequest | None
_RUNTIME_COMPOSITION_SEAL = object()


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


@dataclass(frozen=True)
class _ObservationAuthorityGuard:
    control: SQLiteSituatedAssessmentStore
    descriptor: Any
    assessor_ref: Any
    context_ref: Any
    scope: LedgerAccessScope
    clock: Clock

    def snapshot(self) -> str:
        mandate, binding = self.control.resolve_observation_authority(
            self.descriptor.mandate_id,
            self.descriptor.environment_binding_id,
            principal_id=self.scope.principal_id,
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            evaluated_at=self.clock(),
            source_descriptor_digest=self.descriptor.policy_digest,
            relevance_assessor=self.assessor_ref,
            relevance_context=self.context_ref,
        )
        if (
            mandate.relevance_assessor != self.assessor_ref
            or mandate.relevance_context != self.context_ref
            or binding.environment_binding_id != self.descriptor.environment_binding_id
        ):
            raise SituationalTrustDenied(
                "current observation authority differs from active perception binding"
            )
        return content_digest(
            {
                "mandate_id": mandate.mandate_id,
                "mandate_version": mandate.version,
                "mandate_digest": mandate.mandate_digest,
                "correction_epoch": mandate.correction_epoch,
                "observation_authorization_id": mandate.observation_authorization_id,
                "observation_authorization_receipt_digest": (
                    mandate.observation_authorization_receipt_digest
                ),
                "workspace_record_digest": mandate.workspace_record_digest,
                "environment_binding": binding,
                "source_descriptor_digest": self.descriptor.policy_digest,
                "relevance_assessor": self.assessor_ref,
                "relevance_context": self.context_ref,
                "scope": self.scope,
            }
        )


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
        "_principal_scope",
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
        principal_scope = tuple(_state.trust.principal_scope)
        authority_scope = (
            _state.authority.scope.principal_id,
            _state.authority.scope.tenant_id,
            _state.authority.scope.workspace_id,
        )
        reader_scope = (
            _state.reader.scope.principal_id,
            _state.reader.scope.tenant_id,
            _state.reader.scope.workspace_id,
        )
        if authority_scope != principal_scope or reader_scope != principal_scope:
            raise TypeError("facade composition scope is inconsistent")
        self._registrar = _state.registrar
        self._trust = _state.trust
        self._authority = _state.authority
        self._credentials = _state.credentials
        self._reader = _state.reader
        self._writer = _state.writer
        self._required_scopes = _state.required_scopes
        self._principal_scope = principal_scope
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

    __slots__ = (
        "_admission",
        "_active_perception_binding_digest",
        "_active_perception_database_path",
        "_active_perception_environment_binding_id",
        "_active_perception_mandate_id",
        "_adapter",
        "_composition_seal",
        "_principal_scope",
        "_envelope_adapter",
        "_protocol_ingress_store",
        "_workload_identity_adapter",
        "_steward",
        "_observation_authority_guard",
    )

    def __init__(self) -> None:
        raise TypeError("runtime is created only by the situated composition root")

    @classmethod
    def _from_composition(
        cls,
        *,
        adapter: DataAgentReportAdapter,
        admission: DataAgentAdmissionFacade,
        steward: MandateSteward,
        envelope_adapter: EventEnvelopeAdapter,
        protocol_ingress_store: SQLiteProtocolIngressStore,
        workload_identity_adapter: WorkloadIdentityAdapter,
        observation_authority_guard: _ObservationAuthorityGuard | None = None,
        composition_seal: object | None = None,
    ) -> DataAgentSituatedRuntime:
        if (
            composition_seal is not _RUNTIME_COMPOSITION_SEAL
            or type(adapter) is not DataAgentReportAdapter
            or type(admission) is not DataAgentAdmissionFacade
            or type(steward) is not MandateSteward
            or type(envelope_adapter) is not EventEnvelopeAdapter
            or type(protocol_ingress_store) is not SQLiteProtocolIngressStore
            or type(workload_identity_adapter) is not WorkloadIdentityAdapter
        ):
            raise TypeError("runtime requires deployment-internal composition")
        principal_scope = tuple(adapter.principal_scope)
        steward_scope = (
            steward.scope.principal_id,
            steward.scope.tenant_id,
            steward.scope.workspace_id,
        )
        if (
            admission._principal_scope != principal_scope
            or steward_scope != principal_scope
        ):
            raise TypeError("runtime composition scope is inconsistent")
        if (
            admission._trust is not adapter
            or steward._trust is not adapter
            or admission._authority is not steward._authority
            or admission._reader is not steward._admission_reader
            or admission._writer is not steward._trace_writer
        ):
            raise TypeError("runtime composition reader chain is inconsistent")
        if type(observation_authority_guard) is not _ObservationAuthorityGuard:
            raise TypeError("runtime requires an observation authority guard")
        self = object.__new__(cls)
        self._adapter = adapter
        self._admission = admission
        self._steward = steward
        self._envelope_adapter = envelope_adapter
        self._protocol_ingress_store = protocol_ingress_store
        self._workload_identity_adapter = workload_identity_adapter
        self._observation_authority_guard = observation_authority_guard
        self._principal_scope = principal_scope
        database = observation_authority_guard.control.canonical_database_path
        descriptor = observation_authority_guard.descriptor
        if adapter.active_perception_database_path != database:
            raise TypeError("runtime report and situated databases must be identical")
        self._active_perception_database_path = database
        self._active_perception_mandate_id = descriptor.mandate_id
        self._active_perception_environment_binding_id = (
            descriptor.environment_binding_id
        )
        self._active_perception_binding_digest = _active_perception_binding_digest(
            principal_id=principal_scope[0],
            tenant_id=principal_scope[1],
            workspace_id=principal_scope[2],
            mandate_id=descriptor.mandate_id,
            environment_binding_id=descriptor.environment_binding_id,
            state_namespace=adapter._state_namespace,
            admission_policy_digest=descriptor.policy_digest,
            canonical_database_path=database,
        )
        self._composition_seal = composition_seal
        return self

    def _is_bootstrap_composed(self) -> bool:
        return self._composition_seal is _RUNTIME_COMPOSITION_SEAL

    def observe_report(self, trace_id: str) -> TrustedObservationBundle:
        return self._adapter.pull(trace_id)

    @property
    def principal_scope(self) -> tuple[str, str, str]:
        return self._principal_scope

    @property
    def active_perception_binding_digest(self) -> str:
        return self._active_perception_binding_digest

    @property
    def active_perception_database_path(self) -> Path:
        return self._active_perception_database_path

    @property
    def active_perception_mandate_id(self) -> str:
        return self._active_perception_mandate_id

    @property
    def active_perception_environment_binding_id(self) -> str:
        return self._active_perception_environment_binding_id

    def admit_event(self, event_id: str) -> EnvironmentEventAdmissionReceipt:
        return self._admission.admit_event(event_id)

    def assert_observation_authority(self) -> str:
        return self._observation_authority_guard.snapshot()

    def propose(
        self,
        event_id: str,
        projection_id: str,
        receipt_id: str,
    ) -> ProposalResult:
        return self._steward.observe_event(event_id, projection_id, receipt_id)

    def propose_record(
        self,
        event_id: str,
        projection_id: str,
        receipt_id: str,
    ) -> SituatedAssessmentRecord:
        return self._steward.observe_event_record(event_id, projection_id, receipt_id)

    def propose_authenticated_protocol_envelope(
        self,
        raw_envelope: dict[str, Any],
        workload_assertion: str,
    ) -> ProtocolIngressReceipt:
        envelope = self._envelope_adapter.parse(raw_envelope)
        authorization = self._workload_identity_adapter.authenticate(
            workload_assertion, envelope, self._principal_scope
        )
        replay = self._protocol_ingress_store.replay_or_reserve(authorization, envelope)
        if replay is not None:
            return replay
        try:
            bundle = self.observe_report(envelope.trace_id)
            if bundle.event.environment_binding_id != authorization.source_binding_id:
                raise SituationalTrustDenied(
                    "authenticated workload is not bound to observed environment"
                )
            admission = self.admit_event(bundle.event.environment_event_id)
            proposal = self.propose(
                bundle.event.environment_event_id,
                bundle.projection.projection_id,
                admission.receipt_id,
            )
        except Exception:
            # Conservative boundary: once reserved, every uncertain failure is
            # durable FAILED state. Never delete even if no effect is yet proven.
            self._protocol_ingress_store.fail(authorization, envelope)
            raise
        if isinstance(proposal, TaskDraftProposal):
            outcome_kind = "TASK_DRAFT"
            task_draft = proposal
            help_request = None
        elif isinstance(proposal, HelpRequest):
            outcome_kind = "HELP_REQUEST"
            task_draft = None
            help_request = proposal
        else:
            outcome_kind = "NO_PROPOSAL"
            task_draft = None
            help_request = None
        receipt_payload = {
            "schema_version": "1.0",
            "principal_id": authorization.principal.principal_id,
            "tenant_id": authorization.principal.tenant_id,
            "workspace_id": authorization.principal.workspace_id,
            "source_binding_id": authorization.source_binding_id,
            "protocol": envelope.protocol,
            "protocol_message_id": envelope.protocol_message_id,
            "binding_digest": authorization.binding_digest,
            "envelope_digest": envelope.envelope_digest,
            "source_binding_authorization_digest": content_digest(authorization),
            "admission_receipt_id": admission.receipt_id,
            "outcome_kind": outcome_kind,
            "task_draft": task_draft,
            "help_request": help_request,
            "activation_authorized": False,
            "capability_grant_authorized": False,
            "external_effects_authorized": False,
        }
        receipt_digest = content_digest(receipt_payload)
        receipt = ProtocolIngressReceipt(
            receipt_id=f"protocol-ingress:{receipt_digest}",
            receipt_digest=receipt_digest,
            principal_id=authorization.principal.principal_id,
            tenant_id=authorization.principal.tenant_id,
            workspace_id=authorization.principal.workspace_id,
            source_binding_id=authorization.source_binding_id,
            protocol=envelope.protocol,
            protocol_message_id=envelope.protocol_message_id,
            binding_digest=authorization.binding_digest,
            envelope_digest=envelope.envelope_digest,
            source_binding_authorization_digest=content_digest(authorization),
            admission_receipt_id=admission.receipt_id,
            outcome_kind=outcome_kind,
            task_draft=task_draft,
            help_request=help_request,
        )
        return self._protocol_ingress_store.complete(authorization, envelope, receipt)


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
        workload_identities: tuple[WorkloadIdentityRegistration, ...] = (),
        external_state_adapters: tuple[ExternalStateSourceAdapter, ...] = (),
        external_state_authorization_receipts: tuple[
            ExternalStateAuthorizationReceipt, ...
        ] = (),
    ) -> DataAgentSituatedRuntime:
        if type(adapter) is not DataAgentReportAdapter:
            raise TypeError("composition requires the concrete Data Agent adapter")
        if type(material_store) is not SQLiteDataAgentReportAdmissionMaterialStore:
            raise TypeError(
                "composition requires the concrete admission material store"
            )
        if type(control) is not SQLiteSituatedAssessmentStore:
            raise TypeError("composition requires the durable situated authority store")
        report_database = adapter.active_perception_database_path
        if (
            report_database is None
            or control.canonical_database_path != report_database
        ):
            raise TypeError(
                "composition report and situated databases must be identical"
            )
        if adapter._credential_authorization_reader_for_composition is not credentials:
            raise TypeError("composition requires one credential authorization reader")
        principal_id, tenant_id, workspace_id = adapter.principal_scope
        descriptor = adapter.admission_policy_descriptor
        candidate_mandate, _ = control.resolve_active(
            descriptor.mandate_id,
            descriptor.environment_binding_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluated_at=clock(),
        )
        context_ref = candidate_mandate.relevance_context
        mandate, binding = control.resolve_observation_authority(
            descriptor.mandate_id,
            descriptor.environment_binding_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluated_at=clock(),
            source_descriptor_digest=descriptor.policy_digest,
            relevance_assessor=assessor.ref,
            relevance_context=context_ref,
        )
        if context_ref is None:
            raise SituationalTrustDenied(
                "verified observation authorization context is unavailable"
            )
        context = (
            assessor._resolve_context_for_composition(context_ref)
            if type(assessor) is ProviderRelevanceAssessor
            else None
        )
        if type(assessor) is ProviderRelevanceAssessor and (
            context is None
            or context.ref() != context_ref
            or context.mandate_id != mandate.mandate_id
            or context.mandate_version != mandate.version
            or context.mandate_digest != mandate.mandate_digest
            or context.tenant_id != mandate.tenant_id
            or context.workspace_id != mandate.workspace_id
        ):
            raise TypeError("composition requires exact observation authorization")
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
            admission_reader=reader,
            working_set_assembler=TrustedWorkingSetAssembler(
                adapters=external_state_adapters,
                authorization_registry=InMemoryExternalStateAuthorizationRegistry(
                    external_state_authorization_receipts
                ),
                selection_policy_digest=WORKING_SET_SELECTION_POLICY_DIGEST,
            ),
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
            envelope_adapter=EventEnvelopeAdapter(),
            protocol_ingress_store=SQLiteProtocolIngressStore(admission_database),
            workload_identity_adapter=WorkloadIdentityAdapter(workload_identities),
            observation_authority_guard=_ObservationAuthorityGuard(
                control=control,
                descriptor=descriptor,
                assessor_ref=assessor.ref,
                context_ref=context_ref,
                scope=scope,
                clock=clock,
            ),
            composition_seal=_RUNTIME_COMPOSITION_SEAL,
        )


__all__ = [
    "DataAgentAdmissionFacade",
    "DataAgentSituatedBootstrap",
    "DataAgentSituatedRuntime",
]
