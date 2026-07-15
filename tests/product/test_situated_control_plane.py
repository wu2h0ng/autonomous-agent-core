from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest
import agent_os_core

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EvidenceRef,
    EvidenceSourceKind,
    HelpRequest,
    OperationalProjectionRef,
    ProjectionEpistemicStatus,
    RatifiedMandateRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    TaskDraftProposal,
)
from agent_os_core import (
    InMemorySituationalControlPlane,
    InMemorySituationalTrustRegistry,
    OperationalProposalService,
    SQLiteSituatedAssessmentStore,
    SituationalPersistenceConflict,
    SituationalTrustDenied,
    situated_input_binding_digest,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
OBSERVATION_BYTES = b'{"kind":"verified-report"}'
PROJECTION_BYTES = b'{"safe_summary":"report changed"}'
OBSERVATION_DIGEST = hashlib.sha256(OBSERVATION_BYTES).hexdigest()
PROJECTION_DIGEST = hashlib.sha256(PROJECTION_BYTES).hexdigest()
MANDATE_DIGEST = "a" * 64
BINDING_DIGEST = "b" * 64
POLICY_DIGEST = "c" * 64


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
        created_by="environment-adapter:test",
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
        created_by="environment-adapter:test",
        created_at=NOW - timedelta(minutes=3),
    )


def _event() -> EnvironmentEvent:
    return EnvironmentEvent(
        environment_event_id="event:report-1",
        environment_binding_id="binding:data-agent",
        mandate_id="mandate:agent-os",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        event_type_ref="data-agent.report-observed.v1",
        dedupe_key="report:trace-1:revision-1",
        observation=_artifact("artifact:observation", OBSERVATION_DIGEST),
        evidence=(_evidence("evidence:event", "artifact:observation"),),
        occurred_at=NOW - timedelta(minutes=4),
        recorded_at=NOW - timedelta(minutes=3),
    )


def _projection() -> OperationalProjectionRef:
    return OperationalProjectionRef(
        projection_id="projection:report-1",
        environment_binding_id="binding:data-agent",
        mandate_id="mandate:agent-os",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        source_event_ids=("event:report-1",),
        projection_artifact=_artifact("artifact:projection", PROJECTION_DIGEST),
        schema_uri="schema://situated/safe-summary/v1",
        version=1,
        scope_ref="mission:agent-os/product",
        valid_from=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=2),
        fresh_until=NOW + timedelta(minutes=10),
        evidence=(_evidence("evidence:projection", "artifact:projection"),),
        epistemic_status=ProjectionEpistemicStatus.EVIDENCED,
        uncertainty_summary="The report is grounded; significance is unknown.",
        compatibility_digest="d" * 64,
    )


def _assessor_ref(*, version: int = 1) -> RelevanceAssessorRef:
    return RelevanceAssessorRef(
        assessor_id="assessor:bounded-v0",
        version=version,
        policy_digest=POLICY_DIGEST,
    )


def _binding() -> EnvironmentBindingAuthorization:
    return EnvironmentBindingAuthorization(
        environment_binding_id="binding:data-agent",
        version=1,
        binding_digest=BINDING_DIGEST,
    )


def _mandate(*, correction_epoch: int = 0) -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:agent-os",
        version=1,
        mandate_digest=MANDATE_DIGEST,
        ratification_receipt_id="ratification:founder-1",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="user:local",
        ratified_by="user:local",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=30),
        correction_epoch=correction_epoch,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(_binding(),),
        relevance_assessor=_assessor_ref(),
    )


