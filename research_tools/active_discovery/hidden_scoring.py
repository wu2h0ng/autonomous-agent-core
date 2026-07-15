from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, localcontext
from fractions import Fraction

from .canonical import content_digest
from .scoring_contracts import (
    PROBABILITY_SCALE,
    ChallengeCatalogue,
    DiscoveryScoreBundle,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HiddenScoringError(ValueError):
    """Behavior-grounded score inputs are missing, inconsistent, or non-canonical."""


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise HiddenScoringError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _micros(value: Fraction) -> int:
    if value < 0 or value > 1:
        raise HiddenScoringError("score fraction must be in [0,1]")
    return value.numerator * PROBABILITY_SCALE // value.denominator


@dataclass(frozen=True, slots=True)
class ChallengeTruth:
    challenge_digest: str
    true_trace_digest: str

    def __post_init__(self) -> None:
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.true_trace_digest, "true_trace_digest")


@dataclass(frozen=True, slots=True)
class GeneratedTestOutcome:
    test_id: str
    target_valid: bool
    killed_contrast_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.test_id, str) or not self.test_id:
            raise HiddenScoringError("test_id must be non-empty")
        if not isinstance(self.target_valid, bool):
            raise HiddenScoringError("target_valid must be a boolean")
        for value in self.killed_contrast_digests:
            _digest(value, "killed_contrast_digest")
        if len(self.killed_contrast_digests) != len(
            set(self.killed_contrast_digests)
        ):
            raise HiddenScoringError("killed contrast identities must be unique")


@dataclass(frozen=True, slots=True)
class CalibrationDiagnostics:
    brier_loss_micros: int
    log_loss_micros: int
    ece_micros: int
    correct_contract_count: int
    incorrect_contract_count: int
    correct_contract_mean_probability_micros: int
    incorrect_contract_mean_probability_micros: int

    def to_mapping(self) -> dict[str, int]:
        return {
            "brier_loss_micros": self.brier_loss_micros,
            "log_loss_micros": self.log_loss_micros,
            "ece_micros": self.ece_micros,
            "correct_contract_count": self.correct_contract_count,
            "incorrect_contract_count": self.incorrect_contract_count,
            "correct_contract_mean_probability_micros": self.correct_contract_mean_probability_micros,
            "incorrect_contract_mean_probability_micros": self.incorrect_contract_mean_probability_micros,
        }

    @property
    def diagnostics_digest(self) -> str:
        return content_digest("score-calibration-diagnostics/v1", self.to_mapping())


@dataclass(frozen=True, slots=True)
class ScoreComputation:
    h_fraction: Fraction
    c_fraction: Fraction
    t_fraction: Fraction
    score_fraction: Fraction
    h_micros: int
    c_micros: int
    t_micros: int
    score_micros: int
    target_valid_test_count: int
    submitted_test_count: int
    contrast_kill_count: int
    contrast_count: int
    challenge_count: int
    calibration: CalibrationDiagnostics

    def to_mapping(self) -> dict[str, object]:
        return {
            "h_micros": self.h_micros,
            "c_micros": self.c_micros,
            "t_micros": self.t_micros,
            "score_micros": self.score_micros,
            "target_valid_test_count": self.target_valid_test_count,
            "submitted_test_count": self.submitted_test_count,
            "contrast_kill_count": self.contrast_kill_count,
            "contrast_count": self.contrast_count,
            "challenge_count": self.challenge_count,
            "calibration": self.calibration.to_mapping(),
        }

    @property
    def details_digest(self) -> str:
        return content_digest("hidden-score-computation/v2", self.to_mapping())


def combine_components(
    h_fraction: Fraction, c_fraction: Fraction, t_fraction: Fraction
) -> Fraction:
    for value in (h_fraction, c_fraction, t_fraction):
        if not isinstance(value, Fraction) or not 0 <= value <= 1:
            raise HiddenScoringError("component fractions must be Fractions in [0,1]")
    return h_fraction / 2 + c_fraction / 4 + t_fraction / 4


def _deterministic_log_loss_micros(true_probabilities: tuple[int, ...]) -> int:
    total = Decimal(0)
    with localcontext() as context:
        context.prec = 60
        scale = Decimal(PROBABILITY_SCALE)
        for probability in true_probabilities:
            floored = max(1, probability)
            total += -(Decimal(floored) / scale).ln()
        mean = total / Decimal(len(true_probabilities))
        return int((mean * scale).to_integral_value(rounding=ROUND_FLOOR))


