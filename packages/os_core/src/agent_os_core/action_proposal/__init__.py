from __future__ import annotations

from agent_os_contracts import ActionProposal, EvidenceChain, RiskLevel


class ActionProposalBuilder:
    """Builds ActionProposal instances from EvidenceChain data.

    The builder determines risk level, approval requirements, and action type
    based on the query result.  In the MVP, the ``connector_name`` is hardcoded
    to ``"manual_review"`` and the ``action_type`` is differentiated by
    whether the query returned data.
    """

    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        if evidence.query_result.row_count == 0:
            recommendation = "Create a review task to confirm data availability and metric scope."
            risk_level = RiskLevel.R3
            approval_required = True
            approver_role = "Business Owner"
            action_type = "execute"
        else:
            recommendation = (
                "Review the metric result and decide whether follow-up analysis is needed."
            )
            risk_level = RiskLevel.R2
            approval_required = False
            approver_role = None
            action_type = "propose"

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
        )
