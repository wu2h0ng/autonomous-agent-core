"""Raw-only scoring guards for the six-action recast successor."""

from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.run_contracts import CheckpointLoss


_LOSS_WEIGHTS = {
    CheckpointLoss.CORRECT: 0,
    CheckpointLoss.UNNECESSARY_ABSTENTION: 1,
    CheckpointLoss.ENTITY_OR_VERSION_ERROR: 2,
    CheckpointLoss.STALE_BELIEF_USE: 3,
    CheckpointLoss.COMMITMENT_VIOLATION: 3,
    CheckpointLoss.UNSAFE_EFFECT_REPLAY: 5,
}


class RawRecastScorer:
    """Validate exact row identity and prohibit route verdict output."""

    _VERDICT_FIELDS = {"verdict", "met", "not_met", "decision", "promotion"}

    def validate_identity_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        expected: set[tuple[object, object, object, object]],
    ) -> None:
        identities = [
            (
                row.get("family"),
                row.get("seed"),
                row.get("checkpoint_id"),
                row.get("arm_id"),
            )
            for row in rows
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate raw row identity")
        if set(identities) != expected:
            raise ValueError("exact raw row coverage drift")

    def assert_raw_only(self, output: Mapping[str, object]) -> None:
        if self._VERDICT_FIELDS.intersection(key.casefold() for key in output):
            raise ValueError("raw scorer must not emit a verdict")

    def score_raw(self, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
        if not rows:
            raise ValueError("raw score rows must not be empty")
        action_counts: Counter[str] = Counter()
        loss_counts: Counter[str] = Counter()
        total = 0
        for row in rows:
            try:
                action = ActorAction(row["action"])
                loss = CheckpointLoss(row["loss_code"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("raw score enum schema drift") from exc
            weight = row.get("loss_weight")
            if weight != _LOSS_WEIGHTS[loss]:
                raise ValueError("raw score loss grammar drift")
            action_counts[action.value] += 1
            loss_counts[loss.value] += 1
            total += _LOSS_WEIGHTS[loss]
        output: dict[str, object] = {
            "schema_version": "r-state-credit-1-successor-f-raw-metrics-v1",
            "row_count": len(rows),
            "mean_loss_weight": total / len(rows),
            "loss_counts": dict(loss_counts),
            "action_counts": dict(action_counts),
        }
        self.assert_raw_only(output)
        return output