def _assessment(
    *,
    assessor_ref: RelevanceAssessorRef | None = None,
    correction_epoch: int = 0,
    disposition: RelevanceDisposition = RelevanceDisposition.CREATE_TASK,
) -> RelevanceAssessment:
    assessor = assessor_ref or _assessor_ref()
    mandate = _mandate(correction_epoch=correction_epoch)
    return RelevanceAssessment(
        assessment_id="assessment:trusted-1",
        environment_event_id="event:report-1",
        event_observation_digest=OBSERVATION_DIGEST,
        projection_id="projection:report-1",
        projection_digest=PROJECTION_DIGEST,
        mandate_id="mandate:agent-os",
        mandate_version=1,
        mandate_digest=MANDATE_DIGEST,
        environment_binding_id="binding:data-agent",
        environment_binding_version=1,
        environment_binding_digest=BINDING_DIGEST,
        correction_epoch=correction_epoch,
        assessor=assessor,
        input_binding_digest=situated_input_binding_digest(
            mandate,
            _binding(),
            _event(),
            _projection(),
            assessor,
        ),
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        affected_commitment_ids=("commitment:product-v0",),
        disposition=disposition,
        uncertainty_summary="A bounded review is still required.",
        urgency=RelevanceUrgency.MEDIUM,
        expected_loss_of_delay="A regression may remain unreviewed.",
        attention_budget_seconds=600,
        rationale="The grounded report may affect the active commitment.",
        evidence_ids=("evidence:event", "evidence:projection"),
        proposed_goal_statement=(
            "Review the report without activating work."
            if disposition is RelevanceDisposition.CREATE_TASK
            else None
        ),
        known_facts=("A grounded report exists.",),
        unknown_facts=("Whether it affects the active commitment.",),
        acquisition_attempts=("Resolved the trusted projection.",),
        bounded_options=("Observe only", "Prepare a read-only draft"),
        minimum_external_input=(
            "Which bounded option should remain available?"
            if disposition is RelevanceDisposition.HELP
            else None
        ),
        continuable_work=("Refresh evidence without external effects.",),
        assessed_at=NOW - timedelta(minutes=1),
    )


class _Assessor:
    def __init__(self, assessment: RelevanceAssessment) -> None:
        self.assessment = assessment
        self.calls = 0

    @property
    def ref(self) -> RelevanceAssessorRef:
        return self.assessment.assessor

    def assess(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        *,
        assessed_at: datetime,
    ) -> RelevanceAssessment:
        self.calls += 1
        return self.assessment


class _BlockingAssessor(_Assessor):
    def __init__(self, assessment: RelevanceAssessment) -> None:
        super().__init__(assessment)
        self.started = Event()
        self.release = Event()

    def assess(self, *args, **kwargs) -> RelevanceAssessment:  # type: ignore[no-untyped-def]
        self.started.set()
        assert self.release.wait(timeout=5)
        return super().assess(*args, **kwargs)


def _trust(
    *,
    event: EnvironmentEvent | None = None,
    projection: OperationalProjectionRef | None = None,
) -> InMemorySituationalTrustRegistry:
    event = event or _event()
    projection = projection or _projection()
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


def _service(
    assessor: _Assessor,
    *,
    control: InMemorySituationalControlPlane | None = None,
) -> tuple[OperationalProposalService, InMemorySituationalControlPlane]:
    plane = control or InMemorySituationalControlPlane((_mandate(),))
    return (
        OperationalProposalService(
            trust=_trust(),
            control=plane,
            assessor=assessor,
            principal_id="user:local",
        ),
        plane,
    )


def test_service_generates_proposal_without_caller_supplied_assessment() -> None:
    service, plane = _service(_Assessor(_assessment()))

    result = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert isinstance(result, TaskDraftProposal)
    assert result.mandate_version == 1
    assert result.mandate_digest == MANDATE_DIGEST
    assert result.correction_epoch == 0
    assert result.assessor == _assessor_ref()
    assert result.activation_authorized is False
    assert result.external_effects_authorized is False
    assert plane.assessment("assessment:trusted-1") == _assessment()


def test_application_entry_accepts_only_trusted_ids_and_never_writes_task(
    tmp_path,
) -> None:
    assessor = _Assessor(_assessment())
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        situational_trust=_trust(),
        situational_control=SQLiteSituatedAssessmentStore(
            tmp_path / "situated.sqlite3", mandates=(_mandate(),)
        ),
        relevance_assessor=assessor,
        clock=lambda: NOW,
    )

    result = app.propose_situated_work(
        "event:report-1",
        "projection:report-1",
    )

    assert isinstance(result, TaskDraftProposal)
    assert app.store.list_task_ids() == ()
    with pytest.raises(TypeError):
        getattr(app, "propose_situated_work")(
            "event:report-1",
            "projection:report-1",
            _assessment().model_dump(mode="json"),
        )
    assert app.store.list_task_ids() == ()


