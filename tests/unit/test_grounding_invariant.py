"""P5.1b-ii (AR-20260614): the non-bypassable grounding invariant.

A formal answer/action may only be produced when the query passed SQL Safety AND
the EvidenceChain is complete. The Trusted Loop is the sole sanctioned producer of
grounded answers; bypassing the data/evidence path raises GroundingInvariantViolation
(a hard breach, not a business block). The bypass test fails if the invariant is removed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "action_connectors",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    BusinessIntent,
    EvidenceChain,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    QueryResult,
    SQLSafetyResult,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    GroundingInvariantViolation,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
SAFE_SQL = (
    "select order_date, sum(paid_amount) as value from sales.orders "
    "where order_date >= :start_date and order_date < :end_date "
    "group by order_date limit :limit"
)


def _metric(name: str = "gmv") -> MetricContract:
    return MetricContract(
        metric_name=name,
        display_name=name.upper(),
        definition=f"{name} metric.",
        owner="ops",
        unit="CNY",
        allowed_schemas=("sales",),
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


def _runtime() -> TrustedLoopRuntime:
    return TrustedLoopRuntime(
        metric_contract=_metric(),
        sql_template=SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=SAFE_SQL,
            required_parameters=("start_date", "end_date", "limit"),
        ),
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "value": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(_metric(),)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales",
                    owner="data_platform",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
    )


def _evidence(*, allowed: bool = True, trace_id: str = "trace-1") -> EvidenceChain:
    return EvidenceChain(
        evidence_chain_id="evidence-1",
        intent=BusinessIntent(intent_id="i-1", question="GMV?", metric_name="gmv"),
        metric_contract=_metric(),
        query_plan=QueryPlan(metric_name="gmv", sql="select 1", parameters={}),
        sql_safety=SQLSafetyResult(allowed=allowed, reasons=(), checked_schemas=("sales",)),
        query_result=QueryResult(rows=(), row_count=0),
        conclusion="c",
        confidence=0.5,
        limitations=(),
        trace_id=trace_id,
    )


class _UngroundedEvidenceBuilder:
    """Simulates a refactor/surface that bypasses the data/evidence path: returns an
    UNGROUNDED EvidenceChain (sql_safety.allowed=False) without the real builder's check."""

    def build(
        self,
        *,
        evidence_chain_id,
        intent,
        metric_contract,
        query_plan,
        sql_safety,
        query_result,
        trace_id,
        provider_contract=None,
    ) -> EvidenceChain:
        return EvidenceChain(
            evidence_chain_id=evidence_chain_id,
            intent=intent,
            metric_contract=metric_contract,
            query_plan=query_plan,
            sql_safety=SQLSafetyResult(allowed=False, reasons=("bypassed",), checked_schemas=()),
            query_result=query_result,
            conclusion="c",
            confidence=0.5,
            limitations=(),
            trace_id=trace_id,
        )


class GroundingGuardUnitTest(unittest.TestCase):
    def test_passes_on_grounded(self) -> None:
        ev = _evidence(allowed=True, trace_id="trace-1")
        TrustedLoopRuntime._assert_grounded(ev.sql_safety, ev)  # must not raise

    def test_raises_on_disallowed_safety(self) -> None:
        ev = _evidence(allowed=False)
        with self.assertRaises(GroundingInvariantViolation):
            TrustedLoopRuntime._assert_grounded(ev.sql_safety, ev)

    def test_raises_on_incomplete_evidence(self) -> None:
        # safety allowed, but a missing required field (empty trace_id) => incomplete
        ev = _evidence(allowed=True, trace_id="")
        with self.assertRaises(GroundingInvariantViolation):
            TrustedLoopRuntime._assert_grounded(ev.sql_safety, ev)


class GroundingInvariantLoopTest(unittest.TestCase):
    def test_grounded_happy_path(self) -> None:
        result = _runtime().run("GMV last 7 days", dict(PARAMS))
        self.assertTrue(result.evidence_chain.is_complete())
        self.assertTrue(result.evidence_chain.sql_safety.allowed)
        # the answer/action is bound to the grounded evidence chain
        self.assertEqual(
            result.action_proposal.evidence_chain_id, result.evidence_chain.evidence_chain_id
        )

    def test_loop_refuses_ungrounded_evidence(self) -> None:
        # Bypass the data/evidence path: even if the evidence builder is swapped for one
        # that skips grounding, the loop's mediation invariant must refuse to answer.
        runtime = _runtime()
        runtime.evidence_builder = _UngroundedEvidenceBuilder()
        with self.assertRaises(GroundingInvariantViolation):
            runtime.run("GMV last 7 days", dict(PARAMS))


if __name__ == "__main__":
    unittest.main()
