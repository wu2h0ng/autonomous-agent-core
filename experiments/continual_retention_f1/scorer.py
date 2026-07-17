from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import CostRecord, stable_digest
from .fixture import EpisodePlan
from .harness import SealedTrajectory


@dataclass(frozen=True)
class Disposition:
    status: str
    reason: str


@dataclass(frozen=True)
class ArmMetrics:
    coverage: float
    total_regret_denominator: int
    adaptation_speed: float
    b_changed_exposures: int
    context_cycle: int
    return_a_retention: float
    return_a_delta: float
    negative_transfer: float
    correction_rollback_latency: int
    post_correction_wrong_actions: int
    quality: float


@dataclass(frozen=True)
class ScoredArm:
    arm_id: str
    metrics: ArmMetrics
    cost: CostRecord
    custody_digest: str
    budget_valid: bool
    correction_valid: bool
    equivariant: bool = True


class HiddenScorer:
    @staticmethod
    def oracle_ceiling(plan: EpisodePlan) -> ScoredArm:
        changed_exposures = sum(
            latent.phase == "B" and latent.context_index in set(plan.changed_contexts)
            for latent in plan.latent_steps
        )
        metrics = ArmMetrics(
            coverage=1.0,
            total_regret_denominator=len(plan.public_steps),
            adaptation_speed=0.0,
            b_changed_exposures=changed_exposures,
            context_cycle=len(plan.changed_contexts),
            return_a_retention=1.0,
            return_a_delta=0.0,
            negative_transfer=0.0,
            correction_rollback_latency=0,
            post_correction_wrong_actions=0,
            quality=1.0,
        )
        return ScoredArm(
            "OracleCeiling",
            metrics,
            CostRecord(),
            stable_digest(
                "cls-f1-oracle-ceiling/v1",
                {
                    "phase_lengths": plan.phase_lengths,
                    "changed": plan.changed_contexts,
                    "metrics": metrics.__dict__,
                },
            ),
            True,
            True,
        )

    @staticmethod
    def score(plan: EpisodePlan, trajectory: SealedTrajectory) -> ScoredArm:
        if (
            stable_digest("cls-f1-trajectory/v2", trajectory.seal_payload())
            != trajectory.seal_digest
        ):
            raise ValueError("sealed trajectory digest mismatch")
        if (
            hashlib.sha256("\n".join(trajectory.actions).encode()).hexdigest()
            != trajectory.action_digest
        ):
            raise ValueError("action digest mismatch")
        total = len(plan.public_steps)
        if len(trajectory.actions) != total or len(trajectory.rewards) != total:
            raise ValueError("missing coverage is a sealed trajectory failure")
        correct: list[float] = []
        expected_rewards: list[float] = []
        for action, latent, public in zip(
            trajectory.actions, plan.latent_steps, plan.public_steps, strict=True
        ):
            if action not in public.observation.authorized_actions:
                raise ValueError("trajectory contains unauthorized action")
            is_correct = float(action == latent.optimal_action)
            correct.append(is_correct)
            expected_rewards.append(
                is_correct if latent.reward_draw >= 0.1 else 1.0 - is_correct
            )
        if tuple(expected_rewards) != trajectory.rewards:
            raise ValueError("trajectory reward mismatch")
        correction_valid = (
            len(trajectory.correction_receipts) == 1
            and trajectory.correction_receipts[0].invalidated_event_digest
            == f"event-{plan.corrupted_turn}"
            and sum(receipt.corrupted for receipt in trajectory.feedback_receipts) == 1
        )
        if len(trajectory.feedback_receipts) != total:
            correction_valid = False
        for index, receipt in enumerate(trajectory.feedback_receipts):
            expected_delivery = min(index + 2, total)
            expected_corrupted = index == plan.corrupted_turn
            expected_delivered_reward = (
                1.0 - trajectory.rewards[index]
                if expected_corrupted
                else trajectory.rewards[index]
            )
            if (
                receipt.event_digest != f"event-{index}"
                or receipt.action_turn != index
                or receipt.delivered_turn != expected_delivery
                or receipt.corrupted != expected_corrupted
                or receipt.delivered_reward != expected_delivered_reward
            ):
                correction_valid = False
        if trajectory.correction_receipts:
            correction_receipt = trajectory.correction_receipts[0]
            if (
                correction_receipt.delivered_turn != plan.correction_delivery_turn
                or correction_receipt.original_feedback_turn != plan.corrupted_turn + 2
                or len(correction_receipt.arm_state_digest) != 64
            ):
                correction_valid = False
        phase_rows = list(zip(plan.latent_steps, correct, strict=True))
        changed = set(plan.changed_contexts)
        unchanged = set(plan.unchanged_contexts)
        b_changed = [
            row
            for row in phase_rows
            if row[0].phase == "B" and row[0].context_index in changed
        ]
        history: dict[int, list[float]] = {context: [] for context in changed}
        adaptation_speed = len(b_changed)
        for exposure, (latent, value) in enumerate(b_changed, 1):
            history[latent.context_index].append(value)
            if all(
                len(values) >= 2 and sum(values[-2:]) / 2 >= 0.75
                for values in history.values()
            ):
                adaptation_speed = exposure
                break

        def context_tail(phase: str, contexts: set[int], first: bool) -> list[float]:
            values: list[float] = []
            for context in contexts:
                rows = [
                    value
                    for latent, value in phase_rows
                    if latent.phase == phase and latent.context_index == context
                ]
                values.extend(rows[:2] if first else rows[-2:])
            return values

        initial_changed = context_tail("A1", changed, first=False)
        return_changed = context_tail("A2", changed, first=True)
        initial_unchanged = context_tail("A1", unchanged, first=False)
        b_unchanged = context_tail("B", unchanged, first=False)
        initial_retention = sum(initial_changed) / max(1, len(initial_changed))
        return_retention = sum(return_changed) / max(1, len(return_changed))
        initial_unchanged_rate = sum(initial_unchanged) / max(1, len(initial_unchanged))
        b_unchanged_rate = sum(b_unchanged) / max(1, len(b_unchanged))
        correction = trajectory.correction_receipts[0] if correction_valid else None
        rollback_latency = (
            correction.delivered_turn - correction.original_feedback_turn
            if correction is not None
            else total
        )
        wrong_after = 0
        if correction is not None:
            stop = min(total, correction.delivered_turn + 4)
            wrong_after = sum(
                1 for value in correct[correction.delivered_turn : stop] if value == 0
            )
        budget = trajectory.budget
        counts = {
            kind: sum(receipt.kind == kind for receipt in trajectory.operation_receipts)
            for kind in (
                "updates",
                "replays",
                "comparisons",
                "copies",
                "rebuilds",
                "retrievals",
                "search_trials",
            )
        }
        previous = "0" * 64
        for sequence, receipt in enumerate(trajectory.operation_receipts):
            expected = stable_digest(
                "cls-f1-operation-receipt/v1",
                {
                    "sequence": sequence,
                    "kind": receipt.kind,
                    "turn": receipt.turn,
                    "event_digest": receipt.event_digest,
                    "previous_digest": previous,
                },
            )
            if (
                receipt.sequence != sequence
                or receipt.previous_digest != previous
                or receipt.receipt_digest != expected
            ):
                raise ValueError("operation receipt chain mismatch")
            previous = receipt.receipt_digest
        cost = CostRecord(
            **counts,
            stored_events=trajectory.terminal_stored_events,
            state_bytes=trajectory.terminal_state_bytes,
        )
        feedback_count = len(trajectory.feedback_receipts)
        budget_valid = (
            cost.updates
            <= feedback_count * budget.max_updates_per_feedback
            + cost.rebuilds * budget.max_updates_per_feedback
            and cost.replays
            <= feedback_count * budget.max_replays_per_feedback
            + cost.rebuilds * budget.max_replays_per_feedback
            and cost.comparisons <= total * budget.max_comparisons_per_feedback
            and cost.copies <= feedback_count * budget.max_copies_per_feedback
            and cost.retrievals <= feedback_count * budget.max_retrievals_per_feedback
            and cost.search_trials <= budget.max_search_trials
            and cost.rebuilds <= budget.max_rebuilds
            and cost.stored_events <= budget.max_stored_events
            and cost.state_bytes <= budget.max_state_bytes
        )
        metrics = ArmMetrics(
            coverage=1.0,
            total_regret_denominator=total,
            adaptation_speed=float(adaptation_speed),
            b_changed_exposures=len(b_changed),
            context_cycle=len(changed),
            return_a_retention=return_retention,
            return_a_delta=return_retention - initial_retention,
            negative_transfer=max(0.0, initial_unchanged_rate - b_unchanged_rate),
            correction_rollback_latency=rollback_latency,
            post_correction_wrong_actions=wrong_after,
            quality=sum(correct) / total,
        )
        custody_digest = stable_digest(
            "cls-f1-scored-arm/v2",
            {
                "trajectory_seal": trajectory.seal_digest,
                "phase_lengths": plan.phase_lengths,
                "changed": plan.changed_contexts,
                "metrics": metrics.__dict__,
            },
        )
        return ScoredArm(
            trajectory.arm_id,
            metrics,
            cost,
            custody_digest,
            budget_valid,
            correction_valid,
        )


