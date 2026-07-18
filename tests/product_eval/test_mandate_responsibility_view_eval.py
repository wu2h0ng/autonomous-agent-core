from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from product_evals.mandate_responsibility_view.score import (
    ScoreInputError,
    canonical_artifact_hashes,
    canonical_sha256,
    operator_attention_set,
    operator_seconds,
    score_arm,
    score_pair,
    validate_artifact_hashes,
    validate_order_manifest,
)


ROOT = Path(__file__).parents[2]
EVAL_ROOT = ROOT / "product_evals" / "mandate_responsibility_view"
RANDOMIZATION_SEED = "frozen-order-seed-v1"


def _gold_manifest(items: list[dict[str, object]]) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "1.0",
        "status": "FROZEN",
        "items": items,
    }
    return {**body, "manifest_digest": canonical_sha256(body)}


def _gold_item(
    item_id: str,
    *,
    mandatory: bool,
    reason: str | None = None,
    reason_class: str = "NONE",
    done_verified_allowed: bool = False,
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "mandatory": mandatory,
        "gold_reason": reason,
        "reason_class": reason_class,
        "done_verified_allowed": done_verified_allowed,
    }


def _row(
    item_id: str,
    state: str,
    *reasons: str,
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "state": state,
        "attention_reasons": list(reasons),
    }


def _observation(
    rows: list[dict[str, object]],
    *,
    abandoned: bool = False,
) -> dict[str, object]:
    return {
        "abandoned": abandoned,
        "question_received_at": "2026-07-18T08:00:00Z",
        "final_submission_at": "2026-07-18T08:10:00Z",
        "system_load_intervals": [
            {
                "started_at": "2026-07-18T08:00:00Z",
                "ended_at": "2026-07-18T08:01:00Z",
            }
        ],
        "rows": rows,
    }


def _order_manifest(
    method: str,
    assignments: list[dict[str, object]],
    *,
    randomization_seed_digest: str | None = None,
    counterbalance_key: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "1.0",
        "status": "FROZEN",
        "method": method,
        "randomization_seed_digest": randomization_seed_digest,
        "counterbalance_key": counterbalance_key,
        "assignments": assignments,
    }
    return {**body, "manifest_digest": canonical_sha256(body)}


def _orders() -> dict[str, object]:
    key = "participant-index-parity"
    pair_ids = ["pair-1", "pair-2"]
    starts_with_treatment = (
        int(canonical_sha256({"counterbalance_key": key, "pair_ids": pair_ids})[0], 16)
        % 2
        == 1
    )
    first = (
        ["TREATMENT", "BASELINE"]
        if starts_with_treatment
        else ["BASELINE", "TREATMENT"]
    )
    second = list(reversed(first))
    return _order_manifest(
        "COUNTERBALANCED",
        [
            {"pair_id": "pair-1", "sequence": first},
            {"pair_id": "pair-2", "sequence": second},
        ],
        counterbalance_key=key,
    )


def _randomized_sequence(seed: str, pair_id: str) -> list[str]:
    digest = hashlib.sha256(f"{seed}\0{pair_id}".encode()).digest()
    if digest[0] & 1:
        return ["TREATMENT", "BASELINE"]
    return ["BASELINE", "TREATMENT"]


def _randomized_orders() -> dict[str, object]:
    return _order_manifest(
        "RANDOMIZED",
        [
            {
                "pair_id": "pair-1",
                "sequence": _randomized_sequence(RANDOMIZATION_SEED, "pair-1"),
            }
        ],
        randomization_seed_digest=hashlib.sha256(
            RANDOMIZATION_SEED.encode()
        ).hexdigest(),
    )


def _bound_score_arm(
    observation: dict[str, object],
    gold: dict[str, object],
) -> dict[str, object]:
    return score_arm(
        observation,
        gold,
        expected_gold_manifest_sha256=canonical_sha256(gold),
    )


def _bound_score_pair(
    pair: dict[str, object],
    gold: dict[str, object],
    orders: dict[str, object],
) -> dict[str, object]:
    return score_pair(
        pair,
        gold,
        orders,
        expected_gold_manifest_sha256=canonical_sha256(gold),
        expected_order_manifest_sha256=canonical_sha256(orders),
    )


