"""ADR-0014: human-facing choice-set contract for approval-required proposals.

Fail-closed invariant at the TrustedLoopRuntime proposal step: a proposal that
requires human approval MUST surface either a real choice set (>=2 alternatives,
exactly one recommended and bound to ``recommended_action``, covering every seam
``candidate_actions`` label) or an explicit non-empty ``single_option_rationale``.
Violations are refused with a typed ``BlockCode.CHOICE_SET_VIOLATION`` block and
never reach ``awaiting_approval``. Non-approval (R0-R2 propose-only) proposals are
exempt. These tests would fail if the runtime skipped the invariant, hid the
choice set from the trace, or dropped the ADR-0009 ALLOW-rebind flag-follow.
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
    BlockCode,
    MetricContract,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_contracts.governance_decision_seam import (  # noqa: E402
    ALLOW,
    ESCALATE,
    VERIFY_MORE,
    GovernanceDecisionResponse,
)
from agent_os_core import ProviderRegistry, SemanticRegistry, TrustedLoopRuntime  # noqa: E402
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
_QUESTION = "最近7天GMV是多少？"


class _ExecutionSpyConnector(ManualReviewConnector):
    """Raises if execute() is called — regression guard for the refusal path."""

    def __init__(self) -> None:
        self.execute_called = False

    def execute(self, operation, parameters):  # type: ignore[override]
        self.execute_called = True
        raise AssertionError("connector.execute() must not run for a refused proposal")


def _connector_registry(connector: ManualReviewConnector | None = None) -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        connector or ManualReviewConnector(),
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


class _ChoiceSetApprovalBuilder:
    """Approval-required builder with a configurable ADR-0014 choice set."""

    def __init__(
        self,
        *,
        recommended_action: str = "raise_budget",
        alternatives: tuple = (),
        single_option_rationale: str | None = None,
        candidate_actions: tuple[str, ...] = (),
        approval_required: bool = True,
    ) -> None:
        self._recommended_action = recommended_action
        self._alternatives = alternatives
        self._single_option_rationale = single_option_rationale
        self._candidate_actions = candidate_actions
        self._approval_required = approval_required

    def build(self, *, proposal_id: str, evidence) -> ActionProposal:
        kwargs = {}
        if self._alternatives:
            kwargs["alternatives"] = self._alternatives
        if self._single_option_rationale is not None:
            kwargs["single_option_rationale"] = self._single_option_rationale
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action=self._recommended_action,
            reason=evidence.conclusion,
            risk_level=RiskLevel.R3,
            expected_impact="Exercise the ADR-0014 choice-set invariant.",
            approval_required=self._approval_required,
            approver_role="Business Owner" if self._approval_required else None,
            connector_name="manual_review",
            action_type="execute" if self._approval_required else "propose",
            action_parameters={},
            candidate_actions=self._candidate_actions,
            **kwargs,
        )


class _AllowChoosingSeamClient:
    """Contract-only seam stub: ALLOW with a fixed chosen_action (no sibling import)."""

    def __init__(self, chosen_action: str) -> None:
        self._chosen_action = chosen_action

    def decide(self, request) -> GovernanceDecisionResponse:
        return GovernanceDecisionResponse(
            task_id=request.task_id,
            verdict=ALLOW,
            chosen_action=self._chosen_action,
            confidence=0.9,
            reason="test stub",
            audit_ref="audit-choice-set-1",
        )


class _EscalatingSeamClient:
    """Contract-only seam stub that TIGHTENS via a configurable escalation verdict."""

    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    def decide(self, request) -> GovernanceDecisionResponse:
        return GovernanceDecisionResponse(
            task_id=request.task_id,
            verdict=self._verdict,
            chosen_action=None,  # escalation -> no causal selection
            confidence=0.4,
            reason="test escalation stub",
            audit_ref="audit-escalate-1",
        )


class _RaisingSeamClient:
    """Seam stub whose decide() raises — exercises the client-unavailable path."""

    def decide(self, request):  # noqa: ARG002 - stub always raises
        raise RuntimeError("seam transport down")


class _InvalidVerdictSeamClient:
    """Seam stub returning a verdict outside the allowed set."""

    def decide(self, request) -> GovernanceDecisionResponse:
        return GovernanceDecisionResponse(
            task_id=request.task_id,
            verdict="NOT_A_REAL_VERDICT",
            chosen_action=None,
            confidence=0.0,
            reason="test invalid verdict stub",
            audit_ref="audit-invalid-1",
        )


def _build_runtime(
    *,
    rows: list[dict] | None = None,
    connector_registry: ActionConnectorRegistry | None = None,
    governance_decision_client=None,
) -> TrustedLoopRuntime:
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
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor(
            rows if rows is not None else [{"order_date": "2026-05-31", "gmv": 128800.0}]
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
        connector_registry=connector_registry or _connector_registry(),
        governance_decision_client=governance_decision_client,
    )


def _alternative(action: str, *, recommended: bool = False, rationale: str = "why"):
    from agent_os_contracts import ActionAlternative

    return ActionAlternative(
        action=action,
        rationale=rationale,
        risk_level=RiskLevel.R2,
        recommended=recommended,
    )


class ChoiceSetInvariantRefusalTest(unittest.TestCase):
    """ADR-0014 negative paths: violations refuse at the proposal step."""

    def _assert_refused(self, runtime: TrustedLoopRuntime) -> TrustedLoopBlocked:
        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.run(_QUESTION, dict(_PARAMS))
        block = ctx.exception.block
        self.assertEqual(block.code, BlockCode.CHOICE_SET_VIOLATION)
        self.assertEqual(block.stage, "action_proposal")
        self.assertIsNotNone(block.trace_id)
        return ctx.exception

    def test_approval_without_alternatives_or_rationale_is_refused(self) -> None:
        spy = _ExecutionSpyConnector()
        runtime = _build_runtime(connector_registry=_connector_registry(spy))
        runtime.action_builder = _ChoiceSetApprovalBuilder()

        blocked = self._assert_refused(runtime)

        # The refusal is auditable: the persisted trace records the proposal step
        # (with the new choice-set fields) followed by the blocked step, and the
        # run never reaches awaiting_approval.
        run_trace = runtime.trace_store.get(blocked.block.trace_id)
        self.assertIsNotNone(run_trace)
        self.assertEqual(run_trace.status, "blocked")
        steps = [event.step for event in run_trace.events]
        self.assertIn("action_proposal", steps)
        self.assertIn("blocked", steps)
        self.assertNotIn("awaiting_approval", steps)
        proposal_event = next(e for e in run_trace.events if e.step == "action_proposal")
        self.assertEqual(proposal_event.payload["alternatives_count"], 0)
        self.assertFalse(proposal_event.payload["has_single_option_rationale"])
        blocked_event = next(e for e in run_trace.events if e.step == "blocked")
        self.assertEqual(blocked_event.payload["code"], "choice_set_violation")
        # No pending approval record is minted and no connector side effect runs.
        self.assertEqual(runtime.approval_runtime.list(), ())
        self.assertFalse(spy.execute_called)

    def test_alternatives_with_zero_recommended_refused(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            alternatives=(_alternative("hold_budget"), _alternative("raise_budget")),
        )
        self._assert_refused(runtime)

    def test_alternatives_with_two_recommended_refused(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            alternatives=(
                _alternative("hold_budget", recommended=True),
                _alternative("raise_budget", recommended=True),
            ),
        )
        self._assert_refused(runtime)

    def test_recommended_alternative_inconsistent_with_recommended_action_refused(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            recommended_action="raise_budget",
            alternatives=(
                _alternative("hold_budget", recommended=True),
                _alternative("raise_budget"),
            ),
        )
        self._assert_refused(runtime)

    def test_single_entry_alternatives_refused(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            alternatives=(_alternative("raise_budget", recommended=True),),
        )
        self._assert_refused(runtime)

    def test_whitespace_single_option_rationale_refused(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(single_option_rationale="   ")
        self._assert_refused(runtime)

    def test_candidate_action_missing_from_alternatives_refused(self) -> None:
        # ADR-0009 relationship: the human must see at least what the disposer saw.
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            recommended_action="raise_budget",
            candidate_actions=("raise_budget", "pause_campaign"),
            alternatives=(
                _alternative("hold_budget"),
                _alternative("raise_budget", recommended=True),
            ),
        )
        self._assert_refused(runtime)


class ChoiceSetInvariantHappyPathTest(unittest.TestCase):
    """Valid choice sets flow through to awaiting_approval with trace/context."""

    def test_valid_alternatives_reach_awaiting_approval(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            recommended_action="raise_budget",
            alternatives=(
                _alternative("hold_budget", rationale="keep spend flat"),
                _alternative("raise_budget", recommended=True, rationale="verified driver"),
            ),
        )

        result = runtime.run(_QUESTION, dict(_PARAMS))

        steps = [event.step for event in result.trace_events]
        self.assertIn("awaiting_approval", steps)
        proposal_event = next(e for e in result.trace_events if e.step == "action_proposal")
        self.assertEqual(proposal_event.payload["alternatives_count"], 2)
        self.assertFalse(proposal_event.payload["has_single_option_rationale"])
        # The approval-resume context snapshots the choice set for the approval surface.
        approval_id = result.approval_record.approval_id
        context = runtime.approval_context_store.get(approval_id)
        self.assertIsNotNone(context)
        self.assertEqual(len(context.alternatives), 2)
        self.assertEqual(
            [alt.action for alt in context.alternatives if alt.recommended],
            ["raise_budget"],
        )
        self.assertIsNone(context.single_option_rationale)

    def test_single_option_rationale_reaches_awaiting_approval(self) -> None:
        runtime = _build_runtime()
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            single_option_rationale="Only one governed write path exists for this request.",
        )

        result = runtime.run(_QUESTION, dict(_PARAMS))

        steps = [event.step for event in result.trace_events]
        self.assertIn("awaiting_approval", steps)
        proposal_event = next(e for e in result.trace_events if e.step == "action_proposal")
        self.assertEqual(proposal_event.payload["alternatives_count"], 0)
        self.assertTrue(proposal_event.payload["has_single_option_rationale"])
        context = runtime.approval_context_store.get(result.approval_record.approval_id)
        self.assertEqual(
            context.single_option_rationale,
            "Only one governed write path exists for this request.",
        )

    def test_non_approval_r2_path_remains_exempt(self) -> None:
        # Regression (ADR-0014 test 3): the default R2 analysis path is unchanged.
        runtime = _build_runtime()
        result = runtime.run(_QUESTION, dict(_PARAMS))

        self.assertFalse(result.action_proposal.approval_required)
        self.assertEqual(result.action_proposal.alternatives, ())
        self.assertIsNone(result.action_proposal.single_option_rationale)
        steps = [event.step for event in result.trace_events]
        self.assertIn("connector_execute", steps)
        self.assertNotIn("awaiting_approval", steps)


class DefaultBuilderChoiceSetTest(unittest.TestCase):
    """The stock ActionProposalBuilder approval paths satisfy the invariant truthfully."""

    def test_zero_row_review_task_carries_single_option_rationale(self) -> None:
        runtime = _build_runtime(rows=[])
        result = runtime.run(_QUESTION, dict(_PARAMS))

        proposal = result.action_proposal
        self.assertTrue(proposal.approval_required)
        self.assertTrue((proposal.single_option_rationale or "").strip())
        self.assertEqual(proposal.alternatives, ())
        self.assertIn("awaiting_approval", [event.step for event in result.trace_events])

    def test_action_record_intent_carries_single_option_rationale(self) -> None:
        runtime = _build_runtime()
        result = runtime.run("记录行动：基于最近7天GMV创建一个跟进行动", dict(_PARAMS))

        proposal = result.action_proposal
        self.assertTrue(proposal.approval_required)
        self.assertEqual(proposal.connector_name, "action_record")
        self.assertTrue((proposal.single_option_rationale or "").strip())


class ChoiceSetSeamRebindTest(unittest.TestCase):
    """ADR-0009 ALLOW-rebind: the recommended flag follows the seam's chosen_action."""

    def test_allow_rebind_moves_recommended_flag(self) -> None:
        lure = "raise_budget:correlational_lure"
        causal = "raise_budget:causal_driver"
        runtime = _build_runtime(governance_decision_client=_AllowChoosingSeamClient(causal))
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            recommended_action=lure,
            approval_required=False,
            candidate_actions=(lure, causal),
            alternatives=(
                _alternative(lure, recommended=True, rationale="correlates with GMV"),
                _alternative(causal, rationale="verified under intervention"),
            ),
        )

        result = runtime.run(_QUESTION, dict(_PARAMS))

        proposal = result.action_proposal
        self.assertEqual(proposal.recommended_action, causal)
        recommended = [alt.action for alt in proposal.alternatives if alt.recommended]
        self.assertEqual(recommended, [causal])


