from __future__ import annotations

import math

from research_tools.active_discovery.selector import (
    CandidateProbe,
    HypothesisPrediction,
    HypothesisWeight,
    OutcomeLikelihood,
    select_probe,
)


def _deterministic(hypothesis_id: str, outcome: str) -> HypothesisPrediction:
    return HypothesisPrediction(
        hypothesis_id=hypothesis_id,
        outcomes=(OutcomeLikelihood(outcome, 1_000_000),),
    )


def test_selector_chooses_hand_computed_one_bit_partition() -> None:
    weights = (
        HypothesisWeight("h-a", 500_000),
        HypothesisWeight("h-b", 500_000),
    )
    separating = CandidateProbe(
        "probe-separating",
        stable_order=1,
        cost_units=1,
        predictions=(_deterministic("h-a", "yes"), _deterministic("h-b", "no")),
    )
    uninformative = CandidateProbe(
        "probe-same",
        stable_order=0,
        cost_units=1,
        predictions=(_deterministic("h-a", "same"), _deterministic("h-b", "same")),
    )

    selected = select_probe(weights, (uninformative, separating))

    assert selected.probe_id == "probe-separating"
    assert math.isclose(selected.information_gain_bits, 1.0)


def test_selector_ranking_is_invariant_to_hypothesis_and_outcome_labels() -> None:
    original_weights = (
        HypothesisWeight("original-a", 500_000),
        HypothesisWeight("original-b", 500_000),
    )
    renamed_weights = (
        HypothesisWeight("opaque-x", 500_000),
        HypothesisWeight("opaque-y", 500_000),
    )
    original = (
        CandidateProbe(
            "uninformative-original",
            0,
            1,
            (
                _deterministic("original-a", "same"),
                _deterministic("original-b", "same"),
            ),
        ),
        CandidateProbe(
            "informative-original",
            1,
            1,
            (
                _deterministic("original-a", "left"),
                _deterministic("original-b", "right"),
            ),
        ),
    )
    renamed = (
        CandidateProbe(
            "uninformative-renamed",
            0,
            1,
            (_deterministic("opaque-x", "z"), _deterministic("opaque-y", "z")),
        ),
        CandidateProbe(
            "informative-renamed",
            1,
            1,
            (_deterministic("opaque-x", "q"), _deterministic("opaque-y", "p")),
        ),
    )

    original_selection = select_probe(original_weights, original)
    renamed_selection = select_probe(renamed_weights, renamed)

    assert original_selection.stable_order == renamed_selection.stable_order == 1
    assert math.isclose(
        original_selection.information_gain_bits,
        renamed_selection.information_gain_bits,
    )