def test_wrong_assessor_version_is_rejected_before_emission() -> None:
    service, plane = _service(
        _Assessor(_assessment(assessor_ref=_assessor_ref(version=2)))
    )

    with pytest.raises(SituationalTrustDenied, match="assessor"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert plane.assessment("assessment:trusted-1") is None


def test_missing_or_paused_mandate_fails_closed() -> None:
    assessor = _Assessor(_assessment())
    service, plane = _service(assessor)
    plane.pause("mandate:agent-os", expected_epoch=0)

    with pytest.raises(SituationalTrustDenied, match="active"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert assessor.calls == 0
    assert plane.assessment("assessment:trusted-1") is None


def test_revoke_between_assessment_and_emission_wins_atomically() -> None:
    assessor = _BlockingAssessor(_assessment())
    service, plane = _service(assessor)
    outcome: list[object] = []

    def run() -> None:
        try:
            outcome.append(
                service.propose(
                    "event:report-1",
                    "projection:report-1",
                    evaluated_at=NOW,
                )
            )
        except Exception as exc:  # noqa: BLE001 - exact exception asserted below
            outcome.append(exc)

    worker = Thread(target=run)
    worker.start()
    assert assessor.started.wait(timeout=5)
    plane.revoke("mandate:agent-os", expected_epoch=0)
    assessor.release.set()
    worker.join(timeout=5)

    assert len(outcome) == 1
    assert isinstance(outcome[0], SituationalTrustDenied)
    assert "epoch" in str(outcome[0]) or "active" in str(outcome[0])
    assert plane.assessment("assessment:trusted-1") is None


def test_assessment_cannot_forge_binding_or_epoch() -> None:
    service, plane = _service(_Assessor(_assessment(correction_epoch=99)))

    with pytest.raises(SituationalTrustDenied, match="epoch"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert plane.assessment("assessment:trusted-1") is None


def test_internal_compiler_is_not_a_public_os_core_entry_point() -> None:
    assert not hasattr(agent_os_core, "OperationalProposalCompiler")


def test_assessment_digest_binds_complete_event_and_projection_semantics() -> None:
    assessor = _Assessor(_assessment())
    corrected_event = _event().model_copy(update={"dedupe_key": "report:corrected"})
    service = OperationalProposalService(
        trust=_trust(event=corrected_event),
        control=InMemorySituationalControlPlane((_mandate(),)),
        assessor=assessor,
        principal_id="user:local",
    )

    with pytest.raises(SituationalTrustDenied, match="input binding digest"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)


def test_mismatched_trusted_pair_is_rejected_before_assessor() -> None:
    assessor = _Assessor(_assessment())
    projection = _projection().model_copy(update={"mandate_id": "mandate:other"})
    service = OperationalProposalService(
        trust=_trust(projection=projection),
        control=InMemorySituationalControlPlane((_mandate(),)),
        assessor=assessor,
        principal_id="user:local",
    )

    with pytest.raises(SituationalTrustDenied, match="mandate"):
        service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert assessor.calls == 0


def test_help_request_cannot_grant_authority_or_external_effects() -> None:
    service, _ = _service(_Assessor(_assessment(disposition=RelevanceDisposition.HELP)))

    result = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert isinstance(result, HelpRequest)
    assert result.projection_digest == PROJECTION_DIGEST
    assert result.authority_granted is False
    assert result.external_effects_authorized is False
    assert not hasattr(result, "approve")
    assert not hasattr(result, "resume")


def test_application_rejects_partial_situated_configuration(tmp_path) -> None:
    with pytest.raises(ValueError, match="configured together"):
        AgentOSApplication(
            database=tmp_path / "agent-os.sqlite3",
            workspace=tmp_path,
            situational_trust=_trust(),
            situational_control=InMemorySituationalControlPlane((_mandate(),)),
            clock=lambda: NOW,
        )

    with pytest.raises(ValueError, match="trust resolver"):
        AgentOSApplication(
            database=tmp_path / "agent-os-without-trust.sqlite3",
            workspace=tmp_path,
            situational_control=InMemorySituationalControlPlane((_mandate(),)),
            relevance_assessor=_Assessor(_assessment()),
            clock=lambda: NOW,
        )

    with pytest.raises(ValueError, match="durable authority"):
        AgentOSApplication(
            database=tmp_path / "agent-os-memory-authority.sqlite3",
            workspace=tmp_path,
            situational_trust=_trust(),
            situational_control=InMemorySituationalControlPlane((_mandate(),)),
            relevance_assessor=_Assessor(_assessment()),
            clock=lambda: NOW,
        )


def test_revoked_sqlite_mandate_is_terminal_across_instances(tmp_path) -> None:
    database = tmp_path / "situated-terminal-revoke.sqlite3"
    first = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    second = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))

    revoked = first.revoke("mandate:agent-os", expected_epoch=0)

    assert revoked.correction_epoch == 1
    with pytest.raises(SituationalTrustDenied, match="terminal"):
        second.pause("mandate:agent-os", expected_epoch=1)


def test_sqlite_store_persists_task_draft_assessment_across_restart(tmp_path) -> None:
    database = tmp_path / "situated.sqlite3"
    store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    service = OperationalProposalService(
        trust=_trust(),
        control=store,
        assessor=_Assessor(_assessment()),
        principal_id="user:local",
    )

    result = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert isinstance(result, TaskDraftProposal)
    record = store.assessment_record("assessment:trusted-1")
    assert record is not None
    assert record.task_draft == result
    assert record.help_request is None
    assert record.outcome_kind.value == "TASK_DRAFT"

    restarted = SQLiteSituatedAssessmentStore(database)
    assert restarted.assessment_record("assessment:trusted-1") == record


def test_sqlite_store_audits_no_proposal_outcome_across_restart(tmp_path) -> None:
    database = tmp_path / "situated-no-proposal.sqlite3"
    store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    service = OperationalProposalService(
        trust=_trust(),
        control=store,
        assessor=_Assessor(_assessment(disposition=RelevanceDisposition.OBSERVE)),
        principal_id="user:local",
    )

    result = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert result is None
    restarted = SQLiteSituatedAssessmentStore(database)
    record = restarted.assessment_record("assessment:trusted-1")
    assert record is not None
    assert record.outcome_kind.value == "NO_PROPOSAL"
    assert record.task_draft is None
    assert record.help_request is None


def test_sqlite_store_persists_help_request_without_authority_across_restart(
    tmp_path,
) -> None:
    database = tmp_path / "situated-help.sqlite3"
    store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    service = OperationalProposalService(
        trust=_trust(),
        control=store,
        assessor=_Assessor(_assessment(disposition=RelevanceDisposition.HELP)),
        principal_id="user:local",
    )

    result = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert isinstance(result, HelpRequest)
    assert result.authority_granted is False
    assert result.external_effects_authorized is False
    restarted = SQLiteSituatedAssessmentStore(database)
    record = restarted.assessment_record("assessment:trusted-1")
    assert record is not None
    assert record.outcome_kind.value == "HELP_REQUEST"
    assert record.help_request == result
    assert record.task_draft is None


def test_sqlite_revoke_in_one_instance_blocks_other_instance_guarded_emit(
    tmp_path,
) -> None:
    database = tmp_path / "situated-revoke-race.sqlite3"
    authority = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    emitter = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    assessor = _BlockingAssessor(_assessment())
    service = OperationalProposalService(
        trust=_trust(),
        control=emitter,
        assessor=assessor,
        principal_id="user:local",
    )
    outcome: list[object] = []

    def run() -> None:
        try:
            outcome.append(
                service.propose(
                    "event:report-1",
                    "projection:report-1",
                    evaluated_at=NOW,
                )
            )
        except Exception as exc:  # noqa: BLE001 - exact exception asserted below
            outcome.append(exc)

    worker = Thread(target=run)
    worker.start()
    assert assessor.started.wait(timeout=5)
    authority.revoke("mandate:agent-os", expected_epoch=0)
    assessor.release.set()
    worker.join(timeout=5)

    assert len(outcome) == 1
    assert isinstance(outcome[0], SituationalTrustDenied)
    assert emitter.assessment_record("assessment:trusted-1") is None


def test_sqlite_mandate_epoch_cas_survives_other_instance_and_restart(tmp_path) -> None:
    database = tmp_path / "situated-epoch.sqlite3"
    first = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    second = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))

    paused = first.pause("mandate:agent-os", expected_epoch=0)

    assert paused.correction_epoch == 1
    with pytest.raises(SituationalTrustDenied, match="epoch"):
        second.revoke("mandate:agent-os", expected_epoch=0)
    restarted = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    with pytest.raises(SituationalTrustDenied, match="active"):
        restarted.resolve_active(
            "mandate:agent-os",
            "binding:data-agent",
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            evaluated_at=NOW,
        )


