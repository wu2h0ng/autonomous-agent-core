from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EvaluationFailureCode,
    EvaluationReceipt,
    EvaluationScore,
    EvaluatorIdentity,
    EvaluatorInput,
    EvidenceManifest,
    EvidenceManifestEntry,
    FailureReason,
    HiddenSetManifest,
    RubricRef,
    Uncertainty,
)
from agent_os_core import (
    DeterministicEvaluatorAdapter,
    EvaluationAuthorityDenied,
    EvaluationBindingDrift,
    EvaluatorBackendMalformed,
    EvaluatorBackendTimeout,
    EvaluatorBackendUnavailable,
    EvaluatorMeasurementCandidate,
    EvaluatorRegistry,
    ExternalEvaluatorAdapter,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


HIDDEN_BYTES = b'{"cases":["held-out-1"]}'
EVIDENCE_BYTES = b'{"passed":7,"failed":0}'


def _identity(**updates: Any) -> EvaluatorIdentity:
    values: dict[str, Any] = {
        "evaluator_id": "eval-deterministic-1",
        "principal_id": "principal-evaluator",
        "implementation_id": "deterministic-json-evaluator",
        "implementation_version": "1.0.0",
        "config_digest": _digest(b"config-v1"),
        "provider_id": "local-deterministic",
        "model_id": "none",
        "prompt_digest": _digest(b"no-prompt"),
        "checkpoint_digest": _digest(b"no-checkpoint"),
    }
    values.update(updates)
    return EvaluatorIdentity(**values)


def _rubric(**updates: Any) -> RubricRef:
    values: dict[str, Any] = {
        "rubric_id": "rubric-product-tests",
        "rubric_version": "1",
        "rubric_digest": _digest(b"passed / total"),
    }
    values.update(updates)
    return RubricRef(**values)


def _hidden(**updates: Any) -> HiddenSetManifest:
    values: dict[str, Any] = {
        "manifest_id": "hidden-1",
        "manifest_version": "1",
        "artifact_ref": "artifact:hidden-1",
        "content_digest": _digest(HIDDEN_BYTES),
        "item_count": 1,
    }
    values.update(updates)
    return HiddenSetManifest(**values)


def _evidence(**updates: Any) -> EvidenceManifest:
    values: dict[str, Any] = {
        "manifest_id": "evidence-1",
        "entries": (
            EvidenceManifestEntry(
                evidence_ref="artifact:test-report",
                content_digest=_digest(EVIDENCE_BYTES),
                media_type="application/json",
            ),
        ),
    }
    values.update(updates)
    return EvidenceManifest(**values)


def _input(**updates: Any) -> EvaluatorInput:
    values: dict[str, Any] = {
        "evaluation_id": "evaluation-1",
        "proposal_id": "proposal-1",
        "proposer_principal_id": "principal-proposer",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "identity": _identity(),
        "rubric": _rubric(),
        "hidden_set": _hidden(),
        "evidence": _evidence(),
        "requested_at": NOW,
    }
    values.update(updates)
    return EvaluatorInput(**values)


def _reader(ref: str) -> bytes | None:
    return {
        "artifact:hidden-1": HIDDEN_BYTES,
        "artifact:test-report": EVIDENCE_BYTES,
    }.get(ref)


def _candidate(
    value: float = 1.0, *, input_digest: str
) -> EvaluatorMeasurementCandidate:
    return EvaluatorMeasurementCandidate(
        input_digest=input_digest,
        score=EvaluationScore(value=value, scale_min=0.0, scale_max=1.0),
        uncertainty=Uncertainty(confidence=1.0, reasons=()),
        failure_reasons=(),
    )


def test_contracts_are_closed_and_identity_requires_provider_binding() -> None:
    with pytest.raises(ValidationError):
        EvaluatorIdentity.model_validate(
            {
                "evaluator_id": "eval-1",
                "principal_id": "principal-evaluator",
                "implementation_id": "impl",
                "implementation_version": "1",
                "config_digest": _digest(b"config"),
                "model_id": "model",
                "prompt_digest": _digest(b"prompt"),
                "checkpoint_digest": _digest(b"checkpoint"),
            }
        )
    with pytest.raises(ValidationError):
        EvaluatorIdentity(**{**_identity().model_dump(), "authority": "VERIFY"})


def test_proposer_cannot_evaluate_its_own_proposal() -> None:
    request = _input(proposer_principal_id="principal-evaluator")
    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: DeterministicEvaluatorAdapter()},
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluationAuthorityDenied, match="proposer"):
        registry.evaluate(request)


