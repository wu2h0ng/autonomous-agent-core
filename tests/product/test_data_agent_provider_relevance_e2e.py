from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from agent_os_contracts import (
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    ProviderRelevancePolicy,
    RatifiedMandateRef,
    RelevanceDisposition,
    TaskDraftProposal,
)
from agent_os_core import (
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    SQLiteSituatedAssessmentStore,
    SQLiteTaskEventStore,
    SituationalTrustDenied,
    situated_input_binding_digest,
)
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    SQLiteDataAgentReportStateStore,
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


def _context() -> MandateRelevanceContext:
    return MandateRelevanceContext(
        relevance_context_id="mandate-context:data-agent-reports-v1",
        version=1,
        mandate_id="mandate:build-agent-os",
        mandate_version=1,
        mandate_digest="a" * 64,
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
) -> AgentOSApplication:
    return AgentOSApplication(
        database=task_database,
        workspace=workspace,
        data_agent_reports=adapter,
        situational_control=control,
        provider_relevance_policy=policy,
        mandate_relevance_contexts=InMemoryMandateRelevanceContextRegistry(
            (_context(),)
        ),
        relevance_provider=provider,
        relevance_provider_profile=policy.provider_invocation.provider_profile,
        clock=lambda: NOW,
    )


def test_ingest_provider_proposal_offline_replay_and_revoke_survive_restarts(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    situated_database = tmp_path / "situated.sqlite3"
    task_database = tmp_path / "agent-os.sqlite3"
    policy = _provider_policy()
    mandate = _mandate(policy)
    first_adapter, first_broker, first_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    first_provider = _provider(policy)
    first_control = SQLiteSituatedAssessmentStore(
        situated_database,
        mandates=(mandate,),
    )
    first_app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=first_adapter,
        control=first_control,
        provider=first_provider,
        policy=policy,
    )

    bundle = first_app.observe_data_agent_report(TRACE_ID)
    first = first_app.propose_situated_work(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
    )

    assert isinstance(first, TaskDraftProposal)
    assert first.activation_authorized is False
    assert first.external_effects_authorized is False
    assert first_app.store.list_task_ids() == ()
    assert len(first_broker.resolved) == 1
    assert len(first_transport.requests) == 1
    assert len(first_provider.decision_requests) == 1
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

    replay = replay_app.propose_situated_work(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
    )

    assert replay == first
    assert replay_app.store.list_task_ids() == ()
    assert replay_broker.resolved == []
    assert replay_transport.requests == []
    assert replay_provider.decision_requests == []
    input_digest = situated_input_binding_digest(
        mandate,
        _binding(),
        bundle.event,
        bundle.projection,
        policy.assessor_ref(),
    )
    persisted = replay_control.record_by_input_binding(input_digest)
    assert persisted is not None
    replay_app.store.close()

    replay_control.revoke(mandate.mandate_id, expected_epoch=0)
    revoked_adapter, revoked_broker, revoked_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    revoked_provider = _provider(policy)
    revoked_app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=revoked_adapter,
        control=SQLiteSituatedAssessmentStore(situated_database),
        provider=revoked_provider,
        policy=policy,
    )

    with pytest.raises(SituationalTrustDenied, match="not active"):
        revoked_app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
        )

    assert revoked_app.store.list_task_ids() == ()
    assert revoked_broker.resolved == []
    assert revoked_transport.requests == []
    assert revoked_provider.decision_requests == []
    assert replay_control.record_by_input_binding(input_digest) == persisted
    revoked_app.store.close()


def test_unassessed_durable_bundle_is_assessed_once_after_offline_restart(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    policy = _provider_policy()
    first_adapter, first_broker, first_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    bundle = first_adapter.pull(TRACE_ID)
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
        control=SQLiteSituatedAssessmentStore(
            tmp_path / "situated.sqlite3",
            mandates=(_mandate(policy),),
        ),
        provider=provider,
        policy=policy,
    )

    result = app.propose_situated_work(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
    )

    assert isinstance(result, TaskDraftProposal)
    assert restarted_broker.resolved == []
    assert restarted_transport.requests == []
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
        control=SQLiteSituatedAssessmentStore(
            tmp_path / "situated.sqlite3",
            mandates=(_mandate(policy),),
        ),
        provider=provider,
        policy=policy,
    )

    with pytest.raises(SituationalTrustDenied, match="unavailable"):
        app.propose_situated_work(
            foreign_bundle.event.environment_event_id,
            foreign_bundle.projection.projection_id,
        )

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
    control = SQLiteSituatedAssessmentStore(
        tmp_path / f"situated-{corruption}.sqlite3",
        mandates=(_mandate(policy),),
    )
    app = _application(
        task_database=tmp_path / f"agent-os-{corruption}.sqlite3",
        workspace=tmp_path,
        adapter=restarted_adapter,
        control=control,
        provider=provider,
        policy=policy,
    )

    with pytest.raises(DataAgentReportAdapterError):
        app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
        )

    assert restarted_adapter.registry_counts == (0, 0, 0, 0)
    assert broker.resolved == []
    assert transport.requests == []
    assert provider.decision_requests == []
    assert app.store.list_task_ids() == ()
    with sqlite3.connect(tmp_path / f"situated-{corruption}.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM situated_assessment_records"
        ).fetchone()
    assert count == (0,)
    app.store.close()


def test_two_revisions_bind_separate_assessments_and_replay_exactly(
    tmp_path: Path,
) -> None:
    report_database = tmp_path / "reports.sqlite3"
    situated_database = tmp_path / "situated.sqlite3"
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
    mandate = _mandate(policy)
    restarted, broker, transport = _adapter(
        config=feed_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    provider = _provider(policy)
    control = SQLiteSituatedAssessmentStore(
        situated_database,
        mandates=(mandate,),
    )
    app = _application(
        task_database=task_database,
        workspace=tmp_path,
        adapter=restarted,
        control=control,
        provider=provider,
        policy=policy,
    )

    first_result, second_result = tuple(
        app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
        )
        for bundle in bundles
    )

    assert isinstance(first_result, TaskDraftProposal)
    assert isinstance(second_result, TaskDraftProposal)
    assert first_result != second_result
    assert first_result.source_binding_digest != second_result.source_binding_digest
    assert broker.resolved == []
    assert transport.requests == []
    assert len(provider.decision_requests) == 2
    input_digests = tuple(
        situated_input_binding_digest(
            mandate,
            _binding(),
            bundle.event,
            bundle.projection,
            policy.assessor_ref(),
        )
        for bundle in bundles
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
    )
    replayed = tuple(
        replay_app.propose_situated_work(
            bundle.event.environment_event_id,
            bundle.projection.projection_id,
        )
        for bundle in bundles
    )

    assert replayed == (first_result, second_result)
    assert replay_broker.resolved == []
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
        AgentOSApplication(
            database=task_database,
            workspace=tmp_path,
            data_agent_reports=adapter,
            situational_control=SQLiteSituatedAssessmentStore(
                tmp_path / f"situated-{drift}.sqlite3",
                mandates=(_mandate(policy),),
            ),
            provider_relevance_policy=policy,
            mandate_relevance_contexts=InMemoryMandateRelevanceContextRegistry(
                (_context(),)
            ),
            relevance_provider=provider,
            relevance_provider_profile=profile,
            clock=lambda: NOW,
        )

    task_store = SQLiteTaskEventStore(task_database)
    assert task_store.list_task_ids() == ()
    task_store.close()
    assert broker.resolved == []
    assert transport.requests == []
    assert provider.decision_requests == []
