from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    MandateObservationAuthorizationCommand,
    MandateObservationAuthorizationReceipt,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    MandateRelevanceContextRef,
    MandateWorkspaceRecord,
    ObservationBindingDescriptor,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    RelevanceAssessorRef,
    RelevanceDisposition,
    TaskDraftProposal,
    content_digest,
)
from agent_os_core import (
    MandateObservationAuthorizationConflict,
    MandateObservationAuthorizationDenied,
    MandateObservationAuthorizationPersistenceConflict,
    DeterministicProvider,
    InMemoryMandateRelevanceContextRegistry,
    ProviderRelevanceAssessor,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.app import AgentOSApplication
from apps.api_server.data_agent_report_adapter import SQLiteDataAgentReportStateStore
from apps.api_server.data_agent_report_admission import (
    SQLiteDataAgentReportAdmissionMaterialStore,
)
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from apps.api_server.server import Handler
from tests.product.test_data_agent_external_report_adapter import (
    TRACE_ID,
    _adapter,
    _config,
    _credential,
)
from tests.product.test_mandate_workspace_api import _payload
from tests.product.test_provider_relevance_assessor import (
    _draft as _provider_draft,
    _policy as _provider_policy,
)


NOW = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


def _principal(
    principal_id: str,
    *,
    role: PrincipalRole,
    tenant_id: str = "tenant:local",
    workspace_id: str = "workspace:local",
) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id=principal_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        role=role,
        authenticated_at=NOW,
    )


def _assessor() -> RelevanceAssessorRef:
    return RelevanceAssessorRef(
        assessor_id="assessor:data-agent:v1",
        version=1,
        policy_digest="a" * 64,
    )


def _context() -> MandateRelevanceContextRef:
    return MandateRelevanceContextRef(
        relevance_context_id="context:build-agent-os:v1",
        version=1,
        content_digest="b" * 64,
    )


def _descriptor(**updates: object) -> ObservationBindingDescriptor:
    values: dict[str, object] = {
        "environment_binding_id": "binding:data-agent-report:v1",
        "environment_binding_class": "project-state",
        "version": 1,
        "source_descriptor_digest": "c" * 64,
        "observation_capabilities": ("observation.read",),
        "max_wake_budget_per_window": 8,
        "max_query_budget_per_window": 32,
        "relevance_assessor": _assessor(),
        "relevance_context": _context(),
    }
    values.update(updates)
    return ObservationBindingDescriptor.model_validate(values)


def _command(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "authorization_id": "observation-auth:build-agent-os:data-agent:v1",
        "environment_binding_id": "binding:data-agent-report:v1",
        "environment_binding_class": "project-state",
        "binding_version": 1,
        "requested_capabilities": ["observation.read"],
        "wake_budget_per_window": 8,
        "query_budget_per_window": 32,
        "relevance_assessor": _assessor().model_dump(mode="json"),
        "relevance_context": _context().model_dump(mode="json"),
    }
    values.update(updates)
    return values


def _apps(tmp_path, *, descriptor: ObservationBindingDescriptor | None = None):
    database = tmp_path / "agent-os.sqlite3"
    owner = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:owner", role=PrincipalRole.PRINCIPAL),
        clock=lambda: NOW,
    )
    owner.create_mandate_workspace_record(
        _payload(expires_at=NOW + timedelta(days=30))
    )
    authorizer = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
        observation_binding_descriptors=(descriptor or _descriptor(),),
    )
    return database, owner, authorizer


