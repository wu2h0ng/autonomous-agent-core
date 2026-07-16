from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.request import Request

import pytest

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    CredentialRef,
    CredentialStatus,
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
    ProviderInvocationBinding,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRelevancePolicy,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    RatifiedMandateRef,
    RelevanceDisposition,
    RelevanceUrgency,
    TaskDraftProposal,
    content_digest,
)
from agent_os_core import (
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    InMemorySituationalTrustRegistry,
    OperationalProposalService,
    OpenAICompatibleProvider,
    ProviderPort,
    ProviderRelevanceAssessor,
    RELEVANCE_OUTPUT_SCHEMA_DIGEST,
    RELEVANCE_PROMPT_MANIFEST,
    RELEVANCE_PROMPT_TEMPLATE_DIGEST,
    SituationalTrustDenied,
    StaleOperationalProjection,
    situated_input_binding_digest,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
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


def _credential(**updates: object) -> CredentialRef:
    credential = CredentialRef(
        credential_ref_id="credential:relevance",
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="openai-compatible",
        resolver_key="RELEVANCE_API_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )
    return credential.model_copy(update=updates)


def _invocation(
    *,
    profile: ProviderProfile | None = None,
    **updates: object,
) -> ProviderInvocationBinding:
    selected_profile = profile or _profile()
    binding = ProviderInvocationBinding(
        provider_profile=selected_profile,
        provider_id=selected_profile.provider_id,
        endpoint_class=selected_profile.endpoint_class,
        credential_ref_id=selected_profile.credential_ref_id,
        credential_ref_digest=content_digest(_credential()),
        max_context_tokens=selected_profile.max_context_tokens,
        adapter_kind="deterministic-test",
        transport="in-process",
        base_url="in-process://deterministic",
        endpoint_path="decide",
        model_id=selected_profile.model_id,
        request_timeout_seconds=20,
        temperature=Decimal("0"),
    )
    return binding.model_copy(update=updates)


def _policy(
    *,
    version: int = 1,
    invocation: ProviderInvocationBinding | None = None,
    prompt_digest: str = RELEVANCE_PROMPT_TEMPLATE_DIGEST,
    schema_digest: str = RELEVANCE_OUTPUT_SCHEMA_DIGEST,
) -> ProviderRelevancePolicy:
    return ProviderRelevancePolicy(
        assessor_id="assessor:provider-relevance",
        version=version,
        provider_invocation=invocation or _invocation(),
        prompt_revision="situated-relevance-prompt-v1",
        prompt_template_digest=prompt_digest,
        output_schema_ref="agent-os://relevance-assessment-draft/v1",
        output_schema_digest=schema_digest,
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


def _trust(
    *,
    observation_bytes: bytes = OBSERVATION_BYTES,
    projection_bytes: bytes = PROJECTION_BYTES,
) -> InMemorySituationalTrustRegistry:
    event = _event().model_copy(
        update={
            "observation": _artifact(
                "artifact:observation", hashlib.sha256(observation_bytes).hexdigest()
            )
        }
    )
    projection = _projection()
    projection = projection.model_copy(
        update={
            "projection_artifact": _artifact(
                "artifact:projection", hashlib.sha256(projection_bytes).hexdigest()
            )
        }
    )
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
            (event.observation, observation_bytes),
            (projection.projection_artifact, projection_bytes),
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

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        return _invocation()

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
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK),
        invocation_binding=_invocation(),
    )
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
    assert request.expected_invocation_binding_digest == _invocation().digest()
    prompt = json.loads(request.messages[-1].content)
    assert RELEVANCE_PROMPT_TEMPLATE_DIGEST == content_digest(RELEVANCE_PROMPT_MANIFEST)
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
    provider = DeterministicProvider(
        text=_draft(disposition), invocation_binding=_invocation()
    )

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
    assert (
        assessment.expected_provider_invocation_binding_digest == _invocation().digest()
    )
    assert assessment.provider_invocation_receipt_digest == _invocation().digest()
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
    assessment = _assess(
        _assessor(
            DeterministicProvider(text=provider_text, invocation_binding=_invocation())
        )
    )

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
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    assessor = _assessor(provider)

    assessment = _assess(assessor, _mandate(with_context=False))

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert provider.decision_requests == []
    assert "mandate relevance context" in assessment.uncertainty_summary.lower()


def test_wrong_ratified_assessor_version_is_rejected_before_provider_call(
    tmp_path,
) -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
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
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
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
    assert (
        record.assessment.expected_provider_invocation_binding_digest
        == _invocation().digest()
    )
    assert (
        record.assessment.provider_invocation_receipt_digest == _invocation().digest()
    )


def test_sqlite_restart_decodes_and_replays_legacy_v1_assessment_record(
    tmp_path,
) -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    source_database = tmp_path / "provider-v1-source.sqlite3"
    source_store = SQLiteSituatedAssessmentStore(
        source_database, mandates=(_mandate(),)
    )
    source_service = OperationalProposalService(
        trust=_trust(),
        control=source_store,
        assessor=_assessor(provider),
        principal_id="user:local",
    )
    source_service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)
    input_digest = situated_input_binding_digest(
        _mandate(), _binding(), _event(), _projection(), _policy().assessor_ref()
    )
    current_record = source_store.record_by_input_binding(input_digest)
    assert current_record is not None

    legacy_invocation_digest = _invocation().digest()
    legacy_payload = current_record.model_dump(mode="json")
    legacy_assessment = legacy_payload["assessment"]
    assert isinstance(legacy_assessment, dict)
    legacy_assessment["schema_version"] = "1.0"
    legacy_assessment["provider_invocation_binding_digest"] = legacy_invocation_digest
    legacy_assessment.pop("expected_provider_invocation_binding_digest")
    legacy_assessment.pop("provider_call_attempted")
    legacy_assessment.pop("provider_invocation_receipt_digest")

    database = tmp_path / "provider-v1-restart.sqlite3"
    SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
                INSERT INTO situated_assessment_records (
                    assessment_id, assessment_record_id, source_binding_digest,
                    input_binding_digest, principal_id, tenant_id, workspace_id,
                    record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_record.assessment.assessment_id,
                    current_record.assessment_record_id,
                    current_record.source_binding_digest,
                    current_record.assessment.input_binding_digest,
                    _mandate().owner_principal_id,
                    current_record.tenant_id,
                current_record.workspace_id,
                json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    restarted = SQLiteSituatedAssessmentStore(database)
    decoded = restarted.assessment_record(current_record.assessment.assessment_id)
    replayed = restarted.replay_if_active(
        _mandate(),
        _binding(),
        input_digest,
        principal_id="user:local",
        evaluated_at=NOW,
    )

    assert decoded is not None
    assert replayed == decoded
    assert decoded.assessment.schema_version == "1.0"
    assert (
        decoded.assessment.provider_invocation_binding_digest
        == legacy_invocation_digest
    )
    assert decoded.assessment.expected_provider_invocation_binding_digest is None
    assert decoded.assessment.provider_call_attempted is False
    assert decoded.assessment.provider_invocation_receipt_digest is None


def test_application_composes_provider_assessor_on_real_product_entry(tmp_path) -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    database = tmp_path / "agent-os.sqlite3"
    app = AgentOSApplication._with_situated_control(
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

        @property
        def invocation_binding(self) -> ProviderInvocationBinding:
            return _invocation()

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
                invocation_binding_digest=self.invocation_binding.digest(),
            )

    provider = MetadataProvider()
    assessor = _assessor(provider)

    first = _assess(assessor)
    second = _assess(assessor)

    assert first.assessment_id == second.assessment_id
    assert first.input_binding_digest == second.input_binding_digest
    assert first.assessed_at == second.assessed_at == NOW


class _RaisingProvider(ProviderPort):
    def __init__(self, invocation: ProviderInvocationBinding | None = None) -> None:
        self._invocation = invocation or _invocation()
        self.decision_calls = 0

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        return self._invocation

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        raise AssertionError("situated relevance must not use task/run completion")

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        self.decision_calls += 1
        raise RuntimeError("provider adapter exploded")


def test_provider_exception_fails_closed_to_abstain() -> None:
    provider = _RaisingProvider()

    assessment = _assess(_assessor(provider))

    assert provider.decision_calls == 1
    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert "UNAVAILABLE" in assessment.uncertainty_summary


@pytest.mark.parametrize(
    "provider_text",
    (
        _draft(RelevanceDisposition.ABSTAIN).replace(
            "{", '{"disposition":"CREATE_TASK",', 1
        ),
        _draft(RelevanceDisposition.ABSTAIN).replace(
            '"attention_budget_seconds": 600', '"attention_budget_seconds": NaN'
        ),
        _draft(RelevanceDisposition.ABSTAIN).replace(
            '"attention_budget_seconds": 600', '"attention_budget_seconds": Infinity'
        ),
    ),
)
def test_provider_output_rejects_duplicate_keys_and_non_finite_numbers(
    provider_text: str,
) -> None:
    provider = DeterministicProvider(
        text=provider_text, invocation_binding=_invocation()
    )

    assessment = _assess(_assessor(provider))

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert "malformed" in assessment.uncertainty_summary.lower()


@pytest.mark.parametrize(
    "observation_bytes",
    (
        b'{"change":"first","change":"second"}',
        b'{"confidence":NaN}',
        b'{"confidence":Infinity}',
    ),
)
def test_trusted_artifact_rejects_duplicate_keys_and_non_finite_numbers(
    observation_bytes: bytes,
) -> None:
    event = _event().model_copy(
        update={
            "observation": _artifact(
                "artifact:observation", hashlib.sha256(observation_bytes).hexdigest()
            )
        }
    )
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK),
        invocation_binding=_invocation(),
    )
    assessor = ProviderRelevanceAssessor(
        provider=provider,
        provider_profile=_profile(),
        policy=_policy(),
        trust=_trust(observation_bytes=observation_bytes),
        contexts=InMemoryMandateRelevanceContextRegistry((_context(),)),
    )

    assessment = assessor.assess(
        _mandate(), _binding(), event, _projection(), assessed_at=NOW
    )

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert provider.decision_requests == []
    assert "malformed" in assessment.uncertainty_summary.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", "other-provider"),
        ("model_id", "other-model"),
        ("endpoint_class", "other-endpoint"),
        ("credential_ref_id", "credential:other"),
        ("max_context_tokens", 8_000),
        ("request_timeout_seconds", 31),
    ),
)
def test_full_provider_profile_drift_rejected_before_provider_call(
    field: str, value: object
) -> None:
    drifted_profile = _profile().model_copy(update={field: value})
    provider = _RaisingProvider(_invocation(profile=drifted_profile))

    with pytest.raises(ValueError, match="provider"):
        ProviderRelevanceAssessor(
            provider=provider,
            provider_profile=drifted_profile,
            policy=_policy(),
            trust=_trust(),
            contexts=InMemoryMandateRelevanceContextRegistry((_context(),)),
        )

    assert provider.decision_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("temperature", Decimal("0.5")),
        ("base_url", "https://different.example/v1"),
        ("endpoint_path", "/different/completions"),
        ("request_timeout_seconds", 19),
        ("model_id", "different-runtime-model"),
    ),
)
def test_actual_provider_invocation_drift_rejected_before_provider_call(
    field: str, value: object
) -> None:
    provider = _RaisingProvider(_invocation().model_copy(update={field: value}))

    with pytest.raises(ValueError, match="invocation"):
        _assessor(provider)

    assert provider.decision_calls == 0


