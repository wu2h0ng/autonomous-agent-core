from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

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
        clock: Callable[[], datetime] | None = None,
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
        self._clock = clock or (lambda: datetime.now(timezone.utc))

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

        # 1. Duplicate detection is idempotent and does not assess again.
        if self._event_ledger.get(event.binding_id, event.dedupe_key) is not None:
            self._record_transition("EVENT_DEDUPLICATED", event.event_id, "duplicate")
            return SrlEvaluationResult(
                result_class="IGNORE",
                event_id=event.event_id,
                halt_reason="duplicate dedupe_key",
            )

        # 2. Resolve binding and current mission before accepting the event.
        try:
            authorized_binding = self._mandate_registry.authorized_binding(
                event.binding_id
            )
            mission = self._mandate_registry.current_ratified_mission(event.mandate_id)
        except SituationalTrustDenied as exc:
            self._record_transition("TRUST_BINDING_REJECTED", event.event_id, str(exc))
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason=f"binding or mission rejected: {exc}",
            )

        if binding is not None and content_digest(binding) != content_digest(
            authorized_binding
        ):
            self._record_transition(
                "TRUST_BINDING_REJECTED", event.event_id, "binding digest mismatch"
            )
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason="caller binding assertion does not match authorized binding",
            )

        expected_scope = (
            authorized_binding.mandate_id,
            authorized_binding.tenant_id,
            authorized_binding.workspace_id,
        )
        if (
            event.mandate_id,
            event.tenant_id,
            event.workspace_id,
        ) != expected_scope or (
            mission.mandate_id,
            mission.tenant_id,
            mission.workspace_id,
        ) != expected_scope:
            self._record_transition(
                "TRUST_BINDING_REJECTED", event.event_id, "binding scope mismatch"
            )
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason="event, binding, and mission scope mismatch",
            )

        budget_status = self._budget.check_binding_budget(authorized_binding)
        if budget_status.status in {"EXHAUSTED", "HALTED"}:
            reason = f"binding budget {budget_status.status}"
            self._record_transition("BUDGET_HALTED", event.event_id, reason)
            return SrlEvaluationResult(
                result_class="BUDGET_HALT",
                event_id=event.event_id,
                halt_reason=reason,
            )

        # 3. Produce and validate the exact relevance assessment binding.
        try:
            assessment = self._assessor.assess(event, mission)
        except Exception as exc:
            # An assessor is proposal-only and cannot crash the public Runtime
            # entry point or poison event dedupe.  Do not echo exception text:
            # provider/adapter failures may contain sensitive context.
            reason = f"assessor failed: {type(exc).__name__}"
            self._record_transition("ASSESSOR_FAILED", event.event_id, reason)
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason=reason,
            )

        expected_policy_digest = self._mandate_registry.expected_assessor_policy_digest(
            event.mandate_id
        )
        assessment_mismatches = (
            ("mandate", assessment.mandate_id, event.mandate_id),
            (
                "standing mission",
                assessment.standing_mission_id,
                mission.standing_mission_id,
            ),
            ("trigger event", assessment.trigger_event_id, event.event_id),
            ("trigger gap", assessment.trigger_gap_id, None),
            ("assessor policy digest", assessment.assessor_policy_digest, expected_policy_digest),
            ("assessor contract policy", self._assessor.policy_digest, expected_policy_digest),
            ("assessor identity", assessment.assessor_version, self._assessor.instance_id),
        )
        mismatch = next(
            (label for label, actual, expected in assessment_mismatches if actual != expected),
            None,
        )
        if mismatch is not None:
            self._record_transition(
                "ASSESSMENT_BINDING_MISMATCH",
                event.event_id,
                f"{mismatch} mismatch",
            )
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                assessment_id=assessment.assessment_id,
                halt_reason=f"assessment {mismatch} mismatch",
            )

        # Accept only an event whose assessment was produced and exactly bound.
        # The pre-check above avoids repeat assessment in the common duplicate
        # case; the append receipt still closes a concurrent append race.
        receipt = self._event_ledger.append(event)
        if receipt.status == "DUPLICATE":
            self._record_transition("EVENT_DEDUPLICATED", event.event_id, "duplicate")
            return SrlEvaluationResult(
                result_class="IGNORE",
                event_id=event.event_id,
                halt_reason="duplicate dedupe_key",
            )
        if receipt.status != "APPENDED":
            self._record_transition("EVENT_REJECTED", event.event_id, receipt.status)
            return SrlEvaluationResult(
                result_class="HELP",
                event_id=event.event_id,
                halt_reason="event ledger rejected the event",
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
        """Delegate the ProposedGoal -> Task transition to the injected port.

        The authority record must come from an instance distinct from the one
        that produced the source assessment (I-23). The default M0 port remains
        fail-closed; a trusted gate may activate through the authority spine.
        """
        # I-23: producer cannot be acceptor. The producer identity is required;
        # its absence fails closed (it is caller-strippable metadata).
        producer_instance_id = self._extract_producer_instance_id(proposed_goal)
        if producer_instance_id is None:
            self._record_transition(
                "ACTIVATION_REJECTED",
                proposed_goal.proposal_goal_id,
                "producer identity unavailable",
            )
            return TaskActivationResult(
                activated=False,
                rejection_reason="I-23: producer identity unavailable",
            )
        if authority.authority_instance_id == producer_instance_id:
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
        if burden_receipt.status == "EXCEEDED":
            result = HelpDispatchResult(
                emitted=False,
                resolved=False,
                help_request_id=help_request.help_request_id,
                burden_receipt=burden_receipt,
                rejection_reason="help burden budget exceeded",
            )
            self._record_transition(
                "HELP_REQUEST_REJECTED",
                help_request.help_request_id,
                burden_receipt.status,
            )
            return result
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
        """Reject outcome updates until an independent evaluator registry exists."""
        # M0 cannot verify registry identity, signatures, or task/mandate binding.
        # Do not let an injected acceptor turn caller-provided strings into truth.
        result = OutcomeAcceptanceResult(
            accepted=False,
            rejection_reason="no trusted evaluator registry integration in M0",
        )
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
        now = self._clock()
        transition = AuditTransition(
            transition_class=transition_class,
            from_state=from_state,
            to_state=to_state,
            transition_digest=content_digest(
                {
                    "transition_class": transition_class,
                    "from_state": from_state,
                    "to_state": to_state,
                    "timestamp": now.isoformat(),
                }
            ),
            timestamp=now,
            authority_instance_id=authority_instance_id
            or self._runtime_instance.instance_id,
            provenance=(f"runtime:{self._runtime_instance.instance_id}",),
        )
        self._audit.record(transition)

    @staticmethod
    def _extract_producer_instance_id(proposed_goal: ProposedGoal) -> str | None:
        """Extract the assessment producer instance id from proposal constraints.

        An empty/whitespace value is treated as absent so I-23 fails closed.
        """
        for constraint in proposed_goal.constraints:
            if constraint.startswith("assessor-instance:"):
                value = constraint.split(":", 1)[1].strip()
                return value or None
        return None
