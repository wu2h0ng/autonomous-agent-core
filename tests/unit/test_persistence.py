from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "persistence" / "src"))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class PersistenceRepositoriesTest(unittest.TestCase):
    """Exercise the SQLAlchemy-Core stores against in-memory SQLite.

    The same repository code runs on PostgreSQL in production; SQLite (generic
    JSON column) verifies round-trip + dedup/version/append semantics with no DB
    infrastructure. PG-specific integration is covered by guarded tests later.
    """

    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_persistence import create_all

        # A single shared connection so the :memory: DB persists across operations.
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        create_all(self.engine)

    def _feedback(self, fid: str, trace: str, outcome: str):
        from agent_os_contracts import FeedbackEvent

        return FeedbackEvent(
            feedback_id=fid,
            trace_id=trace,
            outcome=outcome,
            metrics={"gmv": 1200.0},
            reviewer="ops@example.com",
        )

    def _asset(self, asset_id: str, trace: str):
        from agent_os_contracts import KnowledgeAsset, LifecycleState

        return KnowledgeAsset(
            asset_id=asset_id,
            title="[gmv] last 7 days",
            asset_type="decision_loop",
            source_trace_id=trace,
            owner="revenue_ops",
            state=LifecycleState.DRAFT,
        )

    def _snapshot(self, sid: str, op: str):
        from agent_os_contracts import StateSnapshot

        return StateSnapshot(
            snapshot_id=sid,
            operation_id=op,
            connector_name="action_record",
            snapshot_type="full",
            state_payload={"records": [1, 2, 3]},
            created_at="2026-06-06T00:00:00Z",
            metadata={"note": "pre-exec"},
        )

    def test_feedback_round_trip_and_append(self) -> None:
        from agent_os_persistence import SqlFeedbackStore

        store = SqlFeedbackStore(self.engine)
        e1 = self._feedback("feedback-1", "trace-a", "adopted")
        e2 = self._feedback("feedback-2", "trace-a", "rejected")
        store.record(e1)
        store.record(e2)

        got = store.get_by_trace("trace-a")
        self.assertEqual(got, (e1, e2))  # round-trip equality + insertion order
        self.assertEqual(store.get_by_trace("trace-missing"), ())
        self.assertEqual(store.outcome_counts(), {"adopted": 1, "rejected": 1})

    def test_knowledge_dedup_and_versioning(self) -> None:
        from agent_os_persistence import SqlKnowledgeStore

        store = SqlKnowledgeStore(self.engine)
        first = self._asset("knowledge-1", "trace-k")
        store.register(first)
        self.assertEqual(store.version_of("trace-k"), 1)
        self.assertEqual(store.get_by_trace("trace-k"), first)

        # register again with a different asset for the same trace -> dedup no-op.
        store.register(self._asset("knowledge-DUP", "trace-k"))
        self.assertEqual(store.version_of("trace-k"), 1)
        self.assertEqual(store.get_by_trace("trace-k").asset_id, "knowledge-1")

        # register_version supersedes and bumps.
        revised = self._asset("knowledge-2", "trace-k")
        store.register_version(revised)
        self.assertEqual(store.version_of("trace-k"), 2)
        self.assertEqual(store.get_by_trace("trace-k"), revised)
        self.assertEqual(store.version_of("trace-missing"), 0)

    def test_approval_round_trip_and_lifecycle_over_sql_store(self) -> None:
        from agent_os_core import ApprovalLiteRuntime
        from agent_os_persistence import SqlApprovalStore

        store = SqlApprovalStore(self.engine)
        # Direct round-trip.
        runtime = ApprovalLiteRuntime(store=store)
        pending = runtime.create_pending(
            approval_id="approval-1", proposal_id="proposal-1", approver_role="Business Owner"
        )
        self.assertEqual(store.get("approval-1"), pending)
        self.assertIsNone(store.get("approval-missing"))

        # Lifecycle persists: a SEPARATE runtime on the same store approves it.
        runtime2 = ApprovalLiteRuntime(store=SqlApprovalStore(self.engine))
        approved = runtime2.approve("approval-1", reason="looks good")
        self.assertEqual(approved.status, "approved")
        self.assertEqual(store.get("approval-1").status, "approved")

    def test_snapshot_round_trip_and_rewrite(self) -> None:
        from agent_os_persistence import SqlSnapshotStore

        store = SqlSnapshotStore(self.engine)
        snap = self._snapshot("snap-1", "op-1")
        store.save(snap)

        loaded = store.get("snap-1")
        self.assertEqual(loaded, snap)  # round-trip incl. dict fields
        self.assertIsNone(store.get("snap-missing"))
        self.assertEqual(store.list_for_operation("op-1"), (snap,))

        # save with same id updates rather than duplicating.
        snap2 = self._snapshot("snap-1", "op-1")
        store.save(snap2)
        self.assertEqual(store.list_for_operation("op-1"), (snap2,))


if __name__ == "__main__":
    unittest.main()
