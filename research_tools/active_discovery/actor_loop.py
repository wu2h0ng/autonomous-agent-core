from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Mapping

from .canonical import canonical_json, content_digest
from .catalogue import VisibleProbeCandidate
from .contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from .scoring_contracts import (
    ChallengeCatalogue,
    ChallengePrediction,
    DiscoveryScoreBundle,
    ScoringContractError,
    StatefulTestIR,
)
from .selector import (
    PROBABILITY_SCALE,
    CandidateProbe,
    HypothesisPrediction,
    HypothesisWeight,
    OutcomeLikelihood,
    SelectorValidationError,
    select_probe,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ORACLE_KEY_TOKENS = frozenset(
    {
        "config",
        "family",
        "groundtruth",
        "hidden",
        "oracle",
        "referee",
        "score",
        "secret",
        "strength",
    }
)


class ActorLoopError(ValueError):
    """The active actor escaped its public, deterministic behavior contract."""


def _closed(raw: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise ActorLoopError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ActorLoopError(f"{label} is missing fields: {sorted(missing)}")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ActorLoopError(f"{field} must be a non-empty NUL-free string")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ActorLoopError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _probability(value: Any, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= PROBABILITY_SCALE
    ):
        raise ActorLoopError(f"{field} is outside the closed probability domain")
    return value


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _reject_oracle_shaped_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ActorLoopError("callback mappings require string field names")
            normalized = _normalized_key(key)
            if any(token in normalized for token in _ORACLE_KEY_TOKENS):
                raise ActorLoopError(f"oracle-shaped callback field is forbidden: {key}")
            _reject_oracle_shaped_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_oracle_shaped_fields(nested)


@dataclass(frozen=True, slots=True)
class PublicProbePayload:
    probe_id: str
    stable_order: int
    operation_id: str
    payload_json: str
    cost_units: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"probe_id", "stable_order", "operation_id", "payload_json", "cost_units"}
    )

    def __post_init__(self) -> None:
        _name(self.probe_id, "probe_id")
        _name(self.operation_id, "operation_id")
        if (
            isinstance(self.stable_order, bool)
            or not isinstance(self.stable_order, int)
            or self.stable_order < 0
        ):
            raise ActorLoopError("stable_order must be an integer >= 0")
        if self.cost_units != 1 or isinstance(self.cost_units, bool):
            raise ActorLoopError("active actor supports exact unit-cost probes")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ActorLoopError("payload_json must be canonical JSON object text") from exc
        if not isinstance(payload, dict) or canonical_json(payload) != self.payload_json:
            raise ActorLoopError("payload_json must be canonical JSON object text")

    def to_mapping(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "stable_order": self.stable_order,
            "operation_id": self.operation_id,
            "payload_json": self.payload_json,
            "cost_units": self.cost_units,
        }


