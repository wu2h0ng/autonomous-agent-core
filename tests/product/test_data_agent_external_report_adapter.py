from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, assert_type

import pytest

from agent_os_contracts import (
    CredentialAuthorizationSnapshot,
    CredentialRef,
    CredentialStatus,
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    OperationalProjectionRef,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    RelevanceAssessment,
    RelevanceAssessorRef,
    RelevanceDisposition,
    RelevanceUrgency,
    TaskDraftProposal,
    content_digest,
)
from apps.api_server.app import AgentOSApplication
from tests.product._steward_app import DeferredAdmittedApplication
from apps.api_server.data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportConflict,
    DataAgentReportHttpRequest,
    DataAgentReportHttpResponse,
    DataAgentReportSourceConfig,
    DataAgentReportStateStore,
    SQLiteDataAgentReportStateStore,
)
from agent_os_core import (
    SituationalScopeMismatch,
    situated_input_binding_digest,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
TRACE_ID = "trace-123"
SECRET = "secret-value-that-must-not-leak"


def _report_bytes(
    *,
    trace_id: str = TRACE_ID,
    audience: str = "external",
    authority_payload: bool = False,
) -> bytes:
    payload: dict[str, object] = {
        "trace_id": trace_id,
        "audience": audience,
        "user_result": {
            "artifact_id": "artifact:data-result",
            "kind": "data_agent_result",
            "title": "GMV analysis result",
            "trace_id": trace_id,
            "evidence_chain_id": "evidence:data-result",
            "question": "What changed?",
            "metric_name": "gmv",
            "audience": audience,
            "redaction": {
                "audience": audience,
                "applied": True,
                "data_classification": "external",
                "redacted_fields": ["internal_reasoning"],
            },
            "action_proposal_id": "data-action-proposal:1",
            "analysis": {
                "summary": "One governed row was returned.",
                "confidence": 0.5,
                "confidence_inputs": None,
                "limitations": ["Source freshness is unknown."],
                "row_count": 1,
                "evidence_chain_id": "evidence:data-result",
            },
            "report": {
                "title": "Evidence-backed report",
                "evidence_cards": [],
                "sections": [],
            },
            "dashboard": {"title": "GMV dashboard", "widgets": []},
            "decision": {
                "recommendation": "Review the result.",
                "reason": "A governed observation exists.",
                "expected_impact": "No automatic effect.",
                "risk_level": "R3",
                "action_proposal_id": "data-action-proposal:1",
                "approval_required": True,
                "approver_role": "Business Owner",
                "confidence": 0.5,
                "knowledge_context_refs": [],
                "knowledge_context_rationale": [],
                "alternatives": [],
                "single_option_rationale": None,
            },
            "business_action": {
                "connector_name": "action_record",
                "action_type": "execute",
                "risk_level": "R3",
                "approval_required": True,
                "approver_role": "Business Owner",
                "trace_id": trace_id,
                "evidence_chain_id": "evidence:data-result",
                "approval_id": "approval:data-only",
                "operation_id": None,
                "status": "PROPOSED",
                "row_count": 1,
            },
        },
    }
    if authority_payload:
        payload["workflow"] = {"execute": True}
        payload["capability_grant"] = {"scope": "workspace:write"}
        payload["task"] = {"activate": True}
    return json.dumps(payload, separators=(",", ":"), sort_keys=False).encode()


class _Broker:
    def __init__(self) -> None:
        self.resolved: list[CredentialRef] = []

    def resolve(self, credential: CredentialRef) -> str:
        self.resolved.append(credential)
        return SECRET


class _AuthorizationReader:
    def __init__(self, snapshot: CredentialAuthorizationSnapshot | None) -> None:
        self.snapshot = snapshot
        self.resolved: list[str] = []

    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        self.resolved.append(credential_ref_id)
        return self.snapshot


class _FailingAuthorizationReader:
    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        del credential_ref_id
        raise RuntimeError("credential authority unavailable")


class _Transport:
    def __init__(
        self,
        response: DataAgentReportHttpResponse
        | Callable[[DataAgentReportHttpRequest], DataAgentReportHttpResponse],
    ) -> None:
        self.response = response
        self.requests: list[DataAgentReportHttpRequest] = []

    def fetch(self, request: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse:
        self.requests.append(request)
        if callable(self.response):
            return self.response(request)
        return self.response


def _credential(**updates: object) -> CredentialRef:
    values: dict[str, Any] = {
        "credential_ref_id": "credential:data-agent-report",
        "owner_principal_id": "user:local",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "provider_id": "data-agent-external-report",
        "resolver_key": "DATA_AGENT_EXTERNAL_REPORT_KEY",
        "scopes": (
            "reports:read",
            "data-agent-origin:http://127.0.0.1:8765",
            "data-agent-tenant:data-tenant-1",
        ),
        "status": CredentialStatus.ACTIVE,
        "created_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(updates)
    return CredentialRef(**values)


def _authorization_snapshot(
    credential: CredentialRef, **updates: object
) -> CredentialAuthorizationSnapshot:
    values: dict[str, Any] = {
        "credential_ref_id": credential.credential_ref_id,
        "credential_ref_digest": content_digest(credential),
        "owner_principal_id": credential.owner_principal_id,
        "tenant_id": credential.tenant_id,
        "workspace_id": credential.workspace_id,
        "provider_id": credential.provider_id,
        "scopes": credential.scopes,
        "status": credential.status,
        "created_at": credential.created_at,
        "expires_at": credential.expires_at,
    }
    values.update(updates)
    return CredentialAuthorizationSnapshot(**values)


def _config(**updates: object) -> DataAgentReportSourceConfig:
    values: dict[str, Any] = {
        "source_id": "source:data-agent-local",
        "base_url": "http://127.0.0.1:8765",
        "source_tenant_id": "data-tenant-1",
        "credential": _credential(),
        "principal_id": "user:local",
        "target_tenant_id": "tenant:local",
        "target_workspace_id": "workspace:local",
        "mandate_id": "mandate:build-agent-os",
        "environment_binding_id": "binding:data-agent-reports",
        "scope_ref": "mission:agent-os/product",
        "allow_loopback_http": True,
        "timeout_seconds": 3,
        "max_response_bytes": 16_384,
        "freshness_seconds": 300,
    }
    values.update(updates)
    return DataAgentReportSourceConfig(**values)


def _response(
    body: bytes | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    final_url: str | None = None,
) -> DataAgentReportHttpResponse:
    return DataAgentReportHttpResponse(
        status_code=status_code,
        headers=headers
        or {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "identity",
        },
        body=body if body is not None else _report_bytes(),
        final_url=final_url
        or "http://127.0.0.1:8765/runs/trace-123/report?audience=external",
    )


def _feed_bytes(
    events: list[dict[str, object]],
    *,
    next_cursor: str | None,
    has_more: bool = False,
) -> bytes:
    return json.dumps(
        {
            "schema_version": "external-report-events.v1",
            "audience": "external",
            "events": events,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _feed_event(cursor: str, report_bytes: bytes | None = None) -> dict[str, object]:
    report = json.loads(report_bytes or _report_bytes())
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return {
        "cursor": cursor,
        "trace_id": report["trace_id"],
        "content_sha256": hashlib.sha256(canonical).hexdigest(),
        "report": report,
    }


def _adapter(
    *,
    response: DataAgentReportHttpResponse | None = None,
    config: DataAgentReportSourceConfig | None = None,
    state_store: DataAgentReportStateStore | None = None,
    now: datetime = NOW,
) -> tuple[DataAgentReportAdapter, _Broker, _Transport]:
    broker = _Broker()
    transport = _Transport(response or _response())
    adapter = DataAgentReportAdapter(
        config or _config(),
        credential_broker=broker,
        transport=transport,
        state_store=state_store,
        clock=lambda: now,
    )
    return adapter, broker, transport


def _binding() -> EnvironmentBindingAuthorization:
    return EnvironmentBindingAuthorization(
        environment_binding_id="binding:data-agent-reports",
        version=1,
        binding_digest="b" * 64,
    )


def _assessor_ref() -> RelevanceAssessorRef:
    return RelevanceAssessorRef(
        assessor_id="assessor:data-agent-report-v0",
        version=1,
        policy_digest="c" * 64,
    )


def _mandate() -> RatifiedMandateRef:
    return RatifiedMandateRef(
        mandate_id="mandate:build-agent-os",
        version=1,
        mandate_digest="a" * 64,
        ratification_receipt_id="ratification:test",
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
        relevance_assessor=_assessor_ref(),
    )


class _ReportAssessor:
    @property
    def ref(self) -> RelevanceAssessorRef:
        return _assessor_ref()

    def assess(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        *,
        assessed_at: datetime,
        working_set: Any = None,
    ) -> RelevanceAssessment:
        return RelevanceAssessment(
            assessment_id="assessment:data-report-1",
            environment_event_id=event.environment_event_id,
            event_observation_digest=event.observation.content_digest,
            projection_id=projection.projection_id,
            projection_digest=projection.projection_artifact.content_digest,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.version,
            mandate_digest=mandate.mandate_digest,
            environment_binding_id=binding.environment_binding_id,
            environment_binding_version=binding.version,
            environment_binding_digest=binding.binding_digest,
            correction_epoch=mandate.correction_epoch,
            assessor=self.ref,
            input_binding_digest=situated_input_binding_digest(
                mandate,
                binding,
                event,
                projection,
                self.ref,
                working_set,
            ),
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            disposition=RelevanceDisposition.CREATE_TASK,
            uncertainty_summary="The external report is grounded but needs bounded review.",
            urgency=RelevanceUrgency.MEDIUM,
            expected_loss_of_delay="A material result may go unreviewed.",
            attention_budget_seconds=600,
            rationale="A new trusted external report may affect the product commitment.",
            evidence_ids=tuple(
                sorted(
                    {
                        *(item.evidence_id for item in event.evidence),
                        *(item.evidence_id for item in projection.evidence),
                    }
                )
            ),
            proposed_goal_statement="Review the external report without activating work.",
            assessed_at=assessed_at,
        )


def test_security_envelope_enters_application_as_trusted_proposal_without_task_write(
    tmp_path,
) -> None:
    adapter, broker, transport = _adapter(
        now=NOW - timedelta(seconds=1),
        state_store=SQLiteDataAgentReportStateStore(
            tmp_path / "data-agent-state.sqlite3"
        ),
    )
    app = DeferredAdmittedApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
        principal=PrincipalIdentity(
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=NOW - timedelta(minutes=1),
        ),
        trust=adapter,
        data_agent_reports=adapter,
        control=SQLiteSituatedAssessmentStore(
            tmp_path / "situated.sqlite3", mandates=(_mandate(),)
        ),
        assessor=_ReportAssessor(),
        clock=lambda: NOW,
    )
    bundle = app.observe_data_agent_report(TRACE_ID)
    assert (bundle.event.tenant_id, bundle.event.workspace_id) == (
        app.principal.tenant_id,
        app.principal.workspace_id,
    )

    result = app.propose_situated_work(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
    )

    assert isinstance(result, TaskDraftProposal)
    assert result.activation_authorized is False
    assert result.external_effects_authorized is False
    assert app.store.list_task_ids() == ()
    assert len(broker.resolved) == 1
    assert transport.requests[0].headers == {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "X-API-Key": SECRET,
        "X-Tenant-Id": "data-tenant-1",
    }
    assert transport.requests[0].url.endswith(
        "/runs/trace-123/report?audience=external"
    )


def test_application_restart_rehydrates_trusted_bundle_by_ids_without_network_or_task_write(
    tmp_path,
) -> None:
    report_database = tmp_path / "data-agent-state.sqlite3"
    application_database = tmp_path / "agent-os.sqlite3"
    situated_database = tmp_path / "situated.sqlite3"
    first_adapter, _, first_transport = _adapter(
        now=NOW - timedelta(seconds=1),
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    first_app = DeferredAdmittedApplication(
        database=application_database,
        workspace=tmp_path,
        principal=PrincipalIdentity(
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=NOW - timedelta(minutes=1),
        ),
        trust=first_adapter,
        data_agent_reports=first_adapter,
        control=SQLiteSituatedAssessmentStore(
            situated_database, mandates=(_mandate(),)
        ),
        assessor=_ReportAssessor(),
        clock=lambda: NOW,
    )
    bundle = first_app.observe_data_agent_report(TRACE_ID)
    assert len(first_transport.requests) == 1

    restarted_adapter, restarted_broker, restarted_transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(report_database),
    )
    restarted_app = DeferredAdmittedApplication(
        database=application_database,
        workspace=tmp_path,
        principal=PrincipalIdentity(
            principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=NOW - timedelta(minutes=1),
        ),
        trust=restarted_adapter,
        data_agent_reports=restarted_adapter,
        control=SQLiteSituatedAssessmentStore(situated_database),
        assessor=_ReportAssessor(),
        clock=lambda: NOW,
    )

    result = restarted_app.propose_situated_work(
        bundle.event.environment_event_id,
        bundle.projection.projection_id,
    )

    assert isinstance(result, TaskDraftProposal)
    assert result.activation_authorized is False
    assert result.external_effects_authorized is False
    assert restarted_app.store.list_task_ids() == ()
    assert restarted_broker.resolved == []
    assert restarted_transport.requests == []
    assert (
        restarted_adapter.resolve_event(bundle.event.environment_event_id)
        == bundle.event
    )
    assert (
        restarted_adapter.resolve_projection(bundle.projection.projection_id)
        == bundle.projection
    )
    assert restarted_adapter.resolve_artifact(bundle.artifact.artifact_id) == (
        bundle.artifact,
        _report_bytes(),
    )
    assert (
        restarted_adapter.resolve_evidence(bundle.evidence.evidence_id)
        == bundle.evidence
    )


@pytest.mark.parametrize(
    "object_kind",
    ["artifact", "evidence", "event", "projection"],
)
def test_each_trusted_resolver_lazily_rehydrates_after_restart(
    tmp_path,
    object_kind: str,
) -> None:
    database = tmp_path / "resolver-restart.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundle = first.pull(TRACE_ID)
    expected_artifact = first.resolve_artifact(bundle.artifact.artifact_id)

    restarted, broker, transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    if object_kind == "artifact":
        resolved: object = restarted.resolve_artifact(bundle.artifact.artifact_id)
        expected: object = expected_artifact
    elif object_kind == "evidence":
        resolved = restarted.resolve_evidence(bundle.evidence.evidence_id)
        expected = bundle.evidence
    elif object_kind == "event":
        resolved = restarted.resolve_event(bundle.event.environment_event_id)
        expected = bundle.event
    else:
        resolved = restarted.resolve_projection(bundle.projection.projection_id)
        expected = bundle.projection

    assert resolved == expected
    assert restarted.registry_counts == (2, 2, 1, 1)
    assert broker.resolved == []
    assert transport.requests == []


def test_restart_namespace_isolation_does_not_rehydrate_foreign_bundle(
    tmp_path,
) -> None:
    database = tmp_path / "namespace-isolation.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundle = first.pull(TRACE_ID)
    isolated, broker, transport = _adapter(
        config=_config(
            mandate_id="mandate:isolated",
            environment_binding_id="binding:isolated",
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )

    assert isolated.resolve_event(bundle.event.environment_event_id) is None
    assert isolated.resolve_projection(bundle.projection.projection_id) is None
    assert isolated.resolve_artifact(bundle.artifact.artifact_id) is None
    assert isolated.resolve_evidence(bundle.evidence.evidence_id) is None
    assert isolated.registry_counts == (0, 0, 0, 0)
    assert broker.resolved == []
    assert transport.requests == []


def test_passive_poll_discovers_immutable_report_without_trace_id(tmp_path) -> None:
    cursor = "opaque-cursor-1"
    feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)
    adapter, broker, transport = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "passive.sqlite3"),
    )

    result = adapter.poll_once(limit=1)

    assert len(result.bundles) == 1
    assert result.next_cursor == cursor
    assert result.has_more is False
    assert adapter.feed_cursor == cursor
    assert len(broker.resolved) == 1
    assert len(transport.requests) == 1
    assert transport.requests[0].headers == {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "X-API-Key": SECRET,
    }
    assert transport.requests[0].url.endswith("/external/report-events?limit=1")


def test_passive_poll_preserves_two_immutable_revisions_of_same_trace(tmp_path) -> None:
    first = _feed_event("opaque-cursor-1")
    second = _feed_event(
        "opaque-cursor-2",
        _report_bytes(authority_payload=True),
    )
    feed = _feed_bytes([first, second], next_cursor="opaque-cursor-2")
    adapter, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "revisions.sqlite3"),
    )

    result = adapter.poll_once(limit=2)

    assert len(result.bundles) == 2
    assert result.bundles[0].artifact.content_digest == first["content_sha256"]
    assert result.bundles[1].artifact.content_digest == second["content_sha256"]
    assert (
        result.bundles[0].artifact.artifact_id != result.bundles[1].artifact.artifact_id
    )