@pytest.mark.parametrize(
    "updates",
    (
        {"model_id": "different-model"},
        {"provider_id": "different-provider"},
        {"endpoint_class": "different-endpoint"},
        {"credential_ref_id": "credential:different"},
        {"max_context_tokens": 1},
    ),
)
def test_invocation_binding_rejects_internal_profile_inconsistency(
    updates: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "provider_profile": _profile(),
        "provider_id": _profile().provider_id,
        "endpoint_class": _profile().endpoint_class,
        "credential_ref_id": _profile().credential_ref_id,
        "credential_ref_digest": content_digest(_credential()),
        "max_context_tokens": _profile().max_context_tokens,
        "adapter_kind": "deterministic-test",
        "transport": "in-process",
        "base_url": "in-process://deterministic",
        "endpoint_path": "decide",
        "model_id": _profile().model_id,
        "request_timeout_seconds": 20,
        "temperature": Decimal("0"),
    }
    values.update(updates)
    with pytest.raises(ValueError):
        ProviderInvocationBinding.model_validate(values)


@pytest.mark.parametrize(
    "credential",
    (
        _credential(tenant_id="tenant:other"),
        _credential(scopes=("other",)),
        _credential(status=CredentialStatus.REVOKED),
        _credential(expires_at=NOW + timedelta(days=1)),
    ),
)
def test_same_credential_id_content_drift_rejected_before_provider_call(
    credential: CredentialRef,
) -> None:
    drifted = _invocation().model_copy(
        update={"credential_ref_digest": content_digest(credential)}
    )
    provider = _RaisingProvider(drifted)

    with pytest.raises(ValueError, match="invocation"):
        _assessor(provider)

    assert provider.decision_calls == 0


