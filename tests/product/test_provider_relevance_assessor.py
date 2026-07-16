from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EvidenceRef,
    EvidenceSourceKind,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    OperationalProjectionRef,
    ProjectionEpistemicStatus,
    ProviderDecisionRequest,
    ProviderErrorCode,
    ProviderFailure,
    ProviderProfile,
    ProviderRelevancePolicy,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    RatifiedMandateRef,
    RelevanceDisposition,
    RelevanceUrgency,
    TaskDraftProposal,
)
from agent_os_core import (
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    InMemorySituationalTrustRegistry,
    OperationalProposalService,
    ProviderPort,
    ProviderRelevanceAssessor,
    SQLiteSituatedAssessmentStore,
    SituationalTrustDenied,
    situated_input_binding_digest,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
OBSERVATION_BYTES = b'{"kind":"external-report","change":"quality gate failed"}'
PROJECTION_BYTES = b'{"state":"commitment at risk","confidence":0.72}'
OBSERVATION_DIGEST = hashlib.sha256(OBSERVATION_BYTES).hexdigest()
PROJECTION_DIGEST = hashlib.sha256(PROJECTION_BYTES).hexdigest()


def _artifact(artifact_id: str, digest: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        content_digest=digest,
        media_type="application/json",
        location_class=ArtifactLocationClass.OBJECT_STORE,
        location_ref=f"object://{artifact_id}",
        acl_scopes=("situated:read",),
        retention_policy="retain-30-days",
        created_by="trusted-redaction-adapter:v1",
        created_at=NOW - timedelta(minutes=4),
    )


def _evidence(evidence_id: str, artifact_id: str) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        source_kind=EvidenceSourceKind.ARTIFACT,
        source_ref=artifact_id,
        relation="supports",
        artifact_ids=(artifact_id,),
        created_by="trusted-redaction-adapter:v1",
        created_at=NOW - timedelta(minutes=3),
    )


def _binding() -> EnvironmentBindingAuthorization:
    return EnvironmentBindingAuthorization(
        environment_binding_id="binding:data-agent",
        version=1,
        binding_digest="b" * 64,
    )


def _profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="provider-profile:relevance-v1",
        provider_id="openai-compatible",
        model_id="model-relevance-v1",
        endpoint_class="openai-compatible",
        credential_ref_id="credential:relevance",
        capabilities=("chat",),
        max_context_tokens=16_000,
        request_timeout_seconds=30,
        created_at=NOW - timedelta(days=1),
    )


def _policy(*, version: int = 1) -> ProviderRelevancePolicy:
    return ProviderRelevancePolicy(
        assessor_id="assessor:provider-relevance",
        version=version,
        provider_profile_id=_profile().profile_id,
        prompt_revision="situated-relevance-prompt-v1",
        output_schema_ref="agent-os://relevance-assessment-draft/v1",
        request_timeout_seconds=20,
        max_artifact_bytes=16_384,
        failure_attention_budget_seconds=60,
    )


def _context() -> MandateRelevanceContext:
    return MandateRelevanceContext(
        relevance_context_id="mandate-context:agent-os-v1",
        version=1,
        mandate_id="mandate:agent-os",
        mandate_version=1,
        mandate_digest="a" * 64,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mission_statement="Keep Agent OS product outcomes truthful and recoverable.",
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:truthful-product",
                statement="Users never receive a false VERIFIED result.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:quality",
                statement="Restore the quality gate without bypassing correction authority.",
                due_at=NOW + timedelta(hours=2),
            ),
        ),
        permanent_constraints=(
            "No task activation from relevance assessment.",
            "No external effect authority.",
            "C7 correction always wins.",
        ),
    )


def _mandate(
    *,
    policy: ProviderRelevancePolicy | None = None,
    with_context: bool = True,
) -> RatifiedMandateRef:
    selected = policy or _policy()
    return RatifiedMandateRef(
        mandate_id="mandate:agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:founder-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="user:local",
        ratified_by="user:local",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=30),
        correction_epoch=0,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(_binding(),),
        relevance_assessor=selected.assessor_ref(),
        relevance_context=_context().ref() if with_context else None,
    )