def test_restart_rehydrates_two_immutable_revisions_without_network(tmp_path) -> None:
    database = tmp_path / "revision-restart.sqlite3"
    first_event = _feed_event("opaque-cursor-1")
    second_event = _feed_event(
        "opaque-cursor-2",
        _report_bytes(authority_payload=True),
    )
    feed = _feed_bytes(
        [first_event, second_event],
        next_cursor="opaque-cursor-2",
    )
    first, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundles = first.poll_once(limit=2).bundles

    restarted, broker, transport = _adapter(
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )

    assert tuple(
        restarted.resolve_event(bundle.event.environment_event_id) for bundle in bundles
    ) == tuple(bundle.event for bundle in bundles)
    assert tuple(
        restarted.resolve_projection(bundle.projection.projection_id)
        for bundle in bundles
    ) == tuple(bundle.projection for bundle in bundles)
    assert restarted.registry_counts == (4, 4, 2, 2)
    assert broker.resolved == []
    assert transport.requests == []


def test_passive_poll_digest_failure_does_not_advance_cursor(tmp_path) -> None:
    event = _feed_event("opaque-cursor-1")
    event["content_sha256"] = "0" * 64
    feed = _feed_bytes([event], next_cursor="opaque-cursor-1")
    adapter, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "digest.sqlite3"),
    )

    with pytest.raises(DataAgentReportAdapterError, match="digest"):
        adapter.poll_once(limit=1)

    assert adapter.feed_cursor is None
    assert adapter.registry_counts == (0, 0, 0, 0)


