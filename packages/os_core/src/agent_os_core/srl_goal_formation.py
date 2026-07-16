from __future__ import annotations

from agent_os_contracts import (
    EnvironmentBinding,
    ProposedGoal,
    SrlRelevanceAssessment,
    SrlRelevanceDisposition,
    StandingMission,
)

from .errors import SituationalProposalError, SituationalTrustDenied
from .srl_ports import GoalFormationPort, compute_assessment_digest


class SrlGoalFormation(GoalFormationPort):
    """Form a ProposedGoal from an INVESTIGATE/CREATE_TASK assessment."""

    def __init__(
        self, *, bindings: dict[str, EnvironmentBinding] | None = None
    ) -> None:
        self._bindings = bindings or {}

    def add_binding_for_event(self, event_id: str, binding: EnvironmentBinding) -> None:
        self._bindings[event_id] = binding

    def form_goal(
        self, assessment: SrlRelevanceAssessment, mission: StandingMission
    ) -> ProposedGoal:
        if assessment.disposition not in {
            SrlRelevanceDisposition.INVESTIGATE,
            SrlRelevanceDisposition.CREATE_TASK,
        }:
            raise SituationalProposalError(
                "goal formation requires INVESTIGATE or CREATE_TASK disposition"
            )
        if assessment.proposed_goal_statement is None:
            raise SituationalProposalError("assessment lacks proposed_goal_statement")
        binding = self._bindings.get(assessment.trigger_event_id or "")
        if binding is None:
            # Fall back to a read-only default if binding is not registered.
            write_allowed = False
        else:
            write_allowed = binding.write_capability_id is not None
        if not write_allowed and self._requires_write_effect(assessment):
            raise SituationalTrustDenied(
                "write-effect proposal rejected on read-only binding"
            )
        source_digest = compute_assessment_digest(assessment)
        return ProposedGoal(
            proposal_goal_id=f"goal-proposal:{source_digest}",
            source_binding_digest=source_digest,
            tenant_id=mission.tenant_id,
            workspace_id=mission.workspace_id,
            created_by="srl-goal-formation:v1",
            created_at=assessment.assessed_at,
            statement=assessment.proposed_goal_statement,
            constraints=(
                "proposal-only:no-automatic-task-activation",
                "proposal-only:no-external-effect-authority",
                f"mandate-ref:{assessment.mandate_id}",
                f"assessment-ref:{assessment.assessment_id}",
                f"assessor-instance:{assessment.assessor_version}",
                f"disposition:{assessment.disposition.value}",
            ),
        )

    @staticmethod
    def _requires_write_effect(assessment: SrlRelevanceAssessment) -> bool:
        # Conservative stub: CREATE_TASK proposals require write capability because
        # they intend to create work; INVESTIGATE is treated as read-only.
        return assessment.disposition is SrlRelevanceDisposition.CREATE_TASK
