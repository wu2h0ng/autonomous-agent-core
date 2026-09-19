"""Aggregate the provider boundary into one typed, content-free snapshot.

The adapter already writes one content-free record per model call attempt to the
opt-in operator log (``AGENT_OS_PROVIDER_LOG``, JSONL). That data answered "how
long, how many tokens, which failure" only if the operator read the file by
hand. This module turns the same records into a
:class:`~agent_os_contracts.ProviderMetricsSnapshot`: call/attempt/response/
failure/retry counts, a latency distribution, exact token totals, failure
categories and both directions of rate limiting.

Two readers, one record stream - which is what makes the numbers trustworthy:

- :class:`ProviderMetricsLedger` keeps a bounded window of the records this
  process produced, so a running daemon can serve metrics without the log
  variable being set;
- :func:`read_provider_log` reads the operator's own file and
  :func:`aggregate_provider_metrics` aggregates it offline.

Both consume the identical dict the adapter writes, so they cannot drift, and a
test pins that they agree on the same calls.

One rule keeps the latency distribution honest: a sample is admitted only for a
call that actually reached the provider.

- A call the client's own rate limit refused locally was never sent, so its
  record says ``provider_request: false`` and carries no ``latency_ms``. It
  contributes no sample; its cost is reported where it belongs, in
  ``rate_limit.local_rejections`` (and, if it waited before being refused, in
  ``local_waits``), because "we did not call, we waited" is not "the provider
  was slow".
- A call that waited locally and then went out contributes exactly its request
  time: the local wait is reported on ``local_rate_limit_wait_ms`` and is never
  added into ``latency_ms``, so a cooldown cannot read as a slow provider.
- A record that says nothing either way is treated as a sent call, so a foreign
  line is still aggregated rather than silently dropped.
- ``attempts`` and ``failures`` still count every attempt record, a locally
  refused call included (it also appears in ``rate_limit.local_rejections``):
  the window's volume is the whole story, and only the latency distribution is
  restricted to the calls that were sent. On the adapter's own records the two
  therefore differ by exactly the refusals; a foreign line without a latency
  widens that gap without being an error.

Content boundary: only the numeric/categorical fields of a record are read, so a
prompt, a completion, a tool payload or a credential can neither be stored nor
surfaced here - even if a foreign record carried those keys.
"""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    ProviderErrorCode,
    ProviderFailureCategory,
    ProviderLatencyStats,
    ProviderMetricsSnapshot,
    ProviderRateLimitStats,
    ProviderTokenTotals,
)

ATTEMPT_EVENT = "provider_attempt"
# Every attempt record states whether the call was sent to the provider. The
# adapter writes False - with no ``latency_ms`` - for a call its own rate limit
# refused before any request was made, and this aggregator admits a latency
# sample only for the others. Held here because this module owns what the record
# stream means; the adapter imports it rather than repeating the spelling.
PROVIDER_REQUEST_KEY = "provider_request"
# The refusal marker itself, read as a second, independent statement that no
# request was made: a record that carries it is out of the latency distribution
# even if it also carries a latency (a hand-written or foreign line).
LOCAL_REJECTION_KEY = "local_rate_limit_rejected"
DEFAULT_LEDGER_LIMIT = 4096

# Percentiles are nearest-rank on the sorted samples: with few attempts (a
# session makes tens, not thousands) an interpolated percentile would invent a
# latency no call ever had.
_PERCENTILES: tuple[tuple[str, float], ...] = (
    ("p50_ms", 0.50),
    ("p90_ms", 0.90),
    ("p95_ms", 0.95),
)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nearest_rank(samples: list[float], fraction: float) -> float:
    rank = max(1, math.ceil(fraction * len(samples)))
    return samples[min(rank, len(samples)) - 1]


def _reached_the_provider(record: Mapping[str, Any]) -> bool:
    """Whether this record describes a call that actually went out.

    Two fields can say "no request was made": ``provider_request: false``, which
    the adapter writes on a call its own rate limit refused, and
    ``local_rate_limit_rejected: true``, which states the same thing for a record
    that omits the first field (a hand-written line, or a writer that forgets
    it). Either one keeps the record out of the latency distribution; a record
    that states neither is treated as a sent call, so a foreign line is still
    aggregated rather than silently dropped.
    """

    if record.get(PROVIDER_REQUEST_KEY) is False:
        return False
    return record.get(LOCAL_REJECTION_KEY) is not True


