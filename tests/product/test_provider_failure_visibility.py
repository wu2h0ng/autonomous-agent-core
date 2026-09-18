"""What the operator reads when the provider fails.

The failure message becomes the turn's final text, i.e. the only thing a user
sees, so it has to name the cause and the next step - and it is durable, so it
must never contain the credential. These cases pin the HTTP status -> error code
classification, the message text, retryability, and the absence of the key, plus
the refusal shape of each of the three adapters (OpenAI-compatible, Anthropic
Messages, Gemini generateContent), which otherwise arrive as an empty answer,
plus what a refusal is allowed to carry: the detail is provider-supplied text
that reaches both a terminal and the durable record.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
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
        if status == 200:
            # A scripted success, so the same stub can drive the happy path
            # (the operator-log records need one).
            self.wfile.write(
                json.dumps(
                    {
                        "id": "resp:stub",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "stub reply",
                                },
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
            )
            return
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


def test_anthropic_end_turn_with_stop_details_is_not_a_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # stop_details can ride along with a normal end_turn. Treating every payload
    # that carries one as a refusal would turn ordinary answers into failures, so
    # the stop_reason is what decides - pin it, because nothing else does.
    _json_reply(
        {
            "id": "msg:ok",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "here is the answer"}],
            "stop_reason": "end_turn",
            "stop_details": {
                "type": "refusal",
                "category": "general_harms",
                "explanation": "This request violates our usage policy.",
            },
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }
    )
    result = _scripted_provider(monkeypatch, AnthropicMessagesProvider).complete(
        _request()
    )
    assert not isinstance(result, ProviderFailure), result
    assert result.text == "here is the answer"
    assert result.finish_reason == "end_turn"


def test_anthropic_streaming_end_turn_with_stop_details_is_not_a_refusal(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
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
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": "end_turn",
                        "stop_details": {
                            "type": "refusal",
                            "category": "bio",
                            "explanation": "This request violates our usage policy.",
                        },
                    },
                    "usage": {"output_tokens": 2},
                },
            ),
        ]
    )
    deltas: list[str] = []
    result = _scripted_provider(
        monkeypatch, AnthropicMessagesProvider
    ).complete_streaming(_request(), on_text_delta=deltas.append)
    assert not isinstance(result, ProviderFailure), result
    assert result.text == "answer"
    assert deltas == ["answer"]


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


def test_gemini_image_block_finish_reasons_are_refusals(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Image generation reports its own blocks, separate from the text ones, and a
    # blocked image leaves the candidate without text: no candidate content at
    # all, or a content list holding only the blocked image. Without these values
    # in the block set the first shape failed parts validation and the second one
    # reached ProviderResponse with an empty text, so the operator read
    # "provider response malformed: ValueError/ValidationError" where the
    # provider had actually refused.
    for reason in ("IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION"):
        for candidate in (
            {"finishReason": reason},
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": "aW1hZ2U=",
                            }
                        }
                    ],
                },
                "finishReason": reason,
            },
        ):
            _json_reply(
                {
                    "responseId": "resp:image-block",
                    "candidates": [candidate],
                    "usageMetadata": {"promptTokenCount": 7},
                }
            )
            result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
                _request()
            )
            assert isinstance(result, ProviderFailure), result
            assert result.code is ProviderErrorCode.REFUSED, result
            assert result.retryable is False
            assert reason in result.safe_message, result.safe_message


def test_gemini_non_blocking_finish_reasons_stay_responses(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Guard the other direction: the block set must not swallow ordinary
    # completions such as a length-truncated answer.
    for reason in ("MAX_TOKENS", "LANGUAGE", "OTHER"):
        _json_reply(
            {
                "responseId": "resp:ok",
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "partial"}]},
                        "finishReason": reason,
                    }
                ],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
            }
        )
        result = _scripted_provider(monkeypatch, GeminiGenerativeProvider).complete(
            _request()
        )
        assert not isinstance(result, ProviderFailure), result
        assert result.text == "partial"
        assert result.finish_reason == reason.lower()


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


_REFUSAL_SECRET = "sk-live-REFUSALDEADBEEFDEADBEEF"


def test_a_refusal_with_a_lone_surrogate_is_refused_not_malformed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Half of a surrogate pair can arrive as a JSON ``\udXXX`` escape, which
    # json.loads turns into a Python string that cannot be encoded as UTF-8. That
    # string became ProviderFailure.safe_message, whose own string_unicode
    # validation raised, so a refusal reached the operator as "provider response
    # malformed: ValidationError" - an internal error where the provider had
    # refused.
    _json_reply(
        {
            "id": "resp:refusal",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": "blocked \ud800 request",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    result = _scripted_provider(monkeypatch, OpenAICompatibleProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED, result
    assert "ValidationError" not in result.safe_message
    assert "blocked" in result.safe_message
    assert "request" in result.safe_message
    # The durable record has to be encodable; a lone surrogate raises here.
    result.safe_message.encode("utf-8")


def test_refusal_text_cannot_inject_a_host_path_a_key_ansi_or_a_newline(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    # The refusal detail is provider-supplied text that becomes the turn's
    # durable final text, so it reaches two boundaries at once: the operator's
    # terminal (ANSI repaints the line it is on, a newline forges another one)
    # and the failure record (an absolute path names the host, a key echoed back
    # is stored as a credential).
    _json_reply(
        {
            "id": "resp:refusal",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": (
                            "\x1b[31mBlocked\x1b[0m by policy\n"
                            f"key {_REFUSAL_SECRET}\n"
                            "at /Users/somebody/private-project/secret.py\ttail\x07"
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    result = _scripted_provider(monkeypatch, OpenAICompatibleProvider).complete(
        _request()
    )
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED
    message = result.safe_message
    # The refusal itself survives.
    assert "Blocked by policy" in message
    # The path keeps its name but loses the host's layout.
    assert "[host-path]/secret.py" in message
    assert "/Users/somebody" not in message
    # The key is gone, and so is the credential the adapter was given.
    assert _REFUSAL_SECRET not in message
    assert "[redacted-credential]" in message
    assert _SECRET not in message
    # One line, no control characters, no half-stripped escape sequence.
    for forbidden in ("\x1b", "[31m", "[0m", "\n", "\r", "\t", "\x07"):
        assert forbidden not in message, repr(message)
    assert len(message) <= len("provider refused: ") + 300


class _NativeProbeProvider(OpenAICompatibleProvider):
    """A new native protocol that overrides only the refusal hook."""

    def _refusal_text(self, payload: dict[str, object]) -> str | None:
        return "native protocol refusal"


def test_the_base_adapter_runs_the_refusal_hook_before_the_completion_mapper(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    # The payload is a native refusal shape the base class knows nothing about:
    # it carries no `choices` at all, so if `_invoke` stopped calling
    # `_refusal_text` the KeyError would surface as MALFORMED and the operator
    # would read an internal error where the provider had refused.
    _json_reply({"native": {"status": "refused"}})
    result = _scripted_provider(monkeypatch, _NativeProbeProvider).complete(_request())
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.REFUSED, result
    assert "native protocol refusal" in result.safe_message


def test_every_native_adapter_overrides_the_refusal_hook() -> None:
    # The base class carries a working OpenAI-compatible implementation, so a new
    # native protocol that forgets `_refusal_text` inherits it silently and its
    # refusals arrive as MALFORMED. The hook contract is written down in
    # OpenAICompatibleProvider and enforced here for every subclass, which is the
    # nearest thing to an abstract method the shared base can have.
    contract = OpenAICompatibleProvider.__doc__ or ""
    assert "_refusal_text" in contract
    subclasses = OpenAICompatibleProvider.__subclasses__()
    assert len(subclasses) >= 3, subclasses
    for subclass in subclasses:
        assert "_refusal_text" in vars(subclass), (
            f"{subclass.__name__} inherits the OpenAI-compatible refusal shape: "
            "override _refusal_text, or a native refusal is reported as MALFORMED"
        )


# --- Retry-After -------------------------------------------------------------

_RETRY_AFTER: list[str] = []


class _RetryAfterHandler(BaseHTTPRequestHandler):
    """429 with a Retry-After header, then a successful response."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if _RETRY_AFTER:
            body = json.dumps({"error": {"message": "slow down"}}).encode()
            self.send_response(429)
            self.send_header("Retry-After", _RETRY_AFTER.pop(0))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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


