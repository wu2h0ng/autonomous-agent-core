from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .contracts import (
    ArmBudget,
    CorrectionEvent,
    CorrectionReceipt,
    CostRecord,
    FeedbackEvent,
    FeedbackReceipt,
    OperationMeter,
    stable_digest,
)
from .fixture import EpisodePlan


_SEAL_TOKEN = object()


@dataclass(frozen=True, init=False)
class SealedTrajectory:
    arm_id: str
    actions: tuple[str, ...]
    rewards: tuple[float, ...]
    feedback_receipts: tuple[FeedbackReceipt, ...]
    correction_receipts: tuple[CorrectionReceipt, ...]
    cost: CostRecord
    budget: ArmBudget
    action_digest: str
    seal_digest: str

    def __init__(
        self,
        arm_id: str,
        actions: tuple[str, ...],
        rewards: tuple[float, ...],
        feedback_receipts: tuple[FeedbackReceipt, ...],
        correction_receipts: tuple[CorrectionReceipt, ...],
        cost: CostRecord,
        budget: ArmBudget,
        action_digest: str,
        seal_digest: str,
        *,
        _seal_token: object | None = None,
    ) -> None:
        if _seal_token is not _SEAL_TOKEN:
            raise ValueError("sealed trajectory can only be built by EpisodeExecutor")
        object.__setattr__(self, "arm_id", arm_id)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "rewards", rewards)
        object.__setattr__(self, "feedback_receipts", feedback_receipts)
        object.__setattr__(self, "correction_receipts", correction_receipts)
        object.__setattr__(self, "cost", cost)
        object.__setattr__(self, "budget", budget)
        object.__setattr__(self, "action_digest", action_digest)
        object.__setattr__(self, "seal_digest", seal_digest)

    def seal_payload(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "actions": list(self.actions),
            "rewards": list(self.rewards),
            "feedback_receipts": [asdict(item) for item in self.feedback_receipts],
            "correction_receipts": [asdict(item) for item in self.correction_receipts],
            "cost": asdict(self.cost),
            "budget": asdict(self.budget),
            "action_digest": self.action_digest,
        }


class EpisodeExecutor:
    def __init__(self, feedback_delay: int = 2) -> None:
        if feedback_delay < 1:
            raise ValueError("feedback delay must be positive")
        self.feedback_delay = feedback_delay

    def execute(self, plan: EpisodePlan, arm) -> SealedTrajectory:
        meter = OperationMeter(arm.budget)
        arm.bind_meter(meter)
        meter.search(arm.qualification_search_trials)
        pending: list[tuple[int, int, FeedbackEvent, bool]] = []
        actions: list[str] = []
        rewards: list[float] = []
        feedback_receipts: list[FeedbackReceipt] = []
        correction_receipts: list[CorrectionReceipt] = []
        corrupted_digest = f"event-{plan.corrupted_turn}"

        def arm_state_bytes() -> bytes:
            state = {
                key: value
                for key, value in sorted(vars(arm).items())
                if key != "_meter"
            }
            return repr(state).encode()

        def deliver(
            delivered_turn: int, action_turn: int, event: FeedbackEvent, corrupted: bool
        ) -> None:
            before = meter.snapshot()
            arm.observe(event)
            delta = meter.delta(before)
            if (
                delta.updates > arm.budget.max_updates_per_feedback
                or delta.replays > arm.budget.max_replays_per_feedback
                or delta.copies > arm.budget.max_copies_per_feedback
                or delta.comparisons > arm.budget.max_comparisons_per_feedback
            ):
                raise RuntimeError("arm exceeded per-feedback operation budget")
            feedback_receipts.append(
                FeedbackReceipt(
                    event.event_digest,
                    action_turn,
                    delivered_turn,
                    event.reward,
                    corrupted,
                )
            )

        for turn, (public, latent) in enumerate(
            zip(plan.public_steps, plan.latent_steps, strict=True)
        ):
            action = arm.act(public.observation)
            if action not in public.observation.authorized_actions:
                raise ValueError("arm emitted unauthorized action")
            true_reward = (
                float(action == latent.optimal_action)
                if latent.reward_draw >= 0.1
                else float(action != latent.optimal_action)
            )
            corrupted = turn == plan.corrupted_turn
            delivered_reward = 1.0 - true_reward if corrupted else true_reward
            event = FeedbackEvent(
                f"event-{turn}", public.observation, action, delivered_reward
            )
            pending.append((turn + self.feedback_delay, turn, event, corrupted))
            actions.append(action)
            rewards.append(true_reward)
            due = [item for item in pending if item[0] <= turn]
            pending = [item for item in pending if item[0] > turn]
            for _, action_turn, feedback, was_corrupted in due:
                deliver(turn, action_turn, feedback, was_corrupted)
            if turn == plan.correction_delivery_turn:
                arm.correct(CorrectionEvent(corrupted_digest))
                correction_receipts.append(
                    CorrectionReceipt(
                        corrupted_digest,
                        turn,
                        plan.corrupted_turn + self.feedback_delay,
                        hashlib.sha256(arm_state_bytes()).hexdigest(),
                    )
                )
        final_turn = len(plan.public_steps)
        for _, action_turn, feedback, was_corrupted in pending:
            deliver(final_turn, action_turn, feedback, was_corrupted)
        action_digest = hashlib.sha256("\n".join(actions).encode()).hexdigest()
        cost = meter.snapshot(
            stored_events=len(getattr(arm, "_events", ())),
            state_bytes=len(arm_state_bytes()),
        )
        payload = {
            "arm_id": type(arm).__name__,
            "actions": actions,
            "rewards": rewards,
            "feedback_receipts": [asdict(item) for item in feedback_receipts],
            "correction_receipts": [asdict(item) for item in correction_receipts],
            "cost": asdict(cost),
            "budget": asdict(arm.budget),
            "action_digest": action_digest,
        }
        return SealedTrajectory(
            type(arm).__name__,
            tuple(actions),
            tuple(rewards),
            tuple(feedback_receipts),
            tuple(correction_receipts),
            cost,
            arm.budget,
            action_digest,
            stable_digest("cls-f1-trajectory/v2", payload),
            _seal_token=_SEAL_TOKEN,
        )
