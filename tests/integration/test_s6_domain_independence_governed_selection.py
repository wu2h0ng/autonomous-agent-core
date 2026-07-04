"""S6 (RR-0048 Option 2): the governed causal-selection loop is DOMAIN-INDEPENDENT (通用 evidence).

The thesis is 通用 — "能力与领域无关,因为环路与领域无关" (capability is domain-independent because the LOOP
is, not because a model memorized a domain). The honest test of that claim is the project's own discipline:
run the identical OS Core on a STRUCTURALLY DIFFERENT domain and show the governance + causal-selection
invariants still hold, with OS Core BYTE-UNCHANGED.

This suite drives the S5 governed causal intervention-selection loop on a SECOND domain — customer RETENTION
(a *rate*, different semantics from GMV's monetary sum), with its OWN domain-specific correlational lure
("send_discount": churned users who get discounts still churn — correlated, not causal) versus a causal
driver ("improve_support"). Nothing in `agent_os_core` / `agent_os_contracts` is imported differently or
modified; only the domain config (MetricContract, SQLTemplate, cohort data, candidate interventions) changes.

Proven here — the SAME loop, a DIFFERENT domain, no rebuild:
  1. 强 holds in the new domain: the governed disposer selects the causal driver over the domain's
     correlational lure (even listed first), by interventional cohort A/B evidence.
  2. 受治理 holds in the new domain: all-lures -> ESCALATE (never auto-select unverified); a paused shell
     halts the run (C7 supremacy is not domain-coupled).
  3. Domain-independence is structural: this test constructs the second domain purely from config and the
     UNMODIFIED OS Core classes (a companion test asserts no OS Core file changed on this slice).

Honest bound: two business-data domains is domain-PARAMETRICITY evidence, NOT the full 通用 claim (language,
perception, cross-modal, "从未见过的领域"). It shows the loop is not GMV-coupled; it does not show arbitrary-
domain generality. The candidate interventions are still enumerated, not self-generated (自主 remains open).
"""

from __future__ import annotations

import subprocess
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
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

# ---- Domain 2: customer RETENTION (a rate), structurally unlike GMV (a monetary sum) ----
_RETENTION_PARAMS = {"cohort_month": "2026-05", "segment": "smb", "limit": 100}
_LURE = "send_discount:retention"  # correlates with retention, no causal effect under intervention
_CAUSAL = "improve_support:retention"  # real cohort A/B lift under intervention


def _lifted_cohort() -> QueryResult:
    # improve_support: treated cohort A retains meaningfully better than control B
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (0.71, 0.74, 0.69, 0.73)]
        + [{"cohort": "B", "metric": v} for v in (0.52, 0.55, 0.50, 0.53)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _flat_cohort() -> QueryResult:
    # send_discount: an A/B intervention barely moves retention (the correlation was confounded by who churns)
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (0.60, 0.61, 0.59, 0.605)]
        + [{"cohort": "B", "metric": v} for v in (0.602, 0.598, 0.601, 0.599)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _cohort_for(action: str) -> QueryResult:
    return _lifted_cohort() if action == _CAUSAL else _flat_cohort()


class _RetentionProposalBuilder:
    def __init__(self, candidates: tuple[str, ...]) -> None:
        self._candidates = candidates

    def build(self, *, proposal_id: str, evidence) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action=self._candidates[0],
            reason="Enumerated retention interventions for governed causal selection.",
            risk_level=RiskLevel.R2,
            expected_impact="Choose the intervention that lifts retention under intervention.",
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


def _retention_runtime(candidates, *, shell_view=None):
    # A DIFFERENT domain: retention_rate metric, retention schema, retention SQL — same OS Core.
    metric = MetricContract(
        metric_name="retention_rate",
        display_name="Retention Rate",
        definition="Share of a cohort still active after 90 days.",
        owner="lifecycle_ops",
        unit="ratio",
        allowed_schemas=("lifecycle",),
    )
    template = SQLTemplate(
        template_id="retention_by_cohort",
        metric_name="retention_rate",
        sql=(
            "select cohort_month, avg(is_active_d90) as retention_rate from lifecycle.membership "
            "where cohort_month = :cohort_month and segment = :segment group by cohort_month limit :limit"
        ),
        required_parameters=("cohort_month", "segment", "limit"),
        # Domain-declared time bound: retention is filtered by cohort_month, not a start/end window. The
        # runtime passes sql_template.required_time_parameters through to SQL Safety, so the loop is NOT
        # coupled to GMV's start_date/end_date shape — a new domain declares its own (here: none). The
        # DEFAULT happens to be GMV-shaped, which is the one honest domain-convenience coupling (a default,
        # not a mechanism): a new domain must override it, exactly as this one does.
        required_time_parameters=(),
    )
    runtime = TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"cohort_month": "2026-05", "retention_rate": 0.61}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-lifecycle",
                    kind=ProviderKind.WAREHOUSE,
                    name="lifecycle warehouse",
                    owner="lifecycle_ops",
                    allowed_schemas=("lifecycle",),
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
    runtime.action_builder = _RetentionProposalBuilder(candidates)
    return runtime


def _governed_decision_event(result):
    for event in result.trace_events:
        if event.step == "governed_decision":
            return event.payload
    raise AssertionError("no governed_decision trace event")


class DomainIndependentGovernedSelection(unittest.TestCase):
    def test_causal_selection_holds_in_retention_domain(self):
        result = _retention_runtime((_LURE, _CAUSAL)).run(
            "最近一批会员的90天留存率是多少？", _RETENTION_PARAMS
        )
        payload = _governed_decision_event(result)
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertEqual(
            payload["chosen_action"], _CAUSAL
        )  # causal beats the domain's correlational lure

    def test_governance_holds_in_retention_domain(self):
        # all-lures -> never auto-select
        escalate = _retention_runtime((_LURE, "cut_price:retention")).run(
            "留存率是多少？", _RETENTION_PARAMS
        )
        self.assertEqual(_governed_decision_event(escalate)["verdict"], "ESCALATE")
        # C7 supremacy is not domain-coupled
        shell = CorrigibilityShell()
        shell.op_pause()
        with self.assertRaises(TrustedLoopBlocked):
            _retention_runtime((_LURE, _CAUSAL), shell_view=shell.view()).run(
                "留存率是多少？", _RETENTION_PARAMS
            )


class OSCoreUnchangedOnThisSlice(unittest.TestCase):
    def test_no_os_core_or_contract_file_changed_by_s6(self):
        """通用 is structural: this slice adds only a test; OS Core / contracts stay byte-unchanged.

        Domain-independence that required editing OS Core would be domain-COUPLING, not independence. This
        guards the claim: the second domain runs on the identical core. (Skips gracefully outside a git tree.)"""
        try:
            changed = subprocess.run(
                ["git", "diff", "--name-only", "main...HEAD"],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=True,
            ).stdout.split()
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.skipTest("not a git checkout")
        core_touched = [
            f
            for f in changed
            if f.startswith("packages/os_core/") or f.startswith("packages/contracts/")
        ]
        self.assertEqual(
            core_touched, [], f"S6 must not modify OS Core/contracts; changed: {core_touched}"
        )


if __name__ == "__main__":
    unittest.main()