def test_hidden_set_bytes_must_match_manifest_before_backend_call() -> None:
    calls = 0
    request = _input(hidden_set=_hidden(content_digest=_digest(b"forged")))

    def backend(_request: EvaluatorInput) -> EvaluatorMeasurementCandidate:
        nonlocal calls
        calls += 1
        return _candidate(input_digest=_request.canonical_digest())

    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: ExternalEvaluatorAdapter(backend)},
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluationAuthorityDenied, match="hidden set"):
        registry.evaluate(request)
    assert calls == 0


def test_evidence_bytes_must_match_manifest_before_backend_call() -> None:
    request = _input(
        evidence=_evidence(
            entries=(
                EvidenceManifestEntry(
                    evidence_ref="artifact:test-report",
                    content_digest=_digest(b"forged"),
                    media_type="application/json",
                ),
            )
        )
    )
    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: DeterministicEvaluatorAdapter()},
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluationAuthorityDenied, match="evidence"):
        registry.evaluate(request)


def test_external_measurement_is_registry_sealed_and_cannot_verify_outcome() -> None:
    request = _input()
    adapter = ExternalEvaluatorAdapter(
        lambda supplied: _candidate(input_digest=supplied.canonical_digest())
    )
    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: adapter},
        artifact_reader=_reader,
        clock=lambda: NOW,
        receipt_id_factory=lambda: "evaluation-receipt-1",
    )

    receipt = registry.evaluate(request)

    assert isinstance(receipt, EvaluationReceipt)
    assert receipt.score.value == 1.0
    assert receipt.receipt_digest == receipt.canonical_digest()
    assert "status" not in receipt.model_dump()
    assert "observed_outcome" not in receipt.model_dump()


def test_external_backend_cannot_return_a_presealed_receipt_or_constant_unbound_score() -> (
    None
):
    request = _input()
    fake_receipt = {
        "receipt_id": "forged",
        "evaluation_id": request.evaluation_id,
        "score": {"value": 1.0, "scale_min": 0.0, "scale_max": 1.0},
        "status": "VERIFIED",
    }

    def forged_backend(_supplied: EvaluatorInput) -> Any:
        return fake_receipt

    registry = EvaluatorRegistry(
        adapters={
            request.identity.evaluator_id: ExternalEvaluatorAdapter(forged_backend)
        },
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluatorBackendMalformed):
        registry.evaluate(request)

    unbound = EvaluatorMeasurementCandidate(
        input_digest=_digest(b"constant"),
        score=EvaluationScore(value=1.0, scale_min=0.0, scale_max=1.0),
        uncertainty=Uncertainty(confidence=1.0, reasons=()),
        failure_reasons=(),
    )
    second = _input(evaluation_id="evaluation-2")
    second_registry = EvaluatorRegistry(
        adapters={
            second.identity.evaluator_id: ExternalEvaluatorAdapter(
                lambda _supplied: unbound
            )
        },
        artifact_reader=_reader,
        clock=lambda: NOW,
    )
    with pytest.raises(EvaluatorBackendMalformed, match="input"):
        second_registry.evaluate(second)


