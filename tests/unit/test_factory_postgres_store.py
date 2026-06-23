from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "packages" / "sdk" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
RUN_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class FactoryPostgresStoreTest(unittest.TestCase):
    """Wire the persistence adapters through the factory and prove durability.

    Uses an injected in-memory SQLite engine as a stand-in for PostgreSQL. The
    key property: a knowledge candidate written by one runtime instance is
    visible to a SEPARATE runtime instance built on the same engine — i.e. it
    survives a simulated process restart, which the in-memory backend cannot do.
    """

    def _engine(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def _config(self, engine):
        from agent_os_api.runtime_factory import STORE_POSTGRES, RuntimeFactoryConfig

        return RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            store_backend=STORE_POSTGRES,
            store_engine=engine,
        )

    def test_postgres_backend_persists_across_runtime_instances(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory
        from agent_os_persistence import EmbeddingKnowledgeStore

        engine = self._engine()
        config = self._config(engine)

        # Instance 1 runs the loop -> writes a knowledge candidate to the DB.
        runtime1 = ContentCommerceRuntimeFactory(config).build()
        # The postgres knowledge store is the embedding decorator (write-side cascade).
        self.assertIsInstance(runtime1.knowledge_store, EmbeddingKnowledgeStore)
        result = runtime1.run("GMV", dict(RUN_PARAMS))
        trace_id = result.evidence_chain.trace_id

        # Instance 2 (fresh build, same engine = simulated restart) sees it.
        factory2 = ContentCommerceRuntimeFactory(config)
        runtime2 = factory2.build()
        asset = runtime2.knowledge_store.get_by_trace(trace_id)
        self.assertIsNotNone(asset, "knowledge candidate did not persist across instances")
        self.assertEqual(runtime2.knowledge_store.version_of(trace_id), 1)

        # P5.1b: a self-report does NOT promote knowledge (wirehead closed)...
        runtime2.record_outcome(trace_id=trace_id, outcome="adopted")
        self.assertEqual(runtime2.knowledge_store.version_of(trace_id), 1)
        # ...only realized external value (operator adoption) promotes it, durably.
        factory2.adoption_ingest().submit(trace_id=trace_id, outcome="adopted")
        runtime2.promote_from_adoption(trace_id)
        runtime3 = ContentCommerceRuntimeFactory(config).build()
        self.assertEqual(runtime3.knowledge_store.version_of(trace_id), 2)

    def test_outcome_flows_into_retrieval_index(self) -> None:
        # End-to-end: run() indexes the candidate, promote_from_adoption re-embeds it with
        # the realized-adoption outcome, and the retriever surfaces that outcome (outcome_boost > 0).
        from agent_os_contracts import KnowledgeQuery

        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory

        engine = self._engine()
        config = self._config(engine)
        factory = ContentCommerceRuntimeFactory(config)
        runtime = factory.build()

        result = runtime.run("GMV", dict(RUN_PARAMS))
        trace_id = result.evidence_chain.trace_id
        # P5.1b: knowledge promotion (and its re-embed) is driven by realized
        # external value, not self-report.
        factory.adoption_ingest().submit(trace_id=trace_id, outcome="adopted")
        runtime.promote_from_adoption(trace_id)

        retriever = factory.build_knowledge_retriever()
        res = retriever.search(KnowledgeQuery(text="GMV", k=10))
        match = next((r for r in res if r.asset.source_trace_id == trace_id), None)
        self.assertIsNotNone(match, "indexed knowledge for the trace was not retrievable")
        self.assertEqual(match.asset.outcome, "adopted")
        self.assertGreater(match.score_breakdown["outcome_boost"], 0.0)

    def test_approval_context_persists_across_runtime_instances(self) -> None:
        from agent_os_contracts import OperationState

        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        result = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        approval_id = result.approval_record.approval_id
        self.assertEqual(result.action_result["status"], "awaiting_approval")

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        approval, operation_trace = runtime2.approve_and_execute_pending_operation(
            approval_id=approval_id,
            reason="approved after restart",
            approved_by="ops@example.com",
        )

        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.approved_by, "ops@example.com")
        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        self.assertEqual(operation_trace.evidence_chain_id, result.evidence_chain.evidence_chain_id)
        action_record_connector = runtime2.connector_registry.get("action_record")
        records = action_record_connector.store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["parameters"]["evidence_chain_id"],
            result.evidence_chain.evidence_chain_id,
        )

        runtime3 = ContentCommerceRuntimeFactory(config).build()
        with self.assertRaises(KeyError):
            runtime3.execute_pending_approved_operation(approval_id=approval_id)

    def test_stale_approval_context_claim_recovers_across_runtime_instances(self) -> None:
        from agent_os_contracts import OperationState
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory
        from agent_os_persistence import approval_operation_contexts

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        result = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        approval_id = result.approval_record.approval_id
        self.assertEqual(result.action_result["status"], "awaiting_approval")

        # Simulate a process crash after claiming the durable context but before
        # release/delete. A later runtime must reclaim only after the lease is stale.
        self.assertIsNotNone(runtime1.approval_context_store.claim(approval_id))
        with engine.begin() as conn:
            row = conn.execute(
                approval_operation_contexts.select().where(
                    approval_operation_contexts.c.approval_id == approval_id
                )
            ).fetchone()
            payload = dict(row.payload)
            payload["_claim"] = {
                "claimed_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
            }
            conn.execute(
                approval_operation_contexts.update()
                .where(approval_operation_contexts.c.approval_id == approval_id)
                .values(payload=payload, status="executing")
            )

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        approval, operation_trace = runtime2.approve_and_execute_pending_operation(
            approval_id=approval_id,
            reason="approved after stale claim",
            approved_by="ops@example.com",
        )

        self.assertEqual(approval.status, "approved")
        self.assertEqual(operation_trace.state, OperationState.EXECUTED)
        records = runtime2.connector_registry.get("action_record").store.records()
        self.assertEqual(len(records), 1)

        runtime3 = ContentCommerceRuntimeFactory(config).build()
        with self.assertRaises(KeyError):
            runtime3.execute_pending_approved_operation(approval_id=approval_id)

    def test_action_record_store_persists_across_runtime_instances(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        result = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        runtime1.approve_and_execute_pending_operation(
            approval_id=result.approval_record.approval_id,
            reason="approved after restart",
            approved_by="ops@example.com",
        )

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        action_record_connector = runtime2.connector_registry.get("action_record")
        records = action_record_connector.store.records()

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["parameters"]["evidence_chain_id"],
            result.evidence_chain.evidence_chain_id,
        )

    def test_action_record_replay_after_runtime_restart_does_not_double_write(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        result = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        runtime1.approve_and_execute_pending_operation(
            approval_id=result.approval_record.approval_id,
            reason="approved before restart",
            approved_by="ops@example.com",
        )

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        operation_trace = runtime2.execute_approved_operation(
            approval_id=result.approval_record.approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

        self.assertEqual(operation_trace.events[-1]["status"], "idempotent_replay")
        records = runtime2.connector_registry.get("action_record").store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["replay_count"], 1)
        self.assertEqual(records[0]["last_replay_status"], "idempotent_replay")

    def test_action_record_sql_store_persists_conflict_audit_without_raw_payload(self) -> None:
        from agent_os_persistence import SqlActionRecordStore, create_all

        engine = self._engine()
        create_all(engine)
        store = SqlActionRecordStore(engine)
        store.add(
            operation_id="operation-1",
            action_type="execute",
            parameters={"amount": 100},
            idempotency_key="trace-1:proposal-1",
        )

        with self.assertRaises(ValueError):
            store.add(
                operation_id="operation-1",
                action_type="execute",
                parameters={"amount": 200, "secret": "raw-conflict-value"},
                idempotency_key="trace-1:proposal-1",
            )

        records = SqlActionRecordStore(engine).records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["conflict_count"], 1)
        self.assertEqual(records[0]["last_conflict"]["operation_id"], "operation-1")
        self.assertIn("parameters_fingerprint", records[0]["last_conflict"])
        self.assertNotIn("parameters", records[0]["last_conflict"])
        self.assertNotIn("raw-conflict-value", repr(records[0]))

    def test_action_record_rollback_snapshot_survives_restart_without_deleting_later_records(
        self,
    ) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        first = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        runtime1.approve_and_execute_pending_operation(
            approval_id=first.approval_record.approval_id,
            reason="approved first action",
            approved_by="ops@example.com",
        )

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        second = runtime2.run("GMV 记录行动", {**RUN_PARAMS, "limit": 50})
        _approval, second_trace = runtime2.approve_and_execute_pending_operation(
            approval_id=second.approval_record.approval_id,
            reason="approved second action",
            approved_by="ops@example.com",
        )
        snapshot_event = next(
            event for event in second_trace.events if event.get("step") == "state_snapshot"
        )
        snapshot_id = snapshot_event["snapshot_id"]

        runtime_extra = ContentCommerceRuntimeFactory(config).build()
        later = runtime_extra.run("GMV 记录行动", {**RUN_PARAMS, "limit": 75})
        runtime_extra.approve_and_execute_pending_operation(
            approval_id=later.approval_record.approval_id,
            reason="approved later action",
            approved_by="ops@example.com",
        )

        runtime3 = ContentCommerceRuntimeFactory(config).build()
        rollback = runtime3.rollback(snapshot_id)
        self.assertEqual(rollback["status"], "rolled_back")

        runtime4 = ContentCommerceRuntimeFactory(config).build()
        records = runtime4.connector_registry.get("action_record").store.records()
        evidence_ids = {record["parameters"]["evidence_chain_id"] for record in records}
        self.assertEqual(len(records), 2)
        self.assertEqual(
            evidence_ids,
            {
                first.evidence_chain.evidence_chain_id,
                later.evidence_chain.evidence_chain_id,
            },
        )

    def test_unknown_store_backend_raises(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        config = RuntimeFactoryConfig(
            domain_pack_path=ROOT / "domain_packs" / "content_commerce",
            store_backend="redis",
        )
        with self.assertRaises(ValueError):
            ContentCommerceRuntimeFactory(config).build()


if __name__ == "__main__":
    unittest.main()
