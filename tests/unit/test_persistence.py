from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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

    def _agent_runtime_snapshot(self, run_id: str, *, output: dict[str, object] | None = None):
        from agent_os_core.agent_runtime import AgentToolResult, RunStateSnapshot

        return RunStateSnapshot(
            run_id=run_id,
            trace_id=f"trace-{run_id}",
            step_id=f"call-{run_id}",
            status="ok",
            pending_tool_call=None,
            last_result=AgentToolResult(
                call_id=f"call-{run_id}",
                tool_name="safe.echo",
                status="ok",
                output=output or {"value": "ok"},
                trace_id=f"trace-{run_id}",
                metadata={"result_class": "safe"},
            ),
            metadata={
                "tool_name": "safe.echo",
                "call_fingerprint": f"call-fp-{run_id}",
                "context_fingerprint": f"context-fp-{run_id}",
                "tool_spec_fingerprint": f"spec-fp-{run_id}",
            },
            last_completed_boundary="agent_runtime.invoke_tool",
        )

    def _approval_context(self, approval_id: str, proposal_id: str):
        from agent_os_contracts import (
            BusinessIntent,
            EvidenceChain,
            MetricContract,
            OperationContract,
            QueryPlan,
            QueryResult,
            SQLSafetyResult,
        )
        from agent_os_core import ApprovalOperationContext

        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        evidence = EvidenceChain(
            evidence_chain_id=f"evidence-{approval_id}",
            intent=BusinessIntent(
                intent_id=f"intent-{approval_id}",
                question="GMV 记录行动",
                metric_name="gmv",
            ),
            metric_contract=metric,
            query_plan=QueryPlan(
                metric_name="gmv",
                sql="select sum(paid_amount) as gmv from sales.orders limit :limit",
                parameters={"limit": 100},
            ),
            sql_safety=SQLSafetyResult(
                allowed=True,
                reasons=(),
                checked_schemas=("sales",),
                checked_tables=("sales.orders",),
                bound_parameters=("limit",),
                limit_value=100,
            ),
            query_result=QueryResult(rows=({"gmv": 128800.0},), row_count=1),
            conclusion="GMV is 128800.0.",
            confidence=0.9,
            limitations=(),
            trace_id=f"trace-{approval_id}",
        )
        operation = OperationContract(
            operation_id=f"operation-{proposal_id}",
            name="operation_for_gmv",
            target_connector="action_record",
            risk_level="R3",
            approval_required=True,
            rollback_supported=True,
            snapshot_required=True,
            connector_name="action_record",
            action_type="execute",
            idempotency_key=f"idem-{approval_id}",
        )
        return ApprovalOperationContext(
            approval_id=approval_id,
            proposal_id=proposal_id,
            operation=operation,
            action_parameters={"evidence_chain_id": evidence.evidence_chain_id, "amount": 100},
            evidence_chain=evidence,
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
        revised2 = self._asset("knowledge-3", "trace-k")
        store.register_version(revised2)
        self.assertEqual(store.version_of("trace-k"), 3)
        self.assertEqual(store.get_by_trace("trace-k"), revised2)
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
        approved = runtime2.approve(
            "approval-1",
            reason="looks good",
            approved_by="ops@example.com",
        )
        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.approved_by, "ops@example.com")
        self.assertEqual(store.get("approval-1").status, "approved")
        self.assertEqual(store.get("approval-1").approved_by, "ops@example.com")

    def test_approval_context_round_trip_and_delete_over_sql_store(self) -> None:
        from agent_os_persistence import SqlApprovalContextStore

        store = SqlApprovalContextStore(self.engine)
        context = self._approval_context("approval-context-1", "proposal-context-1")

        store.save(context)
        self.assertEqual(store.get("approval-context-1"), context)
        self.assertIsNone(store.get("approval-context-missing"))

        store.delete("approval-context-1")
        self.assertIsNone(store.get("approval-context-1"))

    def test_approval_context_claim_blocks_double_consume_and_allows_retry(self) -> None:
        from agent_os_persistence import SqlApprovalContextStore

        store = SqlApprovalContextStore(self.engine)
        context = self._approval_context("approval-context-claim", "proposal-context-claim")

        store.save(context)
        self.assertEqual(store.claim("approval-context-claim"), context)
        self.assertIsNone(store.claim("approval-context-claim"))

        store.release_claim("approval-context-claim")
        self.assertEqual(store.claim("approval-context-claim"), context)

        store.delete("approval-context-claim")
        self.assertIsNone(store.claim("approval-context-claim"))

    def test_approval_context_claim_reclaims_only_stale_executing_context(self) -> None:
        from agent_os_persistence import SqlApprovalContextStore

        current_time = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)

        def clock() -> datetime:
            return current_time

        store = SqlApprovalContextStore(self.engine, clock=clock)
        context = self._approval_context("approval-context-stale", "proposal-context-stale")

        store.save(context)
        self.assertEqual(
            store.claim("approval-context-stale", reclaim_stale_after_seconds=60),
            context,
        )

        current_time += timedelta(seconds=59)
        self.assertIsNone(store.claim("approval-context-stale", reclaim_stale_after_seconds=60))

        current_time += timedelta(seconds=2)
        self.assertEqual(
            store.claim("approval-context-stale", reclaim_stale_after_seconds=60),
            context,
        )

    def test_approval_context_stale_reclaim_allows_only_one_cross_process_winner(self) -> None:
        from sqlalchemy import create_engine

        from agent_os_persistence import SqlApprovalContextStore, create_all

        current_time = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)

        def clock() -> datetime:
            return current_time

        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(
                f"sqlite:///{Path(tmp) / 'claim-race.db'}",
                connect_args={"check_same_thread": False},
            )
            create_all(engine)
            setup_store = SqlApprovalContextStore(engine, clock=clock)
            context = self._approval_context(
                "approval-context-race",
                "proposal-context-race",
            )

            setup_store.save(context)
            self.assertEqual(
                setup_store.claim("approval-context-race", reclaim_stale_after_seconds=60),
                context,
            )

            current_time += timedelta(seconds=61)
            read_barrier = threading.Barrier(2)

            class RacingSqlApprovalContextStore(SqlApprovalContextStore):
                def _with_claim(self, payload: dict[str, object]) -> dict[str, object]:
                    read_barrier.wait(timeout=5)
                    return super()._with_claim(payload)

            winners: list[str] = []
            errors: list[BaseException] = []

            def try_reclaim(label: str) -> None:
                store = RacingSqlApprovalContextStore(engine, clock=clock)
                try:
                    claimed = store.claim(
                        "approval-context-race",
                        reclaim_stale_after_seconds=60,
                    )
                    if claimed is not None:
                        winners.append(label)
                except BaseException as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            threads = [
                threading.Thread(target=try_reclaim, args=("reclaimer-1",)),
                threading.Thread(target=try_reclaim, args=("reclaimer-2",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertEqual(errors, [])
            self.assertEqual(len(winners), 1, winners)
            self.assertIn(winners[0], {"reclaimer-1", "reclaimer-2"})

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

    def test_agent_runtime_checkpoint_round_trip_and_rewrite(self) -> None:
        from agent_os_persistence import SqlAgentCheckpointStore

        store = SqlAgentCheckpointStore(self.engine)
        snapshot = self._agent_runtime_snapshot("run-checkpoint")
        store.save(snapshot)

        self.assertEqual(store.get("run-checkpoint"), snapshot)
        self.assertIsNone(store.get("run-missing"))

        updated = self._agent_runtime_snapshot("run-checkpoint", output={"value": "updated"})
        store.save(updated)
        self.assertEqual(SqlAgentCheckpointStore(self.engine).get("run-checkpoint"), updated)

    def test_action_record_store_round_trip_and_idempotency_over_sql_store(self) -> None:
        from agent_os_persistence import SqlActionRecordStore

        store = SqlActionRecordStore(self.engine)
        first = store.add(
            operation_id="operation-action-1",
            action_type="execute",
            parameters={"amount": 100},
            idempotency_key="idem-action-1",
        )
        replay = store.add(
            operation_id="operation-action-1",
            action_type="execute",
            parameters={"amount": 100},
            idempotency_key="idem-action-1",
        )

        self.assertEqual(first["record_id"], replay["record_id"])
        self.assertEqual(replay["status"], "idempotent_replay")
        self.assertEqual(len(store.records()), 1)

        store2 = SqlActionRecordStore(self.engine)
        self.assertEqual(store2.records()[0]["record_id"], first["record_id"])
        with self.assertRaises(ValueError):
            store2.add(
                operation_id="operation-action-1",
                action_type="execute",
                parameters={"amount": 200},
                idempotency_key="idem-action-1",
            )

    def test_unit_of_work_commits_both_stores(self) -> None:
        from agent_os_persistence import SqlFeedbackStore, SqlKnowledgeStore, SqlUnitOfWork

        uow = SqlUnitOfWork(self.engine)
        with uow() as (fb, kn):
            fb.record(self._feedback("feedback-uow", "trace-uow", "adopted"))
            kn.register(self._asset("knowledge-uow", "trace-uow"))

        # A fresh engine-bound store sees both committed writes.
        self.assertEqual(len(SqlFeedbackStore(self.engine).get_by_trace("trace-uow")), 1)
        self.assertEqual(SqlKnowledgeStore(self.engine).version_of("trace-uow"), 1)

    def test_unit_of_work_rolls_back_both_on_failure(self) -> None:
        from agent_os_persistence import SqlFeedbackStore, SqlKnowledgeStore, SqlUnitOfWork

        uow = SqlUnitOfWork(self.engine)
        with self.assertRaises(RuntimeError):
            with uow() as (fb, kn):
                fb.record(self._feedback("feedback-rb", "trace-rb", "adopted"))
                kn.register(self._asset("knowledge-rb", "trace-rb"))
                raise RuntimeError("boom after both writes")

        # Neither write survived: the transaction rolled back atomically.
        self.assertEqual(SqlFeedbackStore(self.engine).get_by_trace("trace-rb"), ())
        self.assertEqual(SqlKnowledgeStore(self.engine).version_of("trace-rb"), 0)


if __name__ == "__main__":
    unittest.main()
