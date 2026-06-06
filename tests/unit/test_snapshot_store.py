from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import StateSnapshot  # noqa: E402

from agent_os_core.snapshot_store import InMemorySnapshotStore, SnapshotStore  # noqa: E402


def _snapshot(snapshot_id: str, operation_id: str) -> StateSnapshot:
    return StateSnapshot(
        snapshot_id=snapshot_id,
        operation_id=operation_id,
        connector_name="action_record",
        snapshot_type="full",
        state_payload={"records": []},
        created_at="2026-06-06T00:00:00Z",
    )


class InMemorySnapshotStoreTest(unittest.TestCase):
    def test_is_snapshot_store(self) -> None:
        self.assertIsInstance(InMemorySnapshotStore(), SnapshotStore)

    def test_save_and_get(self) -> None:
        store = InMemorySnapshotStore()
        snap = _snapshot("snap-1", "operation-1")
        saved = store.save(snap)
        self.assertEqual(saved, snap)
        self.assertEqual(store.get("snap-1"), snap)

    def test_get_unknown_returns_none(self) -> None:
        store = InMemorySnapshotStore()
        self.assertIsNone(store.get("missing"))

    def test_list_for_operation(self) -> None:
        store = InMemorySnapshotStore()
        store.save(_snapshot("snap-1", "operation-1"))
        store.save(_snapshot("snap-2", "operation-1"))
        store.save(_snapshot("snap-3", "operation-2"))
        for_op1 = store.list_for_operation("operation-1")
        self.assertEqual({s.snapshot_id for s in for_op1}, {"snap-1", "snap-2"})
        self.assertEqual(store.list_for_operation("operation-x"), ())


if __name__ == "__main__":
    unittest.main()