def test_application_rejects_same_profile_id_with_drifted_model_before_call(
    tmp_path,
) -> None:
    drifted_profile = _profile().model_copy(update={"model_id": "drifted-model"})
    provider = _RaisingProvider(_invocation(profile=drifted_profile))

    with pytest.raises(ValueError, match="provider"):
        AgentOSApplication._with_situated_control(
            database=tmp_path / "app-provider-drift.sqlite3",
            workspace=tmp_path,
            situational_trust=_trust(),
            situational_control=SQLiteSituatedAssessmentStore(
                tmp_path / "situated-provider-drift.sqlite3", mandates=(_mandate(),)
            ),
            provider_relevance_policy=_policy(),
            mandate_relevance_contexts=InMemoryMandateRelevanceContextRegistry(
                (_context(),)
            ),
            relevance_provider=provider,
            relevance_provider_profile=drifted_profile,
            clock=lambda: NOW,
        )

    assert provider.decision_calls == 0


def test_openai_provider_exposes_actual_credential_bound_invocation() -> None:
    credential = _credential()
    provider = OpenAICompatibleProvider(
        base_url="https://provider.example/v1/",
        model=_profile().model_id,
        credential=credential,
        timeout_seconds=20,
        temperature=0.25,
        provider_profile=_profile(),
    )

    binding = provider.invocation_binding

    assert binding.base_url == "https://provider.example/v1"
    assert binding.endpoint_path == "/chat/completions"
    assert binding.model_id == _profile().model_id
    assert binding.temperature == Decimal("0.25")
    assert binding.credential_ref_digest == content_digest(credential)