def _ece_fraction(
    confidences: tuple[int, ...], correctness: tuple[bool, ...]
) -> Fraction:
    count = len(confidences)
    bins: list[list[int]] = [[] for _ in range(10)]
    for index, confidence in enumerate(confidences):
        bin_index = min(9, confidence * 10 // PROBABILITY_SCALE)
        bins[bin_index].append(index)
    result = Fraction(0)
    for indices in bins:
        if not indices:
            continue
        bin_count = len(indices)
        accuracy = Fraction(sum(correctness[index] for index in indices), bin_count)
        confidence = Fraction(
            sum(confidences[index] for index in indices),
            bin_count * PROBABILITY_SCALE,
        )
        result += Fraction(bin_count, count) * abs(accuracy - confidence)
    return result


def compute_score(
    *,
    bundle: DiscoveryScoreBundle,
    catalogue: ChallengeCatalogue,
    truths: tuple[ChallengeTruth, ...],
    contrast_digests: tuple[str, ...],
    test_outcomes: tuple[GeneratedTestOutcome, ...],
) -> ScoreComputation:
    # Reparse the sealed bytes so dataclass replacement cannot bypass catalogue checks.
    validated_bundle = DiscoveryScoreBundle.from_mapping(bundle.to_mapping(), catalogue)
    expected_challenges = {item.challenge_digest: item for item in catalogue.sequences}
    truth_map = {item.challenge_digest: item.true_trace_digest for item in truths}
    if len(truth_map) != len(truths) or set(truth_map) != set(expected_challenges):
        raise HiddenScoringError("truth records must cover every challenge exactly once")
    for challenge_digest, true_trace in truth_map.items():
        trace_ids = {
            item.trace_digest for item in expected_challenges[challenge_digest].traces
        }
        if true_trace not in trace_ids:
            raise HiddenScoringError("truth trace is outside the public trace universe")

    for value in contrast_digests:
        _digest(value, "contrast_digest")
    if not contrast_digests:
        raise HiddenScoringError("at least one admissible contrast is required")
    if len(contrast_digests) != len(set(contrast_digests)):
        raise HiddenScoringError("contrast identities must be unique")
    contrast_set = set(contrast_digests)

    expected_tests = {item.test_id for item in validated_bundle.test_ir.tests}
    outcome_map = {item.test_id: item for item in test_outcomes}
    if len(outcome_map) != len(test_outcomes) or set(outcome_map) != expected_tests:
        raise HiddenScoringError("test outcomes must cover submitted tests exactly once")
    unknown_kills = {
        value
        for outcome in test_outcomes
        for value in outcome.killed_contrast_digests
        if value not in contrast_set
    }
    if unknown_kills:
        raise HiddenScoringError("test outcome names an unknown contrast")

    predictions = {
        item.challenge_digest: item for item in validated_bundle.predictions
    }
    quadratic_scores: list[Fraction] = []
    contract_correctness: list[bool] = []
    contract_confidences: list[int] = []
    true_probabilities: list[int] = []
    for challenge_digest in expected_challenges:
        prediction = predictions[challenge_digest]
        probability_map = {
            item.trace_digest: item.probability_micros
            for item in prediction.probabilities
        }
        true_trace = truth_map[challenge_digest]
        squared_error = sum(
            (probability - (PROBABILITY_SCALE if trace == true_trace else 0)) ** 2
            for trace, probability in probability_map.items()
        )
        quadratic_scores.append(
            Fraction(1) - Fraction(squared_error, 2 * PROBABILITY_SCALE**2)
        )
        correct = prediction.predicted_trace_digest == true_trace
        contract_correctness.append(correct)
        contract_confidences.append(
            probability_map[prediction.predicted_trace_digest]
        )
        true_probabilities.append(probability_map[true_trace])

    challenge_count = len(expected_challenges)
    h_fraction = sum(quadratic_scores, Fraction(0)) / challenge_count
    c_fraction = Fraction(sum(contract_correctness), challenge_count)
    target_valid = tuple(item for item in test_outcomes if item.target_valid)
    credited_kills = {
        contrast
        for item in target_valid
        for contrast in item.killed_contrast_digests
    }
    precision = Fraction(len(target_valid), len(test_outcomes))
    recall = Fraction(len(credited_kills), len(contrast_digests))
    t_fraction = (
        Fraction(0)
        if precision == 0 or recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    score_fraction = combine_components(h_fraction, c_fraction, t_fraction)

    correct_probabilities = tuple(
        contract_confidences[index]
        for index, correct in enumerate(contract_correctness)
        if correct
    )
    incorrect_probabilities = tuple(
        contract_confidences[index]
        for index, correct in enumerate(contract_correctness)
        if not correct
    )
    calibration = CalibrationDiagnostics(
        brier_loss_micros=_micros(1 - h_fraction),
        log_loss_micros=_deterministic_log_loss_micros(tuple(true_probabilities)),
        ece_micros=_micros(
            _ece_fraction(tuple(contract_confidences), tuple(contract_correctness))
        ),
        correct_contract_count=len(correct_probabilities),
        incorrect_contract_count=len(incorrect_probabilities),
        correct_contract_mean_probability_micros=(
            sum(correct_probabilities) // len(correct_probabilities)
            if correct_probabilities
            else 0
        ),
        incorrect_contract_mean_probability_micros=(
            sum(incorrect_probabilities) // len(incorrect_probabilities)
            if incorrect_probabilities
            else 0
        ),
    )
    return ScoreComputation(
        h_fraction=h_fraction,
        c_fraction=c_fraction,
        t_fraction=t_fraction,
        score_fraction=score_fraction,
        h_micros=_micros(h_fraction),
        c_micros=_micros(c_fraction),
        t_micros=_micros(t_fraction),
        score_micros=_micros(score_fraction),
        target_valid_test_count=len(target_valid),
        submitted_test_count=len(test_outcomes),
        contrast_kill_count=len(credited_kills),
        contrast_count=len(contrast_digests),
        challenge_count=challenge_count,
        calibration=calibration,
    )


def compute_auc_qe_micros(score_fractions: tuple[Fraction, ...]) -> int:
    if len(score_fractions) != 5:
        raise HiddenScoringError("AUC_QE requires exact prefix scores k=0..4")
    for score in score_fractions:
        if not isinstance(score, Fraction) or not 0 <= score <= 1:
            raise HiddenScoringError("AUC_QE scores must be Fractions in [0,1]")
    area = (
        score_fractions[0] / 2
        + score_fractions[1]
        + score_fractions[2]
        + score_fractions[3]
        + score_fractions[4] / 2
    ) / 4
    return _micros(area)
