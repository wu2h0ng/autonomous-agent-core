"""Grounded outcome judge for RAP bonds (T-P3.3, ADR-0014 D2).

Ring-0 authority: the SOLE decider of a bond's success/failure. It reads
ground-truth regret (judges see truth; deciders do not) and compares the
coalition's realized regret to the uniform-random baseline regret over the
bond's executed steps. The coordinator must route the verdict to
``RAPField.dissolve``; it may never hand-fill an outcome.

Pre-registered rule (ADR-0014 D2): success iff
    mean(realized_regret) < mean(baseline_regret) * beta   (beta = 1.0)
No evidence steps => failure (success must be earned). This is deterministic
and stateful per bond: begin() -> observe()* -> verdict().
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutcomeVerdict:
    outcome: str  # "success" | "failure"
    mean_realized: float
    mean_baseline: float
    steps: int


class OutcomeJudge:
    def __init__(self, beta: float = 1.0) -> None:
        if beta <= 0:
            raise ValueError("beta must be positive")
        self.beta = beta
        self._realized: list[float] = []
        self._baseline: list[float] = []

    def begin(self) -> None:
        """Reset for a new bond's evidence stream."""
        self._realized = []
        self._baseline = []

    def observe(self, realized_regret: float, baseline_regret: float) -> None:
        """Record one executed step's true regret and random-baseline regret."""
        self._realized.append(float(realized_regret))
        self._baseline.append(float(baseline_regret))

    def verdict(self) -> OutcomeVerdict:
        n = len(self._realized)
        if n == 0:
            return OutcomeVerdict("failure", 0.0, 0.0, 0)
        mr = sum(self._realized) / n
        mb = sum(self._baseline) / n
        outcome = "success" if mr < mb * self.beta else "failure"
        return OutcomeVerdict(outcome, mr, mb, n)