def test_independent_admin_projects_ratified_workspace_record_without_execution(
    tmp_path,
) -> None:
    database, owner, authorizer = _apps(tmp_path)

    raw = authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    receipt = MandateObservationAuthorizationReceipt.model_validate(raw)

    workspace_record = owner.get_mandate_workspace_record("mandate:build-agent-os")
    assert receipt.workspace_record_digest == content_digest(
        MandateWorkspaceRecord.model_validate(workspace_record)
    )
    assert receipt.owner_principal_id == "principal:owner"
    assert receipt.authorized_by == "principal:security"
    assert receipt.task_activation_authorized is False
    assert receipt.capability_grant_authorized is False
    assert receipt.external_effects_authorized is False
    assert owner.list_tasks() == []
    assert authorizer.list_tasks() == []
    assert authorizer.list_mandate_observation_authorizations(
        "mandate:build-agent-os"
    ) == [raw]

    authority = SQLiteSituatedAssessmentStore(database)
    mandate, binding = authority.resolve_active(
        "mandate:build-agent-os",
        "binding:data-agent-report:v1",
        principal_id="principal:owner",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluated_at=NOW,
    )
    assert mandate.mandate_digest == receipt.mandate_digest
    assert mandate.relevance_assessor == _assessor()
    assert mandate.relevance_context == _context()
    assert binding == receipt.environment_binding


def test_authorization_contract_rejects_authority_and_effect_fields() -> None:
    for field, value in (
        ("principal_id", "attacker"),
        ("ratified_by", "attacker"),
        ("mandate_digest", "d" * 64),
        ("task_activation_authorized", True),
        ("capability_grant_authorized", True),
        ("external_effects_authorized", True),
    ):
        payload = _command(**{field: value})
        with pytest.raises(ValidationError):
            MandateObservationAuthorizationCommand.model_validate(payload)


@pytest.mark.parametrize(
    "command_update",
    [
        {"environment_binding_class": "git-workspace"},
        {"requested_capabilities": ["workspace.patch"]},
        {"wake_budget_per_window": 17},
        {"query_budget_per_window": 65},
        {
            "relevance_assessor": RelevanceAssessorRef(
                assessor_id="assessor:other", version=1, policy_digest="a" * 64
            ).model_dump(mode="json")
        },
        {
            "relevance_context": MandateRelevanceContextRef(
                relevance_context_id="context:other",
                version=1,
                content_digest="b" * 64,
            ).model_dump(mode="json")
        },
    ],
)
def test_binding_scope_capability_budget_assessor_and_context_fail_closed(
    tmp_path, command_update: dict[str, object]
) -> None:
    _, _, authorizer = _apps(tmp_path)
    with pytest.raises(MandateObservationAuthorizationDenied):
        authorizer.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command(**command_update)
        )
    assert authorizer.list_mandate_observation_authorizations(
        "mandate:build-agent-os"
    ) == []


def test_non_admin_owner_and_cross_scope_admin_cannot_authorize(tmp_path) -> None:
    database, owner, _ = _apps(tmp_path)
    owner = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:owner", role=PrincipalRole.PRINCIPAL),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationDenied):
        owner.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command()
        )
    foreign = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal(
            "principal:foreign-admin",
            role=PrincipalRole.TENANT_ADMIN,
            tenant_id="tenant:foreign",
        ),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationDenied):
        foreign.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command()
        )


def test_exact_replay_is_idempotent_and_same_ids_with_drift_conflict(tmp_path) -> None:
    _, _, authorizer = _apps(tmp_path)
    first = authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    assert authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    ) == first

    with pytest.raises(MandateObservationAuthorizationConflict):
        authorizer.authorize_mandate_observation_binding(
            "mandate:build-agent-os",
            _command(query_budget_per_window=31),
        )


def test_exact_replay_survives_later_request_time_and_second_admin_cannot_rebind(
    tmp_path,
) -> None:
    database, _, authorizer = _apps(tmp_path)
    first = authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    authorizer._clock = lambda: NOW + timedelta(minutes=5)
    assert authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    ) == first

    second_admin = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:security-2", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationConflict):
        second_admin.authorize_mandate_observation_binding(
            "mandate:build-agent-os",
            _command(authorization_id="observation-auth:second"),
        )


def test_receipt_or_index_tamper_fails_closed_after_restart(tmp_path) -> None:
    database, _, authorizer = _apps(tmp_path)
    authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE mandate_observation_authorizations "
            "SET receipt_digest = ? WHERE authorization_id = ?",
            ("f" * 64, "observation-auth:build-agent-os:data-agent:v1"),
        )
    restarted = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationPersistenceConflict):
        restarted.list_mandate_observation_authorizations(
            "mandate:build-agent-os"
        )


