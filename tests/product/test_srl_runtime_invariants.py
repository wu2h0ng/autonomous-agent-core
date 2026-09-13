from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_os_contracts import (
    AgentInstanceRef,
    EnvironmentBinding,
    EnvironmentBindingMode,
    EvaluationPrinciple,
    HelpBudget,
    HelpClass,
    Mandate,
    MandateEnvelope,
    MandateRatificationReceipt,
    MandateStatus,
    ObservedOutcome,
    OutcomeStatus,
    ProposedGoal,
    SrlEnvironmentEvent,
    SrlHelpRequest,
    SrlHelpResponse,
    SrlHelpResponseKind,
    SrlRelevanceAssessment,
    SrlRelevanceDisposition,
    StandingMission,
    content_digest,
)

from agent_os_core.errors import SituationalTrustDenied
from agent_os_core.srl_assessor import FixedAssessor
from agent_os_core.srl_audit import InMemoryAuditLog
from agent_os_core.srl_budget_ledger import InMemoryBudgetLedger
from agent_os_core.srl_event_ledger import InMemoryEventLedger
from agent_os_core.srl_goal_formation import SrlGoalFormation
from agent_os_core.srl_help_dispatch import InMemoryHelpDispatch
from agent_os_core.srl_mandate_registry import InMemoryMandateRegistry
from agent_os_core.srl_outcome_acceptor import InMemoryOutcomeAcceptor
from agent_os_core.srl_ports import (
    ActivationAuthority,
    TrustedOutcomeRecord,
)
from agent_os_core.srl_runtime import SrlRuntime
from agent_os_core.srl_task_activation import InMemoryTaskActivation


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.fixture
def runtime_instance(now):
    return AgentInstanceRef(
        instance_id="runtime-instance-1",
        implementation_id="agent-os-core",
        implementation_version="m0",
        tenant_id="t-1",
        workspace_id="w-1",
        created_at=now,
    )


@pytest.fixture
def assessor_instance(now):
    return AgentInstanceRef(
        instance_id="assessor-instance-1",
        implementation_id="fixed-assessor",
        implementation_version="v1",
        tenant_id="t-1",
        workspace_id="w-1",
        created_at=now,
    )


@pytest.fixture
def authority_instance(now):
    return AgentInstanceRef(
        instance_id="authority-instance-1",
        implementation_id="test-authority",
        implementation_version="v1",
        tenant_id="t-1",
        workspace_id="w-1",
        created_at=now,
    )


@pytest.fixture
def help_budget():
    return HelpBudget(
        max_requests_per_window=1,
        max_operator_minutes_per_window=10,
        max_repeated_question_rate=0.5,
        max_unresolved_wait_seconds=300,
        window_seconds=3600,
    )


@pytest.fixture
def mandate_envelope(help_budget):
    return MandateEnvelope(
        allowed_task_classes=("taskclass.A",),
        allowed_effect_classes=("effect.read",),
        allowed_resource_refs=(),
        capability_grant_rules=("rule.1",),
        wake_budget_per_window=3,
        query_budget_per_window=3,
        help_budget=help_budget,
        max_concurrent_tasks=1,
        max_duration_seconds=3600,
        evaluation_principles=(
            EvaluationPrinciple(
                principle_id="p1", statement="minimize operator load", weight=1.0
            ),
        ),
        escalation_conditions=("escalation.1",),
    )


@pytest.fixture
def mandate(mandate_envelope, now):
    return Mandate(
        mandate_id="mandate-1",
        tenant_id="t-1",
        workspace_id="w-1",
        principal_id="founder",
        status=MandateStatus.ACTIVE,
        mission_statement="test mission",
        desired_outcomes=("outcome.1",),
        permanent_constraints=("constraint.1",),
        authority_envelope=mandate_envelope,
        environment_binding_classes=("binding.git",),
        time_horizon="1d",
        review_cadence_seconds=3600,
        expires_at=now + timedelta(days=1),
        correction_epoch=0,
        revocation_conditions=("revoke.1",),
        created_at=now,
        ratified_at=now,
    )


@pytest.fixture
def ratification_receipt(mandate, now):
    return MandateRatificationReceipt(
        receipt_id="receipt-1",
        mandate_id=mandate.mandate_id,
        mandate_digest=content_digest(mandate),
        principal_attestation="founder-attestation",
        agent_instance_ref_id="agent-1",
        initial_correction_epoch=0,
        ratified_at=now,
    )


