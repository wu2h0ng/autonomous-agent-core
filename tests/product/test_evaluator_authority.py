from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EvaluationScore,
    EvaluatorIdentity,
    EvaluatorInput,
    EvaluatorMeasurementCandidate,
    EvaluatorRegistration,
    EvidenceManifest,
    EvidenceManifestEntry,
    HiddenSetManifest,
    RubricRef,
    Uncertainty,
)
from agent_os_core import (
    EvaluationReceiptStore,
    EvaluatorBackendMalformed,
    EvaluatorBackendTimeout,
    EvaluatorBackendUnavailable,
    EvaluatorRegistry,
    ExternalEvaluatorAdapter,
    TrustedEvaluatorRegistrationRegistry,
    VerifiedEvaluatorInputs,
)


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
ARTIFACTS = {
    "artifact:config": b'{"score":"pass_rate"}',
    "artifact:rubric": b'{"metric":"passed_over_total"}',
    "artifact:prompt": b'{"instruction":"score exact inputs"}',
    "artifact:checkpoint": b'{"implementation":"external-v1"}',
    "artifact:hidden": b'{"minimum_passed":1}',
    "artifact:evidence": b'{"passed":1,"failed":0}',
}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity() -> EvaluatorIdentity:
    return EvaluatorIdentity(
        evaluator_id="external-evaluator-1",
        principal_id="principal-evaluator",
        implementation_id="external-evaluator",
        implementation_version="1",
        config_artifact_ref="artifact:config",
        config_digest=_digest(ARTIFACTS["artifact:config"]),
        provider_id="provider-1",
        model_id="model-1",
        prompt_artifact_ref="artifact:prompt",
        prompt_digest=_digest(ARTIFACTS["artifact:prompt"]),
        checkpoint_artifact_ref="artifact:checkpoint",
        checkpoint_digest=_digest(ARTIFACTS["artifact:checkpoint"]),
    )


def _registration() -> EvaluatorRegistration:
    return EvaluatorRegistration(
        registration_id="registration-1",
        registration_version="1",
        registry_writer_principal_id="principal-registry-writer",
        identity=_identity(),
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
        rubric=RubricRef(
            rubric_id="rubric-1",
            rubric_version="1",
            artifact_ref="artifact:rubric",
            rubric_digest=_digest(ARTIFACTS["artifact:rubric"]),
        ),
        hidden_set=HiddenSetManifest(
            manifest_id="hidden-1",
            manifest_version="1",
            artifact_ref="artifact:hidden",
            content_digest=_digest(ARTIFACTS["artifact:hidden"]),
            item_count=1,
        ),
        evidence=EvidenceManifest(
            manifest_id="evidence-1",
            entries=(
                EvidenceManifestEntry(
                    evidence_ref="artifact:evidence",
                    content_digest=_digest(ARTIFACTS["artifact:evidence"]),
                    media_type="application/json",
                ),
            ),
        ),
        registered_at=NOW,
    )


def _request(evaluation_id: str = "evaluation-1") -> EvaluatorInput:
    return EvaluatorInput(
        evaluation_id=evaluation_id,
        proposal_id="proposal-1",
        proposer_principal_id="principal-proposer",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        task_id="task-1",
        run_id="run-1",
        registration_id="registration-1",
        registration_version="1",
        requested_at=NOW,
    )


def _registry(
    tmp_path: Path,
    backend: Any,
) -> EvaluatorRegistry:
    registration = _registration()
    adapter = ExternalEvaluatorAdapter(
        backend,
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    return EvaluatorRegistry(
        registrations=TrustedEvaluatorRegistrationRegistry(
            {registration.registration_id: registration}
        ),
        adapters={registration.adapter_id: adapter},
        artifact_reader=lambda ref: ARTIFACTS.get(ref),
        receipt_store=EvaluationReceiptStore(
            tmp_path / "receipt.sqlite3",
            writer_namespace="local-test-writer",
            seal_key=b"local-test-seal-key",
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
    )


def _candidate(
    request: EvaluatorInput,
    registration: EvaluatorRegistration,
    inputs: VerifiedEvaluatorInputs,
) -> EvaluatorMeasurementCandidate:
    return EvaluatorMeasurementCandidate(
        input_digest=request.canonical_digest(),
        registration_digest=registration.canonical_digest(),
        score=EvaluationScore(value=1.0, scale_min=0.0, scale_max=1.0),
        uncertainty=Uncertainty(confidence=1.0, reasons=()),
        failure_reasons=(),
        consumption_manifest=inputs.consumption_manifest,
        trace_digest=_digest(b"trace"),
    )


def test_identity_requires_provider_binding_and_contracts_are_closed() -> None:
    payload = _identity().model_dump(mode="json")
    payload.pop("provider_id")
    with pytest.raises(ValidationError):
        EvaluatorIdentity.model_validate(payload)
    with pytest.raises(ValidationError):
        EvaluatorIdentity.model_validate(
            {**_identity().model_dump(mode="json"), "authority": "VERIFY"}
        )


def test_registry_sealed_measurement_has_no_outcome_authority(tmp_path: Path) -> None:
    receipt = _registry(tmp_path, _candidate).evaluate(_request())

    assert receipt.score.value == 1.0
    assert "status" not in receipt.model_dump()
    assert "observed_outcome" not in receipt.model_dump()
    assert "verified" not in receipt.model_dump()


def test_external_backend_cannot_return_presealed_receipt_or_unbound_constant(
    tmp_path: Path,
) -> None:
    def forged(
        _request: EvaluatorInput,
        _registration: EvaluatorRegistration,
        _inputs: VerifiedEvaluatorInputs,
    ) -> Any:
        return {"status": "VERIFIED", "score": 1.0}

    with pytest.raises(EvaluatorBackendMalformed):
        _registry(tmp_path / "forged", forged).evaluate(_request())

    def unbound(
        _request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        candidate = _candidate(_request, registration, inputs)
        return candidate.model_copy(update={"input_digest": _digest(b"constant")})

    with pytest.raises(EvaluatorBackendMalformed, match="input"):
        _registry(tmp_path / "unbound", unbound).evaluate(_request())


def test_backend_unavailable_does_not_silently_fallback(tmp_path: Path) -> None:
    def unavailable(
        _request: EvaluatorInput,
        _registration: EvaluatorRegistration,
        _inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        raise EvaluatorBackendUnavailable("provider offline")

    with pytest.raises(EvaluatorBackendUnavailable, match="offline"):
        _registry(tmp_path, unavailable).evaluate(_request())


def test_backend_timeout_is_typed_and_not_silently_fallback(tmp_path: Path) -> None:
    def timeout(
        _request: EvaluatorInput,
        _registration: EvaluatorRegistration,
        _inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        raise TimeoutError

    with pytest.raises(EvaluatorBackendTimeout, match="timed out"):
        _registry(tmp_path, timeout).evaluate(_request())
