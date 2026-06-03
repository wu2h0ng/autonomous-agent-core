from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import OperationContract  # noqa: E402

from manual_review import ManualReviewConnector  # noqa: E402


class ManualReviewConnectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = ManualReviewConnector()
        self.operation = OperationContract(
            operation_id="op-1",
            name="test_operation",
            target_connector="manual_review",
            risk_level="R3",
            approval_required=True,
        )

    def test_connector_name(self) -> None:
        self.assertEqual(self.connector.connector_name, "manual_review")

    def test_take_snapshot_returns_none(self) -> None:
        result = self.connector.take_snapshot(self.operation)
        self.assertIsNone(result)

    def test_execute_returns_pending_approval(self) -> None:
        result = self.connector.execute(self.operation, {})
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(result["operation_id"], "op-1")
        self.assertIn("assigned_to", result)

    def test_execute_with_approval_required(self) -> None:
        op = OperationContract(
            operation_id="op-2",
            name="needs_approval",
            target_connector="manual_review",
            risk_level="R4",
            approval_required=True,
        )
        result = self.connector.execute(op, {})
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(result["assigned_to"], "approver")

    def test_execute_without_approval_required(self) -> None:
        op = OperationContract(
            operation_id="op-3",
            name="no_approval",
            target_connector="manual_review",
            risk_level="R1",
            approval_required=False,
        )
        result = self.connector.execute(op, {})
        self.assertEqual(result["status"], "pending_approval")
        self.assertIsNone(result["assigned_to"])

    def test_rollback_returns_not_applicable(self) -> None:
        from agent_os_contracts import StateSnapshot

        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            operation_id="op-1",
            connector_name="manual_review",
            snapshot_type="full",
            state_payload={},
            created_at="2026-01-01T00:00:00Z",
        )
        result = self.connector.rollback(snapshot)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIn("reason", result)

    def test_can_rollback_is_false(self) -> None:
        self.assertFalse(self.connector.can_rollback())

    def test_compensating_action_is_none(self) -> None:
        self.assertIsNone(self.connector.compensating_action())


if __name__ == "__main__":
    unittest.main()
