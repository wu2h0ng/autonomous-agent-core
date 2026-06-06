from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import OperationContract, StateSnapshot  # noqa: E402

from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402


def _operation(operation_id: str = "operation-1") -> OperationContract:
    return OperationContract(
        operation_id=operation_id,
        name="op",
        target_connector="action_record",
        risk_level="R2",
        approval_required=False,
        snapshot_required=True,
        rollback_supported=True,
        connector_name="action_record",
        action_type="execute",
    )


class ActionRecordStoreTest(unittest.TestCase):
    def test_starts_empty(self) -> None:
        store = ActionRecordStore()
        self.assertEqual(store.records(), ())

    def test_add_record_returns_id_and_persists(self) -> None:
        store = ActionRecordStore()
        record = store.add(operation_id="operation-1", action_type="execute", parameters={"x": 1})
        self.assertIn("record_id", record)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["operation_id"], "operation-1")
        self.assertEqual(store.records()[0]["action_type"], "execute")
        self.assertEqual(store.records()[0]["parameters"], {"x": 1})

    def test_snapshot_state_and_restore(self) -> None:
        store = ActionRecordStore()
        store.add(operation_id="operation-1", action_type="execute", parameters={"x": 1})
        payload = store.snapshot_state()
        store.add(operation_id="operation-2", action_type="execute", parameters={"y": 2})
        self.assertEqual(len(store.records()), 2)
        store.restore(payload)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["operation_id"], "operation-1")

    def test_restore_is_isolated_from_payload_mutation(self) -> None:
        """Snapshot payload must be a deep copy: mutating the live store after
        snapshotting must not change the captured payload."""
        store = ActionRecordStore()
        store.add(operation_id="operation-1", action_type="execute", parameters={"x": 1})
        payload = store.snapshot_state()
        # Mutate the live record in place.
        store.records()[0]["parameters"]["x"] = 999
        store.restore(payload)
        self.assertEqual(store.records()[0]["parameters"]["x"], 1)


class ActionRecordConnectorTest(unittest.TestCase):
    def test_connector_name(self) -> None:
        connector = ActionRecordConnector(store=ActionRecordStore())
        self.assertEqual(connector.connector_name, "action_record")

    def test_execute_writes_real_state(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        result = connector.execute(_operation(), {"amount": 100})
        self.assertEqual(result["status"], "executed")
        self.assertIn("record_id", result)
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["operation_id"], "operation-1")
        self.assertEqual(store.records()[0]["parameters"], {"amount": 100})

    def test_take_snapshot_returns_state_snapshot(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        connector.execute(_operation(), {"amount": 100})
        snapshot = connector.take_snapshot(_operation("operation-2"))
        self.assertIsInstance(snapshot, StateSnapshot)
        self.assertEqual(snapshot.connector_name, "action_record")
        self.assertEqual(snapshot.operation_id, "operation-2")
        self.assertTrue(snapshot.snapshot_id)
        self.assertTrue(snapshot.created_at)

    def test_snapshot_then_mutate_then_rollback_restores_exactly(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        connector.execute(_operation("operation-1"), {"amount": 100})
        snapshot = connector.take_snapshot(_operation("operation-2"))

        # Real mutation after snapshot.
        connector.execute(_operation("operation-2"), {"amount": 200})
        self.assertEqual(len(store.records()), 2)

        result = connector.rollback(snapshot)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["parameters"], {"amount": 100})

    def test_can_rollback_true(self) -> None:
        connector = ActionRecordConnector(store=ActionRecordStore())
        self.assertTrue(connector.can_rollback())

    def test_compensating_action_is_real_description(self) -> None:
        connector = ActionRecordConnector(store=ActionRecordStore())
        description = connector.compensating_action()
        self.assertIsInstance(description, str)
        self.assertTrue(description.strip())


if __name__ == "__main__":
    unittest.main()