def _retry_run(
    monkeypatch, retry_after: list[str], *, cap: float | None = None
) -> tuple[object, list[float]]:  # type: ignore[no-untyped-def]
    """One 429 (with Retry-After), then a success; returns the sleeps asked for."""
    import agent_os_core.provider as provider_module
    from agent_os_core.provider import OpenAICompatibleProvider

    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    if cap is None:
        monkeypatch.delenv("AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS", raising=False)
    else:
        monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRY_AFTER_SECONDS", str(cap))
    _RETRY_AFTER.clear()
    _RETRY_AFTER.extend(retry_after)
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RetryAfterHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    provider = OpenAICompatibleProvider(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_request())
    return result, sleeps


def test_retry_after_delta_seconds_is_honoured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The provider asked for 2 seconds; our own backoff is 0, so the sleep is
    # entirely the server's instruction.
    result, sleeps = _retry_run(monkeypatch, ["2"])
    assert not isinstance(result, ProviderFailure), result
    assert sleeps == [2.0], sleeps


def test_retry_after_http_date_is_honoured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    when = datetime.now(timezone.utc) + timedelta(seconds=5)
    stamp = format_datetime(when, usegmt=True)
    result, sleeps = _retry_run(monkeypatch, [stamp])
    assert not isinstance(result, ProviderFailure), result
    assert len(sleeps) == 1
    assert 3.0 <= sleeps[0] <= 6.0, sleeps