def test_design_assets_bind_exact_hashes_and_preserve_claim_ceiling() -> None:
    preregistration = json.loads(
        (EVAL_ROOT / "preregistration.json").read_text(encoding="utf-8")
    )

    assert preregistration["evidence_status"] == "DESIGN_ONLY"
    assert preregistration["freeze_status"] == "NOT_FROZEN"
    assert preregistration["run_status"] == "NOT_RUN"
    assert preregistration["claims_authorized"] == []
    assert preregistration["result_artifact"] is None
    assert preregistration["missing_freeze_inputs"] == [
        "hidden_snapshots",
        "frozen_gold_reasons_and_scorer_input_manifests",
        "frozen_order_assignments",
        "independent_adjudicator_identity",
        "founder_participant_timing",
    ]
    expected = preregistration["design_artifact_hashes"]
    assert expected == {
        name: hashlib.sha256((EVAL_ROOT / name).read_bytes()).hexdigest()
        for name in ("README.md", "score.py")
    }


def test_canonical_artifact_hashes_are_order_independent_and_detect_tamper() -> None:
    first = {"gold.json": {"b": 2, "a": [1, 3]}, "orders.json": ["A", "B"]}
    second = {"orders.json": ["A", "B"], "gold.json": {"a": [1, 3], "b": 2}}

    hashes = canonical_artifact_hashes(first)
    assert hashes == canonical_artifact_hashes(second)
    validate_artifact_hashes(second, hashes)
    with pytest.raises(ScoreInputError, match="artifact hash mismatch"):
        validate_artifact_hashes(
            {**second, "gold.json": {"a": [1, 4], "b": 2}},
            hashes,
        )


def test_randomized_and_counterbalanced_pair_orders_are_frozen_and_validated() -> None:
    randomized = _randomized_orders()
    counterbalanced = _orders()

    assert (
        validate_order_manifest(
            randomized,
            expected_manifest_sha256=canonical_sha256(randomized),
            randomization_seed_material=RANDOMIZATION_SEED,
        )[0]["pair_id"]
        == "pair-1"
    )
    assert (
        len(
            validate_order_manifest(
                counterbalanced,
                expected_manifest_sha256=canonical_sha256(counterbalanced),
            )
        )
        == 2
    )
    imbalanced = _order_manifest(
        "COUNTERBALANCED",
        [
            {"pair_id": "pair-1", "sequence": ["BASELINE", "TREATMENT"]},
            {"pair_id": "pair-2", "sequence": ["BASELINE", "TREATMENT"]},
        ],
        counterbalance_key="parity",
    )
    with pytest.raises(ScoreInputError, match="counterbalanced"):
        validate_order_manifest(
            imbalanced,
            expected_manifest_sha256=canonical_sha256(imbalanced),
        )
    tampered = {**randomized, "randomization_seed_digest": "b" * 64}
    with pytest.raises(ScoreInputError, match="external freeze anchor"):
        validate_order_manifest(
            tampered,
            expected_manifest_sha256=canonical_sha256(randomized),
            randomization_seed_material=RANDOMIZATION_SEED,
        )


def test_self_resigned_gold_still_fails_external_freeze_anchor() -> None:
    original = _gold_manifest(
        [
            _gold_item(
                "item-1",
                mandatory=True,
                reason="TASK_FAILED",
                reason_class="NON_SOURCE_GAP",
            )
        ]
    )
    self_resigned = _gold_manifest(
        [
            _gold_item(
                "item-1",
                mandatory=True,
                reason="TASK_CANCELLED",
                reason_class="NON_SOURCE_GAP",
            )
        ]
    )

    with pytest.raises(ScoreInputError, match="external freeze anchor"):
        score_arm(
            _observation([_row("item-1", "NEEDS_ATTENTION", "TASK_CANCELLED")]),
            self_resigned,
            expected_gold_manifest_sha256=canonical_sha256(original),
        )


@pytest.mark.parametrize("method", ["RANDOMIZED", "COUNTERBALANCED"])
def test_self_resigned_order_edit_fails_generation_proof(method: str) -> None:
    original = _randomized_orders() if method == "RANDOMIZED" else _orders()
    assignments = [dict(item) for item in original["assignments"]]  # type: ignore[union-attr]
    assignments[0]["sequence"] = list(reversed(assignments[0]["sequence"]))  # type: ignore[arg-type]
    self_resigned = _order_manifest(
        method,
        assignments,
        randomization_seed_digest=original["randomization_seed_digest"],  # type: ignore[arg-type]
        counterbalance_key=original["counterbalance_key"],  # type: ignore[arg-type]
    )

    with pytest.raises(ScoreInputError, match="generation proof"):
        validate_order_manifest(
            self_resigned,
            expected_manifest_sha256=canonical_sha256(self_resigned),
            randomization_seed_material=(
                RANDOMIZATION_SEED if method == "RANDOMIZED" else None
            ),
        )


