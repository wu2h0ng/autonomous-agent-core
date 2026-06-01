from __future__ import annotations

from agent_os_contracts import ActionProposal, EvidenceChain, RiskLevel


class ActionProposalBuilder:
    def build(self, *, proposal_id: str, evidence: EvidenceChain) -> ActionProposal:
        if evidence.query_result.row_count == 0:
            recommendation = "Create a review task to confirm data availability and metric scope."
            risk_level = RiskLevel.R3
            approval_required = True
            approver_role = "Business Owner"
        else:
            recommendation = "Review the metric result and decide whether follow-up analysis is needed."
            risk_level = RiskLevel.R2
            approval_required = False
            approver_role = None

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
        )
