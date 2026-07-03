"""GoalSystem — declared goals, decidable conflict, governed downgrade (Stage-3).

Formal model: docs/pre_spec/STAGE3-GOAL-SYSTEM.FORMAL-MODEL-2026-07-03.md (9644089).

Success predicates are CONJUNCTIVE EQUALITY only — the expressiveness bound is explicit
(I15): a goal that cannot be written as {var:int -> state:int} raises InexpressibleGoal at
construction and must be escalated by the caller, never silently approximated (and never
handed to an LLM — no organ exists at this layer, structurally).

resolve() is a pure function over two GoalSpecs. Its SIGNATURE admits no organ, belief,
or confidence input: self-resolution by any model is inexpressible in the type (I11).
Tie priority always escalates (I12) — the system never flips a coin over goals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DOWNGRADED = "DOWNGRADED"
ESCALATE_GOALS = "ESCALATE_GOALS"


class InexpressibleGoal(ValueError):
    """The goal is outside the conjunctive-equality predicate class (I15)."""


@dataclass(frozen=True)
class GoalSpec:
    goal_id: str
    requires: dict          # {var:int -> state:int}, the deterministic success predicate
    priority: int           # static, declared
    downgrade: tuple = ()   # pre-declared downgrade lattice (finite chain of GoalSpec)

    def __post_init__(self) -> None:
        for v, s in self.requires.items():
            if not isinstance(v, int) or not isinstance(s, int):
                raise InexpressibleGoal(
                    f"goal '{self.goal_id}': requires must map int var -> int state; "
                    f"got {v!r}:{s!r} — escalate, do not approximate")

    def satisfied(self, x: list) -> bool:
        return all(x[v] == s for v, s in self.requires.items())


@dataclass(frozen=True)
class ConflictReport:
    var: int
    a_state: int
    b_state: int
    a_goal: str = ""
    b_goal: str = ""


def conflict(a: GoalSpec, b: GoalSpec) -> Optional[ConflictReport]:
    """Decidable pairwise check (I13): shared variable, disagreeing required states."""
    for v in sorted(set(a.requires) & set(b.requires)):
        if a.requires[v] != b.requires[v]:
            return ConflictReport(v, a.requires[v], b.requires[v], a.goal_id, b.goal_id)
    return None


@dataclass(frozen=True)
class Resolution:
    kind: str                              # DOWNGRADED | ESCALATE_GOALS
    goal: Optional[GoalSpec] = None        # the downgraded loser (DOWNGRADED only)
    report: Optional[ConflictReport] = None


class GoalConflictHandler:
    """Deterministic resolution over the pre-declared lattice. NO organ input (I11)."""

    def resolve(self, a: GoalSpec, b: GoalSpec) -> Resolution:
        report = conflict(a, b)
        if report is None:
            return Resolution(ESCALATE_GOALS, None, None)   # misuse: nothing to resolve
        if a.priority == b.priority:
            return Resolution(ESCALATE_GOALS, None, report)  # I12: never flip a coin
        winner, loser = (a, b) if a.priority > b.priority else (b, a)
        for g_prime in loser.downgrade:                      # first non-conflicting step wins
            if conflict(winner, g_prime) is None:
                return Resolution(DOWNGRADED, g_prime, report)
        return Resolution(ESCALATE_GOALS, None, report)      # chain empty/exhausted