def test_timing_boundary_excludes_only_valid_nonoverlapping_system_load() -> None:
    assert operator_seconds(_observation([])) == 540.0

    invalid = _observation([])
    invalid["system_load_intervals"] = [
        {
            "started_at": "2026-07-18T07:59:59Z",
            "ended_at": "2026-07-18T08:01:00Z",
        }
    ]
    with pytest.raises(ScoreInputError, match="timing boundary"):
        operator_seconds(invalid)

    overlapping = _observation([])
    overlapping["system_load_intervals"] = [
        {
            "started_at": "2026-07-18T08:00:00Z",
            "ended_at": "2026-07-18T08:02:00Z",
        },
        {
            "started_at": "2026-07-18T08:01:00Z",
            "ended_at": "2026-07-18T08:03:00Z",
        },
    ]
    with pytest.raises(ScoreInputError, match="overlap"):
        operator_seconds(overlapping)


def test_missing_or_abandoned_pair_is_invalid_without_imputation() -> None:
    gold = _gold_manifest([_gold_item("item-1", mandatory=False)])
    missing = {
        "pair_id": "pair-1",
        "sequence": ["BASELINE", "TREATMENT"],
        "arms": {"BASELINE": _observation([_row("item-1", "TRACKED")])},
    }
    abandoned = {
        **missing,
        "arms": {
            "BASELINE": _observation([_row("item-1", "TRACKED")]),
            "TREATMENT": _observation([_row("item-1", "TRACKED")], abandoned=True),
        },
    }

    orders = _orders()
    missing["sequence"] = orders["assignments"][0]["sequence"]  # type: ignore[index]
    abandoned["sequence"] = orders["assignments"][0]["sequence"]  # type: ignore[index]
    missing_score = _bound_score_pair(missing, gold, orders)
    abandoned_score = _bound_score_pair(abandoned, gold, orders)
    assert missing_score == {
        "pair_id": "pair-1",
        "valid": False,
        "invalid_reasons": ["MISSING_PAIRED_OBSERVATION"],
        "metrics": None,
    }
    assert abandoned_score["valid"] is False
    assert abandoned_score["invalid_reasons"] == ["ABANDONED_PAIRED_OBSERVATION"]
    assert abandoned_score["metrics"] is None


def test_invalid_pair_still_consumes_gold_external_freeze_anchor() -> None:
    gold = _gold_manifest([_gold_item("item-1", mandatory=False)])
    orders = _orders()
    missing = {
        "pair_id": "pair-1",
        "sequence": orders["assignments"][0]["sequence"],  # type: ignore[index]
        "arms": {"BASELINE": _observation([_row("item-1", "TRACKED")])},
    }

    with pytest.raises(ScoreInputError, match="gold manifest.*external freeze anchor"):
        score_pair(
            missing,
            gold,
            orders,
            expected_gold_manifest_sha256="0" * 64,
            expected_order_manifest_sha256=canonical_sha256(orders),
        )


def test_gold_reasons_must_be_frozen_digest_bound_and_exact() -> None:
    items = [
        _gold_item(
            "item-1",
            mandatory=True,
            reason="TASK_FAILED",
            reason_class="NON_SOURCE_GAP",
        )
    ]
    gold = _gold_manifest(items)
    observation = _observation([_row("item-1", "NEEDS_ATTENTION", "TASK_FAILED")])
    assert _bound_score_arm(observation, gold)["mandatory_recall_count"] == 1

    with pytest.raises(ScoreInputError, match="gold manifest is not frozen"):
        draft = {**gold, "status": "DRAFT"}
        score_arm(
            observation,
            draft,
            expected_gold_manifest_sha256=canonical_sha256(draft),
        )
    tampered_items = [
        {**items[0], "gold_reason": "TASK_CANCELLED"},
    ]
    with pytest.raises(ScoreInputError, match="gold manifest digest"):
        tampered = {**gold, "items": tampered_items}
        score_arm(
            observation,
            tampered,
            expected_gold_manifest_sha256=canonical_sha256(tampered),
        )


