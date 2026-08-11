from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "action_connectors",
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
    TrustedLoopOutcome,
    TrustedLoopResult,
)
from agent_os_core import (  # noqa: E402
    InMemoryTraceStore,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.agent_runtime import (  # noqa: E402
    AgentRunContext,
    AgentTraceWriter,
    TrustedLoopAgentRuntimeAdapter,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.corrigibility import CorrigibilityShell  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
SAFE_SQL = (
    "select order_date, sum(paid_amount) as value from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date limit :limit"
)


class FakeTrustedLoop:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def evaluate(
        self, question: str, parameters: dict[str, object], *, tenant_id: str = "default"
    ) -> dict[str, object]:
        self.calls.append((question, parameters, tenant_id))
        return {
            "status": "ok",
            "question": question,
            "parameters": parameters,
            "tenant_id": tenant_id,
        }


def _context() -> AgentRunContext:
    return AgentRunContext(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="operator-1",
        principal_role="operator",
        run_id="run-1",
        trace_id="trace-1",
        policy_scope=frozenset({"trusted_loop:evaluate"}),
    )


def _connector_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        ManualReviewConnector(),
        ActionConnectorContract(
            connector_name="manual_review",
            display_name="Manual Review",
            supported_action_types=("propose", "execute"),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="system",
        ),
    )
    return registry


def _real_trusted_loop(*, trace_store: InMemoryTraceStore) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=SAFE_SQL,
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 128800.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales warehouse",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
        trace_store=trace_store,
    )


class TrustedLoopAgentRuntimeAdapterTest(unittest.TestCase):
    def test_safe_trusted_loop_call_goes_through_runtime_envelope(self) -> None:
        loop = FakeTrustedLoop()
        trace_writer = AgentTraceWriter()
        adapter = TrustedLoopAgentRuntimeAdapter(loop, trace_writer=trace_writer)

        result = adapter.evaluate(
            context=_context(),
            question="GMV",
            parameters={"start_date": "2026-05-01", "end_date": "2026-06-01", "limit": 10},
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(loop.calls), 1)
        self.assertEqual(loop.calls[0][2], "tenant-1")
        self.assertIn(
            "agent_runtime.policy_allowed",
            [event["step"] for event in trace_writer.events],
        )

    def test_paused_shell_blocks_before_trusted_loop_execution(self) -> None:
        shell = CorrigibilityShell()
        shell.op_pause()
        loop = FakeTrustedLoop()
        adapter = TrustedLoopAgentRuntimeAdapter(loop, shell_view=shell.view())

        result = adapter.evaluate(
            context=_context(),
            question="GMV",
            parameters={"start_date": "2026-05-01", "end_date": "2026-06-01", "limit": 10},
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_PAUSED")
        self.assertEqual(loop.calls, [])

    def test_real_trusted_loop_evaluate_preserves_grounding_through_adapter(self) -> None:
        trace_store = InMemoryTraceStore()
        trace_writer = AgentTraceWriter()
        adapter = TrustedLoopAgentRuntimeAdapter(
            _real_trusted_loop(trace_store=trace_store),
            trace_writer=trace_writer,
        )

        result = adapter.evaluate(
            context=_context(),
            question="最近7天GMV是多少？",
            parameters=dict(PARAMS),
        )

        self.assertEqual(result.status, "ok")
        self.assertIsInstance(result.output, TrustedLoopOutcome)
        outcome = result.output
        self.assertTrue(outcome.ok)
        self.assertIsInstance(outcome.result, TrustedLoopResult)
        trusted_loop_result = outcome.result
        self.assertEqual(trusted_loop_result.intent.metric_name, "gmv")
        self.assertTrue(trusted_loop_result.evidence_chain.sql_safety.allowed)
        self.assertTrue(trusted_loop_result.evidence_chain.is_complete())
        self.assertEqual(trusted_loop_result.evidence_chain.query_result.row_count, 1)
        self.assertEqual(trusted_loop_result.provider_contract.provider_id, "provider-sales")
        self.assertIsNotNone(trusted_loop_result.data_product_candidate)
        self.assertEqual(trusted_loop_result.action_result["status"], "pending_approval")

        trusted_loop_steps = [event.step for event in trusted_loop_result.trace_events]
        self.assertIn("sql_safety", trusted_loop_steps)
        self.assertIn("evidence_chain", trusted_loop_steps)
        self.assertIn("connector_execute", trusted_loop_steps)
        persisted_trace = trace_store.get(
            trusted_loop_result.evidence_chain.trace_id,
            tenant_id="tenant-1",
        )
        self.assertIsNotNone(persisted_trace)
        self.assertEqual(persisted_trace.status, "ok")

        runtime_steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.policy_allowed", runtime_steps)
        self.assertIn("agent_runtime.tool_succeeded", runtime_steps)


if __name__ == "__main__":
    unittest.main()