@pytest.fixture
def standing_mission(mandate, now):
    return StandingMission(
        standing_mission_id="mission-1",
        mandate_id=mandate.mandate_id,
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        statement="standing mission",
        outcome_criteria_refs=("oc.1",),
        review_cadence_seconds=3600,
        projected_at=now,
        expires_at=mandate.expires_at,
        parent_mandate_digest=content_digest(mandate),
        correction_epoch=0,
        ratification_receipt_digest="sha256:receipt",
    )


@pytest.fixture
def binding(mandate):
    return EnvironmentBinding(
        binding_id="binding-1",
        mandate_id=mandate.mandate_id,
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        source_type="git",
        source_scope="repo://test",
        mode=EnvironmentBindingMode.POLL,
        cursor_type="sha256",
        freshness_seconds=60,
        read_capability_id="cap.read",
        write_capability_id=None,
        wake_budget_per_window=3,
        query_budget_per_window=3,
        dedupe_key_fields=("event_id",),
        secret_policy="no-secret",
    )


@pytest.fixture
def write_binding(binding):
    return binding.model_copy(update={"write_capability_id": "cap.write"})


@pytest.fixture
def event(binding, now):
    return SrlEnvironmentEvent(
        event_id="event-1",
        binding_id=binding.binding_id,
        mandate_id=binding.mandate_id,
        tenant_id=binding.tenant_id,
        workspace_id=binding.workspace_id,
        source_cursor="cursor-1",
        occurred_at=now,
        received_at=now,
        event_class="push",
        payload_digest="sha256:payload",
        dedupe_key="dedupe-1",
        provenance=(),
    )


@pytest.fixture
def make_runtime(
    mandate,
    ratification_receipt,
    standing_mission,
    binding,
    runtime_instance,
    assessor_instance,
):
    def _make(
        disposition=SrlRelevanceDisposition.OBSERVE,
        allow_activation=False,
        register_binding=True,
    ):
        event_ledger = InMemoryEventLedger()
        mandate_registry = InMemoryMandateRegistry()
        mandate_registry.ratify_mandate(mandate, ratification_receipt)
        mandate_registry.register_mission(standing_mission)
        if register_binding:
            mandate_registry.register_binding(binding)

        def factory(event, mission):
            now = datetime.now(timezone.utc)
            return SrlRelevanceAssessment(
                assessment_id=f"assessment:{event.event_id}",
                mandate_id=event.mandate_id,
                standing_mission_id=mission.standing_mission_id,
                trigger_event_id=event.event_id,
                evidence_refs=("evidence://event",),
                uncertainty_summary="fixed",
                urgency="MEDIUM",
                proposed_attention_budget_seconds=60,
                disposition=disposition,
                confidence=0.5,
                false_positive_recorded=disposition
                in {
                    SrlRelevanceDisposition.INVESTIGATE,
                    SrlRelevanceDisposition.CREATE_TASK,
                },
                assessor_version=assessor_instance.instance_id,
                assessor_policy_digest="sha256:assessor-policy",
                proposed_goal_statement="do something"
                if disposition
                in {
                    SrlRelevanceDisposition.INVESTIGATE,
                    SrlRelevanceDisposition.CREATE_TASK,
                }
                else None,
                minimum_external_input="need input"
                if disposition == SrlRelevanceDisposition.HELP
                else None,
                proposed_task_class="taskclass.A"
                if disposition == SrlRelevanceDisposition.CREATE_TASK
                else None,
                assessed_at=now,
            )

        assessor = FixedAssessor(
            instance_id=assessor_instance.instance_id,
            policy_digest="sha256:assessor-policy",
            factory=factory,
        )
        goal_formation = SrlGoalFormation()
        budget_ledger = InMemoryBudgetLedger()
        budget_ledger.set_help_budget(
            mandate.mandate_id, mandate.authority_envelope.help_budget
        )
        help_dispatch = InMemoryHelpDispatch()
        task_activation = InMemoryTaskActivation(allow_activation=allow_activation)
        outcome_acceptor = InMemoryOutcomeAcceptor()
        audit_log = InMemoryAuditLog()

        return SrlRuntime(
            event_ledger=event_ledger,
            mandate_registry=mandate_registry,
            assessor_port=assessor,
            goal_formation=goal_formation,
            budget_enforcement=budget_ledger,
            help_dispatch=help_dispatch,
            task_activation=task_activation,
            outcome_acceptor=outcome_acceptor,
            audit_port=audit_log,
            runtime_instance_ref=runtime_instance,
        )

    return _make


