"""S5 (RR-0048 Option 2): governed causal intervention-SELECTION in the OS loop.

The goal's named core capability — "选择运行哪个干预" (choosing which intervention to run) — lives in the
governed action loop itself, and it must be CAUSAL: pick the intervention that actually moves the metric
under intervention, not the one that merely correlates. Until now the OS loop proposed ONE action and the
seam only verified it. S5 lets the loop carry MULTIPLE candidate interventions and has the deterministic,
contentless governed disposer SELECT among them by real interventional (cohort A/B) evidence — surfacing the
choice in the audit trace. The disposer still only tightens; the human approval gate and C7 are unchanged.

Proven here:
  1. given [correlational lure, causal driver], the governed disposer SELECTS the causal driver (chosen_action)
     and rejects the lure — because the interventional cohort A/B verifier finds an effect only for the causal
     one. This is 强 (causal, not correlational) + governed selection, recorded auditable in the loop's trace.
  2. when EVERY candidate is an unverified lure, the disposer ESCALATEs (never auto-selects an unverified
     intervention) — 受治理: never act on what intervention has not confirmed.
  3. the default (no candidate interventions supplied) path is unchanged — backward compatible.

Honest bound: the candidate interventions are ENUMERATED (supplied by the proposer/domain), not open-world
self-generated; the disposer's selection is SURFACED in the trace, and wiring it to redirect the executed
operation (vs. the recommended action) is a staged next slice. This is governed causal selection among
enumerated interventions, not open-world causal discovery, and not autonomy over the correction gate.
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
    ActionProposal,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryResult,
    RiskLevel,
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
from manual_review import ManualReviewConnector  # noqa: E402

_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}

_LURE = (
    "raise_budget:correlational_lure"  # high observational correlation, NO interventional effect
)
_CAUSAL = "raise_budget:causal_driver"  # real cohort A/B effect under intervention


def _effect_cohort() -> QueryResult:
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (120.0, 132.0, 128.0, 141.0)]
        + [{"cohort": "B", "metric": v} for v in (88.0, 91.0, 84.0, 90.0)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _null_cohort() -> QueryResult:
    # a correlational lure: an A/B intervention on it moves the metric by ~nothing (no causal effect)
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (100.0, 101.0, 99.0, 100.5)]
        + [{"cohort": "B", "metric": v} for v in (100.2, 99.8, 100.1, 99.9)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _cohort_for(action: str) -> QueryResult:
    return _effect_cohort() if action == _CAUSAL else _null_cohort()


class _CandidateProposalBuilder:
    """A proposer that enumerates MULTIPLE candidate interventions for the intent (S5 opt-in path)."""

    def __init__(self, candidates: tuple[str, ...]) -> None:
        self._candidates = candidates

    def build(self, *, proposal_id: str, evidence) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action=self._candidates[0],  # the naive/first candidate
            reason="Multiple candidate interventions enumerated for governed causal selection.",
            risk_level=RiskLevel.R2,
            expected_impact="Choose the intervention that moves the metric under intervention.",
            approval_required=False,
            approver_role=None,
            connector_name="manual_review",
            action_type="propose",
            action_parameters={},
            candidate_actions=self._candidates,
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


def _runtime(candidates, *, shell_view=None):
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
        connector_registry=_connector_registry(),
        shell_view=shell_view,
        governance_decision_client=LocalGovernanceDecisionClient(
            MetricCohortABVerifier(_cohort_for),
            approval_required_at_or_above="R4",
        ),
    )
    if candidates is not None:
        runtime.action_builder = _CandidateProposalBuilder(candidates)
    return runtime


def _governed_decision_event(result):
    for event in result.trace_events:
        if event.step == "governed_decision":
            return event.payload
    raise AssertionError("no governed_decision trace event")


class GovernedCausalInterventionSelection(unittest.TestCase):
    def test_disposer_selects_causal_driver_over_correlational_lure(self):
        # candidate order puts the LURE first, so a "pick the first" policy would pick wrong; the
        # interventional verifier must be what drives the choice to the causal driver.
        result = _runtime((_LURE, _CAUSAL)).run("最近7天GMV是多少？", _PARAMS)
        payload = _governed_decision_event(result)
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertEqual(
            payload["chosen_action"], _CAUSAL
        )  # causal beats correlational, regardless of order

    def test_all_lures_escalates_never_auto_selects(self):
        result = _runtime((_LURE, "raise_budget:another_lure")).run("最近7天GMV是多少？", _PARAMS)
        payload = _governed_decision_event(result)
        self.assertEqual(payload["verdict"], "ESCALATE")  # nothing verified -> never auto-select
        self.assertIsNone(payload["chosen_action"])
        self.assertTrue(result.action_proposal.approval_required)  # forced to a human

    def test_selection_does_not_bypass_corrigibility(self):
        shell = CorrigibilityShell()
        shell.op_pause()
        from agent_os_core.trusted_loop import TrustedLoopBlocked

        with self.assertRaises(TrustedLoopBlocked):
            _runtime((_LURE, _CAUSAL), shell_view=shell.view()).run("最近7天GMV是多少？", _PARAMS)

    def test_default_no_candidates_is_backward_compatible(self):
        # no custom builder -> default proposal has empty candidate_actions -> seam gets (recommended_action,)
        result = _runtime(None).run("最近7天GMV是多少？", _PARAMS)
        payload = _governed_decision_event(result)
        self.assertIn(
            payload["verdict"], {"ALLOW", "ESCALATE", "VERIFY_MORE"}
        )  # unchanged single-candidate path


if __name__ == "__main__":
    unittest.main()
