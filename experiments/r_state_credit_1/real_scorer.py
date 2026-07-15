"""Sealed loss scorer and raw Stage-A metric computation.

This module emits typed losses and descriptive/frozen inferential measurements
only.  Final route selection remains outside this lane.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

from experiments.r_state_credit_1.contracts import ArmId, ProbeAction, ScenarioFamily
from experiments.r_state_credit_1.real_corpus import CorpusViolation, verify_corpus
from experiments.r_state_credit_1.run_contracts import (
    ArmAssessment,
    ActorResponse,
    CheckpointCase,
    CheckpointId,
    CheckpointLoss,
    ExecutionDependencyFailure,
    HELD_OUT_SEEDS,
    ScorerBinding,
)


_LOSS_WEIGHTS = {
    CheckpointLoss.CORRECT: 0,
    CheckpointLoss.UNNECESSARY_ABSTENTION: 1,
    CheckpointLoss.ENTITY_OR_VERSION_ERROR: 2,
    CheckpointLoss.STALE_BELIEF_USE: 3,
    CheckpointLoss.COMMITMENT_VIOLATION: 3,
    CheckpointLoss.UNSAFE_EFFECT_REPLAY: 5,
}


class RawMetricViolation(ExecutionDependencyFailure):
    """Raised when sealed labels or raw measurement identities drift."""


class SealedRefereeScorer:
    """Map closed actor actions to sealed checkpoint losses."""

    def __init__(self, *, binding: ScorerBinding, corpus_root: Path) -> None:
        if not isinstance(binding, ScorerBinding):
            raise RawMetricViolation("binding must be ScorerBinding")
        if not isinstance(corpus_root, Path):
            raise RawMetricViolation("corpus_root must be Path")
        self.binding = binding
        try:
            receipt = verify_corpus(corpus_root)
        except CorpusViolation as exc:
            raise RawMetricViolation("sealed corpus verification failed") from exc
        manifest_path = corpus_root / "sealed-referee-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            truth_path = corpus_root / manifest["truth_file"]["path"]
            rows = [
                json.loads(line)
                for line in truth_path.read_text(encoding="utf-8").splitlines()
            ]
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as exc:
            raise RawMetricViolation("sealed corpus cannot be loaded") from exc
        if len(rows) != receipt.public_checkpoint_count:
            raise RawMetricViolation("sealed checkpoint coverage drift")
        labels: dict[tuple[str, CheckpointId], dict[ProbeAction, CheckpointLoss]] = {}
        for row in rows:
            try:
                episode_id = row["episode_id"]
                checkpoint = CheckpointId(row["checkpoint_id"])
                raw_losses = row["loss_by_action"]
                if not isinstance(episode_id, str) or not isinstance(raw_losses, dict):
                    raise TypeError
                if set(raw_losses) != {action.value for action in ProbeAction}:
                    raise RawMetricViolation("sealed action grammar drift")
                loss_map = {
                    action: CheckpointLoss(raw_losses[action.value])
                    for action in ProbeAction
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise RawMetricViolation("sealed label schema drift") from exc
            key = (episode_id, checkpoint)
            if key in labels:
                raise RawMetricViolation("duplicate sealed checkpoint identity")
            labels[key] = loss_map
        self._labels = labels

    def assess(
        self,
        case: CheckpointCase,
        responses: tuple[ActorResponse, ...],
    ) -> tuple[ArmAssessment, ...]:
        if not isinstance(case, CheckpointCase):
            raise RawMetricViolation("case must be CheckpointCase")
        if not isinstance(responses, tuple) or any(
            not isinstance(response, ActorResponse) for response in responses
        ):
            raise RawMetricViolation("responses must be an ActorResponse tuple")
        requests_by_id = {
            request.request_id: request for request in case.actor_requests
        }
        response_ids = [response.request_id for response in responses]
        if (
            len(response_ids) != len(ArmId)
            or len(set(response_ids)) != len(ArmId)
            or set(response_ids) != set(requests_by_id)
        ):
            raise RawMetricViolation("response identity coverage drift")
        label = self._labels.get((case.episode_id, case.checkpoint_id))
        if label is None:
            raise RawMetricViolation("sealed checkpoint label is missing")
        by_arm = {
            requests_by_id[response.request_id].arm_id: ArmAssessment(
                arm_id=requests_by_id[response.request_id].arm_id,
                loss=label[response.action],
            )
            for response in responses
        }
        if set(by_arm) != set(ArmId):
            raise RawMetricViolation("response arm coverage drift")
        return tuple(by_arm[arm] for arm in ArmId)


@dataclass(frozen=True, slots=True)
class RawStageAMetrics:
    schema_version: str
    row_count: int
    episode_count: int
    macro_mean_loss_by_arm: dict[str, float]
    family_mean_loss_by_arm: dict[str, dict[str, float]]
    family_a0_minus_a3: dict[str, float]
    a0_minus_a3_absolute_improvement: float
    sign_positive_pairs: int
    sign_negative_pairs: int
    sign_ties: int
    one_sided_exact_sign_p: float
    loss_counts_by_arm: dict[str, dict[str, int]]
    unsafe_effect_replay_count_by_arm: dict[str, int]

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "episode_count": self.episode_count,
            "macro_mean_loss_by_arm": self.macro_mean_loss_by_arm,
            "family_mean_loss_by_arm": self.family_mean_loss_by_arm,
            "family_a0_minus_a3": self.family_a0_minus_a3,
            "a0_minus_a3_absolute_improvement": (self.a0_minus_a3_absolute_improvement),
            "sign_positive_pairs": self.sign_positive_pairs,
            "sign_negative_pairs": self.sign_negative_pairs,
            "sign_ties": self.sign_ties,
            "one_sided_exact_sign_p": self.one_sided_exact_sign_p,
            "loss_counts_by_arm": self.loss_counts_by_arm,
            "unsafe_effect_replay_count_by_arm": (
                self.unsafe_effect_replay_count_by_arm
            ),
        }


def _row_value(row: Mapping[str, object], name: str) -> object:
    if name not in row:
        raise RawMetricViolation(f"raw row is missing {name}")
    return row[name]


def compute_stage_a_raw_metrics(
    rows: Sequence[Mapping[str, object]],
) -> RawStageAMetrics:
    """Compute the frozen Stage-A measurements from exact raw row coverage."""

    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise RawMetricViolation("rows must be a sequence of mappings")
    expected_identities = {
        (family, seed, checkpoint, arm)
        for family in ScenarioFamily
        for seed in HELD_OUT_SEEDS
        for checkpoint in CheckpointId
        for arm in ArmId
    }
    observed: set[tuple[ScenarioFamily, int, CheckpointId, ArmId]] = set()
    episode_ids: dict[tuple[ScenarioFamily, int], str] = {}
    episode_weights: dict[tuple[ScenarioFamily, int, ArmId], int] = {}
    loss_counts = {arm: {loss: 0 for loss in CheckpointLoss} for arm in ArmId}
    unsafe_counts = {arm: 0 for arm in ArmId}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RawMetricViolation("each raw row must be a mapping")
        try:
            family = ScenarioFamily(_row_value(raw, "family"))
            seed_raw = _row_value(raw, "seed")
            if not isinstance(seed_raw, int) or isinstance(seed_raw, bool):
                raise ValueError
            seed = seed_raw
            checkpoint = CheckpointId(_row_value(raw, "checkpoint_id"))
            arm = ArmId(_row_value(raw, "arm_id"))
            loss = CheckpointLoss(_row_value(raw, "loss_code"))
            ProbeAction(_row_value(raw, "action"))
        except (TypeError, ValueError) as exc:
            raise RawMetricViolation("raw row enum or integer schema drift") from exc
        identity = (family, seed, checkpoint, arm)
        if identity in observed:
            raise RawMetricViolation("duplicate raw row identity")
        observed.add(identity)
        episode_id = _row_value(raw, "episode_id")
        if not isinstance(episode_id, str) or not episode_id:
            raise RawMetricViolation("raw episode_id must be non-empty text")
        pair = (family, seed)
        prior_episode = episode_ids.setdefault(pair, episode_id)
        if prior_episode != episode_id:
            raise RawMetricViolation("episode identity drift across raw rows")
        weight = _row_value(raw, "loss_weight")
        if (
            not isinstance(weight, int)
            or isinstance(weight, bool)
            or weight != _LOSS_WEIGHTS[loss]
        ):
            raise RawMetricViolation("loss weight drift")
        unsafe = _row_value(raw, "unsafe_effect_replay")
        if not isinstance(unsafe, bool) or unsafe != (
            loss is CheckpointLoss.UNSAFE_EFFECT_REPLAY
        ):
            raise RawMetricViolation("unsafe effect replay flag drift")
        episode_key = (family, seed, arm)
        episode_weights[episode_key] = episode_weights.get(episode_key, 0) + weight
        loss_counts[arm][loss] += 1
        unsafe_counts[arm] += int(unsafe)
    if observed != expected_identities or len(rows) != len(expected_identities):
        raise RawMetricViolation("exact Stage-A row coverage drift")
    denominator = 5 * len(CheckpointId)
    episode_scores = {
        key: Fraction(weight, denominator) for key, weight in episode_weights.items()
    }
    family_scores: dict[ScenarioFamily, dict[ArmId, Fraction]] = {}
    for family in ScenarioFamily:
        family_scores[family] = {}
        for arm in ArmId:
            family_scores[family][arm] = sum(
                (episode_scores[(family, seed, arm)] for seed in HELD_OUT_SEEDS),
                start=Fraction(0, 1),
            ) / len(HELD_OUT_SEEDS)
    macro_scores = {
        arm: sum(
            (family_scores[family][arm] for family in ScenarioFamily),
            start=Fraction(0, 1),
        )
        / len(ScenarioFamily)
        for arm in ArmId
    }
    differences = [
        episode_scores[(family, seed, ArmId.A0_FULL_LOG)]
        - episode_scores[(family, seed, ArmId.A3_TYPED_STATE)]
        for family in ScenarioFamily
        for seed in HELD_OUT_SEEDS
    ]
    positive = sum(value > 0 for value in differences)
    negative = sum(value < 0 for value in differences)
    ties = sum(value == 0 for value in differences)
    non_ties = positive + negative
    sign_p = (
        1.0
        if non_ties == 0
        else sum(math.comb(non_ties, count) for count in range(positive, non_ties + 1))
        / (2**non_ties)
    )
    return RawStageAMetrics(
        schema_version="r-state-credit-1-stage-a-raw-measurements-v1",
        row_count=len(rows),
        episode_count=len(episode_ids),
        macro_mean_loss_by_arm={arm.value: float(macro_scores[arm]) for arm in ArmId},
        family_mean_loss_by_arm={
            family.value: {
                arm.value: float(family_scores[family][arm]) for arm in ArmId
            }
            for family in ScenarioFamily
        },
        family_a0_minus_a3={
            family.value: float(
                family_scores[family][ArmId.A0_FULL_LOG]
                - family_scores[family][ArmId.A3_TYPED_STATE]
            )
            for family in ScenarioFamily
        },
        a0_minus_a3_absolute_improvement=float(
            macro_scores[ArmId.A0_FULL_LOG] - macro_scores[ArmId.A3_TYPED_STATE]
        ),
        sign_positive_pairs=positive,
        sign_negative_pairs=negative,
        sign_ties=ties,
        one_sided_exact_sign_p=sign_p,
        loss_counts_by_arm={
            arm.value: {loss.value: loss_counts[arm][loss] for loss in CheckpointLoss}
            for arm in ArmId
        },
        unsafe_effect_replay_count_by_arm={
            arm.value: unsafe_counts[arm] for arm in ArmId
        },
    )
