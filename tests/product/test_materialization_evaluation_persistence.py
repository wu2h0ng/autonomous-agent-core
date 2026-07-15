from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    CorrectionEpochVector,
)
from agent_os_core import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateScopeMismatch,
)
from agent_os_core.materialization_evaluation_persistence import (
    CandidateEvaluationRecordRequest,
    SQLiteCandidateEvaluationStore,
    candidate_evaluation_idempotency_key,
    candidate_evaluation_payload_digest,
)


NOW = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _draft(**updates: Any) -> CandidateEvaluationDraft:
    values: dict[str, Any] = {
        "candidate_digest": DIGEST_A,
        "candidate_task_id": "task:candidate",
        "evaluation_task_id": "task:evaluation",
        "evaluation_run_id": "run:evaluation",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "evaluator": CandidateEvaluatorIdentity(
            evaluator_id="evaluator:programmatic:1",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="contract-check",
            evaluator_version="1",
            implementation_digest=DIGEST_B,
            configuration_digest=DIGEST_C,
        ),
        "evidence_bundle_digest": DIGEST_D,
        "evidence_refs": ("evidence:1",),
        "disposition": CandidateEvaluationDisposition.EVALUATOR_PASS,
        "score": 0.8,
        "confidence": 0.9,
        "submitted_at": NOW,
    }
    values.update(updates)
    return CandidateEvaluationDraft(**values)


def _request(
    draft: CandidateEvaluationDraft,
    *,
    contract_digest: str = DIGEST_C,
    recorded_by: str = "principal:recorder",
) -> CandidateEvaluationRecordRequest:
    return CandidateEvaluationRecordRequest(
        evaluation_id=f"candidate-evaluation:{draft.evaluation_run_id}",
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_digest=draft.candidate_digest,
        idempotency_key=candidate_evaluation_idempotency_key(
            draft, contract_digest, recorded_by
        ),
        payload_digest=candidate_evaluation_payload_digest(
            draft, contract_digest, recorded_by
        ),
        recorded_by=recorded_by,
        recorded_at=NOW,
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=1,
            run_epoch=2,
            capability_epoch=3,
        ),
        evaluation_contract_digest=contract_digest,
        draft=draft,
    )


@pytest.fixture
def store() -> Iterator[SQLiteCandidateEvaluationStore]:
    value = SQLiteCandidateEvaluationStore()
    yield value
    value.close()


def test_append_assigns_version_parent_and_digest_transactionally(
    store: SQLiteCandidateEvaluationStore,
) -> None:
    first = store.append(_request(_draft()), expected_parent_digest=None)
    second_draft = _draft(
        evaluation_task_id="task:evaluation:2",
        evaluation_run_id="run:evaluation:2",
        parent_evaluation_digest=first.evaluation_digest,
    )
    second = store.append(
        _request(second_draft),
        expected_parent_digest=first.evaluation_digest,
    )

    assert first.evaluation_version == 1
    assert second.evaluation_version == 2
    assert second.draft.parent_evaluation_digest == first.evaluation_digest
    assert store.latest("tenant:1", "workspace:1", DIGEST_A) == second
    assert store.list_for_candidate("tenant:1", "workspace:1", DIGEST_A) == (
        first,
        second,
    )


def test_idempotent_replay_precedes_latest_parent_cas(
    store: SQLiteCandidateEvaluationStore,
) -> None:
    request = _request(_draft())
    first = store.append(request, expected_parent_digest=None)
    second_draft = _draft(
        evaluation_task_id="task:evaluation:2",
        evaluation_run_id="run:evaluation:2",
        parent_evaluation_digest=first.evaluation_digest,
    )
    store.append(_request(second_draft), expected_parent_digest=first.evaluation_digest)

    assert store.append(request, expected_parent_digest=None) == first


def test_same_derived_key_with_changed_output_is_conflict(
    store: SQLiteCandidateEvaluationStore,
) -> None:
    original = _request(_draft())
    store.append(original, expected_parent_digest=None)
    changed = _draft(score=0.1)
    changed_request = _request(changed)
    assert changed_request.idempotency_key == original.idempotency_key
    assert changed_request.payload_digest != original.payload_digest

    with pytest.raises(CandidateIdempotencyConflict):
        store.append(changed_request, expected_parent_digest=None)


