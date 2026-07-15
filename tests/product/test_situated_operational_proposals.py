from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    EnvironmentEvent,
    EvidenceRef,
    EvidenceSourceKind,
    HelpRequest,
    OperationalProjectionRef,
    ProposedGoal,
    RelevanceAssessment,
    RelevanceDisposition,
    TaskDraftProposal,
)
from agent_os_core import (
    InMemorySituationalTrustRegistry,
    OperationalProposalCompiler,
    SituationalScopeMismatch,
    SituationalTrustDenied,
    StaleOperationalProjection,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
OBSERVATION_BYTES = b'{"observation":"verified"}'
PROJECTION_BYTES = b'{"projection":"verified"}'
OBSERVATION_DIGEST = hashlib.sha256(OBSERVATION_BYTES).hexdigest()
PROJECTION_DIGEST = hashlib.sha256(PROJECTION_BYTES).hexdigest()


def _artifact(
    artifact_id: str,
    *,
    tenant_id: str = "tenant:local",
    digest: str = PROJECTION_DIGEST,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        tenant_id=tenant_id,
        workspace_id="workspace:local",
        content_digest=digest,
        media_type="application/json",
        location_class=ArtifactLocationClass.OBJECT_STORE,
        location_ref=f"object://{artifact_id}",
        acl_scopes=("situated:read",),
        retention_policy="retain-30-days",
        created_by="environment-adapter:test",
        created_at=NOW - timedelta(minutes=3),
    )


def _evidence(
    evidence_id: str,
    *,
    tenant_id: str = "tenant:local",
    artifact_id: str = "artifact:observation",
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        workspace_id="workspace:local",
        source_kind=EvidenceSourceKind.ARTIFACT,
        source_ref=artifact_id,
        relation="supports",
        artifact_ids=(artifact_id,),
        created_by="environment-adapter:test",
        created_at=NOW - timedelta(minutes=2),
    )


def _event(**updates: Any) -> EnvironmentEvent:
    tenant_id = str(updates.get("tenant_id", "tenant:local"))
    values: dict[str, Any] = {
        "environment_event_id": "event:report-1",
        "environment_binding_id": "binding:data-agent-reports",
        "mandate_id": "mandate:build-agent-os",
        "tenant_id": tenant_id,
        "workspace_id": "workspace:local",
        "event_type_ref": "data-agent.report-observed.v1",
        "dedupe_key": "report:trace-1",
        "observation": _artifact(
            "artifact:observation",
            tenant_id=tenant_id,
            digest=OBSERVATION_DIGEST,
        ),
        "evidence": (_evidence("evidence:event", tenant_id=tenant_id),),
        "occurred_at": NOW - timedelta(minutes=4),
        "recorded_at": NOW - timedelta(minutes=3),
    }
    values.update(updates)
    return EnvironmentEvent(**values)


def _projection(**updates: Any) -> OperationalProjectionRef:
    tenant_id = str(updates.get("tenant_id", "tenant:local"))
    values: dict[str, Any] = {
        "projection_id": "projection:report-1",
        "environment_binding_id": "binding:data-agent-reports",
        "mandate_id": "mandate:build-agent-os",
        "tenant_id": tenant_id,
        "workspace_id": "workspace:local",
        "source_event_ids": ("event:report-1",),
        "projection_artifact": _artifact(
            "artifact:projection", tenant_id=tenant_id
        ),
        "schema_uri": "schema://operational-projection/data-agent-report/v1",
        "version": 1,
        "scope_ref": "mission:agent-os/product",
        "valid_from": NOW - timedelta(minutes=2),
        "recorded_at": NOW - timedelta(minutes=2),
        "fresh_until": NOW + timedelta(minutes=10),
        "evidence": (
            _evidence(
                "evidence:projection",
                tenant_id=tenant_id,
                artifact_id="artifact:projection",
            ),
        ),
        "epistemic_status": "EVIDENCED",
        "uncertainty_summary": "Freshness is verified; business significance is not.",
        "compatibility_digest": "b" * 64,
    }
    values.update(updates)
    return OperationalProjectionRef(**values)


def _assessment(**updates: Any) -> RelevanceAssessment:
    values: dict[str, Any] = {
        "assessment_id": "assessment:report-1",
        "environment_event_id": "event:report-1",
        "event_observation_digest": OBSERVATION_DIGEST,
        "projection_id": "projection:report-1",
        "projection_digest": PROJECTION_DIGEST,
        "mandate_id": "mandate:build-agent-os",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "disposition": RelevanceDisposition.CREATE_TASK,
        "affected_commitment_ids": ("commitment:product-v0",),
        "uncertainty_summary": "The report is grounded but still needs bounded review.",
        "urgency": "MEDIUM",
        "expected_loss_of_delay": "Delayed follow-up may miss a regression.",
        "attention_budget_seconds": 900,
        "rationale": "A new verified report may alter the product commitment.",
        "evidence_ids": ("evidence:event", "evidence:projection"),
        "proposed_goal_statement": "Review the new report and decide a bounded follow-up.",
        "assessed_at": NOW - timedelta(minutes=1),
    }
    values.update(updates)
    return RelevanceAssessment(**values)


def _trust_registry(
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
                "mandate:build-agent-os",
                "binding:data-agent-reports",
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


def _compiler(
    *,
    event: EnvironmentEvent | None = None,
    projection: OperationalProjectionRef | None = None,
) -> OperationalProposalCompiler:
    return OperationalProposalCompiler(
        _trust_registry(event=event, projection=projection),
        principal_id="user:local",
    )


def _app(tmp_path, *, now: datetime = NOW) -> AgentOSApplication:
    return AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        situational_trust=_trust_registry(),
        clock=lambda: now,
    )


def test_create_task_disposition_compiles_bound_draft_without_side_effect() -> None:
    result = _compiler().compile(
        _event(), _projection(), _assessment(), evaluated_at=NOW
    )

    assert isinstance(result, TaskDraftProposal)
    assert result.triggering_event_id == "event:report-1"
    assert result.event_observation_digest == OBSERVATION_DIGEST
    assert result.projection_id == "projection:report-1"
    assert result.projection_digest == PROJECTION_DIGEST
    assert isinstance(result.goal, ProposedGoal)
    assert result.goal.statement == (
        "Review the new report and decide a bounded follow-up."
    )
    assert result.activation_authorized is False
    assert result.external_effects_authorized is False


def test_help_disposition_compiles_minimum_structured_request() -> None:
    assessment = _assessment(
        disposition=RelevanceDisposition.HELP,
        proposed_goal_statement=None,
        known_facts=("A grounded report exists.",),
        unknown_facts=("Whether the change violates the mandate.",),
        acquisition_attempts=("Checked the frozen trigger policy.",),
        bounded_options=("Record only", "Create a read-only investigation draft"),
        minimum_external_input="Does this change require investigation?",
        continuable_work=("Refresh independent evidence",),
    )

    result = _compiler().compile(
        _event(), _projection(), assessment, evaluated_at=NOW
    )

    assert isinstance(result, HelpRequest)
    assert result.minimum_external_input == (
        "Does this change require investigation?"
    )
    assert result.continuable_work == ("Refresh independent evidence",)
    assert result.authority_granted is False


@pytest.mark.parametrize(
    "disposition",
    [
        RelevanceDisposition.IGNORE,
        RelevanceDisposition.OBSERVE,
        RelevanceDisposition.ABSTAIN,
    ],
)
def test_non_work_disposition_produces_no_proposal(
    disposition: RelevanceDisposition,
) -> None:
    assessment = _assessment(
        disposition=disposition,
        proposed_goal_statement=None,
    )

    assert (
        _compiler().compile(
            _event(), _projection(), assessment, evaluated_at=NOW
        )
        is None
    )


def test_scope_mismatch_fails_closed() -> None:
    with pytest.raises(SituationalScopeMismatch, match="scope"):
        _compiler().compile(
            _event(),
            _projection(tenant_id="tenant:other"),
            _assessment(),
            evaluated_at=NOW,
        )


def test_projection_digest_or_source_event_mismatch_fails_closed() -> None:
    with pytest.raises(SituationalScopeMismatch, match="digest"):
        _compiler().compile(
            _event(),
            _projection(),
            _assessment(projection_digest="c" * 64),
            evaluated_at=NOW,
        )

    with pytest.raises(SituationalScopeMismatch, match="source event"):
        _compiler().compile(
            _event(environment_event_id="event:unbound"),
            _projection(),
            _assessment(environment_event_id="event:unbound"),
            evaluated_at=NOW,
        )

    with pytest.raises(SituationalScopeMismatch, match="observation digest"):
        _compiler().compile(
            _event(),
            _projection(),
            _assessment(event_observation_digest="e" * 64),
            evaluated_at=NOW,
        )


def test_stale_projection_fails_closed() -> None:
    stale = _projection(fresh_until=NOW - timedelta(seconds=1))
    with pytest.raises(StaleOperationalProjection):
        _compiler(projection=stale).compile(
            _event(),
            stale,
            _assessment(),
            evaluated_at=NOW,
        )


def test_help_and_task_fields_are_disposition_specific() -> None:
    with pytest.raises(ValidationError, match="minimum_external_input"):
        _assessment(
            disposition=RelevanceDisposition.HELP,
            proposed_goal_statement=None,
        )

    with pytest.raises(ValidationError, match="proposed_goal_statement"):
        _assessment(proposed_goal_statement=None)


def test_event_and_projection_evidence_must_reference_bound_artifacts() -> None:
    with pytest.raises(ValidationError, match="observation artifact"):
        _event(evidence=(_evidence("evidence:event", artifact_id="artifact:other"),))

    with pytest.raises(ValidationError, match="projection artifact"):
        _projection(
            evidence=(
                _evidence("evidence:projection", artifact_id="artifact:other"),
            )
        )


def test_input_cannot_smuggle_workflow_or_authority(tmp_path) -> None:
    app = _app(tmp_path)
    event_payload = _event().model_dump(mode="json")
    event_payload["workflow"] = {"execute": True}
    event_payload["authority_scopes"] = ["workspace:write"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        app.propose_situated_work(
            event_payload,
            _projection().model_dump(mode="json"),
            _assessment().model_dump(mode="json"),
        )

    assert app.store.list_task_ids() == ()


def test_proposal_identity_is_content_bound_and_replay_stable() -> None:
    compiler = _compiler()
    first = compiler.compile(_event(), _projection(), _assessment(), evaluated_at=NOW)
    replay = compiler.compile(
        _event(),
        _projection(),
        _assessment(),
        evaluated_at=NOW + timedelta(minutes=1),
    )
    changed_event = _event(dedupe_key="report:trace-1-corrected")
    changed = _compiler(event=changed_event).compile(
        changed_event,
        _projection(),
        _assessment(),
        evaluated_at=NOW,
    )

    assert isinstance(first, TaskDraftProposal)
    assert isinstance(replay, TaskDraftProposal)
    assert isinstance(changed, TaskDraftProposal)
    assert first.task_draft_id == replay.task_draft_id
    assert first.source_binding_digest == replay.source_binding_digest
    assert first == replay
    assert changed.task_draft_id != first.task_draft_id
    assert changed.source_binding_digest != first.source_binding_digest


def test_application_entry_point_is_read_only_and_principal_scoped(tmp_path) -> None:
    app = _app(tmp_path)

    result = app.propose_situated_work(
        _event().model_dump(mode="json"),
        _projection().model_dump(mode="json"),
        _assessment().model_dump(mode="json"),
    )

    assert isinstance(result, TaskDraftProposal)
    assert app.store.list_task_ids() == ()

    with pytest.raises(SituationalScopeMismatch, match="principal"):
        app.propose_situated_work(
            _event(tenant_id="tenant:other").model_dump(mode="json"),
            _projection(tenant_id="tenant:other").model_dump(mode="json"),
            _assessment(tenant_id="tenant:other").model_dump(mode="json"),
        )


def test_untrusted_mandate_or_self_certified_artifact_is_rejected(tmp_path) -> None:
    app = _app(tmp_path)

    with pytest.raises(SituationalTrustDenied, match="mandate"):
        app.propose_situated_work(
            _event(mandate_id="mandate:attacker-invented").model_dump(mode="json"),
            _projection(mandate_id="mandate:attacker-invented").model_dump(
                mode="json"
            ),
            _assessment(mandate_id="mandate:attacker-invented").model_dump(
                mode="json"
            ),
        )

    forged = _artifact(
        "artifact:observation",
        digest=hashlib.sha256(b"forged").hexdigest(),
    )
    forged_evidence = _evidence("evidence:event")
    forged_event = _event(observation=forged, evidence=(forged_evidence,))
    with pytest.raises(SituationalTrustDenied, match="event"):
        app.propose_situated_work(
            forged_event.model_dump(mode="json"),
            _projection().model_dump(mode="json"),
            _assessment(
                event_observation_digest=forged.content_digest
            ).model_dump(mode="json"),
        )

    forged_projection = _projection(fresh_until=NOW + timedelta(days=365))
    with pytest.raises(SituationalTrustDenied, match="projection"):
        app.propose_situated_work(
            _event().model_dump(mode="json"),
            forged_projection.model_dump(mode="json"),
            _assessment().model_dump(mode="json"),
        )

    assert app.store.list_task_ids() == ()


def test_application_uses_trusted_clock_not_caller_time(tmp_path) -> None:
    app = _app(tmp_path, now=NOW + timedelta(minutes=20))

    with pytest.raises(StaleOperationalProjection):
        app.propose_situated_work(
            _event().model_dump(mode="json"),
            _projection().model_dump(mode="json"),
            _assessment().model_dump(mode="json"),
        )

    with pytest.raises(TypeError, match="evaluated_at"):
        getattr(app, "propose_situated_work")(
            _event().model_dump(mode="json"),
            _projection().model_dump(mode="json"),
            _assessment().model_dump(mode="json"),
            evaluated_at=NOW,
        )


def test_untyped_assessment_evidence_cannot_leak_into_output() -> None:
    with pytest.raises(SituationalTrustDenied, match="evidence set"):
        _compiler().compile(
            _event(),
            _projection(),
            _assessment(
                evidence_ids=(
                    "evidence:event",
                    "evidence:projection",
                    "evidence:tenant-other:secret",
                )
            ),
            evaluated_at=NOW,
        )


def test_proposed_goal_cannot_enter_generic_task_creation(tmp_path) -> None:
    app = _app(tmp_path)
    result = app.propose_situated_work(
        _event().model_dump(mode="json"),
        _projection().model_dump(mode="json"),
        _assessment().model_dump(mode="json"),
    )

    assert isinstance(result, TaskDraftProposal)
    assert isinstance(result.goal, ProposedGoal)
    with pytest.raises(ValidationError):
        app.create_task(result.goal.model_dump(mode="json"))
    assert app.store.list_task_ids() == ()
