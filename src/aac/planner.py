"""CWMPlanner + PlanProposal — proposal-form planning organ (Stage-5).

Formal model: docs/pre_spec/STAGE5-PLANNER-SOVEREIGNTY.PREREG-2026-07-03.md (30b2c05).

Authority is founder-reserved. This module ships ONLY the proposal form: the planner is
an ORGAN that proposes an ordered plan over the FULL candidate set (no-narrowing invariant,
like relevance) and predicted do-effects; it never restricts what the gate may consider.
The GovernedDecisionGate sits between the planner and the executor — every step is
individually verified+gated, no step inherits plan authority.

The Stage-5 falsifier (experiments/stage5_planner_sovereignty.py) re-runs the Stage-0
ablation with this planner present and PARKs it if the SD4-shadow signature appears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .governed_loop import Candidate


@dataclass(frozen=True)
class PlanStep:
    target: int
    predicted_do_effect: float      # CWM's predicted effect of do(target); advisory only
    cited_claim_ids: tuple = ()


@dataclass(frozen=True)
class PlanProposal:
    steps: tuple                    # tuple[PlanStep], ordered
    predicted_do_effects: dict = field(default_factory=dict)
    declared_failure_modes: tuple = ()
    cost_estimate: float = 0.0


class CWMPlanner:
    """Proposes an ordered plan over the FULL candidate set. NO-NARROWING: the returned
    ranking is a permutation of every action, never a subset — the gate always sees the
    whole choice set. `.rank(task)` makes it drop-in for GovernedLoop as a proposer."""

    reliability = None

    def __init__(self, cwm_effect: Any, n_actions: int) -> None:
        # cwm_effect(target) -> float predicted do-effect (the CWM organ's advice)
        self.cwm_effect = cwm_effect
        self.n_actions = n_actions
        self.last_plan: PlanProposal | None = None

    def propose(self, task) -> PlanProposal:
        order = sorted(range(self.n_actions), key=lambda a: -self.cwm_effect(a))
        steps = tuple(PlanStep(a, self.cwm_effect(a),
                               (f"causal:{task.name}:{a}",)) for a in order)
        plan = PlanProposal(steps=steps,
                            predicted_do_effects={a: self.cwm_effect(a) for a in order},
                            declared_failure_modes=("predicted-effect-may-be-wrong",
                                                    "verifier-may-reject-any-step"),
                            cost_estimate=float(self.n_actions))
        self.last_plan = plan
        return plan

    def rank(self, task) -> list[Candidate]:
        plan = self.propose(task)
        # no-narrowing assertion: the plan covers EVERY action exactly once
        targets = [s.target for s in plan.steps]
        assert sorted(targets) == list(range(self.n_actions)), "planner narrowed the choice set"
        return [Candidate(action=f"apply_lever:{s.target}", target=s.target,
                          cited_claim_ids=s.cited_claim_ids) for s in plan.steps]