def test_passive_poll_reuses_durable_cursor_after_restart(tmp_path) -> None:
    database = tmp_path / "restart-cursor.sqlite3"
    cursor = "opaque-cursor-1"
    first_feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)
    first, _, _ = _adapter(
        response=_response(
            first_feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    first.poll_once(limit=1)
    empty_feed = _feed_bytes([], next_cursor=cursor)
    restarted, _, transport = _adapter(
        response=_response(
            empty_feed,
            final_url=(
                f"http://127.0.0.1:8765/external/report-events?after={cursor}&limit=1"
            ),
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )

    result = restarted.poll_once(limit=1)

    assert result.bundles == ()
    assert restarted.feed_cursor == cursor
    assert transport.requests[0].url.endswith(
        f"/external/report-events?after={cursor}&limit=1"
    )


def test_passive_poll_rejects_non_progressing_page(tmp_path) -> None:
    cursor = "opaque-cursor-1"
    feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)

    def response_for(
        request: DataAgentReportHttpRequest,
    ) -> DataAgentReportHttpResponse:
        return _response(feed, final_url=request.url)

    broker = _Broker()
    transport = _Transport(response_for)
    adapter = DataAgentReportAdapter(
        _config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        credential_broker=broker,
        transport=transport,
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "progress.sqlite3"),
        clock=lambda: NOW,
    )
    adapter.poll_once(limit=1)

    with pytest.raises(DataAgentReportAdapterError, match="progress"):
        adapter.poll_once(limit=1)

    assert adapter.feed_cursor == cursor
    assert len(transport.requests) == 2


def test_passive_poll_rejects_cycle_to_previously_consumed_cursor(tmp_path) -> None:
    feeds = {
        None: _feed_bytes([_feed_event("cursor-1")], next_cursor="cursor-1"),
        "cursor-1": _feed_bytes(
            [_feed_event("cursor-2", _report_bytes(authority_payload=True))],
            next_cursor="cursor-2",
        ),
        "cursor-2": _feed_bytes([_feed_event("cursor-1")], next_cursor="cursor-1"),
    }

    def response_for(
        request: DataAgentReportHttpRequest,
    ) -> DataAgentReportHttpResponse:
        after = None
        if "after=" in request.url:
            after = request.url.split("after=", 1)[1].split("&", 1)[0]
        return _response(feeds[after], final_url=request.url)

    adapter = DataAgentReportAdapter(
        _config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        credential_broker=_Broker(),
        transport=_Transport(response_for),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "cycle.sqlite3"),
        clock=lambda: NOW,
    )
    adapter.poll_once(limit=1)
    adapter.poll_once(limit=1)

    with pytest.raises(DataAgentReportConflict, match="consumed"):
        adapter.poll_once(limit=1)

    assert adapter.feed_cursor == "cursor-2"


