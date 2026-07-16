from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    BoundedOption,
    HelpBudget,
    HelpBurdenReceipt,
    HelpClass,
    KnownFact,
    SrlHelpRequest,
    SrlHelpResponse,
    SrlHelpResponseKind,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _budget(**updates: Any) -> HelpBudget:
    values: dict[str, Any] = {
        "max_requests_per_window": 10,
        "max_operator_minutes_per_window": 30,
        "max_repeated_question_rate": 0.2,
        "max_unresolved_wait_seconds": 3600,
        "window_seconds": 86400,
    }
    values.update(updates)
    return HelpBudget(**values)


def _help_request(**updates: Any) -> SrlHelpRequest:
    values: dict[str, Any] = {
        "help_request_id": "help-1",
        "mandate_id": "mandate-1",
        "standing_mission_id": "sm-1",
        "commitment_id": "commitment-1",
        "goal_id": "goal-1",
        "help_class": HelpClass.IRREVERSIBLE_RISK,
        "known_facts": (
            KnownFact(
                assertion="The proposed patch touches production config",
                provenance_ref="evidence://review",
                confidence=0.95,
            ),
        ),
        "unknowns": ("exact blast radius",),
        "acquisition_attempts": ("queried-config-db",),
        "unsafe_boundary": "Cannot determine rollback window without operator judgment",
        "bounded_options": (
            BoundedOption(
                option_id="opt-1",
                label="Proceed with staged rollout",
                expected_impact="Limited blast radius, reversible",
                required_authority=("operator-confirm",),
            ),
        ),
        "minimum_answer": "Approve or reject the staged rollout",
        "continuable_work": ("collect-static-analysis",),
        "expires_at": NOW + timedelta(hours=1),
        "cancellation_policy": "Auto-cancel if operator responds with context that removes risk",
        "escalation_policy": "Escalate to founder if unresolved after 30 minutes",
        "requested_at": NOW,
    }
    values.update(updates)
    return SrlHelpRequest(**values)


def test_help_request_round_trip() -> None:
    request = _help_request()
    assert request.help_class is HelpClass.IRREVERSIBLE_RISK
    assert request.known_facts[0].confidence == 0.95


def test_help_request_missing_required_field() -> None:
    with pytest.raises(ValidationError, match="unsafe_boundary"):
        _help_request(unsafe_boundary="")


def test_help_request_invalid_help_class() -> None:
    with pytest.raises(ValidationError, match="help_class"):
        _help_request(help_class="GUESS")  # type: ignore[arg-type]


def test_known_fact_confidence_bounds() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        KnownFact(
            assertion="x",
            provenance_ref="p",
            confidence=-0.1,
        )


def test_help_budget_round_trip() -> None:
    budget = _budget()
    assert budget.max_requests_per_window == 10
    assert budget.window_seconds == 86400


def test_help_budget_repeated_question_rate_bounds() -> None:
    with pytest.raises(ValidationError, match="max_repeated_question_rate"):
        _budget(max_repeated_question_rate=1.5)


def test_help_budget_window_seconds_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="window_seconds"):
        _budget(window_seconds=0)


def test_help_burden_receipt_round_trip() -> None:
    receipt = HelpBurdenReceipt(
        receipt_id="receipt-1",
        mandate_id="mandate-1",
        window_start=NOW,
        window_end=NOW + timedelta(days=1),
        request_count=5,
        operator_minutes=12,
        repeated_question_rate=0.0,
        longest_unresolved_wait_seconds=300,
        status="WITHIN_BUDGET",
    )
    assert receipt.status == "WITHIN_BUDGET"


def test_help_burden_receipt_invalid_status() -> None:
    with pytest.raises(ValidationError, match="status"):
        HelpBurdenReceipt(
            receipt_id="receipt-1",
            mandate_id="mandate-1",
            window_start=NOW,
            window_end=NOW + timedelta(days=1),
            request_count=5,
            operator_minutes=12,
            repeated_question_rate=0.0,
            longest_unresolved_wait_seconds=300,
            status="UNKNOWN",  # type: ignore[arg-type]
        )


def test_help_burden_receipt_negative_request_count_rejected() -> None:
    with pytest.raises(ValidationError, match="request_count"):
        HelpBurdenReceipt(
            receipt_id="receipt-1",
            mandate_id="mandate-1",
            window_start=NOW,
            window_end=NOW + timedelta(days=1),
            request_count=-1,
            operator_minutes=12,
            repeated_question_rate=0.0,
            longest_unresolved_wait_seconds=300,
            status="EXCEEDED",
        )


def test_help_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="backdoor"):
        _help_request(backdoor="forbidden")


def test_help_response_operator_decision_round_trip() -> None:
    response = SrlHelpResponse(
        help_request_id="help-1",
        responded_at=NOW,
        responder_principal_id="principal-1",
        response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
        decision="APPROVE",
    )
    assert response.decision == "APPROVE"


def test_help_response_operator_decision_requires_decision() -> None:
    with pytest.raises(ValidationError, match="decision"):
        SrlHelpResponse(
            help_request_id="help-1",
            responded_at=NOW,
            responder_principal_id="principal-1",
            response_kind=SrlHelpResponseKind.OPERATOR_DECISION,
        )


def test_help_response_capability_grant_requires_grant_id() -> None:
    with pytest.raises(ValidationError, match="capability_grant_id"):
        SrlHelpResponse(
            help_request_id="help-1",
            responded_at=NOW,
            responder_principal_id="principal-1",
            response_kind=SrlHelpResponseKind.CAPABILITY_GRANT,
        )


def test_help_response_rejects_raw_text_decision() -> None:
    with pytest.raises(ValidationError, match="response_kind"):
        SrlHelpResponse(
            help_request_id="help-1",
            responded_at=NOW,
            responder_principal_id="principal-1",
            response_kind="RAW_TEXT",  # type: ignore[arg-type]
        )


def test_help_response_cancellation_rejects_decision() -> None:
    with pytest.raises(ValidationError, match="decision"):
        SrlHelpResponse(
            help_request_id="help-1",
            responded_at=NOW,
            responder_principal_id="principal-1",
            response_kind=SrlHelpResponseKind.CANCELLATION,
            decision="APPROVE",
        )
