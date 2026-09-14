"""S2 Ctrl-E: the narrow, display-only explanation channel for a pending action.

The digest authority is the durable projection; the call goes through the
no-authority provider decision path (no tools on the wire); nothing is written
(no event append, no transcript entry) and the response is `durable: false`.
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
    ProviderToolProposal,
    SurfaceClientRef,
    SurfaceExplainCommand,
)
from agent_os_core import (
    AgentLoop,
    ChatSession,
    DeferredApprovalGateway,
    DeterministicProvider,
    SurfaceScopeError,
    SurfaceRuntime,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

EXPLANATION = "This action rewrites fixture.txt in place; risk tier 2."


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
    # scripted[0] answers the turn (proposal -> pending approval);
    # scripted[1] answers the explain decision call.
    app.provider = DeterministicProvider(
        scripted=(
            ("editing fixture.txt", (_proposal("call:1"),)),
            (EXPLANATION, ()),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:explain:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:explain:1",
    )


def _pending_session(app: AgentOSApplication) -> tuple[ChatSession, AgentLoop, str]:
    """Open a session and drive it into a real pending approval; return the
    session, its loop and the durable action digest."""

    session, loop = app.open_chat_session("explain probe", DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    projected = app.tasks.project_session(session.task_id, session.session_id)
    pending = projected.pending_continuation
    assert pending is not None, "the probe must produce a pending approval"
    return session, loop, pending.action.action_digest()


def _command(
    app: AgentOSApplication, session_id: str, action_digest: str
) -> SurfaceExplainCommand:
    return SurfaceExplainCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        session_id=session_id,
        action_digest=action_digest,
        idempotency_key="explain-1",
        requested_at=datetime.now(timezone.utc),
    )


def test_explain_is_display_only_and_writes_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    runtime = SurfaceRuntime(app)
    before = app.store.read(session.task_id)
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)

    response = runtime.explain_action(_command(app, session.session_id, digest))

    assert response.durable is False
    assert response.cost_status == "UNKNOWN"
    assert response.action_digest == digest
    assert response.text == EXPLANATION
    assert response.total_tokens > 0
    # nothing durable changed: no event was appended by the explanation
    assert app.store.read(session.task_id) == before
    # the call went through the narrow decision channel, not a turn request
    assert provider.decision_requests, "explain must use ProviderPort.decide"
    decision = provider.decision_requests[-1]
    assert decision.decision_kind == "ACTION_EXPLANATION"
    payload = str(decision.messages)
    assert "explain probe" not in payload, "the session statement is never sent"
    assert "tenant" not in payload, "tenant/workspace detail is never sent"


def test_explain_rejects_a_digest_that_is_not_the_pending_action(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, _ = _pending_session(app)
    runtime = SurfaceRuntime(app)
    with pytest.raises(ValueError, match="does not match the pending action"):
        runtime.explain_action(_command(app, session.session_id, "digest:wrong"))


def test_explain_requires_a_pending_approval(tmp_path: Path) -> None:
    app = _app(tmp_path)
    # the loop binds the provider at open time: install the text-only provider
    # BEFORE opening so the turn completes without an approval
    app.provider = DeterministicProvider(
        text="nothing to do",
        invocation_binding=app.provider.invocation_binding,
    )
    session, loop = app.open_chat_session("no pending", DeferredApprovalGateway())
    loop.run_turn(session, "hello")
    runtime = SurfaceRuntime(app)
    with pytest.raises(ValueError, match="requires a pending approval"):
        runtime.explain_action(_command(app, session.session_id, "digest:any"))


def test_explain_fails_closed_without_a_live_provider_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    runtime = SurfaceRuntime(app)
    # a reconfigured live provider: same shape, different profile content
    binding = app.provider.invocation_binding
    other_profile = binding.provider_profile.model_copy(update={"model_id": "other-model"})
    other_binding = binding.model_copy(
        update={"provider_profile": other_profile, "model_id": "other-model"}
    )
    app.provider = DeterministicProvider(text="other", invocation_binding=other_binding)
    with pytest.raises(ValueError, match="provider profile to still be live"):
        runtime.explain_action(_command(app, session.session_id, digest))

    second = _app(tmp_path / "second")
    second_session, _, second_digest = _pending_session(second)
    second.provider_configured = False
    with pytest.raises(ValueError, match="configure a provider"):
        SurfaceRuntime(second).explain_action(
            _command(second, second_session.session_id, second_digest)
        )


def test_explain_discards_an_authority_shaped_answer(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    runtime = SurfaceRuntime(app)
    before = app.store.read(session.task_id)
    app.provider = DeterministicProvider(
        scripted=(("I will do it", (_proposal("call:2"),)),),
        invocation_binding=app.provider.invocation_binding,
    )
    with pytest.raises(ValueError, match="authority-shaped"):
        runtime.explain_action(_command(app, session.session_id, digest))
    assert app.store.read(session.task_id) == before


def test_explain_maps_a_provider_failure(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    runtime = SurfaceRuntime(app)

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

    app.provider = FailingProvider(invocation_binding=app.provider.invocation_binding)
    with pytest.raises(ValueError, match="provider call failed"):
        runtime.explain_action(_command(app, session.session_id, digest))


def test_explain_is_scoped_and_idempotent(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    runtime = SurfaceRuntime(app)

    foreign = _command(app, session.session_id, digest)
    foreign = foreign.model_copy(
        update={
            "client": foreign.client.model_copy(
                update={"tenant_id": "tenant:someone-else"}
            )
        }
    )
    with pytest.raises(SurfaceScopeError):
        runtime.explain_action(foreign)

    command = _command(app, session.session_id, digest)
    first = runtime.explain_action(command)
    second = runtime.explain_action(command)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")


def test_explain_route_requires_bearer_and_returns_the_explanation(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    session, _, digest = _pending_session(app)
    token = "test-local-token"
    handler = type(
        "TestExplainHandler",
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
        body = _command(app, session.session_id, digest).model_dump(mode="json")
        request = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/explain",
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
            assert payload["explanation"]["durable"] is False
            assert payload["explanation"]["action_digest"] == digest

        anonymous = urllib.request.Request(
            f"{base}/v1/surface/sessions/{session.session_id}/explain",
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