def _latency_stats(samples: list[float]) -> ProviderLatencyStats:
    if not samples:
        return ProviderLatencyStats(samples=0)
    ordered = sorted(samples)
    p50, p90, p95 = (
        _nearest_rank(ordered, fraction) for _name, fraction in _PERCENTILES
    )
    return ProviderLatencyStats(
        samples=len(ordered),
        mean_ms=sum(ordered) / len(ordered),
        p50_ms=p50,
        p90_ms=p90,
        p95_ms=p95,
        max_ms=ordered[-1],
    )


@dataclass
class _Aggregate:
    request_ids: set[str] = field(default_factory=set)
    attempts: int = 0
    responses: int = 0
    failures: int = 0
    retries: int = 0
    latencies: list[float] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_samples: int = 0
    failure_counts: dict[ProviderErrorCode, int] = field(default_factory=dict)
    failure_retryable: dict[ProviderErrorCode, bool] = field(default_factory=dict)
    rate_limited_attempts: int = 0
    retry_after_observed: int = 0
    max_retry_after_seconds: float | None = None
    local_waits: int = 0
    local_wait_ms_total: float = 0.0
    local_wait_ms_max: float = 0.0
    local_rejections: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def absorb(self, record: Mapping[str, Any]) -> None:
        request_id = record.get("request_id")
        if isinstance(request_id, str) and request_id.strip():
            self.request_ids.add(request_id.strip())
        self.attempts += 1
        attempt_index = _as_int(record.get("attempt")) or 0
        if attempt_index > 0:
            self.retries += 1
        # Only a call that reached the provider has a provider latency to
        # contribute; a locally refused call is counted as a rejection instead
        # of being averaged in as a ~0 ms sample.
        if _reached_the_provider(record):
            latency = _as_float(record.get("latency_ms"))
            if latency is not None and latency >= 0:
                self.latencies.append(latency)
        timestamp = _as_timestamp(record.get("ts"))
        if timestamp is not None:
            if self.started_at is None or timestamp < self.started_at:
                self.started_at = timestamp
            if self.ended_at is None or timestamp > self.ended_at:
                self.ended_at = timestamp
        outcome = record.get("outcome")
        if outcome == "response":
            self.responses += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                value = _as_int(record.get(key))
                if value is not None and value >= 0:
                    setattr(self, key, getattr(self, key) + value)
            self.usage_samples += 1
        elif outcome == "failure":
            self.failures += 1
            code = self._code(record.get("code"))
            if code is not None:
                self.failure_counts[code] = self.failure_counts.get(code, 0) + 1
                self.failure_retryable[code] = bool(record.get("retryable"))
                if code is ProviderErrorCode.RATE_LIMITED:
                    self.rate_limited_attempts += 1
        retry_after = _as_float(record.get("retry_after_seconds"))
        if retry_after is not None and retry_after >= 0:
            self.retry_after_observed += 1
            if (
                self.max_retry_after_seconds is None
                or retry_after > self.max_retry_after_seconds
            ):
                self.max_retry_after_seconds = retry_after
        wait_ms = _as_float(record.get("local_rate_limit_wait_ms"))
        if wait_ms is not None and wait_ms > 0:
            self.local_waits += 1
            self.local_wait_ms_total += wait_ms
            self.local_wait_ms_max = max(self.local_wait_ms_max, wait_ms)
        if record.get(LOCAL_REJECTION_KEY) is True:
            self.local_rejections += 1

    @staticmethod
    def _code(value: object) -> ProviderErrorCode | None:
        if not isinstance(value, str):
            return None
        try:
            return ProviderErrorCode(value)
        except ValueError:
            return None

    def snapshot(
        self,
        *,
        source: str,
        window_records: int,
        window_truncated: bool,
        ignored_lines: int,
        taken_at: datetime | None = None,
    ) -> ProviderMetricsSnapshot:
        categories = tuple(
            ProviderFailureCategory(
                code=code, count=count, retryable=self.failure_retryable.get(code, False)
            )
            for code, count in sorted(
                self.failure_counts.items(), key=lambda item: (-item[1], item[0].value)
            )
        )
        return ProviderMetricsSnapshot(
            source=source,  # type: ignore[arg-type]
            taken_at=taken_at or datetime.now(timezone.utc),
            window_started_at=self.started_at,
            window_ended_at=self.ended_at,
            window_records=window_records,
            window_truncated=window_truncated,
            ignored_lines=ignored_lines,
            calls=len(self.request_ids),
            attempts=self.attempts,
            responses=self.responses,
            failures=self.failures,
            retries=self.retries,
            latency=_latency_stats(self.latencies),
            tokens=ProviderTokenTotals(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                total_tokens=self.total_tokens,
                usage_samples=self.usage_samples,
            ),
            failure_categories=categories,
            rate_limit=ProviderRateLimitStats(
                rate_limited_attempts=self.rate_limited_attempts,
                retry_after_observed=self.retry_after_observed,
                max_retry_after_seconds=self.max_retry_after_seconds,
                local_waits=self.local_waits,
                local_wait_ms_total=round(self.local_wait_ms_total, 1),
                local_wait_ms_max=round(self.local_wait_ms_max, 1),
                local_rejections=self.local_rejections,
            ),
        )