def test_backend_unavailable_does_not_swap_to_deterministic_fallback() -> None:
    request = _input()

    def unavailable(_request: EvaluatorInput) -> EvaluatorMeasurementCandidate:
        raise EvaluatorBackendUnavailable("provider offline")

    registry = EvaluatorRegistry(
        adapters={
            request.identity.evaluator_id: ExternalEvaluatorAdapter(unavailable),
            "fallback": DeterministicEvaluatorAdapter(),
        },
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluatorBackendUnavailable, match="offline"):
        registry.evaluate(request)


def test_backend_timeout_is_typed_and_does_not_silently_fallback() -> None:
    request = _input(evaluation_id="evaluation-timeout")

    def timeout(_request: EvaluatorInput) -> EvaluatorMeasurementCandidate:
        raise TimeoutError

    registry = EvaluatorRegistry(
        adapters={
            request.identity.evaluator_id: ExternalEvaluatorAdapter(timeout),
            "fallback": DeterministicEvaluatorAdapter(),
        },
        artifact_reader=_reader,
        clock=lambda: NOW,
    )

    with pytest.raises(EvaluatorBackendTimeout, match="timed out"):
        registry.evaluate(request)


def test_same_evaluation_id_is_idempotent_but_receipt_replay_with_config_drift_fails() -> (
    None
):
    calls = 0
    request = _input()

    def backend(supplied: EvaluatorInput) -> EvaluatorMeasurementCandidate:
        nonlocal calls
        calls += 1
        return _candidate(input_digest=supplied.canonical_digest())

    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: ExternalEvaluatorAdapter(backend)},
        artifact_reader=_reader,
        clock=lambda: NOW,
        receipt_id_factory=lambda: "evaluation-receipt-1",
    )
    first = registry.evaluate(request)
    replay = registry.evaluate(request.model_copy(deep=True))
    assert replay == first
    assert calls == 1

    drifted = request.model_copy(
        update={"identity": _identity(config_digest=_digest(b"config-v2"))}
    )
    with pytest.raises(EvaluationBindingDrift, match="evaluation_id"):
        registry.evaluate(drifted)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("rubric", _rubric(rubric_version="2")),
        ("hidden_set", _hidden(manifest_version="2")),
        (
            "evidence",
            _evidence(manifest_id="evidence-2"),
        ),
    ],
)
def test_rubric_hidden_and_evidence_drift_fail_closed(
    field: str,
    replacement: object,
) -> None:
    request = _input()
    registry = EvaluatorRegistry(
        adapters={request.identity.evaluator_id: DeterministicEvaluatorAdapter()},
        artifact_reader=_reader,
        clock=lambda: NOW,
    )
    registry.evaluate(request)

    with pytest.raises(EvaluationBindingDrift):
        registry.evaluate(request.model_copy(update={field: replacement}))


def test_deterministic_reference_uses_evidence_and_records_failures() -> None:
    passed = _input()
    failed_bytes = b'{"passed":6,"failed":1}'
    failed = _input(
        evaluation_id="evaluation-failed",
        evidence=EvidenceManifest(
            manifest_id="evidence-failed",
            entries=(
                EvidenceManifestEntry(
                    evidence_ref="artifact:test-report-failed",
                    content_digest=_digest(failed_bytes),
                    media_type="application/json",
                ),
            ),
        ),
    )

    def reader(ref: str) -> bytes | None:
        if ref == "artifact:test-report-failed":
            return failed_bytes
        return _reader(ref)

    registry = EvaluatorRegistry(
        adapters={passed.identity.evaluator_id: DeterministicEvaluatorAdapter(reader)},
        artifact_reader=reader,
        clock=lambda: NOW,
    )
    passed_receipt = registry.evaluate(passed)
    failed_receipt = registry.evaluate(failed)

    assert passed_receipt.score.value == 1.0
    assert failed_receipt.score.value == pytest.approx(6 / 7)
    assert failed_receipt.failure_reasons == (
        FailureReason(
            code=EvaluationFailureCode.CRITERIA_NOT_MET,
            message="one or more deterministic checks failed",
            retriable=False,
        ),
    )