def test_sqlite_source_binding_is_idempotent_and_conflicts_fail_closed(
    tmp_path,
) -> None:
    database = tmp_path / "situated-idempotency.sqlite3"
    store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    service = OperationalProposalService(
        trust=_trust(),
        control=store,
        assessor=_Assessor(_assessment()),
        principal_id="user:local",
    )

    first = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)
    replay = service.propose("event:report-1", "projection:report-1", evaluated_at=NOW)

    assert isinstance(first, TaskDraftProposal)
    assert replay == first
    record = store.record_by_source_binding(first.source_binding_digest)
    assert record is not None
    conflicting = first.model_copy(
        update={
            "goal": first.goal.model_copy(
                update={"statement": "Conflicting output for the same source binding."}
            )
        }
    )
    with pytest.raises(SituationalPersistenceConflict, match="source binding"):
        store._emit_guarded(
            _mandate(),
            _binding(),
            _assessment(),
            principal_id="user:local",
            evaluated_at=NOW,
            source_binding_digest=first.source_binding_digest,
            factory=lambda: conflicting,
        )
    assert store.record_by_source_binding(first.source_binding_digest) == record


def test_sqlite_situated_store_rejects_non_durable_memory_database() -> None:
    with pytest.raises(ValueError, match="file-backed"):
        SQLiteSituatedAssessmentStore(":memory:", mandates=(_mandate(),))


