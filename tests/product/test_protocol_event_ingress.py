from __future__ import annotations

import inspect
import hashlib
import sqlite3
from pathlib import Path

import pytest

import agent_os_contracts as contracts
from agent_os_contracts import RelevanceDisposition, content_digest
from agent_os_core import (
    EventEnvelopeAdapter,
    SituationalScopeMismatch,
    SituationalTrustDenied,
    WorkloadIdentityAdapter,
)
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from tests.product.test_data_agent_situated_http import TRACE_ID, _situated_app


def _require_m1a_contracts() -> None:
    for name in (
        "ActorRef",
        "DelegationRef",
        "PrincipalRef",
        "WorkloadIdentityRegistration",
        "WorkloadRef",
    ):
        assert hasattr(contracts, name), f"missing closed M1a contract: {name}"
    assert "workload_identities" in inspect.signature(
        DataAgentSituatedBootstrap.compose
    ).parameters


def _registration(
    token: str = "workload-secret",
    *,
    tenant_id: str = "tenant:local",
    workspace_id: str = "workspace:local",
):
    _require_m1a_contracts()
    principal = contracts.PrincipalRef(
        principal_id="user:local",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    actor = contracts.ActorRef(
        actor_id="service:data-agent",
        actor_kind="SERVICE",
        principal_ref_digest=content_digest(principal),
    )
    workload = contracts.WorkloadRef(
        workload_id="workload:data-agent-report-ingress",
        trust_domain="agent-os.local",
        principal_ref_digest=content_digest(principal),
    )
    delegation = contracts.DelegationRef(
        delegation_id="delegation:data-agent-report-ingress",
        principal_ref_digest=content_digest(principal),
        actor_ref_digest=content_digest(actor),
        workload_ref_digest=content_digest(workload),
        allowed_source_binding_ids=("binding:data-agent-reports",),
    )
    return contracts.WorkloadIdentityRegistration(
        registration_id=f"workload-registration:{tenant_id}:data-agent-report-ingress",
        workload_assertion_digest=hashlib.sha256(
            contracts.canonical_json(token).encode("utf-8")
        ).hexdigest(),
        principal=principal,
        actor=actor,
        workload=workload,
        delegation=delegation,
        source_id="source:data-agent-local",
        source_binding_id="binding:data-agent-reports",
    )


def _cloud_event(message_id: str = "message-1") -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": message_id,
        "source": "source:data-agent-local",
        "type": "agent-os.data-agent.report-observed",
        "data": {"trace_id": TRACE_ID},
    }


def _mcp_envelope(message_id: str = "message-mcp") -> dict[str, object]:
    return {
        "protocol": "MCP",
        "request_id": message_id,
        "source": "source:data-agent-local",
        "params": {"trace_id": TRACE_ID},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
        },
    }


def _a2a_envelope(message_id: str = "message-a2a") -> dict[str, object]:
    return {
        "protocol": "A2A",
        "message_id": message_id,
        "source": "source:data-agent-local",
        "payload": {"trace_id": TRACE_ID},
        "agent_card": {
            "name": "external-reporter",
            "skills": [{"id": "activate-task"}, {"id": "grant-capability"}],
        },
    }


def _admission_count(tmp_path: Path) -> int:
    database = tmp_path / "agent-os.sqlite3.admission.sqlite3"
    if not database.exists():
        return 0
    with sqlite3.connect(database) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%receipt%'"
        ).fetchall()
        return sum(
            connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for (name,) in tables
        )


def test_authenticated_envelope_uses_real_situated_chain(tmp_path: Path) -> None:
    registration = _registration()
    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(registration,),
    )

    first = app.propose_authenticated_protocol_envelope(
        _cloud_event("message-1"), "workload-secret"
    )
    second = app.propose_authenticated_protocol_envelope(
        _cloud_event("message-2"), "workload-secret"
    )

    assert first.outcome_kind == "TASK_DRAFT"
    assert first.activation_authorized is False
    assert first.capability_grant_authorized is False
    assert first.external_effects_authorized is False
    assert first.binding_digest != second.binding_digest
    assert first.receipt_id != second.receipt_id
    assert app.list_tasks() == []


@pytest.mark.parametrize("assertion", ["", "forged-workload-secret"])
def test_missing_or_forged_binding_auth_denied_without_ledger_write(
    tmp_path: Path,
    assertion: str,
) -> None:
    registration = _registration()
    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(registration,),
    )
    before = _admission_count(tmp_path)

    with pytest.raises(SituationalTrustDenied):
        app.propose_authenticated_protocol_envelope(_cloud_event(), assertion)

    assert _admission_count(tmp_path) == before
    assert app.list_tasks() == []


def test_cloudevents_source_claim_cannot_replace_workload_auth(tmp_path: Path) -> None:
    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(_registration(),),
    )
    before = _admission_count(tmp_path)

    with pytest.raises(SituationalTrustDenied):
        app.propose_authenticated_protocol_envelope(_cloud_event(), "")
    spoofed = _cloud_event()
    spoofed["source"] = "source:attacker"
    with pytest.raises(SituationalTrustDenied):
        app.propose_authenticated_protocol_envelope(spoofed, "workload-secret")

    assert _admission_count(tmp_path) == before
    assert app.list_tasks() == []


@pytest.mark.parametrize("envelope", [_mcp_envelope(), _a2a_envelope()])
def test_mcp_and_a2a_authority_hints_remain_non_executing_drafts(
    tmp_path: Path,
    envelope: dict[str, object],
) -> None:
    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(_registration(),),
    )

    receipt = app.propose_authenticated_protocol_envelope(
        envelope, "workload-secret"
    )

    assert receipt.outcome_kind == "TASK_DRAFT"
    assert receipt.task_draft is not None
    assert receipt.task_draft.activation_authorized is False
    assert receipt.activation_authorized is False
    assert receipt.capability_grant_authorized is False
    assert receipt.external_effects_authorized is False
    assert app.list_tasks() == []


def test_same_protocol_id_is_scoped_and_foreign_tenant_cannot_alias(
    tmp_path: Path,
) -> None:
    local = _registration()
    foreign = _registration(
        "foreign-secret",
        tenant_id="tenant:foreign",
        workspace_id="workspace:foreign",
    )
    envelope = EventEnvelopeAdapter.parse(_cloud_event("shared-external-id"))
    identities = WorkloadIdentityAdapter((local, foreign))
    local_authorization = identities.authenticate(
        "workload-secret",
        envelope,
        ("user:local", "tenant:local", "workspace:local"),
    )
    foreign_authorization = identities.authenticate(
        "foreign-secret",
        envelope,
        ("user:local", "tenant:foreign", "workspace:foreign"),
    )
    assert local_authorization.binding_digest != foreign_authorization.binding_digest

    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(local, foreign),
    )
    before = _admission_count(tmp_path)
    with pytest.raises(SituationalScopeMismatch):
        app.propose_authenticated_protocol_envelope(
            _cloud_event("shared-external-id"), "foreign-secret"
        )
    assert _admission_count(tmp_path) == before