def aggregate_provider_metrics(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str = "in_process",
    ignored_lines: int = 0,
    window_truncated: bool = False,
    taken_at: datetime | None = None,
) -> ProviderMetricsSnapshot:
    """Aggregate attempt records into one snapshot.

    Records that are not ``provider_attempt`` events are skipped and counted in
    ``ignored_lines`` alongside whatever the caller already counted, so a foreign
    or damaged stream is visible instead of silently averaged in.
    """

    aggregate = _Aggregate()
    used = 0
    ignored = ignored_lines
    for record in records:
        if not isinstance(record, Mapping) or record.get("event") != ATTEMPT_EVENT:
            ignored += 1
            continue
        aggregate.absorb(record)
        used += 1
    return aggregate.snapshot(
        source=source,
        window_records=used,
        window_truncated=window_truncated,
        ignored_lines=ignored,
        taken_at=taken_at,
    )


@dataclass(frozen=True)
class ProviderLogRecords:
    """What was usable in a provider log file, and how much was not."""

    records: tuple[dict[str, Any], ...]
    ignored_lines: int
    path: Path | None = None


def read_provider_log(path: Path | str) -> ProviderLogRecords:
    """Read the opt-in provider log.

    A blank line, a line that is not JSON (a process killed mid-write leaves a
    partial last line) or a line that is not an object is skipped and counted -
    reading metrics must not fail because of one damaged line, and it must not
    pretend the file was complete either. A missing file is an empty window.
    """

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return ProviderLogRecords(records=(), ignored_lines=0, path=target)
    records: list[dict[str, Any]] = []
    ignored = 0
    for line in text.splitlines():
        if not line.strip():
            ignored += 1
            continue
        try:
            value = json.loads(line)
        except ValueError:
            ignored += 1
            continue
        if not isinstance(value, dict):
            ignored += 1
            continue
        records.append(value)
    return ProviderLogRecords(
        records=tuple(records), ignored_lines=ignored, path=target
    )


class ProviderMetricsLedger:
    """A bounded in-process window of the provider-attempt records."""

    def __init__(self, *, limit: int = DEFAULT_LEDGER_LIMIT) -> None:
        self._limit = max(1, limit)
        self._records: deque[dict[str, Any]] = deque(maxlen=self._limit)
        self._dropped = 0
        self._lock = threading.Lock()

    def record(self, record: Mapping[str, Any]) -> None:
        if record.get("event") != ATTEMPT_EVENT:
            return
        stored = {key: value for key, value in record.items()}
        with self._lock:
            if len(self._records) == self._limit:
                self._dropped += 1
            self._records.append(stored)

    def snapshot(self, *, taken_at: datetime | None = None) -> ProviderMetricsSnapshot:
        with self._lock:
            records = tuple(self._records)
            dropped = self._dropped
        return aggregate_provider_metrics(
            records,
            source="in_process",
            window_truncated=dropped > 0,
            taken_at=taken_at,
        )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._dropped = 0


_LEDGER_LOCK = threading.Lock()
_SHARED_LEDGER: ProviderMetricsLedger | None = None


def shared_provider_metrics_ledger() -> ProviderMetricsLedger:
    """The process-wide ledger the adapters write their attempts to."""

    global _SHARED_LEDGER
    with _LEDGER_LOCK:
        if _SHARED_LEDGER is None:
            _SHARED_LEDGER = ProviderMetricsLedger()
        return _SHARED_LEDGER


def reset_shared_provider_metrics_ledger() -> None:
    """Test hook: drop the shared ledger so the next use starts empty."""

    global _SHARED_LEDGER
    with _LEDGER_LOCK:
        ledger, _SHARED_LEDGER = _SHARED_LEDGER, None
    if ledger is not None:
        ledger.clear()


__all__ = [
    "ATTEMPT_EVENT",
    "DEFAULT_LEDGER_LIMIT",
    "LOCAL_REJECTION_KEY",
    "PROVIDER_REQUEST_KEY",
    "ProviderLogRecords",
    "ProviderMetricsLedger",
    "aggregate_provider_metrics",
    "read_provider_log",
    "reset_shared_provider_metrics_ledger",
    "shared_provider_metrics_ledger",
]