def test_parent_cas_is_fail_closed(store: SQLiteCandidateEvaluationStore) -> None:
    first = store.append(_request(_draft()), expected_parent_digest=None)

    with pytest.raises(CandidateConcurrentWrite):
        store.append(
            _request(
                _draft(
                    evaluation_task_id="task:evaluation:2",
                    evaluation_run_id="run:evaluation:2",
                )
            ),
            expected_parent_digest=None,
        )
    with pytest.raises(CandidateConcurrentWrite):
        store.append(
            _request(
                _draft(
                    evaluation_task_id="task:evaluation:3",
                    evaluation_run_id="run:evaluation:3",
                    parent_evaluation_digest=DIGEST_D,
                )
            ),
            expected_parent_digest=DIGEST_D,
        )

    empty = SQLiteCandidateEvaluationStore()
    try:
        with pytest.raises(CandidateConcurrentWrite):
            empty.append(
                _request(_draft(parent_evaluation_digest=first.evaluation_digest)),
                expected_parent_digest=first.evaluation_digest,
            )
    finally:
        empty.close()


def test_store_rejects_scope_and_service_digest_bypass(
    store: SQLiteCandidateEvaluationStore,
) -> None:
    request = _request(_draft())
    with pytest.raises(CandidateScopeMismatch, match="scope"):
        store.append(
            replace(request, tenant_id="tenant:other"), expected_parent_digest=None
        )
    with pytest.raises(CandidateIdempotencyConflict, match="payload"):
        store.append(
            replace(request, payload_digest=DIGEST_A), expected_parent_digest=None
        )
    with pytest.raises(CandidateIdempotencyConflict, match="idempotency"):
        store.append(
            replace(request, idempotency_key=DIGEST_A), expected_parent_digest=None
        )


def test_sqlite_restart_preserves_receipt_bytes(tmp_path: Path) -> None:
    database = tmp_path / "evaluations.sqlite3"
    first_store = SQLiteCandidateEvaluationStore(database)
    receipt = first_store.append(_request(_draft()), expected_parent_digest=None)
    first_store.close()

    reopened = SQLiteCandidateEvaluationStore(database)
    try:
        assert reopened.latest("tenant:1", "workspace:1", DIGEST_A) == receipt
        assert (
            reopened.get_by_idempotency(
                "tenant:1", "workspace:1", receipt.idempotency_key
            )
            == receipt
        )
    finally:
        reopened.close()


def test_adm_p2_receipt_bytes_and_digest_are_stable() -> None:
    store = SQLiteCandidateEvaluationStore()
    try:
        receipt = store.append(_request(_draft()), expected_parent_digest=None)
    finally:
        store.close()

    assert (
        receipt.evaluation_digest
        == "8fa2699eddcbbb63adb350d83b890d21f113d4342a61384319468c10eb0a61c7"
    )
    assert receipt.model_dump_json() == (
        '{"schema_version":"1.0","evaluation_id":"candidate-evaluation:run:evaluation",'
        '"evaluation_version":1,"evaluation_digest":"8fa2699eddcbbb63adb350d83b890d21f113d4342a61384319468c10eb0a61c7",'
        '"payload_digest":"84df267e0121e58ee327689bd69227662ef4269920c6af03e24146aeca666c0c",'
        '"idempotency_key":"d98e7db534e86933f04ea2f4b96cff65016b4ec1c461c3a2bfe644e4024019fe",'
        '"recorded_by":"principal:recorder","recorded_at":"2026-07-15T13:00:00Z",'
        '"observed_correction_epochs":{"schema_version":"1.0","task_epoch":1,"run_epoch":2,"capability_epoch":3},'
        '"evaluation_contract_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
        '"draft":{"schema_version":"1.0","candidate_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"candidate_task_id":"task:candidate","evaluation_task_id":"task:evaluation",'
        '"evaluation_run_id":"run:evaluation","tenant_id":"tenant:1","workspace_id":"workspace:1",'
        '"evaluator":{"schema_version":"1.0","evaluator_id":"evaluator:programmatic:1",'
        '"evaluator_kind":"PROGRAMMATIC","evaluator_type":"contract-check","evaluator_version":"1",'
        '"implementation_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        '"configuration_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
        '"provider_id":null,"model_id":null,"checkpoint_digest":null,"prompt_digest":null,'
        '"fallback_policy":"FORBIDDEN"},"evidence_bundle_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",'
        '"evidence_refs":["evidence:1"],"disposition":"EVALUATOR_PASS","score":0.8,"confidence":0.9,'
        '"unresolved_gaps":[],"invalidity_reasons":[],"parent_evaluation_digest":null,'
        '"submitted_at":"2026-07-15T13:00:00Z"}}'
    )
