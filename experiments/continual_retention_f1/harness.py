from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import CorrectionEvent, FeedbackEvent
from .fixture import EpisodePlan


@dataclass(frozen=True)
class SealedTrajectory:
    actions: tuple[str, ...]
    rewards: tuple[float, ...]
    correction_deliveries: int
    action_digest: str


class EpisodeExecutor:
    def __init__(self, feedback_delay: int = 2) -> None:
        if feedback_delay < 1:
            raise ValueError("feedback delay must be positive")
        self.feedback_delay = feedback_delay

    def execute(self, plan: EpisodePlan, arm) -> SealedTrajectory:
        pending: list[tuple[int, FeedbackEvent]] = []
        actions: list[str] = []
        rewards: list[float] = []
        corrections = 0
        for turn, (public, latent) in enumerate(
            zip(plan.public_steps, plan.latent_steps, strict=True)
        ):
            action = arm.act(public.observation)
            if action not in public.observation.authorized_actions:
                raise ValueError("arm emitted unauthorized action")
            reward = (
                float(action == latent.optimal_action)
                if latent.reward_draw >= 0.1
                else float(action != latent.optimal_action)
            )
            event = FeedbackEvent(f"event-{turn}", public.observation, action, reward)
            pending.append((turn + self.feedback_delay, event))
            actions.append(action)
            rewards.append(reward)
            due = [item for item in pending if item[0] <= turn]
            pending = [item for item in pending if item[0] > turn]
            for _, feedback in due:
                arm.observe(feedback)
                if feedback.event_digest == "event-3":
                    arm.correct(CorrectionEvent(feedback.event_digest))
                    corrections += 1
        for _, feedback in pending:
            arm.observe(feedback)
        digest = hashlib.sha256("\n".join(actions).encode()).hexdigest()
        return SealedTrajectory(tuple(actions), tuple(rewards), corrections, digest)
