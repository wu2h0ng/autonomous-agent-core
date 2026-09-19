"""How a stream that already reached the operator, and a stream that was cut off, end.

Two defects measured against a local stub on the turn path that the terminal chat
actually takes (``AgentOSApplication`` -> real adapter -> ``AgentLoop.run_turn``):

1. The loop's own retry budget replayed output the adapter refuses to replay.
   ``provider.py`` states the rule for its own retry loop - "a stream that has
   already emitted a delta is never retried: replaying would duplicate output" -
   and enforces it with an ``emitted`` flag. ``AgentLoop._call_provider`` had a
   second retry loop that knew nothing about it, so a stream that dropped after
   its first delta was fetched again and the operator saw the same text three
   times (measured: 3 HTTP requests, 3 deliveries of one delta).

2. A stream that ended before the response was complete was recorded as a good
   turn. The transport cannot tell the difference (measured separately: for a
   short Content-Length body and for a truncated chunked body, ``readline``
   returns ``b""`` at EOF and raises nothing), so the only evidence is the
   dialect's own end-of-turn marker.

Both cases are asserted on what an operator can observe: the number of HTTP
requests the stub saw, how many times a delta reached the operator, what the turn
recorded as its stop reason, and which durable records the turn left behind.
"""

from __future__ import annotations

import contextlib
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from agent_os_contracts import ProviderErrorCode
from agent_os_core import AgentLoopConfig, AutoApproveGateway
from apps.api_server.app import AgentOSApplication

_OPENAI = "openai-compatible"
_ANTHROPIC = "anthropic-messages"
_GEMINI = "google-generative"

_KEY_ENV = {
    _OPENAI: "STREAM_INTEGRITY_KEY",
    _ANTHROPIC: "ANTHROPIC_API_KEY",
    _GEMINI: "GEMINI_API_KEY",
}

_PROMPT = "answer me"
_DELTA = "PARTIAL-ANSWER"

# Provider env vars that would otherwise leak in from the machine running the
# suite and change which endpoint the application resolves.
_PROVIDER_ENV = (
    "AGENT_OS_PROVIDER_PROFILE",
    "AGENT_OS_PROVIDER_BASE_URL",
    "AGENT_OS_PROVIDER_MODEL",
    "AGENT_OS_PROVIDER_API_KEY_ENV",
    "AGENT_OS_PROVIDER_ENDPOINT_CLASS",
    "AGENT_OS_PROVIDER_TEMPERATURE",
    "AGENT_OS_PROVIDER_MAX_RETRIES",
    "AGENT_OS_PROVIDER_RETRY_BASE_SECONDS",
    "AGENT_OS_PROVIDER_MAX_TOKENS",
    "OPENAI_API_URL",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_TEMPERATURE",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_API_KEY",
    "GEMINI_BASE_URL",
    "GEMINI_MODEL",
    "GEMINI_API_KEY",
)


def _openai_frames(*, end_marker: bool) -> str:
    """One content delta, optionally followed by the dialect's end-of-turn chunk."""
    frames = [
        {"id": "c1", "choices": [{"index": 0, "delta": {"content": _DELTA}}]},
    ]
    if end_marker:
        frames.append(
            {
                "id": "c1",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
    return "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)


def _anthropic_frames(*, end_marker: bool) -> str:
    frames: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {"id": "msg_1", "usage": {"input_tokens": 4}},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": _DELTA},
        },
    ]
    if end_marker:
        frames.append(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            }
        )
    return "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)


def _gemini_frames(*, end_marker: bool) -> str:
    candidate: dict[str, Any] = {
        "content": {"role": "model", "parts": [{"text": _DELTA}]}
    }
    if end_marker:
        candidate["finishReason"] = "STOP"
    return (
        "data: " + json.dumps({"responseId": "r1", "candidates": [candidate]}) + "\n\n"
    )


def _body_for(endpoint_class: str, mode: str) -> str:
    """The SSE body for one mode, per dialect.

    ``complete`` carries the end-of-turn marker its dialect defines (plus the
    dialect's sentinel where one exists); ``no_sentinel`` carries the marker but
    not the sentinel; ``truncated`` carries the same content and then simply
    stops, which is what a connection that died mid-response looks like to this
    client.
    """
    has_marker = mode in {"complete", "no_sentinel"}
    if endpoint_class == _ANTHROPIC:
        return _anthropic_frames(end_marker=has_marker)
    if endpoint_class == _GEMINI:
        return _gemini_frames(end_marker=has_marker)
    body = _openai_frames(end_marker=has_marker)
    if mode == "complete":
        body += "data: [DONE]\n\n"
    return body


