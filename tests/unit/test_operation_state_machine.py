from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import OperationState  # noqa: E402

from agent_os_core.operation_state_machine import (  # noqa: E402
    InvalidStateTransition,
    OperationStateMachine,
)


class OperationStateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = OperationStateMachine()

    # --- Valid transitions ---

    def test_proposed_to_approved(self) -> None:
        result = self.sm.transition(OperationState.PROPOSED, OperationState.APPROVED)
        self.assertEqual(result, OperationState.APPROVED)

    def test_proposed_to_rejected(self) -> None:
        result = self.sm.transition(OperationState.PROPOSED, OperationState.REJECTED)
        self.assertEqual(result, OperationState.REJECTED)

    def test_approved_to_snapshotting(self) -> None:
        result = self.sm.transition(OperationState.APPROVED, OperationState.SNAPSHOTTING)
        self.assertEqual(result, OperationState.SNAPSHOTTING)

    def test_approved_to_executed(self) -> None:
        result = self.sm.transition(OperationState.APPROVED, OperationState.EXECUTED)
        self.assertEqual(result, OperationState.EXECUTED)

    def test_snapshotting_to_executed(self) -> None:
        result = self.sm.transition(OperationState.SNAPSHOTTING, OperationState.EXECUTED)
        self.assertEqual(result, OperationState.EXECUTED)

    def test_snapshotting_to_failed(self) -> None:
        result = self.sm.transition(OperationState.SNAPSHOTTING, OperationState.FAILED)
        self.assertEqual(result, OperationState.FAILED)

    def test_executed_to_observed(self) -> None:
        result = self.sm.transition(OperationState.EXECUTED, OperationState.OBSERVED)
        self.assertEqual(result, OperationState.OBSERVED)

    def test_executed_to_failed(self) -> None:
        result = self.sm.transition(OperationState.EXECUTED, OperationState.FAILED)
        self.assertEqual(result, OperationState.FAILED)

    def test_executed_to_rolling_back(self) -> None:
        result = self.sm.transition(OperationState.EXECUTED, OperationState.ROLLING_BACK)
        self.assertEqual(result, OperationState.ROLLING_BACK)

    def test_executed_to_compensating(self) -> None:
        result = self.sm.transition(OperationState.EXECUTED, OperationState.COMPENSATING)
        self.assertEqual(result, OperationState.COMPENSATING)

    def test_rolling_back_to_rolled_back(self) -> None:
        result = self.sm.transition(OperationState.ROLLING_BACK, OperationState.ROLLED_BACK)
        self.assertEqual(result, OperationState.ROLLED_BACK)

    def test_rolling_back_to_failed(self) -> None:
        result = self.sm.transition(OperationState.ROLLING_BACK, OperationState.FAILED)
        self.assertEqual(result, OperationState.FAILED)

    def test_rolled_back_to_observed(self) -> None:
        result = self.sm.transition(OperationState.ROLLED_BACK, OperationState.OBSERVED)
        self.assertEqual(result, OperationState.OBSERVED)

    def test_compensating_to_observed(self) -> None:
        result = self.sm.transition(OperationState.COMPENSATING, OperationState.OBSERVED)
        self.assertEqual(result, OperationState.OBSERVED)

    def test_compensating_to_failed(self) -> None:
        result = self.sm.transition(OperationState.COMPENSATING, OperationState.FAILED)
        self.assertEqual(result, OperationState.FAILED)

    # --- Invalid transitions ---

    def test_proposed_to_executed_is_invalid(self) -> None:
        with self.assertRaises(InvalidStateTransition) as ctx:
            self.sm.transition(OperationState.PROPOSED, OperationState.EXECUTED)
        self.assertEqual(ctx.exception.current, OperationState.PROPOSED)
        self.assertEqual(ctx.exception.target, OperationState.EXECUTED)

    def test_approved_to_proposed_is_invalid(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.APPROVED, OperationState.PROPOSED)

    def test_executed_to_proposed_is_invalid(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.EXECUTED, OperationState.PROPOSED)

    # --- Terminal states ---

    def test_rejected_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.REJECTED), ())

    def test_observed_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.OBSERVED), ())

    def test_failed_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.FAILED), ())

    def test_transition_from_rejected_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.REJECTED, OperationState.APPROVED)

    def test_transition_from_observed_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.OBSERVED, OperationState.EXECUTED)

    def test_transition_from_failed_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.FAILED, OperationState.PROPOSED)

    # --- allowed_transitions ---

    def test_allowed_transitions_from_proposed(self) -> None:
        allowed = self.sm.allowed_transitions(OperationState.PROPOSED)
        self.assertIn(OperationState.AWAITING_APPROVAL, allowed)
        self.assertIn(OperationState.APPROVED, allowed)
        self.assertIn(OperationState.REJECTED, allowed)
        self.assertEqual(len(allowed), 3)

    def test_allowed_transitions_from_awaiting_approval(self) -> None:
        allowed = self.sm.allowed_transitions(OperationState.AWAITING_APPROVAL)
        self.assertIn(OperationState.APPROVED, allowed)
        self.assertIn(OperationState.REJECTED, allowed)
        self.assertEqual(len(allowed), 2)

    def test_proposed_to_awaiting_approval_is_valid(self) -> None:
        result = self.sm.transition(
            OperationState.PROPOSED, OperationState.AWAITING_APPROVAL
        )
        self.assertEqual(result, OperationState.AWAITING_APPROVAL)

    def test_allowed_transitions_from_approved(self) -> None:
        allowed = self.sm.allowed_transitions(OperationState.APPROVED)
        self.assertIn(OperationState.SNAPSHOTTING, allowed)
        self.assertIn(OperationState.EXECUTED, allowed)
        self.assertEqual(len(allowed), 2)

    def test_allowed_transitions_from_executed(self) -> None:
        allowed = self.sm.allowed_transitions(OperationState.EXECUTED)
        self.assertIn(OperationState.OBSERVED, allowed)
        self.assertIn(OperationState.FAILED, allowed)
        self.assertIn(OperationState.ROLLING_BACK, allowed)
        self.assertIn(OperationState.COMPENSATING, allowed)
        self.assertEqual(len(allowed), 4)

    # --- InvalidStateTransition attributes ---

    def test_invalid_transition_exception_has_current_and_target(self) -> None:
        exc = InvalidStateTransition(OperationState.REJECTED, OperationState.APPROVED)
        self.assertEqual(exc.current, OperationState.REJECTED)
        self.assertEqual(exc.target, OperationState.APPROVED)
        self.assertIn("rejected", exc.message)
        self.assertIn("approved", exc.message)

    def test_invalid_transition_exception_custom_message(self) -> None:
        exc = InvalidStateTransition(
            OperationState.FAILED, OperationState.PROPOSED, message="custom msg"
        )
        self.assertEqual(exc.message, "custom msg")


if __name__ == "__main__":
    unittest.main()
