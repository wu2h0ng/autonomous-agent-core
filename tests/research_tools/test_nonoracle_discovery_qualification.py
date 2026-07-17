from __future__ import annotations

from research_tools.nonoracle_discovery.baselines import (
    correlation_baseline,
    finite_screen_baseline,
    pooled_shift_baseline,
)
from research_tools.nonoracle_discovery.contracts import DirectedAncestryHypothesis
from research_tools.nonoracle_discovery.qualification import (
    confounded_indirect_fixture,
    run_synthetic_qualification,
)


def test_qualification_contains_load_bearing_confounded_and_unstable_cases() -> None:
    receipt = run_synthetic_qualification()

    assert receipt.mode == "SYNTHETIC_QUALIFICATION_NOT_EVIDENCE"
    assert receipt.mechanism_recovers_true_relation
    assert receipt.correlation_selects_confounded_relation
    assert receipt.pooled_shift_selects_unstable_artifact
    assert receipt.mechanism_rejects_unstable_artifact
    assert receipt.expected_hypotheses == (("v0", "v2"),)
    assert receipt.mechanism_hypotheses == receipt.expected_hypotheses
    assert ("v1", "v0") not in receipt.mechanism_hypotheses
    assert {arm.arm_id for arm in receipt.arm_scores} == {
        "INTERVENTION_STABILITY",
        "OBSERVATIONAL_ABS_CORRELATION_MATCHED_K",
        "FIXED_THRESHOLD_POOLED_MEAN_SHIFT",
        "FINITE_SCREEN_ALL_LEGAL_PAIRS",
    }
    assert all(0 <= arm.f1_micros <= 1_000_000 for arm in receipt.arm_scores)


def test_all_baselines_share_public_view_and_hypothesis_contract() -> None:
    fixture = confounded_indirect_fixture()
    arms = (
        correlation_baseline(fixture.dataset, k=1),
        pooled_shift_baseline(fixture.dataset, threshold_micros=500_000),
        finite_screen_baseline(fixture.dataset),
    )

    assert all(all(isinstance(item, DirectedAncestryHypothesis) for item in arm) for arm in arms)
    assert all(arm for arm in arms)
    assert len(arms[2]) == len(fixture.dataset.conditions) * (len(fixture.dataset.variable_ids) - 1)


def test_correlation_and_pooled_shift_fail_in_declared_distinct_ways() -> None:
    fixture = confounded_indirect_fixture()
    correlation_pairs = {
        (item.source, item.target) for item in correlation_baseline(fixture.dataset, k=1)
    }
    pooled_pairs = {
        (item.source, item.target)
        for item in pooled_shift_baseline(fixture.dataset, threshold_micros=500_000)
    }

    assert fixture.confounded_relation in correlation_pairs
    assert fixture.unstable_artifact_relation in pooled_pairs
    assert fixture.true_relation not in correlation_pairs


def test_matched_k_correlation_is_tie_inclusive_not_name_selected() -> None:
    fixture = confounded_indirect_fixture()
    values = correlation_baseline(fixture.dataset, k=1)
    cutoff = values[0].stability_micros

    assert all(item.stability_micros >= cutoff for item in values)
    assert len(values) > 1


def test_qualification_receipt_is_deterministic_and_contains_no_result_verdict() -> None:
    first = run_synthetic_qualification()
    second = run_synthetic_qualification()

    assert first == second
    assert first.receipt_digest == second.receipt_digest
    assert not hasattr(first, "research_verdict")
    assert not hasattr(first, "real_score")
