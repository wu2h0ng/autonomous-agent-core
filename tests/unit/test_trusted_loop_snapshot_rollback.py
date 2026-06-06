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
    ActionProposal,
    EvidenceChain,
    MetricContract,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    InMemorySnapshotStore,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402

from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402


class _ActionRecordProposalBuilder:
    """Routes every proposal to the action_record connector at R2 risk.

    R2 (non-empty result) => non-approval AND snapshot-eligible (snapshot_required
    comes from the connector contract, risk is R2 which is >= R2).
    """

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action="write_action_record",
            reason=evidence.conclusion,
            risk_level=RiskLevel.R2,
            expected_impact="record persisted",
            approval_required=False,
            approver_role=None,
            connector_name="action_record",
            action_type="execute",
            action_parameters={"amount": 100},
        )


def _build_action_record_registry(store: ActionRecordStore) -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    connector = ActionRecordConnector(store=store)
    contract = ActionConnectorContract(
        connector_name="action_record",
        display_name="Action Record",
        supported_action_types=("execute",),
        supports_snapshot=True,
        supports_rollback=True,
        compensating_action_description="Restore the action record store to the snapshot state",
        risk_ceiling="R3",
        owner="system",
    )
    registry.register(connector, contract)
    return registry


def _build_runtime(store: ActionRecordStore) -> TrustedLoopRuntime:
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
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "gmv": 128800.0}]),
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
        connector_registry=_build_action_record_registry(store),
    )
    runtime.action_builder = _ActionRecordProposalBuilder()  # type: ignore[assignment]
    return runtime


class TrustedLoopSnapshotTest(unittest.TestCase):
    def test_default_snapshot_store_is_in_memory(self) -> None:
        store = ActionRecordStore()
        runtime = _build_runtime(store)
        self.assertIsInstance(runtime.snapshot_store, InMemorySnapshotStore)

    def test_governed_path_persists_snapshot_and_executes(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(record_store)

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # The connector executed a real write.
        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(result.action_result.get("status"), "executed")
        self.assertEqual(len(record_store.records()), 1)

        # A snapshot was taken AND persisted in the snapshot_store.
        self.assertIsNotNone(result.state_snapshot)
        persisted = runtime.snapshot_store.get(result.state_snapshot.snapshot_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.connector_name, "action_record")

    def test_runtime_rollback_restores_store(self) -> None:
        record_store = ActionRecordStore()
        runtime = _build_runtime(record_store)

        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        snapshot_id = result.state_snapshot.snapshot_id
        self.assertEqual(len(record_store.records()), 1)

        rollback_result = runtime.rollback(snapshot_id)
        self.assertEqual(rollback_result["status"], "rolled_back")
        # Snapshot was taken BEFORE the execute write, so rollback empties the store.
        self.assertEqual(len(record_store.records()), 0)

    def test_rollback_unknown_snapshot_raises_keyerror(self) -> None:
        runtime = _build_runtime(ActionRecordStore())
        with self.assertRaises(KeyError):
            runtime.rollback("snapshot-does-not-exist")


if __name__ == "__main__":
    unittest.main()