@pytest.mark.parametrize(
    "credential",
    (
        _credential(status=CredentialStatus.REVOKED),
        _credential(scopes=("other",)),
        _credential(
            created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2001, 1, 1, tzinfo=timezone.utc),
        ),
    ),
)
def test_openai_provider_rejects_unusable_credential_at_composition(
    credential: CredentialRef,
) -> None:
    with pytest.raises(ValueError, match="credential"):
        OpenAICompatibleProvider(
            base_url="https://provider.example/v1",
            model=_profile().model_id,
            credential=credential,
            timeout_seconds=20,
            temperature=0,
            provider_profile=_profile(),
        )


@pytest.mark.parametrize(
    ("prompt_digest", "schema_digest"),
    (
        ("f" * 64, RELEVANCE_OUTPUT_SCHEMA_DIGEST),
        (RELEVANCE_PROMPT_TEMPLATE_DIGEST, "f" * 64),
    ),
)
def test_prompt_and_schema_content_drift_rejected_before_provider_call(
    prompt_digest: str, schema_digest: str
) -> None:
    provider = _RaisingProvider()

    with pytest.raises(ValueError, match="prompt|schema"):
        _assessor(
            provider,
            policy=_policy(
                prompt_digest=prompt_digest,
                schema_digest=schema_digest,
            ),
        )

    assert provider.decision_calls == 0


