"""What the operator reads when the provider fails.

The failure message becomes the turn's final text, i.e. the only thing a user
sees, so it has to name the cause and the next step - and it is durable, so it
must never contain the credential. These cases pin the HTTP status -> error code
classification, the message text, retryability, and the absence of the key, plus
the refusal shape of each of the three adapters (OpenAI-compatible, Anthropic
Messages, Gemini generateContent), which otherwise arrive as an empty answer.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
)
from agent_os_core.provider import (
    AnthropicMessagesProvider,
    EnvCredentialBroker,
    GeminiGenerativeProvider,
    OpenAICompatibleProvider,
)

_SECRET = "sk-failure-visibility-DEADBEEF"
_STATUSES: list[int] = []


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        status = _STATUSES.pop(0) if _STATUSES else 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": {"message": "stub"}}).encode())

    def log_message(self, *_args: object) -> None:  # keep pytest output clean
        return


def _stub(statuses: list[int]) -> str:
    _STATUSES.clear()
    _STATUSES.extend(statuses)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def _credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credential:test",
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="openai-compatible",
        resolver_key="FAILURE_VISIBILITY_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        request_id="req:1",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content="hi"),),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def _failure_for(monkeypatch, status: int, repeats: int = 1) -> ProviderFailure:
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    provider = OpenAICompatibleProvider(
        base_url=_stub([status] * repeats),
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_request())
    assert isinstance(result, ProviderFailure), result
    return result


def test_rejected_credential_names_the_cause_and_the_next_step(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for status in (401, 403):
        failure = _failure_for(monkeypatch, status)
        assert failure.code is ProviderErrorCode.AUTHENTICATION_FAILED
        assert failure.retryable is False
        assert "rejected the credential" in failure.safe_message
        assert "check the configured provider key" in failure.safe_message


def test_rate_limit_and_unavailable_are_marked_retryable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    limited = _failure_for(monkeypatch, 429, repeats=4)
    assert limited.code is ProviderErrorCode.RATE_LIMITED
    assert limited.retryable is True
    assert "rate limited" in limited.safe_message

    unavailable = _failure_for(monkeypatch, 503, repeats=4)
    assert unavailable.code is ProviderErrorCode.UNAVAILABLE
    assert unavailable.retryable is True
    assert "unavailable" in unavailable.safe_message


def test_other_client_errors_are_not_retried(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    failure = _failure_for(monkeypatch, 400)
    assert failure.code is ProviderErrorCode.MALFORMED
    assert failure.retryable is False
    assert "rejected the request" in failure.safe_message


def test_failure_messages_never_carry_the_credential(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # safe_message is durable and rendered to the operator, so a key in it would
    # be a leak. Assert the raw secret and its payload part are absent from every
    # classification we can produce.
    for status, repeats in ((401, 1), (429, 4), (400, 1), (503, 4)):
        failure = _failure_for(monkeypatch, status, repeats=repeats)
        rendered = json.dumps(failure.model_dump(mode="json"))
        assert _SECRET not in rendered, rendered
        assert _SECRET.removeprefix("sk-") not in rendered, rendered


def test_success_still_returns_a_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Guard against turning ordinary traffic into failures while adding the
    # classification above.
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    provider = OpenAICompatibleProvider(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_request())
    assert not isinstance(result, ProviderFailure), result
    assert result.text == "ok"


class _OkHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {
                "id": "resp:1",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


class _RefusalHandler(BaseHTTPRequestHandler):
    """A refusal in the OpenAI-compatible non-streaming shape."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {
                "id": "resp:refusal",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "refusal": "I cannot help with that request.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


class _FilterHandler(BaseHTTPRequestHandler):
    """Moderation block: the content filter shows up as the finish reason."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {
                "id": "resp:filter",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "content_filter",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 0,
                    "total_tokens": 1,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


_FRAMES: list[dict[str, object]] = []


class _StreamRefusalHandler(BaseHTTPRequestHandler):
    """SSE stub that streams a refusal delta and then ends."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for frame in _FRAMES:
            self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *_args: object) -> None:
        return


def _provider_for(
    monkeypatch, handler: type[BaseHTTPRequestHandler]
) -> OpenAICompatibleProvider:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return OpenAICompatibleProvider(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )


