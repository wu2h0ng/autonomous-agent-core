"""SPINE-1 (P5.1b / AR-20260614): the non-bypassable Data Agent grounding invariant.

A formal answer/action may only be produced when the query passed SQL Safety AND the evidence
chain is typed-complete. This is the monorepo-native re-implementation in the domain pack (the
donor's ``TrustedLoopRuntime._assert_grounded``); it would FAIL if the guard were removed or
turned into a no-op.
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.evidence import (
    EvidenceCompleteness,
    assess_evidence_completeness,
)
from domain_packs.data_agent.grounding import (
    GroundingInvariantViolation,
    assert_grounded,
)
from domain_packs.data_agent.runtime import DataSQLSafetyChecker

_SAFE_SQL = (
    "select order_date, sum(paid_amount) as gmv from sales.orders "
    "where order_date >= :start_date and order_date < :end_date limit :limit"
)
_SAFE_PARAMS = ("start_date", "end_date", "limit")
_SAFE_VALUES = {"start_date": "2026-01-01", "end_date": "2026-02-01", "limit": 100}


def _checker() -> DataSQLSafetyChecker:
    return DataSQLSafetyChecker(("sales",), max_limit=1_000)


def _complete_evidence():
    return assess_evidence_completeness(claims=("GMV returned 5 rows",), metric_refs=("gmv:v1",))


def test_grounded_when_sql_is_safe_and_evidence_is_complete() -> None:
    safety = _checker().check(_SAFE_SQL, _SAFE_PARAMS, _SAFE_VALUES)

    assert safety.allowed is True
    assert_grounded(sql_allowed=safety.allowed, evidence=_complete_evidence())


def test_unsafe_sql_refuses_to_ground() -> None:
    safety = _checker().check("delete from sales.orders")

    assert safety.allowed is False
    with pytest.raises(GroundingInvariantViolation, match="SQL Safety did not pass"):
        assert_grounded(sql_allowed=safety.allowed, evidence=_complete_evidence())


def test_incomplete_evidence_refuses_to_ground() -> None:
    safety = _checker().check(_SAFE_SQL, _SAFE_PARAMS, _SAFE_VALUES)
    incomplete = assess_evidence_completeness(claims=(), metric_refs=("gmv:v1",))

    assert incomplete.complete is False
    with pytest.raises(GroundingInvariantViolation, match="incomplete"):
        assert_grounded(sql_allowed=safety.allowed, evidence=incomplete)


def test_guard_checks_sql_before_evidence() -> None:
    """Both conditions must hold; a safe-looking answer with bad SQL still refuses."""
    incomplete = assess_evidence_completeness(claims=(), metric_refs=())
    with pytest.raises(GroundingInvariantViolation, match="SQL Safety did not pass"):
        assert_grounded(sql_allowed=False, evidence=incomplete)


def test_internally_inconsistent_completeness_is_refused() -> None:
    """A fabricated complete=True with missing requirements cannot be constructed."""
    with pytest.raises(ValueError):
        EvidenceCompleteness(complete=True, missing=("claims",))
    with pytest.raises(ValueError):
        EvidenceCompleteness(complete=False, missing=())