# ---------------------------------------------------------------------------
# V0/V1 contract invariants are tested elsewhere; below focus on RT invariants.
# ---------------------------------------------------------------------------


def test_i4_standing_mission_parent_digest_mismatch(
    make_runtime, mandate, standing_mission, ratification_receipt, event
):
    """I-4: Runtime rejects StandingMission whose parent digest does not match current Mandate."""
    runtime = make_runtime()
    # Tamper with the mandate after mission registration.
    registry = runtime._mandate_registry
    bad_mandate = mandate.model_copy(update={"mission_statement": "tampered"})
    bad_receipt = ratification_receipt.model_copy(
        update={"mandate_digest": content_digest(bad_mandate)}
    )
    registry._mandates[mandate.mandate_id] = bad_mandate
    registry._receipts[mandate.mandate_id] = bad_receipt

    result = runtime.evaluate_event(event)
    assert result.result_class == "HELP"
    assert "parent digest mismatch" in (result.halt_reason or "").lower()


def test_i8_assessor_policy_digest_mismatch(make_runtime, event):
    """I-8: Runtime rejects assessment with mismatched assessor policy digest."""
    runtime = make_runtime()
    # Override the expected policy digest in the registry.
    runtime._mandate_registry._assessor_policy_digests[event.mandate_id] = (
        "sha256:wrong-policy"
    )
    result = runtime.evaluate_event(event)
    assert result.result_class == "HELP"
    assert "assessor policy digest mismatch" in (result.halt_reason or "").lower()


def test_i11_help_burden_exceeded(make_runtime, event):
    """I-11: HelpBurdenReceipt flips to EXCEEDED when budget crossed."""
    runtime = make_runtime(disposition=SrlRelevanceDisposition.HELP)
    runtime.evaluate_event(event)
    help_request = SrlHelpRequest(
        help_request_id="help-1",
        mandate_id=event.mandate_id,
        standing_mission_id="mission-1",
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="confirm scope",
        continuable_work=("wait",),
        requested_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate to founder",
    )
    r1 = runtime.emit_help_request(help_request)
    assert r1.burden_receipt is not None
    assert r1.burden_receipt.status == "WITHIN_BUDGET"

    help_request2 = help_request.model_copy(
        update={"help_request_id": "help-2", "minimum_answer": "confirm scope 2"}
    )
    r2 = runtime.emit_help_request(help_request2)
    assert r2.burden_receipt.status == "EXCEEDED"


def test_i12_duplicate_event_deduped(make_runtime, event):
    """I-12: Duplicate dedupe_key within a binding is rejected or idempotent."""
    runtime = make_runtime()
    r1 = runtime.evaluate_event(event)
    r2 = runtime.evaluate_event(event)
    assert r1.result_class == "OBSERVE"
    assert r2.result_class == "IGNORE"
    assert "duplicate" in (r2.halt_reason or "").lower()


def test_i13_binding_budget_exhausted(make_runtime, event, binding):
    """I-13: Exceeding wake/query budget stops event processing and emits BUDGET_HALT."""
    runtime = make_runtime()
    # Consume the wake budget externally.
    for _ in range(binding.wake_budget_per_window):
        runtime._budget.consume_wake(binding.binding_id)
    result = runtime.evaluate_event(event, binding=binding)
    assert result.result_class == "BUDGET_HALT"


def test_i14_no_capability_grant_from_srl_organ():
    """I-14: No SRL organ can create ActionPermit, CapabilityGrant or ActionReceipt."""
    port = InMemoryTaskActivation(allow_activation=True)
    goal = ProposedGoal(
        proposal_goal_id="goal-1",
        source_binding_digest="a" * 64,
        tenant_id="t-1",
        workspace_id="w-1",
        created_by="srl-goal-formation:v1",
        created_at=datetime.now(timezone.utc),
        statement="x",
        constraints=("capability-grant:foo",),
    )
    authority = ActivationAuthority(
        authority_id="auth-1",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        authority_instance_id="authority-1",
        source_assessment_id="a-1",
        source_proposed_goal_id="goal-1",
        authorization_digest="sha256:auth",
        authorized_at=datetime.now(timezone.utc),
    )
    result = port.activate(goal, authority)
    assert not result.activated
    assert "CapabilityGrant" in (result.rejection_reason or "")


