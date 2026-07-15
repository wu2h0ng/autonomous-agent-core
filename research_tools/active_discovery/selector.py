from __future__ import annotations

import math
from dataclasses import dataclass


PROBABILITY_SCALE = 1_000_000


class SelectorValidationError(ValueError):
    """A probability partition cannot be used by the deterministic selector."""


def _probability(value: int, field: str, *, allow_zero: bool = True) -> int:
    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= PROBABILITY_SCALE
    ):
        raise SelectorValidationError(
            f"{field} is outside the closed probability domain"
        )
    return value


@dataclass(frozen=True, slots=True)
class HypothesisWeight:
    hypothesis_id: str
    probability_micros: int

    def __post_init__(self) -> None:
        if not self.hypothesis_id:
            raise SelectorValidationError("hypothesis_id must be non-empty")
        _probability(
            self.probability_micros, "hypothesis probability", allow_zero=False
        )


@dataclass(frozen=True, slots=True)
class OutcomeLikelihood:
    outcome_label: str
    probability_micros: int

    def __post_init__(self) -> None:
        if not self.outcome_label:
            raise SelectorValidationError("outcome_label must be non-empty")
        _probability(self.probability_micros, "outcome probability")


@dataclass(frozen=True, slots=True)
class HypothesisPrediction:
    hypothesis_id: str
    outcomes: tuple[OutcomeLikelihood, ...]

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.outcomes:
            raise SelectorValidationError(
                "prediction requires a hypothesis and outcomes"
            )
        labels = tuple(item.outcome_label for item in self.outcomes)
        if len(labels) != len(set(labels)):
            raise SelectorValidationError(
                "outcome labels must be unique per hypothesis"
            )
        if sum(item.probability_micros for item in self.outcomes) != PROBABILITY_SCALE:
            raise SelectorValidationError("outcome likelihoods must sum to one")


@dataclass(frozen=True, slots=True)
class CandidateProbe:
    probe_id: str
    stable_order: int
    cost_units: int
    predictions: tuple[HypothesisPrediction, ...]

    def __post_init__(self) -> None:
        if not self.probe_id or not self.predictions:
            raise SelectorValidationError("candidate probe requires id and predictions")
        if isinstance(self.stable_order, bool) or not isinstance(
            self.stable_order, int
        ):
            raise SelectorValidationError("stable_order must be an integer")
        if (
            isinstance(self.cost_units, bool)
            or not isinstance(self.cost_units, int)
            or self.cost_units < 1
        ):
            raise SelectorValidationError("cost_units must be an integer >= 1")
        ids = tuple(item.hypothesis_id for item in self.predictions)
        if len(ids) != len(set(ids)):
            raise SelectorValidationError("predictions must be unique by hypothesis")


@dataclass(frozen=True, slots=True)
class ProbeSelection:
    probe_id: str
    stable_order: int
    information_gain_bits: float
    information_per_cost: float


def _entropy(probabilities: list[float]) -> float:
    return -sum(value * math.log2(value) for value in probabilities if value > 0.0)


def information_gain_bits(
    weights: tuple[HypothesisWeight, ...], candidate: CandidateProbe
) -> float:
    if not weights:
        raise SelectorValidationError("selector requires hypotheses")
    weight_ids = tuple(item.hypothesis_id for item in weights)
    if len(weight_ids) != len(set(weight_ids)):
        raise SelectorValidationError("hypothesis weights must be unique")
    if sum(item.probability_micros for item in weights) != PROBABILITY_SCALE:
        raise SelectorValidationError("hypothesis weights must sum to one")

    predictions = {item.hypothesis_id: item for item in candidate.predictions}
    if set(predictions) != set(weight_ids):
        raise SelectorValidationError(
            "candidate predictions must cover exact hypotheses"
        )

    marginal: dict[str, float] = {}
    conditional_entropy = 0.0
    for hypothesis in weights:
        h_probability = hypothesis.probability_micros / PROBABILITY_SCALE
        outcome_probabilities: list[float] = []
        for outcome in predictions[hypothesis.hypothesis_id].outcomes:
            probability = outcome.probability_micros / PROBABILITY_SCALE
            outcome_probabilities.append(probability)
            marginal[outcome.outcome_label] = (
                marginal.get(outcome.outcome_label, 0.0) + h_probability * probability
            )
        conditional_entropy += h_probability * _entropy(outcome_probabilities)
    information = _entropy(list(marginal.values())) - conditional_entropy
    return max(0.0, information)


def select_probe(
    weights: tuple[HypothesisWeight, ...], candidates: tuple[CandidateProbe, ...]
) -> ProbeSelection:
    if not candidates:
        raise SelectorValidationError("selector requires candidate probes")
    stable_orders = tuple(item.stable_order for item in candidates)
    if len(stable_orders) != len(set(stable_orders)):
        raise SelectorValidationError("candidate stable_order values must be unique")

    scored: list[ProbeSelection] = []
    for candidate in candidates:
        information = information_gain_bits(weights, candidate)
        scored.append(
            ProbeSelection(
                probe_id=candidate.probe_id,
                stable_order=candidate.stable_order,
                information_gain_bits=information,
                information_per_cost=information / candidate.cost_units,
            )
        )
    return min(
        scored,
        key=lambda item: (
            -item.information_per_cost,
            -item.information_gain_bits,
            item.stable_order,
        ),
    )
