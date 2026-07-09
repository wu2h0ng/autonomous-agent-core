from __future__ import annotations

from collections.abc import Callable

from agent_os_contracts import ActionProposal, EvidenceChain, RiskLevel


class UncertaintyDrivenProposer:
    """Self-generates candidate experiments from the system's OWN uncertainty (S7, RR-0048 Option 2).

    Given a domain-supplied ``driver_space`` and a ``resolved_provider`` (the drivers whose causal effect the
    system has already DETERMINED via recorded interventional outcomes), this proposer emits the UNRESOLVED
    drivers as the candidate experiments — the interventions worth running to reduce uncertainty. As outcomes
    accumulate the resolved set grows and the proposed experiment set shifts: the system chooses its own
    experiments from what it does not yet know (对世界开环,受治理闭环). The governed disposer then selects
    causally among these candidates (the seam), a human approves, and C7 can stop the run.

    Honest bound: this prioritizes WITHIN a known ``driver_space`` by heuristic uncertainty; it does NOT
    discover the driver-space or hypothesize novel causal structure (open-world causal discovery lives in the
    object layer and reaches the OS only through the governed-decision seam). It is self-directed
    experimentation over known variables, governed and correctable — a bounded autonomy, never autonomy over
    the correction gate.
    """

    def __init__(
        self,
        *,
        driver_space: tuple[str, ...],
        resolved_provider: Callable[[], set[str]],
    ) -> None:
        if not driver_space:
            raise ValueError("driver_space must be non-empty")
        self._driver_space = tuple(driver_space)
        self._resolved_provider = resolved_provider

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        resolved = self._resolved_provider() or set()
        unresolved = tuple(driver for driver in self._driver_space if driver not in resolved)
        # Never emit an empty experiment set (nothing to govern). If everything is resolved, re-offer the
        # full space; a staleness / re-test policy is a deliberate future refinement, not silent emptiness.
        candidates = unresolved or self._driver_space
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action=candidates[0],
            reason="Self-generated experiments over unresolved drivers to reduce causal uncertainty.",
            risk_level=RiskLevel.R2,
            expected_impact="Determine which unconfirmed driver moves the metric under intervention.",
            approval_required=False,
            approver_role=None,
            connector_name="manual_review",
            action_type="propose",
            action_parameters={},
            candidate_actions=candidates,
        )


class ActionProposalBuilder:
    """Builds ActionProposal instances from EvidenceChain data.

    The builder determines risk level, approval requirements, and action type
    based on the query result and explicit user intent.  Plain analysis stays
    on the no-side-effect ``manual_review`` connector.  Explicit requests to
    record a follow-up action route to the reversible ``action_record``
    connector, but remain approval-bound.
    """

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        if evidence.query_result.row_count > 0 and self._requests_action_record(
            evidence.intent.question
        ):
            return self._build_action_record_proposal(
                proposal_id=proposal_id,
                evidence=evidence,
            )

        if evidence.query_result.row_count == 0:
            recommendation = "Create a review task to confirm data availability and metric scope."
            risk_level = RiskLevel.R3
            approval_required = True
            approver_role = "Business Owner"
            action_type = "execute"
            # ADR-0014: this builder genuinely deliberates over ONE admissible action —
            # an empty result grounds no alternative business action, only a
            # data-availability review. State that explicitly instead of padding the
            # choice set with fabricated alternatives.
            single_option_rationale = (
                "The metric query returned no rows, so no alternative business action "
                "can be grounded in this evidence; the only admissible follow-up is a "
                "review task confirming data availability and metric scope."
            )
        else:
            recommendation = (
                "Review the metric result and decide whether follow-up analysis is needed."
            )
            risk_level = RiskLevel.R2
            approval_required = False
            approver_role = None
            action_type = "propose"
            single_option_rationale = None

        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=evidence.metric_contract.metric_name,
            recommended_action=recommendation,
            reason=evidence.conclusion,
            risk_level=risk_level,
            expected_impact="Improve decision traceability before operational action.",
            approval_required=approval_required,
            approver_role=approver_role,
            connector_name="manual_review",
            action_type=action_type,
            action_parameters={},
            single_option_rationale=single_option_rationale,
        )

    @staticmethod
    def _requests_action_record(question: str) -> bool:
        normalized = question.lower()
        triggers = (
            "记录行动",
            "行动记录",
            "跟进行动",
            "创建行动",
            "创建跟进",
            "登记行动",
            "落地动作",
            "业务动作",
            "record action",
            "action record",
            "log action",
            "create action",
            "create follow-up",
            "follow-up action",
        )
        return any(trigger in normalized for trigger in triggers)

    @staticmethod
    def _build_action_record_proposal(
        *,
        proposal_id: str,
        evidence: EvidenceChain,
    ) -> ActionProposal:
        metric_name = evidence.metric_contract.metric_name
        return ActionProposal(
            proposal_id=proposal_id,
            evidence_chain_id=evidence.evidence_chain_id,
            target_object=metric_name,
            recommended_action=(
                "Create an approval-bound follow-up action record for this metric result."
            ),
            reason=evidence.conclusion,
            risk_level=RiskLevel.R3,
            expected_impact=(
                "Persist a reversible business action record tied to the evidence chain."
            ),
            approval_required=True,
            approver_role="Business Owner",
            connector_name="action_record",
            action_type="execute",
            action_parameters={
                "metric_name": metric_name,
                "question": evidence.intent.question,
                "evidence_chain_id": evidence.evidence_chain_id,
                "trace_id": evidence.trace_id,
                "row_count": evidence.query_result.row_count,
                "conclusion": evidence.conclusion,
                "confidence": evidence.confidence,
            },
            # ADR-0014: the user explicitly requested recording this follow-up action
            # and the reversible action_record connector is the only governed write
            # path for that request — a truthful single-option rationale, not padding.
            single_option_rationale=(
                "The user explicitly requested recording a follow-up action; the "
                "reversible action_record connector is the only governed write path "
                "for that request, so no alternative action is enumerated."
            ),
        )
