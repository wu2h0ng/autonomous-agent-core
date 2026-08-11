"""S8 (RR-0048 Option 2): a LIVE closed active-experimentation loop (not a simulated ledger).

S7 proved the self-generation MECHANISM, but its resolved-ledger was a hand-set simulation. S8 makes the
loop live: a real `ExperimentLedger` store, and an `ActiveExperimentationLoop` that records the driver the
governed disposer CONFIRMED into that store, so the NEXT round's self-generated experiments are driven by
the system's OWN accumulated result — end to end, no simulation, single domain.

The closed cycle, run for real here:
    propose experiments from the ledger (自主, S7) -> govern-causally-select (强, S5)
      -> record the confirmed driver into the ledger (learn / 复利) -> re-propose from the updated ledger.

Proven:
  1. round 1 (empty ledger) proposes the whole driver-space; the disposer confirms the causal driver; the
     loop records it into the REAL ledger. Round 2 reads that real ledger and its self-generated experiments
     have SHIFTED — the confirmed driver is gone, the remaining unknowns are proposed. No hand-set state.
  2. the loop only records what the governed disposer CONFIRMED via interventional evidence (never a
     self-declared success), and it never promotes knowledge or mints value — resolution drives experiment
     PRIORITIZATION only (anti-wirehead: the moat/value path stays S4 operator-attested).
  3. 受治理: a paused shell halts a live round; the loop cannot run experiments through a paused C7.

Honest bound: still a KNOWN driver-space (not open-world discovery), single-step, single domain; "resolved"
is a binary interventional-evidence signal. This is a live governed active-experimentation loop over known
variables — a real milestone shape ("在一个领域做到是里程碑"), not the arbitrary-domain open-world goal.
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
from agent_os_core.experimentation import ActiveExperimentationLoop, ExperimentLedger  # noqa: E402
from agent_os_core.governance_decision_seam import (  # noqa: E402
    LocalGovernanceDecisionClient,
    MetricCohortABVerifier,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
_Q = "最近7天GMV是多少？"

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


def _runtime(ledger: ExperimentLedger, *, shell_view=None) -> TrustedLoopRuntime:
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
    # the proposer reads the REAL ledger — no simulated set
    runtime.action_builder = UncertaintyDrivenProposer(
        driver_space=_DRIVER_SPACE,
        resolved_provider=ledger.resolved,
    )
    return runtime


class LiveClosedActiveExperimentationLoop(unittest.TestCase):
    def test_experiments_shift_from_real_recorded_outcomes(self):
        ledger = ExperimentLedger()
        loop = ActiveExperimentationLoop(runtime=_runtime(ledger), ledger=ledger)

        r1 = loop.run_round(_Q, _PARAMS)
        # round 1: whole unknown space proposed; the causal driver confirmed and recorded into the REAL ledger
        self.assertEqual(tuple(r1.result.action_proposal.candidate_actions), _DRIVER_SPACE)
        self.assertEqual(r1.chosen_action, _CAUSAL)
        self.assertEqual(ledger.resolved(), {_CAUSAL})  # learned from the real run, not hand-set

        r2 = loop.run_round(_Q, _PARAMS)
        # round 2: the self-generated experiments SHIFTED, driven by the real ledger update from round 1
        self.assertEqual(tuple(r2.result.action_proposal.candidate_actions), (_LURE_1, _LURE_2))
        self.assertNotIn(_CAUSAL, r2.result.action_proposal.candidate_actions)
        self.assertIsNone(
            r2.chosen_action
        )  # only lures remain -> nothing confirmed -> escalate to a human

    def test_loop_records_only_confirmed_drivers_never_self_declares(self):
        # a run whose candidates are ALL lures confirms nothing -> the ledger stays empty (the loop never
        # records a success it did not interventionally confirm; anti-wirehead for the experiment ledger).
        ledger = ExperimentLedger()
        rt = _runtime(ledger)
        rt.action_builder = UncertaintyDrivenProposer(
            driver_space=(_LURE_1, _LURE_2), resolved_provider=ledger.resolved
        )
        loop = ActiveExperimentationLoop(runtime=rt, ledger=ledger)

        loop.run_round(_Q, _PARAMS)
        self.assertEqual(ledger.resolved(), set())  # nothing confirmed -> nothing recorded

    def test_live_round_obeys_corrigibility(self):
        ledger = ExperimentLedger()
        shell = CorrigibilityShell()
        shell.op_pause()
        loop = ActiveExperimentationLoop(
            runtime=_runtime(ledger, shell_view=shell.view()), ledger=ledger
        )
        with self.assertRaises(TrustedLoopBlocked):
            loop.run_round(_Q, _PARAMS)
        self.assertEqual(ledger.resolved(), set())  # a paused run records nothing


if __name__ == "__main__":
    unittest.main()
