from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_os_contracts import (
    AgentInstanceRef,
    EnvironmentBinding,
    EnvironmentBindingMode,
    EvaluationPrinciple,
    HelpBudget,
    Mandate,
    MandateEnvelope,
    MandateRatificationReceipt,
    MandateStatus,
    ProposedGoal,
    SrlEnvironmentEvent,
    SrlRelevanceAssessment,
    StandingMission,
    content_digest,
)
from agent_os_core.event_store import InMemoryTaskEventStore
from agent_os_core.srl_activation_gate import (
    ActivationDenialReason,
    C7ClearanceRef,
    CreatedTask,
    TaskRequirements,
    TaskServiceCreationAdapter,
    TrustedTaskActivationGate,
)
from agent_os_core.srl_audit import InMemoryAuditLog
from agent_os_core.srl_budget_ledger import InMemoryBudgetLedger
from agent_os_core.srl_event_ledger import InMemoryEventLedger
from agent_os_core.srl_goal_formation import SrlGoalFormation
from agent_os_core.srl_help_dispatch import InMemoryHelpDispatch
from agent_os_core.srl_mandate_registry import InMemoryMandateRegistry
from agent_os_core.srl_outcome_acceptor import InMemoryOutcomeAcceptor
from agent_os_core.srl_ports import ActivationAuthority
from agent_os_core.srl_runtime import SrlRuntime
from agent_os_core.srl_task_activation import InMemoryTaskActivation
from agent_os_core.task_service import TaskService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.fixture
def mandate(now):
    envelope = MandateEnvelope(
        allowed_task_classes=("taskclass.A",),
        allowed_effect_classes=("effect.read",),
        allowed_resource_refs=(),
        capability_grant_rules=("rule.1",),
        wake_budget_per_window=3,
        query_budget_per_window=3,
        help_budget=HelpBudget(
            max_requests_per_window=1,
            max_operator_minutes_per_window=10,
            max_repeated_question_rate=0.5,
            max_unresolved_wait_seconds=300,
            window_seconds=3600,
        ),
        max_concurrent_tasks=1,
        max_duration_seconds=3600,
        evaluation_principles=(
            EvaluationPrinciple(
                principle_id="p1", statement="minimize operator load", weight=1.0
            ),
        ),
        escalation_conditions=("escalation.1",),
    )
    return Mandate(
        mandate_id="mandate-1",
        tenant_id="t-1",
        workspace_id="w-1",
        principal_id="founder",
        status=MandateStatus.ACTIVE,
        mission_statement="test mission",
        desired_outcomes=("outcome.1",),
        permanent_constraints=("constraint.1",),
        authority_envelope=envelope,
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
def mandate_registry(mandate, now):
    registry = InMemoryMandateRegistry(clock=lambda: now)
    receipt = MandateRatificationReceipt(
        receipt_id="receipt-1",
        mandate_id=mandate.mandate_id,
        mandate_digest=content_digest(mandate),
        principal_attestation="founder-attestation",
        agent_instance_ref_id="agent-1",
        initial_correction_epoch=0,
        ratified_at=now,
    )
    registry.ratify_mandate(mandate, receipt)
    registry.register_mission(
        StandingMission(
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
    )
    registry.register_binding(
        EnvironmentBinding(
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
    )
    return registry


@pytest.fixture
def goal(now):
    return ProposedGoal(
        proposal_goal_id="goal-1",
        source_binding_digest="a" * 64,
        tenant_id="t-1",
        workspace_id="w-1",
        created_by="srl-goal-formation:v1",
        created_at=now,
        statement="fix the failing test",
        constraints=(
            "mandate-ref:mandate-1",
            "assessment-ref:assessment:event-1",
            "assessor-instance:assessor-instance-1",
        ),
    )


@pytest.fixture
def authority(now):
    return ActivationAuthority(
        authority_id="auth-1",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        authority_instance_id="authority-instance-1",
        producer_instance_id="assessor-instance-1",
        source_assessment_id="assessment:event-1",
        source_proposed_goal_id="goal-1",
        authorization_digest="sha256:auth",
        authorized_at=now,
    )


class _AuthorityRegistry:
    def __init__(self, known):
        self._known = {a.authority_id: a for a in known}

    def resolve(self, authority_id):
        return self._known.get(authority_id)


class _Requirements:
    def __init__(self, value: TaskRequirements | None):
        self._value = value

    def resolve(self, proposed_goal, authority) -> TaskRequirements | None:
        return self._value


class _C7:
    def __init__(self, value: C7ClearanceRef | None):
        self._value = value

    def current_clearance(self, mandate_id: str) -> C7ClearanceRef | None:
        return self._value


class _Creation:
    def __init__(self, task_id: str | None = "task-1"):
        self._task_id = task_id
        self.calls = []

    def create_task(self, proposed_goal, authority, requirements, clearance):
        self.calls.append((proposed_goal, authority, requirements, clearance))
        if self._task_id is None:
            return None
        return CreatedTask(task_id=self._task_id)


def _requirements():
    return TaskRequirements(
        expected_outcome_ref="expected-outcome:1",
        commitment_ref="commitment:1",
        capability_scope=("cap.read",),
    )


def _clearance(epoch=0):
    return C7ClearanceRef(
        correction_epoch=epoch,
        clearance_digest="sha256:clearance",
        cleared_at=datetime.now(timezone.utc),
    )


def _gate(
    mandate_registry,
    *,
    authority=None,
    requirements: TaskRequirements | None = None,
    has_requirements: bool = True,
    c7: C7ClearanceRef | None = None,
    has_c7: bool = True,
    creation=None,
):
    return TrustedTaskActivationGate(
        authority_registry=_AuthorityRegistry([authority] if authority else []),
        mandate_registry=mandate_registry,
        requirements=_Requirements(
            requirements
            if requirements is not None
            else (_requirements() if has_requirements else None)
        ),
        c7_clearance=_C7(
            c7 if c7 is not None else (_clearance() if has_c7 else None)
        ),
        task_creation=creation or _Creation(),
    )


# ---------------------------------------------------------------------------
# Fail-closed gates
# ---------------------------------------------------------------------------


def test_gate_rejects_caller_minted_authority_without_trusted_registry(
    mandate_registry, goal, authority
):
    """A caller-constructed authority not resolved by the trusted registry is denied."""
    gate = _gate(mandate_registry, authority=None, creation=_Creation())
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_NOT_RECOGNIZED.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_inactive_mandate(mandate_registry, goal, authority):
    suspended = mandate_registry.get_mandate("mandate-1").model_copy(
        update={"status": MandateStatus.SUSPENDED}
    )
    mandate_registry._mandates["mandate-1"] = suspended
    gate = _gate(mandate_registry, authority=authority)
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.MANDATE_NOT_ACTIVE.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_missing_requirements(mandate_registry, goal, authority):
    gate = _gate(mandate_registry, authority=authority, has_requirements=False)
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.REQUIREMENTS_MISSING.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_missing_c7_clearance(mandate_registry, goal, authority):
    gate = _gate(mandate_registry, authority=authority, has_c7=False)
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.C7_CLEARANCE_MISSING.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_c7_epoch_mismatch(mandate_registry, goal, authority):
    gate = _gate(mandate_registry, authority=authority, c7=_clearance(epoch=99))
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.C7_EPOCH_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_same_instance_producer_and_acceptor(
    mandate_registry, goal, now
):
    producer_authority = ActivationAuthority(
        authority_id="auth-1",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        authority_instance_id="assessor-instance-1",
        producer_instance_id="assessor-instance-1",
        source_assessment_id="assessment:event-1",
        source_proposed_goal_id="goal-1",
        authorization_digest="sha256:auth",
        authorized_at=now,
    )
    gate = _gate(mandate_registry, authority=producer_authority)
    result = gate.activate(goal, producer_authority)
    assert not result.activated
    assert ActivationDenialReason.SAME_INSTANCE_PROPOSE_AND_ACCEPT.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_authority_goal_binding_mismatch(
    mandate_registry, goal, now
):
    mismatched = ActivationAuthority(
        authority_id="auth-1",
        mandate_id="mandate-1",
        standing_mission_id="mission-1",
        authority_instance_id="authority-instance-1",
        producer_instance_id="assessor-instance-1",
        source_assessment_id="assessment:event-1",
        source_proposed_goal_id="other-goal",
        authorization_digest="sha256:auth",
        authorized_at=now,
    )
    gate = _gate(mandate_registry, authority=mismatched)
    result = gate.activate(goal, mismatched)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_fails_closed_when_creation_port_refuses(
    mandate_registry, goal, authority
):
    gate = _gate(
        mandate_registry, authority=authority, creation=_Creation(task_id=None)
    )
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.TASK_CREATION_REFUSED.value in (
        result.rejection_reason or ""
    )


# ---------------------------------------------------------------------------
# Trusted path
# ---------------------------------------------------------------------------


def test_gate_activates_only_through_trusted_creation_port(
    mandate_registry, goal, authority
):
    creation = _Creation(task_id="task-42")
    gate = _gate(mandate_registry, authority=authority, creation=creation)
    result = gate.activate(goal, authority)
    assert result.activated
    assert result.task_id == "task-42"
    assert len(creation.calls) == 1
    assert creation.calls[0][2].expected_outcome_ref == "expected-outcome:1"


def test_default_m0_stub_still_fails_closed(goal, authority):
    """Backward compatibility: the M0 stub remains fail-closed."""
    result = InMemoryTaskActivation().activate(goal, authority)
    assert not result.activated
    assert "TaskService/C7" in (result.rejection_reason or "")


class _NoopAssessor:
    """Assessor that must never be invoked by activate_goal."""

    instance_id = "assessor-instance-1"
    policy_digest = "sha256:assessor-policy"

    def assess(
        self, event: SrlEnvironmentEvent, mission: StandingMission
    ) -> SrlRelevanceAssessment:
        raise AssertionError("activate_goal must not call the assessor")


def test_runtime_delegates_activation_to_injected_trusted_gate(
    mandate_registry, goal, authority, now
):
    gate = _gate(mandate_registry, authority=authority)
    runtime = SrlRuntime(
        event_ledger=InMemoryEventLedger(),
        mandate_registry=mandate_registry,
        assessor_port=_NoopAssessor(),
        goal_formation=SrlGoalFormation(),
        budget_enforcement=InMemoryBudgetLedger(),
        help_dispatch=InMemoryHelpDispatch(),
        task_activation=gate,
        outcome_acceptor=InMemoryOutcomeAcceptor(),
        audit_port=InMemoryAuditLog(),
        runtime_instance_ref=AgentInstanceRef(
            instance_id="runtime-instance-1",
            implementation_id="agent-os-core",
            implementation_version="m1",
            tenant_id="t-1",
            workspace_id="w-1",
            created_at=now,
        ),
    )
    result = runtime.activate_goal(goal, authority)
    assert result.activated
    assert result.task_id == "task-1"


def test_runtime_default_port_remains_fail_closed(goal, authority, now):
    """Without a trusted gate injected, the runtime must not activate."""
    runtime = SrlRuntime(
        event_ledger=InMemoryEventLedger(),
        mandate_registry=InMemoryMandateRegistry(),
        assessor_port=_NoopAssessor(),
        goal_formation=SrlGoalFormation(),
        budget_enforcement=InMemoryBudgetLedger(),
        help_dispatch=InMemoryHelpDispatch(),
        task_activation=InMemoryTaskActivation(),
        outcome_acceptor=InMemoryOutcomeAcceptor(),
        audit_port=InMemoryAuditLog(),
        runtime_instance_ref=AgentInstanceRef(
            instance_id="runtime-instance-1",
            implementation_id="agent-os-core",
            implementation_version="m1",
            tenant_id="t-1",
            workspace_id="w-1",
            created_at=now,
        ),
    )
    result = runtime.activate_goal(goal, authority)
    assert not result.activated


def test_gate_rejects_stripped_producer_identity(mandate_registry, goal, authority):
    stripped = goal.model_copy(
        update={
            "constraints": tuple(
                c for c in goal.constraints if not c.startswith("assessor-instance:")
            )
        }
    )
    result = _gate(mandate_registry, authority=authority).activate(stripped, authority)
    assert not result.activated
    assert ActivationDenialReason.PRODUCER_IDENTITY_UNAVAILABLE.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_empty_producer_value(mandate_registry, goal, authority):
    empty = goal.model_copy(
        update={
            "constraints": tuple(
                "assessor-instance:" if c.startswith("assessor-instance:") else c
                for c in goal.constraints
            )
        }
    )
    result = _gate(mandate_registry, authority=authority).activate(empty, authority)
    assert not result.activated
    assert ActivationDenialReason.PRODUCER_IDENTITY_UNAVAILABLE.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_forged_goal_producer(mandate_registry, goal, authority):
    forged = goal.model_copy(
        update={
            "constraints": tuple(
                "assessor-instance:other-instance"
                if c.startswith("assessor-instance:")
                else c
                for c in goal.constraints
            )
        }
    )
    result = _gate(mandate_registry, authority=authority).activate(forged, authority)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_cross_mandate_authority(mandate_registry, goal, authority, now):
    cross = authority.model_copy(update={"mandate_id": "mandate-2"})
    result = _gate(mandate_registry, authority=cross).activate(goal, cross)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_assessment_ref_mismatch(mandate_registry, goal, authority, now):
    other = authority.model_copy(update={"source_assessment_id": "assessment:other"})
    result = _gate(mandate_registry, authority=other).activate(goal, other)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_mismatched_registered_authority(mandate_registry, goal, authority, now):
    # Registry resolves the id to a different record than the caller supplied.
    different = authority.model_copy(update={"authorization_digest": "sha256:different"})
    gate = TrustedTaskActivationGate(
        authority_registry=_AuthorityRegistry([different]),
        mandate_registry=mandate_registry,
        requirements=_Requirements(_requirements()),
        c7_clearance=_C7(_clearance()),
        task_creation=_Creation(),
    )
    result = gate.activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_NOT_RECOGNIZED.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_tenant_scope_mismatch(mandate_registry, goal, authority):
    out_of_scope = goal.model_copy(update={"tenant_id": "t-2"})
    result = _gate(mandate_registry, authority=authority).activate(
        out_of_scope, authority
    )
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_mission_mismatch(mandate_registry, goal, authority, now):
    wrong_mission = authority.model_copy(update={"standing_mission_id": "mission-9"})
    result = _gate(mandate_registry, authority=wrong_mission).activate(
        goal, wrong_mission
    )
    assert not result.activated
    assert ActivationDenialReason.AUTHORITY_BINDING_MISMATCH.value in (
        result.rejection_reason or ""
    )


def test_gate_rejects_unavailable_mandate(goal, authority):
    empty = InMemoryMandateRegistry()
    result = _gate(empty, authority=authority).activate(goal, authority)
    assert not result.activated
    assert ActivationDenialReason.MANDATE_UNAVAILABLE.value in (
        result.rejection_reason or ""
    )


def test_runtime_rejects_empty_producer_value(mandate_registry, goal, authority, now):
    empty = goal.model_copy(
        update={
            "constraints": tuple(
                "assessor-instance:" if c.startswith("assessor-instance:") else c
                for c in goal.constraints
            )
        }
    )
    runtime = SrlRuntime(
        event_ledger=InMemoryEventLedger(),
        mandate_registry=mandate_registry,
        assessor_port=_NoopAssessor(),
        goal_formation=SrlGoalFormation(),
        budget_enforcement=InMemoryBudgetLedger(),
        help_dispatch=InMemoryHelpDispatch(),
        task_activation=_gate(mandate_registry, authority=authority),
        outcome_acceptor=InMemoryOutcomeAcceptor(),
        audit_port=InMemoryAuditLog(),
        runtime_instance_ref=AgentInstanceRef(
            instance_id="runtime-instance-1",
            implementation_id="agent-os-core",
            implementation_version="m1",
            tenant_id="t-1",
            workspace_id="w-1",
            created_at=now,
        ),
    )
    result = runtime.activate_goal(empty, authority)
    assert not result.activated
    assert ActivationDenialReason.PRODUCER_IDENTITY_UNAVAILABLE.value in (
        result.rejection_reason or ""
    )


def test_task_service_adapter_creates_durable_idempotent_task(
    mandate_registry, goal, authority
):
    task_service = TaskService(event_store=InMemoryTaskEventStore())
    gate = _gate(
        mandate_registry,
        authority=authority,
        creation=TaskServiceCreationAdapter(task_service),
    )
    first = gate.activate(goal, authority)
    second = gate.activate(goal, authority)
    assert first.activated
    assert second.activated
    assert first.task_id is not None
    assert first.task_id == second.task_id
    assert task_service.get_task(first.task_id).task_id == first.task_id


def test_conflicting_authority_reactivation_fails_closed(
    mandate_registry, goal, authority, now
):
    """F1: a different authority for the same goal must be denied, not raise."""
    task_service = TaskService(event_store=InMemoryTaskEventStore())
    competing = authority.model_copy(
        update={
            "authority_id": "auth-2",
            "authority_instance_id": "authority-instance-2",
            "authorization_digest": "sha256:auth-2",
            "authorized_at": now + timedelta(seconds=30),
        }
    )
    gate = TrustedTaskActivationGate(
        authority_registry=_AuthorityRegistry([authority, competing]),
        mandate_registry=mandate_registry,
        requirements=_Requirements(_requirements()),
        c7_clearance=_C7(_clearance()),
        task_creation=TaskServiceCreationAdapter(task_service),
    )
    first = gate.activate(goal, authority)
    conflict = gate.activate(goal, competing)
    assert first.activated
    assert not conflict.activated
    assert ActivationDenialReason.TASK_IDENTITY_CONFLICT.value in (
        conflict.rejection_reason or ""
    )
