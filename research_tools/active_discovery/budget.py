from __future__ import annotations

from dataclasses import asdict, dataclass

from .canonical import content_digest


class BudgetError(ValueError):
    """Base class for hard probe-budget failures."""


class BudgetExceeded(BudgetError):
    """A reservation would exceed the frozen hard budget."""


class DuplicateBudgetOperation(BudgetError):
    """An operation id was already charged."""


@dataclass(frozen=True, slots=True)
class BudgetReceipt:
    sequence: int
    operation_id: str
    charged_units: int
    consumed_units: int
    remaining_units: int
    prior_receipt_digest: str | None
    receipt_digest: str


class BudgetLedger:
    """Append-only exact-integer budget ledger."""

    def __init__(self, limit_units: int) -> None:
        if (
            isinstance(limit_units, bool)
            or not isinstance(limit_units, int)
            or limit_units < 0
        ):
            raise BudgetError("limit_units must be an integer >= 0")
        self._limit_units = limit_units
        self._receipts: tuple[BudgetReceipt, ...] = ()
        self._operation_ids: frozenset[str] = frozenset()

    @property
    def limit_units(self) -> int:
        return self._limit_units

    @property
    def receipts(self) -> tuple[BudgetReceipt, ...]:
        return self._receipts

    @property
    def consumed_units(self) -> int:
        return sum(receipt.charged_units for receipt in self._receipts)

    @property
    def remaining_units(self) -> int:
        return self._limit_units - self.consumed_units

    def reserve(self, operation_id: str, cost_units: int) -> BudgetReceipt:
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise BudgetError("operation_id must be a non-empty string")
        if operation_id in self._operation_ids:
            raise DuplicateBudgetOperation(operation_id)
        if (
            isinstance(cost_units, bool)
            or not isinstance(cost_units, int)
            or cost_units < 1
        ):
            raise BudgetError("cost_units must be an integer >= 1")
        if cost_units > self.remaining_units:
            raise BudgetExceeded(
                f"operation {operation_id!r} exceeds remaining budget "
                f"({cost_units} > {self.remaining_units})"
            )

        sequence = len(self._receipts)
        consumed = self.consumed_units + cost_units
        prior = self._receipts[-1].receipt_digest if self._receipts else None
        payload = {
            "sequence": sequence,
            "operation_id": operation_id,
            "charged_units": cost_units,
            "consumed_units": consumed,
            "remaining_units": self._limit_units - consumed,
            "prior_receipt_digest": prior,
        }
        receipt = BudgetReceipt(
            **payload,
            receipt_digest=content_digest("budget-receipt", payload),
        )
        self._receipts = (*self._receipts, receipt)
        self._operation_ids = self._operation_ids | {operation_id}
        return receipt

    @property
    def ledger_digest(self) -> str:
        return content_digest(
            "budget-ledger",
            {
                "limit_units": self._limit_units,
                "receipts": [asdict(receipt) for receipt in self._receipts],
            },
        )
