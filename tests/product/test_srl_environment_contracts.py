from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    EnvironmentBinding,
    EnvironmentBindingMode,
    SrlEnvironmentEvent,
    SrlOperationalProjectionRef,
    SrlRelevanceAssessment,
    SrlRelevanceDisposition,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _binding(**updates: Any) -> EnvironmentBinding:
    values: dict[str, Any] = {
        "binding_id": "binding-1",
        "mandate_id": "mandate-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "source_type": "git",
        "source_scope": "repo://canonical",
        "mode": EnvironmentBindingMode.POLL,
        "cursor_type": "commit-sha",
        "freshness_seconds": 60,
        "read_capability_id": "cap:git:read",
        "write_capability_id": None,
        "wake_budget_per_window": 10,
        "query_budget_per_window": 50,
        "dedupe_key_fields": ("commit_sha", "ref"),
        "secret_policy": "no-pii-in-payload",
    }
    values.update(updates)
    return EnvironmentBinding(**values)


def _event(**updates: Any) -> SrlEnvironmentEvent:
    values: dict[str, Any] = {
        "event_id": "event-1",
        "binding_id": "binding-1",
        "mandate_id": "mandate-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "source_cursor": "abc123",
        "occurred_at": NOW,
        "received_at": NOW + timedelta(seconds=1),
        "event_class": "git.push",
        "payload_digest": "sha256:payload",
        "dedupe_key": "abc123:main",
        "provenance": ("git://canonical",),
    }
    values.update(updates)
    return SrlEnvironmentEvent(**values)


def _assessment(**updates: Any) -> SrlRelevanceAssessment:
    values: dict[str, Any] = {
        "assessment_id": "assessment-1",
        "mandate_id": "mandate-1",
        "standing_mission_id": "sm-1",
        "trigger_event_id": "event-1",
        "affected_commitment_ids": ("commitment-1",),
        "evidence_refs": ("evidence://event-1",),
        "uncertainty_summary": "Direct push to main",
        "urgency": "HIGH",
        "expected_loss_of_delay_seconds": 300,
        "proposed_attention_budget_seconds": 600,
        "disposition": SrlRelevanceDisposition.CREATE_TASK,
        "confidence": 0.9,
        "false_positive_recorded": True,
        "assessor_version": "assessor-1.0",
        "assessor_policy_digest": "sha256:assessor-policy",
        "proposed_goal_statement": "Investigate direct push to main",
        "proposed_task_class": "Goal",
        "assessed_at": NOW,
    }
    values.update(updates)
    return SrlRelevanceAssessment(**values)


def _projection(**updates: Any) -> SrlOperationalProjectionRef:
    values: dict[str, Any] = {
        "projection_id": "projection-1",
        "artifact_digest": "sha256:artifact",
        "schema_version": "som-1.0",
        "mandate_id": "mandate-1",
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=1),
        "evidence_refs": ("evidence://projection-1",),
        "uncertainty_conflict_summary": "No conflicts",
        "freshness_at": NOW,
        "compatibility_digest": "sha256:compat",
    }
    values.update(updates)
    return SrlOperationalProjectionRef(**values)


def test_environment_binding_round_trip() -> None:
    binding = _binding()
    assert binding.mode is EnvironmentBindingMode.POLL
    assert binding.write_capability_id is None


def test_environment_binding_requires_read_capability() -> None:
    with pytest.raises(ValidationError, match="read_capability_id"):
        _binding(read_capability_id="")


def test_environment_binding_mode_invalid() -> None:
    with pytest.raises(ValidationError, match="mode"):
        EnvironmentBinding(
            binding_id="binding-1",
            mandate_id="mandate-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            source_type="git",
            source_scope="repo://canonical",
            mode="PUSH",  # type: ignore[arg-type]
            cursor_type="commit-sha",
            freshness_seconds=60,
            read_capability_id="cap:git:read",
            dedupe_key_fields=("commit_sha",),
            secret_policy="no-pii",
        )


def test_environment_event_round_trip() -> None:
    event = _event()
    assert event.event_class == "git.push"
    assert event.provenance == ("git://canonical",)


def test_environment_event_requires_event_id() -> None:
    with pytest.raises(ValidationError, match="event_id"):
        _event(event_id="")


def test_relevance_assessment_round_trip() -> None:
    assessment = _assessment()
    assert assessment.disposition is SrlRelevanceDisposition.CREATE_TASK


def test_relevance_assessment_requires_event_or_gap_trigger() -> None:
    with pytest.raises(ValidationError, match="trigger"):
        _assessment(trigger_event_id=None, trigger_gap_id=None)


def test_relevance_assessment_gap_trigger_valid() -> None:
    assessment = _assessment(trigger_event_id=None, trigger_gap_id="gap-1")
    assert assessment.trigger_gap_id == "gap-1"


def test_relevance_assessment_invalid_disposition() -> None:
    with pytest.raises(ValidationError, match="disposition"):
        _assessment(disposition="PANIC")  # type: ignore[arg-type]


def test_relevance_assessment_confidence_bounds() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        _assessment(confidence=1.5)


def test_relevance_assessment_urgency_invalid() -> None:
    with pytest.raises(ValidationError, match="urgency"):
        _assessment(urgency="URGENT")  # type: ignore[arg-type]


def test_relevance_assessment_negative_attention_budget_rejected() -> None:
    with pytest.raises(ValidationError, match="proposed_attention_budget_seconds"):
        _assessment(proposed_attention_budget_seconds=-1)


def test_operational_projection_ref_round_trip() -> None:
    projection = _projection()
    assert projection.schema_version == "som-1.0"


def test_operational_projection_ref_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_refs"):
        _projection(evidence_refs=())


def test_operational_projection_ref_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra_field"):
        _projection(extra_field="forbidden")


def test_relevance_assessment_requires_assessor_policy_digest() -> None:
    with pytest.raises(ValidationError, match="assessor_policy_digest"):
        _assessment(assessor_policy_digest="")


def test_relevance_assessment_create_task_requires_proposal_fields() -> None:
    with pytest.raises(ValidationError, match="proposed_goal_statement"):
        _assessment(proposed_goal_statement=None)
    with pytest.raises(ValidationError, match="proposed_task_class"):
        _assessment(proposed_task_class=None)


def test_relevance_assessment_help_requires_minimum_external_input() -> None:
    assessment = _assessment(
        disposition=SrlRelevanceDisposition.HELP,
        minimum_external_input="Approve or reject the staged rollout",
        proposed_goal_statement=None,
        proposed_task_class=None,
        false_positive_recorded=False,
    )
    assert assessment.disposition is SrlRelevanceDisposition.HELP


def test_relevance_assessment_help_rejects_proposed_goal() -> None:
    with pytest.raises(ValidationError, match="proposed_goal_statement"):
        _assessment(
            disposition=SrlRelevanceDisposition.HELP,
            minimum_external_input="Need input",
            proposed_goal_statement="Should not be here",
        )


def test_relevance_assessment_non_work_rejects_proposal_fields() -> None:
    with pytest.raises(ValidationError, match="proposed_goal_statement"):
        _assessment(
            disposition=SrlRelevanceDisposition.OBSERVE,
            proposed_goal_statement="Should not be here",
            proposed_task_class=None,
        )


def test_relevance_assessment_task_requires_false_positive_recorded() -> None:
    with pytest.raises(ValidationError, match="false_positive_recorded"):
        _assessment(false_positive_recorded=False)


def test_relevance_assessment_create_task_rejects_minimum_external_input() -> None:
    with pytest.raises(ValidationError, match="minimum_external_input"):
        _assessment(minimum_external_input="Should not be here")