def test_retry_after_is_capped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A hostile or mistaken header must not stall the turn.
    result, sleeps = _retry_run(monkeypatch, ["9999"], cap=1.5)
    assert not isinstance(result, ProviderFailure), result
    assert sleeps == [1.5], sleeps


def test_unparseable_retry_after_falls_back_to_backoff(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result, sleeps = _retry_run(monkeypatch, ["soon-ish"])
    assert not isinstance(result, ProviderFailure), result
    # Garbage is ignored rather than handed to sleep(), and with our own backoff
    # set to zero the retry does not sleep at all - so the observable proof is
    # that no sleep call happened (a parsed instruction would have produced one).
    assert sleeps == [], sleeps


def test_a_non_retryable_failure_does_not_honour_retry_after(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # 401 is not retryable: no retry, so no sleep and no hint left behind.
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    import agent_os_core.provider as provider_module
    from agent_os_core.provider import OpenAICompatibleProvider

    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    provider = OpenAICompatibleProvider(
        base_url=_stub([401]),
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_request())
    assert isinstance(result, ProviderFailure), result
    assert result.code is ProviderErrorCode.AUTHENTICATION_FAILED
    assert sleeps == [], sleeps
    assert provider._retry_after_hint is None  # type: ignore[attr-defined]


# --- operator log ------------------------------------------------------------


def _logged_request(text: str = "SECRET-PROMPT-TEXT"):
    from agent_os_contracts import ProviderMessage, ProviderMessageRole, ProviderRequest

    return ProviderRequest(
        request_id="req:log",
        task_id="task:1",
        run_id="run:1",
        provider_profile_id="provider-profile:default",
        messages=(ProviderMessage(role=ProviderMessageRole.USER, content=text),),
        timeout_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def _read_log(path) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_no_operator_log_without_the_env_variable(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AGENT_OS_PROVIDER_LOG", raising=False)
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    provider = OpenAICompatibleProvider(
        base_url=_stub([200]),
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    assert not isinstance(provider.complete(_request()), ProviderFailure)
    assert list(tmp_path.iterdir()) == []


def test_successful_call_writes_one_content_free_record(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    log = tmp_path / "nested" / "provider.jsonl"
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    provider = OpenAICompatibleProvider(
        base_url=_stub([200]),
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_logged_request())
    assert not isinstance(result, ProviderFailure), result

    records = _read_log(log)
    assert len(records) == 1, records
    record = records[0]
    assert record["event"] == "provider_attempt"
    assert record["outcome"] == "response"
    assert record["attempt"] == 0
    assert record["provider_id"] == "openai-compatible"
    assert record["model_id"] == "stub-model"
    assert record["latency_ms"] >= 0
    assert record["total_tokens"] == 3
    assert "finish_reason" in record
    # The log answers "how long / how many tokens / which failure" and nothing
    # else: no prompt text, no completion text, no credential.
    raw = log.read_text()
    assert "SECRET-PROMPT-TEXT" not in raw
    assert _SECRET not in raw
    assert (log.stat().st_mode & 0o777) == 0o600


def test_a_rate_limited_attempt_is_logged_with_its_retry_after(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Two records: the 429 (with the server's instruction) and the success after
    # the retry.
    import agent_os_core.provider as provider_module

    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    log = (
        __import__("pathlib").Path(
            __import__("tempfile").mkdtemp(prefix="provider-log-")
        )
        / "provider.jsonl"
    )
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(log))
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    _RETRY_AFTER.clear()
    _RETRY_AFTER.append("3")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RetryAfterHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    provider = OpenAICompatibleProvider(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    assert not isinstance(provider.complete(_request()), ProviderFailure)
    assert sleeps == [3.0], sleeps

    records = _read_log(log)
    assert [record["outcome"] for record in records] == ["failure", "response"]
    assert records[0]["code"] == "RATE_LIMITED"
    assert records[0]["retryable"] is True
    assert records[0]["retry_after_seconds"] == 3.0
    assert records[0]["attempt"] == 0
    assert records[1]["attempt"] == 1


def test_an_unwritable_operator_log_does_not_break_the_call(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("AGENT_OS_PROVIDER_LOG", str(blocker / "nested" / "log.jsonl"))
    monkeypatch.setenv("FAILURE_VISIBILITY_KEY", _SECRET)
    provider = OpenAICompatibleProvider(
        base_url=_stub([200]),
        model="stub-model",
        credential=_credential(),
        credentials=EnvCredentialBroker(),
        retry_base_seconds=0.0,
    )
    result = provider.complete(_request())
    assert not isinstance(result, ProviderFailure), result
    assert not (blocker / "nested").exists()