@dataclass(frozen=True, slots=True)
class BehaviorHypothesis:
    hypothesis_id: str
    description: str
    probability_micros: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"hypothesis_id", "description", "probability_micros"}
    )

    def __post_init__(self) -> None:
        _name(self.hypothesis_id, "hypothesis_id")
        _name(self.description, "description")
        _probability(self.probability_micros, "hypothesis probability")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> BehaviorHypothesis:
        _closed(raw, cls.FIELDS, "behavior hypothesis")
        return cls(
            hypothesis_id=raw["hypothesis_id"],
            description=raw["description"],
            probability_micros=raw["probability_micros"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "description": self.description,
            "probability_micros": self.probability_micros,
        }


@dataclass(frozen=True, slots=True)
class ProbeHypothesisLikelihood:
    probe_id: str
    hypothesis_id: str
    outcomes: tuple[OutcomeLikelihood, ...]

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"probe_id", "hypothesis_id", "outcomes"}
    )

    def __post_init__(self) -> None:
        _name(self.probe_id, "probe_id")
        _name(self.hypothesis_id, "hypothesis_id")
        if not self.outcomes:
            raise ActorLoopError("probe likelihood requires outcome probabilities")
        labels = tuple(item.outcome_label for item in self.outcomes)
        if len(labels) != len(set(labels)):
            raise ActorLoopError("probe likelihood outcome labels must be unique")
        if sum(item.probability_micros for item in self.outcomes) != PROBABILITY_SCALE:
            raise ActorLoopError("probe likelihoods must sum exactly to 1_000_000")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProbeHypothesisLikelihood:
        _closed(raw, cls.FIELDS, "probe hypothesis likelihood")
        outcomes = raw["outcomes"]
        if not isinstance(outcomes, list):
            raise ActorLoopError("probe likelihood outcomes must be a list")
        parsed: list[OutcomeLikelihood] = []
        try:
            for item in outcomes:
                if not isinstance(item, Mapping):
                    raise ActorLoopError("probe outcome likelihood is invalid")
                _closed(
                    item,
                    frozenset({"outcome_label", "probability_micros"}),
                    "outcome likelihood",
                )
                parsed.append(
                    OutcomeLikelihood(
                        outcome_label=item["outcome_label"],
                        probability_micros=item["probability_micros"],
                    )
                )
        except (KeyError, SelectorValidationError) as exc:
            raise ActorLoopError("probe outcome likelihood is invalid") from exc
        return cls(raw["probe_id"], raw["hypothesis_id"], tuple(parsed))

    def to_mapping(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "hypothesis_id": self.hypothesis_id,
            "outcomes": [
                {
                    "outcome_label": item.outcome_label,
                    "probability_micros": item.probability_micros,
                }
                for item in self.outcomes
            ],
        }


@dataclass(frozen=True, slots=True)
class ActorModelOutput:
    hypotheses: tuple[BehaviorHypothesis, ...]
    probe_likelihoods: tuple[ProbeHypothesisLikelihood, ...]
    selected_probe_id: str
    predictions: tuple[ChallengePrediction, ...]
    test_ir: StatefulTestIR

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "hypotheses",
            "probe_likelihoods",
            "selected_probe_id",
            "predictions",
            "test_ir",
        }
    )

    def __post_init__(self) -> None:
        _name(self.selected_probe_id, "selected_probe_id")
        if len(self.hypotheses) < 2 or any(
            not isinstance(item, BehaviorHypothesis) for item in self.hypotheses
        ):
            raise ActorLoopError("actor must maintain competing behavior hypotheses")
        ids = tuple(item.hypothesis_id for item in self.hypotheses)
        if len(ids) != len(set(ids)):
            raise ActorLoopError("behavior hypothesis ids must be unique")
        if sum(item.probability_micros for item in self.hypotheses) != PROBABILITY_SCALE:
            raise ActorLoopError("behavior hypothesis weights must sum to 1_000_000")
        if not self.probe_likelihoods or any(
            not isinstance(item, ProbeHypothesisLikelihood)
            for item in self.probe_likelihoods
        ):
            raise ActorLoopError("actor must emit per-probe likelihoods")
        if not self.predictions or any(
            not isinstance(item, ChallengePrediction) for item in self.predictions
        ):
            raise ActorLoopError("actor must emit held-out behavior predictions")
        if not isinstance(self.test_ir, StatefulTestIR):
            raise ActorLoopError("actor must emit StatefulTestIR")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ActorModelOutput:
        _reject_oracle_shaped_fields(raw)
        _closed(raw, cls.FIELDS, "actor model output")
        for field in ("hypotheses", "probe_likelihoods", "predictions"):
            if not isinstance(raw[field], list):
                raise ActorLoopError(f"{field} must be a list")
        if not isinstance(raw["test_ir"], Mapping):
            raise ActorLoopError("test_ir must be an object")
        try:
            return cls(
                hypotheses=tuple(
                    BehaviorHypothesis.from_mapping(item)
                    for item in raw["hypotheses"]
                ),
                probe_likelihoods=tuple(
                    ProbeHypothesisLikelihood.from_mapping(item)
                    for item in raw["probe_likelihoods"]
                ),
                selected_probe_id=raw["selected_probe_id"],
                predictions=tuple(
                    ChallengePrediction.from_mapping(item)
                    for item in raw["predictions"]
                ),
                test_ir=StatefulTestIR.from_mapping(raw["test_ir"]),
            )
        except (ScoringContractError, TypeError) as exc:
            raise ActorLoopError("actor score output is invalid") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "hypotheses": [item.to_mapping() for item in self.hypotheses],
            "probe_likelihoods": [
                item.to_mapping() for item in self.probe_likelihoods
            ],
            "selected_probe_id": self.selected_probe_id,
            "predictions": [item.to_mapping() for item in self.predictions],
            "test_ir": self.test_ir.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ActorLoopReceipt:
    prefix_bundles: tuple[DiscoveryScoreBundle, ...]
    selected_probe_ids: tuple[str, ...]
    observations: tuple[ProbeObservation, ...]
    decision_digests: tuple[str, ...]

    @property
    def receipt_digest(self) -> str:
        return content_digest(
            "active-discovery-actor-loop/v1",
            {
                "prefix_bundle_digests": [
                    item.bundle_digest for item in self.prefix_bundles
                ],
                "selected_probe_ids": list(self.selected_probe_ids),
                "observation_digests": [
                    item.observation_digest for item in self.observations
                ],
                "decision_digests": list(self.decision_digests),
            },
        )