def test_p0_allow_activation_flag_cannot_accept_caller_minted_authority(now):
    """P0-1: a local boolean cannot stand in for TaskService/C7 authority."""
    port = InMemoryTaskActivation(allow_activation=True)
    goal = ProposedGoal(
        proposal_goal_id="goal-caller-minted",
        source_binding_digest="a" * 64,
        tenant_id="t-1",
        workspace_id="w-1",
        created_by="srl-goal-formation:v1",
        created_at=now,
        statement="caller-proposed goal",
        constraints=("assessor-instance:assessor-instance-1",),
    )
    caller_authority = ActivationAuthority(
        authority_id="auth-caller-minted",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        authority_instance_id="authority-instance-1",
        source_assessment_id="assessment:event-1",
        source_proposed_goal_id=goal.proposal_goal_id,
        authorization_digest="arbitrary-nonempty-digest",
        authorized_at=now,
    )

    result = port.activate(goal, caller_authority)

    assert not result.activated
    assert "TaskService/C7" in (result.rejection_reason or "")


def test_p0_runtime_rejects_mismatched_authority_without_producer_metadata(
    make_runtime, now
):
    """P0-1: removing producer metadata cannot admit a wholly mismatched authority."""
    runtime = make_runtime(allow_activation=True)
    goal_without_producer = ProposedGoal(
        proposal_goal_id="goal-without-producer",
        source_binding_digest="b" * 64,
        tenant_id="t-1",
        workspace_id="w-1",
        created_by="srl-goal-formation:v1",
        created_at=now,
        statement="goal with caller-removed producer metadata",
        constraints=(),
    )
    mismatched_authority = ActivationAuthority(
        authority_id="auth-mismatched",
        mandate_id="wrong-mandate",
        standing_mission_id="wrong-mission",
        authority_instance_id="assessor-instance-1",
        source_assessment_id="wrong-assessment",
        source_proposed_goal_id="wrong-goal",
        authorization_digest="arbitrary-nonempty-digest",
        authorized_at=now,
    )

    result = runtime.activate_goal(goal_without_producer, mismatched_authority)

    assert not result.activated
    # I-23 now fails closed when producer identity is absent.
    assert "producer identity unavailable" in (result.rejection_reason or "")


def test_i15_untrusted_outcome_rejected(make_runtime, mandate, standing_mission, now):
    """I-15: Outcome updates require trusted ObservedOutcome record."""
    runtime = make_runtime()
    observed = ObservedOutcome(
        observed_outcome_id="out-1",
        expected_outcome_id="expected-1",
        task_id="task-1",
        run_id="run-1",
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        evaluator_type="deterministic",
        evaluator_version="v1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("evidence://test",),
        observed_at=now,
    )
    record = TrustedOutcomeRecord(
        record_id="rec-1",
        mandate_id=mandate.mandate_id,
        standing_mission_id=standing_mission.standing_mission_id,
        task_id="task-1",
        observed_outcome=observed,
        evaluator_registry_instance_id="untrusted-registry",
        registry_signature_digest="sha256:sig",
        recorded_at=now,
    )
    result = runtime.accept_outcome(record)
    assert not result.accepted
    assert "trusted evaluator registry" in (result.rejection_reason or "").lower()


def test_p0_public_registry_id_and_arbitrary_digest_cannot_trust_outcome(
    make_runtime, mandate, standing_mission, now
):
    """P0-2: a caller-controlled registry ID and non-empty digest are not trust."""
    runtime = make_runtime()
    runtime._outcome.trust_registry("caller-whitelisted-registry")
    observed = ObservedOutcome(
        observed_outcome_id="out-forged-signature",
        expected_outcome_id="expected-1",
        task_id="task-1",
        run_id="run-1",
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        evaluator_type="deterministic",
        evaluator_version="v1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("evidence://forged",),
        observed_at=now,
    )
    forged = TrustedOutcomeRecord(
        record_id="rec-forged-signature",
        mandate_id=mandate.mandate_id,
        standing_mission_id=standing_mission.standing_mission_id,
        task_id=observed.task_id,
        observed_outcome=observed,
        evaluator_registry_instance_id="caller-whitelisted-registry",
        registry_signature_digest="arbitrary-nonempty-text",
        recorded_at=now,
    )

    result = runtime.accept_outcome(forged)

    assert not result.accepted
    assert "no trusted evaluator registry" in (result.rejection_reason or "").lower()


