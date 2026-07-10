from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    Goal,
    ObservedOutcome,
    OutcomeStatus,
    ResourceBudget,
    canonical_json,
    content_digest,
)


def test_goal_rejects_unknown_fields(now: datetime) -> None:
    with pytest.raises(ValidationError):
        Goal.model_validate(
            {
                "goal_id": "goal-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "created_by": "user-1",
                "created_at": now,
                "statement": "Ship a verified patch",
                "hidden_authority": "forbidden",
            }
        )


def test_goal_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Goal(
            goal_id="goal-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            created_by="user-1",
            created_at=datetime(2026, 7, 10, 8, 0),
            statement="Ship a verified patch",
        )


def test_contract_is_immutable(goal: Goal) -> None:
    with pytest.raises(ValidationError):
        goal.statement = "changed"


def test_commitment_normalizes_authority_scopes(now: datetime) -> None:
    commitment = Commitment(
        commitment_id="commitment-1",
        task_id="task-1",
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        accepted_by="user-1",
        accepted_at=now,
        deliverables=("patch",),
        acceptance_criteria=("tests pass",),
        authority_scopes=("repo:write", "repo:read", "repo:write"),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("tests verified",),
        expires_at=now + timedelta(hours=1),
    )

    assert commitment.authority_scopes == ("repo:read", "repo:write")


@pytest.mark.parametrize("field", ["deliverables", "acceptance_criteria"])
def test_commitment_requires_deliverable_and_acceptance_criterion(
    field: str,
    now: datetime,
) -> None:
    values = {
        "commitment_id": "commitment-1",
        "task_id": "task-1",
        "goal_id": "goal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "accepted_by": "user-1",
        "accepted_at": now,
        "deliverables": ("patch",),
        "acceptance_criteria": ("tests pass",),
        "budget": ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        "risk_tier": 1,
        "exit_conditions": ("tests verified",),
        "expires_at": now + timedelta(hours=1),
    }
    values[field] = ()

    with pytest.raises(ValidationError):
        Commitment(**values)


def test_canonical_digest_is_mapping_order_independent() -> None:
    left = {"b": 2, "a": {"d": 4, "c": 3}}
    right = {"a": {"c": 3, "d": 4}, "b": 2}

    assert canonical_json(left) == canonical_json(right)
    assert content_digest(left) == content_digest(right)


def test_verified_outcome_requires_score_and_evidence(now: datetime) -> None:
    expected = ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=now,
    )

    with pytest.raises(ValidationError, match="verified outcome"):
        ObservedOutcome(
            observed_outcome_id="observed-1",
            expected_outcome_id=expected.expected_outcome_id,
            task_id="task-1",
            run_id="run-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            evaluator_type=expected.evaluator_type,
            evaluator_version=expected.evaluator_version,
            status=OutcomeStatus.VERIFIED,
            confidence=0.0,
            observed_at=now,
        )


def test_verified_outcome_keeps_evidence_separate_from_receipt(now: datetime) -> None:
    outcome = ObservedOutcome(
        observed_outcome_id="observed-1",
        expected_outcome_id="expected-1",
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type="pytest",
        evaluator_version="1",
        status=OutcomeStatus.VERIFIED,
        score=1.0,
        confidence=1.0,
        evidence_refs=("artifact:test-report",),
        observed_at=now,
    )

    assert outcome.status is OutcomeStatus.VERIFIED
    assert outcome.evidence_refs == ("artifact:test-report",)
