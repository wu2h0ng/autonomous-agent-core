"""Client-side pacing for model calls.

The adapter already retried retryable failures and honoured a server's
``Retry-After``, but nothing paced the client's *own* calls: a loop that called
the provider back to back went out at full speed, and a 429 only held back the
retry of the call that received it - the next call went straight back at the
provider that had just asked for quiet. This module adds the three bounds an
operator can actually observe:

- a per-provider token bucket (``AGENT_OS_PROVIDER_RATE_LIMIT_RPS`` /
  ``AGENT_OS_PROVIDER_RATE_LIMIT_BURST``): calls over the rate wait locally;
- a per-provider concurrency bound (``AGENT_OS_PROVIDER_MAX_CONCURRENCY``);
- a cross-call 429 cooldown: after a rate-limited failure the provider defers
  *other* calls for the server's own ``Retry-After`` window (still bounded by
  ``AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS``, default 30 s), so a slow-down
  instruction outlives the call that carried it.

Honesty rules: a throttle is never silent. A call that has to wait reports the
wait it took (``RateLimitLease.waited_seconds``), and a call whose wait would
exceed ``AGENT_OS_PROVIDER_RATE_LIMIT_MAX_WAIT_SECONDS`` is refused with
``LocalRateLimitRejection`` instead of stalling the turn - the adapter turns that
into a typed ``LOCAL_RATE_LIMITED`` failure, and no provider request is made.
A refused call therefore has no provider latency to report: its record is
flagged unsent (``provider_request: false``) and carries no ``latency_ms``, so
the operator's latency distribution counts only calls that actually went out.
The refusal is counted in ``local_rejections`` and any time the call spent
waiting locally before the refusal goes to the local-wait field - never into
``latency_ms``.

State lives in :class:`ProviderRateLimitState`, which is shared process-wide so
that two adapters over one provider identity (a reconfigure builds a new
instance) defer to the same cooldown. The clock and the sleep function are
constructor arguments, and the defaults are bound at import: a monkeypatched
timer must not be able to silently disable pacing.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

RATE_LIMIT_RPS_ENV = "AGENT_OS_PROVIDER_RATE_LIMIT_RPS"
RATE_LIMIT_BURST_ENV = "AGENT_OS_PROVIDER_RATE_LIMIT_BURST"
MAX_CONCURRENCY_ENV = "AGENT_OS_PROVIDER_MAX_CONCURRENCY"
MAX_WAIT_ENV = "AGENT_OS_PROVIDER_RATE_LIMIT_MAX_WAIT_SECONDS"
COOLDOWN_FLOOR_ENV = "AGENT_OS_PROVIDER_429_COOLDOWN_SECONDS"
RETRY_AFTER_CAP_ENV = "AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS"

# A coding session makes a handful of calls per turn, so 20/s is far above any
# legitimate burst and still a real ceiling on a runaway loop. 0 disables the
# rate limit; the concurrency bound can be disabled the same way.
DEFAULT_REQUESTS_PER_SECOND = 20.0
DEFAULT_BURST = 40
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_MAX_WAIT_SECONDS = 30.0
DEFAULT_COOLDOWN_FLOOR_SECONDS = 0.0
DEFAULT_RETRY_AFTER_CAP_SECONDS = 30.0

# Below this, sleeping only serializes callers without pacing anything.
_EPSILON_SECONDS = 1e-4
# Bounded re-check loop: a concurrent 429 can extend a cooldown while we sleep.
_MAX_WAIT_ITERATIONS = 4

REASON_RATE_LIMIT = "rate_limit"
REASON_COOLDOWN = "cooldown"
REASON_CONCURRENCY = "concurrency"

_MONOTONIC = time.monotonic
_SLEEP = time.sleep


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _float_setting(
    environ: Mapping[str, str], name: str, default: float
) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _int_setting(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


def retry_after_cap_seconds(environ: Mapping[str, str] | None = None) -> float:
    """The most silence a provider may ask for, in seconds.

    A provider (or anything in front of it) can otherwise ask for an hour of
    silence and the turn would sit there; the cap keeps the server's pacing
    advisory rather than a way to stall the operator.
    """

    configured = _float_setting(
        _environ(environ), RETRY_AFTER_CAP_ENV, DEFAULT_RETRY_AFTER_CAP_SECONDS
    )
    if configured < 0:
        return DEFAULT_RETRY_AFTER_CAP_SECONDS
    return configured


@dataclass(frozen=True)
class ClientRateLimitConfig:
    """The client's own pacing bounds for one provider identity."""

    requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND
    burst: int = DEFAULT_BURST
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS
    cooldown_floor_seconds: float = DEFAULT_COOLDOWN_FLOOR_SECONDS

    @property
    def rate_limited(self) -> bool:
        return self.requests_per_second > 0 and self.burst >= 1

    def describe(self, reason: str) -> str:
        if reason == REASON_CONCURRENCY:
            return f"{self.max_concurrency} concurrent calls"
        if reason == REASON_COOLDOWN:
            return "the provider's own Retry-After window"
        return f"{self.requests_per_second:g} requests/second (burst {self.burst})"