def test_application_passive_poll_never_creates_task(tmp_path) -> None:
    cursor = "opaque-cursor-1"
    feed = _feed_bytes([_feed_event(cursor)], next_cursor=cursor)
    adapter, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=1",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "app-feed.sqlite3"),
    )
    app = AgentOSApplication(
        database=tmp_path / "app.sqlite3",
        workspace=tmp_path,
        data_agent_reports=adapter,
        clock=lambda: NOW,
    )

    result = app.poll_data_agent_reports_once(limit=1)

    assert len(result.bundles) == 1
    assert app.store.list_task_ids() == ()


def test_feed_validation_returns_narrowed_trace_and_report_types() -> None:
    cursor = "opaque-cursor-1"
    payload = json.loads(_feed_bytes([_feed_event(cursor)], next_cursor=cursor))

    events, next_cursor, has_more = DataAgentReportAdapter._validate_feed_contract(
        payload,
        prior_cursor=None,
        limit=1,
    )

    event = events[0]
    assert_type(event["trace_id"], str)
    assert_type(event["report"], dict[str, object])
    assert next_cursor == cursor
    assert has_more is False


def test_digest_is_sha256_of_exact_stored_bytes() -> None:
    exact = b'{"trace_id":"trace-123", "audience":"external","user_result":{"trace_id":"trace-123","audience":"external","redaction":{"audience":"external","applied":true},"business_action":{"trace_id":"trace-123"}}}\n'
    adapter, _, _ = _adapter(response=_response(exact))

    bundle = adapter.pull(TRACE_ID)
    resolved = adapter.resolve_artifact(bundle.artifact.artifact_id)

    assert bundle.artifact.content_digest == hashlib.sha256(exact).hexdigest()
    assert resolved == (bundle.artifact, exact)


def test_pull_surface_accepts_only_trace_id_and_uses_frozen_scope() -> None:
    signature = inspect.signature(DataAgentReportAdapter.pull)
    assert tuple(signature.parameters) == ("self", "trace_id")
    adapter, _, _ = _adapter()

    bundle = adapter.pull(TRACE_ID)

    assert bundle.event.tenant_id == "tenant:local"
    assert bundle.event.workspace_id == "workspace:local"
    assert bundle.event.mandate_id == "mandate:build-agent-os"
    assert bundle.event.environment_binding_id == "binding:data-agent-reports"


@pytest.mark.parametrize(
    "trace_id",
    ["../escape", "nested/path", "encoded%2fpath", " leading", "line\nbreak"],
)
def test_trace_id_cannot_escape_fixed_report_path(trace_id: str) -> None:
    adapter, broker, transport = _adapter()

    with pytest.raises(DataAgentReportAdapterError, match="trace_id"):
        adapter.pull(trace_id)

    assert broker.resolved == []
    assert transport.requests == []


def test_rejects_unapproved_or_non_https_origin_before_resolving_credential() -> None:
    broker = _Broker()
    with pytest.raises(DataAgentReportAdapterError, match="HTTPS"):
        DataAgentReportAdapter(
            replace(
                _config(),
                base_url="http://example.com",
                allow_loopback_http=False,
            ),
            credential_broker=broker,
            transport=_Transport(_response()),
            clock=lambda: NOW,
        )
    assert broker.resolved == []


