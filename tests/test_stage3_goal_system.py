"""STAGE-3 contract tests — GoalSystem + GoalConflictHandler + WriteAuthorityLedger.

Formal model: docs/pre_spec/STAGE3-GOAL-SYSTEM.FORMAL-MODEL-2026-07-03.md (9644089).
Written BEFORE the mechanism files exist (Hard Boundary #17).
Locks: I11 self-resolution structurally inexpressible · I12 deterministic downgrade,
tie escalates · I13 no missed conflict within the predicate class · I14 authority
closure · I15 honest expressiveness bound · the A4 adversarial battery.
"""
from __future__ import annotations

import inspect
import unittest

from aac.goal_system import (
    GoalSpec, conflict, GoalConflictHandler, Resolution, DOWNGRADED, ESCALATE_GOALS,
    InexpressibleGoal,
)
from aac.write_authority import (
    WriteAuthorityLedger, BELIEF_WRITE, MEMORY_WRITE, UnknownAuthority,
)


def g(gid, req, prio=1, down=()):
    return GoalSpec(goal_id=gid, requires=req, priority=prio, downgrade=down)


class ConflictPredicate(unittest.TestCase):     # I13
    def test_detects_shared_var_disagreement(self):
        r = conflict(g("a", {2: 1}), g("b", {2: 0, 3: 1}))
        self.assertIsNotNone(r)
        self.assertEqual((r.var, r.a_state, r.b_state), (2, 1, 0))

    def test_compatible_goals_none(self):
        self.assertIsNone(conflict(g("a", {1: 1}), g("b", {2: 0})))
        self.assertIsNone(conflict(g("a", {1: 1}), g("b", {1: 1, 2: 0})))

    def test_a4_battery_no_missed_conflicts(self):
        pairs = [({0: 1}, {0: 0}), ({1: 0, 2: 1}, {2: 0}), ({3: 1}, {3: 0, 0: 1})]
        for ra, rb in pairs:
            self.assertIsNotNone(conflict(g("a", ra), g("b", rb)))


class ResolveIsGoverned(unittest.TestCase):
    def test_signature_admits_no_organ_or_belief(self):    # I11: structural
        params = list(inspect.signature(GoalConflictHandler.resolve).parameters)
        self.assertEqual(params, ["self", "a", "b"])

    def test_downgrade_walks_predeclared_chain(self):      # I12
        loser = g("b", {2: 0}, prio=1,
                  down=(g("b1", {2: 0, 5: 1}), g("b2", {4: 1})))   # b1 still conflicts, b2 clean
        r = GoalConflictHandler().resolve(g("a", {2: 1}, prio=2), loser)
        self.assertEqual(r.kind, DOWNGRADED)
        self.assertEqual(r.goal.goal_id, "b2")

    def test_empty_or_fully_conflicting_chain_escalates(self):
        r = GoalConflictHandler().resolve(g("a", {2: 1}, prio=2), g("b", {2: 0}, prio=1))
        self.assertEqual(r.kind, ESCALATE_GOALS)
        self.assertIsNotNone(r.report)

    def test_tie_priority_always_escalates(self):          # I12: no coin flips
        r = GoalConflictHandler().resolve(g("a", {2: 1}, prio=1),
                                          g("b", {2: 0}, prio=1, down=(g("b2", {4: 1}),)))
        self.assertEqual(r.kind, ESCALATE_GOALS)

    def test_deterministic(self):
        h = GoalConflictHandler()
        a, b = g("a", {2: 1}, prio=2), g("b", {2: 0}, prio=1, down=(g("b2", {4: 1}),))
        self.assertEqual(h.resolve(a, b), h.resolve(a, b))


class ExpressivenessBound(unittest.TestCase):   # I15
    def test_inexpressible_goal_raises_at_construction(self):
        with self.assertRaises(InexpressibleGoal):
            GoalSpec(goal_id="x", requires={"not-an-int": 1}, priority=1, downgrade=())
        with self.assertRaises(InexpressibleGoal):
            GoalSpec(goal_id="x", requires={2: "high"}, priority=1, downgrade=())


class AuthorityClosure(unittest.TestCase):      # I14
    def test_allowed_authorities_check_cleanly(self):
        events = []
        led = WriteAuthorityLedger(observe=events.append)
        led.grant("attributor", BELIEF_WRITE)
        led.check("attributor", BELIEF_WRITE)   # no raise

    def test_forbidden_authorities_are_unrepresentable(self):
        led = WriteAuthorityLedger()
        for bad in ("gate_write", "shell_write", "terminal_goal_write", "audit_write"):
            with self.assertRaises(UnknownAuthority):
                led.grant("anyone", bad)

    def test_undeclared_writer_refused_and_audited(self):
        events = []
        led = WriteAuthorityLedger(observe=events.append)
        self.assertFalse(led.check("rogue", MEMORY_WRITE))
        self.assertIn("write_refused", [e.get("event") for e in events])


if __name__ == "__main__":
    unittest.main()
