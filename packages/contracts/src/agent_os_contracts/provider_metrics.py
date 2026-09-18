"""Typed read-out of the provider boundary: what a session actually did.

One shape for the aggregated answer to "how many calls, how slow, how many
retries, which failures", served by ``GET /v1/surface/observability/metrics``
and produced by ``agent_os_core.provider_metrics``.

Content boundary, by construction: these models have no field that can carry a
prompt, a completion, an argument payload or a credential - the aggregate is a
count/latency/token/code summary of the *same* content-free records the opt-in
provider log (``AGENT_OS_PROVIDER_LOG``) already writes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel, UtcDateTime
from .provider import ProviderErrorCode


class ProviderFailureCategory(ContractModel):
    """One failure code and how often it happened in the window."""

    code: ProviderErrorCode
    count: int = Field(ge=0)
    retryable: bool


class ProviderLatencyStats(ContractModel):
    """Attempt latency in milliseconds, for calls that reached the provider.

    ``samples`` counts exactly the calls that were sent: a call the client's own
    rate limit refused locally was never sent, contributes no latency and is
    reported in ``ProviderRateLimitStats.local_rejections`` instead. ``samples
    == 0`` means the window had no timed provider call, and every statistic is
    ``None`` - never a pseudo-zero latency.
    """

    samples: int = Field(ge=0)
    mean_ms: float | None = None
    p50_ms: float | None = None
    p90_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None


class ProviderTokenTotals(ContractModel):
    """Exact token totals, plus how many attempts reported usage."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    usage_samples: int = Field(ge=0)


class ProviderRateLimitStats(ContractModel):
    """Both directions of rate limiting, kept apart.

    ``rate_limited_attempts``/``retry_after_observed`` are what the *provider*
    said; ``local_*`` is what the *client* did about it (and to itself).

    ``local_rejections`` counts calls the client refused before sending them.
    Such a call may also appear in ``local_waits`` when it waited before the
    refusal, and its wait time is inside ``local_wait_ms_total`` - never inside
    the latency distribution.
    """

    rate_limited_attempts: int = Field(ge=0)
    retry_after_observed: int = Field(ge=0)
    max_retry_after_seconds: float | None = None
    local_waits: int = Field(ge=0)
    local_wait_ms_total: float = Field(ge=0)
    local_wait_ms_max: float = Field(ge=0)
    local_rejections: int = Field(ge=0)


class ProviderMetricsSnapshot(ContractModel):
    """The aggregated provider boundary over a bounded window.

    ``attempts`` counts attempt records, including a call the client refused
    locally (``rate_limit.local_rejections`` names those); ``latency.samples``
    counts only the calls that were actually sent.
    """

    source: Literal["in_process", "log_file"]
    taken_at: UtcDateTime
    window_started_at: UtcDateTime | None = None
    window_ended_at: UtcDateTime | None = None
    window_records: int = Field(ge=0)
    # True when the window is not the whole history (the in-process ledger is
    # bounded, and a log file can be older than what was read).
    window_truncated: bool = False
    # Lines the reader could not use: blank, unparseable, or not provider-attempt
    # records. Reported so a stale or damaged log is visible rather than silently
    # folded into the totals.
    ignored_lines: int = Field(ge=0)
    calls: int = Field(ge=0)
    attempts: int = Field(ge=0)
    responses: int = Field(ge=0)
    failures: int = Field(ge=0)
    retries: int = Field(ge=0)
    latency: ProviderLatencyStats
    tokens: ProviderTokenTotals
    failure_categories: tuple[ProviderFailureCategory, ...] = ()
    rate_limit: ProviderRateLimitStats
