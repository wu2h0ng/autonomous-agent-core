"""E2 permission-mode policy matrix (M2, test-first).

Frozen source: GC §E2 recording semantics + mode x tier x verdict matrix:
- tier-1 READ_ONLY auto-pass is the pre-existing tier default: no
  POLICY_VERDICT_RECORDED, no basis=permission_mode, no mode_event_id;
- ACCEPT_IN_WORKSPACE auto-allows tier-2 in-sandbox edits with the durable
  three-record chain (mode event + POLICY_VERDICT_RECORDED(ALLOW,
  basis=permission_mode, mode_event_id) + normal permit/receipt) and NEVER an
  ApprovalDecision(APPROVE);
- tier-3+ in-allowlist requires a real human ApprovalDecision in every mode;
- out-of-allowlist / sandbox escape is fail-closed denied in every mode,
  never executable, not approvable, denial recorded durably with reason.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
)
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication


def proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def chat_app(root: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _open_session(app: AgentOSApplication) -> Any:
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    return session


def _set_mode(app: AgentOSApplication, session_id: str, mode: str) -> Any:
    from agent_os_contracts import SurfaceSetPermissionModeCommand

    task_id = app.surface_task_for_session(session_id)
    return app.surface.set_permission_mode(
        SurfaceSetPermissionModeCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            mode=mode,  # type: ignore[arg-type]
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"mode:{session_id}:{mode}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _begin_turn(app: AgentOSApplication, session_id: str, stream_id: str) -> Any:
    task_id = app.surface_task_for_session(session_id)
    return app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text="do the edit",
            stream=SurfaceStreamBinding(
                runtime_boot_id=app.runtime_boot_id, stream_id=stream_id
            ),
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"turn:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _wait_for(predicate: Any, description: str, timeout: float = 5.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"{description} did not occur within {timeout}s")


def _turn_completed(app: AgentOSApplication, task_id: str, turn_id: str) -> Any:
    def _payload(event: Any) -> dict[str, Any]:
        return json.loads(event.payload_json)

    def _done() -> Any:
        for event in app.store.read(task_id):
            if event.event_type is not TaskEventType.SESSION_TURN_COMPLETED:
                continue
            payload = _payload(event)
            if payload.get("turn_id") == turn_id:
                return payload
        return None

    return _wait_for(_done, f"turn {turn_id} completion")


def _pending_approval(app: AgentOSApplication, task_id: str, session_id: str) -> Any:
    def _pending() -> Any:
        projected = app.tasks.project_session(task_id, session_id)
        return projected.pending_continuation

    return _wait_for(_pending, "pending approval")


def _verdicts(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    return [
        json.loads(event.payload_json)
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.POLICY_VERDICT_RECORDED
    ]


def _approvals(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    values = []
    for event in app.store.read(task_id):
        if event.event_type is not TaskEventType.APPROVAL_RECORDED:
            continue
        values.append(json.loads(event.payload_json)["approval"])
    return values


def _mode_event_ids(app: AgentOSApplication, task_id: str) -> list[str]:
    return [
        event.event_id
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.SESSION_PERMISSION_MODE_SET
    ]


def _edit_script() -> tuple:
    return (
        (
            "",
            (
                proposal(
                    "call-edit",
                    "workspace.edit",
                    {
                        "path": "fixture.txt",
                        "old_string": "stable\n",
                        "new_string": "fixed\n",
                    },
                ),
            ),
        ),
        ("edit applied", ()),
    )


def _run_turn_async(app: AgentOSApplication, session_id: str) -> Any:
    stream_id = app.subscribe_stream(session_id)
    response = _begin_turn(app, session_id, stream_id)
    return response


# ---------------------------------------------------------------------------
# Frozen matrix
# ---------------------------------------------------------------------------


def test_accept_in_workspace_auto_allows_tier2_with_provenance_chain(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=_edit_script())
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    mode_event_ids = _mode_event_ids(app, session.task_id)
    assert len(mode_event_ids) == 1

    response = _run_turn_async(app, session.session_id)
    completed = _turn_completed(app, session.task_id, response.turn_id)
    assert completed["stop_reason"] == "completed"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"

    verdicts = _verdicts(app, session.task_id)
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict["verdict"] == "ALLOW"
    assert verdict["basis"] == "permission_mode"
    assert verdict["mode_event_id"] == mode_event_ids[0]
    assert verdict["capability_id"] == "workspace.edit"
    assert verdict["action_digest"]
    # Auto-allow is NEVER a human ApprovalDecision.
    assert [
        a for a in _approvals(app, session.task_id) if a["disposition"] == "APPROVE"
    ] == []


def test_ask_mode_tier2_still_requires_interactive_approval(tmp_path: Path) -> None:
    app = chat_app(tmp_path, scripted=_edit_script())
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    response = _run_turn_async(app, session.session_id)
    _pending_approval(app, session.task_id, session.session_id)
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _verdicts(app, session.task_id) == []
    assert app.surface_has_uncommitted_turn(session.session_id) is True
    assert response.turn_id


def test_accept_read_only_tier2_still_requires_interactive_approval(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=_edit_script())
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_READ_ONLY")
    _run_turn_async(app, session.session_id)
    _pending_approval(app, session.task_id, session.session_id)
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _verdicts(app, session.task_id) == []


def test_accept_in_workspace_tier3_shell_still_requires_human_approval(
    tmp_path: Path,
) -> None:
    app = chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-shell",
                        "workspace.shell",
                        {"command": "echo hi"},
                    ),
                ),
            ),
            ("shell done", ()),
        ),
    )
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    _run_turn_async(app, session.session_id)
    pending = _pending_approval(app, session.task_id, session.session_id)
    assert pending is not None
    allow_verdicts = [
        v for v in _verdicts(app, session.task_id) if v["verdict"] == "ALLOW"
    ]
    assert allow_verdicts == []


def test_out_of_allowlist_is_fail_closed_denied_not_approvable(tmp_path: Path) -> None:
    app = chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-exfil",
                        "workspace.exfiltrate",
                        {"path": "fixture.txt"},
                    ),
                ),
            ),
            ("done", ()),
        ),
    )
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    response = _run_turn_async(app, session.session_id)
    completed = _turn_completed(app, session.task_id, response.turn_id)
    assert completed["stop_reason"] == "unauthorized_proposal"
    # The deny is recorded durably with reason; nothing is approvable.
    denies = [
        v
        for v in _verdicts(app, session.task_id)
        if v["verdict"] == "DENY" and v["basis"] == "out_of_allowlist"
    ]
    assert len(denies) == 1
    assert denies[0]["reason"]
    assert denies[0]["capability_id"] == "workspace.exfiltrate"
    assert denies[0]["action_digest"]
    assert (
        app.tasks.project_session(
            session.task_id, session.session_id
        ).pending_continuation
        is None
    )
    assert [
        a for a in _approvals(app, session.task_id) if a["disposition"] == "APPROVE"
    ] == []


def test_read_only_tier1_auto_pass_records_no_mode_provenance(tmp_path: Path) -> None:
    app = chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-read",
                        "workspace.read",
                        {"path": "fixture.txt"},
                    ),
                ),
            ),
            ("read done", ()),
        ),
    )
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    response = _run_turn_async(app, session.session_id)
    completed = _turn_completed(app, session.task_id, response.turn_id)
    assert completed["stop_reason"] == "completed"
    # READ_ONLY audit semantics: no verdict record at all for the auto-pass.
    assert _verdicts(app, session.task_id) == []
    assert [
        a for a in _approvals(app, session.task_id) if a["disposition"] == "APPROVE"
    ] == []


def test_bypass_constant_deny_under_mode_auto_allow(tmp_path: Path) -> None:
    """A constant-deny policy implementation fails here: under
    ACCEPT_IN_WORKSPACE the edit must actually execute."""
    app = chat_app(tmp_path, scripted=_edit_script())
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    session = _open_session(app)
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    response = _run_turn_async(app, session.session_id)
    completed = _turn_completed(app, session.task_id, response.turn_id)
    assert completed["stop_reason"] == "completed"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