class _StubHandler(BaseHTTPRequestHandler):
    """SSE stub bound to an ephemeral port; counts the requests it receives."""

    protocol_version = "HTTP/1.1"
    mode = "complete"
    endpoint_class = _OPENAI
    posts: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).posts.append(body)
        if type(self).mode == "http500":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if type(self).mode == "reset_after_delta":
            # The delta is delivered, then the connection dies: the one shape in
            # which the adapter itself reports a retryable failure *after* output
            # has already reached the operator.
            frame = f"data: {json.dumps({'id': 'c1', 'choices': [{'index': 0, 'delta': {'content': _DELTA}}]})}\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(frame) + 4096))
            self.end_headers()
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.35)
            self.connection.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
            self.connection.close()
            return
        if type(self).mode == "short_body":
            # The realistic connection death: the declared Content-Length is larger
            # than the bytes that arrive, so the body is cut off mid-response and
            # the socket closes. urllib hands this to the parser as an ordinary end
            # of stream, which is the whole reason the SSE-level marker decides.
            encoded = _body_for(type(self).endpoint_class, "truncated").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded) + 4096))
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
            self.close_connection = True
            return
        encoded = _body_for(type(self).endpoint_class, type(self).mode).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def _stub(*, endpoint_class: str, mode: str) -> Iterator[str]:
    _StubHandler.endpoint_class = endpoint_class
    _StubHandler.mode = mode
    _StubHandler.posts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _Turn:
    """Everything one turn lets an operator observe."""

    def __init__(self, app: AgentOSApplication, session: Any, result: Any) -> None:
        self.http_requests = len(_StubHandler.posts)
        self.request_bodies = list(_StubHandler.posts)
        self.stop_reason = result.stop_reason
        self.text = result.text
        self.events = list(app.tasks._event_store.read(session.task_id))

    def event_types(self) -> list[str]:
        return [
            str(getattr(event.event_type, "value", event.event_type))
            for event in self.events
        ]

    def count(self, name: str) -> int:
        return sum(1 for event_type in self.event_types() if event_type == name)

    def attempt_records(self) -> list[dict[str, Any]]:
        return [
            event.decoded_payload()["provider_attempt_failure"]
            for event in self.events
            if str(getattr(event.event_type, "value", "")) == "PROVIDER_ATTEMPT_FAILED"
        ]


def _run_turn(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    endpoint_class: str = _OPENAI,
    mode: str,
    inner_retries: str = "0",
    outer_retries: int = 2,
) -> tuple[_Turn, list[str]]:
    """Drive one real turn against the stub and report what reached the operator.

    The provider environment is set through ``monkeypatch`` so the stub endpoint
    cannot leak into the next test - the daemon-spawning cases in this suite
    inherit the process environment and would otherwise be pointed at a dead
    port with the wrong endpoint class.
    """

    key_env = _KEY_ENV[endpoint_class]
    with _stub(endpoint_class=endpoint_class, mode=mode) as url:
        for name in _PROVIDER_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", url)
        monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "stub-model")
        monkeypatch.setenv("AGENT_OS_PROVIDER_ENDPOINT_CLASS", endpoint_class)
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", key_env)
        monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRIES", inner_retries)
        monkeypatch.setenv("AGENT_OS_PROVIDER_RETRY_BASE_SECONDS", "0")
        monkeypatch.setenv(key_env, "stub-key")
        (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        assert app.provider_configured
        deltas: list[str] = []
        session, loop = app.open_chat_session(
            "stream-integrity",
            AutoApproveGateway(),
            loop_config=AgentLoopConfig(max_provider_retries=outer_retries),
        )
        loop._text_delta_sink = deltas.append
        result = loop.run_turn(session, _PROMPT)
        return _Turn(app, session, result), deltas


def test_a_delta_that_reached_the_operator_is_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Measured before the fix: 3 HTTP requests and 3 deliveries of one delta - the
    # adapter's own rule ("a stream that has already emitted a delta is never
    # retried") was enforced inside the adapter and ignored by the loop above it.
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="reset_after_delta")

    assert turn.http_requests == 1
    assert deltas == [_DELTA]
    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"


def test_both_retry_budgets_stop_together_after_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "The two layers agree" measured rather than asserted in prose: with the
    # adapter's internal retries enabled as well, the same stream is fetched once
    # and the delta delivered once. The adapter stops on its own ``emitted`` flag;
    # the loop above it now stops on the same fact, so neither can retry what the
    # other refuses to.
    turn, deltas = _run_turn(
        tmp_path, monkeypatch, mode="reset_after_delta", inner_retries="2"
    )

    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_failure_after_output_records_one_attempt_that_had_emitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same turn read off the durable log: one attempt, and it says the attempt
    # had already produced output. Before the fix three such records were written
    # for one honest failure.
    turn, _deltas = _run_turn(tmp_path, monkeypatch, mode="reset_after_delta")

    records = turn.attempt_records()
    assert len(records) == 1
    assert records[0]["emitted_output"] is True
    assert records[0]["attempts_planned"] == 3
    assert turn.count("PROVIDER_ATTEMPT_FAILED") == 1


