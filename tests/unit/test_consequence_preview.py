"""P2-B (ADR-0016): evidence-bound SYMBOLIC ledger consequence preview.

Before an approver decides, the approval surface shows the action's OWN governed history,
derived live from the durable ``action_records`` ledger: "this action_type has N prior
executions, M of which resolved to the intended (clean) execution outcome". This is an HONEST
COUNT the human reads — never a prediction, learned model, or probability.

Each test is written to FAIL if the derivation is bypassed:
  1. counts are derived from the seeded ledger (a constant/ignored-ledger impl gives the wrong
     numbers);
  2. a novel action reports ``available=False`` with zero counts (distinguishing "no history"
     from "0/0 resolved");
  4. a failing ledger read degrades to ``available=False`` with the approval STILL creatable
     (no crash, no fabricated counts);
  5. the preview is attached to the EvidenceChain (auditable), not only loose on the proposal.

Tenant isolation (test 3) lives in ``test_action_history.py`` against the tenant-scoped SQL
repository — the honest place to prove one tenant's history never leaks into another's preview.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _pkg in ("contracts", "os_core", "persistence", "sdk"):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    ConnectorExecutionSemantics,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

# A question that routes the ActionProposalBuilder to the reversible ``action_record`` connector
# (action_type="execute", approval_required=True) — so the loop halts at awaiting_approval and the
# proposal carries a consequence preview over the action's OWN prior "execute" history.
_ACTION_INTENT = "记录行动：基于最近7天GMV创建一个跟进行动"
_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


class _FailingHistoryPort:
    """A history port whose ledger read raises — proves fail-safe degradation (advisory, not a gate)."""

    def outcomes_for(self, *, action_type: str, tenant_id: str = "default") -> tuple[str, ...]:
        raise RuntimeError("simulated ledger read failure")


def _history_adapter(store):
    """Real adapter over the action_record ledger (imported lazily; absent pre-implementation)."""
    from action_record.action_history import ActionRecordHistoryAdapter

    return ActionRecordHistoryAdapter(store)


def _seed_executions(store, *, action_type: str = "execute", clean: int, uncertain: int) -> None:
    """Seed the ledger with a KNOWN mix: ``clean`` records resolve to the intended outcome,
    ``uncertain`` records executed-but-did-not-cleanly-resolve (ACK lost after the write)."""
    for i in range(clean):
        store.add(operation_id=f"op-clean-{i}", action_type=action_type, parameters={"i": i})
    for i in range(uncertain):
        record = store.add(
            operation_id=f"op-uncertain-{i}", action_type=action_type, parameters={"i": i}
        )
        store.mark_execution_uncertain(
            record_id=record["record_id"],
            operation_id=f"op-uncertain-{i}",
            action_type=action_type,
            idempotency_key=None,
            parameters={"i": i},
            reason_code="ack_lost_after_write",
            error_type="TimeoutError",
        )


def _connector_registry(store: ActionRecordStore) -> ActionConnectorRegistry:
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
    registry.register(
        ActionRecordConnector(store=store),
        ActionConnectorContract(
            connector_name="action_record",
            display_name="Action Record",
            supported_action_types=("execute",),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description="Restore the action record store to the pre-execution snapshot",
            risk_ceiling="R3",
            owner="system",
            execution_semantics=ConnectorExecutionSemantics(
                durability_scope="connector_local_ledger",
                external_ack_status="not_applicable",
                ledger_status="recorded",
                supports_idempotency=True,
                supports_reconciliation=True,
            ),
        ),
    )
    return registry


def _runtime(store, *, action_history_port) -> TrustedLoopRuntime:
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
            "select order_date, sum(paid_amount) as gmv from sales.orders "
            "where order_date >= :start_date and order_date < :end_date group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
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
        connector_registry=_connector_registry(store),
        action_history_port=action_history_port,
    )


class LedgerConsequencePreview(unittest.TestCase):
    def test_preview_counts_derived_from_ledger(self):
        """5 prior executions, 3 clean → prior_executions=5, resolved_intended=3, resolved_other=2.

        FAILS if the code returns a constant or ignores the ledger: the exact 5/3/2 split can only
        come from reading the seeded records.
        """
        store = ActionRecordStore()
        _seed_executions(store, clean=3, uncertain=2)
        runtime = _runtime(store, action_history_port=_history_adapter(store))

        result = runtime.run(_ACTION_INTENT, _PARAMS)

        preview = result.action_proposal.consequence_preview
        self.assertIsNotNone(preview)
        self.assertTrue(preview.available)
        self.assertEqual(preview.action_type, "execute")
        self.assertEqual(preview.prior_executions, 5)
        self.assertEqual(preview.resolved_intended, 3)
        self.assertEqual(preview.resolved_other, 2)
        # oldest -> newest, exactly the seeded mix (clean then uncertain).
        self.assertEqual(
            preview.last_outcomes,
            ("executed", "executed", "executed", "execution_uncertain", "execution_uncertain"),
        )
        # SYMBOLIC preview only: the action still halts for a human decision (R4/R5 proposal-only spirit).
        self.assertEqual(result.action_result["status"], "awaiting_approval")

    def test_novel_action_reports_unavailable(self):
        """A novel action (no prior records) → available=False, all counts 0 — NOT a fabricated 0/0.

        FAILS if a novel action is dressed as real data (available=True with zero counts).
        """
        store = ActionRecordStore()  # empty ledger: no prior "execute" history
        runtime = _runtime(store, action_history_port=_history_adapter(store))

        result = runtime.run(_ACTION_INTENT, _PARAMS)

        preview = result.action_proposal.consequence_preview
        self.assertIsNotNone(preview)
        self.assertFalse(preview.available)
        self.assertEqual(preview.prior_executions, 0)
        self.assertEqual(preview.resolved_intended, 0)
        self.assertEqual(preview.resolved_other, 0)
        self.assertEqual(preview.last_outcomes, ())

    def test_ledger_unavailable_degrades_safely(self):
        """A failing ledger read → available=False, no crash, and the approval is STILL creatable.

        FAILS if the failure crashes the loop, or fabricates counts, or blocks the approval.
        """
        store = ActionRecordStore()
        runtime = _runtime(store, action_history_port=_FailingHistoryPort())

        result = runtime.run(_ACTION_INTENT, _PARAMS)  # must not raise

        preview = result.action_proposal.consequence_preview
        self.assertIsNotNone(preview)
        self.assertFalse(preview.available)
        self.assertEqual(preview.prior_executions, 0)
        self.assertEqual(preview.resolved_intended, 0)
        self.assertEqual(preview.resolved_other, 0)
        # The preview is advisory, not a gate: the approval still halts pending a human decision.
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertIsNotNone(result.approval_record)

    def test_preview_is_evidence_attached(self):
        """The preview is attached to the EvidenceChain (auditable), equal to the proposal's.

        FAILS if the preview lives only on the proposal as loose JSON and never enters the evidence.
        """
        store = ActionRecordStore()
        _seed_executions(store, clean=2, uncertain=1)
        runtime = _runtime(store, action_history_port=_history_adapter(store))

        result = runtime.run(_ACTION_INTENT, _PARAMS)

        evidence_preview = result.evidence_chain.consequence_preview
        self.assertIsNotNone(evidence_preview)
        # Same evidence-bound object the proposal surfaces — one derivation, attached as evidence.
        self.assertEqual(evidence_preview, result.action_proposal.consequence_preview)
        self.assertTrue(evidence_preview.available)
        self.assertEqual(evidence_preview.prior_executions, 3)
        self.assertEqual(evidence_preview.resolved_intended, 2)
        self.assertEqual(evidence_preview.resolved_other, 1)


if __name__ == "__main__":
    unittest.main()