def test_credential_ref_must_match_frozen_tenant_origin_and_external_scope() -> None:
    bad_credentials = (
        _credential(scopes=("reports:read",)),
        _credential(scopes=("reports:read", "data-agent-tenant:other")),
        _credential(provider_id="generic-api-key"),
        _credential(tenant_id="tenant:other"),
    )
    for credential in bad_credentials:
        with pytest.raises(DataAgentReportAdapterError, match="credential"):
            DataAgentReportAdapter(
                _config(credential=credential),
                credential_broker=_Broker(),
                transport=_Transport(_response()),
                clock=lambda: NOW,
            )

    with pytest.raises(DataAgentReportAdapterError, match="tenant id"):
        DataAgentReportAdapter(
            _config(source_tenant_id="tenant\r\nX-Evil: injected"),
            credential_broker=_Broker(),
            transport=_Transport(_response()),
            clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    "current_authorization",
    [
        None,
        _authorization_snapshot(_credential(), status=CredentialStatus.REVOKED),
        _authorization_snapshot(_credential(), expires_at=NOW),
        _authorization_snapshot(_credential(), credential_ref_digest="f" * 64),
        _authorization_snapshot(_credential(), owner_principal_id="user:other"),
        _authorization_snapshot(_credential(), provider_id="provider:other"),
        _authorization_snapshot(_credential(), scopes=("reports:read",)),
    ],
    ids=(
        "unavailable",
        "revoked",
        "expired",
        "rotated",
        "principal-drift",
        "provider-drift",
        "scope-drift",
    ),
)
def test_live_credential_preflight_denies_before_secret_or_network(
    current_authorization: CredentialAuthorizationSnapshot | None,
) -> None:
    credential = _credential()
    broker = _Broker()
    transport = _Transport(_response())
    authorizations = _AuthorizationReader(current_authorization)
    adapter = DataAgentReportAdapter(
        _config(credential=credential),
        credential_broker=broker,
        credential_authorizations=authorizations,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(DataAgentReportAdapterError, match="credential"):
        adapter.pull(TRACE_ID)

    assert authorizations.resolved == [credential.credential_ref_id]
    assert broker.resolved == []
    assert transport.requests == []


def test_live_credential_preflight_rechecks_authority_after_startup() -> None:
    credential = _credential()
    broker = _Broker()
    transport = _Transport(_response())
    authorizations = _AuthorizationReader(_authorization_snapshot(credential))
    adapter = DataAgentReportAdapter(
        _config(credential=credential),
        credential_broker=broker,
        credential_authorizations=authorizations,
        transport=transport,
        clock=lambda: NOW,
    )

    adapter.pull(TRACE_ID)
    authorizations.snapshot = _authorization_snapshot(
        credential, status=CredentialStatus.REVOKED
    )

    with pytest.raises(DataAgentReportAdapterError, match="credential"):
        adapter.pull(TRACE_ID)

    assert authorizations.resolved == [
        credential.credential_ref_id,
        credential.credential_ref_id,
    ]
    assert len(broker.resolved) == 1
    assert len(transport.requests) == 1


@pytest.mark.parametrize("reader_kind", ("revoked", "exception"))
def test_feed_live_credential_preflight_denies_before_secret_or_network(
    reader_kind: str,
) -> None:
    credential = _credential(
        scopes=(
            "reports:read",
            "report-events:read",
            "data-agent-origin:http://127.0.0.1:8765",
            "data-agent-tenant:data-tenant-1",
        )
    )
    authorizations = (
        _AuthorizationReader(
            _authorization_snapshot(credential, status=CredentialStatus.REVOKED)
        )
        if reader_kind == "revoked"
        else _FailingAuthorizationReader()
    )
    broker = _Broker()
    transport = _Transport(_response())
    adapter = DataAgentReportAdapter(
        _config(credential=credential),
        credential_broker=broker,
        credential_authorizations=authorizations,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(DataAgentReportAdapterError, match="credential"):
        adapter.poll_once(limit=1)

    assert broker.resolved == []
    assert transport.requests == []


def test_redirect_or_final_origin_change_is_rejected_without_registration() -> None:
    adapter, _, _ = _adapter(
        response=_response(
            status_code=302,
            headers={"Location": "https://attacker.example/steal"},
        )
    )
    with pytest.raises(DataAgentReportAdapterError, match="status"):
        adapter.pull(TRACE_ID)
    assert adapter.registry_counts == (0, 0, 0, 0)

    adapter, _, _ = _adapter(
        response=_response(final_url="https://attacker.example/steal")
    )
    with pytest.raises(DataAgentReportAdapterError, match="destination"):
        adapter.pull(TRACE_ID)
    assert adapter.registry_counts == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response(status_code=404), "status"),
        (_response(headers={"Content-Type": "text/html"}), "media type"),
        (
            _response(
                headers={
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                }
            ),
            "encoding",
        ),
        (_response(body=b"x" * 20_000), "size"),
    ],
)
def test_invalid_http_response_leaves_registry_empty(
    response: DataAgentReportHttpResponse, message: str
) -> None:
    adapter, _, _ = _adapter(response=response)

    with pytest.raises(DataAgentReportAdapterError, match=message):
        adapter.pull(TRACE_ID)

    assert adapter.registry_counts == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "body",
    [
        b'{"trace_id":"trace-123","trace_id":"trace-other","audience":"external","user_result":{}}',
        _report_bytes(trace_id="trace-other"),
        _report_bytes(audience="internal"),
        b'{"trace_id":"trace-123","audience":"external","user_result":{"trace_id":"trace-123","audience":"external","redaction":{"audience":"internal","applied":true},"business_action":{"trace_id":"trace-123"}}}',
        b'{"trace_id":"trace-123","audience":"external","user_result":{"trace_id":"trace-123","audience":"external","redaction":{"audience":"external","applied":false},"business_action":{"trace_id":"trace-123"}}}',
        b'{"trace_id":"trace-123","audience":"external","user_result":{"trace_id":"trace-123","audience":"external","redaction":{"audience":"external","applied":true},"business_action":{"trace_id":"trace-other"}}}',
        b'{"trace_id":"trace-123","audience":"external","score":NaN,"user_result":{"trace_id":"trace-123","audience":"external","redaction":{"audience":"external","applied":true},"business_action":{"trace_id":"trace-123"}}}',
    ],
)
def test_malformed_internal_or_substituted_report_is_atomic_failure(
    body: bytes,
) -> None:
    adapter, _, _ = _adapter(response=_response(body))

    with pytest.raises(DataAgentReportAdapterError):
        adapter.pull(TRACE_ID)

    assert adapter.registry_counts == (0, 0, 0, 0)


def test_authority_shaped_report_remains_opaque() -> None:
    body = _report_bytes(authority_payload=True)
    adapter, _, _ = _adapter(response=_response(body))

    bundle = adapter.pull(TRACE_ID)
    projection_bytes = adapter.resolve_artifact(
        bundle.projection.projection_artifact.artifact_id
    )

    assert adapter.resolve_artifact(bundle.artifact.artifact_id) == (
        bundle.artifact,
        body,
    )
    assert projection_bytes is not None
    assert b"workflow" not in projection_bytes[1]
    assert b"capability_grant" not in projection_bytes[1]
    assert b"activate" not in projection_bytes[1]
    assert not hasattr(bundle, "task")
    assert not hasattr(bundle, "grant")
    assert not hasattr(bundle, "approval")


