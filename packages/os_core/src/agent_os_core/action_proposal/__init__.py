from __future__ import annotations

from agent_os_contracts import ActionProposal, EvidenceChain, RiskLevel


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
        )
