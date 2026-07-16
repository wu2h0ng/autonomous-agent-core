from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Iterable, Protocol, TypeAlias

from agent_os_contracts import (
    ArtifactRef,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EvidenceRef,
    HelpRequest,
    LedgerAccessScope,
    MandateOperationalStatus,
    OperationalProjectionRef,
    ProposedGoal,
    RatifiedMandateRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    SituatedAssessmentRecord,
    TaskDraftProposal,
    content_digest,
)

from .errors import (
    SituationalPersistenceConflict,
    SituationalScopeMismatch,
    SituationalTrustDenied,
    StaleOperationalProjection,
)
from .situated_persistence import (
    ProposalResult,
    SituatedAssessmentStore,
    proposal_result,
    situated_assessment_record,
    scoped_situated_assessment_reader,
    ScopedSituatedAssessmentReader,
)


SituationalBinding: TypeAlias = tuple[str, str, str, str, str]


def situated_input_binding_digest(
    mandate: RatifiedMandateRef,
    binding: EnvironmentBindingAuthorization,
    event: EnvironmentEvent,
    projection: OperationalProjectionRef,
    assessor: RelevanceAssessorRef,
) -> str:
    return content_digest(
        {
            "mandate_id": mandate.mandate_id,
            "mandate_version": mandate.version,
            "mandate_digest": mandate.mandate_digest,
            "correction_epoch": mandate.correction_epoch,
            "relevance_context": (
                mandate.relevance_context.model_dump(mode="json")
                if mandate.relevance_context is not None
                else None
            ),
            "environment_binding": binding.model_dump(mode="json"),
            "event": event.model_dump(mode="json"),
            "projection": projection.model_dump(mode="json"),
            "assessor": assessor.model_dump(mode="json"),
        }
    )


def situated_source_binding_digest(
    event: EnvironmentEvent,
    projection: OperationalProjectionRef,
    assessment: RelevanceAssessment,
) -> str:
    return content_digest(
        {
            "event": event.model_dump(mode="json"),
            "projection": projection.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
        }
    )


class RelevanceAssessorPort(Protocol):
    @property
    def ref(self) -> RelevanceAssessorRef: ...

    def assess(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        *,
        assessed_at: datetime,
    ) -> RelevanceAssessment: ...