def test_command_digest_tamper_fails_closed_on_list(tmp_path) -> None:
    database, _, authorizer = _apps(tmp_path)
    authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE mandate_observation_authorizations SET command_digest = ?",
            ("0" * 64,),
        )
    with pytest.raises(MandateObservationAuthorizationPersistenceConflict):
        authorizer.list_mandate_observation_authorizations(
            "mandate:build-agent-os"
        )


def test_same_mandate_id_is_isolated_by_tenant_and_workspace(tmp_path) -> None:
    database, _, first_admin = _apps(tmp_path)
    first_admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    second_owner = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal(
            "principal:owner-2",
            role=PrincipalRole.PRINCIPAL,
            tenant_id="tenant:second",
            workspace_id="workspace:second",
        ),
        clock=lambda: NOW,
    )
    second_owner.create_mandate_workspace_record(
        _payload(expires_at=NOW + timedelta(days=30))
    )
    second_admin = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal(
            "principal:security-2",
            role=PrincipalRole.TENANT_ADMIN,
            tenant_id="tenant:second",
            workspace_id="workspace:second",
        ),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    second_admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command(authorization_id="auth:second")
    )
    first = SQLiteSituatedAssessmentStore(database).resolve_active(
        "mandate:build-agent-os",
        "binding:data-agent-report:v1",
        principal_id="principal:owner",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluated_at=NOW,
    )
    second = SQLiteSituatedAssessmentStore(database).resolve_active(
        "mandate:build-agent-os",
        "binding:data-agent-report:v1",
        principal_id="principal:owner-2",
        tenant_id="tenant:second",
        workspace_id="workspace:second",
        evaluated_at=NOW,
    )
    assert first[0].tenant_id != second[0].tenant_id


def test_missing_expired_or_digest_drifted_workspace_record_fails_closed(
    tmp_path,
) -> None:
    missing_database = tmp_path / "missing.sqlite3"
    missing = AgentOSApplication(
        database=missing_database,
        workspace=tmp_path,
        principal=_principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationDenied):
        missing.authorize_mandate_observation_binding("mandate:missing", _command())

    database = tmp_path / "expired.sqlite3"
    owner = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:owner", role=PrincipalRole.PRINCIPAL),
        clock=lambda: NOW,
    )
    owner.create_mandate_workspace_record(
        _payload(expires_at=NOW + timedelta(seconds=1))
    )
    expired = AgentOSApplication(
        database=database,
        workspace=tmp_path,
        principal=_principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW + timedelta(seconds=2),
        observation_binding_descriptors=(_descriptor(),),
    )
    with pytest.raises(MandateObservationAuthorizationDenied):
        expired.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command()
        )

    drift_dir = tmp_path / "drift"
    drift_dir.mkdir()
    drift_database, _, authorizer = _apps(drift_dir)
    with sqlite3.connect(drift_database) as connection:
        connection.execute(
            "UPDATE mandate_workspace_records SET record_digest = ?",
            ("0" * 64,),
        )
    with pytest.raises(MandateObservationAuthorizationPersistenceConflict):
        authorizer.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command()
        )


def test_pause_or_correction_epoch_invalidates_old_authorization(tmp_path) -> None:
    database, _, authorizer = _apps(tmp_path)
    authorizer.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    authority = SQLiteSituatedAssessmentStore(database)
    authority.pause("mandate:build-agent-os", expected_epoch=0)

    with pytest.raises(MandateObservationAuthorizationDenied):
        authorizer.authorize_mandate_observation_binding(
            "mandate:build-agent-os", _command()
        )
    with pytest.raises(Exception, match="not active"):
        authority.resolve_active(
            "mandate:build-agent-os",
            "binding:data-agent-report:v1",
            principal_id="principal:owner",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            evaluated_at=NOW,
        )


def test_caller_created_ratified_ref_cannot_enter_authorization_api(tmp_path) -> None:
    _, _, authorizer = _apps(tmp_path)
    payload = _command(
        allowed_environment_bindings=[],
        owner_principal_id="attacker",
        authority_envelope_digest="e" * 64,
    )
    with pytest.raises(ValidationError):
        authorizer.authorize_mandate_observation_binding(
            "mandate:build-agent-os", payload
        )