def test_application_uses_sqlite_situated_store_without_task_conversion(
    tmp_path,
) -> None:
    database = tmp_path / "agent-os-with-situated.sqlite3"
    situated_store = SQLiteSituatedAssessmentStore(database, mandates=(_mandate(),))
    app = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        situational_trust=_trust(),
        situational_control=situated_store,
        relevance_assessor=_Assessor(_assessment()),
        clock=lambda: NOW,
    )

    result = app.propose_situated_work("event:report-1", "projection:report-1")

    assert isinstance(result, TaskDraftProposal)
    assert app.store.list_task_ids() == ()
    restarted = SQLiteSituatedAssessmentStore(database)
    assert restarted.assessment_record("assessment:trusted-1") is not None


def test_sqlite_store_does_not_expose_public_guarded_emission_bypass(tmp_path) -> None:
    store = SQLiteSituatedAssessmentStore(
        tmp_path / "situated-private-writer.sqlite3", mandates=(_mandate(),)
    )

    assert not hasattr(store, "emit_guarded")


def test_sqlite_guarded_emission_rolls_back_when_outcome_factory_fails(
    tmp_path,
) -> None:
    store = SQLiteSituatedAssessmentStore(
        tmp_path / "situated-rollback.sqlite3", mandates=(_mandate(),)
    )

    def fail() -> None:
        raise RuntimeError("compiler failed")

    with pytest.raises(RuntimeError, match="compiler failed"):
        store._emit_guarded(
            _mandate(),
            _binding(),
            _assessment(),
            principal_id="user:local",
            evaluated_at=NOW,
            source_binding_digest="f" * 64,
            factory=fail,
        )
    assert store.assessment_record("assessment:trusted-1") is None
