"""Negative-transfer / regime-shift monitor."""

from __future__ import annotations

from uuid import uuid4

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr

from experiments.w1w2_live_adaptation.w1_state import W1Scope


class TransferSignal(ContractModel):
    scope: W1Scope
    arm_name: NonEmptyStr
    step: int = Field(ge=0)
    reward: float
    baseline_reward: float
    frozen_reward: float


class TransferAssessment(ContractModel):
    assessment_id: NonEmptyStr
    scope: W1Scope
    step: int
    negative_transfer_detected: bool
    regime_shift_detected: bool
    recommended_action: NonEmptyStr
    reason: NonEmptyStr


class TransferMonitor:
    """Detects negative transfer from frozen outcome/regret signals.

    Recommends/executes only rollback or an already authorized W2 option.
    """

    def __init__(self, regret_window: int = 5, threshold: float = 0.0) -> None:
        self._regret_window = regret_window
        self._threshold = threshold
        self._history: dict[str, list[TransferSignal]] = {}

    def _key(self, scope: W1Scope) -> str:
        from experiments.w1w2_live_adaptation._contracts import canonical_json
        return canonical_json(scope)

    def assess(
        self,
        signal: TransferSignal,
        current_checkpoint_id: str | None,
        authorized_option_ids: tuple[str, ...],
    ) -> TransferAssessment:
        key = self._key(signal.scope)
        history = self._history.setdefault(key, [])
        history.append(signal)

        window = history[-self._regret_window :]
        regrets = [max(0.0, s.frozen_reward - s.reward) for s in window]
        cumulative_regret = sum(regrets)
        negative_transfer = cumulative_regret > self._threshold and len(window) >= self._regret_window

        baseline_drop = sum(s.baseline_reward - s.reward for s in window) / max(len(window), 1)
        regime_shift = negative_transfer and baseline_drop > 0.5

        if negative_transfer and current_checkpoint_id is not None:
            recommended = "ROLLBACK"
            reason = f"negative transfer (regret={cumulative_regret:.2f}); rollback to {current_checkpoint_id}"
        elif negative_transfer and authorized_option_ids:
            recommended = f"W2_OPTION:{authorized_option_ids[0]}"
            reason = f"negative transfer (regret={cumulative_regret:.2f}); switch to authorized option"
        else:
            recommended = "CONTINUE"
            reason = "no significant negative transfer"

        return TransferAssessment(
            assessment_id=f"ta-{uuid4().hex}",
            scope=signal.scope,
            step=signal.step,
            negative_transfer_detected=negative_transfer,
            regime_shift_detected=regime_shift,
            recommended_action=recommended,
            reason=reason,
        )