def _event() -> EnvironmentEvent:
    artifact = _artifact("artifact:observation", OBSERVATION_DIGEST)
    return EnvironmentEvent(
        environment_event_id="event:report-1",
        environment_binding_id="binding:data-agent",
        mandate_id="mandate:agent-os",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        event_type_ref="data-agent:external-report.v1",
        dedupe_key="report:trace-1:revision-1",
        observation=artifact,
        evidence=(_evidence("evidence:event", artifact.artifact_id),),
        occurred_at=NOW - timedelta(minutes=4),
        recorded_at=NOW - timedelta(minutes=3),
    )


def _projection() -> OperationalProjectionRef:
    artifact = _artifact("artifact:projection", PROJECTION_DIGEST)
    return OperationalProjectionRef(
        projection_id="projection:report-1",
        environment_binding_id="binding:data-agent",
        mandate_id="mandate:agent-os",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        source_event_ids=("event:report-1",),
        projection_artifact=artifact,
        schema_uri="agent-os://projection/report/v1",
        version=1,
        scope_ref="repository:agent-os",
        valid_from=NOW - timedelta(minutes=3),
        recorded_at=NOW - timedelta(minutes=2),
        fresh_until=NOW + timedelta(hours=1),
        evidence=(_evidence("evidence:projection", artifact.artifact_id),),
        epistemic_status=ProjectionEpistemicStatus.EVIDENCED,
        uncertainty_summary="The exact affected component is not yet confirmed.",
        compatibility_digest="d" * 64,
    )


def _trust() -> InMemorySituationalTrustRegistry:
    event = _event()
    projection = _projection()
    return InMemorySituationalTrustRegistry(
        bindings=(
            (
                "user:local",
                "tenant:local",
                "workspace:local",
                "mandate:agent-os",
                "binding:data-agent",
            ),
        ),
        artifacts=(
            (event.observation, OBSERVATION_BYTES),
            (projection.projection_artifact, PROJECTION_BYTES),
        ),
        evidence=(*event.evidence, *projection.evidence),
        events=(event,),
        projections=(projection,),
    )


def _draft(disposition: RelevanceDisposition) -> str:
    payload: dict[str, object] = {
        "affected_commitment_ids": ["commitment:quality"],
        "disposition": disposition.value,
        "uncertainty_summary": "The report is grounded but impact needs bounded review.",
        "urgency": RelevanceUrgency.HIGH.value,
        "expected_loss_of_delay": "The quality commitment may miss its deadline.",
        "attention_budget_seconds": 600,
        "rationale": "The trusted report conflicts with the active quality commitment.",
        "known_facts": ["A trusted external report records a failed quality gate."],
        "unknown_facts": ["Which component caused the failure."],
        "acquisition_attempts": ["Read the trusted operational projection."],
        "bounded_options": [
            "Prepare a read-only task draft",
            "Request operator judgment",
        ],
        "continuable_work": ["Inspect evidence without external effects."],
    }
    if disposition is RelevanceDisposition.CREATE_TASK:
        payload["proposed_goal_statement"] = (
            "Investigate the failed quality gate without activating a task."
        )
    if disposition is RelevanceDisposition.HELP:
        payload["minimum_external_input"] = (
            "Choose whether the quality deadline or compatibility constraint dominates."
        )
    return json.dumps(payload)


def _assessor(
    provider: ProviderPort,
    *,
    policy: ProviderRelevancePolicy | None = None,
    contexts: InMemoryMandateRelevanceContextRegistry | None = None,
) -> ProviderRelevanceAssessor:
    return ProviderRelevanceAssessor(
        provider=provider,
        provider_profile=_profile(),
        policy=policy or _policy(),
        trust=_trust(),
        contexts=contexts or InMemoryMandateRelevanceContextRegistry((_context(),)),
    )


def _assess(
    assessor: ProviderRelevanceAssessor, mandate: RatifiedMandateRef | None = None
):
    selected = mandate or _mandate()
    return assessor.assess(
        selected,
        _binding(),
        _event(),
        _projection(),
        assessed_at=NOW,
    )


class _FailureProvider(ProviderPort):
    def __init__(self, code: ProviderErrorCode) -> None:
        self.code = code
        self.decision_calls = 0

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        raise AssertionError("situated relevance must not use task/run completion")

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        self.decision_calls += 1
        return ProviderFailure(
            failure_id="failure:relevance",
            request_id=request.request_id,
            code=self.code,
            retryable=self.code is ProviderErrorCode.TIMEOUT,
            safe_message="provider relevance decision unavailable",
            occurred_at=NOW,
        )