def test_p0_forged_outcome_with_outer_inner_binding_mismatch_is_rejected(
    make_runtime, mandate, now
):
    """P0-2: outer mandate/mission/task fields cannot disguise a cross-task record."""
    runtime = make_runtime()
    runtime._outcome.trust_registry("caller-whitelisted-registry")
    observed = ObservedOutcome(
        observed_outcome_id="out-cross-task",
        expected_outcome_id="expected-1",
        task_id="inner-task",
        run_id="run-1",
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        evaluator_type="deterministic",
        evaluator_version="v1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("evidence://forged",),
        observed_at=now,
    )
    forged = TrustedOutcomeRecord(
        record_id="rec-cross-task",
        mandate_id="wrong-mandate",
        standing_mission_id="wrong-mission",
        task_id="outer-task",
        observed_outcome=observed,
        evaluator_registry_instance_id="caller-whitelisted-registry",
        registry_signature_digest="arbitrary-nonempty-text",
        recorded_at=now,
    )

    result = runtime.accept_outcome(forged)

    assert not result.accepted
    assert "no trusted evaluator registry" in (result.rejection_reason or "").lower()


def test_i16_mandate_not_active_rejected(
    make_runtime, mandate, standing_mission, event
):
    """I-16: StandingMission rejected if Mandate not RATIFIED/ACTIVE or expired."""
    runtime = make_runtime()
    runtime._mandate_registry._mandates[mandate.mandate_id] = mandate.model_copy(
        update={"status": MandateStatus.SUSPENDED}
    )
    result = runtime.evaluate_event(event)
    assert result.result_class == "HELP"
    assert "mandate is not ratified or active" in (result.halt_reason or "").lower()


def test_i18_read_only_binding_rejects_write_effect(make_runtime, event):
    """I-18: Read-only binding rejects write-effect proposal."""
    runtime = make_runtime(disposition=SrlRelevanceDisposition.CREATE_TASK)
    result = runtime.evaluate_event(event)
    assert result.result_class == "PROPOSED_GOAL"
    with pytest.raises(SituationalTrustDenied):
        runtime.propose_goal(
            SrlRelevanceAssessment(
                assessment_id="a-1",
                mandate_id=event.mandate_id,
                standing_mission_id="mission-1",
                trigger_event_id=event.event_id,
                evidence_refs=("evidence://test",),
                uncertainty_summary="x",
                urgency="HIGH",
                proposed_attention_budget_seconds=60,
                disposition=SrlRelevanceDisposition.CREATE_TASK,
                confidence=0.9,
                false_positive_recorded=True,
                assessor_version="assessor-instance-1",
                assessor_policy_digest="sha256:assessor-policy",
                proposed_goal_statement="write something",
                proposed_task_class="taskclass.A",
                assessed_at=datetime.now(timezone.utc),
            )
        )


def test_i20_after_help_expiry_only_continuable_work(make_runtime, now):
    """I-20: After SrlHelpRequest expires, only continuable_work may continue."""
    runtime = make_runtime()
    help_request = SrlHelpRequest(
        help_request_id="help-expired",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        tenant_id="t-1",
        workspace_id="w-1",
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="x",
        continuable_work=("wait",),
        requested_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=1),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate to founder",
    )
    runtime.emit_help_request(help_request)
    # An OPERATOR_DECISION after expiry should be rejected; only CANCELLATION/REVOCATION allowed.
    bad_response = SrlHelpResponse(
        help_request_id="help-expired",
        response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
        decision="APPROVE",
        responded_at=now,
        responder_principal_id="operator-1",
    )
    result = runtime.resolve_help_request(bad_response)
    assert not result.resolved
    assert "expiry" in (result.rejection_reason or "").lower()


