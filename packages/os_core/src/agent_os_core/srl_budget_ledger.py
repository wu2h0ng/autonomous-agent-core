from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from agent_os_contracts import (
    EnvironmentBinding,
    HelpBudget,
    HelpBurdenReceipt,
    SrlHelpRequest,
)

from .srl_ports import BudgetEnforcementPort, BudgetStatus


@dataclass
class _BindingBudget:
    wake_used: int = 0
    query_used: int = 0
    halted: bool = False


@dataclass
class _HelpWindow:
    budget: HelpBudget | None = None
    requests: list[SrlHelpRequest] = field(default_factory=list)
    operator_minutes: int = 0


class InMemoryBudgetLedger(BudgetEnforcementPort):
    """In-memory wake/query/help budget ledger separate from dispatch."""

    durable = False

    def __init__(self, *, now: datetime | None = None) -> None:
        self._lock = RLock()
        self._binding_budgets: dict[str, _BindingBudget] = defaultdict(_BindingBudget)
        self._help_windows: dict[str, _HelpWindow] = defaultdict(_HelpWindow)
        self._clock = now or datetime.now(timezone.utc)

    def set_help_budget(self, mandate_id: str, budget: HelpBudget) -> None:
        with self._lock:
            self._help_windows[mandate_id].budget = budget

    def check_binding_budget(self, binding: EnvironmentBinding) -> BudgetStatus:
        with self._lock:
            budget = self._binding_budgets[binding.binding_id]
            # M0: each check consumes one wake unit.
            budget.wake_used += 1
            if budget.halted:
                return BudgetStatus(
                    binding_id=binding.binding_id,
                    status="HALTED",
                    remaining_wake=0,
                    remaining_query=0,
                )
            remaining_wake = max(0, binding.wake_budget_per_window - budget.wake_used)
            remaining_query = max(
                0, binding.query_budget_per_window - budget.query_used
            )
            status: Any = (
                "WITHIN_BUDGET"
                if remaining_wake > 0 and remaining_query > 0
                else "EXHAUSTED"
            )
            return BudgetStatus(
                binding_id=binding.binding_id,
                status=status,
                remaining_wake=remaining_wake,
                remaining_query=remaining_query,
            )

    def consume_wake(self, binding_id: str) -> None:
        with self._lock:
            self._binding_budgets[binding_id].wake_used += 1

    def consume_query(self, binding_id: str) -> None:
        with self._lock:
            self._binding_budgets[binding_id].query_used += 1

    def halt_binding(self, binding_id: str) -> None:
        with self._lock:
            self._binding_budgets[binding_id].halted = True

    def charge_help(self, help_request: SrlHelpRequest) -> HelpBurdenReceipt:
        with self._lock:
            window = self._help_windows[help_request.mandate_id]
            window.requests.append(help_request)
            return self._compute_receipt(help_request.mandate_id)

    def _compute_receipt(self, mandate_id: str) -> HelpBurdenReceipt:
        window = self._help_windows[mandate_id]
        # In-memory stub uses a fixed window anchored at self._clock.
        window_start = self._clock
        window_end = window_start + timedelta(days=1)
        request_count = len(window.requests)
        # Repeated-question rate is computed as fraction of requests sharing the
        # same minimum_answer as the most recent request.
        if not window.requests:
            repeated_rate = 0.0
        else:
            last_minimum = window.requests[-1].minimum_answer
            repeats = sum(
                1 for r in window.requests if r.minimum_answer == last_minimum
            )
            repeated_rate = repeats / request_count
        budget = window.budget
        exceeded = budget is not None and request_count > budget.max_requests_per_window
        status: Any = "EXCEEDED" if exceeded else "WITHIN_BUDGET"
        return HelpBurdenReceipt(
            receipt_id=f"help-burden:{mandate_id}:{request_count}",
            mandate_id=mandate_id,
            window_start=window_start,
            window_end=window_end,
            request_count=request_count,
            operator_minutes=window.operator_minutes,
            repeated_question_rate=repeated_rate,
            longest_unresolved_wait_seconds=0,
            status=status,
        )

    def receipt_for(self, mandate_id: str) -> HelpBurdenReceipt:
        with self._lock:
            return self._compute_receipt(mandate_id)
