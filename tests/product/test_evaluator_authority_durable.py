from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EvaluationArtifactRole,
    EvaluationConsumptionEntry,
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
    canonical_json,
    content_digest,
)
from agent_os_core import (
    DeterministicEvaluatorAdapter,
    EvaluationAuthorityDenied,
    EvaluationBindingDrift,
    EvaluationInProgress,
    EvaluationReceiptStore,
    EvaluatorAdapter,
    EvaluatorRegistry,
    ExternalEvaluatorAdapter,
    TrustedEvaluatorRegistrationRegistry,
    VerifiedEvaluatorInputs,
)


NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)
CONFIG = b'{"score":"pass_rate"}'
RUBRIC = b'{"metric":"passed_over_total"}'
PROMPT = b'{"instruction":"score exact inputs"}'
CHECKPOINT = b'{"implementation":"deterministic-v2"}'
HIDDEN = b'{"minimum_passed":7}'
EVIDENCE = b'{"passed":7,"failed":0}'


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(**updates: Any) -> EvaluatorIdentity:
    values: dict[str, Any] = {
        "evaluator_id": "evaluator-1",
        "principal_id": "principal-evaluator",
        "implementation_id": "deterministic-evaluator",
        "implementation_version": "2.0.0",
        "config_artifact_ref": "artifact:config",
        "config_digest": _digest(CONFIG),
        "provider_id": "local-deterministic",
        "model_id": "none",
        "prompt_artifact_ref": "artifact:prompt",
        "prompt_digest": _digest(PROMPT),
        "checkpoint_artifact_ref": "artifact:checkpoint",
        "checkpoint_digest": _digest(CHECKPOINT),
    }
    values.update(updates)
    return EvaluatorIdentity(**values)


def _registration(**updates: Any) -> EvaluatorRegistration:
    values: dict[str, Any] = {
        "registration_id": "registration-1",
        "registration_version": "1",
        "registry_writer_principal_id": "principal-registry-writer",
        "identity": _identity(),
        "adapter_id": "deterministic-json",
        "adapter_version": "2",
        "adapter_binding_digest": _digest(b"deterministic-json:2"),
        "rubric": RubricRef(
            rubric_id="rubric-1",
            rubric_version="1",
            artifact_ref="artifact:rubric",
            rubric_digest=_digest(RUBRIC),
        ),
        "hidden_set": HiddenSetManifest(
            manifest_id="hidden-1",
            manifest_version="1",
            artifact_ref="artifact:hidden",
            content_digest=_digest(HIDDEN),
            item_count=1,
        ),
        "evidence": EvidenceManifest(
            manifest_id="evidence-1",
            entries=(
                EvidenceManifestEntry(
                    evidence_ref="artifact:evidence",
                    content_digest=_digest(EVIDENCE),
                    media_type="application/json",
                ),
            ),
        ),
        "registered_at": NOW,
    }
    values.update(updates)
    return EvaluatorRegistration(**values)


def _request(**updates: Any) -> EvaluatorInput:
    values: dict[str, Any] = {
        "evaluation_id": "evaluation-1",
        "proposal_id": "proposal-1",
        "proposer_principal_id": "principal-proposer",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "registration_id": "registration-1",
        "registration_version": "1",
        "requested_at": NOW,
    }
    values.update(updates)
    return EvaluatorInput(**values)


def _artifacts(**updates: bytes) -> dict[str, bytes]:
    values = {
        "artifact:config": CONFIG,
        "artifact:rubric": RUBRIC,
        "artifact:prompt": PROMPT,
        "artifact:checkpoint": CHECKPOINT,
        "artifact:hidden": HIDDEN,
        "artifact:evidence": EVIDENCE,
    }
    values.update(updates)
    return values


def _reader(artifacts: dict[str, bytes]):
    return lambda ref: artifacts.get(ref)


