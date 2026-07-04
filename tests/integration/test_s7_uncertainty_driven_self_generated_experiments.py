"""S7 (RR-0048 Option 2): the loop SELF-GENERATES its own experiments from its own uncertainty.

The 自主 gap the loop kept hitting: candidate interventions were ENUMERATED (supplied per run), not
self-generated. S7 closes a bounded, in-bounds slice of it. An `UncertaintyDrivenProposer` generates the
candidate experiments from the system's OWN resolved-ledger — it proposes testing the drivers whose causal
effect it has NOT yet determined — so the experiment list SHIFTS as outcomes accumulate. The system chooses
its own experiments from what it does not yet know; the governed disposer still selects causally (S5), the
human still approves, and C7 still stops.

Proven here:
  1. self-generation: round 1 proposes the full unresolved driver-space; after a driver is resolved
     (learned), round 2's self-generated candidate list DROPS it and proposes the remaining unknowns — the
     system's chosen experiments change because its uncertainty changed (对世界开环,受治理闭环 + 从反馈学习).
  2. 强 among the self-generated set: the governed disposer selects the causal driver over the lures by
     interventional cohort A/B evidence; when only lures remain, it ESCALATEs (never auto-runs an unverified
     experiment — it asks a human to authorize the exploratory test).
  3. 受治理: a paused shell halts a self-generated run before anything executes (C7 is not bypassed by the
     loop proposing its own work).

Honest bound — this is NOT open-world causal discovery. The proposer prioritizes WITHIN a domain-supplied
driver-space; it does not discover the driver-space or hypothesize novel causal structure (that lives in the
object layer and reaches the OS only through the seam). It is self-directed experimentation over known
variables by heuristic uncertainty, governed and correctable — a bounded 自主, not autonomy over the gate.
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
from agent_os_core.action_proposal import UncertaintyDrivenProposer  # noqa: E402
from agent_os_core.governance_decision_seam import (  # noqa: E402
    LocalGovernanceDecisionClient,
    MetricCohortABVerifier,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}

# a domain-supplied driver-space; only the causal one moves the metric under intervention
_CAUSAL = "raise_budget:causal_driver"
_LURE_1 = "shift_creative:lure"
_LURE_2 = "resend_email:lure"
_DRIVER_SPACE = (_CAUSAL, _LURE_1, _LURE_2)


def _effect_cohort() -> QueryResult:
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (120.0, 132.0, 128.0, 141.0)]
        + [{"cohort": "B", "metric": v} for v in (88.0, 91.0, 84.0, 90.0)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _null_cohort() -> QueryResult:
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (100.0, 101.0, 99.0, 100.5)]
        + [{"cohort": "B", "metric": v} for v in (100.2, 99.8, 100.1, 99.9)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _cohort_for(action: str) -> QueryResult:
    return _effect_cohort() if action == _CAUSAL else _null_cohort()


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


def _runtime(resolved: set[str], *, shell_view=None):
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
    # the system self-generates its experiments from what it has NOT yet resolved
    runtime.action_builder = UncertaintyDrivenProposer(
        driver_space=_DRIVER_SPACE,
        resolved_provider=lambda: set(resolved),
    )
    return runtime


def _governed_decision_event(result):
    for event in result.trace_events:
        if event.step == "governed_decision":
            return event.payload
    raise AssertionError("no governed_decision trace event")


class UncertaintyDrivenSelfGeneratedExperiments(unittest.TestCase):
    def test_self_generated_experiments_shift_as_the_system_learns(self):
        resolved: set[str] = set()

        # round 1: nothing resolved -> the system proposes the whole unknown driver-space and the governed
        # disposer causally selects the driver that moves the metric under intervention.
        r1 = _runtime(resolved).run("最近7天GMV是多少？", _PARAMS)
        self.assertEqual(tuple(r1.action_proposal.candidate_actions), _DRIVER_SPACE)
        self.assertEqual(_governed_decision_event(r1)["chosen_action"], _CAUSAL)

        # the system learns: the causal driver is now resolved (would be recorded via S4 outcome ledger).
        resolved.add(_CAUSAL)

        # round 2: the SELF-GENERATED experiment list has changed — it no longer proposes the resolved
        # driver; it proposes the remaining unknowns. Only lures remain, so the disposer ESCALATEs (never
        # auto-runs an unverified experiment — it asks a human to authorize the exploratory test).
        r2 = _runtime(resolved).run("最近7天GMV是多少？", _PARAMS)
        self.assertEqual(tuple(r2.action_proposal.candidate_actions), (_LURE_1, _LURE_2))
        self.assertNotIn(
            _CAUSAL, r2.action_proposal.candidate_actions
        )  # experiment set shifted with learning
        self.assertEqual(_governed_decision_event(r2)["verdict"], "ESCALATE")
        self.assertTrue(r2.action_proposal.approval_required)

    def test_all_resolved_falls_back_to_full_space_never_empty(self):
        # if everything is resolved, the proposer must not emit an empty experiment set (which would send
        # nothing to govern); it falls back to the full space so the loop stays well-formed.
        r = _runtime(set(_DRIVER_SPACE)).run("最近7天GMV是多少？", _PARAMS)
        self.assertEqual(tuple(r.action_proposal.candidate_actions), _DRIVER_SPACE)

    def test_self_generated_run_still_obeys_corrigibility(self):
        shell = CorrigibilityShell()
        shell.op_pause()
        with self.assertRaises(TrustedLoopBlocked):
            _runtime(set(), shell_view=shell.view()).run("最近7天GMV是多少？", _PARAMS)


if __name__ == "__main__":
    unittest.main()
