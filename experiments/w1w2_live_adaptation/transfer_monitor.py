"""Negative-transfer monitor behind opaque trusted-scorer custody."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr
from experiments.w1w2_live_adaptation.w1_state import W1Scope


class ScorerReceiptBinding(ContractModel):
    run_id: NonEmptyStr
    scope: W1Scope
    arm_name: NonEmptyStr
    step: int = Field(ge=0)
    gate_digest: NonEmptyStr


class SealedScorerOutcome(ContractModel):
    reward: float
    frozen_reference_reward: float
    oracle_reward: float


class ScorerReceipt(ContractModel):
    """Resolver-held receipt; candidate and monitor callers receive only its id."""

    receipt_id: NonEmptyStr
    binding: ScorerReceiptBinding
    outcome: SealedScorerOutcome


class TrustedScorerPort(Protocol):
    """External scorer plus atomic, one-time receipt resolver."""

    def score(
        self, binding: ScorerReceiptBinding, outcome: SealedScorerOutcome
    ) -> str: ...

    def consume(
        self,
        receipt_id: str,
        expected: ScorerReceiptBinding,
    ) -> ScorerReceipt | None: ...


class TransferAssessment(ContractModel):
    assessment_id: NonEmptyStr
    scope: W1Scope
    step: int
    negative_transfer_detected: bool
    regime_shift_detected: bool
    recommended_action: NonEmptyStr
    reason: NonEmptyStr


class TransferMonitor:
    """Resolve scorer receipts exactly once under constructor-bound authority."""

    def __init__(
        self,
        regret_window: int,
        threshold: float,
        gate_digest: str,
        run_id: str,
        scope: W1Scope,
        arm_name: str,
        scorer_resolver: TrustedScorerPort,
    ) -> None:
        self._regret_window = regret_window
        self._threshold = threshold
        self._gate_digest = gate_digest
        self._run_id = run_id
        self._scope = scope
        self._arm_name = arm_name
        self._scorer_resolver = scorer_resolver
        self._history: list[ScorerReceipt] = []

    def gate_digest(self) -> str:
        return self._gate_digest

    def assess(
        self,
        receipt_id: str,
        step: int,
        current_checkpoint_id: str | None,
        authorized_option_ids: tuple[str, ...],
    ) -> TransferAssessment:
        expected = ScorerReceiptBinding(
            run_id=self._run_id,
            scope=self._scope,
            arm_name=self._arm_name,
            step=step,
            gate_digest=self._gate_digest,
        )
        receipt = self._scorer_resolver.consume(receipt_id, expected)
        if (
            receipt is None
            or receipt.receipt_id != receipt_id
            or receipt.binding != expected
        ):
            raise ValueError("invalid, mismatched or replayed scorer receipt")
        self._history.append(receipt)

        window = self._history[-self._regret_window :]
        regrets = [
            max(0.0, item.outcome.oracle_reward - item.outcome.reward)
            for item in window
        ]
        cumulative_regret = sum(regrets)
        negative_transfer = (
            cumulative_regret > self._threshold and len(window) >= self._regret_window
        )
        frozen_reference_regret = sum(
            max(
                0.0,
                item.outcome.frozen_reference_reward - item.outcome.reward,
            )
            for item in window
        ) / max(len(window), 1)
        regime_shift = negative_transfer and frozen_reference_regret > 0.5

        if negative_transfer and current_checkpoint_id is not None:
            recommended = "ROLLBACK"
            reason = f"negative transfer (regret={cumulative_regret:.2f}); rollback"
        elif negative_transfer and authorized_option_ids:
            recommended = f"W2_OPTION:{authorized_option_ids[0]}"
            reason = (
                f"negative transfer (regret={cumulative_regret:.2f}); authorized switch"
            )
        else:
            recommended = "CONTINUE"
            reason = "no significant negative transfer"
        return TransferAssessment(
            assessment_id=f"ta-{uuid4().hex}",
            scope=self._scope,
            step=step,
            negative_transfer_detected=negative_transfer,
            regime_shift_detected=regime_shift,
            recommended_action=recommended,
            reason=reason,
        )
