"""R-CSL-1 subject-owned commitment ledger.

This module deliberately contains no world model, learned representation, organ,
or shell writer. It consumes only externally supplied admissible actions and
previous true feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence


class CommitmentOutcome(str, Enum):
    PRESERVED = "preserved"
    BROKEN = "broken"
    REPAIRED = "repaired"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class CommitmentFeedback:
    action: int | None
    outcome: CommitmentOutcome
    violation: bool
    budget_delta: float
    repair_commitment: str | None = None


@dataclass(frozen=True)
class LedgerTrace:
    admissible_actions: tuple[int, ...]
    selected_action: int | None
    scores: Mapping[int, float]
    correction_fields: tuple[str, ...]
    c7_violation: bool


@dataclass(frozen=True)
class LedgerDecision:
    action: int | None
    trace: LedgerTrace


@dataclass(frozen=True)
class LedgerSnapshot:
    commitment_value: Mapping[str, float]
    repair_priority: Mapping[str, float]
    dual_weight: float
    last_action: int | None


@dataclass
class CommitmentLedgerPolicy:
    n_actions: int
    action_commitments: Mapping[int, str] | None = None
    ledger_initial_commitment_weight: float = 1.0
    dual_initial_weight: float = 1.0
    repair_priority_initial_weight: float = 1.0
    switching_cost_weight: float = 0.25
    budget_pressure_weight: float = 1.0
    max_dual_weight: float = 5.0
    dual_update_rate: float = 0.10
    repair_decay: float = 0.95
    commitment_value: dict[str, float] = field(init=False)
    repair_priority: dict[str, float] = field(init=False)
    dual_weight: float = field(init=False)
    last_action: int | None = field(default=None, init=False)
    last_budget_pressure: float = field(default=0.0, init=False)
    c7_violation_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.n_actions <= 0:
            raise ValueError("n_actions must be positive.")
        commitments = self.action_commitments or {action: str(action) for action in range(self.n_actions)}
        unknown = [action for action in commitments if action < 0 or action >= self.n_actions]
        if unknown:
            raise ValueError(f"action commitment map contains unknown action(s): {unknown}")
        self.action_commitments = dict(commitments)
        self.commitment_value = {
            commitment: 0.0 for commitment in set(self.action_commitments.values())
        }
        self.repair_priority = {
            commitment: 0.0 for commitment in set(self.action_commitments.values())
        }
        self.dual_weight = self.dual_initial_weight

    def observe(self, feedback: CommitmentFeedback | None) -> None:
        if feedback is None:
            return
        if feedback.action is not None:
            self._require_action(feedback.action)
            commitment = self._commitment_for(feedback.action)
            if feedback.outcome is CommitmentOutcome.PRESERVED:
                self.commitment_value[commitment] += 1.0
                self.repair_priority[commitment] *= self.repair_decay
            elif feedback.outcome is CommitmentOutcome.REPAIRED:
                self.commitment_value[commitment] += 1.5
                self.repair_priority[commitment] *= self.repair_decay
            elif feedback.outcome is CommitmentOutcome.BROKEN:
                self.commitment_value[commitment] -= 1.0
                target = feedback.repair_commitment or commitment
                self._ensure_commitment(target)
                self.repair_priority[target] += self.repair_priority_initial_weight
        if feedback.violation:
            self.dual_weight = min(
                self.max_dual_weight,
                self.dual_weight + self.dual_update_rate,
            )
        else:
            self.dual_weight = max(
                0.0,
                self.dual_weight - (self.dual_update_rate * 0.5),
            )
        self.last_budget_pressure = max(0.0, -feedback.budget_delta) * self.budget_pressure_weight

    def select(
        self,
        *,
        admissible_actions: set[int] | frozenset[int] | Sequence[int],
        feedback: CommitmentFeedback | None = None,
        correction_fields: Sequence[str] = (),
    ) -> LedgerDecision:
        self.observe(feedback)
        admissible = tuple(sorted(set(admissible_actions)))
        for action in admissible:
            self._require_action(action)
        if not admissible:
            trace = LedgerTrace(
                admissible_actions=(),
                selected_action=None,
                scores=MappingProxyType({}),
                correction_fields=tuple(correction_fields),
                c7_violation=False,
            )
            return LedgerDecision(action=None, trace=trace)
        scores = {action: self._score(action) for action in admissible}
        action = max(admissible, key=lambda candidate: (scores[candidate], -candidate))
        if action not in admissible:
            self.c7_violation_count += 1
            c7_violation = True
            action = None
        else:
            c7_violation = False
            self.last_action = action
        trace = LedgerTrace(
            admissible_actions=admissible,
            selected_action=action,
            scores=MappingProxyType(dict(scores)),
            correction_fields=tuple(correction_fields),
            c7_violation=c7_violation,
        )
        return LedgerDecision(action=action, trace=trace)

    def step(self, correction_signal: object) -> LedgerDecision:
        feedback = CommitmentFeedback(
            action=getattr(correction_signal, "previous_action", None),
            outcome=CommitmentOutcome(str(getattr(correction_signal, "commitment_outcome"))),
            violation=bool(getattr(correction_signal, "previous_violation")),
            budget_delta=float(getattr(correction_signal, "budget_delta")),
            repair_commitment=getattr(correction_signal, "repair_commitment", None),
        )
        fields = tuple(getattr(correction_signal, "source_fields", ()))
        admissible = getattr(correction_signal, "admissible_actions")
        return self.select(
            admissible_actions=admissible,
            feedback=feedback,
            correction_fields=fields,
        )

    def snapshot(self) -> LedgerSnapshot:
        return LedgerSnapshot(
            commitment_value=MappingProxyType(dict(self.commitment_value)),
            repair_priority=MappingProxyType(dict(self.repair_priority)),
            dual_weight=self.dual_weight,
            last_action=self.last_action,
        )

    def _score(self, action: int) -> float:
        commitment = self._commitment_for(action)
        score = self.ledger_initial_commitment_weight * self.commitment_value[commitment]
        score += self.dual_weight * self.repair_priority[commitment]
        if self.last_action is not None and self.last_action != action:
            score -= self.switching_cost_weight
        score -= self.last_budget_pressure
        return score

    def _commitment_for(self, action: int) -> str:
        assert self.action_commitments is not None
        return self.action_commitments.get(action, str(action))

    def _ensure_commitment(self, commitment: str) -> None:
        self.commitment_value.setdefault(commitment, 0.0)
        self.repair_priority.setdefault(commitment, 0.0)

    def _require_action(self, action: int) -> None:
        if action < 0 or action >= self.n_actions:
            raise ValueError(f"action outside finite action set: {action}")
