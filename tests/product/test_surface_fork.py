"""S3 fork: a child session with imported history; the parent is never written.

Gate conditions covered here: protected `SESSION_FORKED` provenance, byte
identical system prompt, raw parent-event import with a recomputable digest,
imported-turn markers with zero tokens, refusal on an uncommitted parent,
tenant scoping that hides foreign parents, child turn continuation.
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
    PrincipalIdentity,
    PrincipalRole,
    ProviderMessageRole,
    ProviderToolProposal,
    SurfaceClientRef,
    SurfaceForkCommand,
    content_digest,
)
from agent_os_core import (
    ChatSession,
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SurfaceRuntime,
    SurfaceSessionNotFound,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes


def _proposal(call_id: str) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id="workspace.edit",
        arguments_json=json.dumps(
            {"path": "fixture.txt", "old_string": "stable", "new_string": "changed"}
        ),
    )


def _app(root: Path, principal: PrincipalIdentity | None = None) -> AgentOSApplication:
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root, principal=principal
    )
    app.provider = DeterministicProvider(
        text="noted", invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    return app


def _parent_with_turns(app: AgentOSApplication) -> ChatSession:
    session, loop = app.open_chat_session("parent session", DeferredApprovalGateway())
    loop.run_turn(session, "first request")
    loop.run_turn(session, "second request")
    return session


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:fork:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:fork:1",
    )


def _command(app: AgentOSApplication, parent_session_id: str) -> SurfaceForkCommand:
    return SurfaceForkCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        parent_session_id=parent_session_id,
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(parent_session_id)
        ),
        idempotency_key="fork-1",
        requested_at=datetime.now(timezone.utc),
    )


def _raw_parent_messages(app: AgentOSApplication, task_id: str, session_id: str) -> list[Any]:
    records = []
    for event in app.store.read(task_id):
        if event.event_type.value != "SESSION_MESSAGE_RECORDED":
            continue
        payload = event.decoded_payload()
        if payload.get("session_id") != session_id:
            continue
        records.append(
            {
                "message_index": payload["message_index"],
                "turn_id": payload.get("turn_id"),
                "message": payload["message"],
            }
        )
    records.sort(key=lambda item: item["message_index"])
    return records


def test_fork_imports_history_and_never_touches_the_parent(tmp_path: Path) -> None:
    app = _app(tmp_path)
    parent = _parent_with_turns(app)
    runtime = SurfaceRuntime(app)
    parent_events_before = list(app.store.read(parent.task_id))
    parent_projection_before = app.tasks.project_session(parent.task_id, parent.session_id)

    response = runtime.fork_session(_command(app, parent.session_id))

    child_id = response.snapshot.session.session_id
    assert child_id != parent.session_id
    assert response.snapshot.session.task_id != parent.task_id
    assert response.parent_session_id == parent.session_id
    assert response.imported_turns == 2

    child = app.tasks.project_session(response.snapshot.session.task_id, child_id)
    assert child.forked_from == parent.session_id
    assert child.permission_mode == "ASK", "a fork never inherits an auto mode"
    assert child.next_message_index == parent_projection_before.next_message_index
    assert child.history[0].content == parent_projection_before.history[0].content
    assert child.history[0].role is ProviderMessageRole.SYSTEM
    assert child.history[1:] == parent_projection_before.history[1:], (
        "imported messages are byte-identical to the parent's"
    )
    assert response.imported_messages == parent_projection_before.next_message_index - 1
    user_turns = [
        message for message in child.history if message.role is ProviderMessageRole.USER
    ]
    assert len(user_turns) == 2

    # imported turn completions are marked and carry zero tokens (honest: the
    # child was never billed for them)
    completions = [
        event.decoded_payload()
        for event in app.store.read(response.snapshot.session.task_id)
        if event.event_type.value == "SESSION_TURN_COMPLETED"
    ]
    assert len(completions) == 2
    assert all(payload["imported"] is True for payload in completions)
    assert all(payload["total_tokens"] == 0 for payload in completions)
    assert all(payload["stop_reason"] == "imported" for payload in completions)

    # the digest is recomputable from the parent's own raw event payloads
    records = _raw_parent_messages(app, parent.task_id, parent.session_id)
    assert content_digest({"imported_messages": records[1:]}) == response.imported_history_digest

    # the parent is untouched: same events, same projection
    assert list(app.store.read(parent.task_id)) == parent_events_before
    assert app.tasks.project_session(parent.task_id, parent.session_id) == parent_projection_before


def test_fork_refuses_a_parent_with_an_uncommitted_turn(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("editing", (_proposal("call:1"),)),),
        invocation_binding=app.provider.invocation_binding,
    )
    session, loop = app.open_chat_session("pending parent", DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    assert app.tasks.project_session(session.task_id, session.session_id).pending_continuation

    with pytest.raises(InvalidTransitionError, match="uncommitted turn"):
        SurfaceRuntime(app).fork_session(_command(app, session.session_id))


def test_fork_hides_a_foreign_parent(tmp_path: Path) -> None:
    owner = _app(tmp_path)
    parent = _parent_with_turns(owner)

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
        SurfaceRuntime(other).fork_session(_command(other, parent.session_id))


def test_forked_child_continues_its_own_turns(tmp_path: Path) -> None:
    app = _app(tmp_path)
    parent = _parent_with_turns(app)
    response = SurfaceRuntime(app).fork_session(_command(app, parent.session_id))
    child_id = response.snapshot.session.session_id
    before = app.tasks.project_session(response.snapshot.session.task_id, child_id)

    restored, loop = app.restore_chat_session(child_id, DeferredApprovalGateway())
    loop.run_turn(restored, "first child turn")

    after = app.tasks.project_session(response.snapshot.session.task_id, child_id)
    assert after.next_message_index == before.next_message_index + 2  # user + assistant
    assert after.resumable_turn_id is None
    assert after.history[0] == before.history[0]
    assert after.history[-1].role is ProviderMessageRole.ASSISTANT


def test_fork_is_idempotent_for_the_same_command(tmp_path: Path) -> None:
    app = _app(tmp_path)
    parent = _parent_with_turns(app)
    runtime = SurfaceRuntime(app)
    command = _command(app, parent.session_id)
    first = runtime.fork_session(command)
    second = runtime.fork_session(command)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")


def test_fork_route_requires_bearer_and_returns_the_child(tmp_path: Path) -> None:
    app = _app(tmp_path)
    parent = _parent_with_turns(app)
    token = "test-local-token"
    handler = type(
        "TestForkHandler",
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
        body = _command(app, parent.session_id).model_dump(mode="json")
        request = urllib.request.Request(
            f"{base}/v1/surface/sessions/{parent.session_id}/fork",
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
            assert payload["fork"]["parent_session_id"] == parent.session_id
            assert payload["fork"]["imported_turns"] == 2

        anonymous = urllib.request.Request(
            f"{base}/v1/surface/sessions/{parent.session_id}/fork",
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
