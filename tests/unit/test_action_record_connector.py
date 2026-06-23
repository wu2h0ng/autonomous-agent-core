from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import OperationContract, StateSnapshot  # noqa: E402

from action_record import (  # noqa: E402
    ActionRecordConnector,
    ActionRecordExecutionUncertain,
    ActionRecordStore,
)


def _operation(
    operation_id: str = "operation-1", idempotency_key: str | None = None
) -> OperationContract:
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
        idempotency_key=idempotency_key,
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

    def test_dry_run_previews_without_mutating_store(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        preview = connector.dry_run(_operation(idempotency_key="key-1"), {"amount": 100})

        self.assertEqual(preview["status"], "dry_run")
        self.assertEqual(preview["connector_name"], "action_record")
        self.assertEqual(preview["idempotency_key"], "key-1")
        self.assertEqual(store.records(), ())

    def test_idempotency_key_prevents_retry_double_write(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        operation = _operation(idempotency_key="trace-1:proposal-1")

        first = connector.execute(operation, {"amount": 100})
        second = connector.execute(operation, {"amount": 100})

        self.assertEqual(first["record_id"], second["record_id"])
        self.assertEqual(second["status"], "idempotent_replay")
        self.assertEqual(second["replay_status"], "idempotent_replay")
        self.assertEqual(second["external_ack_status"], "not_applicable")
        self.assertNotIn("last_replay_status", second)
        self.assertEqual(len(store.records()), 1)

    def test_idempotent_replay_updates_retry_audit_without_double_write(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        operation = _operation(idempotency_key="trace-1:proposal-1")

        connector.execute(operation, {"amount": 100})
        connector.execute(operation, {"amount": 100})

        self.assertEqual(len(store.records()), 1)
        self.assertEqual(store.records()[0]["replay_count"], 1)
        self.assertEqual(store.records()[0]["last_replay_status"], "idempotent_replay")

    def test_replay_after_uncertain_execution_preserves_audit_without_raw_parameters(
        self,
    ) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        operation = _operation(idempotency_key="trace-1:proposal-1")

        first = connector.execute(operation, {"amount": 100, "secret": "raw-ack-token"})
        store.mark_execution_uncertain(
            record_id=first["record_id"],
            operation_id=operation.operation_id,
            action_type=operation.action_type,
            idempotency_key=operation.idempotency_key,
            parameters={"amount": 100, "secret": "raw-ack-token"},
            reason_code="lost_ack_after_write",
            error_type="TimeoutError",
        )
        replay = connector.execute(operation, {"amount": 100, "secret": "raw-ack-token"})

        self.assertEqual(replay["status"], "idempotent_replay")
        self.assertEqual(replay["replay_status"], "idempotent_replay_after_uncertain")
        self.assertEqual(replay["external_ack_status"], "unknown")
        self.assertEqual(replay["execution_certainty"], "uncertain_recovered")
        self.assertEqual(replay["ack_status"], "lost_after_write_recovered_by_idempotency")
        self.assertNotIn("last_replay_status", replay)
        self.assertEqual(len(store.records()), 1)
        record = store.records()[0]
        self.assertEqual(record["uncertain_execution_count"], 1)
        self.assertEqual(record["last_uncertain_execution"]["reason_code"], "lost_ack_after_write")
        self.assertIn("parameters_fingerprint", record["last_uncertain_execution"])
        self.assertNotIn("parameters", record["last_uncertain_execution"])
        self.assertNotIn("raw-ack-token", repr(record["last_uncertain_execution"]))

    def test_uncertain_execution_exception_carries_safe_audit_event(self) -> None:
        exc = ActionRecordExecutionUncertain(
            record_id="record-1",
            operation_id="operation-1",
            action_type="execute",
            idempotency_key="trace-1:proposal-1",
            reason_code="lost_ack_after_write",
            error_type="TimeoutError",
        )

        event = exc.audit_event()

        self.assertEqual(event["step"], "connector_execution_uncertain")
        self.assertEqual(event["record_id"], "record-1")
        self.assertEqual(event["execution_certainty"], "uncertain")
        self.assertEqual(event["ack_status"], "lost_after_write")
        self.assertNotIn("parameters", event)

    def test_reusing_idempotency_key_with_different_payload_fails(self) -> None:
        connector = ActionRecordConnector(store=ActionRecordStore())
        operation = _operation(idempotency_key="trace-1:proposal-1")
        connector.execute(operation, {"amount": 100})

        with self.assertRaises(ValueError):
            connector.execute(operation, {"amount": 200})

    def test_idempotency_conflict_is_audited_without_raw_conflicting_payload(self) -> None:
        store = ActionRecordStore()
        connector = ActionRecordConnector(store=store)
        operation = _operation(idempotency_key="trace-1:proposal-1")
        connector.execute(operation, {"amount": 100})

        with self.assertRaises(ValueError):
            connector.execute(operation, {"amount": 200, "secret": "raw-conflict-value"})

        record = store.records()[0]
        self.assertEqual(record["conflict_count"], 1)
        self.assertEqual(record["last_conflict"]["operation_id"], "operation-1")
        self.assertEqual(record["last_conflict"]["action_type"], "execute")
        self.assertIn("parameters_fingerprint", record["last_conflict"])
        self.assertNotIn("parameters", record["last_conflict"])
        self.assertNotIn("raw-conflict-value", repr(record))

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