def test_non_streaming_refusal_is_a_refusal_not_an_empty_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # content is null and the text lives in `refusal`; reading only content made
    # this an empty assistant turn with no explanation.
    result = _provider_for(monkeypatch, _RefusalHandler).complete(_request())
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert result.retryable is False
    assert "I cannot help with that request." in result.safe_message


def test_content_filter_is_reported_as_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result = _provider_for(monkeypatch, _FilterHandler).complete(_request())
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "content filter" in result.safe_message


def test_streaming_refusal_is_a_refusal_not_an_empty_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The TUI reads the streaming path, so a refusal must be recognised here too.
    global _FRAMES
    _FRAMES = [
        {
            "id": "resp:stream",
            "choices": [
                {
                    "delta": {"refusal": "I cannot help with that request."},
                    "finish_reason": "stop",
                }
            ],
        }
    ]
    deltas: list[str] = []
    result = _provider_for(monkeypatch, _StreamRefusalHandler).complete_streaming(
        _request(), on_text_delta=deltas.append
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "I cannot help with that request." in result.safe_message
    assert deltas == [], "a refusal must not be streamed as assistant text"


def test_a_refusal_is_bounded_and_secret_free(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    global _FRAMES
    long_refusal = "no " * 400
    _FRAMES = [
        {
            "id": "resp:stream",
            "choices": [{"delta": {"refusal": long_refusal}, "finish_reason": "stop"}],
        }
    ]
    result = _provider_for(monkeypatch, _StreamRefusalHandler).complete_streaming(
        _request(), on_text_delta=lambda _s: None
    )
    assert isinstance(result, ProviderFailure), result
    assert len(result.safe_message) < 400, result.safe_message
    assert _SECRET not in json.dumps(result.model_dump(mode="json"))


# The native adapters each have their own refusal shape. One handler serves one
# configured reply, so a case can pin a whole wire shape (body or SSE frames).
_REPLY_BODY: bytes = b""
_REPLY_CONTENT_TYPE = "application/json"


class _ScriptedHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", _REPLY_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(_REPLY_BODY)))
        self.end_headers()
        self.wfile.write(_REPLY_BODY)

    def log_message(self, format: str, *args: object) -> None:  # noqa: ANN002
        return


def _reply(body: str, content_type: str = "application/json") -> None:
    global _REPLY_BODY, _REPLY_CONTENT_TYPE
    _REPLY_BODY = body.encode("utf-8")
    _REPLY_CONTENT_TYPE = content_type


def _json_reply(payload: dict[str, object]) -> None:
    _reply(json.dumps(payload))


def _gemini_sse_reply(chunks: list[dict[str, object]]) -> None:
    _reply(
        "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks),
        "text/event-stream",
    )


def _anthropic_sse_reply(events: list[tuple[str, dict[str, object]]]) -> None:
    _reply(
        "".join(
            f"event: {name}\ndata: {json.dumps(payload)}\n\n"
            for name, payload in events
        ),
        "text/event-stream",
    )


def _scripted_provider(
    monkeypatch,  # type: ignore[no-untyped-def]
    provider_cls: type[OpenAICompatibleProvider],
) -> OpenAICompatibleProvider:
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return provider_cls(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )


def test_anthropic_refusal_is_a_refusal_not_an_empty_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A policy refusal ends the message with stop_reason="refusal" and an empty
    # content list, so reading only the text made it an empty turn.
    _json_reply(
        {
            "id": "msg:refusal",
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {
                "type": "refusal",
                "category": "cyber",
                "explanation": "This request violates our usage policy.",
            },
            "usage": {"input_tokens": 3, "output_tokens": 0},
        }
    )
    result = _scripted_provider(monkeypatch, AnthropicMessagesProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert result.retryable is False
    assert "This request violates our usage policy." in result.safe_message
    assert _SECRET not in json.dumps(result.model_dump(mode="json"))


def test_anthropic_refusal_names_the_category_when_there_is_no_explanation(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    # stop_details.explanation is explicitly not guaranteed and is null when the
    # provider has none, so the category is the fallback - not a blank message.
    _json_reply(
        {
            "id": "msg:refusal",
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {
                "type": "refusal",
                "category": "general_harms",
                "explanation": None,
            },
            "usage": {"input_tokens": 3, "output_tokens": 0},
        }
    )
    result = _scripted_provider(monkeypatch, AnthropicMessagesProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "general_harms" in result.safe_message


def test_anthropic_streaming_refusal_is_a_refusal_not_an_empty_answer(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    # The TUI reads the streaming path: message_delta carries the stop_reason.
    _anthropic_sse_reply(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {"id": "msg:stream", "usage": {"input_tokens": 4}},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": "refusal",
                        "stop_details": {
                            "type": "refusal",
                            "category": "bio",
                            "explanation": "I cannot help with that request.",
                        },
                    },
                    "usage": {"output_tokens": 1},
                },
            ),
        ]
    )
    deltas: list[str] = []
    result = _scripted_provider(
        monkeypatch, AnthropicMessagesProvider
    ).complete_streaming(_request(), on_text_delta=deltas.append)
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "I cannot help with that request." in result.safe_message
    assert deltas == [], "a refusal must not be streamed as assistant text"


def test_gemini_safety_finish_reason_is_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A blocked candidate has no text at all, so it used to read as an empty
    # answer instead of a refusal.
    _json_reply(
        {
            "responseId": "resp:safety",
            "candidates": [
                {"content": {"role": "model", "parts": []}, "finishReason": "SAFETY"}
            ],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 0},
        }
    )
    result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert result.retryable is False
    assert "SAFETY" in result.safe_message
    assert _SECRET not in json.dumps(result.model_dump(mode="json"))


def test_gemini_blocked_prompt_is_a_refusal_not_a_malformed_response(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    # A blocked prompt comes back with promptFeedback and no candidates at all,
    # which the mapper rejected as malformed; the block is the real cause.
    _json_reply(
        {
            "promptFeedback": {
                "blockReason": "PROHIBITED_CONTENT",
                "blockReasonMessage": "The prompt was blocked for prohibited content.",
            }
        }
    )
    result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "prohibited content" in result.safe_message


def test_gemini_prompt_block_without_a_message_names_the_reason(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    _json_reply({"promptFeedback": {"blockReason": "BLOCKLIST"}})
    result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "BLOCKLIST" in result.safe_message


def test_gemini_streaming_blocked_prompt_is_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The TUI reads the streaming path, where the block arrives in the first
    # chunk as promptFeedback with no candidates.
    _gemini_sse_reply(
        [
            {
                "responseId": "resp:stream",
                "promptFeedback": {
                    "blockReason": "SAFETY",
                    "blockReasonMessage": "The prompt was blocked for safety.",
                },
                "usageMetadata": {"promptTokenCount": 6},
            }
        ]
    )
    deltas: list[str] = []
    result = _scripted_provider(
        monkeypatch, GeminiGenerativeProvider
    ).complete_streaming(_request(), on_text_delta=deltas.append)
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "blocked for safety" in result.safe_message
    assert deltas == [], "a refusal must not be streamed as assistant text"


def test_gemini_streaming_safety_finish_reason_is_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _gemini_sse_reply(
        [
            {
                "responseId": "resp:stream",
                "candidates": [
                    {
                        "content": {"role": "model", "parts": []},
                        "finishReason": "SAFETY",
                    }
                ],
            }
        ]
    )
    result = _scripted_provider(
        monkeypatch, GeminiGenerativeProvider
    ).complete_streaming(_request(), on_text_delta=lambda _s: None)
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    assert "SAFETY" in result.safe_message


def test_unset_gemini_block_reason_is_not_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Guard the other direction: an ordinary answer that carries a placeholder
    # block reason must still come back as a response.
    _json_reply(
        {
            "responseId": "resp:ok",
            "promptFeedback": {"blockReason": "BLOCKED_REASON_UNSPECIFIED"},
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "ok"}]},
                    "finishReason": "STOP",
                }
            ],
        }
    )
    result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
        _request()
    )
    assert not isinstance(result, ProviderFailure), result
    assert result.text == "ok"


def test_native_refusals_are_bounded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A runaway explanation must not bloat the durable failure record.
    _json_reply(
        {
            "id": "msg:refusal",
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "explanation": "no " * 400},
            "usage": {"input_tokens": 3, "output_tokens": 0},
        }
    )
    result = _scripted_provider(monkeypatch, AnthropicMessagesProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert len(result.safe_message) < 400, result.safe_message
