"""SPINE-1 (ADR-0014): monorepo-native human-facing approval choice-set contract.

Fail-closed invariants:
  * a choice set is EITHER >=2 distinct alternatives with exactly one recommended action,
    OR a single alternative plus a non-empty single_option_rationale;
  * a REVISE decision must carry the surfaced choice set and select an action within it —
    otherwise the choice-set audit trail would be a fiction.

Each test would FAIL if the invariant were skipped (e.g. a validator that accepted any set).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    ApprovalChoice,
    ApprovalChoiceSet,
    ApprovalDecision,
    ApprovalDisposition,
    PrincipalRole,
)

_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _decision(**overrides: object) -> ApprovalDecision:
    payload: dict[str, object] = {
        "approval_id": "approval:1",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "action_digest": _DIGEST,
        "actor_id": "principal:1",
        "actor_role": PrincipalRole.PRINCIPAL,
        "disposition": ApprovalDisposition.APPROVE,
        "reason": "reviewed",
        "decided_at": _NOW,
        "expires_at": _NOW + timedelta(hours=1),
    }
    payload.update(overrides)
    return ApprovalDecision(**payload)


# --- structural choice-set invariants ------------------------------------------------


def test_single_option_without_rationale_is_refused() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoiceSet(alternatives=(ApprovalChoice(action="keep"),))


def test_single_option_with_rationale_and_recommendation_is_valid() -> None:
    choice_set = ApprovalChoiceSet(
        alternatives=(ApprovalChoice(action="keep"),),
        recommended_action="keep",
        single_option_rationale="no alternative existed under the current mandate",
    )
    assert choice_set.action_labels() == ("keep",)


def test_multi_alternative_without_recommendation_is_refused() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoiceSet(
            alternatives=(ApprovalChoice(action="a"), ApprovalChoice(action="b"))
        )


def test_recommendation_must_be_a_surfaced_alternative() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoiceSet(
            alternatives=(ApprovalChoice(action="a"), ApprovalChoice(action="b")),
            recommended_action="c",
        )


def test_duplicate_alternatives_are_refused() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoiceSet(
            alternatives=(ApprovalChoice(action="a"), ApprovalChoice(action="a")),
            recommended_action="a",
        )


def test_empty_choice_set_is_refused() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoiceSet()


def test_valid_multi_alternative_choice_set_is_accepted() -> None:
    choice_set = ApprovalChoiceSet(
        alternatives=(
            ApprovalChoice(action="apply", rationale="best evidence"),
            ApprovalChoice(action="defer", rationale="needs review"),
        ),
        recommended_action="apply",
    )
    assert choice_set.action_labels() == ("apply", "defer")


# --- decision-level discipline -------------------------------------------------------


def test_revise_requires_a_choice_set() -> None:
    with pytest.raises(ValidationError):
        _decision(disposition=ApprovalDisposition.REVISE, selected_action="apply")


def test_revise_must_select_an_action_within_the_choice_set() -> None:
    choice_set = ApprovalChoiceSet(
        alternatives=(ApprovalChoice(action="apply"), ApprovalChoice(action="defer")),
        recommended_action="apply",
    )
    with pytest.raises(ValidationError):
        _decision(
            disposition=ApprovalDisposition.REVISE,
            choice_set=choice_set,
            selected_action="not-surfaced",
        )


def test_revise_within_the_choice_set_is_accepted() -> None:
    choice_set = ApprovalChoiceSet(
        alternatives=(ApprovalChoice(action="apply"), ApprovalChoice(action="defer")),
        recommended_action="apply",
    )
    decision = _decision(
        disposition=ApprovalDisposition.REVISE,
        choice_set=choice_set,
        selected_action="defer",
    )
    assert decision.selected_action == "defer"


def test_approve_without_a_choice_set_remains_backward_compatible() -> None:
    decision = _decision(disposition=ApprovalDisposition.APPROVE)
    assert decision.choice_set is None
    assert decision.selected_action is None


def test_selected_action_requires_a_surfacing_choice_set() -> None:
    with pytest.raises(ValidationError):
        _decision(disposition=ApprovalDisposition.APPROVE, selected_action="apply")


def test_approve_with_a_valid_surfaced_choice_is_accepted() -> None:
    choice_set = ApprovalChoiceSet(
        alternatives=(ApprovalChoice(action="apply"), ApprovalChoice(action="defer")),
        recommended_action="apply",
    )
    decision = _decision(
        disposition=ApprovalDisposition.APPROVE,
        choice_set=choice_set,
        selected_action="apply",
    )
    assert decision.choice_set is not None