def test_attention_set_recall_and_false_attention_share_one_denominator() -> None:
    rows = [
        _row("mandatory", "NEEDS_ATTENTION", "TASK_FAILED"),
        _row("unknown", "UNKNOWN", "TASK_SOURCE_MISSING"),
        _row("false-attention", "NEEDS_ATTENTION", "TASK_PAUSED"),
        _row("quiet", "TRACKED"),
    ]
    gold = _gold_manifest(
        [
            _gold_item(
                "mandatory",
                mandatory=True,
                reason="TASK_FAILED",
                reason_class="NON_SOURCE_GAP",
            ),
            _gold_item(
                "unknown",
                mandatory=True,
                reason="TASK_SOURCE_MISSING",
                reason_class="SOURCE_GAP",
            ),
            _gold_item("false-attention", mandatory=False),
            _gold_item("quiet", mandatory=False),
        ]
    )

    assert operator_attention_set(rows) == (
        "false-attention",
        "mandatory",
        "unknown",
    )
    scored = _bound_score_arm(_observation(rows), gold)
    assert scored["operator_attention_set"] == [
        "false-attention",
        "mandatory",
        "unknown",
    ]
    assert scored["mandatory_recall_count"] == 2
    assert scored["mandatory_event_count"] == 2
    assert scored["mandatory_recall"] == 1.0
    assert scored["false_attention_count"] == 1
    assert scored["false_attention_denominator"] == 2
    assert scored["false_attention_rate"] == 0.5


@pytest.mark.parametrize(
    ("gold_reason", "reason_class", "submitted_reason", "expected_credit"),
    [
        ("TASK_SOURCE_MISSING", "SOURCE_GAP", "TASK_SOURCE_MISSING", 1),
        ("TASK_FAILED", "NON_SOURCE_GAP", "TASK_FAILED", 0),
        ("TASK_SOURCE_MISSING", "SOURCE_GAP", "TASK_SOURCE_MALFORMED", 0),
    ],
)
def test_unknown_credit_requires_matching_frozen_source_gap_reason(
    gold_reason: str,
    reason_class: str,
    submitted_reason: str,
    expected_credit: int,
) -> None:
    gold = _gold_manifest(
        [
            _gold_item(
                "item-1",
                mandatory=True,
                reason=gold_reason,
                reason_class=reason_class,
            )
        ]
    )
    scored = _bound_score_arm(
        _observation([_row("item-1", "UNKNOWN", submitted_reason)]),
        gold,
    )
    assert scored["mandatory_recall_count"] == expected_credit


@pytest.mark.parametrize("state", ["NEEDS_ATTENTION", "UNKNOWN"])
def test_reason_stuffing_cannot_receive_mandatory_recall(state: str) -> None:
    if state == "UNKNOWN":
        gold_reason = "TASK_SOURCE_MISSING"
        reason_class = "SOURCE_GAP"
        stuffed_reason = "TASK_SOURCE_MALFORMED"
    else:
        gold_reason = "TASK_FAILED"
        reason_class = "NON_SOURCE_GAP"
        stuffed_reason = "TASK_CANCELLED"
    gold = _gold_manifest(
        [
            _gold_item(
                "item-1",
                mandatory=True,
                reason=gold_reason,
                reason_class=reason_class,
            )
        ]
    )

    scored = _bound_score_arm(
        _observation([_row("item-1", state, gold_reason, stuffed_reason)]),
        gold,
    )

    assert scored["mandatory_recall_count"] == 0


@pytest.mark.parametrize(
    ("reason", "spoofed_class"),
    [
        ("TASK_FAILED", "SOURCE_GAP"),
        ("TASK_SOURCE_MISSING", "NON_SOURCE_GAP"),
        ("CALLER_INVENTED_GAP", "SOURCE_GAP"),
    ],
)
def test_gold_reason_class_must_match_closed_canonical_taxonomy(
    reason: str,
    spoofed_class: str,
) -> None:
    gold = _gold_manifest(
        [
            _gold_item(
                "item-1",
                mandatory=True,
                reason=reason,
                reason_class=spoofed_class,
            )
        ]
    )

    with pytest.raises(ScoreInputError, match="canonical reason taxonomy"):
        _bound_score_arm(
            _observation([_row("item-1", "UNKNOWN", reason)]),
            gold,
        )