def test_i21_help_burden_computed_by_separate_ledger(make_runtime, event):
    """I-21: HelpBurdenReceipt is computed by budget ledger separate from emitter."""
    runtime = make_runtime(disposition=SrlRelevanceDisposition.HELP)
    runtime.evaluate_event(event)
    help_request = SrlHelpRequest(
        help_request_id="help-ledger",
        mandate_id=event.mandate_id,
        standing_mission_id="mission-1",
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="x",
        continuable_work=("wait",),
        requested_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate to founder",
    )
    result = runtime.emit_help_request(help_request)
    assert result.burden_receipt is not None
    # The dispatch port itself does not compute the receipt.
    assert runtime._help.emit(help_request).burden_receipt is None


def test_m0_has_no_public_w1_w2_mutation_entry_point():
    """M0 exposes no W1/W2 mutation entry point; future ports remain unproved."""
    assert not hasattr(SrlRuntime, "apply_w1_update")
    assert not hasattr(SrlRuntime, "apply_w2_update")


def test_i23_same_instance_cannot_propose_and_accept(
    make_runtime, event, assessor_instance, write_binding
):
    """I-23: Same instance cannot both produce assessment and emit authority record."""
    runtime = make_runtime(disposition=SrlRelevanceDisposition.CREATE_TASK)
    result = runtime.evaluate_event(event)
    assert result.result_class == "PROPOSED_GOAL"
    assessment = runtime._assessor.assess(
        event, runtime._mandate_registry.current_ratified_mission(event.mandate_id)
    )
    runtime._goal_formation.add_binding_for_event(event.event_id, write_binding)
    proposed_goal = runtime.propose_goal(assessment)
    # Authority from the same assessor instance must be rejected.
    bad_authority = ActivationAuthority(
        authority_id="auth-1",
        mandate_id=event.mandate_id,
        standing_mission_id="mission-1",
        authority_instance_id=assessor_instance.instance_id,
        source_assessment_id=assessment.assessment_id,
        source_proposed_goal_id=proposed_goal.proposal_goal_id,
        authorization_digest="sha256:auth",
        authorized_at=datetime.now(timezone.utc),
    )
    activation = runtime.activate_goal(proposed_goal, bad_authority)
    assert not activation.activated
    assert "I-23" in (activation.rejection_reason or "")


def test_same_process_in_memory_duplicate_is_idempotent(make_runtime, event):
    """M0 deduplicates replay only inside one in-memory Runtime/ledger."""
    runtime = make_runtime()
    r1 = runtime.evaluate_event(event)
    r2 = runtime.evaluate_event(event)
    assert r1.result_class == "OBSERVE"
    assert r2.result_class == "IGNORE"
    # No duplicate work should be recorded in the audit log for the second event.
    transition_classes = [t.transition_class for t in runtime._audit.transitions()]
    assert transition_classes.count("ASSESSMENT_PRODUCED") == 1


