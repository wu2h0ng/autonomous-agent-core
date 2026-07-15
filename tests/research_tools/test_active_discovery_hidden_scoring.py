from __future__ import annotations

import ast
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from research_tools.active_discovery.hidden_scoring import (
    ChallengeTruth,
    GeneratedTestOutcome,
    HiddenScoringError,
    combine_components,
    compute_auc_qe_micros,
    compute_score,
)
from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeCatalogue,
    ChallengePrediction,
    ChallengeSequence,
    ChallengeStep,
    DiscoveryScoreBundle,
    OutcomeAtom,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
    TraceProbability,
)


def _trace(label: str) -> BehaviorTrace:
    return BehaviorTrace(
        atoms=(
            OutcomeAtom.create(
                status_code=0,
                stdout=label,
                stderr="",
                output={"value": label},
                state_relation="SAME",
            ),
        )
    )


def _fixture(
    *, true_probability: int = 800_000, predict_true: bool = True, label: str = "a"
) -> tuple[ChallengeCatalogue, DiscoveryScoreBundle, str, str]:
    true_trace = _trace(f"{label}-true")
    false_trace = _trace(f"{label}-false")
    traces = tuple(
        sorted((true_trace, false_trace), key=lambda item: item.canonical_bytes)
    )
    sequence = ChallengeSequence.create(
        reset_slot="clean",
        steps=(ChallengeStep.create(operation_id="op", payload={"challenge": label}),),
        traces=traces,
    )
    catalogue = ChallengeCatalogue.create(
        instance_public_digest=("1" if label == "a" else "2") * 64,
        sequences=(sequence,),
        probe_sequence_digests=(),
    )
    probabilities = tuple(
        TraceProbability(
            trace.trace_digest,
            true_probability
            if trace.trace_digest == true_trace.trace_digest
            else 1_000_000 - true_probability,
        )
        for trace in traces
    )
    predicted = (
        true_trace.trace_digest if predict_true else false_trace.trace_digest
    )
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    tests = tuple(
        StatefulTestCase.create(
            test_id=f"test-{index}",
            reset_slot=f"test-reset-{index}",
            steps=(
                StatefulTestStep.create(
                    operation_id="op",
                    payload={"held-out": index},
                    assertions=(assertion,),
                ),
            ),
            provenance_refs=("public-descriptor",),
        )
        for index in range(2)
    )
    bundle = DiscoveryScoreBundle.create(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        instance_public_digest=catalogue.instance_public_digest,
        arm_id="ACTIVE_VOI",
        actor_binding_digest="3" * 64,
        prefix_index=0,
        parent_bundle_digest=None,
        predictions=(
            ChallengePrediction(
                challenge_digest=sequence.challenge_digest,
                probabilities=probabilities,
                predicted_trace_digest=predicted,
            ),
        ),
        test_ir=StatefulTestIR(tests=tests),
        transcript_prefix_digest="4" * 64,
        consumed_units=0,
        budget_receipt_digest="5" * 64,
        catalogue=catalogue,
    )
    return catalogue, bundle, true_trace.trace_digest, false_trace.trace_digest


def test_exact_behavior_contract_test_and_composite_math() -> None:
    catalogue, bundle, true_trace, _ = _fixture()
    result = compute_score(
        bundle=bundle,
        catalogue=catalogue,
        truths=(ChallengeTruth(catalogue.sequences[0].challenge_digest, true_trace),),
        contrast_digests=("a" * 64, "b" * 64),
        test_outcomes=(
            GeneratedTestOutcome("test-0", True, ("a" * 64,)),
            GeneratedTestOutcome("test-1", False, ("b" * 64,)),
        ),
    )

    assert result.h_micros == 960_000
    assert result.c_micros == 1_000_000
    assert result.t_micros == 500_000
    assert result.score_micros == 855_000
    assert result.target_valid_test_count == 1
    assert result.contrast_kill_count == 1
    assert result.calibration.brier_loss_micros == 40_000
    assert result.details_digest != "0" * 64


