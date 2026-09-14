"""S5a increment 2: `/undo [n]` over the Surface protocol.

The candidate set is durable-only (SUCCEEDED workspace.edit/apply_patch
receipts that still match the file, newest first, not yet compensated). A
candidate whose file changed since the edit is refused untouched; every undo
that does run goes through the governed compensation spine and appends new
records only — the original receipt and the session history stay readable.
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
    ProviderToolProposal,
    SurfaceClientRef,
    SurfaceSetPermissionModeCommand,
    SurfaceUndoCommand,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SurfaceRuntime,
    SurfaceSequenceConflict,
    SurfaceSessionNotFound,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes


def _proposal(call_id: str, old: str, new: str) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id="workspace.edit",
        arguments_json=json.dumps(
            {"path": "fixture.txt", "old_string": old, "new_string": new}
        ),
    )


def _scripted(*proposals: tuple[str, str, str]) -> tuple[Any, ...]:
    steps: list[Any] = []
    for call_id, old, new in proposals:
        steps.append(("editing fixture.txt", (_proposal(call_id, old, new),)))
        steps.append(("done", ()))
    return tuple(steps)


def _app(root: Path, principal: PrincipalIdentity | None = None) -> AgentOSApplication:
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root, principal=principal
    )
    app.provider = DeterministicProvider(
        scripted=_scripted(("call:1", "stable", "changed")),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client(app: AgentOSApplication) -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:undo:1",
        client_type="TEST",
        principal_id=app.principal.principal_id,
        tenant_id=app.principal.tenant_id,
        workspace_id=app.principal.workspace_id,
        device_id="device:undo:1",
    )


def _set_mode(app: AgentOSApplication, session_id: str, mode: str) -> None:
    app.surface.set_permission_mode(
        SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client(app),
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
            expected_event_sequence=app.surface_current_sequence(
                app.surface_task_for_session(session_id)
            ),
            idempotency_key=f"mode:{session_id}:{mode}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _edited_session(app: AgentOSApplication, prompts: list[str]) -> Any:
    session, _ = app.open_chat_session("undo probe", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    # the mode is a durable session event: restore so the loop sees it
    session, loop = app.restore_chat_session(session.session_id, DeferredApprovalGateway())
    for prompt in prompts:
        loop.run_turn(session, prompt)
    return session


def _command(
    app: AgentOSApplication,
    session_id: str,
    *,
    count: int = 1,
    key: str = "undo-1",
    expected_event_sequence: int | None = None,
) -> SurfaceUndoCommand:
    return SurfaceUndoCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(app),
        session_id=session_id,
        count=count,
        expected_event_sequence=(
            app.surface_current_sequence(app.surface_task_for_session(session_id))
            if expected_event_sequence is None
            else expected_event_sequence
        ),
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


def _event_types(app: AgentOSApplication, task_id: str) -> list[str]:
    return [event.event_type.value for event in app.store.read(task_id)]


def test_undo_restores_the_file_and_records_the_compensation(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"
    before = app.tasks.project_session(session.task_id, session.session_id)

    response = SurfaceRuntime(app).undo_last_edits(_command(app, session.session_id))

    assert response.session_id == session.session_id
    assert response.refused == ()
    assert len(response.undone) == 1
    entry = response.undone[0]
    assert entry.path == "fixture.txt"
    assert entry.status == "UNDONE"
    assert entry.action_id
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"

    # the governed shape: proposed -> policy -> receipt -> COMPENSATION_*
    events = _event_types(app, session.task_id)
    assert "COMPENSATION_STARTED" in events
    assert "ACTION_COMPENSATED" in events
    assert "POLICY_DECIDED" in events

    after = app.tasks.project_session(session.task_id, session.session_id)
    # append-only: the history, the index space and the original receipt survive
    assert after.history == before.history
    assert after.next_message_index == before.next_message_index
    receipts = [
        event.decoded_payload()["receipt"]
        for event in app.store.read(session.task_id)
        if event.event_type.value == "ACTION_RECEIPT_RECORDED"
    ]
    original = [
        receipt
        for receipt in receipts
        if receipt.get("action_id") == entry.action_id
    ]
    assert len(original) == 1
    assert original[0]["status"] == "SUCCEEDED"


def test_undo_refuses_when_the_file_changed_since_the_edit(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    (tmp_path / "fixture.txt").write_text("operator wrote this\n", encoding="utf-8")

    response = SurfaceRuntime(app).undo_last_edits(_command(app, session.session_id))

    assert response.undone == ()
    assert len(response.refused) == 1
    refused = response.refused[0]
    assert refused.path == "fixture.txt"
    assert refused.status == "REFUSED"
    assert "changed since this recorded edit" in refused.reason
    # the newer content is untouched and no compensation was attempted
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == (
        "operator wrote this\n"
    )
    events = _event_types(app, session.task_id)
    assert "COMPENSATION_STARTED" not in events
    assert "ACTION_COMPENSATED" not in events


def test_undo_nothing_left_is_an_empty_honest_result(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    runtime = SurfaceRuntime(app)

    first = runtime.undo_last_edits(_command(app, session.session_id))
    assert len(first.undone) == 1
    second = runtime.undo_last_edits(
        _command(app, session.session_id, key="undo-2")
    )

    assert second.undone == ()
    assert second.refused == ()
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_undo_replays_with_the_same_idempotency_key(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    runtime = SurfaceRuntime(app)
    command = _command(app, session.session_id)

    first = runtime.undo_last_edits(command)
    events_after_first = list(app.store.read(session.task_id))
    second = runtime.undo_last_edits(command)

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    # the replay is a read: nothing new was appended
    assert list(app.store.read(session.task_id)) == events_after_first
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_undo_two_edits_of_one_file_returns_to_the_original(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=_scripted(
            ("call:1", "stable", "changed"),
            ("call:2", "changed", "final"),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    session = _edited_session(app, ["first edit", "second edit"])
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "final\n"
    runtime = SurfaceRuntime(app)

    first = runtime.undo_last_edits(_command(app, session.session_id))
    assert len(first.undone) == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"
    second = runtime.undo_last_edits(
        _command(app, session.session_id, key="undo-2")
    )
    assert len(second.undone) == 1
    assert second.undone[0].action_id != first.undone[0].action_id
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_undo_count_two_covers_both_edits_in_one_command(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=_scripted(
            ("call:1", "stable", "changed"),
            ("call:2", "changed", "final"),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    session = _edited_session(app, ["first edit", "second edit"])

    response = SurfaceRuntime(app).undo_last_edits(
        _command(app, session.session_id, count=2)
    )

    assert response.refused == ()
    assert [entry.status for entry in response.undone] == ["UNDONE", "UNDONE"]
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    compensated = [
        event
        for event in app.store.read(session.task_id)
        if event.event_type.value == "ACTION_COMPENSATED"
    ]
    assert len(compensated) == 2


def test_session_keeps_working_after_undo(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=_scripted(
            ("call:1", "stable", "changed"),
            ("call:2", "stable", "changed again"),
        ),
        invocation_binding=app.provider.invocation_binding,
    )
    session, _ = app.open_chat_session("undo probe", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    session, loop = app.restore_chat_session(session.session_id, DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    runtime = SurfaceRuntime(app)
    runtime.undo_last_edits(_command(app, session.session_id))
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"

    # the same live loop keeps working: the next edit runs on the restored file
    loop.run_turn(session, "edit it again")

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed again\n"
    projected = app.tasks.project_session(session.task_id, session.session_id)
    assert projected.resumable_turn_id is None
    assert projected.next_message_index > 1


def test_undo_requires_quiescence_and_an_open_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("editing", (_proposal("call:1", "stable", "changed"),)),),
        invocation_binding=app.provider.invocation_binding,
    )
    session, loop = app.open_chat_session("pending", DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")

    with pytest.raises(InvalidTransitionError, match="turn is open"):
        SurfaceRuntime(app).undo_last_edits(_command(app, session.session_id))

    closed_app = _app(tmp_path / "closed")
    closed, _ = closed_app.open_chat_session("closing", DeferredApprovalGateway())
    closed_app.tasks.close_session(closed.task_id, closed.session_id)
    with pytest.raises(InvalidTransitionError, match="closed"):
        closed_app.surface_undo_last_edits(
            _command(closed_app, closed.session_id)
        )


def test_undo_hides_a_foreign_session(tmp_path: Path) -> None:
    owner = _app(tmp_path)
    session = _edited_session(owner, ["please edit fixture.txt"])

    # a second app over the same durable store: the workspace fixture file is
    # rewritten by the fixture builder, so the refusal is judged on the bytes
    # that are on disk at the moment of the refused command
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
    before_bytes = (tmp_path / "fixture.txt").read_bytes()
    with pytest.raises(SurfaceSessionNotFound):
        SurfaceRuntime(other).undo_last_edits(_command(other, session.session_id))
    # the foreign refusal is a read-only denial: the file is untouched
    assert (tmp_path / "fixture.txt").read_bytes() == before_bytes


def test_undo_enforces_sequence_cas(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    with pytest.raises(SurfaceSequenceConflict):
        SurfaceRuntime(app).undo_last_edits(
            _command(app, session.session_id, expected_event_sequence=0)
        )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"


def test_undo_route_requires_bearer_and_returns_entries(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session = _edited_session(app, ["please edit fixture.txt"])
    token = "test-local-token"
    handler = type(
        "TestUndoHandler",
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
    url = f"{base}/v1/surface/sessions/{session.session_id}/undo"
    try:
        body = _command(app, session.session_id).model_dump(mode="json")
        request = urllib.request.Request(
            url,
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
            assert payload["undo"]["undone"][0]["status"] == "UNDONE"
            assert payload["undo"]["undone"][0]["path"] == "fixture.txt"
            assert payload["undo"]["refused"] == []

        anonymous = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(anonymous)
        assert unauth.value.code == 401

        stale = _command(
            app, session.session_id, key="undo-stale", expected_event_sequence=0
        ).model_dump(mode="json")
        conflicted = urllib.request.Request(
            url,
            data=json.dumps(stale).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        with pytest.raises(urllib.error.HTTPError) as conflict:
            urllib.request.urlopen(conflicted)
        assert conflict.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