@dataclass(frozen=True, slots=True)
class HiddenConfigurationPolicyTrace:
    configuration_digest: str
    voi_probe_ids: tuple[str, ...]
    systematic_probe_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.configuration_digest, "configuration_digest")
        if len(self.voi_probe_ids) != len(self.systematic_probe_ids):
            raise ActorLoopError("policy traces must have matched probe budgets")
        if not self.voi_probe_ids:
            raise ActorLoopError("policy traces must contain probe choices")
        for field_name, values in (
            ("voi_probe_ids", self.voi_probe_ids),
            ("systematic_probe_ids", self.systematic_probe_ids),
        ):
            if any(not isinstance(item, str) or not item for item in values):
                raise ActorLoopError(f"{field_name} must contain probe ids")


@dataclass(frozen=True, slots=True)
class StaticReductionAudit:
    disposition: str
    all_configurations_equal: bool
    legal_configuration_count: int
    counterexample_configuration_digests: tuple[str, ...]


def audit_static_voi_reduction(
    legal_configuration_domain: tuple[HiddenConfigurationPolicyTrace, ...],
) -> StaticReductionAudit:
    """Classify exact policy equality without exposing the domain to the actor."""

    if not legal_configuration_domain:
        raise ActorLoopError("static reduction audit requires the legal domain")
    digests = tuple(item.configuration_digest for item in legal_configuration_domain)
    if len(digests) != len(set(digests)):
        raise ActorLoopError("legal configuration digests must be unique")
    counterexamples = tuple(
        item.configuration_digest
        for item in legal_configuration_domain
        if item.voi_probe_ids != item.systematic_probe_ids
    )
    reduced = not counterexamples
    return StaticReductionAudit(
        disposition=(
            "PARK_ACTIVE_ADAPTATION"
            if reduced
            else "ACTIVE_ADAPTATION_NOT_STATICALLY_REDUCED"
        ),
        all_configurations_equal=reduced,
        legal_configuration_count=len(legal_configuration_domain),
        counterexample_configuration_digests=counterexamples,
    )


def _coerce_model_output(value: object) -> ActorModelOutput:
    if isinstance(value, ActorModelOutput):
        return value
    if not isinstance(value, Mapping):
        raise ActorLoopError("model callback must return typed output or a mapping")
    return ActorModelOutput.from_mapping(value)