def test_unregistered_binding_fails_before_assessment_or_ledger_acceptance(
    make_runtime, event
):
    runtime = make_runtime(register_binding=False)

    result = runtime.evaluate_event(event)

    assert result.result_class == "HELP"
    assert "binding" in (result.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == ()
    assert not any(
        transition.transition_class == "ASSESSMENT_PRODUCED"
        for transition in runtime._audit.transitions()
    )


def test_registered_binding_is_authority_source_when_argument_omitted(
    make_runtime, event, binding
):
    runtime = make_runtime()
    runtime._mandate_registry.register_binding(binding)

    result = runtime.evaluate_event(event)

    assert result.result_class == "OBSERVE"


@pytest.mark.parametrize(
    "binding_update",
    [
        {"binding_id": "foreign-binding"},
        {"wake_budget_per_window": 999},
        {"source_scope": "repo://attacker"},
    ],
)
def test_caller_binding_is_only_exact_digest_assertion(
    make_runtime, event, binding, binding_update
):
    runtime = make_runtime()
    runtime._mandate_registry.register_binding(binding)
    asserted_binding = binding.model_copy(update=binding_update)

    result = runtime.evaluate_event(event, binding=asserted_binding)

    assert result.result_class == "HELP"
    assert "binding" in (result.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == ()


def test_event_scope_must_equal_registered_binding_and_current_mission(
    make_runtime, event, binding
):
    runtime = make_runtime()
    runtime._mandate_registry.register_binding(binding)
    foreign_event = event.model_copy(update={"tenant_id": "foreign-tenant"})

    result = runtime.evaluate_event(foreign_event)

    assert result.result_class == "HELP"
    assert "scope" in (result.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == ()


@pytest.mark.parametrize(
    "assessment_update, reason",
    [
        ({"mandate_id": "foreign-mandate"}, "mandate"),
        ({"standing_mission_id": "foreign-mission"}, "mission"),
        ({"trigger_event_id": "foreign-event"}, "trigger"),
        ({"assessor_version": "foreign-assessor"}, "assessor"),
    ],
)
def test_assessment_must_be_exactly_bound_before_routing(
    make_runtime, event, binding, assessment_update, reason
):
    runtime = make_runtime()
    runtime._mandate_registry.register_binding(binding)
    original_assess = runtime._assessor.assess
    runtime._assessor.assess = lambda assessed_event, mission: original_assess(
        assessed_event, mission
    ).model_copy(update=assessment_update)

    result = runtime.evaluate_event(event)

    assert result.result_class == "HELP"
    assert reason in (result.halt_reason or "").lower()
    assert not any(
        transition.transition_class == "ASSESSMENT_PRODUCED"
        for transition in runtime._audit.transitions()
    )


def test_event_assessment_rejects_non_null_trigger_gap_before_ledger_acceptance(
    make_runtime, event
):
    runtime = make_runtime()
    original_assess = runtime._assessor.assess
    runtime._assessor.assess = lambda assessed_event, mission: original_assess(
        assessed_event, mission
    ).model_copy(update={"trigger_gap_id": "foreign-gap"})

    result = runtime.evaluate_event(event)

    assert result.result_class == "HELP"
    assert "trigger gap" in (result.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == ()


def test_mismatched_assessment_does_not_poison_valid_retry(make_runtime, event):
    runtime = make_runtime()
    original_assess = runtime._assessor.assess
    calls = [0]

    def mismatch_once(assessed_event, mission):
        calls[0] += 1
        assessment = original_assess(assessed_event, mission)
        if calls[0] == 1:
            return assessment.model_copy(update={"assessor_version": "foreign-assessor"})
        return assessment

    runtime._assessor.assess = mismatch_once

    rejected = runtime.evaluate_event(event)
    assert runtime._event_ledger.list_events(event.binding_id) == ()
    accepted = runtime.evaluate_event(event)

    assert rejected.result_class == "HELP"
    assert runtime._event_ledger.list_events(event.binding_id) == (event,)
    assert accepted.result_class == "OBSERVE"
    assert calls[0] == 2


def test_assessor_exception_does_not_poison_valid_retry(make_runtime, event):
    runtime = make_runtime()
    original_assess = runtime._assessor.assess
    calls = [0]

    def raise_once(assessed_event, mission):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("assessor unavailable")
        return original_assess(assessed_event, mission)

    runtime._assessor.assess = raise_once

    rejected = runtime.evaluate_event(event)
    assert rejected.result_class == "HELP"
    assert "assessor failed" in (rejected.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == ()

    accepted = runtime.evaluate_event(event)

    assert accepted.result_class == "OBSERVE"
    assert runtime._event_ledger.list_events(event.binding_id) == (event,)
    assert calls[0] == 2


def test_race_time_duplicate_append_is_idempotent_ignore(make_runtime, event):
    runtime = make_runtime()
    original_append = runtime._event_ledger.append

    def lose_append_race(raced_event):
        original_append(raced_event)
        return original_append(raced_event)

    runtime._event_ledger.append = lose_append_race

    result = runtime.evaluate_event(event)

    assert result.result_class == "IGNORE"
    assert "duplicate" in (result.halt_reason or "").lower()
    assert runtime._event_ledger.list_events(event.binding_id) == (event,)


def test_binding_registration_is_idempotent_but_rejects_digest_change(
    mandate, ratification_receipt, binding
):
    registry = InMemoryMandateRegistry()
    registry.ratify_mandate(mandate, ratification_receipt)

    registry.register_binding(binding)
    registry.register_binding(binding.model_copy())

    with pytest.raises(SituationalTrustDenied, match="digest"):
        registry.register_binding(
            binding.model_copy(update={"source_scope": "repo://different"})
        )
    assert registry.authorized_binding(binding.binding_id) == binding


def test_help_authority_rejects_backdated_response_after_expiry(now):
    current = [now]
    dispatch = InMemoryHelpDispatch(clock=lambda: current[0])
    request = SrlHelpRequest(
        help_request_id="help-live-clock",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        tenant_id="t-1",
        workspace_id="w-1",
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="approve?",
        continuable_work=("wait",),
        requested_at=now,
        expires_at=now + timedelta(seconds=1),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate",
    )
    assert dispatch.emit(request).emitted
    current[0] = now + timedelta(seconds=2)
    response = SrlHelpResponse(
        help_request_id=request.help_request_id,
        response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
        decision="APPROVE",
        responded_at=now,
        responder_principal_id="operator-1",
    )

    result = dispatch.resolve(response)

    assert not result.resolved
    assert "expiry" in (result.rejection_reason or "").lower()


def test_help_authority_rejects_response_timestamp_after_expiry(now):
    dispatch = InMemoryHelpDispatch(clock=lambda: now)
    request = SrlHelpRequest(
        help_request_id="help-response-time",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        tenant_id="t-1",
        workspace_id="w-1",
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="approve?",
        continuable_work=("wait",),
        requested_at=now - timedelta(seconds=2),
        expires_at=now + timedelta(seconds=1),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate",
    )
    dispatch.emit(request)
    response = SrlHelpResponse(
        help_request_id=request.help_request_id,
        response_kind=SrlHelpResponseKind.CAPABILITY_GRANT,
        capability_grant_id="grant-1",
        responded_at=now + timedelta(seconds=2),
        responder_principal_id="operator-1",
    )

    result = dispatch.resolve(response)

    assert not result.resolved
    assert "expiry" in (result.rejection_reason or "").lower()


def test_help_budget_exceeded_prevents_dispatch(make_runtime, event):
    runtime = make_runtime(disposition=SrlRelevanceDisposition.HELP)
    request = SrlHelpRequest(
        help_request_id="help-first",
        mandate_id=event.mandate_id,
        standing_mission_id="mission-1",
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        help_class=HelpClass.INFORMATION,
        unsafe_boundary="operator input required",
        minimum_answer="first",
        continuable_work=("wait",),
        requested_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        cancellation_policy="cancel on expiry",
        escalation_policy="escalate",
    )
    assert runtime.emit_help_request(request).emitted

    result = runtime.emit_help_request(
        request.model_copy(
            update={"help_request_id": "help-exceeded", "minimum_answer": "second"}
        )
    )

    assert result.burden_receipt is not None
    assert result.burden_receipt.status == "EXCEEDED"
    assert not result.emitted
    assert "exceeded" in (result.rejection_reason or "").lower()
    assert "help-exceeded" not in runtime._help._requests


def test_wake_budget_allows_exactly_n_wakes_and_ignores_unused_zero_query(binding):
    ledger = InMemoryBudgetLedger()
    exact_two = binding.model_copy(
        update={"wake_budget_per_window": 2, "query_budget_per_window": 0}
    )

    first = ledger.check_binding_budget(exact_two)
    second = ledger.check_binding_budget(exact_two)
    third = ledger.check_binding_budget(exact_two)

    assert first.status == "WITHIN_BUDGET"
    assert second.status == "WITHIN_BUDGET"
    assert third.status == "EXHAUSTED"


def test_mandate_registry_uses_live_clock_for_expiry(
    mandate, ratification_receipt, standing_mission, now
):
    current = [now]
    registry = InMemoryMandateRegistry(clock=lambda: current[0])
    registry.ratify_mandate(mandate, ratification_receipt)
    registry.register_mission(standing_mission)
    assert registry.current_ratified_mission(mandate.mandate_id) == standing_mission

    current[0] = mandate.expires_at

    with pytest.raises(SituationalTrustDenied, match="expired"):
        registry.current_ratified_mission(mandate.mandate_id)


def test_runtime_audit_transition_uses_one_live_timestamp(make_runtime, event, now):
    current = [now]
    runtime = make_runtime()
    runtime._clock = lambda: current[0]

    runtime.evaluate_event(event)
    first = runtime._audit.transitions()[0]
    assert first.timestamp == now

    current[0] = now + timedelta(seconds=1)
    runtime.evaluate_event(event)
    assert runtime._audit.transitions()[-1].timestamp == current[0]
