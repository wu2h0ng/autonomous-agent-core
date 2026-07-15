from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable, Protocol, TypeAlias

from agent_os_contracts import (
    ArtifactRef,
    EnvironmentEvent,
    EvidenceRef,
    HelpRequest,
    OperationalProjectionRef,
    ProposedGoal,
    RelevanceAssessment,
    RelevanceDisposition,
    TaskDraftProposal,
    content_digest,
)

from .errors import (
    SituationalScopeMismatch,
    SituationalTrustDenied,
    StaleOperationalProjection,
)


SituationalBinding: TypeAlias = tuple[str, str, str, str, str]


class SituationalTrustResolver(Protocol):
    def binding_is_authorized(self, binding: SituationalBinding) -> bool: ...

    def resolve_artifact(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None: ...

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

    def resolve_projection(
        self, projection_id: str
    ) -> OperationalProjectionRef | None:
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

    def resolve_projection(
        self, projection_id: str
    ) -> OperationalProjectionRef | None:
        resolved = self._projections.get(projection_id)
        return resolved if isinstance(resolved, OperationalProjectionRef) else None


class OperationalProposalCompiler:
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
        source_binding_digest = content_digest(
            {
                "event": event.model_dump(mode="json"),
                "projection": projection.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }
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
                tenant_id=assessment.tenant_id,
                workspace_id=assessment.workspace_id,
                triggering_event_id=event.environment_event_id,
                event_observation_digest=event.observation.content_digest,
                projection_id=projection.projection_id,
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
                raise SituationalTrustDenied("artifact bytes do not match trusted digest")
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
