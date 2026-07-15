from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    CorrectionEpochVector,
    candidate_evaluation_receipt_digest,
    content_digest,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _evaluator(**updates: Any) -> CandidateEvaluatorIdentity:
    values: dict[str, Any] = {
        "evaluator_id": "evaluator:programmatic:1",
        "evaluator_kind": CandidateEvaluatorKind.PROGRAMMATIC,
        "evaluator_type": "contract-check",
        "evaluator_version": "1",
        "implementation_digest": DIGEST_A,
        "configuration_digest": DIGEST_B,
        "fallback_policy": "FORBIDDEN",
    }
    values.update(updates)
    return CandidateEvaluatorIdentity(**values)


def _draft(**updates: Any) -> CandidateEvaluationDraft:
    values: dict[str, Any] = {
        "candidate_digest": DIGEST_A,
        "candidate_task_id": "task:candidate",
        "evaluation_task_id": "task:evaluation",
        "evaluation_run_id": "run:evaluation",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "evaluator": _evaluator(),
        "evidence_bundle_digest": DIGEST_C,
        "evidence_refs": ("evidence:z", "evidence:a", "evidence:z"),
        "disposition": CandidateEvaluationDisposition.EVALUATOR_PASS,
        "score": 0.9,
        "confidence": 0.8,
        "submitted_at": NOW,
    }
    values.update(updates)
    return CandidateEvaluationDraft(**values)


def _receipt_payload(**updates: Any) -> dict[str, Any]:
    draft = updates.pop("draft", _draft())
    values: dict[str, Any] = {
        "schema_version": "1.0",
        "evaluation_id": "candidate-evaluation:1",
        "evaluation_version": 1,
        "payload_digest": content_digest(
            {
                "schema": "ADM-P2-BOUND-PAYLOAD-V1",
                "draft": draft,
                "evaluation_contract_digest": DIGEST_D,
                "recorded_by": "principal:recorder",
            }
        ),
        "idempotency_key": DIGEST_B,
        "recorded_by": "principal:recorder",
        "recorded_at": NOW,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=1,
            run_epoch=2,
            capability_epoch=3,
        ),
        "evaluation_contract_digest": DIGEST_D,
        "draft": draft,
    }
    values.update(updates)
    return values


def test_evaluation_contract_enums_are_closed() -> None:
    assert {item.value for item in CandidateEvaluationDisposition} == {
        "EVALUATOR_PASS",
        "EVALUATOR_FAIL",
        "UNRESOLVED",
        "INVALID",
    }
    assert {item.value for item in CandidateEvaluatorKind} == {
        "PROGRAMMATIC",
        "HUMAN",
        "MODEL",
    }


def test_model_evaluator_requires_full_identity_and_forbids_fallback() -> None:
    with pytest.raises(ValidationError, match="MODEL evaluator"):
        _evaluator(evaluator_kind="MODEL")

    model = _evaluator(
        evaluator_kind="MODEL",
        provider_id="provider:1",
        model_id="model:1",
        checkpoint_digest=DIGEST_C,
        prompt_digest=DIGEST_D,
    )
    assert model.model_id == "model:1"

    values = model.model_dump(mode="json")
    values["fallback_policy"] = "ALLOW"
    with pytest.raises(ValidationError):
        CandidateEvaluatorIdentity.model_validate(values)


def test_non_model_evaluator_forbids_model_identity_fields() -> None:
    with pytest.raises(ValidationError, match="forbid model identity"):
        _evaluator(provider_id="provider:smuggled")


def test_draft_normalizes_refs_and_rejects_same_task_or_extra_contract_digest() -> None:
    draft = _draft()
    assert draft.evidence_refs == ("evidence:a", "evidence:z")

    with pytest.raises(ValidationError, match="different tasks"):
        _draft(evaluation_task_id="task:candidate")

    values = draft.model_dump(mode="json")
    values["evaluation_contract_digest"] = DIGEST_D
    with pytest.raises(ValidationError, match="Extra inputs"):
        CandidateEvaluationDraft.model_validate(values)


@pytest.mark.parametrize("field", ["score", "confidence"])
def test_draft_rejects_non_finite_numeric_values(field: str) -> None:
    with pytest.raises(ValidationError):
        _draft(**{field: float("nan")})

    if field == "confidence":
        with pytest.raises(ValidationError):
            _draft(confidence=1.1)


def test_disposition_shapes_are_fail_closed() -> None:
    with pytest.raises(ValidationError, match="require score"):
        _draft(score=None)
    with pytest.raises(ValidationError, match="UNRESOLVED"):
        _draft(disposition="UNRESOLVED", score=None, unresolved_gaps=())
    unresolved = _draft(
        disposition="UNRESOLVED",
        score=None,
        unresolved_gaps=("gap:z", "gap:a", "gap:z"),
    )
    assert unresolved.unresolved_gaps == ("gap:a", "gap:z")
    with pytest.raises(ValidationError, match="INVALID"):
        _draft(disposition="INVALID", score=None, invalidity_reasons=())


def test_receipt_digest_is_validated_and_mutation_sensitive() -> None:
    payload = _receipt_payload()
    receipt = CandidateEvaluationReceipt(
        **payload,
        evaluation_digest=candidate_evaluation_receipt_digest(payload),
    )
    assert len(receipt.evaluation_digest) == 64

    for field, value in {
        "evaluation_version": 2,
        "recorded_by": "principal:other",
        "evaluation_contract_digest": DIGEST_C,
    }.items():
        changed = dict(payload)
        changed[field] = value
        assert candidate_evaluation_receipt_digest(changed) != receipt.evaluation_digest

    with pytest.raises(ValidationError, match="evaluation_digest"):
        CandidateEvaluationReceipt(**payload, evaluation_digest=DIGEST_A)


def test_receipt_digest_helper_rejects_self_inclusion() -> None:
    payload = _receipt_payload()
    payload["evaluation_digest"] = DIGEST_A
    with pytest.raises(ValueError, match="excluded"):
        candidate_evaluation_receipt_digest(payload)
