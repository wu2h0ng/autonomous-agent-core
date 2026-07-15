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
