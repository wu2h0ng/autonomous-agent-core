from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict, dataclass

from .contracts import (
    ArmBudget,
    CorrectionEvent,
    CorrectionReceipt,
    FeedbackEvent,
    FeedbackReceipt,
    OperationReceipt,
    stable_digest,
)
from .fixture import EpisodePlan


_EXECUTOR_TOKEN = object()


@dataclass(frozen=True, init=False)
class SealedTrajectory:
    arm_id: str
    actions: tuple[str, ...]
    rewards: tuple[float, ...]
    feedback_receipts: tuple[FeedbackReceipt, ...]
    correction_receipts: tuple[CorrectionReceipt, ...]
    operation_receipts: tuple[OperationReceipt, ...]
    terminal_stored_events: int
    terminal_state_bytes: int
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
        operation_receipts: tuple[OperationReceipt, ...],
        terminal_stored_events: int,
        terminal_state_bytes: int,
        budget: ArmBudget,
        action_digest: str,
        seal_digest: str,
        *,
        _seal_token: object | None = None,
    ) -> None:
        if _seal_token is not _EXECUTOR_TOKEN:
            raise ValueError("sealed trajectory can only be built by EpisodeExecutor")
        object.__setattr__(self, "arm_id", arm_id)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "rewards", rewards)
        object.__setattr__(self, "feedback_receipts", feedback_receipts)
        object.__setattr__(self, "correction_receipts", correction_receipts)
        object.__setattr__(self, "operation_receipts", operation_receipts)
        object.__setattr__(self, "terminal_stored_events", terminal_stored_events)
        object.__setattr__(self, "terminal_state_bytes", terminal_state_bytes)
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
            "operation_receipts": [asdict(item) for item in self.operation_receipts],
            "terminal_stored_events": self.terminal_stored_events,
            "terminal_state_bytes": self.terminal_state_bytes,
            "budget": asdict(self.budget),
            "action_digest": self.action_digest,
        }


class EpisodeExecutor:
    def __init__(self, feedback_delay: int = 2) -> None:
        if feedback_delay < 1:
            raise ValueError("feedback delay must be positive")
        self.feedback_delay = feedback_delay

    def execute(self, plan: EpisodePlan, arm) -> SealedTrajectory:
        # The profiler is instrumentation for exact reviewed implementations,
        # never a sandbox for caller supplied Python.  Runtime subclasses are
        # rejected; freeze custody must additionally bind these implementation
        # bytes before any result-bearing run.
        from .baselines import (
            RecencyArm,
            ResetOnChangeArm,
            SingleStoreReplayStabilityArm,
            StaticArm,
            WSLSDiagnosticArm,
        )
        from .dual_store import DualStoreRetentionArm

        allowed = {
            SingleStoreReplayStabilityArm,
            ResetOnChangeArm,
            RecencyArm,
            StaticArm,
            WSLSDiagnosticArm,
            DualStoreRetentionArm,
        }
        if type(arm) not in allowed:
            raise TypeError(
                "untrusted arm implementation; exact reviewed type required"
            )
        operation_receipts: list[OperationReceipt] = []
        current_turn = -1
        current_event = "qualification"

        def record(kind: str) -> None:
            previous = (
                operation_receipts[-1].receipt_digest
                if operation_receipts
                else "0" * 64
            )
            sequence = len(operation_receipts)
            digest = stable_digest(
                "cls-f1-operation-receipt/v1",
                {
                    "sequence": sequence,
                    "kind": kind,
                    "turn": current_turn,
                    "event_digest": current_event,
                    "previous_digest": previous,
                },
            )
            operation_receipts.append(
                OperationReceipt(
                    sequence, kind, current_turn, current_event, previous, digest
                )
            )

        for _ in range(arm.qualification_search_trials):
            record("search_trials")
        pending: list[tuple[int, int, FeedbackEvent, bool]] = []
        actions: list[str] = []
        rewards: list[float] = []
        feedback_receipts: list[FeedbackReceipt] = []
        correction_receipts: list[CorrectionReceipt] = []
        corrupted_digest = f"event-{plan.corrupted_turn}"

        def arm_state_bytes() -> bytes:
            state = {key: value for key, value in sorted(vars(arm).items()) if True}
            return repr(state).encode()

        def profiler(frame, event_name, arg):
            if event_name != "call" or frame.f_locals.get("self") is not arm:
                return profiler
            name = frame.f_code.co_name
            caller = frame.f_back.f_code.co_name if frame.f_back else ""
            if name == "_update_value" and caller != "_replay_value":
                record("updates")
            elif name == "_replay_value":
                record("replays")
            elif name == "_copy_prototype":
                record("copies")
            elif name == "_retrieve_prototype":
                record("retrievals")
            elif name == "_rebuild_event":
                record("rebuilds")
            return profiler

        def deliver(
            delivered_turn: int, action_turn: int, event: FeedbackEvent, corrupted: bool
        ) -> None:
            nonlocal current_turn, current_event
            current_turn, current_event = delivered_turn, event.event_digest
            before_count = len(operation_receipts)
            before_state = hashlib.sha256(arm_state_bytes()).hexdigest()

            sys.setprofile(profiler)
            try:
                arm.observe(event)
                if sys.getprofile() is not profiler:
                    raise RuntimeError("arm disabled evaluator instrumentation")
            finally:
                sys.setprofile(None)
            delta = operation_receipts[before_count:]
            counts = {
                kind: sum(item.kind == kind for item in delta)
                for kind in ("updates", "replays", "copies", "retrievals", "rebuilds")
            }
            if (
                counts["updates"] > arm.budget.max_updates_per_feedback
                or counts["replays"] > arm.budget.max_replays_per_feedback
                or counts["copies"] > arm.budget.max_copies_per_feedback
                or counts["retrievals"] > arm.budget.max_retrievals_per_feedback
            ):
                raise RuntimeError("arm exceeded per-feedback operation budget")
            after_state = hashlib.sha256(arm_state_bytes()).hexdigest()
            if before_state != after_state and not delta:
                raise RuntimeError("unmetered arm state mutation")
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
            current_turn, current_event = turn, f"act-{turn}"
            for _ in public.observation.authorized_actions:
                record("comparisons")
            if (
                len(public.observation.authorized_actions)
                > arm.budget.max_comparisons_per_feedback
            ):
                raise RuntimeError("arm exceeded comparison budget")
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
                current_turn, current_event = turn, corrupted_digest
                sys.setprofile(profiler)
                try:
                    arm.correct(CorrectionEvent(corrupted_digest))
                finally:
                    sys.setprofile(None)
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
        terminal_stored_events = len(getattr(arm, "_events", ()))
        terminal_state_bytes = len(arm_state_bytes())
        payload = {
            "arm_id": type(arm).__name__,
            "actions": actions,
            "rewards": rewards,
            "feedback_receipts": [asdict(item) for item in feedback_receipts],
            "correction_receipts": [asdict(item) for item in correction_receipts],
            "operation_receipts": [asdict(item) for item in operation_receipts],
            "terminal_stored_events": terminal_stored_events,
            "terminal_state_bytes": terminal_state_bytes,
            "budget": asdict(arm.budget),
            "action_digest": action_digest,
        }
        return SealedTrajectory(
            type(arm).__name__,
            tuple(actions),
            tuple(rewards),
            tuple(feedback_receipts),
            tuple(correction_receipts),
            tuple(operation_receipts),
            terminal_stored_events,
            terminal_state_bytes,
            arm.budget,
            action_digest,
            stable_digest("cls-f1-trajectory/v2", payload),
            _seal_token=_EXECUTOR_TOKEN,
        )
