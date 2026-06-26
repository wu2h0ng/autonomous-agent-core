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


class _LostAckAfterWriteConnector:
    """Fault wrapper: commit the connector write, mark uncertainty, then lose ACK once."""

    def __init__(self, inner):
        self._inner = inner
        self._failed_once = False

    @property
    def connector_name(self) -> str:
        return self._inner.connector_name

    @property
    def store(self):
        return self._inner.store

    def take_snapshot(self, operation):
        return self._inner.take_snapshot(operation)

    def dry_run(self, operation, parameters):
        return self._inner.dry_run(operation, parameters)

    def execute(self, operation, parameters):
        from action_record import ActionRecordExecutionUncertain

        result = self._inner.execute(operation, parameters)
        if not self._failed_once:
            self._failed_once = True
            self._inner.store.mark_execution_uncertain(
                record_id=result["record_id"],
                operation_id=operation.operation_id,
                action_type=operation.action_type,
                idempotency_key=operation.idempotency_key,
                parameters=parameters,
                reason_code="lost_ack_after_write",
                error_type="TimeoutError",
            )
            raise ActionRecordExecutionUncertain(
                record_id=result["record_id"],
                operation_id=operation.operation_id,
                action_type=operation.action_type,
                idempotency_key=operation.idempotency_key,
                reason_code="lost_ack_after_write",
                error_type="TimeoutError",
            )
        return result

    def rollback(self, snapshot):
        return self._inner.rollback(snapshot)

    def can_rollback(self) -> bool:
        return self._inner.can_rollback()

    def compensating_action(self):
        return self._inner.compensating_action()


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

    def test_agent_runtime_checkpoint_store_is_factory_selected_and_persists_resume(
        self,
    ) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory
        from agent_os_core.agent_runtime import (
            AgentRunContext,
            AgentToolCall,
            TrustedLoopAgentRuntimeAdapter,
        )
        from agent_os_persistence import SqlAgentCheckpointStore

        engine = self._engine()
        config = self._config(engine)
        first_factory = ContentCommerceRuntimeFactory(config)
        first_runtime = first_factory.build()
        checkpoint_store = first_factory.build_agent_checkpoint_store()
        self.assertIsInstance(checkpoint_store, SqlAgentCheckpointStore)

        context = AgentRunContext(
            tenant_id="tenant",
            workspace_id="workspace",
            principal_id="internal",
            principal_role="internal",
            run_id="factory-checkpoint-run",
            trace_id="factory-checkpoint-trace",
            policy_scope=frozenset({"trusted_loop:evaluate"}),
        )
        first_adapter = TrustedLoopAgentRuntimeAdapter(
            first_runtime,
            shell_view=first_runtime.shell_view,
            checkpoint_store=checkpoint_store,
        )
        first = first_adapter.evaluate(
            context=context,
            question="GMV",
            parameters=dict(RUN_PARAMS),
        )
        self.assertEqual(first.status, "ok")

        second_factory = ContentCommerceRuntimeFactory(config)
        second_runtime = second_factory.build()
        second_adapter = TrustedLoopAgentRuntimeAdapter(
            second_runtime,
            shell_view=second_runtime.shell_view,
            checkpoint_store=second_factory.build_agent_checkpoint_store(),
        )
        resumed = second_adapter.runtime.resume_from_checkpoint(
            AgentToolCall(
                call_id=f"{TrustedLoopAgentRuntimeAdapter.TOOL_NAME}:{context.run_id}",
                tool_name=TrustedLoopAgentRuntimeAdapter.TOOL_NAME,
                args={"question": "GMV", "parameters": dict(RUN_PARAMS)},
            ),
            context,
        )

        self.assertEqual(resumed.status, "ok")
        self.assertEqual(resumed.output["type"], "TrustedLoopOutcome")
        self.assertEqual(resumed.output["status"], "ok")
        self.assertEqual(
            resumed.output["result"]["trace_id"],
            first.output.result.evidence_chain.trace_id,
        )
        self.assertEqual(
            resumed.output["result"]["evidence_chain_id"],
            first.output.result.evidence_chain.evidence_chain_id,
        )

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

    def test_action_record_lost_ack_after_write_retries_without_double_write_and_audits_uncertainty(
        self,
    ) -> None:
        from action_record import ActionRecordExecutionUncertain
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory
        from agent_os_persistence import SqlActionRecordStore

        engine = self._engine()
        config = self._config(engine)

        runtime1 = ContentCommerceRuntimeFactory(config).build()
        result = runtime1.run("GMV 记录行动", dict(RUN_PARAMS))
        approval_id = result.approval_record.approval_id
        contract = runtime1.connector_registry.get_contract("action_record")
        real_connector = runtime1.connector_registry.get("action_record")
        runtime1.connector_registry.register(
            _LostAckAfterWriteConnector(real_connector),
            contract,
        )

        with self.assertRaises(ActionRecordExecutionUncertain):
            runtime1.approve_and_execute_pending_operation(
                approval_id=approval_id,
                reason="approved before lost ack",
                approved_by="ops@example.com",
            )

        records_after_failure = SqlActionRecordStore(engine).records()
        self.assertEqual(len(records_after_failure), 1)
        self.assertEqual(records_after_failure[0]["uncertain_execution_count"], 1)
        self.assertEqual(
            records_after_failure[0]["last_uncertain_execution"]["reason_code"],
            "lost_ack_after_write",
        )
        self.assertNotIn("parameters", records_after_failure[0]["last_uncertain_execution"])
        run_trace_after_failure = runtime1.trace_store.get(result.evidence_chain.trace_id)
        self.assertIsNotNone(run_trace_after_failure)
        uncertain_events = [
            event.payload["operation_event"]
            for event in run_trace_after_failure.events
            if event.step == "approved_operation_trace"
            and event.payload["operation_event"].get("step") == "connector_execution_uncertain"
        ]
        failure_operation_steps = [
            event.payload["operation_event"].get("step")
            for event in run_trace_after_failure.events
            if event.step == "approved_operation_trace"
        ]
        self.assertIn("state_snapshot", failure_operation_steps)
        self.assertEqual(len(uncertain_events), 1)
        self.assertEqual(uncertain_events[0]["execution_certainty"], "uncertain")
        self.assertEqual(uncertain_events[0]["ack_status"], "lost_after_write")

        runtime2 = ContentCommerceRuntimeFactory(config).build()
        _approval, operation_trace = runtime2.approve_and_execute_pending_operation(
            approval_id=approval_id,
            reason="retry after uncertain execution",
            approved_by="ops@example.com",
        )

        records_after_retry = runtime2.connector_registry.get("action_record").store.records()
        self.assertEqual(len(records_after_retry), 1)
        self.assertEqual(records_after_retry[0]["replay_count"], 1)
        final_event = operation_trace.events[-1]
        self.assertEqual(final_event["step"], "connector_executed")
        self.assertEqual(final_event["status"], "idempotent_replay")
        self.assertEqual(final_event["execution_certainty"], "uncertain_recovered")
        self.assertEqual(
            final_event["ack_status"],
            "lost_after_write_recovered_by_idempotency",
        )
        self.assertEqual(final_event["record_id"], records_after_retry[0]["record_id"])
        self.assertNotIn("parameters", final_event)

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