def test_runtime_recomputes_prompt_manifest_digest_on_construction(
    monkeypatch,
) -> None:
    provider = _RaisingProvider()
    user_template = RELEVANCE_PROMPT_MANIFEST["user"]
    assert isinstance(user_template, dict)
    monkeypatch.setitem(user_template, "unratified_static_field", True)

    with pytest.raises(ValueError, match="prompt"):
        _assessor(provider)

    assert provider.decision_calls == 0


def test_replay_revalidates_projection_freshness_without_provider_call(
    tmp_path,
) -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    database = tmp_path / "stale-replay.sqlite3"
    service = OperationalProposalService(
        trust=_trust(),
        control=SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),)),
        assessor=_assessor(provider),
        principal_id="user:local",
    )
    assert isinstance(
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW),
        TaskDraftProposal,
    )

    with pytest.raises(StaleOperationalProjection):
        service.propose(
            "event:report-1",
            "projection:report-1",
            evaluated_at=NOW + timedelta(hours=2),
        )

    assert len(provider.decision_requests) == 1


def test_revocation_wins_over_blocked_replay_across_sqlite_instances(tmp_path) -> None:
    class BlockingReplayStore(SQLiteSituatedAssessmentStore):
        def __init__(
            self, database, *, started: threading.Event, release: threading.Event
        ):
            self.started = started
            self.release = release
            super().__init__(database)

        def replay_if_active(self, *args, **kwargs):
            self.started.set()
            assert self.release.wait(timeout=5)
            return super().replay_if_active(*args, **kwargs)

    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    assessor = _assessor(provider)
    database = tmp_path / "atomic-replay.sqlite3"
    first_store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    first_service = OperationalProposalService(
        trust=_trust(),
        control=first_store,
        assessor=assessor,
        principal_id="user:local",
    )
    assert isinstance(
        first_service.propose(
            "event:report-1", "projection:report-1", evaluated_at=NOW
        ),
        TaskDraftProposal,
    )
    started = threading.Event()
    release = threading.Event()
    replay_service = OperationalProposalService(
        trust=_trust(),
        control=BlockingReplayStore(database, started=started, release=release),
        assessor=assessor,
        principal_id="user:local",
    )
    outcome: list[object] = []

    def replay() -> None:
        try:
            outcome.append(
                replay_service.propose(
                    "event:report-1", "projection:report-1", evaluated_at=NOW
                )
            )
        except Exception as exc:
            outcome.append(exc)

    thread = threading.Thread(target=replay)
    thread.start()
    assert started.wait(timeout=5)
    SQLiteSituatedAssessmentStore(database).revoke("mandate:agent-os", expected_epoch=0)
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], SituationalTrustDenied)
    assert len(provider.decision_requests) == 1


