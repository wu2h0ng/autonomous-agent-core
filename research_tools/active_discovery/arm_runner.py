from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, ClassVar, Mapping, Protocol

from .budget import BudgetLedger
from .canonical import content_digest
from .catalogue import VisibleProbeCandidate, VisibleProbeCatalogue
from .contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from .families.manifest import FamilyManifest
from .referee import HaltAuthority, HiddenScore, SealedRefereeSession
from .selector import (
    PROBABILITY_SCALE,
    HypothesisWeight,
    select_probe,
)


ARM_RUN_SCHEMA = "active-discovery-matched-arm-run/v1"
ARM_RECEIPT_SCHEMA = "active-discovery-matched-arm-receipt/v1"
_MODE = "NOT_EVIDENCE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RunnerValidationError(ValueError):
    """A development arm run escaped its closed matched-budget contract."""


class ArmKind(str, Enum):
    SYSTEMATIC = "SYSTEMATIC"
    RANDOM = "RANDOM"
    VOI = "VOI"


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RunnerValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class MatchedArmRunSpec:
    schema_version: str
    mode: str
    run_id: str
    family_manifest_digest: str
    budget_units: int
    random_seed: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "mode",
            "run_id",
            "family_manifest_digest",
            "budget_units",
            "random_seed",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != ARM_RUN_SCHEMA or self.mode != _MODE:
            raise RunnerValidationError(
                "matched arm spec must use the closed NOT_EVIDENCE schema and mode"
            )
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise RunnerValidationError("run_id must be a non-empty string")
        _digest(self.family_manifest_digest, "family_manifest_digest")
        if (
            isinstance(self.budget_units, bool)
            or not isinstance(self.budget_units, int)
            or self.budget_units < 1
        ):
            raise RunnerValidationError("budget_units must be an integer >= 1")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise RunnerValidationError("random_seed must be an integer")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> MatchedArmRunSpec:
        unknown = set(raw) - cls.FIELDS
        missing = cls.FIELDS - set(raw)
        if unknown:
            raise RunnerValidationError(f"unknown fields: {sorted(unknown)}")
        if missing:
            raise RunnerValidationError(f"missing fields: {sorted(missing)}")
        return cls(
            schema_version=raw["schema_version"],
            mode=raw["mode"],
            run_id=raw["run_id"],
            family_manifest_digest=_digest(
                raw["family_manifest_digest"], "family_manifest_digest"
            ),
            budget_units=raw["budget_units"],
            random_seed=raw["random_seed"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "run_id": self.run_id,
            "family_manifest_digest": self.family_manifest_digest,
            "budget_units": self.budget_units,
            "random_seed": self.random_seed,
        }

    @property
    def spec_digest(self) -> str:
        return content_digest("matched-arm-run-spec", self.to_mapping())


@dataclass(frozen=True, slots=True)
class ArmRunReceipt:
    arm_kind: ArmKind
    episode_id: str
    family_manifest_digest: str
    descriptor_digest: str
    selected_probe_ids: tuple[str, ...]
    observation_digests: tuple[str, ...]
    consumed_units: int
    budget_ledger_digest: str
    transcript_digest: str
    seal_digest: str
    final_visible_belief_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "arm_kind": self.arm_kind.value,
            "episode_id": self.episode_id,
            "family_manifest_digest": self.family_manifest_digest,
            "descriptor_digest": self.descriptor_digest,
            "selected_probe_ids": list(self.selected_probe_ids),
            "observation_digests": list(self.observation_digests),
            "consumed_units": self.consumed_units,
            "budget_ledger_digest": self.budget_ledger_digest,
            "transcript_digest": self.transcript_digest,
            "seal_digest": self.seal_digest,
            "final_visible_belief_digest": self.final_visible_belief_digest,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest("development-arm-receipt", self.to_mapping())


@dataclass(frozen=True, slots=True)
class MatchedArmReceipt:
    schema_version: str
    mode: str
    spec_digest: str
    arms: tuple[ArmRunReceipt, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "spec_digest": self.spec_digest,
            "arms": [
                {**arm.to_mapping(), "receipt_digest": arm.receipt_digest}
                for arm in self.arms
            ],
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest("matched-development-arm-receipt", self.to_mapping())


class DevelopmentFamilyAdapter(Protocol):
    @property
    def manifest(self) -> FamilyManifest: ...

    @property
    def catalogue(self) -> VisibleProbeCatalogue: ...

    def public_descriptor(self) -> PublicEnvironmentDescriptor: ...

    def state_digest(self) -> str: ...

    def execute(self, request: ProbeRequest) -> ProbeObservation: ...

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore: ...


def select_visible_voi_candidate(
    weights: tuple[HypothesisWeight, ...],
    candidates: tuple[VisibleProbeCandidate, ...],
) -> VisibleProbeCandidate:
    if not candidates:
        raise RunnerValidationError("VOI selection requires visible candidates")
    selection = select_probe(
        weights,
        tuple(candidate.selector_candidate for candidate in candidates),
    )
    return next(
        candidate
        for candidate in candidates
        if candidate.probe_id == selection.probe_id
    )


def update_visible_beliefs(
    weights: tuple[HypothesisWeight, ...],
    candidate: VisibleProbeCandidate,
    *,
    status_code: int,
) -> tuple[HypothesisWeight, ...]:
    observed_label = candidate.observed_label(status_code)
    predictions = {item.hypothesis_id: item for item in candidate.predictions}
    if set(predictions) != {item.hypothesis_id for item in weights}:
        raise RunnerValidationError(
            "visible belief update requires exact candidate hypotheses"
        )
    unnormalized: list[int] = []
    for weight in weights:
        outcomes = {
            outcome.outcome_label: outcome.probability_micros
            for outcome in predictions[weight.hypothesis_id].outcomes
        }
        likelihood = outcomes.get(observed_label)
        if likelihood is None:
            raise RunnerValidationError(
                "visible observation label is absent from candidate likelihoods"
            )
        unnormalized.append(weight.probability_micros * likelihood)
    total = sum(unnormalized)
    if total <= 0:
        raise RunnerValidationError("visible belief update has zero total likelihood")

    probabilities: list[int] = []
    remainders: list[tuple[int, int]] = []
    for index, value in enumerate(unnormalized):
        probability, remainder = divmod(value * PROBABILITY_SCALE, total)
        probabilities.append(probability)
        remainders.append((remainder, index))
    missing = PROBABILITY_SCALE - sum(probabilities)
    for _, index in sorted(remainders, key=lambda item: (-item[0], item[1]))[:missing]:
        probabilities[index] += 1
    if any(value <= 0 for value in probabilities):
        raise RunnerValidationError(
            "visible posterior collapsed outside the supported weight domain"
        )
    return tuple(
        HypothesisWeight(weight.hypothesis_id, probabilities[index])
        for index, weight in enumerate(weights)
    )


def _visible_belief_digest(weights: tuple[HypothesisWeight, ...]) -> str:
    return content_digest(
        "visible-belief-state",
        [asdict(weight) for weight in weights],
    )


def _random_order(
    seed: int, candidates: tuple[VisibleProbeCandidate, ...]
) -> tuple[VisibleProbeCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                content_digest(
                    "random-arm-public-rank",
                    {"seed": seed, "probe_id": candidate.probe_id},
                ),
                candidate.stable_order,
            ),
        )
    )


