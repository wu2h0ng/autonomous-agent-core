"""Negative-transfer / regime-shift monitor using trusted scorer receipts."""

from __future__ import annotations

from uuid import uuid4

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr
from experiments.w1w2_live_adaptation.w1_state import W1Scope


class ScorerReceipt(ContractModel):
    """Trusted scorer-side outcome receipt. Candidate never observes this directly."""

    receipt_id: NonEmptyStr
    scope: W1Scope
    arm_name: NonEmptyStr
    step: int = Field(ge=0)
    reward: float
    baseline_reward: float
    oracle_reward: float


class TransferAssessment(ContractModel):
    assessment_id: NonEmptyStr
    scope: W1Scope
    step: int
    negative_transfer_detected: bool
    regime_shift_detected: bool
    recommended_action: NonEmptyStr
    reason: NonEmptyStr


class TransferMonitor:
    """Detects negative transfer from trusted scorer receipts.

    Recommends/executes only rollback or an already authorized W2 option.
    """

    def __init__(
        self,
        regret_window: int,
        threshold: float,
        gate_digest: str,
    ) -> None:
        self._regret_window = regret_window
        self._threshold = threshold
        self._gate_digest = gate_digest
        self._history: dict[str, list[ScorerReceipt]] = {}

    def _key(self, scope: W1Scope) -> str:
        from experiments.w1w2_live_adaptation._contracts import canonical_json
        return canonical_json(scope)

    def gate_digest(self) -> str:
        return self._gate_digest

    def assess(
        self,
        receipt: ScorerReceipt,
        current_checkpoint_id: str | None,
        authorized_option_ids: tuple[str, ...],
    ) -> TransferAssessment:
        key = self._key(receipt.scope)
        history = self._history.setdefault(key, [])
        history.append(receipt)

        window = history[-self._regret_window :]
        regrets = [max(0.0, s.oracle_reward - s.reward) for s in window]
        cumulative_regret = sum(regrets)
        negative_transfer = cumulative_regret > self._threshold and len(window) >= self._regret_window

        baseline_regret = sum(max(0.0, s.baseline_reward - s.reward) for s in window) / max(len(window), 1)
        regime_shift = negative_transfer and baseline_regret > 0.5

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
            scope=receipt.scope,
            step=receipt.step,
            negative_transfer_detected=negative_transfer,
            regime_shift_detected=regime_shift,
            recommended_action=recommended,
            reason=reason,
        )
