from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .canonical import canonical_json, content_digest
from .selector import (
    PROBABILITY_SCALE,
    CandidateProbe,
    HypothesisPrediction,
    HypothesisWeight,
)


class CatalogueValidationError(ValueError):
    """A visible development probe catalogue is not closed or matched."""


@dataclass(frozen=True, slots=True)
class VisibleProbeCandidate:
    probe_id: str
    stable_order: int
    payload_json: str
    cost_units: int
    zero_status_label: str
    nonzero_status_label: str
    predictions: tuple[HypothesisPrediction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id.strip():
            raise CatalogueValidationError("probe_id must be a non-empty string")
        if (
            isinstance(self.stable_order, bool)
            or not isinstance(self.stable_order, int)
            or self.stable_order < 0
        ):
            raise CatalogueValidationError("stable_order must be an integer >= 0")
        if self.cost_units != 1 or isinstance(self.cost_units, bool):
            raise CatalogueValidationError(
                "development candidates require exact unit cost"
            )
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CatalogueValidationError(
                "payload_json must be a canonical JSON object"
            ) from exc
        if (
            not isinstance(payload, dict)
            or canonical_json(payload) != self.payload_json
        ):
            raise CatalogueValidationError(
                "payload_json must be a canonical JSON object"
            )
        labels = {self.zero_status_label, self.nonzero_status_label}
        if (
            any(not isinstance(label, str) or not label for label in labels)
            or len(labels) != 2
        ):
            raise CatalogueValidationError(
                "zero and nonzero status labels must be distinct non-empty strings"
            )
        if not self.predictions:
            raise CatalogueValidationError("candidate requires visible predictions")
        hypothesis_ids = tuple(item.hypothesis_id for item in self.predictions)
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise CatalogueValidationError("prediction hypothesis ids must be unique")
        for prediction in self.predictions:
            prediction_labels = tuple(
                outcome.outcome_label for outcome in prediction.outcomes
            )
            if len(prediction_labels) != 2 or set(prediction_labels) != labels:
                raise CatalogueValidationError(
                    "prediction outcome labels must match the visible status partition"
                )

    @property
    def selector_candidate(self) -> CandidateProbe:
        return CandidateProbe(
            probe_id=self.probe_id,
            stable_order=self.stable_order,
            cost_units=self.cost_units,
            predictions=self.predictions,
        )

    def observed_label(self, status_code: int) -> str:
        return self.zero_status_label if status_code == 0 else self.nonzero_status_label

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    @property
    def candidate_digest(self) -> str:
        return content_digest("visible-probe-candidate", self.to_mapping())


@dataclass(frozen=True, slots=True)
class VisibleProbeCatalogue:
    candidates: tuple[VisibleProbeCandidate, ...]
    initial_weights: tuple[HypothesisWeight, ...]

    def __post_init__(self) -> None:
        if not self.candidates or not self.initial_weights:
            raise CatalogueValidationError(
                "catalogue requires candidates and initial hypothesis weights"
            )
        probe_ids = tuple(item.probe_id for item in self.candidates)
        stable_orders = tuple(item.stable_order for item in self.candidates)
        if len(probe_ids) != len(set(probe_ids)):
            raise CatalogueValidationError("candidate probe ids must be unique")
        if len(stable_orders) != len(set(stable_orders)):
            raise CatalogueValidationError("candidate stable orders must be unique")
        weight_ids = tuple(item.hypothesis_id for item in self.initial_weights)
        if len(weight_ids) != len(set(weight_ids)):
            raise CatalogueValidationError("initial hypothesis ids must be unique")
        if (
            sum(item.probability_micros for item in self.initial_weights)
            != PROBABILITY_SCALE
        ):
            raise CatalogueValidationError("initial hypothesis weights must sum to one")
        for candidate in self.candidates:
            prediction_ids = {item.hypothesis_id for item in candidate.predictions}
            if prediction_ids != set(weight_ids):
                raise CatalogueValidationError(
                    "every candidate must cover the exact visible hypotheses"
                )

    def to_mapping(self) -> dict[str, object]:
        return {
            "candidates": [item.to_mapping() for item in self.candidates],
            "initial_weights": [asdict(item) for item in self.initial_weights],
        }

    @property
    def catalogue_digest(self) -> str:
        return content_digest("visible-probe-catalogue", self.to_mapping())
