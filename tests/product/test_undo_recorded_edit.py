"""S5a: undo one recorded chat edit (operator-triggered file undo).

Engine core only: `RunCoordinator.compensate_recorded_edit` +
`AgentOSApplication.undo_recorded_edit`. The undo goes through the existing
governance spine (proposed -> policy decision -> permit -> receipt ->
COMPENSATION_* records); the original receipt and the session history are
untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ProviderToolProposal,
    SurfaceClientRef,
    SurfaceSetPermissionModeCommand,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    RunExecutionError,
)

from apps.api_server.app import AgentOSApplication


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
        scripted=(
            ("editing fixture.txt", (_proposal("call:1"),)),
            ("done", ()),
        ),
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
    task_id = app.surface_task_for_session(session_id)
    app.surface.set_permission_mode(
        SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client(app),
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"mode:{session_id}:{mode}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _edit_action_id(app: AgentOSApplication, task_id: str) -> str:
    for event in reversed(app.store.read(task_id)):
        if event.event_type.value != "ACTION_PROPOSED":
            continue
        payload = event.decoded_payload()
        action = payload.get("action") if isinstance(payload, dict) else None
        if isinstance(action, dict) and action.get("capability_id") == "workspace.edit":
            return str(action["action_id"])
    raise AssertionError("no recorded workspace.edit action")


def test_undo_restores_the_before_image_and_records_the_compensation(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    session, loop = app.open_chat_session("undo probe", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    # the mode is a durable session event: restore so the loop sees it
    session, loop = app.restore_chat_session(session.session_id, DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"

    action_id = _edit_action_id(app, session.task_id)
    record = app.undo_recorded_edit(session.task_id, action_id=action_id)

    assert record.status.value == "COMPENSATED"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    events = [event.event_type.value for event in app.store.read(session.task_id)]
    assert "COMPENSATION_STARTED" in events
    assert "ACTION_COMPENSATED" in events
    # the governed shape: the compensation went through policy + a receipt
    assert "POLICY_DECIDED" in events


def test_undo_unknown_action_is_refused(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, _ = app.open_chat_session("undo probe", DeferredApprovalGateway())
    with pytest.raises(RunExecutionError, match="not found"):
        app.undo_recorded_edit(session.task_id, action_id="action:missing")


def test_undo_is_idempotent_through_the_sealed_replay(tmp_path: Path) -> None:
    app = _app(tmp_path)
    session, loop = app.open_chat_session("undo probe", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    # the mode is a durable session event: restore so the loop sees it
    session, loop = app.restore_chat_session(session.session_id, DeferredApprovalGateway())
    loop.run_turn(session, "please edit fixture.txt")
    action_id = _edit_action_id(app, session.task_id)

    first = app.undo_recorded_edit(session.task_id, action_id=action_id)
    second = app.undo_recorded_edit(session.task_id, action_id=action_id)

    assert first.status.value == "COMPENSATED"
    # the second call returns the EXISTING record: no second compensation
    # action, no second receipt (append-only, honest idempotency)
    assert second.status.value == "COMPENSATED"
    assert second.compensation_id == first.compensation_id
    assert second.receipt_id == first.receipt_id
    assert second.reason == first.reason
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