def test_durable_first_seen_state_makes_cross_process_replay_fully_stable(
    tmp_path,
) -> None:
    database = tmp_path / "data-agent-observations.sqlite3"
    first_store = SQLiteDataAgentReportStateStore(database)
    second_store = SQLiteDataAgentReportStateStore(database)
    first = DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=first_store,
        clock=lambda: NOW - timedelta(seconds=10),
    )
    second = DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=second_store,
        clock=lambda: NOW - timedelta(seconds=2),
    )

    first_bundle = first.pull(TRACE_ID)
    second_bundle = second.pull(TRACE_ID)

    assert second_bundle == first_bundle
    assert second_bundle.event.occurred_at == NOW - timedelta(seconds=10)


def test_same_adapter_same_trace_same_bytes_replays_exact_bundle() -> None:
    adapter, _, _ = _adapter()

    first = adapter.pull(TRACE_ID)
    replay = adapter.pull(TRACE_ID)

    assert replay == first


def test_same_trace_different_bytes_is_conflict_not_overwrite() -> None:
    first_response = _response()
    changed = _response(_report_bytes(authority_payload=True))
    calls = 0

    def alternating(_: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse:
        nonlocal calls
        calls += 1
        return first_response if calls == 1 else changed

    broker = _Broker()
    transport = _Transport(alternating)
    adapter = DataAgentReportAdapter(
        _config(), credential_broker=broker, transport=transport, clock=lambda: NOW
    )
    first = adapter.pull(TRACE_ID)

    with pytest.raises(DataAgentReportConflict):
        adapter.pull(TRACE_ID)

    assert adapter.resolve_artifact(first.artifact.artifact_id) == (
        first.artifact,
        first_response.body,
    )
    assert adapter.registry_counts == (2, 2, 1, 1)


def test_secret_never_appears_in_safe_error_or_registered_contracts() -> None:
    def leaking_transport(_: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse:
        raise RuntimeError(f"request failed with {SECRET}")

    broker = _Broker()
    adapter = DataAgentReportAdapter(
        _config(),
        credential_broker=broker,
        transport=_Transport(leaking_transport),
        clock=lambda: NOW,
    )

    with pytest.raises(DataAgentReportAdapterError) as exc_info:
        adapter.pull(TRACE_ID)

    assert SECRET not in str(exc_info.value)
    assert adapter.registry_counts == (0, 0, 0, 0)


def test_response_body_containing_resolved_credential_is_rejected() -> None:
    payload = json.loads(_report_bytes())
    payload["debug_echo"] = SECRET
    body = json.dumps(payload, separators=(",", ":")).encode()
    adapter, _, _ = _adapter(response=_response(body))

    with pytest.raises(DataAgentReportAdapterError, match="credential material"):
        adapter.pull(TRACE_ID)

    assert adapter.registry_counts == (0, 0, 0, 0)


def test_json_escaped_credential_echo_is_rejected_after_strict_parse() -> None:
    escaped = "".join(f"\\u{ord(character):04x}" for character in SECRET)
    body = _report_bytes()[:-1] + f',"debug_echo":"{escaped}"}}'.encode()
    assert SECRET.encode() not in body
    adapter, _, _ = _adapter(response=_response(body))

    with pytest.raises(DataAgentReportAdapterError, match="credential material"):
        adapter.pull(TRACE_ID)

    assert adapter.registry_counts == (0, 0, 0, 0)


def test_application_rejects_report_adapter_bound_to_other_principal(tmp_path) -> None:
    adapter, _, transport = _adapter()
    other = PrincipalIdentity(
        principal_id="user:other",
        tenant_id="tenant:other",
        workspace_id="workspace:other",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )

    with pytest.raises(SituationalScopeMismatch, match="scope does not match"):
        AgentOSApplication(
            database=tmp_path / "other.sqlite3",
            workspace=tmp_path,
            principal=other,
            data_agent_reports=adapter,
            clock=lambda: NOW,
        )

    assert transport.requests == []


def test_application_requires_durable_first_seen_state(tmp_path) -> None:
    adapter, _, _ = _adapter()

    with pytest.raises(ValueError, match="durable first-seen"):
        AgentOSApplication(
            database=tmp_path / "agent-os.sqlite3",
            workspace=tmp_path,
            data_agent_reports=adapter,
            clock=lambda: NOW,
        )


def test_default_transport_performs_real_local_read_only_http_round_trip() -> None:
    received: dict[str, str] = {}
    body = _report_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received["path"] = self.path
            received["api_key"] = self.headers.get("X-API-Key", "")
            received["tenant"] = self.headers.get("X-Tenant-Id", "")
            received["encoding"] = self.headers.get("Accept-Encoding", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "identity")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    credential = _credential(
        scopes=(
            "reports:read",
            f"data-agent-origin:{origin}",
            "data-agent-tenant:data-tenant-1",
        )
    )
    try:
        adapter = DataAgentReportAdapter(
            _config(base_url=origin, credential=credential),
            credential_broker=_Broker(),
            clock=lambda: NOW,
        )
        bundle = adapter.pull(TRACE_ID)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert bundle.artifact.content_digest == hashlib.sha256(body).hexdigest()
    assert received == {
        "path": "/runs/trace-123/report?audience=external",
        "api_key": SECRET,
        "tenant": "data-tenant-1",
        "encoding": "identity",
    }


def test_default_transport_does_not_follow_redirect_or_forward_api_key() -> None:
    attacker_requests: list[str] = []

    class AttackerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            attacker_requests.append(self.headers.get("X-API-Key", ""))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    attacker = ThreadingHTTPServer(("127.0.0.1", 0), AttackerHandler)
    attacker_thread = threading.Thread(target=attacker.serve_forever, daemon=True)
    attacker_thread.start()
    attacker_url = f"http://127.0.0.1:{attacker.server_port}/steal"

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", attacker_url)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    origin = f"http://127.0.0.1:{source.server_port}"
    credential = _credential(
        scopes=(
            "reports:read",
            f"data-agent-origin:{origin}",
            "data-agent-tenant:data-tenant-1",
        )
    )
    try:
        adapter = DataAgentReportAdapter(
            _config(base_url=origin, credential=credential),
            credential_broker=_Broker(),
            clock=lambda: NOW,
        )
        with pytest.raises(DataAgentReportAdapterError, match="status"):
            adapter.pull(TRACE_ID)
    finally:
        source.shutdown()
        source.server_close()
        source_thread.join(timeout=2)
        attacker.shutdown()
        attacker.server_close()
        attacker_thread.join(timeout=2)

    assert attacker_requests == []
    assert adapter.registry_counts == (0, 0, 0, 0)


def test_slow_drip_exceeding_total_deadline_fails_without_registration() -> None:
    body = _report_bytes()

    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "identity")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for chunk in (body[:10], body[10:20], body[20:]):
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                threading.Event().wait(0.7)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    credential = _credential(
        scopes=(
            "reports:read",
            f"data-agent-origin:{origin}",
            "data-agent-tenant:data-tenant-1",
        )
    )
    adapter = DataAgentReportAdapter(
        _config(
            base_url=origin,
            credential=credential,
            timeout_seconds=1,
        ),
        credential_broker=_Broker(),
        clock=lambda: NOW,
    )
    try:
        with pytest.raises(DataAgentReportAdapterError, match="transport failed"):
            adapter.pull(TRACE_ID)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert adapter.registry_counts == (0, 0, 0, 0)


def test_slow_response_headers_are_bounded_by_total_wall_clock_deadline() -> None:
    raw_response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Encoding: identity\r\n\r\n" + _report_bytes()
    )

    class SlowHeaderHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            for offset in range(0, len(raw_response), 8):
                try:
                    self.connection.sendall(raw_response[offset : offset + 8])
                except OSError:
                    return
                threading.Event().wait(0.3)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHeaderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    credential = _credential(
        scopes=(
            "reports:read",
            f"data-agent-origin:{origin}",
            "data-agent-tenant:data-tenant-1",
        )
    )
    adapter = DataAgentReportAdapter(
        _config(base_url=origin, credential=credential, timeout_seconds=1),
        credential_broker=_Broker(),
        clock=lambda: NOW,
    )
    started = time.monotonic()
    try:
        with pytest.raises(DataAgentReportAdapterError, match="transport failed"):
            adapter.pull(TRACE_ID)
    finally:
        elapsed = time.monotonic() - started
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert elapsed < 1.8
    assert adapter.registry_counts == (0, 0, 0, 0)