def _run_arm(
    *,
    arm_kind: ArmKind,
    spec: MatchedArmRunSpec,
    adapter: DevelopmentFamilyAdapter,
    halt_authority: HaltAuthority,
) -> ArmRunReceipt:
    descriptor = adapter.public_descriptor()
    catalogue = adapter.catalogue
    if adapter.manifest.manifest_digest != spec.family_manifest_digest:
        raise RunnerValidationError("adapter manifest does not match run spec")
    if adapter.manifest.probe_budget_units != spec.budget_units:
        raise RunnerValidationError("adapter and run spec budgets do not match")
    if adapter.manifest.descriptor_digest != descriptor.descriptor_digest:
        raise RunnerValidationError("adapter descriptor binding mismatch")
    if adapter.manifest.catalogue_digest != catalogue.catalogue_digest:
        raise RunnerValidationError("adapter catalogue binding mismatch")
    if spec.budget_units > len(catalogue.candidates):
        raise RunnerValidationError("budget exceeds the unit-cost public catalogue")

    episode_id = f"{spec.run_id}:{arm_kind.value}"
    ledger = BudgetLedger(spec.budget_units)
    session = SealedRefereeSession(
        episode_id=episode_id,
        adapter=adapter,
        budget=ledger,
        halt_authority=halt_authority,
    )
    remaining = list(catalogue.candidates)
    fixed_order = (
        tuple(sorted(remaining, key=lambda item: item.stable_order))
        if arm_kind is ArmKind.SYSTEMATIC
        else _random_order(spec.random_seed, tuple(remaining))
        if arm_kind is ArmKind.RANDOM
        else ()
    )
    weights = catalogue.initial_weights
    visible_state_digest = descriptor.initial_state_digest
    selected_probe_ids: list[str] = []
    observation_digests: list[str] = []
    for step_index in range(spec.budget_units):
        if arm_kind is ArmKind.VOI:
            candidate = select_visible_voi_candidate(weights, tuple(remaining))
        else:
            candidate = fixed_order[step_index]
        remaining = [item for item in remaining if item.probe_id != candidate.probe_id]
        observation = session.probe(
            ProbeRequest.from_mapping(
                {
                    "episode_id": episode_id,
                    "arm_id": arm_kind.value,
                    "step_index": step_index,
                    "probe_id": candidate.probe_id,
                    "operation_id": descriptor.operation_id,
                    "payload_json": candidate.payload_json,
                    "expected_state_digest": visible_state_digest,
                    "cost_units": 1,
                }
            )
        )
        visible_state_digest = observation.after_state_digest
        selected_probe_ids.append(candidate.probe_id)
        observation_digests.append(observation.observation_digest)
        weights = update_visible_beliefs(
            weights,
            candidate,
            status_code=observation.status_code,
        )
    if ledger.consumed_units != spec.budget_units or ledger.remaining_units != 0:
        raise RunnerValidationError("arm did not consume the exact hard budget")
    bundle_digest = content_digest(
        "development-arm-bundle",
        {
            "mode": _MODE,
            "spec_digest": spec.spec_digest,
            "arm_kind": arm_kind.value,
            "selected_probe_ids": selected_probe_ids,
            "observation_digests": observation_digests,
        },
    )
    seal = session.seal(bundle_digest=bundle_digest)
    return ArmRunReceipt(
        arm_kind=arm_kind,
        episode_id=episode_id,
        family_manifest_digest=adapter.manifest.manifest_digest,
        descriptor_digest=descriptor.descriptor_digest,
        selected_probe_ids=tuple(selected_probe_ids),
        observation_digests=tuple(observation_digests),
        consumed_units=ledger.consumed_units,
        budget_ledger_digest=ledger.ledger_digest,
        transcript_digest=seal.transcript_digest,
        seal_digest=seal.seal_digest,
        final_visible_belief_digest=_visible_belief_digest(weights),
    )


def run_matched_arms(
    *,
    spec: MatchedArmRunSpec,
    adapter_factory: Callable[[], DevelopmentFamilyAdapter],
    halt_authority: HaltAuthority,
) -> MatchedArmReceipt:
    arms: list[ArmRunReceipt] = []
    adapter_ids: set[int] = set()
    for arm_kind in ArmKind:
        adapter = adapter_factory()
        if id(adapter) in adapter_ids:
            raise RunnerValidationError("each arm requires a fresh adapter instance")
        adapter_ids.add(id(adapter))
        arms.append(
            _run_arm(
                arm_kind=arm_kind,
                spec=spec,
                adapter=adapter,
                halt_authority=halt_authority,
            )
        )
    return MatchedArmReceipt(
        schema_version=ARM_RECEIPT_SCHEMA,
        mode=_MODE,
        spec_digest=spec.spec_digest,
        arms=tuple(arms),
    )