def _validate_decision(
    output: ActorModelOutput,
    legal_probes: tuple[PublicProbePayload, ...],
) -> None:
    legal_ids = {item.probe_id for item in legal_probes}
    by_pair = {
        (item.probe_id, item.hypothesis_id): item
        for item in output.probe_likelihoods
    }
    expected_pairs = {
        (probe.probe_id, hypothesis.hypothesis_id)
        for probe in legal_probes
        for hypothesis in output.hypotheses
    }
    if len(by_pair) != len(output.probe_likelihoods) or set(by_pair) != expected_pairs:
        raise ActorLoopError(
            "model likelihoods must cover every exact legal probe/hypothesis pair"
        )
    if output.selected_probe_id not in legal_ids:
        raise ActorLoopError("model selected an illegal probe")

    candidates: list[CandidateProbe] = []
    for probe in legal_probes:
        predictions: list[HypothesisPrediction] = []
        label_partition: frozenset[str] | None = None
        for hypothesis in output.hypotheses:
            likelihood = by_pair[(probe.probe_id, hypothesis.hypothesis_id)]
            labels = frozenset(item.outcome_label for item in likelihood.outcomes)
            if label_partition is None:
                label_partition = labels
            elif labels != label_partition:
                raise ActorLoopError(
                    "hypotheses must predict one shared outcome partition per probe"
                )
            predictions.append(
                HypothesisPrediction(hypothesis.hypothesis_id, likelihood.outcomes)
            )
        candidates.append(
            CandidateProbe(
                probe_id=probe.probe_id,
                stable_order=probe.stable_order,
                cost_units=probe.cost_units,
                predictions=tuple(predictions),
            )
        )
    weights = tuple(
        HypothesisWeight(item.hypothesis_id, item.probability_micros)
        for item in output.hypotheses
    )
    try:
        expected = select_probe(weights, tuple(candidates)).probe_id
    except SelectorValidationError as exc:
        raise ActorLoopError("model-generated VOI domain is invalid") from exc
    if output.selected_probe_id != expected:
        raise ActorLoopError("model probe choice does not match its generated VOI choice")


def _validated_observation(
    observation: ProbeObservation, request: ProbeRequest
) -> ProbeObservation:
    if not isinstance(observation, ProbeObservation):
        raise ActorLoopError("probe executor must return ProbeObservation")
    if (
        observation.episode_id != request.episode_id
        or observation.step_index != request.step_index
        or observation.probe_id != request.probe_id
        or observation.before_state_digest != request.expected_state_digest
    ):
        raise ActorLoopError("probe observation does not bind the exact request")
    try:
        output = json.loads(observation.output_json)
    except json.JSONDecodeError as exc:
        raise ActorLoopError("probe observation output is invalid") from exc
    recreated = ProbeObservation.create(
        episode_id=observation.episode_id,
        step_index=observation.step_index,
        probe_id=observation.probe_id,
        status_code=observation.status_code,
        stdout=observation.stdout,
        stderr=observation.stderr,
        output=output,
        before_state_digest=observation.before_state_digest,
        after_state_digest=observation.after_state_digest,
    )
    if recreated != observation:
        raise ActorLoopError("probe observation digest is not self-consistent")
    return observation