class ChoiceSetSeamEscalationReGateTest(unittest.TestCase):
    """ADR-0014 fix: a seam that ESCALATES a propose-only proposal must not reach the
    human approval surface with a blank/collapsed choice set. The runtime attaches a
    truthful seam-escalation single_option_rationale (tighten-only), then re-runs the
    invariant and blocks a still-degenerate choice set with CHOICE_SET_VIOLATION.
    """

    def _run_to_approval(self, runtime: TrustedLoopRuntime):
        result = runtime.run(_QUESTION, dict(_PARAMS))
        steps = [event.step for event in result.trace_events]
        self.assertIn("awaiting_approval", steps)
        return result, steps

    def _assert_truthful_seam_rationale(self, rationale: str | None, *, verdict_token: str) -> None:
        text = (rationale or "").strip()
        self.assertTrue(text, "a seam-escalated single option must never be blank")
        self.assertIn("governance seam", text)
        self.assertIn(verdict_token, text)
        self.assertIn("propose-only", text)

    def _assert_escalated_propose_only_attaches_rationale(
        self, seam_client, *, verdict_token: str
    ) -> None:
        spy = _ExecutionSpyConnector()
        runtime = _build_runtime(
            connector_registry=_connector_registry(spy),
            governance_decision_client=seam_client,
        )
        runtime.action_builder = _ChoiceSetApprovalBuilder(approval_required=False)

        result, steps = self._run_to_approval(runtime)

        proposal = result.action_proposal
        self.assertTrue(proposal.approval_required)
        self.assertEqual(proposal.alternatives, ())
        self._assert_truthful_seam_rationale(
            proposal.single_option_rationale, verdict_token=verdict_token
        )
        # The machine-attached rationale is auditable as its own trace event, distinct
        # from a builder-supplied rationale.
        self.assertIn("choice_set_seam_escalation", steps)
        # The approval-resume context AND the durable approval record both carry it, so a
        # post-execution audit can still show why only one option was surfaced.
        approval_id = result.approval_record.approval_id
        context = runtime.approval_context_store.get(approval_id)
        self.assertEqual(context.single_option_rationale, proposal.single_option_rationale)
        record = runtime.approval_runtime.get(approval_id)
        self.assertEqual(record.single_option_rationale, proposal.single_option_rationale)
        # A blank single option never reaches a human; no connector side effect runs.
        self.assertFalse(spy.execute_called)

    def test_escalate_verdict_on_propose_only_attaches_truthful_rationale(self) -> None:
        self._assert_escalated_propose_only_attaches_rationale(
            _EscalatingSeamClient(ESCALATE), verdict_token="ESCALATE"
        )

    def test_verify_more_verdict_on_propose_only_attaches_truthful_rationale(self) -> None:
        self._assert_escalated_propose_only_attaches_rationale(
            _EscalatingSeamClient(VERIFY_MORE), verdict_token="VERIFY_MORE"
        )

    def test_seam_unavailable_on_propose_only_attaches_truthful_rationale(self) -> None:
        self._assert_escalated_propose_only_attaches_rationale(
            _RaisingSeamClient(), verdict_token="seam-unavailable"
        )

    def test_invalid_verdict_on_propose_only_attaches_truthful_rationale(self) -> None:
        self._assert_escalated_propose_only_attaches_rationale(
            _InvalidVerdictSeamClient(), verdict_token="invalid-verdict"
        )

    def test_seam_escalation_of_degenerate_choice_set_is_blocked(self) -> None:
        # A propose-only proposal that already carried a DEGENERATE non-empty choice set
        # (length-1 alternatives) cannot be rescued by an attached rationale — the human
        # would still see a collapsed set. The re-gate blocks it with CHOICE_SET_VIOLATION.
        spy = _ExecutionSpyConnector()
        runtime = _build_runtime(
            connector_registry=_connector_registry(spy),
            governance_decision_client=_EscalatingSeamClient(ESCALATE),
        )
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            approval_required=False,
            alternatives=(_alternative("raise_budget", recommended=True),),
        )

        with self.assertRaises(TrustedLoopBlocked) as ctx:
            runtime.run(_QUESTION, dict(_PARAMS))
        block = ctx.exception.block
        self.assertEqual(block.code, BlockCode.CHOICE_SET_VIOLATION)
        self.assertEqual(block.stage, "action_proposal")

        run_trace = runtime.trace_store.get(block.trace_id)
        steps = [event.step for event in run_trace.events]
        self.assertNotIn("awaiting_approval", steps)
        self.assertIn("blocked", steps)
        self.assertEqual(runtime.approval_runtime.list(), ())
        self.assertFalse(spy.execute_called)

    def test_seam_escalation_preserves_valid_builder_choice_set(self) -> None:
        # Tighten-only + truthfulness: a propose-only proposal that ALREADY enumerated a
        # valid >=2 choice set must reach approval with its real alternatives intact — the
        # runtime must NOT clobber it with a single_option_rationale (there is not a single
        # option) and must NOT block it.
        runtime = _build_runtime(governance_decision_client=_EscalatingSeamClient(ESCALATE))
        runtime.action_builder = _ChoiceSetApprovalBuilder(
            approval_required=False,
            recommended_action="raise_budget",
            alternatives=(
                _alternative("hold_budget", rationale="keep spend flat"),
                _alternative("raise_budget", recommended=True, rationale="verified driver"),
            ),
        )

        result, _ = self._run_to_approval(runtime)

        proposal = result.action_proposal
        self.assertTrue(proposal.approval_required)
        self.assertIsNone(proposal.single_option_rationale)
        self.assertEqual(len(proposal.alternatives), 2)
        self.assertEqual(
            [alt.action for alt in proposal.alternatives if alt.recommended],
            ["raise_budget"],
        )


if __name__ == "__main__":
    unittest.main()
