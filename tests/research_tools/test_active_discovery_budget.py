from __future__ import annotations

import pytest

from research_tools.active_discovery.budget import BudgetExceeded, BudgetLedger


def test_budget_exhaustion_does_not_append_a_receipt() -> None:
    ledger = BudgetLedger(limit_units=2)
    first = ledger.reserve("probe-1", 2)

    assert first.remaining_units == 0
    with pytest.raises(BudgetExceeded, match="exceeds remaining budget"):
        ledger.reserve("probe-2", 1)

    assert ledger.consumed_units == 2
    assert tuple(receipt.operation_id for receipt in ledger.receipts) == ("probe-1",)


def _ledger_digest(
    *,
    limit_units: int = 4,
    operations: tuple[tuple[str, int], ...] = (("probe-1", 1), ("probe-2", 1)),
) -> str:
    ledger = BudgetLedger(limit_units=limit_units)
    for operation_id, cost_units in operations:
        ledger.reserve(operation_id, cost_units)
    return ledger.ledger_digest


def test_ledger_digest_is_stable_and_binds_budget_and_receipt_content() -> None:
    baseline = _ledger_digest()
    equivalent = _ledger_digest()
    variants = (
        _ledger_digest(limit_units=5),
        _ledger_digest(operations=(("probe-x", 1), ("probe-2", 1))),
        _ledger_digest(operations=(("probe-1", 2), ("probe-2", 1))),
        _ledger_digest(operations=(("probe-2", 1), ("probe-1", 1))),
    )

    assert equivalent == baseline
    assert all(variant != baseline for variant in variants)