def client_rate_limit_config_from_env(
    environ: Mapping[str, str] | None = None,
) -> ClientRateLimitConfig:
    """Read the pacing configuration, falling back to usable defaults.

    An unusable value (a typo, a negative burst) falls back to the default
    rather than to "unlimited": a misconfiguration must not silently remove the
    ceiling. A negative rate is an explicit zero (disabled).
    """

    values = _environ(environ)
    rate = _float_setting(
        values, RATE_LIMIT_RPS_ENV, DEFAULT_REQUESTS_PER_SECOND
    )
    if rate < 0:
        rate = 0.0
    burst = _int_setting(values, RATE_LIMIT_BURST_ENV, DEFAULT_BURST)
    if burst < 1:
        burst = DEFAULT_BURST
    concurrency = _int_setting(
        values, MAX_CONCURRENCY_ENV, DEFAULT_MAX_CONCURRENCY
    )
    if concurrency < 0:
        concurrency = DEFAULT_MAX_CONCURRENCY
    max_wait = _float_setting(
        values, MAX_WAIT_ENV, DEFAULT_MAX_WAIT_SECONDS
    )
    if max_wait < 0:
        max_wait = 0.0
    floor = _float_setting(
        values, COOLDOWN_FLOOR_ENV, DEFAULT_COOLDOWN_FLOOR_SECONDS
    )
    if floor < 0:
        floor = 0.0
    return ClientRateLimitConfig(
        requests_per_second=rate,
        burst=burst,
        max_concurrency=concurrency,
        max_wait_seconds=max_wait,
        cooldown_floor_seconds=floor,
    )


