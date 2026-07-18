from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from agent_os_contracts import (
    CredentialRef,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    ProviderRelevancePolicy,
    ProviderProfile,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    RelevanceDisposition,
    TaskDraftProposal,
    content_digest,
)
from agent_os_core import (
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    ProviderRelevanceAssessor,
    SQLiteTaskEventStore,
    SituationalTrustDenied,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_admission import (
    DataAgentReportAdmissionError,
    SQLiteDataAgentReportAdmissionMaterialStore,
)
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    SQLiteDataAgentReportStateStore,
)
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from apps.api_server.mandate_active_perception import (
    ActivePerceptionDisposition,
    MandateActivePerceptionConfig,
    MandateActivePerceptionService,
    SQLiteMandateActivePerceptionStore,
)
from tests.product.test_data_agent_external_report_adapter import (
    NOW,
    TRACE_ID,
    _adapter,
    _binding,
    _config,
    _credential as _data_credential,
    _feed_bytes,
    _feed_event,
    _report_bytes,
    _response,
)
from tests.product.test_provider_relevance_assessor import (
    _draft as _provider_draft,
    _invocation as _provider_invocation,
    _policy as _provider_policy,
)
from tests.product.mandate_observation_support import (
    authorize_workspace_observation,
    create_workspace_record,
)


def _context(*, mandate_digest: str = "a" * 64) -> MandateRelevanceContext:
    return MandateRelevanceContext(
        relevance_context_id="mandate-context:data-agent-reports-v1",
        version=1,
        mandate_id="mandate:build-agent-os",
        mandate_version=1,
        mandate_digest=mandate_digest,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mission_statement=(
            "Keep Agent OS product commitments truthful without activating work."
        ),
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:truthful-product",
                statement="Review trusted Data Agent reports without hidden authority.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:quality",
                statement="Protect the verified product quality boundary.",
                due_at=NOW + timedelta(hours=2),
            ),
        ),
        permanent_constraints=(
            "No task activation from relevance assessment.",
            "No external effect authority.",
            "C7 correction always wins.",
        ),
    )


def _mandate(policy: ProviderRelevancePolicy) -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:build-agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:data-agent-provider-e2e",
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
        relevance_assessor=policy.assessor_ref(),
        relevance_context=_context().ref(),
    )


def _provider(
    policy: ProviderRelevancePolicy,
    disposition: RelevanceDisposition = RelevanceDisposition.CREATE_TASK,
) -> DeterministicProvider:
    return DeterministicProvider(
        text=_provider_draft(disposition),
        invocation_binding=policy.provider_invocation,
    )


