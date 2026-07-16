from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CredentialLeaseRef,
    EnvironmentEventAdmissionReceipt,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    credential_lease_digest,
    environment_event_admission_receipt_digest,
    event_origin_registration_digest,
    payload_admission_attestation_digest,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64
DIGEST_0 = "0" * 64
DIGEST_1 = "1" * 64
DIGEST_2 = "2" * 64
DIGEST_3 = "3" * 64
DIGEST_4 = "4" * 64
DIGEST_5 = "5" * 64
DIGEST_6 = "6" * 64
DIGEST_7 = "7" * 64
DIGEST_8 = "8" * 64
DIGEST_9 = "9" * 64


def _registration_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "environment_event_id": "environment-event-1",
        "source_id": "source-1",
        "source_config_digest": DIGEST_A,
        "credential_ref_id": "credential-ref-1",
        "credential_ref_digest": DIGEST_B,
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "event_digest": DIGEST_C,
        "observation_digest": DIGEST_D,
        "event_schema_digest": DIGEST_E,
        "payload_policy_digest": DIGEST_F,
        "registered_at": NOW,
    }


def _registration(**updates: Any) -> EventOriginRegistration:
    payload = _registration_payload()
    payload.update(updates)
    digest = event_origin_registration_digest(payload)
    return EventOriginRegistration(
        registration_id=f"event-origin:{digest}",
        registration_digest=digest,
        **payload,
    )


def _lease_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "credential_ref_id": "credential-ref-1",
        "credential_ref_digest": DIGEST_A,
        "source_id": "source-1",
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "correction_epoch": 3,
        "issued_at": NOW,
        "valid_from": NOW + timedelta(seconds=1),
        "expires_at": NOW + timedelta(hours=1),
        "issuer_id": "credential-authority/v1",
    }


def _lease(**updates: Any) -> CredentialLeaseRef:
    payload = _lease_payload()
    payload.update(updates)
    digest = credential_lease_digest(payload)
    return CredentialLeaseRef(
        lease_id=f"credential-lease:{digest}",
        lease_digest=digest,
        **payload,
    )


def _attestation_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "environment_event_id": "environment-event-1",
        "source_id": "source-1",
        "observation_artifact_id": "artifact-1",
        "observation_digest": DIGEST_A,
        "policy_digest": DIGEST_B,
        "schema_digest": DIGEST_C,
        "issuer_id": "payload-admission-policy/v1",
        "assessed_at": NOW,
        "disposition": "ADMITTED_UNDER_POLICY",
        "credential_reflected": False,
    }


def _attestation(**updates: Any) -> PayloadAdmissionAttestation:
    payload = _attestation_payload()
    payload.update(updates)
    digest = payload_admission_attestation_digest(payload)
    return PayloadAdmissionAttestation(
        attestation_id=f"payload-admission:{digest}",
        attestation_digest=digest,
        **payload,
    )


def _receipt_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "environment_event_id": "environment-event-1",
        "event_digest": DIGEST_A,
        "event_origin_digest": DIGEST_B,
        "credential_lease_digest": DIGEST_C,
        "payload_attestation_digest": DIGEST_D,
        "mandate_id": "mandate-1",
        "environment_binding_id": "binding-1",
        "environment_binding_version": 4,
        "environment_binding_digest": DIGEST_E,
        "correction_epoch": 3,
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "admitted_at": NOW,
        "issued_by": "event-admission-service/v1",
        "grants_authority": False,
        "authorizes_effects": False,
    }


def _receipt(**updates: Any) -> EnvironmentEventAdmissionReceipt:
    payload = _receipt_payload()
    payload.update(updates)
    digest = environment_event_admission_receipt_digest(payload)
    return EnvironmentEventAdmissionReceipt(
        receipt_id=f"event-admission:{digest}",
        receipt_digest=digest,
        **payload,
    )


def _trace(**updates: Any) -> SituatedEvaluationTrace:
    payload: dict[str, Any] = {
        "trace_id": "situated-trace-1",
        "admission_receipt_digest": DIGEST_A,
        "event_id": "environment-event-1",
        "projection_id": "projection-1",
        "mandate_id": "mandate-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "status": SituatedTraceStatus.COMPLETED,
        "reason": SituatedTraceReason.TASK_DRAFT,
        "result_binding_digest": DIGEST_B,
        "delegation_attempt_count": 1,
        "committed_provider_call_attempted": True,
        "input_tokens": 100,
        "output_tokens": 30,
        "duration_ms": 250,
        "measurement_scope": "LOCAL_CONTROLLED",
        "recorded_at": NOW,
    }
    payload.update(updates)
    return SituatedEvaluationTrace(**payload)