class LocalRateLimitRejection(RuntimeError):
    """The client's own pacing bound refused the call before it was sent.

    Raised instead of stalling a turn for longer than the operator allowed. The
    adapter reports it as a typed ``LOCAL_RATE_LIMITED`` failure, so the cause
    ("our own limit", not the provider's) is named to the operator and no
    provider request is made.
    """

    def __init__(
        self,
        *,
        reason: str,
        required_wait_seconds: float,
        key: str,
        config: ClientRateLimitConfig,
    ) -> None:
        self.reason = reason
        self.required_wait_seconds = required_wait_seconds
        self.key = key
        self.limit = config.describe(reason)
        self.max_wait_seconds = config.max_wait_seconds
        super().__init__(
            f"client-side {self.limit} for provider {key} would hold this call "
            f"for {required_wait_seconds:.1f}s, above the "
            f"{config.max_wait_seconds:.1f}s wait bound; the call was not sent"
        )


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass
class RateLimitLease:
    """A granted slot: what it cost the caller, and how to give it back."""

    waited_seconds: float = 0.0
    reason: str | None = None
    _release: Callable[[], None] | None = field(default=None, repr=False)

    def release(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()

    def __enter__(self) -> RateLimitLease:
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.release()
        return False


class ProviderRateLimitState:
    """Mutable pacing state, keyed by provider identity.

    One instance is shared by every adapter in a process (see
    :func:`shared_rate_limit_state`), which is what makes a 429 defer the *other*
    call: the cooldown is a property of the provider, not of the adapter object
    that happened to receive the 429.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = _MONOTONIC,
        sleeper: Callable[[float], None] = _SLEEP,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.RLock()
        self._buckets: dict[str, _Bucket] = {}
        self._cooldown_until: dict[str, float] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}

    def reserve(
        self,
        key: str,
        config: ClientRateLimitConfig,
        *,
        defer_to_cooldown: bool = True,
    ) -> RateLimitLease:
        """Wait (bounded) for a slot, or refuse the call.

        ``defer_to_cooldown`` is False for a retry of the call that received the
        429: that call has already honoured the server's instruction through its
        own bounded backoff, and waiting a second time would double the delay.
        Other calls defer.
        """

        waited = 0.0
        required = 0.0
        reason: str | None = None
        for _iteration in range(_MAX_WAIT_ITERATIONS):
            now = self._clock()
            with self._lock:
                rate_wait = self._rate_wait_locked(key, config, now)
                cooldown_wait = (
                    max(0.0, self._cooldown_until.get(key, 0.0) - now)
                    if defer_to_cooldown
                    else 0.0
                )
                required = max(rate_wait, cooldown_wait)
                if required <= _EPSILON_SECONDS:
                    self._charge_locked(key, config, now)
                    break
                if waited + required > config.max_wait_seconds:
                    raise LocalRateLimitRejection(
                        reason=(
                            REASON_COOLDOWN
                            if cooldown_wait >= rate_wait
                            else REASON_RATE_LIMIT
                        ),
                        required_wait_seconds=required,
                        key=key,
                        config=config,
                    )
            reason = (
                REASON_COOLDOWN if cooldown_wait >= rate_wait else REASON_RATE_LIMIT
            )
            self._sleeper(required)
            waited += required
        else:  # pragma: no cover - the loop drains its iterations and refuses
            raise LocalRateLimitRejection(
                reason=REASON_RATE_LIMIT,
                required_wait_seconds=required,
                key=key,
                config=config,
            )
        release = self._acquire_concurrency(key, config, waited)
        return RateLimitLease(waited_seconds=waited, reason=reason, _release=release)

    def note_rate_limited(
        self,
        key: str,
        config: ClientRateLimitConfig,
        retry_after_seconds: float | None,
        *,
        cap_seconds: float | None = None,
    ) -> float:
        """Record a 429: other calls to this provider wait out ``applied`` seconds.

        The server's own instruction wins, the configured floor covers a
        provider that sends no header, and the cap still bounds both. Returns the
        cooldown actually applied, so the caller can log what was decided rather
        than what was asked for.
        """

        cap = retry_after_cap_seconds() if cap_seconds is None else cap_seconds
        if retry_after_seconds is None or not math.isfinite(retry_after_seconds):
            applied = config.cooldown_floor_seconds
        else:
            applied = max(float(retry_after_seconds), config.cooldown_floor_seconds)
        applied = min(max(0.0, applied), max(0.0, cap))
        if applied <= 0.0:
            return 0.0
        with self._lock:
            self._cooldown_until[key] = self._clock() + applied
        return applied

    def cooldown_remaining(self, key: str) -> float:
        with self._lock:
            until = self._cooldown_until.get(key)
        if until is None:
            return 0.0
        return max(0.0, until - self._clock())

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._cooldown_until.clear()
            self._semaphores.clear()

    def _rate_wait_locked(
        self, key: str, config: ClientRateLimitConfig, now: float
    ) -> float:
        if not config.rate_limited:
            return 0.0
        bucket = self._buckets.get(key)
        if bucket is None:
            return 0.0
        tokens = min(
            float(config.burst),
            bucket.tokens + (now - bucket.updated_at) * config.requests_per_second,
        )
        if tokens >= 1.0:
            return 0.0
        return (1.0 - tokens) / config.requests_per_second

    def _charge_locked(
        self, key: str, config: ClientRateLimitConfig, now: float
    ) -> None:
        if not config.rate_limited:
            return
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = _Bucket(
                tokens=max(0.0, float(config.burst) - 1.0), updated_at=now
            )
            return
        tokens = min(
            float(config.burst),
            bucket.tokens + (now - bucket.updated_at) * config.requests_per_second,
        )
        if tokens >= 1.0:
            bucket.tokens = tokens - 1.0
            bucket.updated_at = now
            return
        # The caller was let through by a race; debit the slot it took so the
        # bucket still ends up one token poorer.
        deficit = 1.0 - tokens
        bucket.tokens = 0.0
        bucket.updated_at = now + deficit / config.requests_per_second

    def _acquire_concurrency(
        self, key: str, config: ClientRateLimitConfig, already_waited: float
    ) -> Callable[[], None] | None:
        if config.max_concurrency <= 0:
            return None
        semaphore = self._semaphore(key, config)
        remaining = max(0.0, config.max_wait_seconds - already_waited)
        if not semaphore.acquire(timeout=remaining):
            raise LocalRateLimitRejection(
                reason=REASON_CONCURRENCY,
                required_wait_seconds=remaining,
                key=key,
                config=config,
            )
        return semaphore.release

    def _semaphore(
        self, key: str, config: ClientRateLimitConfig
    ) -> threading.BoundedSemaphore:
        with self._lock:
            semaphore = self._semaphores.get(key)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(config.max_concurrency)
                self._semaphores[key] = semaphore
            return semaphore


class ProviderRateLimitGate:
    """A :class:`ProviderRateLimitState` bound to one configuration.

    The adapter holds a gate; the state behind it is process-wide, so a
    reconfigure (a new adapter object for the same provider) does not forget a
    cooldown the provider just asked for.
    """

    def __init__(
        self,
        config: ClientRateLimitConfig | None = None,
        *,
        state: ProviderRateLimitState | None = None,
    ) -> None:
        self._config = (
            config if config is not None else client_rate_limit_config_from_env()
        )
        self._state = state if state is not None else shared_rate_limit_state()

    @property
    def config(self) -> ClientRateLimitConfig:
        return self._config

    @property
    def state(self) -> ProviderRateLimitState:
        return self._state

    def reserve(
        self, key: str, *, defer_to_cooldown: bool = True
    ) -> RateLimitLease:
        return self._state.reserve(
            key, self._config, defer_to_cooldown=defer_to_cooldown
        )

    def note_rate_limited(
        self,
        key: str,
        retry_after_seconds: float | None,
        *,
        cap_seconds: float | None = None,
    ) -> float:
        return self._state.note_rate_limited(
            key, self._config, retry_after_seconds, cap_seconds=cap_seconds
        )

    def cooldown_remaining(self, key: str) -> float:
        return self._state.cooldown_remaining(key)


_SHARED_LOCK = threading.Lock()
_SHARED_STATE: ProviderRateLimitState | None = None


def shared_rate_limit_state() -> ProviderRateLimitState:
    """The process-wide pacing state, created on first use."""

    global _SHARED_STATE
    with _SHARED_LOCK:
        if _SHARED_STATE is None:
            _SHARED_STATE = ProviderRateLimitState()
        return _SHARED_STATE


def reset_shared_rate_limit_state() -> None:
    """Test hook: drop the shared state so the next use starts empty."""

    global _SHARED_STATE
    with _SHARED_LOCK:
        state, _SHARED_STATE = _SHARED_STATE, None
    if state is not None:
        state.reset()


def rate_limit_key(provider_id: str, base_url: str) -> str:
    """Provider identity used for buckets and cooldowns.

    The credential is never part of it: two keys (or a rotated key) against the
    same endpoint are the same provider, and the key must stay out of anything an
    operator can read back.
    """

    return f"{provider_id}|{base_url}"


__all__ = [
    "COOLDOWN_FLOOR_ENV",
    "ClientRateLimitConfig",
    "DEFAULT_BURST",
    "DEFAULT_COOLDOWN_FLOOR_SECONDS",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_WAIT_SECONDS",
    "DEFAULT_REQUESTS_PER_SECOND",
    "DEFAULT_RETRY_AFTER_CAP_SECONDS",
    "LocalRateLimitRejection",
    "MAX_CONCURRENCY_ENV",
    "MAX_WAIT_ENV",
    "ProviderRateLimitGate",
    "ProviderRateLimitState",
    "RATE_LIMIT_BURST_ENV",
    "RATE_LIMIT_RPS_ENV",
    "RETRY_AFTER_CAP_ENV",
    "RateLimitLease",
    "client_rate_limit_config_from_env",
    "rate_limit_key",
    "reset_shared_rate_limit_state",
    "retry_after_cap_seconds",
    "shared_rate_limit_state",
]