def _registry(
    tmp_path: Path,
    *,
    registration: EvaluatorRegistration | None = None,
    adapter: EvaluatorAdapter | None = None,
    artifacts: dict[str, bytes] | None = None,
) -> EvaluatorRegistry:
    resolved_registration = registration or _registration()
    resolved_artifacts = artifacts or _artifacts()
    resolved_adapter = adapter or DeterministicEvaluatorAdapter()
    return EvaluatorRegistry(
        registrations=TrustedEvaluatorRegistrationRegistry(
            {resolved_registration.registration_id: resolved_registration}
        ),
        adapters={resolved_registration.adapter_id: resolved_adapter},
        artifact_reader=_reader(resolved_artifacts),
        receipt_store=EvaluationReceiptStore(
            tmp_path / "evaluation.sqlite3",
            writer_namespace="local-evaluator-writer",
            seal_key=b"local-test-seal-key",
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
    )


def test_request_only_references_trusted_registration_and_cannot_mint_authority() -> (
    None
):
    with pytest.raises(ValidationError):
        EvaluatorInput.model_validate(
            {
                **_request().model_dump(mode="json"),
                "identity": _identity().model_dump(mode="json"),
            }
        )


@pytest.mark.parametrize(
    "proposer",
    ["principal-evaluator", "principal-registry-writer"],
)
def test_proposer_registry_writer_and_evaluator_are_separate(
    tmp_path: Path,
    proposer: str,
) -> None:
    with pytest.raises(EvaluationAuthorityDenied):
        _registry(tmp_path).evaluate(_request(proposer_principal_id=proposer))


def test_registration_rejects_registry_writer_equal_to_evaluator() -> None:
    with pytest.raises(ValidationError, match="registry writer"):
        _registration(registry_writer_principal_id="principal-evaluator")


def test_sqlite_store_is_restart_idempotent_and_returns_canonical_bytes(
    tmp_path: Path,
) -> None:
    first_registry = _registry(tmp_path)
    first = first_registry.evaluate(_request())
    second_registry = _registry(tmp_path)
    replay = second_registry.evaluate(_request())

    assert replay == first
    assert second_registry.verify_receipt(replay)
    assert canonical_json(replay).encode() == second_registry.receipt_bytes(
        replay.evaluation_id
    )


def test_same_id_registration_or_request_drift_fails_after_restart(
    tmp_path: Path,
) -> None:
    _registry(tmp_path).evaluate(_request())
    drifted_registration = _registration(registration_version="2")
    with pytest.raises(EvaluationBindingDrift):
        _registry(tmp_path, registration=drifted_registration).evaluate(
            _request(registration_version="2")
        )


def test_concurrent_reservation_allows_only_one_backend_call(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def backend(
        request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return EvaluatorMeasurementCandidate(
            input_digest=request.canonical_digest(),
            registration_digest=registration.canonical_digest(),
            score=EvaluationScore(value=1.0, scale_min=0.0, scale_max=1.0),
            uncertainty=Uncertainty(confidence=1.0, reasons=()),
            failure_reasons=(),
            consumption_manifest=inputs.consumption_manifest,
            trace_digest=content_digest(
                {"input": request.canonical_digest(), "consumed": True}
            ),
        )

    adapter = ExternalEvaluatorAdapter(
        backend,
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    registration = _registration(
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    first_registry = _registry(
        tmp_path,
        registration=registration,
        adapter=adapter,
    )
    second_registry = _registry(
        tmp_path,
        registration=registration,
        adapter=adapter,
    )
    result: list[object] = []

    thread = threading.Thread(
        target=lambda: result.append(first_registry.evaluate(_request()))
    )
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(EvaluationInProgress):
        second_registry.evaluate(_request())
    release.set()
    thread.join(timeout=5)

    assert len(result) == 1
    assert calls == 1
    assert second_registry.evaluate(_request()) == result[0]


def test_registration_and_artifacts_are_rechecked_after_backend(tmp_path: Path) -> None:
    artifacts = _artifacts()

    def backend(
        request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        artifacts["artifact:rubric"] = b"tampered-after-dispatch"
        return EvaluatorMeasurementCandidate(
            input_digest=request.canonical_digest(),
            registration_digest=registration.canonical_digest(),
            score=EvaluationScore(value=1.0, scale_min=0.0, scale_max=1.0),
            uncertainty=Uncertainty(confidence=1.0, reasons=()),
            failure_reasons=(),
            consumption_manifest=inputs.consumption_manifest,
            trace_digest=_digest(b"trace"),
        )

    registration = _registration(
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    adapter = ExternalEvaluatorAdapter(
        backend,
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    with pytest.raises(EvaluationBindingDrift, match="changed during evaluation"):
        _registry(
            tmp_path,
            registration=registration,
            adapter=adapter,
            artifacts=artifacts,
        ).evaluate(_request())


def test_public_self_hash_is_not_receipt_authority_and_mutation_cannot_pollute_store(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    receipt = registry.evaluate(_request())
    forged = receipt.model_copy(update={"store_seal": _digest(b"forged")})
    assert not registry.verify_receipt(forged)

    object.__setattr__(receipt.score, "value", 0.0)
    reread = registry.get_receipt(receipt.evaluation_id)
    assert reread is not None
    assert reread.score.value == 1.0
    assert registry.verify_receipt(reread)


def test_registration_snapshot_and_receipt_bytes_are_defensively_revalidated(
    tmp_path: Path,
) -> None:
    registration = _registration()
    registrations = TrustedEvaluatorRegistrationRegistry(
        {registration.registration_id: registration}
    )
    object.__setattr__(registration.identity, "provider_id", "attacker-provider")
    resolved = registrations.resolve("registration-1", "1")
    assert resolved.identity.provider_id == "local-deterministic"

    registry = _registry(tmp_path)
    registry.evaluate(_request())
    database = tmp_path / "evaluation.sqlite3"
    with sqlite3.connect(database) as connection:
        raw = connection.execute(
            "SELECT receipt_bytes FROM evaluation_receipts WHERE evaluation_id = ?",
            ("evaluation-1",),
        ).fetchone()[0]
        connection.execute(
            "UPDATE evaluation_receipts SET receipt_bytes = ? WHERE evaluation_id = ?",
            (b" " + raw, "evaluation-1"),
        )
    with pytest.raises(EvaluationAuthorityDenied, match="stored receipt bytes"):
        registry.get_receipt("evaluation-1")


def test_adapter_binding_is_registration_owned(tmp_path: Path) -> None:
    wrong = ExternalEvaluatorAdapter(
        lambda _request, _registration, _inputs: pytest.fail("must not run"),
        adapter_id="deterministic-json",
        adapter_version="999",
        adapter_binding_digest=_digest(b"wrong"),
    )
    with pytest.raises(EvaluationAuthorityDenied, match="adapter binding"):
        _registry(tmp_path, adapter=wrong).evaluate(_request())


def test_deterministic_reference_consumes_hidden_and_evidence_inputs(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    first = registry.evaluate(_request())
    assert first.score.value == 1.0
    roles = {entry.role for entry in first.consumption_manifest}
    assert roles == set(EvaluationArtifactRole)

    stricter_hidden = b'{"minimum_passed":8}'
    artifacts = _artifacts(**{"artifact:hidden": stricter_hidden})
    registration = _registration(
        registration_id="registration-2",
        hidden_set=HiddenSetManifest(
            manifest_id="hidden-2",
            manifest_version="1",
            artifact_ref="artifact:hidden",
            content_digest=_digest(stricter_hidden),
            item_count=1,
        ),
    )
    second = _registry(
        tmp_path / "second",
        registration=registration,
        artifacts=artifacts,
    ).evaluate(
        _request(
            evaluation_id="evaluation-2",
            registration_id="registration-2",
        )
    )
    assert second.score.value < first.score.value


def test_consumption_manifest_must_cover_every_verified_input(tmp_path: Path) -> None:
    registration = _registration(
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )

    def ignores_inputs(
        request: EvaluatorInput,
        current: EvaluatorRegistration,
        _inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        return EvaluatorMeasurementCandidate(
            input_digest=request.canonical_digest(),
            registration_digest=current.canonical_digest(),
            score=EvaluationScore(value=1.0, scale_min=0.0, scale_max=1.0),
            uncertainty=Uncertainty(confidence=1.0, reasons=()),
            failure_reasons=(),
            consumption_manifest=(
                EvaluationConsumptionEntry(
                    role=EvaluationArtifactRole.EVIDENCE,
                    artifact_ref="artifact:evidence",
                    content_digest=_digest(EVIDENCE),
                ),
            ),
            trace_digest=_digest(b"constant-score"),
        )

    adapter = ExternalEvaluatorAdapter(
        ignores_inputs,
        adapter_id="external-test",
        adapter_version="1",
        adapter_binding_digest=_digest(b"external-test:1"),
    )
    with pytest.raises(EvaluationAuthorityDenied, match="consumption"):
        _registry(
            tmp_path,
            registration=registration,
            adapter=adapter,
        ).evaluate(_request())