@pytest.mark.parametrize(
    ("helper", "payload", "expected"),
    [
        (
            event_origin_registration_digest,
            _registration_payload(),
            "d016eafb48b7c68129345f1df5a94be6bfaa59f5aeae9f0970e193f82610f55a",
        ),
        (
            credential_lease_digest,
            _lease_payload(),
            "d657bf52129a396e77111bb73977b3a293d75cc60432ee927b217429df535b04",
        ),
        (
            payload_admission_attestation_digest,
            _attestation_payload(),
            "de4ac30beb2060f5357f7ce7813a1b212f8d83c25182b1b2bb0070c052df7972",
        ),
        (
            environment_event_admission_receipt_digest,
            _receipt_payload(),
            "518b92b35c8a3e58c1855f65b53cb2d84c8ee0adc7fdeaaa842edde55e818f29",
        ),
    ],
)
def test_content_addressed_digest_helpers_are_exact(
    helper: Any,
    payload: dict[str, Any],
    expected: str,
) -> None:
    assert helper(payload) == expected


def test_content_addressed_ids_are_exact() -> None:
    registration = _registration()
    lease = _lease()
    attestation = _attestation()
    receipt = _receipt()
    assert registration.registration_id == (
        "event-origin:"
        "d016eafb48b7c68129345f1df5a94be6bfaa59f5aeae9f0970e193f82610f55a"
    )
    assert lease.lease_id == (
        "credential-lease:"
        "d657bf52129a396e77111bb73977b3a293d75cc60432ee927b217429df535b04"
    )
    assert attestation.attestation_id == (
        "payload-admission:"
        "de4ac30beb2060f5357f7ce7813a1b212f8d83c25182b1b2bb0070c052df7972"
    )
    assert receipt.receipt_id == (
        "event-admission:"
        "518b92b35c8a3e58c1855f65b53cb2d84c8ee0adc7fdeaaa842edde55e818f29"
    )


@pytest.mark.parametrize(
    ("factory", "payload_factory", "id_field", "digest_field", "mutations"),
    [
        (
            _registration,
            _registration_payload,
            "registration_id",
            "registration_digest",
            {
                "schema_version": "1.1",
                "environment_event_id": "environment-event-2",
                "source_id": "source-2",
                "source_config_digest": DIGEST_0,
                "credential_ref_id": "credential-ref-2",
                "credential_ref_digest": DIGEST_1,
                "principal_id": "principal-2",
                "tenant_id": "tenant-2",
                "workspace_id": "workspace-2",
                "mandate_id": "mandate-2",
                "environment_binding_id": "binding-2",
                "event_digest": DIGEST_2,
                "observation_digest": DIGEST_3,
                "event_schema_digest": DIGEST_4,
                "payload_policy_digest": DIGEST_5,
                "registered_at": NOW + timedelta(seconds=1),
            },
        ),
        (
            _lease,
            _lease_payload,
            "lease_id",
            "lease_digest",
            {
                "schema_version": "1.1",
                "credential_ref_id": "credential-ref-2",
                "credential_ref_digest": DIGEST_0,
                "source_id": "source-2",
                "principal_id": "principal-2",
                "tenant_id": "tenant-2",
                "workspace_id": "workspace-2",
                "mandate_id": "mandate-2",
                "environment_binding_id": "binding-2",
                "correction_epoch": 4,
                "issued_at": NOW - timedelta(seconds=1),
                "valid_from": NOW + timedelta(seconds=2),
                "expires_at": NOW + timedelta(hours=2),
                "issuer_id": "credential-authority/v2",
            },
        ),
        (
            _attestation,
            _attestation_payload,
            "attestation_id",
            "attestation_digest",
            {
                "schema_version": "1.1",
                "environment_event_id": "environment-event-2",
                "source_id": "source-2",
                "observation_artifact_id": "artifact-2",
                "observation_digest": DIGEST_0,
                "policy_digest": DIGEST_1,
                "schema_digest": DIGEST_2,
                "issuer_id": "payload-admission-policy/v2",
                "assessed_at": NOW + timedelta(seconds=1),
                "disposition": "DENIED",
                "credential_reflected": True,
            },
        ),
        (
            _receipt,
            _receipt_payload,
            "receipt_id",
            "receipt_digest",
            {
                "schema_version": "1.1",
                "environment_event_id": "environment-event-2",
                "event_digest": DIGEST_0,
                "event_origin_digest": DIGEST_1,
                "credential_lease_digest": DIGEST_2,
                "payload_attestation_digest": DIGEST_3,
                "mandate_id": "mandate-2",
                "environment_binding_id": "binding-2",
                "environment_binding_version": 5,
                "environment_binding_digest": DIGEST_4,
                "correction_epoch": 4,
                "principal_id": "principal-2",
                "tenant_id": "tenant-2",
                "workspace_id": "workspace-2",
                "admitted_at": NOW + timedelta(seconds=1),
                "issued_by": "other-service/v1",
                "grants_authority": True,
                "authorizes_effects": True,
            },
        ),
    ],
)
def test_old_content_address_is_rejected_after_every_field_mutation(
    factory: Any,
    payload_factory: Any,
    id_field: str,
    digest_field: str,
    mutations: dict[str, Any],
) -> None:
    original = factory()
    original_values = original.model_dump()
    assert set(mutations) == set(payload_factory())
    for field_name, mutated_value in mutations.items():
        values = {**original_values, field_name: mutated_value}
        with pytest.raises(ValidationError):
            type(original).model_validate(values)

    with pytest.raises(ValidationError, match=id_field):
        type(original).model_validate({**original_values, id_field: "wrong-id"})
    with pytest.raises(ValidationError, match=digest_field):
        type(original).model_validate({**original_values, digest_field: DIGEST_9})