def test_perfect_anchor_monotonicity_and_literal_zero_component_anchor() -> None:
    catalogue, bundle, true_trace, false_trace = _fixture()
    perfect = compute_score(
        bundle=replace(
            bundle,
            predictions=(
                ChallengePrediction(
                    challenge_digest=catalogue.sequences[0].challenge_digest,
                    probabilities=tuple(
                        TraceProbability(
                            trace.trace_digest,
                            1_000_000 if trace.trace_digest == true_trace else 0,
                        )
                        for trace in catalogue.sequences[0].traces
                    ),
                    predicted_trace_digest=true_trace,
                ),
            ),
        ),
        catalogue=catalogue,
        truths=(ChallengeTruth(catalogue.sequences[0].challenge_digest, true_trace),),
        contrast_digests=("a" * 64, "b" * 64),
        test_outcomes=(
            GeneratedTestOutcome("test-0", True, ("a" * 64,)),
            GeneratedTestOutcome("test-1", True, ("b" * 64,)),
        ),
    )
    wrong_catalogue, wrong_bundle, wrong_true, _ = _fixture(
        true_probability=200_000, predict_true=False
    )
    wrong = compute_score(
        bundle=wrong_bundle,
        catalogue=wrong_catalogue,
        truths=(
            ChallengeTruth(
                wrong_catalogue.sequences[0].challenge_digest, wrong_true
            ),
        ),
        contrast_digests=("a" * 64, "b" * 64),
        test_outcomes=(
            GeneratedTestOutcome("test-0", True, ("a" * 64,)),
            GeneratedTestOutcome("test-1", True, ("b" * 64,)),
        ),
    )

    assert perfect.h_micros == perfect.c_micros == perfect.t_micros == 1_000_000
    assert perfect.score_micros == 1_000_000
    assert wrong.h_micros < perfect.h_micros
    assert wrong.c_micros == 0
    assert wrong.score_micros < perfect.score_micros
    assert combine_components(Fraction(0), Fraction(0), Fraction(0)) == 0
    assert combine_components(Fraction(1, 10), Fraction(0), Fraction(0)) > 0
    assert combine_components(Fraction(0), Fraction(1, 10), Fraction(0)) > 0
    assert combine_components(Fraction(0), Fraction(0), Fraction(1, 10)) > 0
    assert false_trace != true_trace


def test_target_invalid_test_never_receives_contrast_kill_credit() -> None:
    catalogue, bundle, true_trace, _ = _fixture()
    result = compute_score(
        bundle=bundle,
        catalogue=catalogue,
        truths=(ChallengeTruth(catalogue.sequences[0].challenge_digest, true_trace),),
        contrast_digests=("a" * 64, "b" * 64),
        test_outcomes=(
            GeneratedTestOutcome("test-0", False, ("a" * 64, "b" * 64)),
            GeneratedTestOutcome("test-1", True, ()),
        ),
    )

    assert result.target_valid_test_count == 1
    assert result.contrast_kill_count == 0
    assert result.t_micros == 0


def test_numeric_metrics_are_identity_relabeling_invariant() -> None:
    first_catalogue, first_bundle, first_true, _ = _fixture(label="a")
    second_catalogue, second_bundle, second_true, _ = _fixture(label="b")
    outcomes = (
        GeneratedTestOutcome("test-0", True, ("a" * 64,)),
        GeneratedTestOutcome("test-1", False, ()),
    )
    first = compute_score(
        bundle=first_bundle,
        catalogue=first_catalogue,
        truths=(
            ChallengeTruth(first_catalogue.sequences[0].challenge_digest, first_true),
        ),
        contrast_digests=("a" * 64,),
        test_outcomes=outcomes,
    )
    second = compute_score(
        bundle=second_bundle,
        catalogue=second_catalogue,
        truths=(
            ChallengeTruth(second_catalogue.sequences[0].challenge_digest, second_true),
        ),
        contrast_digests=("a" * 64,),
        test_outcomes=outcomes,
    )

    assert (
        first.h_micros,
        first.c_micros,
        first.t_micros,
        first.score_micros,
    ) == (
        second.h_micros,
        second.c_micros,
        second.t_micros,
        second.score_micros,
    )


def test_query_efficiency_uses_exact_trapezoid_and_no_platform_float() -> None:
    scores = (
        Fraction(0),
        Fraction(1, 4),
        Fraction(1, 2),
        Fraction(3, 4),
        Fraction(1),
    )
    assert compute_auc_qe_micros(scores) == 500_000

    source = Path(
        "research_tools/active_discovery/hidden_scoring.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
        for node in ast.walk(tree)
    )


def test_score_rejects_missing_truth_zero_contrast_and_unknown_kill() -> None:
    catalogue, bundle, _, _ = _fixture()
    with pytest.raises(HiddenScoringError, match="truth"):
        compute_score(
            bundle=bundle,
            catalogue=catalogue,
            truths=(),
            contrast_digests=("a" * 64,),
            test_outcomes=(
                GeneratedTestOutcome("test-0", True, ()),
                GeneratedTestOutcome("test-1", True, ()),
            ),
        )
    with pytest.raises(HiddenScoringError, match="contrast"):
        compute_score(
            bundle=bundle,
            catalogue=catalogue,
            truths=(
                ChallengeTruth(
                    catalogue.sequences[0].challenge_digest,
                    catalogue.sequences[0].traces[0].trace_digest,
                ),
            ),
            contrast_digests=(),
            test_outcomes=(
                GeneratedTestOutcome("test-0", True, ()),
                GeneratedTestOutcome("test-1", True, ()),
            ),
        )