def _application(
    *,
    task_database: Path,
    workspace: Path,
    adapter: DataAgentReportAdapter,
    control: SQLiteSituatedAssessmentStore,
    provider: DeterministicProvider,
    policy: ProviderRelevancePolicy,
    credential: CredentialRef | None = None,
    provider_profile: ProviderProfile | None = None,
) -> AgentOSApplication:
    credential = credential or _data_credential()
    credentials = adapter._credential_authorization_reader_for_composition
    configured = credentials.resolve_authorization(credential.credential_ref_id)
    assert configured is not None
    assert configured.credential_ref_digest == content_digest(credential)
    authority_database = Path(control._database)
    workspace_record = create_workspace_record(
        authority_database, workspace, adapter=adapter, now=NOW
    )
    context = _context(mandate_digest=content_digest(workspace_record.mandate))
    assessor = ProviderRelevanceAssessor(
        provider=provider,
        provider_profile=provider_profile
        or policy.provider_invocation.provider_profile,
        policy=policy,
        trust=adapter,
        contexts=InMemoryMandateRelevanceContextRegistry((context,)),
    )
    with sqlite3.connect(authority_database) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'mandate_observation_authorizations'"
        ).fetchone()
        authorization_exists = (
            connection.execute(
                "SELECT 1 FROM mandate_observation_authorizations LIMIT 1"
            ).fetchone()
            if table_exists is not None
            else None
        )
    if authorization_exists is None:
        authorize_workspace_observation(
            authority_database,
            workspace,
            adapter=adapter,
            assessor=assessor.ref,
            context=context.ref(),
            now=NOW,
        )
    runtime = DataAgentSituatedBootstrap.compose(
        adapter=adapter,
        material_store=SQLiteDataAgentReportAdmissionMaterialStore(
            task_database.with_name(f"{task_database.name}.material.sqlite3"),
            principal_id=adapter.principal_scope[0],
            tenant_id=adapter.principal_scope[1],
            workspace_id=adapter.principal_scope[2],
        ),
        credentials=credentials,
        control=control,
        assessor=assessor,
        admission_database=task_database.with_name(
            f"{task_database.name}.admission.sqlite3"
        ),
        clock=lambda: NOW,
    )
    principal = PrincipalIdentity(
        principal_id=adapter.principal_scope[0],
        tenant_id=adapter.principal_scope[1],
        workspace_id=adapter.principal_scope[2],
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    return AgentOSApplication._with_data_agent_situated_runtime(
        situated_runtime=runtime,
        database=task_database,
        workspace=workspace,
        principal=principal,
        clock=lambda: NOW,
    )


def test_ingest_provider_proposal_offline_replay_and_revoke_survive_restarts(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    situated_database = report_database
    task_database = tmp_path / "agent-os.sqlite3"
    policy = _provider_policy()
    first_adapter, first_broker, first_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    first_provider = _provider(policy)
    first_control = SQLiteSituatedAssessmentStore(situated_database)
    first_app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=first_adapter,
        control=first_control,
        provider=first_provider,
        policy=policy,
    )

    bundle = first_app.observe_data_agent_report(TRACE_ID)
    first = first_app.observe_admit_and_propose_data_agent_report(TRACE_ID)

    assert isinstance(first, TaskDraftProposal)
    assert first.activation_authorized is False
    assert first.external_effects_authorized is False
    assert first_app.store.list_task_ids() == ()
    assert len(first_broker.resolved) == 3
    assert len(first_transport.requests) == 2
    assert len(first_provider.decision_requests) == 1
    receipt = first_app.admit_data_agent_event(bundle.event.environment_event_id)
    with pytest.raises(SituationalTrustDenied):
        first_app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
            receipt.model_copy(),  # type: ignore[arg-type]
        )
    assert len(first_provider.decision_requests) == 1
    assert first_app.store.list_task_ids() == ()
    first_app.store.close()

    replay_adapter, replay_broker, replay_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    replay_provider = _provider(policy, RelevanceDisposition.HELP)
    replay_control = SQLiteSituatedAssessmentStore(situated_database)
    replay_app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=replay_adapter,
        control=replay_control,
        provider=replay_provider,
        policy=policy,
    )

    replay = replay_app.observe_admit_and_propose_data_agent_report(TRACE_ID)

    assert replay == first
    assert replay_app.store.list_task_ids() == ()
    assert len(replay_broker.resolved) == 2
    assert len(replay_transport.requests) == 1
    assert replay_provider.decision_requests == []
    assessment = replay_control.assessment(first.relevance_assessment_id)
    assert assessment is not None
    input_digest = assessment.input_binding_digest
    persisted = replay_control.record_by_input_binding(input_digest)
    assert persisted is not None
    replay_app.store.close()

    replay_control.revoke(
        "mandate:build-agent-os",
        expected_epoch=0,
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    revoked_adapter, revoked_broker, revoked_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    revoked_provider = _provider(policy)
    with pytest.raises(SituationalTrustDenied, match="not active"):
        _application(
            task_database=task_database,
            workspace=tmp_path,
            adapter=revoked_adapter,
            control=SQLiteSituatedAssessmentStore(situated_database),
            provider=revoked_provider,
            policy=policy,
        )

    assert revoked_broker.resolved == []
    assert len(revoked_transport.requests) == 0
    assert revoked_provider.decision_requests == []
    assert replay_control.record_by_input_binding(input_digest) == persisted


def test_active_perception_completed_replay_does_not_call_provider_again(
    tmp_path: Path,
) -> None:
    runtime_database = tmp_path / "runtime.sqlite3"
    credential = _data_credential(
        scopes=(
            "reports:read",
            "report-events:read",
            "data-agent-origin:http://127.0.0.1:8765",
            "data-agent-tenant:data-tenant-1",
        )
    )
    cursor = "cursor-active-1"
    adapter, _, _ = _adapter(
        response=_response(
            _feed_bytes([_feed_event(cursor)], next_cursor=cursor),
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(credential=credential),
        state_store=SQLiteDataAgentReportStateStore(runtime_database),
    )
    policy = _provider_policy()
    provider = _provider(policy)
    control = SQLiteSituatedAssessmentStore(runtime_database)
    app = _application(
        task_database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        adapter=adapter,
        control=control,
        provider=provider,
        policy=policy,
        credential=credential,
    )
    runtime = app._data_agent_situated_runtime
    assert runtime is not None
    config = MandateActivePerceptionConfig(
        schedule_id="schedule:provider-active",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mandate_id="mandate:build-agent-os",
        environment_binding_id="binding:data-agent-reports",
        interval_seconds=60,
        budget_window_seconds=3600,
        wake_budget_per_window=4,
        query_budget_per_window=4,
        feed_limit=1,
        lease_seconds=30,
    )
    store = SQLiteMandateActivePerceptionStore(runtime_database)
    service = MandateActivePerceptionService(
        config=config,
        store=store,
        adapter=adapter,
        runtime=runtime,
        clock=lambda: NOW,
    )
    service.ensure_schedule(first_wake_at=NOW)

    first = service.run_due_once(worker_id="worker-1")
    service.reschedule(next_wake_at=NOW + timedelta(hours=1))
    replay = service.run_due_once(worker_id="worker-2")

    assert first.disposition is ActivePerceptionDisposition.COMPLETED
    assert first.proposal_count == 1
    assert replay.disposition is ActivePerceptionDisposition.NOT_DUE
    assert len(provider.decision_requests) == 1
    assert adapter.pending_dispatches() == ()
    with sqlite3.connect(runtime_database) as connection:
        outcome_record_id, outcome_digest = connection.execute(
            """
            SELECT outcome_record_id, outcome_digest
            FROM data_agent_report_dispatch_outbox WHERE status = 'COMPLETED'
            """
        ).fetchone()
    durable_record = control.record_by_result_digest(outcome_digest)
    assert durable_record is not None
    assert outcome_record_id == durable_record.assessment_record_id
    assert outcome_digest == content_digest(durable_record)
    assert app.store.list_task_ids() == ()
    app.store.close()


def test_unassessed_durable_bundle_is_assessed_once_after_offline_restart(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    policy = _provider_policy()
    first_adapter, first_broker, first_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    first_adapter.pull(TRACE_ID)
    assert len(first_broker.resolved) == 1
    assert len(first_transport.requests) == 1

    restarted_adapter, restarted_broker, restarted_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    provider = _provider(policy)
    app = _application(
        task_database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        adapter=restarted_adapter,
        control=SQLiteSituatedAssessmentStore(report_database),
        provider=provider,
        policy=policy,
    )

    result = app.observe_admit_and_propose_data_agent_report(TRACE_ID)

    assert isinstance(result, TaskDraftProposal)
    assert len(restarted_broker.resolved) == 2
    assert len(restarted_transport.requests) == 1
    assert len(provider.decision_requests) == 1
    assert restarted_adapter.registry_counts == (2, 2, 1, 1)
    assert app.store.list_task_ids() == ()
    app.store.close()


def test_foreign_namespace_never_rehydrates_or_calls_provider(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    foreign_adapter, _, _ = _adapter(
        config=_config(
            principal_id="user:foreign",
            target_tenant_id="tenant:foreign",
            target_workspace_id="workspace:foreign",
            credential=_data_credential(
                owner_principal_id="user:foreign",
                tenant_id="tenant:foreign",
                workspace_id="workspace:foreign",
            ),
        ),
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    foreign_bundle = foreign_adapter.pull(TRACE_ID)

    local_adapter, local_broker, local_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    policy = _provider_policy()
    provider = _provider(policy)
    app = _application(
        task_database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        adapter=local_adapter,
        control=SQLiteSituatedAssessmentStore(report_database),
        provider=provider,
        policy=policy,
    )

    with pytest.raises(DataAgentReportAdmissionError, match="unavailable"):
        app.admit_data_agent_event(foreign_bundle.event.environment_event_id)

    assert local_adapter.registry_counts == (0, 0, 0, 0)
    assert local_broker.resolved == []
    assert local_transport.requests == []
    assert provider.decision_requests == []
    assert app.store.list_task_ids() == ()
    app.store.close()


@pytest.mark.parametrize("corruption", ("body", "bundle"))
def test_corrupt_durable_report_fails_closed_before_provider_without_partial_registry(
    tmp_path: Path,
    corruption: str,
) -> None:
    report_database = tmp_path / f"reports-{corruption}.sqlite3"
    first_adapter, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    bundle = first_adapter.pull(TRACE_ID)
    with sqlite3.connect(report_database) as connection:
        if corruption == "body":
            connection.execute(
                "UPDATE data_agent_report_observations SET body = ?",
                (sqlite3.Binary(b"{}"),),
            )
        else:
            row = connection.execute(
                "SELECT bundle_json FROM data_agent_report_observations"
            ).fetchone()
            assert row is not None
            mutated = json.loads(str(row[0]))
            mutated["projection"]["scope_ref"] = "mission:tampered"
            connection.execute(
                "UPDATE data_agent_report_observations SET bundle_json = ?",
                (
                    json.dumps(
                        mutated,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

    restarted_adapter, broker, transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    policy = _provider_policy()
    provider = _provider(policy)
    control = SQLiteSituatedAssessmentStore(report_database)
    app = _application(
        task_database=tmp_path / f"agent-os-{corruption}.sqlite3",
        workspace=tmp_path,
        adapter=restarted_adapter,
        control=control,
        provider=provider,
        policy=policy,
    )

    with pytest.raises(DataAgentReportAdapterError):
        app.admit_data_agent_event(bundle.event.environment_event_id)

    assert restarted_adapter.registry_counts == (0, 0, 0, 0)
    assert broker.resolved == []
    assert transport.requests == []
    assert provider.decision_requests == []
    assert app.store.list_task_ids() == ()
    with sqlite3.connect(report_database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM situated_assessment_records"
        ).fetchone()
    assert count == (0,)
    app.store.close()


def test_two_revisions_bind_separate_assessments_and_replay_exactly(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    situated_database = report_database
    task_database = tmp_path / "agent-os.sqlite3"
    first_feed = _feed_event("opaque-cursor-1")
    second_feed = _feed_event(
        "opaque-cursor-2",
        _report_bytes(authority_payload=True),
    )
    assert first_feed["trace_id"] == second_feed["trace_id"] == TRACE_ID
    assert first_feed["content_sha256"] != second_feed["content_sha256"]
    feed = _feed_bytes(
        [first_feed, second_feed],
        next_cursor="opaque-cursor-2",
    )
    feed_config = _config(
        credential=_data_credential(
            scopes=(
                "reports:read",
                "report-events:read",
                "data-agent-origin:http://127.0.0.1:8765",
                "data-agent-tenant:data-tenant-1",
            )
        )
    )
    writer, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        config=feed_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    bundles = writer.poll_once(limit=2).bundles
    policy = _provider_policy()
    restarted, broker, transport = _adapter(
        config=feed_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    provider = _provider(policy)
    control = SQLiteSituatedAssessmentStore(situated_database)
    app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=restarted,
        control=control,
        provider=provider,
        policy=policy,
        credential=feed_config.credential,
    )

    def propose_bundle(bundle):  # type: ignore[no-untyped-def]
        receipt = app.admit_data_agent_event(bundle.event.environment_event_id)
        return app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
            receipt.receipt_id,
        )

    first_result, second_result = tuple(propose_bundle(bundle) for bundle in bundles)

    assert isinstance(first_result, TaskDraftProposal)
    assert isinstance(second_result, TaskDraftProposal)
    assert first_result != second_result
    assert first_result.source_binding_digest != second_result.source_binding_digest
    assert len(broker.resolved) == 2
    assert transport.requests == []
    assert len(provider.decision_requests) == 2
    assessments = tuple(
        control.assessment(result.relevance_assessment_id)
        for result in (first_result, second_result)
    )
    assert all(assessment is not None for assessment in assessments)
    input_digests = tuple(
        assessment.input_binding_digest
        for assessment in assessments
        if assessment is not None
    )
    assert input_digests[0] != input_digests[1]
    records = tuple(control.record_by_input_binding(digest) for digest in input_digests)
    assert all(record is not None for record in records)
    assert records[0] is not None and records[1] is not None
    assert records[0].assessment.assessment_id != records[1].assessment.assessment_id
    assert records[0].source_binding_digest != records[1].source_binding_digest
    assert app.store.list_task_ids() == ()
    app.store.close()

    replay_adapter, replay_broker, replay_transport = _adapter(
        config=feed_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    replay_provider = _provider(policy, RelevanceDisposition.HELP)
    replay_app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=replay_adapter,
        control=SQLiteSituatedAssessmentStore(situated_database),
        provider=replay_provider,
        policy=policy,
        credential=feed_config.credential,
    )

    def replay_bundle(bundle):  # type: ignore[no-untyped-def]
        receipt = replay_app.admit_data_agent_event(bundle.event.environment_event_id)
        return replay_app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
            receipt.receipt_id,
        )

    replayed = tuple(replay_bundle(bundle) for bundle in bundles)

    assert replayed == (first_result, second_result)
    assert len(replay_broker.resolved) == 2
    assert replay_transport.requests == []
    assert replay_provider.decision_requests == []
    assert replay_app.store.list_task_ids() == ()
    replay_app.store.close()


@pytest.mark.parametrize("drift", ("profile", "provider", "policy"))
def test_same_id_provider_binding_drift_fails_during_application_construction(
    tmp_path: Path,
    drift: str,
) -> None:
    expected_policy = _provider_policy()
    policy = expected_policy
    profile = expected_policy.provider_invocation.provider_profile
    provider_invocation = expected_policy.provider_invocation
    if drift == "profile":
        profile = profile.model_copy(update={"model_id": "model-relevance-drifted"})
    elif drift == "provider":
        provider_invocation = provider_invocation.model_copy(
            update={"transport": "in-process-drifted"}
        )
    else:
        policy_invocation = _provider_invocation(transport="in-process-drifted")
        policy = _provider_policy(invocation=policy_invocation)
        profile = policy.provider_invocation.provider_profile
    provider = DeterministicProvider(
        text=_provider_draft(RelevanceDisposition.CREATE_TASK),
        invocation_binding=provider_invocation,
    )
    adapter, broker, transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(
            tmp_path / f"reports-{drift}.sqlite3"
        ),
    )
    task_database = tmp_path / f"agent-os-{drift}.sqlite3"

    with pytest.raises(ValueError, match="provider (profile|invocation)"):
        _application(
            task_database=task_database,
            workspace=tmp_path,
            adapter=adapter,
            control=SQLiteSituatedAssessmentStore(
                tmp_path / f"reports-{drift}.sqlite3"
            ),
            provider=provider,
            policy=policy,
            provider_profile=profile,
        )

    task_store = SQLiteTaskEventStore(task_database)
    assert task_store.list_task_ids() == ()
    task_store.close()
    assert broker.resolved == []
    assert transport.requests == []
    assert provider.decision_requests == []