def test_legacy_sqlite_observation_schema_migrates_for_id_rehydration(tmp_path) -> None:
    source_database = tmp_path / "source.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(source_database),
    )
    bundle = first.pull(TRACE_ID)
    with sqlite3.connect(source_database) as connection:
        legacy_row = connection.execute(
            """
            SELECT namespace_digest, source_id, source_tenant_id, trace_id,
                   raw_digest, body, bundle_json
            FROM data_agent_report_observations
            """
        ).fetchone()
    assert legacy_row is not None

    legacy_database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy_database) as connection:
        connection.execute(
            """
            CREATE TABLE data_agent_report_observations (
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                raw_digest TEXT NOT NULL,
                body BLOB NOT NULL,
                bundle_json TEXT NOT NULL,
                PRIMARY KEY (namespace_digest, trace_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO data_agent_report_observations (
                namespace_digest, source_id, source_tenant_id, trace_id,
                raw_digest, body, bundle_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            legacy_row,
        )

    restarted, broker, transport = _adapter(
        state_store=SQLiteDataAgentReportStateStore(legacy_database),
    )

    assert restarted.resolve_event(bundle.event.environment_event_id) == bundle.event
    assert (
        restarted.resolve_projection(bundle.projection.projection_id)
        == bundle.projection
    )
    assert broker.resolved == []
    assert transport.requests == []
    with sqlite3.connect(legacy_database) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(data_agent_report_observations)"
            )
        }
        version_row = connection.execute(
            """
            SELECT schema_version FROM data_agent_report_schema_metadata
            WHERE component = 'data-agent-report-adapter'
            """
        ).fetchone()
    assert {
        "report_trace_id",
        "revision_digest",
        "event_id",
        "projection_id",
    } <= columns
    assert version_row == (2,)


def test_invalid_legacy_row_rolls_back_schema_migration(tmp_path) -> None:
    source_database = tmp_path / "valid-source.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(source_database),
    )
    first.pull(TRACE_ID)
    with sqlite3.connect(source_database) as connection:
        legacy_row: list[object] = list(
            connection.execute(
                """
                SELECT namespace_digest, source_id, source_tenant_id, trace_id,
                       raw_digest, body, bundle_json
                FROM data_agent_report_observations
                """
            ).fetchone()
            or ()
        )
    assert legacy_row
    legacy_row[5] = sqlite3.Binary(b"{}")

    legacy_database = tmp_path / "invalid-legacy.sqlite3"
    with sqlite3.connect(legacy_database) as connection:
        connection.execute(
            """
            CREATE TABLE data_agent_report_observations (
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                raw_digest TEXT NOT NULL,
                body BLOB NOT NULL,
                bundle_json TEXT NOT NULL,
                PRIMARY KEY (namespace_digest, trace_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO data_agent_report_observations (
                namespace_digest, source_id, source_tenant_id, trace_id,
                raw_digest, body, bundle_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            legacy_row,
        )

    with pytest.raises(DataAgentReportAdapterError, match="digest"):
        SQLiteDataAgentReportStateStore(legacy_database)

    with sqlite3.connect(legacy_database) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(data_agent_report_observations)"
            )
        }
        metadata_table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'data_agent_report_schema_metadata'
            """
        ).fetchone()
    assert "report_trace_id" not in columns
    assert metadata_table is None


def test_corrupt_durable_body_fails_closed_without_partial_registry(tmp_path) -> None:
    database = tmp_path / "corrupt-body.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundle = first.pull(TRACE_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE data_agent_report_observations SET body = ?",
            (sqlite3.Binary(b"{}"),),
        )
    reopened_store = SQLiteDataAgentReportStateStore(database)
    restarted, _, transport = _adapter(state_store=reopened_store)

    with pytest.raises(DataAgentReportAdapterError, match="digest"):
        restarted.resolve_event(bundle.event.environment_event_id)

    assert restarted.registry_counts == (0, 0, 0, 0)
    assert transport.requests == []


def test_corrupt_durable_bundle_binding_fails_closed_without_partial_registry(
    tmp_path,
) -> None:
    database = tmp_path / "corrupt-bundle.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundle = first.pull(TRACE_ID)
    reopened_store = SQLiteDataAgentReportStateStore(database)
    with sqlite3.connect(database) as connection:
        raw_bundle = connection.execute(
            "SELECT bundle_json FROM data_agent_report_observations"
        ).fetchone()
        assert raw_bundle is not None
        mutated = json.loads(str(raw_bundle[0]))
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
    restarted, _, transport = _adapter(state_store=reopened_store)

    with pytest.raises(DataAgentReportAdapterError, match="bundle binding"):
        restarted.resolve_projection(bundle.projection.projection_id)

    assert restarted.registry_counts == (0, 0, 0, 0)
    assert transport.requests == []


def test_shared_policy_rejects_invalid_source_contract_before_registration(
    tmp_path,
) -> None:
    writer, broker, transport = _adapter()
    invalid_body = _report_bytes(trace_id="trace-other")
    invalid_digest = hashlib.sha256(invalid_body).hexdigest()
    with pytest.raises(DataAgentReportAdapterError, match="trace binding"):
        writer._build_bundle(  # type: ignore[attr-defined]
            TRACE_ID,
            invalid_body,
            invalid_digest,
            NOW,
        )

    assert writer.registry_counts == (0, 0, 0, 0)
    assert broker.resolved == []
    assert transport.requests == []


def test_corrupt_durable_object_index_fails_closed_without_partial_registry(
    tmp_path,
) -> None:
    database = tmp_path / "corrupt-index.sqlite3"
    first, _, _ = _adapter(
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundle = first.pull(TRACE_ID)
    reopened_store = SQLiteDataAgentReportStateStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE data_agent_report_bundle_index
            SET report_trace_id = 'trace:tampered'
            WHERE object_kind = 'event'
            """
        )
    restarted, _, transport = _adapter(state_store=reopened_store)

    with pytest.raises(DataAgentReportAdapterError, match="index binding"):
        restarted.resolve_event(bundle.event.environment_event_id)

    assert restarted.registry_counts == (0, 0, 0, 0)
    assert transport.requests == []


