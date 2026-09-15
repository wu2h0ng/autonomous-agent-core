"""SPINE-1 (ADR-0016): monorepo-native evidence-bound SYMBOLIC ledger consequence preview.

Before an approver decides, Agent Core shows the action's OWN governed history as honest counts:
"this action_type has N prior executions, M of which resolved to the intended outcome". This is
NOT a prediction/model/probability.

Each test is written to FAIL if the derivation is bypassed:
  1. counts come from the injected ledger (a constant/ignored-port impl gives the wrong numbers);
  2. a novel action reports available=False with zero counts (distinguishing "no history" from
     a fabricated "0 of N");
  3. a missing port reports available=False (no crash);
  4. a failing ledger read degrades to available=False (never fabricates, never raises);
  5. last_outcomes is a true most-recent slice in oldest->newest order;
  6. the port is called with the caller's tenant (tenant scoping is the adapter's, proven here by
     observing the argument the derivation forwards).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_os_contracts import ConsequencePreview
from agent_os_core import (
    DEFAULT_LAST_OUTCOMES,
    INTENDED_EXECUTION_OUTCOME,
    ActionHistoryPort,
    build_consequence_preview,
)


class _FakeLedger(ActionHistoryPort):
    """In-memory port that speaks the generic outcome vocabulary, keyed by (tenant, action_type)."""

    def __init__(self, records: dict[tuple[str, str], list[str]] | None = None) -> None:
        self._records = records or {}
        self.calls: list[tuple[str, str]] = []

    def outcomes_for(self, *, action_type: str, tenant_id: str = "default") -> tuple[str, ...]:
        self.calls.append((action_type, tenant_id))
        return tuple(self._records.get((tenant_id, action_type), ()))


class _FailingLedger(ActionHistoryPort):
    def outcomes_for(self, *, action_type: str, tenant_id: str = "default") -> tuple[str, ...]:
        raise RuntimeError("simulated ledger read failure")


def test_counts_are_derived_from_the_ledger() -> None:
    ledger = _FakeLedger({("default", "execute"): ["executed", "executed", "uncertain", "executed", "uncertain"]})

    preview = build_consequence_preview(action_type="execute", history_port=ledger)

    assert preview.available is True
    assert preview.prior_executions == 5
    assert preview.resolved_intended == 3
    assert preview.resolved_other == 2


def test_novel_action_is_unavailable_with_zero_counts() -> None:
    ledger = _FakeLedger({("default", "execute"): ["executed"]})

    preview = build_consequence_preview(action_type="never_seen", history_port=ledger)

    assert preview.available is False
    assert preview.prior_executions == 0
    assert preview.resolved_intended == 0
    assert preview.resolved_other == 0
    assert preview.last_outcomes == ()


def test_missing_port_is_unavailable() -> None:
    preview = build_consequence_preview(action_type="execute", history_port=None)

    assert preview.available is False
    assert preview.prior_executions == 0


def test_failing_ledger_read_degrades_to_unavailable_without_raising() -> None:
    preview = build_consequence_preview(action_type="execute", history_port=_FailingLedger())

    assert preview.available is False
    assert preview.prior_executions == 0


def test_last_outcomes_is_a_true_recency_slice_oldest_to_newest() -> None:
    outcomes = [INTENDED_EXECUTION_OUTCOME, "uncertain", INTENDED_EXECUTION_OUTCOME, "uncertain"]
    ledger = _FakeLedger({("default", "execute"): outcomes})

    preview = build_consequence_preview(action_type="execute", history_port=ledger, last_k=2)

    assert preview.last_outcomes == ("executed", "uncertain")
    assert preview.last_outcomes == tuple(outcomes[-2:])


def test_default_last_outcomes_window_is_bounded() -> None:
    ledger = _FakeLedger({("default", "execute"): [INTENDED_EXECUTION_OUTCOME] * 9})

    preview = build_consequence_preview(action_type="execute", history_port=ledger)

    assert len(preview.last_outcomes) == DEFAULT_LAST_OUTCOMES


def test_port_receives_the_callers_tenant() -> None:
    ledger = _FakeLedger({("acme", "execute"): ["executed"], ("default", "execute"): ["executed"] * 4})

    tenant_preview = build_consequence_preview(action_type="execute", history_port=ledger, tenant_id="acme")
    other_preview = build_consequence_preview(action_type="execute", history_port=ledger, tenant_id="default")

    assert tenant_preview.prior_executions == 1
    assert other_preview.prior_executions == 4
    assert ("execute", "acme") in ledger.calls


def test_unavailable_preview_cannot_carry_counts() -> None:
    with pytest.raises(ValidationError):
        ConsequencePreview(action_type="execute", available=False, prior_executions=3)


def test_counts_must_reconcile() -> None:
    with pytest.raises(ValidationError):
        ConsequencePreview(
            action_type="execute",
            available=True,
            prior_executions=5,
            resolved_intended=1,
            resolved_other=1,
        )
