from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    MetricContract,
    OperationContract,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
    TelemetryDimension,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime  # noqa: E402
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


def _build_default_connector_registry() -> ActionConnectorRegistry:
    """Build a connector registry with ManualReviewConnector.

    Caller-side construction: OS Core never imports action connectors.
    """
    registry = ActionConnectorRegistry()
    connector = ManualReviewConnector()
    contract = ActionConnectorContract(
        connector_name="manual_review",
        display_name="Manual Review",
        supported_action_types=("propose", "execute"),
        supports_snapshot=False,
        supports_rollback=False,
        compensating_action_description=None,
        risk_ceiling="R5",
        owner="system",
    )
    registry.register(connector, contract)
    return registry


class TrustedLoopRuntimeTest(unittest.TestCase):
    def test_runs_minimum_trusted_loop(self) -> None:
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
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )
        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            sql_template=template,
            query_executor=StaticQueryExecutor(
                [
                    {"order_date": "2026-05-31", "gmv": 128800.0},
                ]
            ),
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
            connector_registry=_build_default_connector_registry(),
        )

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertEqual(result.intent.metric_name, "gmv")
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertIsNotNone(result.provider_contract)
        self.assertEqual(result.provider_contract.provider_id, "provider-sales")
        self.assertIsNotNone(result.data_requirement)
        self.assertEqual(result.data_requirement.metric_names, ("gmv",))
        self.assertIsNotNone(result.lineage_snapshot)
        self.assertEqual(result.lineage_snapshot.provider_id, "provider-sales")
        self.assertIsNotNone(result.data_product_candidate)
        self.assertEqual(result.action_proposal.risk_level, RiskLevel.R2)
        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(
            [event.step for event in result.trace_events],
            [
                "intent",
                "semantic_resolution",
                "query_plan",
                "sql_safety",
                "query_result",
                "data_product_candidate",
                "evidence_chain",
                "action_proposal",
                "operation_contract",
                "connector_execute",
            ],
        )
        telemetry_dimensions = {event.dimension for event in result.telemetry_events}
        self.assertIn(TelemetryDimension.BUSINESS, telemetry_dimensions)
        self.assertIn(TelemetryDimension.QUALITY, telemetry_dimensions)
        self.assertIn(TelemetryDimension.COST, telemetry_dimensions)
        self.assertIn(TelemetryDimension.SYSTEM, telemetry_dimensions)
        self.assertTrue(
            any(event.name == "evidence_chain.complete" for event in result.telemetry_events)
        )


class TrustedLoopGovernanceTest(unittest.TestCase):
    """Integration tests for the governance/connector/approval/trace pipeline."""

    def _build_runtime(
        self,
        rows: list[dict] | None = None,
        connector_registry: ActionConnectorRegistry | None = None,
    ) -> TrustedLoopRuntime:
        """Helper to build a runtime with sensible defaults for governance tests."""
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
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )
        kwargs: dict = {
            "metric_contract": metric,
            "sql_template": template,
            "query_executor": StaticQueryExecutor(
                rows if rows is not None else [{"order_date": "2026-05-31", "gmv": 128800.0}]
            ),
            "semantic_registry": SemanticRegistry(metric_contracts=(metric,)),
            "provider_registry": ProviderRegistry(
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
        }
        if connector_registry is not None:
            kwargs["connector_registry"] = connector_registry
        else:
            kwargs["connector_registry"] = _build_default_connector_registry()
        return TrustedLoopRuntime(**kwargs)

    def test_trusted_loop_with_governance(self) -> None:
        """Full pipeline: intent → governance → state machine → connector → trace."""
        runtime = self._build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # operation_contract should be populated
        self.assertIsNotNone(result.operation_contract)
        self.assertIsInstance(result.operation_contract, OperationContract)
        self.assertEqual(result.operation_contract.connector_name, "manual_review")

        # action_result should contain status
        self.assertIsNotNone(result.action_result)
        self.assertIsInstance(result.action_result, dict)
        self.assertIn("status", result.action_result)

        # trace_events should contain operation_contract and connector_execute steps
        trace_steps = [event.step for event in result.trace_events]
        self.assertIn("operation_contract", trace_steps)
        self.assertIn("connector_execute", trace_steps)

        # Verify the operation_contract step has the right info
        op_trace_event = next(e for e in result.trace_events if e.step == "operation_contract")
        self.assertEqual(op_trace_event.payload["connector_name"], "manual_review")

        # Verify the connector_execute step has the right info
        exec_trace_event = next(e for e in result.trace_events if e.step == "connector_execute")
        self.assertEqual(exec_trace_event.payload["connector_name"], "manual_review")
        self.assertIn("status", exec_trace_event.payload)

    def test_governance_with_high_risk_triggers_approval(self) -> None:
        """High risk (row_count=0) should trigger approval_required and create pending record."""
        runtime = self._build_runtime(rows=[])
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # High risk => approval_required
        self.assertTrue(result.action_proposal.approval_required)
        self.assertIsNotNone(result.approval_record)
        self.assertEqual(result.approval_record.status, "pending")

    def test_nonexistent_connector_raises_keyerror(self) -> None:
        """Requesting a nonexistent connector should raise KeyError."""
        from agent_os_contracts import ActionProposal, EvidenceChain

        # Build a custom ActionProposalBuilder that produces proposals
        # with connector_name="nonexistent"
        class _NonexistentProposalBuilder:
            def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
                if evidence.query_result.row_count == 0:
                    risk_level = RiskLevel.R3
                    approval_required = True
                    approver_role = "Business Owner"
                    action_type = "execute"
                else:
                    risk_level = RiskLevel.R2
                    approval_required = False
                    approver_role = None
                    action_type = "propose"
                return ActionProposal(
                    proposal_id=proposal_id,
                    evidence_chain_id=evidence.evidence_chain_id,
                    target_object=evidence.metric_contract.metric_name,
                    recommended_action="test",
                    reason=evidence.conclusion,
                    risk_level=risk_level,
                    expected_impact="test",
                    approval_required=approval_required,
                    approver_role=approver_role,
                    connector_name="nonexistent",
                    action_type=action_type,
                    action_parameters={},
                )

        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        template = SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )

        # Use an empty registry — no connectors registered at all
        empty_registry = ActionConnectorRegistry()

        runtime = TrustedLoopRuntime(
            metric_contract=metric,
            sql_template=template,
            query_executor=StaticQueryExecutor([{"gmv": 100}]),
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
            connector_registry=empty_registry,
        )
        # Override the action_builder to produce proposals with nonexistent connector
        runtime.action_builder = _NonexistentProposalBuilder()  # type: ignore[assignment]

        with self.assertRaises(KeyError):
            runtime.run(
                "最近7天GMV是多少？",
                {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
            )

    def test_connector_registry_required(self) -> None:
        """The runtime must raise ValueError if connector_registry is not provided.

        OS Core must not import action connectors, so the caller is responsible
        for constructing and injecting the registry.
        """
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        template = SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )
        with self.assertRaises(ValueError) as ctx:
            TrustedLoopRuntime(
                metric_contract=metric,
                sql_template=template,
                query_executor=StaticQueryExecutor([{"gmv": 100}]),
                connector_registry=None,
            )
        self.assertIn("connector_registry is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