def test_prompt_contains_digest_bound_mission_and_trusted_redacted_bytes() -> None:
    provider = DeterministicProvider(text=_draft(RelevanceDisposition.CREATE_TASK))
    assessor = _assessor(provider)

    assessment = _assess(assessor)

    assert assessment.disposition is RelevanceDisposition.CREATE_TASK
    assert len(provider.decision_requests) == 1
    request = provider.decision_requests[0]
    assert isinstance(request, ProviderDecisionRequest)
    assert not hasattr(request, "task_id")
    assert not hasattr(request, "run_id")
    assert request.decision_kind == "SITUATED_RELEVANCE"
    assert request.provider_profile_id == _profile().profile_id
    prompt = json.loads(request.messages[-1].content)
    assert (
        prompt["mandate_context"]["mission_statement"] == _context().mission_statement
    )
    assert prompt["mandate_context"]["open_commitments"][0]["commitment_id"] == (
        "commitment:quality"
    )
    assert prompt["event"]["observation"]["change"] == "quality gate failed"
    assert prompt["projection"]["content"]["state"] == "commitment at risk"
    assert prompt["authority_boundary"] == {
        "assessment_is_proposal_only": True,
        "external_effects_authorized": False,
        "task_activation_authorized": False,
    }


@pytest.mark.parametrize(
    ("disposition", "goal", "minimum_input"),
    (
        (RelevanceDisposition.CREATE_TASK, True, False),
        (RelevanceDisposition.HELP, False, True),
        (RelevanceDisposition.ABSTAIN, False, False),
    ),
)
def test_strict_provider_draft_supports_create_task_help_and_abstain(
    disposition: RelevanceDisposition,
    goal: bool,
    minimum_input: bool,
) -> None:
    provider = DeterministicProvider(text=_draft(disposition))

    assessment = _assess(_assessor(provider))

    assert assessment.disposition is disposition
    assert (assessment.proposed_goal_statement is not None) is goal
    assert (assessment.minimum_external_input is not None) is minimum_input
    expected_digest = situated_input_binding_digest(
        _mandate(), _binding(), _event(), _projection(), _policy().assessor_ref()
    )
    assert assessment.assessment_id == f"relevance-assessment:{expected_digest}"
    assert assessment.input_binding_digest == expected_digest
    assert assessment.assessor == _policy().assessor_ref()
    assert assessment.assessed_at == NOW


@pytest.mark.parametrize(
    "provider_text",
    (
        "not-json",
        json.dumps(
            {
                **json.loads(_draft(RelevanceDisposition.CREATE_TASK)),
                "assessment_id": "provider-forged-id",
                "correction_epoch": 999,
                "assessor": {
                    "assessor_id": "forged",
                    "version": 1,
                    "policy_digest": "f" * 64,
                },
            }
        ),
    ),
)
def test_malformed_or_authority_shaped_output_fails_closed_to_abstain(
    provider_text: str,
) -> None:
    assessment = _assess(_assessor(DeterministicProvider(text=provider_text)))

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert assessment.proposed_goal_statement is None
    assert assessment.minimum_external_input is None
    assert assessment.assessment_id.startswith("relevance-assessment:")
    assert "malformed" in assessment.uncertainty_summary.lower()


@pytest.mark.parametrize(
    "code",
    (ProviderErrorCode.TIMEOUT, ProviderErrorCode.UNAVAILABLE),
)
def test_provider_failure_fails_closed_to_auditable_abstain(
    code: ProviderErrorCode,
) -> None:
    provider = _FailureProvider(code)

    assessment = _assess(_assessor(provider))

    assert provider.decision_calls == 1
    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert code.value in assessment.uncertainty_summary
    assert assessment.evidence_ids == ("evidence:event", "evidence:projection")


def test_missing_ratified_mandate_context_abstains_without_provider_call() -> None:
    provider = DeterministicProvider(text=_draft(RelevanceDisposition.CREATE_TASK))
    assessor = _assessor(provider)

    assessment = _assess(assessor, _mandate(with_context=False))

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert provider.decision_requests == []
    assert "mandate relevance context" in assessment.uncertainty_summary.lower()