def run_actor_loop(
    *,
    experiment_id: str,
    episode_id: str,
    arm_id: str,
    actor_binding_digest: str,
    descriptor: PublicEnvironmentDescriptor,
    candidates: tuple[VisibleProbeCandidate, ...],
    challenge_catalogue: ChallengeCatalogue,
    model_callback: Callable[
        [
            PublicEnvironmentDescriptor,
            tuple[PublicProbePayload, ...],
            tuple[ProbeObservation, ...],
        ],
        ActorModelOutput | Mapping[str, Any],
    ],
    execute_probe: Callable[[ProbeRequest], ProbeObservation],
    probe_budget: int = 4,
) -> ActorLoopReceipt:
    """Build an inert k=0..4 actor chain from public observations only."""

    _name(experiment_id, "experiment_id")
    _name(episode_id, "episode_id")
    _name(arm_id, "arm_id")
    _digest(actor_binding_digest, "actor_binding_digest")
    if not isinstance(descriptor, PublicEnvironmentDescriptor):
        raise ActorLoopError("descriptor must be PublicEnvironmentDescriptor")
    if challenge_catalogue.instance_public_digest != descriptor.descriptor_digest:
        raise ActorLoopError("challenge catalogue does not bind the public descriptor")
    if probe_budget != 4 or isinstance(probe_budget, bool):
        raise ActorLoopError("successor actor requires the fixed four-probe budget")
    if len(candidates) < probe_budget + 1:
        raise ActorLoopError("k=0..4 decisions require at least five legal probes")

    public_probes = tuple(
        sorted(
            (
                PublicProbePayload(
                    probe_id=candidate.probe_id,
                    stable_order=candidate.stable_order,
                    operation_id=descriptor.operation_id,
                    payload_json=candidate.payload_json,
                    cost_units=candidate.cost_units,
                )
                for candidate in candidates
            ),
            key=lambda item: item.stable_order,
        )
    )
    ids = tuple(item.probe_id for item in public_probes)
    orders = tuple(item.stable_order for item in public_probes)
    if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
        raise ActorLoopError("legal probe ids and stable orders must be unique")

    remaining = list(public_probes)
    observations: list[ProbeObservation] = []
    selected: list[str] = []
    bundles: list[DiscoveryScoreBundle] = []
    decision_digests: list[str] = []
    parent_digest: str | None = None
    state_digest = descriptor.initial_state_digest
    for prefix_index in range(probe_budget + 1):
        legal = tuple(remaining)
        transcript = tuple(observations)
        first = _coerce_model_output(model_callback(descriptor, legal, transcript))
        second = _coerce_model_output(model_callback(descriptor, legal, transcript))
        first_bytes = canonical_json(first.to_mapping())
        if first_bytes != canonical_json(second.to_mapping()):
            raise ActorLoopError("model callback is non-deterministic for one transcript")
        _validate_decision(first, legal)
        decision_digests.append(
            content_digest("active-actor-decision/v1", first.to_mapping())
        )
        transcript_prefix_digest = content_digest(
            "active-actor-transcript-prefix/v1",
            [item.observation_digest for item in observations],
        )
        budget_receipt_digest = content_digest(
            "active-actor-budget-prefix/v1",
            {
                "episode_id": episode_id,
                "arm_id": arm_id,
                "consumed_units": prefix_index,
                "observation_digests": [
                    item.observation_digest for item in observations
                ],
            },
        )
        try:
            bundle = DiscoveryScoreBundle.create(
                experiment_id=experiment_id,
                instance_public_digest=descriptor.descriptor_digest,
                arm_id=arm_id,
                actor_binding_digest=actor_binding_digest,
                prefix_index=prefix_index,
                parent_bundle_digest=parent_digest,
                predictions=first.predictions,
                test_ir=first.test_ir,
                transcript_prefix_digest=transcript_prefix_digest,
                consumed_units=prefix_index,
                budget_receipt_digest=budget_receipt_digest,
                catalogue=challenge_catalogue,
            )
        except ScoringContractError as exc:
            raise ActorLoopError("model bundle failed the closed scoring contract") from exc
        bundles.append(bundle)
        parent_digest = bundle.bundle_digest

        if prefix_index == probe_budget:
            break
        chosen = next(
            probe for probe in remaining if probe.probe_id == first.selected_probe_id
        )
        request = ProbeRequest(
            episode_id=episode_id,
            arm_id=arm_id,
            step_index=prefix_index,
            probe_id=chosen.probe_id,
            operation_id=chosen.operation_id,
            payload_json=chosen.payload_json,
            expected_state_digest=state_digest,
            cost_units=chosen.cost_units,
        )
        observation = _validated_observation(execute_probe(request), request)
        observations.append(observation)
        selected.append(chosen.probe_id)
        state_digest = observation.after_state_digest
        remaining.remove(chosen)

    return ActorLoopReceipt(
        prefix_bundles=tuple(bundles),
        selected_probe_ids=tuple(selected),
        observations=tuple(observations),
        decision_digests=tuple(decision_digests),
    )
