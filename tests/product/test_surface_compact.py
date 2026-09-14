"""S4 `/compact`: one durable compaction record + a raw/view split.

Gate conditions (CONTEXT-COMPACT-0 `REVISE_TO_SPEC`): the raw history and the
durable index space are unchanged (`history`, `next_message_index`); only the
derived `context_view` (system prompt + one untrusted summary + tail) is what
the provider request and `/context` consume. Compaction requires quiescence,
the summary comes from the narrow decision channel, and a provider failure
leaves no event behind.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessageRole,
    ProviderToolProposal,
    SurfaceClientRef,
    SurfaceCompactCommand,
    content_digest,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SurfaceRuntime,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

SUMMARY = "Earlier: the operator asked for two changes; both were noted."


def _proposal(call_id: str) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id="workspace.edit",
        arguments_json=json.dumps(
            {"path": "fixture.txt", "old_string": "stable", "new_string": "changed"}
        ),
    )


def _app(root: Path) -> AgentOSApplication:
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("noted", ()), ("noted again", ()), (SUMMARY, ())),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _session_with_turns(app: AgentOSApplication, turns: int = 2) -> Any:
    session, loop = app.open_chat_session("compact probe", DeferredApprovalGateway())
    for index in range(turns):
        loop.run_turn(session, f"request {index}")
    return session


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:compact:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:compact:1",
    )


def _command(app: AgentOSApplication, session_id: str) -> SurfaceCompactCommand:
    return SurfaceCompactCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        session_id=session_id,
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key="compact-1",
        requested_at=datetime.now(timezone.utc),
    )


def test_compact_rewrites_only_the_request_view(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _session_with_turns(app)
    before = app.tasks.project_session(session.task_id, session.session_id)
    runtime = SurfaceRuntime(app)

    response = runtime.compact_session(_command(app, session.session_id))

    assert response.summary == SUMMARY
    assert response.untrusted is True
    assert response.durable is True
    assert response.cost_status == "UNKNOWN"
    assert response.replaced_to_message_index == before.next_message_index - 1
    assert response.summary_digest == content_digest({"summary": SUMMARY})

    after = app.tasks.project_session(session.task_id, session.session_id)
    # the raw history and the durable index space are untouched
    assert after.history == before.history
    assert after.next_message_index == before.next_message_index
    assert after.compaction is not None
    assert after.compaction.summary == SUMMARY
    # the request view is [system, untrusted summary] — the tail is empty here
    assert len(after.context_view) == 2
    assert after.context_view[0] == before.history[0]
    assert after.context_view[1].role is ProviderMessageRole.ASSISTANT
    assert "model-generated, untrusted" in after.context_view[1].content
    assert SUMMARY in after.context_view[1].content
    assert after.context_view[1].content.encode("utf-8").startswith(
        "[context summary".encode("utf-8")
    )

    status = app.surface_context_status(session.session_id)
    assert status.compactions == 1
    assert status.used_chars == sum(
        len(message.content) for message in after.context_view
    )
    assert status.history_chars == sum(
        len(message.content) for message in after.history
    )
    # the recorded char counts are the true ones; a summary may legitimately be
    # longer than a tiny history (reported, never clamped or pretended away)
    assert after.compaction.before_chars == status.history_chars
    assert after.compaction.after_chars == status.used_chars


def test_compacted_session_resumes_and_continues_turns(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _session_with_turns(app)
    SurfaceRuntime(app).compact_session(_command(app, session.session_id))
    before = app.tasks.project_session(session.task_id, session.session_id)

    restored, loop = app.restore_chat_session(session.session_id, DeferredApprovalGateway())
    loop.run_turn(restored, "after compaction")

    after = app.tasks.project_session(session.task_id, session.session_id)
    # durable indices continue from the raw history, not from the shrunken view
    assert after.next_message_index == before.next_message_index + 2
    assert after.resumable_turn_id is None
    assert after.history[: len(before.history)] == before.history
    assert after.context_view[1].content == before.context_view[1].content


def test_compact_requires_quiescence(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("editing", (_proposal("call:1"),)),),
        invocation_binding=app.provider.invocation_binding,
    )
    session, loop = app.open_chat_session("pending", DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    runtime = SurfaceRuntime(app)
    with pytest.raises(InvalidTransitionError, match="open turn"):
        runtime.compact_session(_command(app, session.session_id))

    empty_app = _app(tmp_path / "second")
    empty, _ = empty_app.open_chat_session("empty", DeferredApprovalGateway())
    with pytest.raises(ValueError, match="nothing to compact yet"):
        SurfaceRuntime(empty_app).compact_session(_command(empty_app, empty.session_id))


def test_compact_is_refused_twice_and_provider_failure_leaves_no_event(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    session = _session_with_turns(app)
    runtime = SurfaceRuntime(app)
    runtime.compact_session(_command(app, session.session_id))
    with pytest.raises(InvalidTransitionError, match="already has a compaction record"):
        runtime.compact_session(
            _command(app, session.session_id).model_copy(
                update={"idempotency_key": "compact-2"}
            )
        )

    # provider failure: the summary call fails and nothing is recorded
    other = _session_with_turns(_app(tmp_path / "third"))
    failing_app = _app(tmp_path / "fourth")
    failing_session = _session_with_turns(failing_app)

    class FailingProvider(DeterministicProvider):
        def decide(self, request: Any) -> ProviderFailure:
            return ProviderFailure(
                failure_id="failure:1",
                request_id=request.request_id,
                code=ProviderErrorCode.TIMEOUT,
                retryable=True,
                safe_message="timed out",
                occurred_at=datetime.now(timezone.utc),
            )

    failing_app.provider = FailingProvider(
        invocation_binding=failing_app.provider.invocation_binding
    )
    before_events = list(
        failing_app.store.read(failing_session.task_id)
    )
    with pytest.raises(RuntimeError, match="retryable=True"):
        SurfaceRuntime(failing_app).compact_session(
            _command(failing_app, failing_session.session_id)
        )
    assert list(failing_app.store.read(failing_session.task_id)) == before_events
    assert other is not None  # keep the third session alive for isolation


def test_compact_rejects_an_authority_shaped_summary(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _session_with_turns(app)
    before_events = list(app.store.read(session.task_id))
    app.provider = DeterministicProvider(
        scripted=(("I will do it", (_proposal("call:9"),)),),
        invocation_binding=app.provider.invocation_binding,
    )
    with pytest.raises(ValueError, match="authority-shaped"):
        SurfaceRuntime(app).compact_session(_command(app, session.session_id))
    assert list(app.store.read(session.task_id)) == before_events


def test_compact_route_requires_bearer_and_returns_the_summary(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _session_with_turns(app)
    token = "test-local-token"
    handler = type(
        "TestCompactHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = _command(app, session.session_id).model_dump(mode="json")
        request = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/compact",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["compaction"]["summary"] == SUMMARY
            assert payload["compaction"]["untrusted"] is True

        anonymous = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/compact",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(anonymous)
        assert unauth.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_summary_survives_request_side_trimming(tmp_path: Path) -> None:
    """Review P1 (F1): the compaction summary is part of the mandatory request
    prefix — trimming must never silently drop it."""

    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=tmp_path
    )
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    provider = DeterministicProvider(
        scripted=(
            ("short answer", ()),
            ("short answer", ()),
            ("short answer", ()),
            (SUMMARY, ()),
            ("after compaction", ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider = provider
    app.provider_configured = True
    from agent_os_core.agent_loop import AgentLoopConfig

    session, loop = app.open_chat_session(
        "trim probe",
        DeferredApprovalGateway(),
        loop_config=AgentLoopConfig(max_context_chars=1_200),
    )
    for index in range(3):
        loop.run_turn(session, f"request number {index} " + "x" * 400)

    status_before = app.surface_context_status(session.session_id)
    assert status_before.compactions == 0

    SurfaceRuntime(app).compact_session(_command(app, session.session_id))

    restored, loop_after = app.restore_chat_session(
        session.session_id, DeferredApprovalGateway()
    )
    for index in range(3):
        loop_after.run_turn(restored, f"post compaction {index} " + "y" * 400)

    sent = tuple(provider.requests[-1].messages)
    assert any(
        message.content.startswith("[context summary") for message in sent
    ), "the summary must always be sent, trimming or not"
    status = app.surface_context_status(session.session_id)
    assert status.compactions == 1
    assert status.dropped_turns > 0, "the probe must exercise trimming"
    # the status describes the completed history, which is never smaller than
    # the last request's view
    assert status.used_chars >= sum(len(message.content) for message in sent)


def test_compact_refuses_a_closed_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _ = app.open_chat_session("closed soon", DeferredApprovalGateway())
    app.tasks.close_session(session.task_id, session.session_id)
    with pytest.raises(InvalidTransitionError, match="closed"):
        app.surface_compact_session(_command(app, session.session_id))