def test_wrong_ratified_assessor_version_is_rejected_before_provider_call(
    tmp_path,
) -> None:
    provider = DeterministicProvider(text=_draft(RelevanceDisposition.CREATE_TASK))
    assessor = _assessor(provider, policy=_policy(version=2))
    service = OperationalProposalService(
        trust=_trust(),
        control=SQLiteSituatedAssessmentStore(
            tmp_path / "wrong-assessor.sqlite3", mandates=(_mandate(),)
        ),
        assessor=assessor,
        principal_id="user:local",
    )

    with pytest.raises(SituationalTrustDenied, match="assessor"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert provider.decision_requests == []


def test_durable_exact_replay_reuses_input_bound_outcome_without_provider_call(
    tmp_path,
) -> None:
    provider = DeterministicProvider(text=_draft(RelevanceDisposition.CREATE_TASK))
    assessor = _assessor(provider)
    database = tmp_path / "provider-replay.sqlite3"
    first_store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    first_service = OperationalProposalService(
        trust=_trust(),
        control=first_store,
        assessor=assessor,
        principal_id="user:local",
    )

    first = first_service.propose(
        "event:report-1", "projection:report-1", evaluated_at=NOW
    )
    provider.text = _draft(RelevanceDisposition.HELP)
    restarted_service = OperationalProposalService(
        trust=_trust(),
        control=SQLiteSituatedAssessmentStore(database),
        assessor=assessor,
        principal_id="user:local",
    )
    replay = restarted_service.propose(
        "event:report-1", "projection:report-1", evaluated_at=NOW
    )

    assert isinstance(first, TaskDraftProposal)
    assert replay == first
    assert len(provider.decision_requests) == 1
    input_digest = situated_input_binding_digest(
        _mandate(), _binding(), _event(), _projection(), _policy().assessor_ref()
    )
    record = first_store.record_by_input_binding(input_digest)
    assert record is not None
    assert record.assessment.assessment_id == f"relevance-assessment:{input_digest}"


def test_application_composes_provider_assessor_on_real_product_entry(tmp_path) -> None:
    provider = DeterministicProvider(text=_draft(RelevanceDisposition.CREATE_TASK))
    database = tmp_path / "agent-os.sqlite3"
    app = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        situational_trust=_trust(),
        situational_control=SQLiteSituatedAssessmentStore(
            tmp_path / "situated.sqlite3", mandates=(_mandate(),)
        ),
        provider_relevance_policy=_policy(),
        mandate_relevance_contexts=InMemoryMandateRelevanceContextRegistry(
            (_context(),)
        ),
        relevance_provider=provider,
        relevance_provider_profile=_profile(),
        clock=lambda: NOW,
    )

    result = app.propose_situated_work("event:report-1", "projection:report-1")

    assert isinstance(result, TaskDraftProposal)
    assert result.activation_authorized is False
    assert result.external_effects_authorized is False
    assert app.store.list_task_ids() == ()
    assert len(provider.decision_requests) == 1


def test_provider_response_metadata_never_changes_assessment_identity() -> None:
    class MetadataProvider(ProviderPort):
        def __init__(self) -> None:
            self.sequence = 0

        def complete(
            self, request: ProviderRequest
        ) -> ProviderResponse | ProviderFailure:
            raise AssertionError("situated relevance must not use task/run completion")

        def decide(
            self, request: ProviderDecisionRequest
        ) -> ProviderResponse | ProviderFailure:
            self.sequence += 1
            return ProviderResponse(
                response_id=f"response:{self.sequence}",
                request_id=request.request_id,
                text=_draft(RelevanceDisposition.ABSTAIN),
                tool_proposals=(),
                usage=ProviderUsage(
                    input_tokens=1,
                    output_tokens=1,
                    total_tokens=2,
                    estimated_cost_usd=Decimal("0"),
                ),
                finish_reason="stop",
                received_at=NOW + timedelta(seconds=self.sequence),
            )

    provider = MetadataProvider()
    assessor = _assessor(provider)

    first = _assess(assessor)
    second = _assess(assessor)

    assert first.assessment_id == second.assessment_id
    assert first.input_binding_digest == second.input_binding_digest
    assert first.assessed_at == second.assessed_at == NOW
