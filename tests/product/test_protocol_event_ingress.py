from __future__ import annotations

import inspect
import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import agent_os_contracts as contracts
import agent_os_core as core
from agent_os_contracts import RelevanceDisposition, content_digest
from agent_os_core import (
    EventEnvelopeAdapter,
    SituationalScopeMismatch,
    SituationalTrustDenied,
    WorkloadIdentityAdapter,
)
from apps.api_server.data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from apps.api_server.data_agent_situated_bootstrap import DataAgentAdmissionFacade
from agent_os_core import MandateSteward
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


def test_exact_replay_survives_restart_and_binds_durable_auth_chain(
    tmp_path: Path,
) -> None:
    registration = _registration()
    first_app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(registration,),
    )
    first = first_app.propose_authenticated_protocol_envelope(
        _cloud_event("durable-replay"), "workload-secret"
    )
    count_after_first = _admission_count(tmp_path)

    restarted_app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(registration,),
    )
    with (
        patch.object(
            DataAgentAdmissionFacade,
            "admit_event",
            side_effect=AssertionError("exact replay must not re-admit"),
        ),
        patch.object(
            MandateSteward,
            "observe_event",
            side_effect=AssertionError("exact replay must not re-propose"),
        ),
    ):
        replay = restarted_app.propose_authenticated_protocol_envelope(
            _cloud_event("durable-replay"), "workload-secret"
        )

    assert replay == first
    assert _admission_count(tmp_path) == count_after_first
    with sqlite3.connect(tmp_path / "agent-os.sqlite3.admission.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT principal_id, tenant_id, workspace_id, source_binding_id,
                   protocol, protocol_message_id, envelope_digest,
                   authorization_digest, receipt_json
            FROM protocol_ingress_receipts
            """
        ).fetchone()
    assert row is not None
    assert row[:6] == (
        "user:local",
        "tenant:local",
        "workspace:local",
        "binding:data-agent-reports",
        "CLOUDEVENTS",
        "durable-replay",
    )
    assert row[6] == first.envelope_digest
    assert row[7] == first.source_binding_authorization_digest
    assert contracts.ProtocolIngressReceipt.model_validate_json(row[8]) == first


def test_same_scoped_protocol_id_digest_drift_is_typed_conflict_without_admission(
    tmp_path: Path,
) -> None:
    assert hasattr(core, "ProtocolIngressConflict")
    app = _situated_app(
        tmp_path,
        RelevanceDisposition.CREATE_TASK,
        workload_identities=(_registration(),),
    )
    app.propose_authenticated_protocol_envelope(
        _cloud_event("drift-conflict"), "workload-secret"
    )
    before = _admission_count(tmp_path)
    drifted = _cloud_event("drift-conflict")
    drifted["extension"] = "changed-envelope"

    with (
        patch.object(
            DataAgentAdmissionFacade,
            "admit_event",
            side_effect=AssertionError("drift conflict must precede admission"),
        ),
        pytest.raises(core.ProtocolIngressConflict),
    ):
        app.propose_authenticated_protocol_envelope(drifted, "workload-secret")

    assert _admission_count(tmp_path) == before


@pytest.mark.parametrize(
    ("contract_name", "field", "replacement"),
    [
        ("ActorRef", "actor_id", "workload:data-agent-report-ingress"),
        ("WorkloadRef", "workload_id", "service:data-agent"),
        ("DelegationRef", "delegation_id", "service:data-agent"),
    ],
)
def test_identity_kinds_cannot_be_replaced_or_aliased(
    contract_name: str,
    field: str,
    replacement: str,
) -> None:
    registration = _registration()
    contract = getattr(registration, contract_name.removesuffix("Ref").lower())
    payload = contract.model_dump(mode="python")
    payload[field] = replacement

    with pytest.raises(ValidationError):
        getattr(contracts, contract_name).model_validate(payload)


@pytest.mark.parametrize(
    ("disposition", "outcome_kind", "trace_reason"),
    [
        (RelevanceDisposition.CREATE_TASK, "TASK_DRAFT", "TASK_DRAFT"),
        (RelevanceDisposition.HELP, "HELP_REQUEST", "HELP_REQUEST"),
        (RelevanceDisposition.IGNORE, "NO_PROPOSAL", "NO_PROPOSAL"),
    ],
)
def test_protocol_ingress_persists_complete_task6_evidence_chain(
    tmp_path: Path,
    disposition: RelevanceDisposition,
    outcome_kind: str,
    trace_reason: str,
) -> None:
    app = _situated_app(
        tmp_path,
        disposition,
        workload_identities=(_registration(),),
    )
    receipt = app.propose_authenticated_protocol_envelope(
        _cloud_event(f"task6-{outcome_kind.lower()}"), "workload-secret"
    )

    assert receipt.outcome_kind == outcome_kind
    admission_db = tmp_path / "agent-os.sqlite3.admission.sqlite3"
    with sqlite3.connect(admission_db) as connection:
        admission_rows = connection.execute(
            "SELECT COUNT(*) FROM srl_event_admission_receipts"
        ).fetchone()[0]
        trace = connection.execute(
            """
            SELECT status, reason, delegation_attempt_count, canonical_json
            FROM srl_situated_evaluation_traces
            """
        ).fetchone()
    assert admission_rows == 1
    assert trace is not None
    assert trace[:3] == ("COMPLETED", trace_reason, 1)
    trace_contract = contracts.SituatedEvaluationTrace.model_validate_json(trace[3])
    assert trace_contract.admission_receipt_digest
    assert trace_contract.result_binding_digest

    with sqlite3.connect(tmp_path / "situated.sqlite3") as connection:
        assessment_row = connection.execute(
            "SELECT source_binding_digest, record_json FROM situated_assessment_records"
        ).fetchone()
    assert assessment_row is not None
    assessment = contracts.SituatedAssessmentRecord.model_validate_json(
        assessment_row[1]
    ).assessment
    assert assessment.provider_call_attempted is True
    assert assessment.expected_provider_invocation_binding_digest
    assert assessment.provider_invocation_receipt_digest
    if receipt.task_draft is not None:
        assert receipt.task_draft.source_binding_digest == assessment_row[0]
    assert app.list_tasks() == []