def test_http_authorize_and_list_observation_authorizations(tmp_path) -> None:
    _, _, authorizer = _apps(tmp_path)
    public = AgentOSApplication(database=tmp_path / "public.sqlite3", workspace=tmp_path)
    handler = type(
        "ObservationAuthorizationHandler",
        (Handler,),
        {
            "application": public,
            "admin_applications": {"opaque-admin-token": authorizer},
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    path = "/v1/mandates/mandate:build-agent-os/environment-bindings:authorize"
    list_path = "/v1/mandates/mandate:build-agent-os/observation-authorizations"
    try:
        request = urllib.request.Request(
            base + path,
            data=json.dumps(_command()).encode(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "same-http-key",
                "Authorization": "Bearer opaque-admin-token",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 201
            created = json.loads(response.read())
        list_request = urllib.request.Request(
            base + list_path,
            headers={"Authorization": "Bearer opaque-admin-token"},
        )
        with urllib.request.urlopen(list_request) as response:
            assert response.status == 200
            listed = json.loads(response.read())
        assert listed == {"observation_authorizations": [created]}
        assert created["task_activation_authorized"] is False
        assert created["capability_grant_authorized"] is False
        assert created["external_effects_authorized"] is False
        conflicting = urllib.request.Request(
            base + path,
            data=json.dumps(_command(query_budget_per_window=31)).encode(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "same-http-key",
                "Authorization": "Bearer opaque-admin-token",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(conflicting)
        assert excinfo.value.code == 409
        conflict = json.loads(excinfo.value.read())
        assert conflict["error"] == "MandateObservationAuthorizationConflict"

        for token in (None, "wrong-token"):
            headers = {"Content-Type": "application/json"}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            denied = urllib.request.Request(
                base + path,
                data=json.dumps(_command()).encode(),
                headers=headers,
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as denied_info:
                urllib.request.urlopen(denied)
            assert denied_info.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_data_agent_observation_replays_without_second_provider_assessment(
    tmp_path,
) -> None:
    authority_database = tmp_path / "authority.sqlite3"
    task_database = tmp_path / "task.sqlite3"
    report_database = tmp_path / "reports.sqlite3"
    owner = AgentOSApplication(
        database=authority_database,
        workspace=tmp_path,
        principal=_principal("user:local", role=PrincipalRole.PRINCIPAL),
        clock=lambda: NOW,
    )
    workspace_raw = owner.create_mandate_workspace_record(
        _payload(expires_at=NOW + timedelta(days=30))
    )
    workspace_record = MandateWorkspaceRecord.model_validate(workspace_raw)
    policy = _provider_policy()
    context = MandateRelevanceContext(
        relevance_context_id="context:authorized-data-agent:v1",
        version=1,
        mandate_id=workspace_record.mandate.mandate_id,
        mandate_version=1,
        mandate_digest=content_digest(workspace_record.mandate),
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        mission_statement=workspace_record.mandate.mission_statement,
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:founder-load",
                statement="Reduce hidden Founder cognitive load.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:quality",
                statement="Protect the verified product quality boundary.",
                due_at=NOW + timedelta(hours=2),
            ),
        ),
        permanent_constraints=workspace_record.mandate.permanent_constraints,
    )
    source_credential = _credential(
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    source_config = _config(credential=source_credential)
    first_adapter, _, _ = _adapter(
        config=source_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
        now=NOW,
    )
    descriptor = ObservationBindingDescriptor(
        environment_binding_id="binding:data-agent-reports",
        environment_binding_class="project-state",
        version=1,
        source_descriptor_digest=first_adapter.admission_policy_descriptor.policy_digest,
        observation_capabilities=("observation.read",),
        max_wake_budget_per_window=8,
        max_query_budget_per_window=32,
        relevance_assessor=policy.assessor_ref(),
        relevance_context=context.ref(),
    )
    admin = AgentOSApplication(
        database=authority_database,
        workspace=tmp_path,
        principal=_principal("principal:security", role=PrincipalRole.TENANT_ADMIN),
        clock=lambda: NOW,
        observation_binding_descriptors=(descriptor,),
    )
    command = _command(
        environment_binding_id="binding:data-agent-reports",
        relevance_assessor=policy.assessor_ref().model_dump(mode="json"),
        relevance_context=context.ref().model_dump(mode="json"),
    )
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os", command
    )

    drift_adapter, _, _ = _adapter(
        config=_config(
            credential=source_credential,
            scope_ref="mission:drifted-source-policy",
        ),
        state_store=SQLiteDataAgentReportStateStore(tmp_path / "drift-reports.sqlite3"),
        now=NOW,
    )
    drift_assessor = ProviderRelevanceAssessor(
        provider=DeterministicProvider(
            text=_provider_draft(RelevanceDisposition.CREATE_TASK),
            invocation_binding=policy.provider_invocation,
        ),
        provider_profile=policy.provider_invocation.provider_profile,
        policy=policy,
        trust=drift_adapter,
        contexts=InMemoryMandateRelevanceContextRegistry((context,)),
    )
    with pytest.raises(TypeError, match="exact observation authorization"):
        DataAgentSituatedBootstrap.compose(
            adapter=drift_adapter,
            material_store=SQLiteDataAgentReportAdmissionMaterialStore(
                tmp_path / "drift-material.sqlite3",
                principal_id="user:local",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            ),
            credentials=drift_adapter._credential_authorization_reader_for_composition,
            control=SQLiteSituatedAssessmentStore(authority_database),
            assessor=drift_assessor,
            admission_database=tmp_path / "drift-admission.sqlite3",
            clock=lambda: NOW,
        )

    def compose(adapter, provider):
        control = SQLiteSituatedAssessmentStore(authority_database)
        assessor = ProviderRelevanceAssessor(
            provider=provider,
            provider_profile=policy.provider_invocation.provider_profile,
            policy=policy,
            trust=adapter,
            contexts=InMemoryMandateRelevanceContextRegistry((context,)),
        )
        runtime = DataAgentSituatedBootstrap.compose(
            adapter=adapter,
            material_store=SQLiteDataAgentReportAdmissionMaterialStore(
                tmp_path / "admission-material.sqlite3",
                principal_id="user:local",
                tenant_id="tenant:local",
                workspace_id="workspace:local",
            ),
            credentials=adapter._credential_authorization_reader_for_composition,
            control=control,
            assessor=assessor,
            admission_database=tmp_path / "event-admission.sqlite3",
            clock=lambda: NOW,
        )
        return AgentOSApplication._with_data_agent_situated_runtime(
            situated_runtime=runtime,
            principal=_principal("user:local", role=PrincipalRole.PRINCIPAL),
            database=task_database,
            workspace=tmp_path,
            clock=lambda: NOW,
        )

    first_provider = DeterministicProvider(
        text=_provider_draft(RelevanceDisposition.CREATE_TASK),
        invocation_binding=policy.provider_invocation,
    )
    first_app = compose(first_adapter, first_provider)
    first = first_app.observe_admit_and_propose_data_agent_report(TRACE_ID)
    assert isinstance(first, TaskDraftProposal)
    assert first.activation_authorized is False
    assert first.external_effects_authorized is False
    assert len(first_provider.decision_requests) == 1
    assert first_app.list_tasks() == []

    replay_adapter, _, _ = _adapter(
        config=source_config,
        state_store=SQLiteDataAgentReportStateStore(report_database),
        now=NOW,
    )
    replay_provider = DeterministicProvider(
        text=_provider_draft(RelevanceDisposition.HELP),
        invocation_binding=policy.provider_invocation,
    )
    replay_app = compose(replay_adapter, replay_provider)
    replay = replay_app.observe_admit_and_propose_data_agent_report(TRACE_ID)
    assert replay == first
    assert replay_provider.decision_requests == []
    assert replay_app.list_tasks() == []

    with sqlite3.connect(authority_database) as connection:
        connection.execute("DELETE FROM mandate_observation_authorizations")
    with pytest.raises(Exception, match="observation authorization"):
        compose(replay_adapter, replay_provider)