def test_openai_wire_uses_only_frozen_approved_invocation_state(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": "response:frozen-wire",
                    "choices": [
                        {
                            "message": {
                                "content": _draft(RelevanceDisposition.ABSTAIN)
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode()

    captured: list[tuple[Request, int]] = []

    def opener(request: Request, *, timeout: int):
        captured.append((request, timeout))
        return Response()

    monkeypatch.setenv("RELEVANCE_API_KEY", "approved-secret")
    provider = OpenAICompatibleProvider(
        base_url="https://approved.example/v1",
        model=_profile().model_id,
        credential=_credential(),
        timeout_seconds=20,
        temperature=0.25,
        provider_profile=_profile(),
        opener=opener,
    )
    for attribute, drifted in (
        ("model", "drifted-model"),
        ("base_url", "https://drifted.example/v1"),
        ("temperature", 0.9),
        ("timeout_seconds", 1),
        ("credential", _credential(resolver_key="DRIFTED_API_KEY")),
    ):
        with pytest.raises(AttributeError):
            setattr(provider, attribute, drifted)

    response = provider.decide(
        ProviderDecisionRequest(
            request_id="request:frozen-wire",
            decision_kind="SITUATED_RELEVANCE",
            provider_profile_id=_profile().profile_id,
            expected_invocation_binding_digest=provider.invocation_binding.digest(),
            messages=(
                ProviderMessage(
                    role=ProviderMessageRole.USER,
                    content="approved prompt",
                ),
            ),
            timeout_seconds=19,
            created_at=NOW,
        )
    )

    assert isinstance(response, ProviderResponse)
    assert len(captured) == 1
    request, timeout = captured[0]
    assert request.full_url == "https://approved.example/v1/chat/completions"
    assert isinstance(request.data, bytes)
    body = json.loads(request.data)
    assert body["model"] == _profile().model_id
    assert body["temperature"] == 0.25
    assert timeout == 19
    assert request.headers["Authorization"] == "Bearer approved-secret"


class _ReceiptProvider(ProviderPort):
    def __init__(self, receipt_digest: str | None) -> None:
        self.receipt_digest = receipt_digest
        self.decision_calls = 0

    @property
    def invocation_binding(self) -> ProviderInvocationBinding:
        return _invocation()

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        raise AssertionError("situated relevance must not use task/run completion")

    def decide(
        self, request: ProviderDecisionRequest
    ) -> ProviderResponse | ProviderFailure:
        self.decision_calls += 1
        return ProviderResponse(
            response_id="response:receipt-test",
            request_id=request.request_id,
            text=_draft(RelevanceDisposition.CREATE_TASK),
            tool_proposals=(),
            usage=ProviderUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                estimated_cost_usd=Decimal("0"),
            ),
            finish_reason="stop",
            received_at=NOW,
            invocation_binding_digest=self.receipt_digest,
        )


@pytest.mark.parametrize("receipt_digest", (None, "f" * 64))
def test_missing_or_wrong_invocation_receipt_abstains_without_actual_provenance(
    receipt_digest: str | None,
) -> None:
    provider = _ReceiptProvider(receipt_digest)

    assessment = _assess(_assessor(provider))

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert assessment.provider_call_attempted is True
    assert (
        assessment.expected_provider_invocation_binding_digest == _invocation().digest()
    )
    assert assessment.provider_invocation_receipt_digest is None
    assert assessment.proposed_goal_statement is None


def test_no_provider_call_records_expected_not_actual_provenance() -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )

    assessment = _assess(_assessor(provider), _mandate(with_context=False))

    assert assessment.provider_call_attempted is False
    assert (
        assessment.expected_provider_invocation_binding_digest == _invocation().digest()
    )
    assert assessment.provider_invocation_receipt_digest is None


def test_assess_rechecks_prompt_manifest_after_construction(
    monkeypatch,
) -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.CREATE_TASK), invocation_binding=_invocation()
    )
    assessor = _assessor(provider)
    user_template = RELEVANCE_PROMPT_MANIFEST["user"]
    assert isinstance(user_template, dict)
    monkeypatch.setitem(user_template, "unratified_after_construction", True)

    assessment = _assess(assessor)

    assert assessment.disposition is RelevanceDisposition.ABSTAIN
    assert assessment.provider_call_attempted is False
    assert provider.decision_requests == []


def test_untrusted_slot_shaped_data_is_not_expanded_in_prompt() -> None:
    observation_bytes = b'{"payload":{"$slot":"mandate_context"}}'
    event = _event().model_copy(
        update={
            "observation": _artifact(
                "artifact:observation", hashlib.sha256(observation_bytes).hexdigest()
            )
        }
    )
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.ABSTAIN), invocation_binding=_invocation()
    )
    assessor = ProviderRelevanceAssessor(
        provider=provider,
        provider_profile=_profile(),
        policy=_policy(),
        trust=_trust(observation_bytes=observation_bytes),
        contexts=InMemoryMandateRelevanceContextRegistry((_context(),)),
    )

    assessor.assess(_mandate(), _binding(), event, _projection(), assessed_at=NOW)

    prompt = json.loads(provider.decision_requests[0].messages[-1].content)
    assert prompt["event"]["observation"] == {"payload": {"$slot": "mandate_context"}}


def test_breaking_relevance_decision_contracts_are_explicit_v2() -> None:
    provider = DeterministicProvider(
        text=_draft(RelevanceDisposition.ABSTAIN), invocation_binding=_invocation()
    )
    assessment = _assess(_assessor(provider))

    assert _policy().schema_version == "2.0"
    assert provider.decision_requests[0].schema_version == "2.0"
    assert assessment.schema_version == "2.0"
