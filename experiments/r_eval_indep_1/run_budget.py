"""Typed, conservative pre-freeze budget fixture for one R-EVAL run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunBudget:
    per_call_input_tokens: int
    per_call_output_tokens: int
    per_call_cost_microusd: int
    per_call_latency_ms: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_microusd: int
    total_latency_ms: int
    wallclock_ms: int
    concurrency: int
    retry_count: int

    def __post_init__(self) -> None:
        values = (
            self.per_call_input_tokens,
            self.per_call_output_tokens,
            self.per_call_cost_microusd,
            self.per_call_latency_ms,
            self.total_input_tokens,
            self.total_output_tokens,
            self.total_cost_microusd,
            self.total_latency_ms,
            self.wallclock_ms,
        )
        if any(value <= 0 for value in values):
            raise ValueError("budget limits must be positive")
        if self.concurrency != 1 or self.retry_count != 0:
            raise ValueError("successor freezes concurrency=1 and retry=0")
        if self.total_input_tokens < self.per_call_input_tokens:
            raise ValueError("total input budget below per-call budget")
        if self.total_output_tokens < self.per_call_output_tokens:
            raise ValueError("total output budget below per-call budget")
        if self.total_cost_microusd < self.per_call_cost_microusd:
            raise ValueError("total cost budget below per-call budget")
        if self.wallclock_ms < self.per_call_latency_ms:
            raise ValueError("wallclock budget below per-call latency")


# A Founder/freezer may accept or replace these constants exactly once before
# freeze. They cannot be mutated after freeze or in response to results.
DEFAULT_RUN_BUDGET = RunBudget(
    per_call_input_tokens=32_000,
    per_call_output_tokens=8_000,
    per_call_cost_microusd=5_000_000,
    per_call_latency_ms=180_000,
    total_input_tokens=14_208_000,
    total_output_tokens=3_552_000,
    total_cost_microusd=2_220_000_000,
    total_latency_ms=79_920_000,
    wallclock_ms=86_400_000,
    concurrency=1,
    retry_count=0,
)