def test_unknown_future_state_schema_fails_closed(tmp_path) -> None:
    database = tmp_path / "future-schema.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE data_agent_report_schema_metadata (
                component TEXT NOT NULL PRIMARY KEY,
                schema_version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO data_agent_report_schema_metadata (
                component, schema_version
            ) VALUES ('data-agent-report-adapter', 999)
            """
        )

    with pytest.raises(DataAgentReportAdapterError, match="unsupported"):
        SQLiteDataAgentReportStateStore(database)


def test_state_store_does_not_read_or_overwrite_database_user_version(tmp_path) -> None:
    database = tmp_path / "shared-user-version.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 999")

    SQLiteDataAgentReportStateStore(database)

    with sqlite3.connect(database) as connection:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert user_version == 999


def test_duplicate_persisted_event_contract_id_fails_closed(tmp_path) -> None:
    database = tmp_path / "duplicate-event-id.sqlite3"
    feed = _feed_bytes(
        [
            _feed_event("opaque-cursor-1"),
            _feed_event(
                "opaque-cursor-2",
                _report_bytes(authority_payload=True),
            ),
        ],
        next_cursor="opaque-cursor-2",
    )
    first, _, _ = _adapter(
        response=_response(
            feed,
            final_url="http://127.0.0.1:8765/external/report-events?limit=2",
        ),
        config=_config(
            credential=_credential(
                scopes=(
                    "reports:read",
                    "report-events:read",
                    "data-agent-origin:http://127.0.0.1:8765",
                    "data-agent-tenant:data-tenant-1",
                )
            )
        ),
        state_store=SQLiteDataAgentReportStateStore(database),
    )
    bundles = first.poll_once(limit=2).bundles
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX data_agent_report_event_ids")
        connection.execute(
            """
            UPDATE data_agent_report_observations SET event_id = ?
            WHERE event_id = ?
            """,
            (
                bundles[0].event.environment_event_id,
                bundles[1].event.environment_event_id,
            ),
        )

    with pytest.raises(DataAgentReportAdapterError, match="schema"):
        SQLiteDataAgentReportStateStore(database)


def test_changed_report_conflict_survives_adapter_restart(tmp_path) -> None:
    database = tmp_path / "durable-conflict.sqlite3"
    first = DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW,
    )
    first.pull(TRACE_ID)
    changed_body = _report_bytes(authority_payload=True)
    restarted = DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        transport=_Transport(_response(changed_body)),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    with pytest.raises(DataAgentReportConflict):
        restarted.pull(TRACE_ID)

    assert restarted.registry_counts == (0, 0, 0, 0)


def test_durable_namespace_binds_target_scope_and_mandate(tmp_path) -> None:
    database = tmp_path / "scoped-observations.sqlite3"
    first = DataAgentReportAdapter(
        _config(),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW,
    )
    first_bundle = first.pull(TRACE_ID)
    other_credential = _credential(
        owner_principal_id="user:other",
        tenant_id="tenant:other",
        workspace_id="workspace:other",
    )
    second = DataAgentReportAdapter(
        _config(
            credential=other_credential,
            principal_id="user:other",
            target_tenant_id="tenant:other",
            target_workspace_id="workspace:other",
            mandate_id="mandate:other",
            environment_binding_id="binding:other",
        ),
        credential_broker=_Broker(),
        transport=_Transport(_response()),
        state_store=SQLiteDataAgentReportStateStore(database),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    second_bundle = second.pull(TRACE_ID)

    assert second_bundle != first_bundle
    assert second_bundle.event.tenant_id == "tenant:other"
    assert second_bundle.event.mandate_id == "mandate:other"
    assert second_bundle.event.environment_binding_id == "binding:other"


def test_concurrent_resolver_cannot_observe_partial_registration() -> None:
    adapter, _, _ = _adapter()
    artifacts_updated = threading.Event()
    allow_writer = threading.Event()
    reader_finished = threading.Event()

    class BlockingDict(dict):
        def update(self, *args: object, **kwargs: object) -> None:
            super().update(*args, **kwargs)
            artifacts_updated.set()
            allow_writer.wait(timeout=2)

    adapter._artifacts = BlockingDict()  # type: ignore[attr-defined]
    writer = threading.Thread(target=lambda: adapter.pull(TRACE_ID), daemon=True)
    writer.start()
    assert artifacts_updated.wait(timeout=2)

    resolved: list[object] = []

    def read_during_registration() -> None:
        resolved.append(adapter.resolve_artifact(next(iter(adapter._artifacts))))  # type: ignore[attr-defined]
        reader_finished.set()

    reader = threading.Thread(target=read_during_registration, daemon=True)
    reader.start()
    assert not reader_finished.wait(timeout=0.1)
    allow_writer.set()
    writer.join(timeout=2)
    reader.join(timeout=2)

    assert reader_finished.is_set()
    assert resolved[0] is not None
    assert adapter.registry_counts == (2, 2, 1, 1)
