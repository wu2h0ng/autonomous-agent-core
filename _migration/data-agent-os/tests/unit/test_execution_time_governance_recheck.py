"""ADR-0005: execution-time governance recheck (corrigibility C7 + seam) before any connector side-effect.

The seam and the operator pause are enforced at PROPOSAL time in run(); an approval-required action executes
LATER via execute_approved_operation(). These tests prove that a state change BETWEEN approval and execution —
the operator pausing, or the seam flipping to DENY — blocks the real connector write, while an already-approved
action is NOT re-gated by ESCALATE/VERIFY_MORE or by the seam being unavailable (never block on the organ).

Every "blocked" assertion checks store.records() == () — i.e. the reversible connector never executed.
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
    SQLTemplate,
)
from agent_os_contracts.governance_decision_seam import (  # noqa: E402
    ALLOW,
    DENY,
    ESCALATE,
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
)
from agent_os_core import (  # noqa: E402
    CorrigibilityShell,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.governance_decision_seam import GovernanceDecisionClient  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_ACTION_INTENT = "记录行动：基于最近7天GMV创建一个跟进行动"
_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}


class _MutableClient(GovernanceDecisionClient):
    """A seam stub whose verdict can be flipped between proposal and execution (or made to raise)."""

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.raises = False
        self.calls = 0

    def decide(self, req: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        self.calls += 1
        if self.raises:
            raise RuntimeError("seam service unavailable at execution time")
        chosen = "act" if self.verdict == ALLOW else None
        return GovernanceDecisionResponse(
            req.task_id, self.verdict, chosen, 0.9, f"fixed:{self.verdict}", "ref-int"
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
    """run the action-record intent to awaiting_approval, then approve; return the run result + approval_id."""
    result = runtime.run(_ACTION_INTENT, _PARAMS)
    assert result.action_proposal.approval_required is True
    assert result.action_result["status"] == "awaiting_approval"
    approval_id = result.approval_record.approval_id
    runtime.approval_runtime.approve(approval_id, reason="approved by operator")
    return result, approval_id


class ExecutionTimeCorrigibilityRecheck(unittest.TestCase):
    def test_pause_after_approval_blocks_before_connector(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view())
        result, approval_id = _run_to_approved(runtime)
        shell.op_pause()  # operator pauses AFTER approval, BEFORE execution
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.execute_approved_operation(
                approval_id=approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )
        self.assertEqual(ctx.exception.block.code, BlockCode.PAUSED)
        self.assertEqual(store.records(), ())  # the reversible connector NEVER executed

    def test_not_paused_executes(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view())
        result, approval_id = _run_to_approved(runtime)
        trace = runtime.execute_approved_operation(
            approval_id=approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(trace.state.value, "executed")


class ExecutionTimeSeamRecheck(unittest.TestCase):
    def _run_execute(self, store, runtime):
        result, approval_id = _run_to_approved(runtime)
        return runtime.execute_approved_operation(
            approval_id=approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )

    def test_seam_deny_at_execution_blocks_before_connector(self):
        store = ActionRecordStore()
        client = _MutableClient(ALLOW)  # ALLOW at proposal so it reaches approval
        runtime = _runtime(store, client=client)
        result, approval_id = _run_to_approved(runtime)
        client.verdict = DENY  # disposer flips to DENY after approval
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.execute_approved_operation(
                approval_id=approval_id,
                operation=result.operation_contract,
                action_parameters=result.action_proposal.action_parameters,
                evidence_chain=result.evidence_chain,
                proposal_id=result.action_proposal.proposal_id,
            )
        self.assertEqual(ctx.exception.block.code, BlockCode.GOVERNANCE_DENIED)
        self.assertEqual(store.records(), ())

    def test_seam_allow_at_execution_executes(self):
        store = ActionRecordStore()
        trace = self._run_execute(store, _runtime(store, client=_MutableClient(ALLOW)))
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(trace.state.value, "executed")

    def test_seam_escalate_at_execution_still_executes(self):
        # post-approval, ESCALATE/VERIFY_MORE are redundant (a human already approved) -> execute, not re-gate
        store = ActionRecordStore()
        client = _MutableClient(ALLOW)
        runtime = _runtime(store, client=client)
        result, approval_id = _run_to_approved(runtime)
        client.verdict = ESCALATE
        trace = runtime.execute_approved_operation(
            approval_id=approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(trace.state.value, "executed")

    def test_seam_unavailable_at_execution_executes(self):
        # never block on the organ (ADR-0047): the human approval stands if the seam is down at execution
        store = ActionRecordStore()
        client = _MutableClient(ALLOW)
        runtime = _runtime(store, client=client)
        result, approval_id = _run_to_approved(runtime)
        client.raises = True
        trace = runtime.execute_approved_operation(
            approval_id=approval_id,
            operation=result.operation_contract,
            action_parameters=result.action_proposal.action_parameters,
            evidence_chain=result.evidence_chain,
            proposal_id=result.action_proposal.proposal_id,
        )
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(trace.state.value, "executed")

    def test_no_client_not_paused_unchanged(self):
        store = ActionRecordStore()
        trace = self._run_execute(store, _runtime(store))
        self.assertEqual(len(store.records()), 1)
        self.assertEqual(trace.state.value, "executed")


if __name__ == "__main__":
    unittest.main()