@pytest.mark.parametrize(
    ("helper", "payload", "forbidden_fields"),
    [
        (
            event_origin_registration_digest,
            _registration_payload(),
            ("registration_id", "registration_digest"),
        ),
        (
            credential_lease_digest,
            _lease_payload(),
            ("lease_id", "lease_digest"),
        ),
        (
            payload_admission_attestation_digest,
            _attestation_payload(),
            ("attestation_id", "attestation_digest"),
        ),
        (
            environment_event_admission_receipt_digest,
            _receipt_payload(),
            ("receipt_id", "receipt_digest"),
        ),
    ],
)
def test_digest_helpers_reject_id_or_digest_self_inclusion(
    helper: Any,
    payload: dict[str, Any],
    forbidden_fields: tuple[str, str],
) -> None:
    for field_name in forbidden_fields:
        with pytest.raises(ValueError, match=field_name):
            helper({**payload, field_name: "forbidden"})


@pytest.mark.parametrize(
    ("issued_at", "valid_from", "expires_at"),
    [
        (NOW + timedelta(seconds=1), NOW, NOW + timedelta(hours=1)),
        (NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=1)),
    ],
)
def test_credential_lease_requires_strict_chronology(
    issued_at: datetime,
    valid_from: datetime,
    expires_at: datetime,
) -> None:
    with pytest.raises(ValidationError, match="issued_at <= valid_from < expires_at"):
        _lease(issued_at=issued_at, valid_from=valid_from, expires_at=expires_at)


def test_credential_lease_allows_issuance_at_valid_from() -> None:
    lease = _lease(issued_at=NOW, valid_from=NOW)
    assert lease.issued_at == lease.valid_from


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_lease, "correction_epoch"),
        (_receipt, "environment_binding_version"),
        (_receipt, "correction_epoch"),
        (_trace, "delegation_attempt_count"),
        (_trace, "input_tokens"),
        (_trace, "output_tokens"),
        (_trace, "duration_ms"),
    ],
)
def test_non_negative_numeric_bounds(factory: Any, field_name: str) -> None:
    with pytest.raises(ValidationError, match=field_name):
        factory(**{field_name: -1})


def test_fixed_false_and_closed_literal_fields_reject_authority_smuggling() -> None:
    with pytest.raises(ValidationError, match="credential_reflected"):
        _attestation(credential_reflected=True)
    with pytest.raises(ValidationError, match="disposition"):
        _attestation(disposition="DENIED")
    with pytest.raises(ValidationError, match="grants_authority"):
        _receipt(grants_authority=True)
    with pytest.raises(ValidationError, match="authorizes_effects"):
        _receipt(authorizes_effects=True)
    with pytest.raises(ValidationError, match="issued_by"):
        _receipt(issued_by="other-service/v1")
    with pytest.raises(ValidationError, match="measurement_scope"):
        _trace(measurement_scope="PRODUCTION")


def test_situated_trace_enums_are_exactly_closed() -> None:
    assert {member.value for member in SituatedTraceStatus} == {
        "PENDING",
        "COMPLETED",
        "DENIED",
    }
    assert {member.value for member in SituatedTraceReason} == {
        "ASSESSMENT_PENDING",
        "TASK_DRAFT",
        "HELP_REQUEST",
        "NO_PROPOSAL",
        "ADMISSION_DENIED",
        "AUTHORITY_CHANGED",
        "PROVIDER_FAILED",
    }
    with pytest.raises(ValidationError, match="status"):
        _trace(status="FAILED")
    with pytest.raises(ValidationError, match="reason"):
        _trace(reason="UNKNOWN")


def test_situated_trace_accepts_optional_measurements() -> None:
    trace = _trace(
        status=SituatedTraceStatus.PENDING,
        reason=SituatedTraceReason.ASSESSMENT_PENDING,
        result_binding_digest=None,
        committed_provider_call_attempted=None,
        input_tokens=None,
        output_tokens=None,
    )
    assert trace.measurement_scope == "LOCAL_CONTROLLED"
    assert trace.result_binding_digest is None


def test_contracts_are_frozen_and_forbid_extra_fields() -> None:
    registration = _registration()
    with pytest.raises(ValidationError, match="extra_field"):
        EventOriginRegistration.model_validate(
            {**registration.model_dump(), "extra_field": "forbidden"}
        )
    with pytest.raises(ValidationError, match="frozen"):
        registration.source_id = "source-2"
