from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    ObservedOutcome,
    OutcomeStatus,
    ResourceBudget,
)


ACCEPTED_AT = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _budget(**updates: Any) -> ResourceBudget:
    values: dict[str, Any] = {
        "max_cost_usd": Decimal("1.50"),
        "max_duration_seconds": 300,
        "max_provider_tokens": 2_000,
        "max_tool_calls": 4,
    }
    values.update(updates)
    return ResourceBudget(**values)


def _commitment(**updates: Any) -> Commitment:
    values: dict[str, Any] = {
        "commitment_id": "commitment-1",
        "task_id": "task-1",
        "goal_id": "goal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "accepted_by": "user-1",
        "accepted_at": ACCEPTED_AT,
        "deliverables": ("patch",),
        "acceptance_criteria": ("tests pass",),
        "authority_scopes": ("repo:read", "repo:write"),
        "budget": _budget(),
        "risk_tier": 1,
        "exit_conditions": ("acceptance criteria verified",),
        "expires_at": ACCEPTED_AT + timedelta(hours=1),
    }
    values.update(updates)
    return Commitment(**values)


def _expected_outcome(**updates: Any) -> ExpectedOutcome:
    values: dict[str, Any] = {
        "expected_outcome_id": "expected-1",
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": ("test-report",),
        "failure_semantics": ("test command exits non-zero",),
        "threshold": 1.0,
        "observation_window_seconds": 60,
        "frozen_at": ACCEPTED_AT,
    }
    values.update(updates)
    return ExpectedOutcome(**values)


def _observed_outcome(**updates: Any) -> ObservedOutcome:
    values: dict[str, Any] = {
        "observed_outcome_id": "observed-1",
        "expected_outcome_id": "expected-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "status": OutcomeStatus.VERIFIED,
        "score": 1.0,
        "confidence": 1.0,
        "evidence_refs": ("evidence-1",),
        "observed_at": ACCEPTED_AT,
    }
    values.update(updates)
    return ObservedOutcome(**values)


def test_resource_budget_compares_every_dimension() -> None:
    limit = _budget()

    assert _budget(max_tool_calls=3).fits_within(limit)
    assert not _budget(max_tool_calls=5).fits_within(limit)
    assert not _budget(max_cost_usd=Decimal("1.51")).fits_within(limit)


def test_commitment_requires_future_expiry() -> None:
    with pytest.raises(ValidationError, match="expires_at"):
        _commitment(expires_at=ACCEPTED_AT)


def test_commitment_uses_shared_risk_tier_bounds() -> None:
    with pytest.raises(ValidationError):
        _commitment(risk_tier=6)


def test_expected_outcome_requires_failure_semantics() -> None:
    with pytest.raises(ValidationError):
        _expected_outcome(failure_semantics=())


def test_expected_outcome_rejects_non_finite_threshold() -> None:
    with pytest.raises(ValidationError, match="finite"):
        _expected_outcome(threshold=float("nan"))


def test_unresolved_outcome_requires_gap() -> None:
    with pytest.raises(ValidationError, match="unresolved"):
        _observed_outcome(
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=0.2,
            evidence_refs=(),
            unresolved_gaps=(),
        )


def test_verified_outcome_rejects_unresolved_gaps() -> None:
    with pytest.raises(ValidationError, match="verified"):
        _observed_outcome(unresolved_gaps=("evidence is incomplete",))


def test_verified_score_and_confidence_are_independent() -> None:
    outcome = _observed_outcome(score=1.0, confidence=0.2)

    assert outcome.score == 1.0
    assert outcome.confidence == 0.2


def test_observed_outcome_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        _observed_outcome(confidence=1.1)