class InMemorySituationalControlPlane:
    """V0 external-ratification and epoch guard; it grants no task authority."""

    durable = False

    def __init__(self, mandates: Iterable[RatifiedMandateRef] = ()) -> None:
        self._lock = RLock()
        self._mandates: dict[str, RatifiedMandateRef] = {}
        self._records: dict[str, SituatedAssessmentRecord] = {}
        self._record_ids_by_source: dict[str, str] = {}
        for mandate in mandates:
            if mandate.mandate_id in self._mandates:
                raise ValueError("ratified mandate ids must be unique")
            self._mandates[mandate.mandate_id] = mandate

    def resolve_active(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        with self._lock:
            return self._resolve_active_unlocked(
                mandate_id,
                environment_binding_id,
                principal_id=principal_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                evaluated_at=evaluated_at,
            )

    def _resolve_active_unlocked(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        mandate = self._mandates.get(mandate_id)
        if mandate is None:
            raise SituationalTrustDenied("ratified mandate is unavailable")
        if (
            mandate.owner_principal_id != principal_id
            or mandate.tenant_id != tenant_id
            or mandate.workspace_id != workspace_id
        ):
            raise SituationalTrustDenied("ratified mandate scope is not authorized")
        if mandate.status is not MandateOperationalStatus.ACTIVE:
            raise SituationalTrustDenied("ratified mandate is not active")
        if evaluated_at < mandate.valid_from or evaluated_at >= mandate.expires_at:
            raise SituationalTrustDenied(
                "ratified mandate is not active at evaluation time"
            )
        binding = mandate.binding(environment_binding_id)
        if binding is None:
            raise SituationalTrustDenied("environment binding is not ratified")
        return mandate, binding

    def _emit_guarded(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        assessment: RelevanceAssessment,
        *,
        principal_id: str,
        evaluated_at: datetime,
        source_binding_digest: str,
        factory: Callable[[], ProposalResult],
    ) -> ProposalResult:
        with self._lock:
            current, current_binding = self._resolve_active_unlocked(
                mandate.mandate_id,
                binding.environment_binding_id,
                principal_id=principal_id,
                tenant_id=mandate.tenant_id,
                workspace_id=mandate.workspace_id,
                evaluated_at=evaluated_at,
            )
            if current != mandate or current_binding != binding:
                raise SituationalTrustDenied(
                    "mandate or environment binding epoch changed before emission"
                )
            result = factory()
            record = situated_assessment_record(
                assessment,
                result,
                source_binding_digest=source_binding_digest,
            )
            existing_by_id = self._records.get(assessment.assessment_id)
            existing_id = self._record_ids_by_source.get(source_binding_digest)
            existing_by_source = (
                self._records.get(existing_id) if existing_id is not None else None
            )
            existing = existing_by_id or existing_by_source
            if existing is not None:
                if existing != record:
                    raise SituationalPersistenceConflict(
                        "assessment identity or source binding conflicts with record"
                    )
                return proposal_result(existing)
            self._records[assessment.assessment_id] = record
            self._record_ids_by_source[source_binding_digest] = assessment.assessment_id
            return result

    def assessment(self, assessment_id: str) -> RelevanceAssessment | None:
        with self._lock:
            record = self._records.get(assessment_id)
            return record.assessment if record is not None else None

    def assessment_record(self, assessment_id: str) -> SituatedAssessmentRecord | None:
        with self._lock:
            return self._records.get(assessment_id)

    def record_by_source_binding(
        self, source_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        with self._lock:
            assessment_id = self._record_ids_by_source.get(source_binding_digest)
            return (
                self._records.get(assessment_id) if assessment_id is not None else None
            )

    def record_by_input_binding(
        self, input_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        with self._lock:
            return next(
                (
                    record
                    for record in self._records.values()
                    if record.assessment.input_binding_digest == input_binding_digest
                ),
                None,
            )

    def scoped_reader(
        self, scope: LedgerAccessScope
    ) -> ScopedSituatedAssessmentReader:
        return scoped_situated_assessment_reader(self, scope)

    def replay_if_active(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        input_binding_digest: str,
        *,
        principal_id: str,
        evaluated_at: datetime,
    ) -> SituatedAssessmentRecord | None:
        with self._lock:
            current, current_binding = self._resolve_active_unlocked(
                mandate.mandate_id,
                binding.environment_binding_id,
                principal_id=principal_id,
                tenant_id=mandate.tenant_id,
                workspace_id=mandate.workspace_id,
                evaluated_at=evaluated_at,
            )
            if current != mandate or current_binding != binding:
                raise SituationalTrustDenied(
                    "mandate or environment binding epoch changed before replay"
                )
            record = next(
                (
                    item
                    for item in self._records.values()
                    if item.assessment.input_binding_digest == input_binding_digest
                ),
                None,
            )
            if record is not None and (
                record.assessment.assessment_id
                != f"relevance-assessment:{input_binding_digest}"
                or record.tenant_id != mandate.tenant_id
                or record.workspace_id != mandate.workspace_id
            ):
                raise SituationalPersistenceConflict(
                    "replay record does not match guarded input binding"
                )
            return record

    def pause(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.PAUSED,
        )

    def revoke(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.REVOKED,
        )

    def _change_status(
        self,
        mandate_id: str,
        *,
        expected_epoch: int,
        status: MandateOperationalStatus,
    ) -> RatifiedMandateRef:
        with self._lock:
            current = self._mandates.get(mandate_id)
            if current is None:
                raise SituationalTrustDenied("ratified mandate is unavailable")
            if current.correction_epoch != expected_epoch:
                raise SituationalTrustDenied("mandate correction epoch changed")
            updated = current.model_copy(
                update={
                    "status": status,
                    "correction_epoch": current.correction_epoch + 1,
                }
            )
            self._mandates[mandate_id] = updated
            return updated


class SituationalTrustResolver(Protocol):
    def binding_is_authorized(self, binding: SituationalBinding) -> bool: ...

    def resolve_artifact(
        self, artifact_id: str
    ) -> tuple[ArtifactRef, bytes] | None: ...

    def resolve_evidence(self, evidence_id: str) -> EvidenceRef | None: ...

    def resolve_event(self, event_id: str) -> EnvironmentEvent | None: ...

    def resolve_projection(
        self, projection_id: str
    ) -> OperationalProjectionRef | None: ...


class _DenyAllSituationalTrust:
    def binding_is_authorized(self, binding: SituationalBinding) -> bool:
        return False

    def resolve_artifact(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
        return None

    def resolve_evidence(self, evidence_id: str) -> EvidenceRef | None:
        return None

    def resolve_event(self, event_id: str) -> EnvironmentEvent | None:
        return None

    def resolve_projection(self, projection_id: str) -> OperationalProjectionRef | None:
        return None


class InMemorySituationalTrustRegistry:
    """Immutable V0 trust adapter; production adapters may resolve durable stores."""

    def __init__(
        self,
        *,
        bindings: Iterable[SituationalBinding] = (),
        artifacts: Iterable[tuple[ArtifactRef, bytes]] = (),
        evidence: Iterable[EvidenceRef] = (),
        events: Iterable[EnvironmentEvent] = (),
        projections: Iterable[OperationalProjectionRef] = (),
    ) -> None:
        self._bindings = frozenset(bindings)
        self._artifacts = self._unique_artifacts(artifacts)
        self._evidence = self._unique_evidence(evidence)
        self._events = self._unique_contracts(
            events, id_attribute="environment_event_id", contract_name="event"
        )
        self._projections = self._unique_contracts(
            projections, id_attribute="projection_id", contract_name="projection"
        )

    @staticmethod
    def _unique_artifacts(
        artifacts: Iterable[tuple[ArtifactRef, bytes]],
    ) -> dict[str, tuple[ArtifactRef, bytes]]:
        indexed: dict[str, tuple[ArtifactRef, bytes]] = {}
        for artifact, content in artifacts:
            if artifact.artifact_id in indexed:
                raise ValueError("trusted artifact ids must be unique")
            indexed[artifact.artifact_id] = (artifact, bytes(content))
        return indexed

    @staticmethod
    def _unique_evidence(evidence: Iterable[EvidenceRef]) -> dict[str, EvidenceRef]:
        indexed: dict[str, EvidenceRef] = {}
        for item in evidence:
            if item.evidence_id in indexed:
                raise ValueError("trusted evidence ids must be unique")
            indexed[item.evidence_id] = item
        return indexed

    @staticmethod
    def _unique_contracts(
        contracts: Iterable[EnvironmentEvent] | Iterable[OperationalProjectionRef],
        *,
        id_attribute: str,
        contract_name: str,
    ) -> dict[str, EnvironmentEvent | OperationalProjectionRef]:
        indexed: dict[str, EnvironmentEvent | OperationalProjectionRef] = {}
        for contract in contracts:
            contract_id = str(getattr(contract, id_attribute))
            if contract_id in indexed:
                raise ValueError(f"trusted {contract_name} ids must be unique")
            indexed[contract_id] = contract
        return indexed

    def binding_is_authorized(self, binding: SituationalBinding) -> bool:
        return binding in self._bindings

    def resolve_artifact(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
        return self._artifacts.get(artifact_id)

    def resolve_evidence(self, evidence_id: str) -> EvidenceRef | None:
        return self._evidence.get(evidence_id)

    def resolve_event(self, event_id: str) -> EnvironmentEvent | None:
        resolved = self._events.get(event_id)
        return resolved if isinstance(resolved, EnvironmentEvent) else None

    def resolve_projection(self, projection_id: str) -> OperationalProjectionRef | None:
        resolved = self._projections.get(projection_id)
        return resolved if isinstance(resolved, OperationalProjectionRef) else None


class OperationalProposalService:
    """Resolve trusted inputs, invoke one ratified assessor, then emit under epoch guard."""

    def __init__(
        self,
        *,
        trust: SituationalTrustResolver,
        control: SituatedAssessmentStore,
        assessor: RelevanceAssessorPort,
        principal_id: str,
    ) -> None:
        self._trust = trust
        self._control = control
        self._assessor = assessor
        self._principal_id = principal_id
        self._compiler = _OperationalProposalCompiler(
            trust,
            principal_id=principal_id,
        )

    def propose(
        self,
        event_id: str,
        projection_id: str,
        *,
        evaluated_at: datetime,
    ) -> ProposalResult:
        evaluated_at = _OperationalProposalCompiler._utc(evaluated_at)
        event = self._trust.resolve_event(event_id)
        projection = self._trust.resolve_projection(projection_id)
        if event is None or projection is None:
            raise SituationalTrustDenied("trusted event or projection is unavailable")
        self._validate_input_pair(event, projection)
        mandate, binding = self._control.resolve_active(
            event.mandate_id,
            event.environment_binding_id,
            principal_id=self._principal_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            evaluated_at=evaluated_at,
        )
        expected_assessor = mandate.relevance_assessor
        if self._assessor.ref != expected_assessor:
            raise SituationalTrustDenied("relevance assessor is not ratified")
        input_binding_digest = situated_input_binding_digest(
            mandate,
            binding,
            event,
            projection,
            expected_assessor,
        )
        existing = self._control.replay_if_active(
            mandate,
            binding,
            input_binding_digest,
            principal_id=self._principal_id,
            evaluated_at=evaluated_at,
        )
        if existing is not None:
            self._validate_assessment(
                existing.assessment,
                mandate=mandate,
                binding=binding,
                event=event,
                projection=projection,
            )
            _OperationalProposalCompiler._validate_time(
                event,
                projection,
                existing.assessment,
                evaluated_at,
            )
            return proposal_result(existing)
        assessment = self._assessor.assess(
            mandate,
            binding,
            event,
            projection,
            assessed_at=evaluated_at,
        )
        self._validate_assessment(
            assessment,
            mandate=mandate,
            binding=binding,
            event=event,
            projection=projection,
        )
        source_binding_digest = situated_source_binding_digest(
            event,
            projection,
            assessment,
        )
        return self._control._emit_guarded(
            mandate,
            binding,
            assessment,
            principal_id=self._principal_id,
            evaluated_at=evaluated_at,
            source_binding_digest=source_binding_digest,
            factory=lambda: self._compiler.compile(
                event,
                projection,
                assessment,
                evaluated_at=evaluated_at,
            ),
        )

    def _validate_input_pair(
        self,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
    ) -> None:
        exact_values = (
            (projection.mandate_id, event.mandate_id, "mandate"),
            (
                projection.environment_binding_id,
                event.environment_binding_id,
                "environment binding",
            ),
            (projection.tenant_id, event.tenant_id, "tenant"),
            (projection.workspace_id, event.workspace_id, "workspace"),
        )
        for actual, expected, label in exact_values:
            if actual != expected:
                raise SituationalTrustDenied(
                    f"trusted event and projection {label} do not match"
                )
        if event.environment_event_id not in projection.source_event_ids:
            raise SituationalTrustDenied(
                "trusted projection does not reference the event"
            )
        binding: SituationalBinding = (
            self._principal_id,
            event.tenant_id,
            event.workspace_id,
            event.mandate_id,
            event.environment_binding_id,
        )
        if not self._trust.binding_is_authorized(binding):
            raise SituationalTrustDenied("situated input binding is not authorized")

    def _validate_assessment(
        self,
        assessment: RelevanceAssessment,
        *,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
    ) -> None:
        expected_input_digest = situated_input_binding_digest(
            mandate,
            binding,
            event,
            projection,
            mandate.relevance_assessor,
        )
        exact_values = (
            (assessment.mandate_id, mandate.mandate_id, "mandate id"),
            (assessment.mandate_version, mandate.version, "mandate version"),
            (assessment.mandate_digest, mandate.mandate_digest, "mandate digest"),
            (
                assessment.environment_binding_id,
                binding.environment_binding_id,
                "environment binding id",
            ),
            (
                assessment.environment_binding_version,
                binding.version,
                "environment binding version",
            ),
            (
                assessment.environment_binding_digest,
                binding.binding_digest,
                "environment binding digest",
            ),
            (
                assessment.correction_epoch,
                mandate.correction_epoch,
                "mandate correction epoch",
            ),
            (assessment.assessor, mandate.relevance_assessor, "assessor"),
            (
                assessment.input_binding_digest,
                expected_input_digest,
                "assessment input binding digest",
            ),
            (assessment.tenant_id, mandate.tenant_id, "tenant"),
            (assessment.workspace_id, mandate.workspace_id, "workspace"),
            (assessment.environment_event_id, event.environment_event_id, "event"),
            (
                assessment.event_observation_digest,
                event.observation.content_digest,
                "event observation digest",
            ),
            (assessment.projection_id, projection.projection_id, "projection"),
            (
                assessment.projection_digest,
                projection.projection_artifact.content_digest,
                "projection digest",
            ),
        )
        for actual, expected, label in exact_values:
            if actual != expected:
                raise SituationalTrustDenied(
                    f"trusted assessment {label} does not match ratified input"
                )


class _OperationalProposalCompiler:
    """Compile a bound assessment without writing state or granting authority."""

    _TASK_DISPOSITIONS = {
        RelevanceDisposition.INVESTIGATE,
        RelevanceDisposition.CREATE_TASK,
    }

    def __init__(
        self,
        trust: SituationalTrustResolver | None = None,
        *,
        principal_id: str = "principal:unbound",
    ) -> None:
        self._trust = trust or _DenyAllSituationalTrust()
        self._principal_id = principal_id

    def compile(
        self,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        assessment: RelevanceAssessment,
        *,
        evaluated_at: datetime,
    ) -> TaskDraftProposal | HelpRequest | None:
        evaluated_at = self._utc(evaluated_at)
        self._validate_bindings(event, projection, assessment)
        self._validate_trust(event, projection, assessment)
        self._validate_time(event, projection, assessment, evaluated_at)
        source_binding_digest = situated_source_binding_digest(
            event,
            projection,
            assessment,
        )

        evidence_ids = tuple(
            sorted(
                {
                    *(item.evidence_id for item in event.evidence),
                    *(item.evidence_id for item in projection.evidence),
                    *assessment.evidence_ids,
                }
            )
        )
        if assessment.disposition in self._TASK_DISPOSITIONS:
            assert assessment.proposed_goal_statement is not None
            goal = ProposedGoal(
                proposal_goal_id=f"goal-proposal:{source_binding_digest}",
                source_binding_digest=source_binding_digest,
                tenant_id=assessment.tenant_id,
                workspace_id=assessment.workspace_id,
                created_by="situated-proposal-compiler:v1",
                created_at=assessment.assessed_at,
                statement=assessment.proposed_goal_statement,
                constraints=(
                    "proposal-only:no-automatic-task-activation",
                    "proposal-only:no-external-effect-authority",
                    f"mandate-ref:{assessment.mandate_id}",
                    f"event-ref:{event.environment_event_id}",
                    f"projection-ref:{projection.projection_id}",
                ),
            )
            return TaskDraftProposal(
                task_draft_id=f"task-draft:{source_binding_digest}",
                source_binding_digest=source_binding_digest,
                mandate_id=assessment.mandate_id,
                mandate_version=assessment.mandate_version,
                mandate_digest=assessment.mandate_digest,
                environment_binding_id=assessment.environment_binding_id,
                environment_binding_version=assessment.environment_binding_version,
                environment_binding_digest=assessment.environment_binding_digest,
                correction_epoch=assessment.correction_epoch,
                assessor=assessment.assessor,
                tenant_id=assessment.tenant_id,
                workspace_id=assessment.workspace_id,
                triggering_event_id=event.environment_event_id,
                event_observation_digest=event.observation.content_digest,
                projection_id=projection.projection_id,
                projection_digest=projection.projection_artifact.content_digest,
                relevance_assessment_id=assessment.assessment_id,
                goal=goal,
                evidence_ids=evidence_ids,
                created_at=assessment.assessed_at,
            )
        if assessment.disposition is RelevanceDisposition.HELP:
            assert assessment.minimum_external_input is not None
            return HelpRequest(
                help_request_id=f"help:{source_binding_digest}",
                source_binding_digest=source_binding_digest,
                mandate_id=assessment.mandate_id,
                mandate_version=assessment.mandate_version,
                mandate_digest=assessment.mandate_digest,
                environment_binding_id=assessment.environment_binding_id,
                environment_binding_version=assessment.environment_binding_version,
                environment_binding_digest=assessment.environment_binding_digest,
                correction_epoch=assessment.correction_epoch,
                assessor=assessment.assessor,
                tenant_id=assessment.tenant_id,
                workspace_id=assessment.workspace_id,
                triggering_event_id=event.environment_event_id,
                event_observation_digest=event.observation.content_digest,
                projection_id=projection.projection_id,
                projection_digest=projection.projection_artifact.content_digest,
                relevance_assessment_id=assessment.assessment_id,
                known_facts=assessment.known_facts,
                unknown_facts=assessment.unknown_facts,
                acquisition_attempts=assessment.acquisition_attempts,
                bounded_options=assessment.bounded_options,
                minimum_external_input=assessment.minimum_external_input,
                continuable_work=assessment.continuable_work,
                rationale=assessment.rationale,
                evidence_ids=evidence_ids,
                created_at=assessment.assessed_at,
            )
        return None

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_bindings(
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        assessment: RelevanceAssessment,
    ) -> None:
        scopes = {
            (event.tenant_id, event.workspace_id, event.mandate_id),
            (projection.tenant_id, projection.workspace_id, projection.mandate_id),
            (assessment.tenant_id, assessment.workspace_id, assessment.mandate_id),
        }
        if len(scopes) != 1:
            raise SituationalScopeMismatch(
                "event, projection and assessment scope must match exactly"
            )
        if event.environment_binding_id != projection.environment_binding_id:
            raise SituationalScopeMismatch("environment binding mismatch")
        if assessment.environment_binding_id != event.environment_binding_id:
            raise SituationalScopeMismatch("assessment environment binding mismatch")
        if assessment.environment_event_id != event.environment_event_id:
            raise SituationalScopeMismatch("assessment event binding mismatch")
        if assessment.event_observation_digest != event.observation.content_digest:
            raise SituationalScopeMismatch("event observation digest mismatch")
        if assessment.projection_id != projection.projection_id:
            raise SituationalScopeMismatch("assessment projection binding mismatch")
        if event.environment_event_id not in projection.source_event_ids:
            raise SituationalScopeMismatch(
                "projection does not contain the bound source event"
            )
        if (
            assessment.projection_digest
            != projection.projection_artifact.content_digest
        ):
            raise SituationalScopeMismatch("projection digest mismatch")
        required_evidence = {
            *(item.evidence_id for item in event.evidence),
            *(item.evidence_id for item in projection.evidence),
        }
        if not required_evidence.issubset(set(assessment.evidence_ids)):
            raise SituationalScopeMismatch(
                "assessment evidence must bind event and projection evidence"
            )

    def _validate_trust(
        self,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        assessment: RelevanceAssessment,
    ) -> None:
        binding = (
            self._principal_id,
            event.tenant_id,
            event.workspace_id,
            event.mandate_id,
            event.environment_binding_id,
        )
        if not self._trust.binding_is_authorized(binding):
            raise SituationalTrustDenied(
                "mandate/environment binding is not authorized for principal"
            )
        if self._trust.resolve_event(event.environment_event_id) != event:
            raise SituationalTrustDenied("environment event is not trusted")
        if self._trust.resolve_projection(projection.projection_id) != projection:
            raise SituationalTrustDenied("operational projection is not trusted")
        required_evidence = {
            *(item.evidence_id for item in event.evidence),
            *(item.evidence_id for item in projection.evidence),
        }
        if set(assessment.evidence_ids) != required_evidence:
            raise SituationalTrustDenied(
                "assessment evidence set must exactly match typed trusted evidence"
            )
        for artifact in (event.observation, projection.projection_artifact):
            resolved = self._trust.resolve_artifact(artifact.artifact_id)
            if resolved is None or resolved[0] != artifact:
                raise SituationalTrustDenied("artifact reference is not trusted")
            if "situated:read" not in artifact.acl_scopes:
                raise SituationalTrustDenied("artifact lacks situated read scope")
            if hashlib.sha256(resolved[1]).hexdigest() != artifact.content_digest:
                raise SituationalTrustDenied(
                    "artifact bytes do not match trusted digest"
                )
        for item in (*event.evidence, *projection.evidence):
            if self._trust.resolve_evidence(item.evidence_id) != item:
                raise SituationalTrustDenied("evidence reference is not trusted")

    @staticmethod
    def _validate_time(
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        assessment: RelevanceAssessment,
        evaluated_at: datetime,
    ) -> None:
        if projection.recorded_at < event.recorded_at:
            raise SituationalScopeMismatch(
                "projection cannot precede its bound source event"
            )
        if assessment.assessed_at < projection.recorded_at:
            raise SituationalScopeMismatch(
                "assessment cannot precede its bound projection"
            )
        if evaluated_at < assessment.assessed_at:
            raise SituationalScopeMismatch("evaluation cannot precede assessment")
        if evaluated_at < projection.valid_from:
            raise StaleOperationalProjection("projection is not yet valid")
        if evaluated_at > projection.fresh_until:
            raise StaleOperationalProjection("projection freshness window expired")
