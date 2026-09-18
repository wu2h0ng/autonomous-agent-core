"""Client-side rate limiting and the cross-call 429 cooldown.

Measured gap (2026-09-18): the adapter had bounded retry and Retry-After
handling, but nothing paced the *client's own* model calls, and a server
instruction to slow down only held back the retry inside the call that received
it - the next call went straight back out. These cases pin the two behaviours
the operator can observe: a call that is throttled locally waits (or is refused
outright when the wait would exceed the bound) and says so, and a 429 defers
other calls to the same provider for the server's own Retry-After window.

Time is injected (`ProviderRateLimitState(clock=..., sleeper=...)`), so the
timing assertions are exact rather than wall-clock dependent. The one case that
needs real time is the concurrency bound, which is a real semaphore.
"""

from __future__ import annotations

import json
import threading
import time as time_module
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
)
from agent_os_core.client_rate_limit import (
    ClientRateLimitConfig,
    LocalRateLimitRejection,
    ProviderRateLimitGate,
    ProviderRateLimitState,
    client_rate_limit_config_from_env,
)
from agent_os_core.provider import EnvCredentialBroker, OpenAICompatibleProvider

_SECRET = "sk-client-rate-limit-DEADBEEF"


class _FakeClock:
    """A monotonic clock that advances exactly when somebody sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0, seconds
        self.sleeps.append(seconds)
        self.now += seconds


def _gate(
    clock: _FakeClock,
    *,
    requests_per_second: float = 1_000.0,
    burst: int = 100,
    max_concurrency: int = 0,
    max_wait_seconds: float = 30.0,
    cooldown_floor_seconds: float = 0.0,
) -> tuple[ProviderRateLimitGate, ProviderRateLimitState]:
    state = ProviderRateLimitState(clock=clock.monotonic, sleeper=clock.sleep)
    gate = ProviderRateLimitGate(
        ClientRateLimitConfig(
            requests_per_second=requests_per_second,
            burst=burst,
            max_concurrency=max_concurrency,
            max_wait_seconds=max_wait_seconds,
            cooldown_floor_seconds=cooldown_floor_seconds,
        ),
        state=state,
    )
    return gate, state


# --- the limiter itself ------------------------------------------------------


def test_the_burst_allowance_lets_the_configured_number_of_calls_through() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, requests_per_second=2.0, burst=3)

    for _ in range(3):
        lease = gate.reserve("provider:stub")
        assert lease.waited_seconds == 0.0
        lease.release()

    assert clock.sleeps == []


def test_a_call_over_the_rate_limit_waits_locally_and_says_so() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, requests_per_second=2.0, burst=1)

    gate.reserve("provider:stub").release()
    lease = gate.reserve("provider:stub")

    # One token per 0.5 s at 2 rps, and the wait is reported rather than hidden.
    assert lease.waited_seconds == pytest.approx(0.5)
    assert lease.reason == "rate_limit"
    assert clock.sleeps == [pytest.approx(0.5)]
    lease.release()


def test_the_rate_limit_refills_over_time() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, requests_per_second=2.0, burst=1)

    gate.reserve("provider:stub").release()
    clock.now += 1.0
    clock.sleeps.clear()

    lease = gate.reserve("provider:stub")

    assert lease.waited_seconds == 0.0
    assert clock.sleeps == []
    lease.release()


def test_a_wait_longer_than_the_bound_is_refused_instead_of_stalling() -> None:
    clock = _FakeClock()
    gate, _state = _gate(
        clock, requests_per_second=0.1, burst=1, max_wait_seconds=2.0
    )

    gate.reserve("provider:stub").release()

    with pytest.raises(LocalRateLimitRejection) as rejected:
        gate.reserve("provider:stub")

    assert rejected.value.reason == "rate_limit"
    assert rejected.value.required_wait_seconds == pytest.approx(10.0)
    assert rejected.value.key == "provider:stub"
    assert clock.sleeps == [], "a refused call must not sleep first"


def test_zero_requests_per_second_disables_the_rate_limit() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, requests_per_second=0.0, burst=1)

    for _ in range(50):
        lease = gate.reserve("provider:stub")
        assert lease.waited_seconds == 0.0
        lease.release()

    assert clock.sleeps == []


def test_the_concurrency_bound_refuses_the_extra_caller_after_the_bound() -> None:
    # Real time: the bound is a semaphore, not a token bucket, so it is measured
    # against the wall clock rather than the injected one.
    state = ProviderRateLimitState()
    gate = ProviderRateLimitGate(
        ClientRateLimitConfig(
            requests_per_second=0.0,
            burst=1,
            max_concurrency=1,
            max_wait_seconds=0.2,
        ),
        state=state,
    )
    held = gate.reserve("provider:stub")

    started = time_module.monotonic()
    with pytest.raises(LocalRateLimitRejection) as rejected:
        gate.reserve("provider:stub")
    elapsed = time_module.monotonic() - started

    assert rejected.value.reason == "concurrency"
    assert elapsed >= 0.15, elapsed

    held.release()
    gate.reserve("provider:stub").release()


def test_releasing_a_lease_twice_is_harmless() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, max_concurrency=1)

    lease = gate.reserve("provider:stub")
    lease.release()
    lease.release()

    gate.reserve("provider:stub").release()


# --- the cross-call 429 cooldown --------------------------------------------


def test_a_cooldown_defers_other_calls_to_the_same_provider() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock)

    applied = gate.note_rate_limited("provider:stub", 3.0)

    assert applied == 3.0
    lease = gate.reserve("provider:stub")
    assert lease.reason == "cooldown"
    assert lease.waited_seconds == pytest.approx(3.0)
    assert clock.sleeps == [pytest.approx(3.0)]
    lease.release()


def test_a_cooldown_does_not_defer_a_different_provider() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock)

    gate.note_rate_limited("provider:a", 5.0)
    lease = gate.reserve("provider:b")

    assert lease.waited_seconds == 0.0
    assert clock.sleeps == []
    lease.release()


def test_a_cooldown_is_capped_by_the_configured_maximum(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS", "1.5")
    clock = _FakeClock()
    gate, _state = _gate(clock)

    applied = gate.note_rate_limited("provider:stub", 9_999.0)

    assert applied == 1.5
    lease = gate.reserve("provider:stub")
    assert lease.waited_seconds == pytest.approx(1.5)
    lease.release()


def test_a_cooldown_longer_than_the_bound_is_refused_instead_of_stalling(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS", "60")
    clock = _FakeClock()
    gate, _state = _gate(clock, max_wait_seconds=5.0)

    gate.note_rate_limited("provider:stub", 30.0)

    with pytest.raises(LocalRateLimitRejection) as rejected:
        gate.reserve("provider:stub")

    assert rejected.value.reason == "cooldown"
    assert rejected.value.required_wait_seconds >= 30.0


def test_the_cooldown_floor_applies_when_the_server_sends_no_instruction() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock, cooldown_floor_seconds=2.0)

    assert gate.note_rate_limited("provider:stub", None) == 2.0
    lease = gate.reserve("provider:stub")
    assert lease.waited_seconds == pytest.approx(2.0)
    lease.release()


def test_without_a_floor_and_without_a_header_no_cooldown_is_invented() -> None:
    clock = _FakeClock()
    gate, _state = _gate(clock)

    assert gate.note_rate_limited("provider:stub", None) == 0.0
    lease = gate.reserve("provider:stub")
    assert lease.waited_seconds == 0.0
    assert clock.sleeps == []
    lease.release()


# --- configuration ----------------------------------------------------------


def test_the_configuration_comes_from_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_RPS", "2.5")
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_BURST", "7")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_CONCURRENCY", "3")
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_MAX_WAIT_SECONDS", "4.5")
    monkeypatch.setenv("AGENT_OS_PROVIDER_429_COOLDOWN_SECONDS", "1.25")

    config = client_rate_limit_config_from_env()

    assert config.requests_per_second == 2.5
    assert config.burst == 7
    assert config.max_concurrency == 3
    assert config.max_wait_seconds == 4.5
    assert config.cooldown_floor_seconds == 1.25


def test_unusable_configuration_falls_back_to_the_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_RPS", "fast")
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_BURST", "-4")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_CONCURRENCY", "many")
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_MAX_WAIT_SECONDS", "soon")

    config = client_rate_limit_config_from_env()

    default = ClientRateLimitConfig()
    assert config == default
    # The defaults are a real ceiling, not "off": a runaway loop is paced.
    assert default.requests_per_second > 0
    assert default.burst >= 1
    assert default.max_concurrency >= 1


def test_a_negative_rate_disables_the_limit_but_not_the_cooldown() -> None:
    config = ClientRateLimitConfig(
        requests_per_second=-1.0, cooldown_floor_seconds=2.0
    )

    assert config.rate_limited is False
    assert config.cooldown_floor_seconds == 2.0


# --- the adapter -------------------------------------------------------------


def _credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential:rate-limit",
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="openai-compatible",
        resolver_key="CLIENT_RATE_LIMIT_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _request(request_id: str) -> ProviderRequest:
    return ProviderRequest(
        request_id=request_id,
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hi"),),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def _stub(
    plan: list[tuple[int, str | None]],
) -> tuple[str, list[float]]:
    """A scripted OpenAI-compatible endpoint; returns its base url and hit log."""

    hits: list[float] = []
    queue = list(plan)

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            hits.append(time_module.monotonic())
            status, retry_after = queue.pop(0) if queue else (200, None)
            if status == 200:
                body = json.dumps(
                    {
                        "id": "resp:stub",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 2,
                            "total_tokens": 3,
                        },
                    }
                ).encode()
            else:
                body = json.dumps({"error": {"message": "slow down"}}).encode()
            self.send_response(status)
            if retry_after is not None:
                self.send_header("Retry-After", retry_after)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", hits


def _provider(
    base_url: str,
    gate: ProviderRateLimitGate | None,
    *,
    max_retries: int = 0,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url=base_url,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_retries=max_retries,
        retry_base_seconds=0.0,
        rate_limit_gate=gate,
    )


def test_a_429_defers_the_next_call_to_the_same_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    gate, _state = _gate(clock)
    base_url, hits = _stub([(429, "2"), (200, None)])
    provider = _provider(base_url, gate)

    first = provider.complete(_request("req:1"))
    assert isinstance(first, ProviderFailure), first
    assert first.code is ProviderErrorCode.RATE_LIMITED
    assert clock.sleeps == [], "the first call has nothing to defer to"

    second = provider.complete(_request("req:2"))

    assert not isinstance(second, ProviderFailure), second
    assert clock.sleeps == [pytest.approx(2.0)], clock.sleeps
    assert len(hits) == 2


def test_the_429_cooldown_is_shared_across_provider_instances(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Two adapters over one provider identity (a reconfigure builds a new
    # instance): the deferral belongs to the provider, not to the object.
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    state = ProviderRateLimitState(clock=clock.monotonic, sleeper=clock.sleep)
    config = ClientRateLimitConfig(
        requests_per_second=1_000.0, burst=100, max_concurrency=0
    )
    base_url, _hits = _stub([(429, "1.5"), (200, None)])

    first_provider = _provider(base_url, ProviderRateLimitGate(config, state=state))
    second_clock_provider = _provider(
        base_url, ProviderRateLimitGate(config, state=state)
    )

    assert isinstance(first_provider.complete(_request("req:1")), ProviderFailure)
    second = second_clock_provider.complete(_request("req:2"))

    assert not isinstance(second, ProviderFailure), second
    assert clock.sleeps == [pytest.approx(1.5)], clock.sleeps


def test_a_429_without_a_header_does_not_invent_a_cooldown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Preserves the existing Retry-After semantics: garbage or absent means the
    # adapter falls back to its own backoff and holds nothing else back.
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    gate, _state = _gate(clock)
    base_url, _hits = _stub([(429, None), (200, None)])
    provider = _provider(base_url, gate)

    assert isinstance(provider.complete(_request("req:1")), ProviderFailure)
    assert not isinstance(provider.complete(_request("req:2")), ProviderFailure)

    assert clock.sleeps == [], clock.sleeps


def test_a_non_retryable_failure_sets_no_cooldown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    gate, _state = _gate(clock)
    base_url, _hits = _stub([(401, "5"), (200, None)])
    provider = _provider(base_url, gate)

    failure = provider.complete(_request("req:1"))
    assert isinstance(failure, ProviderFailure)
    assert failure.code is ProviderErrorCode.AUTHENTICATION_FAILED
    assert not isinstance(provider.complete(_request("req:2")), ProviderFailure)
    assert clock.sleeps == [], clock.sleeps


def test_a_deferred_attempt_reports_the_wait_beside_the_request_latency(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    # The operator's latency distribution must be the provider's latency: a
    # local wait reported inside latency_ms would make a cooldown look like a
    # slow provider, so the two are separate fields on the same record.
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    log = tmp_path / "provider.jsonl"
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))
    clock = _FakeClock()
    gate, _state = _gate(clock)
    base_url, _hits = _stub([(429, "4"), (200, None)])
    provider = _provider(base_url, gate)

    assert isinstance(provider.complete(_request("req:1")), ProviderFailure)
    assert not isinstance(provider.complete(_request("req:2")), ProviderFailure)

    records = [json.loads(line) for line in log.read_text().splitlines() if line]
    deferred = records[-1]
    assert deferred["local_rate_limit_wait_ms"] == pytest.approx(4_000.0)
    assert deferred["local_rate_limit_reason"] == "cooldown"
    assert deferred["latency_ms"] < 1_000, deferred["latency_ms"]


def test_a_locally_refused_call_never_reaches_the_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    gate, _state = _gate(
        clock, requests_per_second=0.1, burst=1, max_wait_seconds=1.0
    )
    base_url, hits = _stub([(200, None)])
    provider = _provider(base_url, gate, max_retries=3)

    assert not isinstance(provider.complete(_request("req:1")), ProviderFailure)
    refused = provider.complete(_request("req:2"))

    assert isinstance(refused, ProviderFailure), refused
    assert refused.code is ProviderErrorCode.LOCAL_RATE_LIMITED
    assert refused.retryable is False, "a local refusal must not spin on retries"
    assert "local" in refused.safe_message
    assert len(hits) == 1, "the refused call must not have been sent"
    assert clock.sleeps == []


def test_the_adapter_uses_the_shared_registry_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Without an injected gate, two adapters for the same provider identity share
    # the process-wide deferral registry.
    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    monkeypatch.setenv("AGENT_OS_PROVIDER_RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS", "0.05")
    base_url, _hits = _stub([(429, "0.05"), (200, None)])

    from agent_os_core.client_rate_limit import reset_shared_rate_limit_state

    reset_shared_rate_limit_state()
    try:
        key = f"openai-compatible|{base_url}"
        first = _provider(base_url, None)  # type: ignore[arg-type]
        second = _provider(base_url, None)  # type: ignore[arg-type]
        assert isinstance(first.complete(_request("req:1")), ProviderFailure)

        started = time_module.monotonic()
        assert not isinstance(second.complete(_request("req:2")), ProviderFailure)
        elapsed = time_module.monotonic() - started

        assert elapsed >= 0.04, (elapsed, key)
    finally:
        reset_shared_rate_limit_state()
