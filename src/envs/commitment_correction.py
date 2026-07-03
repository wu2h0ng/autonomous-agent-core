"""R-CSL-1 correction-signal environment primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


FORBIDDEN_CORRECTION_FIELDS = frozenset(
    {
        "preferred_action",
        "action_value",
        "reward_advice",
        "policy_temperature",
        "gate_state",
        "baseline_state",
        "seed",
        "metric",
        "verdict",
    }
)


@dataclass(frozen=True)
class CorrectionSignal:
    admissible_actions: tuple[int, ...]
    previous_violation: bool
    budget_delta: float
    commitment_outcome: str
    previous_action: int | None = None
    repair_commitment: str | None = None
    audit_ref: str | None = None
    source_fields: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "CorrectionSignal":
        forbidden = sorted(FORBIDDEN_CORRECTION_FIELDS.intersection(payload))
        if forbidden:
            raise ValueError(f"correction signal contains forbidden advice field(s): {forbidden}")
        if "admissible_actions" not in payload:
            raise ValueError("correction signal requires admissible_actions.")
        actions = tuple(sorted({int(action) for action in payload["admissible_actions"]}))  # type: ignore[union-attr]
        if any(action < 0 for action in actions):
            raise ValueError(f"admissible action set contains negative action: {actions}")
        outcome = str(payload.get("commitment_outcome", "neutral"))
        if outcome not in {"preserved", "broken", "repaired", "neutral"}:
            raise ValueError(f"unknown commitment_outcome: {outcome}")
        previous_action_raw = payload.get("previous_action")
        repair_raw = payload.get("repair_commitment")
        audit_ref_raw = payload.get("audit_ref")
        return cls(
            admissible_actions=actions,
            previous_violation=bool(payload.get("previous_violation", False)),
            budget_delta=float(payload.get("budget_delta", 0.0)),
            commitment_outcome=outcome,
            previous_action=int(previous_action_raw) if previous_action_raw is not None else None,
            repair_commitment=str(repair_raw) if repair_raw is not None else None,
            audit_ref=str(audit_ref_raw) if audit_ref_raw is not None else None,
            source_fields=tuple(sorted(str(key) for key in payload)),
        )


@dataclass
class CommitmentCorrectionEnv:
    """Small deterministic finite simulation family for smoke tests and future r-final."""

    n_actions: int = 4
    seed: int = 0
    budget: float = 10.0
    step_index: int = 0
    active_commitment: str = "hold"
    previous_action: int | None = None
    previous_violation: bool = False
    last_budget_delta: float = 0.0
    last_commitment_outcome: str = "neutral"
    last_repair_commitment: str | None = None

    def __post_init__(self) -> None:
        if self.n_actions <= 0:
            raise ValueError("n_actions must be positive.")

    def correction_signal(self) -> CorrectionSignal:
        forbidden = self._forbidden_actions()
        admissible = tuple(action for action in range(self.n_actions) if action not in forbidden)
        return CorrectionSignal(
            admissible_actions=admissible,
            previous_violation=self.previous_violation,
            budget_delta=self.last_budget_delta,
            commitment_outcome=self.last_commitment_outcome,
            previous_action=self.previous_action,
            repair_commitment=self.last_repair_commitment,
            audit_ref=f"r-csl-1:{self.step_index}",
            source_fields=(
                "admissible_actions",
                "previous_violation",
                "budget_delta",
                "commitment_outcome",
                "previous_action",
                "repair_commitment",
                "audit_ref",
            ),
        )

    def step(self, action: int | None) -> CorrectionSignal:
        signal = self.correction_signal()
        violation = action is not None and action not in signal.admissible_actions
        if action is None:
            budget_delta = -0.2
            outcome = "neutral"
        elif violation:
            budget_delta = -2.0
            outcome = "broken"
        elif action == self._shock_action():
            budget_delta = -0.7
            outcome = "broken"
        elif action == 2:
            budget_delta = +0.5
            outcome = "repaired"
        elif action in {0, 1}:
            budget_delta = +0.2
            outcome = "preserved"
        else:
            budget_delta = -0.4
            outcome = "broken"
        self.budget += budget_delta
        self.previous_action = action
        self.previous_violation = violation
        self.last_budget_delta = budget_delta
        self.last_commitment_outcome = outcome
        self.last_repair_commitment = "repair" if outcome == "broken" else None
        self.step_index += 1
        return self.correction_signal()

    def task_signature(self) -> str:
        shock_cycle = tuple(self._shock_action_at(step) for step in range(12))
        return f"seed={self.seed};shock={shock_cycle}"

    def _forbidden_actions(self) -> set[int]:
        forbidden: set[int] = set()
        if self.step_index % 7 == 6:
            forbidden.add(0)
        if self.step_index % 11 == 4:
            forbidden.add((self.seed + self.step_index) % self.n_actions)
        if len(forbidden) >= self.n_actions:
            forbidden.pop()
        return forbidden

    def _shock_action(self) -> int:
        return self._shock_action_at(self.step_index)

    def _shock_action_at(self, step_index: int) -> int:
        if step_index % 5 != 3:
            return -1
        return (self.seed + step_index) % self.n_actions
