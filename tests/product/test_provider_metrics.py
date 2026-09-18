"""Aggregated provider metrics: counts, latency, tokens and failure categories.

Measured gap (2026-09-18): observability was the durable task-event audit,
`/cost`, `/task` and `/export`, plus an opt-in per-attempt provider log
(`AGENT_OS_PROVIDER_LOG`). Nothing aggregated that data, so an operator could
not answer "how many calls, how slow, how many retries, which failures" without
reading the JSONL by hand. This module surface is asserted here:

- the aggregation is exact (counts, nearest-rank percentiles, token totals,
  failure categories) and refuses to invent a latency when it has no samples;
- the process ledger and the opt-in log file are the *same* record stream, so
  aggregating either agrees - the log stays the operator's durable copy and the
  ledger is what a running process can serve;
- a snapshot never carries prompt text, completion text or a credential;
- the public read path is the authenticated route
  ``GET /v1/surface/observability/metrics`` with a typed body.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator

import pytest

from agent_os_contracts import (
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderMetricsSnapshot,
    ProviderRequest,
)
from agent_os_core.client_rate_limit import (
    ClientRateLimitConfig,
    ProviderRateLimitGate,
    ProviderRateLimitState,
)
from agent_os_core.provider import EnvCredentialBroker, OpenAICompatibleProvider
from agent_os_core.provider_metrics import (
    ProviderMetricsLedger,
    aggregate_provider_metrics,
    read_provider_log,
    reset_shared_provider_metrics_ledger,
    shared_provider_metrics_ledger,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

_SECRET = "sk-provider-metrics-DEADBEEF"
_PROMPT = "SECRET-PROMPT-TEXT"


@pytest.fixture(autouse=True)
def _clean_shared_ledger() -> Generator[None, None, None]:
    reset_shared_provider_metrics_ledger()
    yield
    reset_shared_provider_metrics_ledger()


def _record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "ts": "2026-09-18T10:00:00+00:00",
        "event": "provider_attempt",
        "request_id": "request:1",
        "provider_id": "openai-compatible",
        "model_id": "stub-model",
        "attempt": 0,
        "stream": False,
        "latency_ms": 10.0,
        "outcome": "response",
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
        "text_chars": 4,
        "tool_proposals": 0,
        "finish_reason": "stop",
    }
    record.update(updates)
    return record


def _failure_record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "ts": "2026-09-18T10:00:05+00:00",
        "event": "provider_attempt",
        "request_id": "request:9",
        "provider_id": "openai-compatible",
        "model_id": "stub-model",
        "attempt": 0,
        "stream": False,
        "latency_ms": 40.0,
        "outcome": "failure",
        "code": "RATE_LIMITED",
        "retryable": True,
        "retry_after_seconds": 2.0,
    }
    record.update(updates)
    return record


# --- aggregation -------------------------------------------------------------


def test_attempts_latency_tokens_and_failure_categories_are_aggregated() -> None:
    records = (
        _record(request_id="request:1", latency_ms=10.0),
        _record(request_id="request:1", attempt=1, latency_ms=20.0),
        _record(request_id="request:2", latency_ms=30.0),
        _failure_record(request_id="request:3", latency_ms=40.0),
    )

    snapshot = aggregate_provider_metrics(records)

    assert snapshot.attempts == 4
    assert snapshot.calls == 3, "three request ids, four attempts"
    assert snapshot.responses == 3
    assert snapshot.failures == 1
    assert snapshot.retries == 1, "one attempt with attempt > 0"
    assert snapshot.window_records == 4
    assert snapshot.latency.samples == 4
    assert snapshot.latency.mean_ms == pytest.approx(25.0)
    assert snapshot.latency.p50_ms == pytest.approx(20.0)
    assert snapshot.latency.p90_ms == pytest.approx(40.0)
    assert snapshot.latency.p95_ms == pytest.approx(40.0)
    assert snapshot.latency.max_ms == pytest.approx(40.0)
    assert snapshot.tokens.input_tokens == 3
    assert snapshot.tokens.output_tokens == 6
    assert snapshot.tokens.total_tokens == 9
    assert snapshot.tokens.usage_samples == 3
    assert [
        (category.code, category.count, category.retryable)
        for category in snapshot.failure_categories
    ] == [(ProviderErrorCode.RATE_LIMITED, 1, True)]
    assert snapshot.rate_limit.rate_limited_attempts == 1
    assert snapshot.rate_limit.retry_after_observed == 1
    assert snapshot.rate_limit.max_retry_after_seconds == pytest.approx(2.0)
    assert snapshot.source == "in_process"


def test_failure_categories_are_ordered_and_grouped() -> None:
    records = (
        _failure_record(code="MALFORMED", retryable=False),
        _failure_record(code="RATE_LIMITED", retryable=True),
        _failure_record(code="RATE_LIMITED", retryable=True),
        _failure_record(code="TIMEOUT", retryable=True),
    )

    snapshot = aggregate_provider_metrics(records)

    assert [
        (category.code.value, category.count) for category in snapshot.failure_categories
    ] == [("RATE_LIMITED", 2), ("MALFORMED", 1), ("TIMEOUT", 1)]


def test_an_empty_window_reports_no_latency_rather_than_zero() -> None:
    snapshot = aggregate_provider_metrics(())

    assert snapshot.attempts == 0
    assert snapshot.calls == 0
    assert snapshot.window_records == 0
    assert snapshot.window_started_at is None
    assert snapshot.window_ended_at is None
    assert snapshot.latency.samples == 0
    assert snapshot.latency.mean_ms is None
    assert snapshot.latency.p50_ms is None
    assert snapshot.latency.p90_ms is None
    assert snapshot.latency.p95_ms is None
    assert snapshot.latency.max_ms is None
    assert snapshot.tokens.total_tokens == 0
    assert snapshot.rate_limit.max_retry_after_seconds is None


def test_records_that_are_not_provider_attempts_are_ignored() -> None:
    records = (
        _record(),
        {"event": "something_else", "latency_ms": 9_000.0},
        {},
    )

    snapshot = aggregate_provider_metrics(records)

    assert snapshot.attempts == 1
    assert snapshot.latency.max_ms == pytest.approx(10.0)
    assert snapshot.ignored_lines == 2


def test_the_window_is_the_timestamp_range_of_the_records() -> None:
    snapshot = aggregate_provider_metrics(
        (
            _record(ts="2026-09-18T10:00:00+00:00"),
            _record(ts="2026-09-18T10:05:00+00:00"),
        )
    )

    assert snapshot.window_started_at == datetime(
        2026, 9, 18, 10, 0, tzinfo=timezone.utc
    )
    assert snapshot.window_ended_at == datetime(
        2026, 9, 18, 10, 5, tzinfo=timezone.utc
    )


# --- the ledger --------------------------------------------------------------


def test_the_ledger_keeps_a_bounded_window_and_says_when_it_dropped_records() -> None:
    ledger = ProviderMetricsLedger(limit=2)

    for index in range(5):
        ledger.record(_record(request_id=f"request:{index}"))

    snapshot = ledger.snapshot()

    assert snapshot.window_records == 2
    assert snapshot.window_truncated is True
    assert snapshot.attempts == 2


def test_the_ledger_serves_what_the_process_recorded() -> None:
    ledger = ProviderMetricsLedger()

    ledger.record(_record(request_id="request:1"))
    ledger.record(_failure_record(request_id="request:2"))

    snapshot = ledger.snapshot()

    assert snapshot.attempts == 2
    assert snapshot.responses == 1
    assert snapshot.failures == 1


def test_the_shared_ledger_is_the_process_wide_one() -> None:
    from agent_os_core.provider_metrics import shared_provider_metrics_ledger as again

    assert shared_provider_metrics_ledger() is again()


# --- the log file is the same record stream ----------------------------------


def _write_log(path: Path, records: list[dict[str, object]], trailer: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(record) + "\n" for record in records)
    path.write_text(body + trailer, encoding="utf-8")


def test_reading_the_log_reports_the_lines_it_could_not_use(tmp_path: Path) -> None:
    path = tmp_path / "provider.jsonl"
    _write_log(path, [_record(), _failure_record()], trailer="not json at all\n\n")

    loaded = read_provider_log(path)

    assert len(loaded.records) == 2
    assert loaded.ignored_lines == 2


def test_a_missing_log_reads_as_an_empty_window(tmp_path: Path) -> None:
    loaded = read_provider_log(tmp_path / "absent.jsonl")

    assert loaded.records == ()
    assert loaded.ignored_lines == 0


def test_the_ledger_and_the_log_file_agree_on_the_same_calls(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.product.test_client_rate_limit import _credential, _request, _stub

    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    log = tmp_path / "provider.jsonl"
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))
    base_url, _hits = _stub([(429, "1"), (200, None)])
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_retries=1,
        retry_base_seconds=0.0,
        rate_limit_gate=ProviderRateLimitGate(
            ClientRateLimitConfig(requests_per_second=0.0, max_concurrency=0)
        ),
    )

    provider.complete(_request("req:1"))
    provider.complete(_request("req:2"))

    from_ledger = shared_provider_metrics_ledger().snapshot()
    loaded = read_provider_log(log)
    from_log = aggregate_provider_metrics(
        loaded.records, source="log_file", ignored_lines=loaded.ignored_lines
    )

    assert from_ledger.source == "in_process"
    assert from_log.source == "log_file"
    for field in (
        "calls",
        "attempts",
        "responses",
        "failures",
        "retries",
        "window_records",
    ):
        assert getattr(from_ledger, field) == getattr(from_log, field), field
    assert from_ledger.latency.samples == from_log.latency.samples
    assert from_ledger.tokens.total_tokens == from_log.tokens.total_tokens
    assert from_ledger.rate_limit.rate_limited_attempts == 1
    assert from_log.rate_limit.rate_limited_attempts == 1
    assert from_log.rate_limit.max_retry_after_seconds == pytest.approx(1.0)


def test_local_throttling_shows_up_in_the_snapshot(monkeypatch) -> None:
    from tests.product.test_client_rate_limit import (
        _FakeClock,
        _credential,
        _request,
        _stub,
    )

    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    clock = _FakeClock()
    state = ProviderRateLimitState(clock=clock.monotonic, sleeper=clock.sleep)
    gate = ProviderRateLimitGate(
        ClientRateLimitConfig(
            requests_per_second=0.0, burst=1, max_concurrency=0
        ),
        state=state,
    )
    base_url, _hits = _stub([(200, None)])
    # The provider defers to a cooldown on its own key (its endpoint), so the
    # cooldown is recorded there rather than on an invented identity.
    gate.note_rate_limited(f"openai-compatible|{base_url}", 4.0)
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_retries=0,
        retry_base_seconds=0.0,
        rate_limit_gate=gate,
    )

    assert not isinstance(provider.complete(_request("req:1")), ProviderFailure)

    snapshot = shared_provider_metrics_ledger().snapshot()

    assert clock.sleeps == [pytest.approx(4.0)]
    assert snapshot.rate_limit.local_waits == 1
    assert snapshot.rate_limit.local_wait_ms_total == pytest.approx(4_000.0)
    assert snapshot.rate_limit.local_wait_ms_max == pytest.approx(4_000.0)


def test_a_locally_refused_call_is_counted_as_a_rejection(monkeypatch) -> None:
    from tests.product.test_client_rate_limit import _credential, _request, _stub

    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    gate = ProviderRateLimitGate(
        ClientRateLimitConfig(
            requests_per_second=0.05, burst=1, max_concurrency=0, max_wait_seconds=1.0
        )
    )
    base_url, _hits = _stub([(200, None)])
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_retries=0,
        retry_base_seconds=0.0,
        rate_limit_gate=gate,
    )

    assert not isinstance(provider.complete(_request("req:1")), ProviderFailure)
    refused = provider.complete(_request("req:2"))
    assert isinstance(refused, ProviderFailure)
    assert refused.code is ProviderErrorCode.LOCAL_RATE_LIMITED

    snapshot = shared_provider_metrics_ledger().snapshot()

    assert snapshot.rate_limit.local_rejections == 1
    assert snapshot.failures == 1
    assert [category.code for category in snapshot.failure_categories] == [
        ProviderErrorCode.LOCAL_RATE_LIMITED
    ]


def test_a_snapshot_never_carries_content_or_a_credential(monkeypatch, tmp_path: Path) -> None:
    from tests.product.test_client_rate_limit import _credential, _stub

    monkeypatch.setenv("CLIENT_RATE_LIMIT_KEY", _SECRET)
    log = tmp_path / "provider.jsonl"
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))
    base_url, _hits = _stub([(200, None)])
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        max_retries=0,
        retry_base_seconds=0.0,
        rate_limit_gate=ProviderRateLimitGate(
            ClientRateLimitConfig(requests_per_second=0.0, max_concurrency=0)
        ),
    )
    request = ProviderRequest(
        request_id="req:private",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content=_PROMPT),
        ),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )

    provider.complete(request)

    # A record stream that *did* carry content (a future/foreign log) must not be
    # able to push it into the snapshot either.
    hostile = shared_provider_metrics_ledger()
    hostile.record(
        {
            **_record(),
            "prompt": _PROMPT,
            "completion": "SECRET-COMPLETION-TEXT",
            "api_key": _SECRET,
        }
    )
    rendered = json.dumps(
        [
            shared_provider_metrics_ledger().snapshot().model_dump(mode="json"),
            aggregate_provider_metrics(read_provider_log(log).records).model_dump(
                mode="json"
            ),
        ]
    )

    for secret in (_PROMPT, "SECRET-COMPLETION-TEXT", _SECRET):
        assert secret not in rendered, secret


# --- the public read path ----------------------------------------------------


class _MetricsServer:
    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.token = token

    def get(self, path: str, *, authenticated: bool = True) -> tuple[int, Any]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.base + path,
            method="GET",
            headers={
                "Authorization": (
                    f"Bearer {self.token}" if authenticated else "Bearer wrong"
                )
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


@pytest.fixture
def metrics_server(tmp_path: Path) -> Generator[_MetricsServer, None, None]:
    app = AgentOSApplication(
        database=tmp_path / "metrics.sqlite3",
        workspace=tmp_path,
    )
    token = "test-local-token"
    handler = type(
        "TestMetricsHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _MetricsServer(f"http://127.0.0.1:{server.server_address[1]}", token)
    finally:
        server.shutdown()
        server.server_close()


def test_the_metrics_route_serves_the_typed_snapshot(
    metrics_server: _MetricsServer,
) -> None:
    shared_provider_metrics_ledger().record(_record(request_id="request:1"))
    shared_provider_metrics_ledger().record(_failure_record(request_id="request:2"))

    status, body = metrics_server.get("/v1/surface/observability/metrics")

    assert status == 200, body
    assert set(body) == {"metrics"}
    snapshot = ProviderMetricsSnapshot.model_validate(body["metrics"])
    assert snapshot.source == "in_process"
    assert snapshot.attempts == 2
    assert snapshot.responses == 1
    assert snapshot.failures == 1
    assert snapshot.latency.samples == 2


def test_the_metrics_route_reads_the_operator_log_when_asked(
    metrics_server: _MetricsServer, monkeypatch, tmp_path: Path
) -> None:
    log = tmp_path / "operator-provider.jsonl"
    _write_log(log, [_record(request_id="request:1"), _failure_record()])
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))

    status, body = metrics_server.get(
        "/v1/surface/observability/metrics?source=log"
    )

    assert status == 200, body
    snapshot = ProviderMetricsSnapshot.model_validate(body["metrics"])
    assert snapshot.source == "log_file"
    assert snapshot.attempts == 2


def test_the_log_source_says_so_when_no_log_is_configured(
    metrics_server: _MetricsServer, monkeypatch
) -> None:
    monkeypatch.delenv("AGENT_OS_PROVIDER_LOG", raising=False)

    status, body = metrics_server.get("/v1/surface/observability/metrics?source=log")

    assert status == 422, body
    assert "AGENT_OS_PROVIDER_LOG" in body["message"]


def test_an_unknown_metrics_source_is_rejected(metrics_server: _MetricsServer) -> None:
    status, body = metrics_server.get(
        "/v1/surface/observability/metrics?source=somewhere-else"
    )

    assert status == 422, body
    assert "source" in body["message"]


def test_the_metrics_route_requires_the_local_token(
    metrics_server: _MetricsServer,
) -> None:
    status, body = metrics_server.get(
        "/v1/surface/observability/metrics", authenticated=False
    )

    assert status == 401, body
