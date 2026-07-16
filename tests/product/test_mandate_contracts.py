from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    AgentInstanceRef,
    EvaluationPrinciple,
    HelpBudget,
    Mandate,
    MandateEnvelope,
    MandateRatificationReceipt,
    MandateStatus,
    StandingMission,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _help_budget(**updates: Any) -> HelpBudget:
    values: dict[str, Any] = {
        "max_requests_per_window": 10,
        "max_operator_minutes_per_window": 30,
        "max_repeated_question_rate": 0.2,
        "max_unresolved_wait_seconds": 3600,
        "window_seconds": 86400,
    }
    values.update(updates)
    return HelpBudget(**values)


def _envelope(**updates: Any) -> MandateEnvelope:
    values: dict[str, Any] = {
        "allowed_task_classes": ("Goal", "Program", "Task"),
        "allowed_effect_classes": ("READ_ONLY", "IDEMPOTENT_EXTERNAL"),
        "allowed_resource_refs": ("repo://canonical",),
        "capability_grant_rules": ("read-only-default",),
        "wake_budget_per_window": 100,
        "query_budget_per_window": 100,
        "help_budget": _help_budget(),
        "max_concurrent_tasks": 4,
        "max_duration_seconds": 3600,
        "evaluation_principles": (
            EvaluationPrinciple(
                principle_id="ep-1",
                statement="Do no harm",
                outcome_criteria_ref="criteria://safety",
                weight=1.0,
            ),
        ),
        "escalation_conditions": ("envelope-overflow", "irreversible-risk"),
    }
    values.update(updates)
    return MandateEnvelope(**values)


def _mandate(**updates: Any) -> Mandate:
    values: dict[str, Any] = {
        "mandate_id": "mandate-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "principal_id": "principal-1",
        "status": MandateStatus.RATIFIED,
        "mission_statement": "Maintain repository quality invariants",
        "desired_outcomes": ("tests-green", "no-regressions"),
        "permanent_constraints": ("no-external-effects",),
        "authority_envelope": _envelope(),
        "environment_binding_classes": ("filesystem", "git", "message-bus"),
        "time_horizon": "90 days",
        "review_cadence_seconds": 86400,
        "expires_at": NOW + timedelta(days=90),
        "correction_epoch": 0,
        "revocation_conditions": ("founder-revocation", "safety-incident"),
        "created_at": NOW,
        "ratified_at": NOW,
    }
    values.update(updates)
    return Mandate(**values)


def test_mandate_round_trip() -> None:
    mandate = _mandate()
    assert mandate.mandate_id == "mandate-1"
    assert mandate.status is MandateStatus.RATIFIED
    assert mandate.authority_envelope.help_budget.max_requests_per_window == 10


def test_mandate_ratified_requires_ratified_at() -> None:
    with pytest.raises(ValidationError, match="ratified_at"):
        _mandate(ratified_at=None)


def test_mandate_active_requires_ratified_at() -> None:
    with pytest.raises(ValidationError, match="ratified_at"):
        _mandate(status=MandateStatus.ACTIVE, ratified_at=None)


def test_mandate_draft_does_not_require_ratified_at() -> None:
    mandate = _mandate(status=MandateStatus.DRAFT, ratified_at=None)
    assert mandate.status is MandateStatus.DRAFT
    assert mandate.ratified_at is None


def test_mandate_rejects_missing_required_field() -> None:
    with pytest.raises(ValidationError, match="mission_statement"):
        _mandate(mission_statement="")


def test_mandate_envelope_requires_nonempty_allowed_task_classes() -> None:
    with pytest.raises(ValidationError, match="allowed_task_classes"):
        _envelope(allowed_task_classes=())


def test_mandate_envelope_requires_nonempty_allowed_effect_classes() -> None:
    with pytest.raises(ValidationError, match="allowed_effect_classes"):
        _envelope(allowed_effect_classes=())


def test_mandate_envelope_requires_nonempty_capability_grant_rules() -> None:
    with pytest.raises(ValidationError, match="capability_grant_rules"):
        _envelope(capability_grant_rules=())


def test_evaluation_principle_weight_bounds() -> None:
    with pytest.raises(ValidationError, match="weight"):
        EvaluationPrinciple(
            principle_id="ep-bad",
            statement="Too heavy",
            weight=1.5,
        )


def test_mandate_envelope_help_budget_overflow_rejected() -> None:
    with pytest.raises(ValidationError, match="max_requests_per_window"):
        _envelope(help_budget=_help_budget(max_requests_per_window=-1))


def test_agent_instance_ref_round_trip() -> None:
    ref = AgentInstanceRef(
        instance_id="instance-1",
        implementation_id="agent-os-core",
        implementation_version="0.1.0",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_at=NOW,
    )
    assert ref.instance_id == "instance-1"


def _agent_instance_ref(**updates: Any) -> AgentInstanceRef:
    values: dict[str, Any] = {
        "instance_id": "instance-1",
        "implementation_id": "agent-os-core",
        "implementation_version": "0.1.0",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "created_at": NOW,
    }
    values.update(updates)
    return AgentInstanceRef(**values)


def test_agent_instance_ref_rejects_mission_field() -> None:
    with pytest.raises(ValidationError, match="mission"):
        _agent_instance_ref(mission_statement="should not be here")


def test_agent_instance_ref_rejects_permission_field() -> None:
    with pytest.raises(ValidationError, match="permission"):
        _agent_instance_ref(permissions=("should-not-be-here",))


def test_agent_instance_ref_rejects_environment_field() -> None:
    with pytest.raises(ValidationError, match="environment"):
        _agent_instance_ref(environment_bindings=("should-not-be-here",))


def test_agent_instance_ref_rejects_learning_field() -> None:
    with pytest.raises(ValidationError, match="learning"):
        _agent_instance_ref(learning_history=("should-not-be-here",))


def test_standing_mission_round_trip() -> None:
    mission = StandingMission(
        standing_mission_id="sm-1",
        mandate_id="mandate-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        statement="Keep tests green",
        outcome_criteria_refs=("criteria://tests",),
        active_commitment_ids=("commitment-1",),
        disallowed_action_classes=("irreversible-external",),
        review_cadence_seconds=3600,
        projected_at=NOW,
        expires_at=NOW + timedelta(days=30),
        parent_mandate_digest="sha256:abc",
        correction_epoch=0,
        ratification_receipt_digest="sha256:receipt",
    )
    assert mission.review_cadence_seconds == 3600


def test_mandate_ratification_receipt_round_trip() -> None:
    receipt = MandateRatificationReceipt(
        receipt_id="receipt-1",
        mandate_id="mandate-1",
        mandate_digest="sha256:mandate",
        principal_attestation="attestation-1",
        agent_instance_ref_id="instance-1",
        initial_correction_epoch=0,
        ratified_at=NOW,
    )
    assert receipt.initial_correction_epoch == 0


def test_mandate_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="hidden_field"):
        _mandate(hidden_field="forbidden")
