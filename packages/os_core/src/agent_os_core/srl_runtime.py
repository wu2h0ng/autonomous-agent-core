from __future__ import annotations

from datetime import datetime, timezone

from agent_os_contracts import (
    AgentInstanceRef,
    EnvironmentBinding,
    ProposedGoal,
    SrlEnvironmentEvent,
    SrlHelpRequest,
    SrlHelpResponse,
    SrlRelevanceAssessment,
    SrlRelevanceDisposition,
)

from .errors import SituationalTrustDenied
from .srl_ports import (
    ActivationAuthority,
    AssessorPort,
    AuditPort,
    AuditTransition,
    BudgetEnforcementPort,
    EventLedgerPort,
    GoalFormationPort,
    HelpDispatchPort,
    HelpDispatchResult,
    MandateRegistryPort,
    OutcomeAcceptanceResult,
    OutcomeAcceptorPort,
    SrlEvaluationResult,
    TaskActivationPort,
    TaskActivationResult,
    TrustedOutcomeRecord,
    content_digest,
)


class SrlRuntime:
    """Minimal fail-closed Situated Responsibility Loop Runtime (M0).

    M0 consumes ratified Mandate/SRL contracts and produces bounded,
    authority-audited work decisions. It has no persistence, no provider calls,
    and no TaskService integration. All authority transitions are recorded via
    the injected ``AuditPort``.
    """

    def __init__(
        self,
        *,
        event_ledger: EventLedgerPort,
        mandate_registry: MandateRegistryPort,
        assessor_port: AssessorPort,
        goal_formation: GoalFormationPort,
        budget_enforcement: BudgetEnforcementPort,
        help_dispatch: HelpDispatchPort,
        task_activation: TaskActivationPort,
        outcome_acceptor: OutcomeAcceptorPort,
        audit_port: AuditPort,
        runtime_instance_ref: AgentInstanceRef,
    ) -> None:
        self._event_ledger = event_ledger
        self._mandate_registry = mandate_registry
        self._assessor = assessor_port
        self._goal_formation = goal_formation
        self._budget = budget_enforcement
        self._help = help_dispatch
        self._task_activation = task_activation
        self._outcome = outcome_acceptor
        self._audit = audit_port
        self._runtime_instance = runtime_instance_ref
        self._clock = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def evaluate_event(
        self,
        event: SrlEnvironmentEvent,
        *,
        binding: EnvironmentBinding | None = None,
    ) -> SrlEvaluationResult:
        """Evaluate a single environment event inside the Mandate envelope.

        This method is side-effect free except for durable audit logging and
        optional binding-budget consumption.
        """
        self._record_transition("EVENT_RECEIVED", event.event_id, "evaluating")

        # 1. Deduplicate / record event.
        receipt = self._event_ledger.append(event)
        if receipt.status == "DUPLICATE":
            self._record_transition("EVENT_DEDUPLICATED", event.event_id, "duplicate")
            return SrlEvaluationResult(
                result_class="IGNORE",
                event_id=event.event_id,
                halt_reason="duplicate dedupe_key",
            )
        if receipt.status == "REJECTED":
            self._record_transition("EVENT_REJECTED", event.event_id, "rejected")
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason="event ledger rejected the event",
            )

        # 2. Binding budget check (I-13).
        if binding is not None:
            budget_status = self._budget.check_binding_budget(binding)
            if budget_status.status in {"EXHAUSTED", "HALTED"}:
                reason = f"binding budget {budget_status.status}"
                self._record_transition("BUDGET_HALTED", event.event_id, reason)
                return SrlEvaluationResult(
                    result_class="BUDGET_HALT",
                    event_id=event.event_id,
                    halt_reason=reason,
                )

        # 3. Resolve current ratified mission (I-4, I-16).
        try:
            mission = self._mandate_registry.current_ratified_mission(event.mandate_id)
        except SituationalTrustDenied as exc:
            self._record_transition("MISSION_REJECTED", event.event_id, str(exc))
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason=f"mission rejected: {exc}",
            )

        # 4. Produce relevance assessment (I-8 validated below).
        assessment = self._assessor.assess(event, mission)

        # 5. Validate assessor policy digest (I-8).
        expected_policy_digest = self._mandate_registry.expected_assessor_policy_digest(
            event.mandate_id
        )
        if assessment.assessor_policy_digest != expected_policy_digest:
            self._record_transition(
                "ASSESSOR_POLICY_MISMATCH",
                event.event_id,
                "assessor_policy_digest mismatch",
            )
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
                halt_reason="assessor policy digest mismatch",
            )

        self._record_transition(
            "ASSESSMENT_PRODUCED",
            event.event_id,
            assessment.disposition.value,
            authority_instance_id=getattr(self._assessor, "instance_id", "unknown"),
        )

        # 6. Route by disposition.
        disposition = assessment.disposition
        if disposition in {
            SrlRelevanceDisposition.IGNORE,
            SrlRelevanceDisposition.ABSTAIN,
        }:
            return SrlEvaluationResult(
                result_class="IGNORE",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
            )

        if disposition == SrlRelevanceDisposition.OBSERVE:
            return SrlEvaluationResult(
                result_class="OBSERVE",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
            )

        if disposition == SrlRelevanceDisposition.HELP:
            # Caller is expected to call emit_help_request separately.
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
            )

        if disposition == SrlRelevanceDisposition.INVESTIGATE:
            return SrlEvaluationResult(
                result_class="INVESTIGATE",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
            )

        if disposition == SrlRelevanceDisposition.CREATE_TASK:
            return SrlEvaluationResult(
                result_class="PROPOSED_GOAL",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
            )

        # Unknown disposition -> ABSTAIN (fail-closed).
        self._record_transition(
            "UNKNOWN_DISPOSITION", event.event_id, disposition.value
        )
        return SrlEvaluationResult(
            result_class="IGNORE",
            event_id=event.event_id,
            assessment_id=assessment.assessment_id,
            halt_reason="unknown disposition treated as ABSTAIN",
        )

    def propose_goal(self, assessment: SrlRelevanceAssessment) -> ProposedGoal:
        """Turn an INVESTIGATE/CREATE_TASK assessment into a ProposedGoal.

        Proposal only; activation requires a separate authority record.
        """
        mission = self._mandate_registry.current_ratified_mission(assessment.mandate_id)
        expected_digest = self._mandate_registry.expected_assessor_policy_digest(
            assessment.mandate_id
        )
        if assessment.assessor_policy_digest != expected_digest:
            raise SituationalTrustDenied("assessor policy digest mismatch")
        proposed_goal = self._goal_formation.form_goal(assessment, mission)
        self._record_transition(
            "GOAL_PROPOSED",
            assessment.assessment_id,
            proposed_goal.proposal_goal_id,
        )
        return proposed_goal

    def activate_goal(
        self,
        proposed_goal: ProposedGoal,
        authority: ActivationAuthority,
    ) -> TaskActivationResult:
        """Promote a ProposedGoal to a Task after authority checks.

        The authority record must come from an instance distinct from the one
        that produced the source assessment (I-23).
        """
        # I-23: producer cannot be acceptor.
        producer_instance_id = self._extract_producer_instance_id(proposed_goal)
        if (
            producer_instance_id
            and authority.authority_instance_id == producer_instance_id
        ):
            self._record_transition(
                "ACTIVATION_REJECTED",
                proposed_goal.proposal_goal_id,
                "same instance produced assessment and authority",
            )
            return TaskActivationResult(
                activated=False,
                rejection_reason="I-23: same instance cannot produce and accept evidence",
            )

        result = self._task_activation.activate(proposed_goal, authority)
        self._record_transition(
            "GOAL_ACTIVATED" if result.activated else "ACTIVATION_REJECTED",
            proposed_goal.proposal_goal_id,
            result.task_id or result.rejection_reason or "",
            authority_instance_id=authority.authority_instance_id,
        )
        return result

    def emit_help_request(self, help_request: SrlHelpRequest) -> HelpDispatchResult:
        """Create a typed help request and charge the separate help budget."""
        # Help burden computed by ledger, not dispatcher (I-21).
        burden_receipt = self._budget.charge_help(help_request)
        result = self._help.emit(help_request)
        # HelpDispatchResult is immutable; reconstruct with the ledger receipt.
        result = HelpDispatchResult(
            emitted=result.emitted,
            resolved=result.resolved,
            help_request_id=result.help_request_id,
            burden_receipt=burden_receipt,
            rejection_reason=result.rejection_reason,
        )
        self._record_transition(
            "HELP_REQUEST_EMITTED",
            help_request.help_request_id,
            burden_receipt.status,
        )
        return result

    def resolve_help_request(self, response: SrlHelpResponse) -> HelpDispatchResult:
        """Resolve a help request with a typed authority record."""
        result = self._help.resolve(response)
        self._record_transition(
            "HELP_REQUEST_RESOLVED" if result.resolved else "HELP_RESOLUTION_REJECTED",
            response.help_request_id,
            response.response_kind.value,
        )
        return result

    def accept_outcome(
        self,
        outcome_record: TrustedOutcomeRecord,
    ) -> OutcomeAcceptanceResult:
        """Accept an outcome only when signed by the trusted evaluator registry."""
        result = self._outcome.accept(outcome_record)
        self._record_transition(
            "OUTCOME_ACCEPTED" if result.accepted else "OUTCOME_REJECTED",
            outcome_record.record_id,
            result.rejection_reason or "accepted",
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_transition(
        self,
        transition_class: str,
        from_state: str,
        to_state: str,
        *,
        authority_instance_id: str | None = None,
    ) -> None:
        transition = AuditTransition(
            transition_class=transition_class,
            from_state=from_state,
            to_state=to_state,
            transition_digest=content_digest(
                {
                    "transition_class": transition_class,
                    "from_state": from_state,
                    "to_state": to_state,
                    "timestamp": self._clock.isoformat(),
                }
            ),
            timestamp=self._clock,
            authority_instance_id=authority_instance_id
            or self._runtime_instance.instance_id,
            provenance=(f"runtime:{self._runtime_instance.instance_id}",),
        )
        self._audit.record(transition)

    @staticmethod
    def _extract_producer_instance_id(proposed_goal: ProposedGoal) -> str | None:
        """Extract the assessment producer instance id from proposal constraints."""
        for constraint in proposed_goal.constraints:
            if constraint.startswith("assessor-instance:"):
                return constraint.split(":", 1)[1]
        return None