def adjudicate(
    candidate: ScoredArm,
    baselines: tuple[ScoredArm, ...],
    oracle: ScoredArm,
) -> Disposition:
    if not baselines:
        raise ValueError("strong non-oracle baseline is required")
    all_arms = (candidate, *baselines, oracle)
    if any(
        not arm.budget_valid or not arm.correction_valid or not arm.equivariant
        for arm in all_arms
    ):
        return Disposition("INVALID", "K4 custody, budget, correction, or equivariance")
    if any(
        baseline.cost.search_trials != candidate.cost.search_trials
        for baseline in baselines
    ):
        return Disposition("INVALID", "K4 unequal qualification search budget")
    strongest = max(
        baselines,
        key=lambda arm: (
            arm.metrics.quality,
            arm.metrics.return_a_retention,
            -arm.metrics.adaptation_speed,
        ),
    )
    if (
        strongest.metrics.quality >= 0.95
        or oracle.metrics.quality - strongest.metrics.quality <= 0.03
    ):
        return Disposition("TRIVIAL_INVALID", "K5 cheap strategy saturation")
    tolerance = min(
        candidate.metrics.context_cycle,
        max(1.0, 0.1 * candidate.metrics.b_changed_exposures),
    )
    retention_gain = (
        candidate.metrics.return_a_retention - strongest.metrics.return_a_retention
    )
    if (
        strongest.metrics.adaptation_speed
        <= candidate.metrics.adaptation_speed + tolerance
        and retention_gain <= 0.03
    ):
        return Disposition("KILL_TC1", "K1 strongest cheap baseline matches")
    if (
        candidate.metrics.adaptation_speed >= strongest.metrics.adaptation_speed
        or retention_gain <= 0
        or candidate.metrics.negative_transfer > strongest.metrics.negative_transfer
        or candidate.metrics.correction_rollback_latency
        > strongest.metrics.correction_rollback_latency
        or candidate.metrics.post_correction_wrong_actions
        > strongest.metrics.post_correction_wrong_actions
    ):
        return Disposition("NO_ADOPT", "K2 safety or quality failure")
    if (
        candidate.cost.charged_work > 2 * strongest.cost.charged_work
        or candidate.cost.state_bytes > 2 * strongest.cost.state_bytes
    ) and retention_gain < 0.05:
        return Disposition("OVERHEAD", "K3 unjustified cost")
    return Disposition(
        "QUALIFIED_FOR_RESULT_FREEZE_REVIEW", "narrow qualification only"
    )
