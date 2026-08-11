"""S2 (RR-0048 Option 2): a real reversible R0-R3 action, governed by the LOCAL disposer.

Wires the native governed brain — ``LocalGovernanceDecisionClient`` over the REAL
``MetricCohortABVerifier`` (standardized mean difference over a cohort A/B query) — into a
``TrustedLoopRuntime`` with the reversible ``action_record`` connector, and proves the founder's
risk-acceptance conditions for the first real action (可逆 reversible, R0-R3, 控制试点 controlled-pilot):

  1. verified cohort effect -> disposer ALLOW -> OS approval -> ADR-0005 execution-time recheck
     (disposer re-consulted, still ALLOW) -> connector.execute -> a REAL ledger write.
  2. the executed action is REVERSIBLE: ``runtime.rollback(snapshot)`` restores the ledger.
  3. corrigibility (C7) is absolute over a real action: an operator pause AFTER approval halts the
     execution before any connector side-effect (0 records) — the runtime cannot un-pause itself.
  4. decision strength: with NO verified cohort effect the disposer ESCALATEs (it never auto-clears
     an action whose causal effect is unverified); with a verified effect the SAME action clears to
     ALLOW. This is the §22 structure/decision strength wired end-to-end — NOT a value-prediction claim.

Every "blocked/halted" assertion checks ``store.records() == ()`` — the reversible connector never ran.
The disposer is the NATIVE ``LocalGovernanceDecisionClient`` (no subprocess); the live cross-process
seam service is S3. No cross-repo import (#19): the seam is a shared contract implemented on both sides.
"""

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
    BlockCode,
    ConnectorExecutionSemantics,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryResult,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    CorrigibilityShell,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.governance_decision_seam import (  # noqa: E402
    LocalGovernanceDecisionClient,
    MetricCohortABVerifier,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_ACTION_INTENT = "记录行动：基于最近7天GMV创建一个跟进行动"
_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


def _cohort(effect: bool) -> QueryResult:
    """A cohort A/B QueryResult the verifier scores. effect=True -> clear A>>B separation
    (verified-effective); effect=False -> empty (thin -> fail-closed -> not effective)."""
    if not effect:
        return QueryResult(rows=(), row_count=0)
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (120.0, 132.0, 128.0, 141.0)]
        + [{"cohort": "B", "metric": v} for v in (88.0, 91.0, 84.0, 90.0)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _local_disposer(effect: bool, *, shell_view=None) -> LocalGovernanceDecisionClient:
    """The NATIVE governed brain: a deterministic disposer over the REAL cohort A/B verifier.
    approval_required_at_or_above='R4' => R0-R3 are low-stakes (auto-ALLOW iff verified-effective)."""
    return LocalGovernanceDecisionClient(
        MetricCohortABVerifier(lambda action: _cohort(effect)),
        approval_required_at_or_above="R4",
        shell_view=shell_view,
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


def _runtime(store, *, shell_view=None, client=None) -> TrustedLoopRuntime:
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
        shell_view=shell_view,
        governance_decision_client=client,
    )


def _run_to_approved(runtime):
    result = runtime.run(_ACTION_INTENT, _PARAMS)
    assert result.action_proposal.approval_required is True
    assert result.action_result["status"] == "awaiting_approval"
    approval_id = result.approval_record.approval_id
    runtime.approval_runtime.approve(approval_id, reason="approved by operator")
    return result, approval_id


def _execute(runtime, result, approval_id):
    return runtime.execute_approved_operation(
        approval_id=approval_id,
        operation=result.operation_contract,
        action_parameters=result.action_proposal.action_parameters,
        evidence_chain=result.evidence_chain,
        proposal_id=result.action_proposal.proposal_id,
    )


def _snapshot_id_from_trace_events(events) -> str:
    for event in events:
        if event.get("step") == "state_snapshot":
            snapshot_id = event.get("snapshot_id")
            if isinstance(snapshot_id, str):
                return snapshot_id
    raise AssertionError("operation trace did not include a state_snapshot event")


def _verdicts(shell, event_name):
    return [
        entry.payload.get("verdict")
        for entry in shell.audit.entries()
        if entry.payload.get("event") == event_name
    ]


class GovernedRealReversibleAction(unittest.TestCase):
    def test_verified_effect_action_executes_end_to_end(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view(), client=_local_disposer(effect=True))
        result, approval_id = _run_to_approved(runtime)

        trace = _execute(runtime, result, approval_id)

        self.assertEqual(trace.state.value, "executed")
        self.assertEqual(len(store.records()), 1)  # a REAL reversible ledger write happened
        # the LOCAL disposer governed the ACTUAL execution (ADR-0005 execution-time recheck), not just the proposal
        self.assertEqual(_verdicts(shell, "execution_governed_decision"), ["ALLOW"])
        self.assertIn("ALLOW", _verdicts(shell, "governed_decision"))

    def test_executed_action_is_reversible_via_rollback(self):
        store = ActionRecordStore()
        runtime = _runtime(store, client=_local_disposer(effect=True))
        result, approval_id = _run_to_approved(runtime)

        trace = _execute(runtime, result, approval_id)
        self.assertEqual(len(store.records()), 1)

        rollback_result = runtime.rollback(_snapshot_id_from_trace_events(trace.events))
        self.assertEqual(rollback_result["status"], "rolled_back")
        self.assertEqual(store.records(), ())  # fully reversible: the ledger is restored

    def test_corrigibility_pause_halts_the_real_action(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view(), client=_local_disposer(effect=True))
        result, approval_id = _run_to_approved(runtime)

        shell.op_pause()  # operator pauses AFTER approval, BEFORE execution

        with self.assertRaises(TrustedLoopBlocked) as ctx:
            _execute(runtime, result, approval_id)
        self.assertEqual(ctx.exception.block.code, BlockCode.PAUSED)
        self.assertEqual(store.records(), ())  # the real reversible connector NEVER ran

    def test_unverified_effect_escalates_and_never_auto_clears(self):
        # NO verified cohort effect -> the disposer ESCALATEs -> the action is not auto-cleared; nothing executes.
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view(), client=_local_disposer(effect=False))

        result = runtime.run(_ACTION_INTENT, _PARAMS)

        self.assertTrue(result.action_proposal.approval_required)
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertEqual(store.records(), ())  # nothing auto-executed on an unverified effect
        self.assertIn("ESCALATE", _verdicts(shell, "governed_decision"))

    def test_decision_strength_discriminates_verified_from_unverified(self):
        # the SAME action + SAME runtime wiring: a verified cohort effect clears to ALLOW where an
        # unverified one only ESCALATEs. That discrimination IS the governed brain's decision strength.
        shell_effect = CorrigibilityShell()
        _runtime(
            ActionRecordStore(), shell_view=shell_effect.view(), client=_local_disposer(effect=True)
        ).run(_ACTION_INTENT, _PARAMS)

        shell_null = CorrigibilityShell()
        _runtime(
            ActionRecordStore(), shell_view=shell_null.view(), client=_local_disposer(effect=False)
        ).run(_ACTION_INTENT, _PARAMS)

        self.assertIn("ALLOW", _verdicts(shell_effect, "governed_decision"))
        self.assertIn("ESCALATE", _verdicts(shell_null, "governed_decision"))
        self.assertNotIn("ALLOW", _verdicts(shell_null, "governed_decision"))


if __name__ == "__main__":
    unittest.main()