def test_a_failure_without_output_still_uses_the_whole_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control for the test above: the fix must not disable the loop's retry, only
    # the replay. A retryable failure that produced nothing is still retried to
    # the configured budget (1 + max_provider_retries requests).
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="http500")

    assert turn.http_requests == 3
    assert deltas == []
    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"


def test_retry_budgets_still_compose_across_the_two_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Measured pin, not an endorsement: with the adapter's internal retries on, one
    # turn makes (1 + max_provider_retries) outer attempts, each of which is
    # (1 + adapter retries) HTTP requests, so a bare HTTP 500 costs 9 requests
    # while the loop above believes it made 3 attempts. That composition is
    # untouched here - it is a second, separate defect - and this case exists so
    # that changing it has to be deliberate.
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="http500", inner_retries="2")

    assert turn.http_requests == 9
    assert deltas == []


def test_a_truncated_stream_is_a_typed_failure_not_a_good_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Measured before the fix: the stream carried one content delta and then
    # stopped with no end-of-turn marker at all, and the turn was recorded as
    # PROVIDER_RESPONDED / stop_reason=completed, i.e. an answer cut in half was
    # presented as the answer.
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="truncated")

    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"
    assert turn.count("PROVIDER_RESPONDED") == 0
    assert turn.text != _DELTA
    # The delta had already reached the operator, so the failure is recorded and
    # the turn stops there rather than replaying it (the rule from defect 1).
    assert turn.http_requests == 1
    assert deltas == [_DELTA]
    records = turn.attempt_records()
    assert len(records) == 1
    assert records[0]["emitted_output"] is True


def test_a_body_cut_off_mid_response_is_the_same_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The realistic shape of the same defect: the response declares a Content-Length
    # larger than the bytes that arrive and the socket closes mid-body. (Measured
    # while writing this: the transport reports it as an ordinary end of stream -
    # ``readline`` returns b"" and raises nothing - which is why the dialect's own
    # end-of-turn marker, not EOF, is what decides.)
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="short_body")

    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"
    assert turn.count("PROVIDER_RESPONDED") == 0
    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_complete_stream_is_still_a_good_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other direction, and the reason the check is about the dialect's own
    # end-of-turn marker rather than about EOF: a stream that ends normally must
    # not become a failure.
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="complete")

    assert turn.stop_reason == "completed"
    assert turn.count("PROVIDER_RESPONDED") == 1
    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_stream_that_ends_on_its_end_of_turn_chunk_needs_no_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reference client treats a missing `[DONE]` as an ordinary end of
    # iteration, so `[DONE]` alone cannot be the test. A stream whose last chunk
    # carries the turn's finish reason has told us the model stopped, and stays a
    # good turn even with no sentinel.
    turn, deltas = _run_turn(tmp_path, monkeypatch, mode="no_sentinel")

    assert turn.stop_reason == "completed"
    assert turn.count("PROVIDER_RESPONDED") == 1
    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_truncated_anthropic_stream_is_a_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same rule in the Anthropic dialect, where the end of the turn is the
    # message_delta carrying stop_reason.
    turn, deltas = _run_turn(
        tmp_path, monkeypatch, endpoint_class=_ANTHROPIC, mode="truncated"
    )

    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"
    assert turn.count("PROVIDER_RESPONDED") == 0
    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_complete_anthropic_stream_is_still_a_good_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn, deltas = _run_turn(
        tmp_path, monkeypatch, endpoint_class=_ANTHROPIC, mode="complete"
    )

    assert turn.stop_reason == "completed"
    assert turn.count("PROVIDER_RESPONDED") == 1
    assert deltas == [_DELTA]


def test_a_truncated_gemini_stream_is_a_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gemini's end of turn is the candidate's finishReason.
    turn, deltas = _run_turn(
        tmp_path, monkeypatch, endpoint_class=_GEMINI, mode="truncated"
    )

    assert turn.stop_reason == f"provider_failure:{ProviderErrorCode.UNAVAILABLE.value}"
    assert turn.count("PROVIDER_RESPONDED") == 0
    assert turn.http_requests == 1
    assert deltas == [_DELTA]


def test_a_complete_gemini_stream_is_still_a_good_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn, deltas = _run_turn(
        tmp_path, monkeypatch, endpoint_class=_GEMINI, mode="complete"
    )

    assert turn.stop_reason == "completed"
    assert turn.count("PROVIDER_RESPONDED") == 1
    assert deltas == [_DELTA]
