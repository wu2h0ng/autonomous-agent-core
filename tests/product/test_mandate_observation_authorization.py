from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    MandateObservationAuthorizationCommand,
    MandateObservationAuthorizationReceipt,
    MandateRelevanceContextRef,
    ObservationBindingDescriptor,
    PrincipalIdentity,
    PrincipalRole,
    RelevanceAssessorRef,
    content_digest,
)
from agent_os_core import (
    MandateObservationAuthorizationConflict,
    MandateObservationAuthorizationDenied,
    MandateObservationAuthorizationPersistenceConflict,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore
from apps.api_server.app import AgentOSApplication
from tests.product.test_mandate_workspace_api import _payload


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
    assert receipt.workspace_record_digest == content_digest(workspace_record)
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
    owner.observation_binding_descriptors = (_descriptor(),)
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
