"""S1 `/context`: the shared request-view rule + the read-only projection.

The rule the endpoint reports must be the rule the loop enforces. This file
locks `trimmed_history_view` against the messages the provider actually
received and against a frozen copy of the pre-refactor selection rule, and
asserts the endpoint is read-only and leaks nothing.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_os_contracts import (
    PrincipalIdentity,
    PrincipalRole,
    ProviderMessage,
    ProviderMessageRole,
)
from agent_os_core import (
    AutoApproveGateway,
    DeterministicProvider,
    SurfaceSessionNotFound,
)
from agent_os_core.agent_loop import AgentLoopConfig, trimmed_history_view

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

FORBIDDEN = (
    "statement",
    "envelope_id",
    "expected_outcome_id",
    "credential",
    "principal_id",
)


def _app(
    root: Path, principal: PrincipalIdentity | None = None
) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root, principal=principal
    )
    app.provider = DeterministicProvider(
        text=" ".join(["chunk"] * 120),  # ~840 chars per response
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _message(role: ProviderMessageRole, content: str) -> ProviderMessage:
    return ProviderMessage(role=role, content=content)


def test_trimmed_history_view_rule_is_exact() -> None:
    system = _message(ProviderMessageRole.SYSTEM, "s" * 10)
    user = _message(ProviderMessageRole.USER, "u" * 20)
    assistant = _message(ProviderMessageRole.ASSISTANT, "a" * 20)

    under = trimmed_history_view((system, user, assistant), 100)
    assert under.kept == (system, user, assistant)
    assert under.dropped_turns == 0
    assert under.used_chars == 50

    # over budget: drop the oldest whole turn block (system prompt is kept)
    over = trimmed_history_view((system, user, assistant, user, assistant), 60)
    assert over.kept == (system, user, assistant)
    assert over.dropped_turns == 1
    assert over.used_chars == 50

    # a stray non-USER block before the first turn is dropped with it and is
    # never counted as a turn
    odd = trimmed_history_view(
        (system, _message(ProviderMessageRole.ASSISTANT, "a" * 100), user), 50
    )
    assert odd.kept == (system,)
    assert odd.dropped_turns == 1
    assert odd.used_chars == 10

    empty = trimmed_history_view((), 10)
    assert empty.kept == ()
    assert empty.dropped_turns == 0
    assert empty.used_chars == 0


def test_context_status_matches_the_request_actually_sent(tmp_path: Path) -> None:
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=tmp_path
    )
    provider = DeterministicProvider(
        text=" ".join(["chunk"] * 120),  # ~840 chars per response
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider = provider
    app.provider_configured = True
    config = AgentLoopConfig(max_context_chars=4_000, max_turn_tokens=1_234)
    session, loop = app.open_chat_session(
        "context probe", AutoApproveGateway(), loop_config=config
    )
    for index in range(6):
        loop.run_turn(session, f"turn {index} " + "x" * 400)

    status = app.surface_context_status(session.session_id)
    sent = tuple(provider.requests[-1].messages)
    projected = app.tasks.project_session(session.task_id, session.session_id)

    # The shared rule must reproduce real traffic: the last provider call
    # happened before the trailing assistant reply was recorded, so the
    # pre-call history is the completed history minus that one message.
    assert projected.history[-1].role is ProviderMessageRole.ASSISTANT
    pre_call = tuple(projected.history[:-1])
    pre_view = trimmed_history_view(pre_call, config.max_context_chars)
    assert pre_view.dropped_turns > 0, "the probe must actually exercise trimming"
    assert tuple(pre_view.kept) == sent, "the shared rule is the rule the loop enforced"
    assert sum(len(message.content) for message in sent) == pre_view.used_chars

    # The endpoint reports the same rule over the durable history.
    view = trimmed_history_view(projected.history, config.max_context_chars)
    assert status.used_chars == view.used_chars
    assert status.used_chars < sum(len(message.content) for message in projected.history)
    assert status.history_chars == sum(
        len(message.content) for message in projected.history
    )
    assert status.history_chars > status.used_chars, "the untrimmed size is declared"
    assert status.dropped_turns == view.dropped_turns
    assert status.budget_chars == config.max_context_chars
    assert status.turn_token_budget == config.max_turn_tokens
    assert status.turns == 6
    assert status.message_count == projected.next_message_index
    # the provider context window is NOT known anywhere the runtime reads, so
    # the honest answer is "unset" — never an invented percentage
    assert status.window_tokens is None
    assert status.window_source == "unset"

    completions = [
        event.decoded_payload()["total_tokens"]
        for event in app.store.read(session.task_id)
        if event.event_type.value == "SESSION_TURN_COMPLETED"
    ]
    assert len(completions) == 6
    assert status.total_tokens == sum(completions)

    # read-only: asking again appends nothing
    before = app.store.read(session.task_id)
    app.surface_context_status(session.session_id)
    assert app.store.read(session.task_id) == before


def test_context_status_empty_session_no_leak_and_session_scoped(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    first, _ = app.open_chat_session("first session", AutoApproveGateway())
    second, _ = app.open_chat_session("second session", AutoApproveGateway())

    status = app.surface_context_status(first.session_id)
    assert status.session_id == first.session_id
    assert status.turns == 0
    assert status.total_tokens == 0
    assert status.message_count == 1  # the opening system message
    assert status.used_chars > 0  # the system prompt itself counts
    assert status.dropped_turns == 0

    # a turn on the other session never leaks into this one
    other, other_loop = app.open_chat_session("other session", AutoApproveGateway())
    other_loop.run_turn(other, "hello")
    assert app.surface_context_status(first.session_id).total_tokens == 0
    assert app.surface_context_status(other.session_id).total_tokens > 0
    assert app.surface_context_status(second.session_id).total_tokens == 0

    text = json.dumps(status.model_dump(mode="json"))
    for forbidden in FORBIDDEN:
        assert forbidden not in text, f"leaked field: {forbidden}"


def _legacy_trimmed(
    history: tuple[ProviderMessage, ...], budget: int
) -> tuple[ProviderMessage, ...]:
    """Frozen copy of the pre-refactor selection rule (the C1 risk is that the
    extraction changed which messages are sent, so the old rule is pinned here
    as a differential reference, not reimplemented from the new one)."""

    messages = tuple(history)
    if not messages:
        return ()
    total = sum(len(message.content) for message in messages)
    if total <= budget:
        return messages
    cut = 1  # never drop the system prompt
    while cut < len(messages) and total > budget:
        if messages[cut].role is not ProviderMessageRole.USER:
            cut += 1
            continue
        total -= len(messages[cut].content)
        cut += 1
        while cut < len(messages) and messages[cut].role is not ProviderMessageRole.USER:
            total -= len(messages[cut].content)
            cut += 1
    return (messages[0], *messages[cut:])


def test_trimmed_history_view_is_differentially_equal_to_the_legacy_rule() -> None:
    system = _message(ProviderMessageRole.SYSTEM, "s" * 7)
    user = _message(ProviderMessageRole.USER, "u" * 11)
    assistant = _message(ProviderMessageRole.ASSISTANT, "a" * 13)
    tool = _message(ProviderMessageRole.ASSISTANT, "t" * 5)
    shapes = [
        (),
        (system,),
        (system, user),
        (system, user, assistant),
        (system, user, assistant, user, assistant),
        (system, assistant, user),  # leading non-USER block
        (system, tool, user, assistant),
        (system, user, tool, user, tool, user, tool),
        (system, user, assistant, tool, user, assistant, tool, user, assistant),
    ]
    budgets = list(range(0, 120, 3)) + [10_000]
    for shape in shapes:
        for budget in budgets:
            expected = _legacy_trimmed(shape, budget)
            assert trimmed_history_view(shape, budget).kept == expected, (
                shape,
                budget,
            )


def test_context_status_budget_smaller_than_the_system_prompt_is_honest(
    tmp_path: Path,
) -> None:
    """The rule never drops the system prompt: `used_chars` may exceed the
    budget, and the projection says so instead of clamping the number."""

    app = _app(tmp_path)
    session, _ = app.open_chat_session(
        "tiny budget", AutoApproveGateway(), loop_config=AgentLoopConfig(max_context_chars=1)
    )
    status = app.surface_context_status(session.session_id)
    assert status.budget_chars == 1
    assert status.used_chars == status.history_chars  # only the system prompt remains
    assert status.used_chars > status.budget_chars


def test_context_status_is_tenant_scoped_and_indistinguishable_from_missing(
    tmp_path: Path,
) -> None:
    owner = _app(tmp_path)
    session, _ = owner.open_chat_session("owned", AutoApproveGateway())
    assert owner.surface_context_status(session.session_id).session_id == session.session_id

    other = _app(
        tmp_path,
        PrincipalIdentity(
            principal_id="user:other",
            tenant_id="tenant:other",
            workspace_id="workspace:other",
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=datetime.now(timezone.utc),
        ),
    )
    with pytest.raises(SurfaceSessionNotFound):
        other.surface_context_status(session.session_id)
    # the same class as a genuinely missing session: existence is not leaked
    with pytest.raises(SurfaceSessionNotFound):
        other.surface_context_status("session:missing")


def test_context_route_requires_bearer_and_returns_status(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _ = app.open_chat_session("route session", AutoApproveGateway())
    token = "test-local-token"
    handler = type(
        "TestContextHandler",
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
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/context",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["context"]["session_id"] == session.session_id
            assert payload["context"]["window_tokens"] is None

        anonymous = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/context"
        )
        with pytest.raises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(anonymous)
        assert unauth.value.code == 401

        unknown = urllib.request.Request(
            f"{base}/v1/surface/sessions/session:missing/context",
            headers={"Authorization": f"Bearer {token}"},
        )
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(unknown)
        assert missing.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
