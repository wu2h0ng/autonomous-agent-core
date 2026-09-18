"""Defect (b): a permission DENY has to be visible where it happened.

The kernel records `POLICY_VERDICT_RECORDED(DENY, basis=rule, rule_id=…)`, but the
record named only the *capability* and its action digest. No surface could
reconstruct which attempted action was refused (action id / node id / arguments),
and the model was told only "an operator permission rule forbids this capability"
— without the rule id. So the operator saw nothing and the model could report
"done" while the file was untouched.

These assertions are the bypass detector for that defect: dropping the identity
fields, the rule name, or the `denied` flag reddens them. A denial is still NOT a
proposal — `ACTION_PROPOSED` must stay absent on every deny path.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ProviderMessageRole,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceSetPermissionModeCommand,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    PermissionDenyRule,
    PermissionRuleKind,
)
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def _rule(rule_id: str = "rule-1", capability_id: str = "workspace.edit") -> PermissionDenyRule:
    return PermissionDenyRule(
        rule_id=rule_id,
        kind=PermissionRuleKind.DENY,
        capability_id=capability_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="operator",
        created_at=NOW,
        reason="deploy freeze",
    )


def _proposal(call_id: str, capability_id: str, arguments: dict) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _edit_script() -> tuple:
    return (
        (
            "",
            (
                _proposal(
                    "call-edit",
                    "workspace.edit",
                    {"path": "fixture.txt", "old_string": "stable\n", "new_string": "fixed\n"},
                ),
            ),
        ),
        ("edit applied", ()),
    )


def _outsider_script() -> tuple:
    return (
        (
            "",
            (_proposal("call-x", "workspace.exfiltrate", {"path": "fixture.txt"}),),
        ),
        ("nothing else to do", ()),
    )


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _wait_for(predicate, description: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"{description} did not occur within {timeout}s")


def _chat_app(root: Path, script: tuple) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=script, invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    return app


def _set_mode(app: AgentOSApplication, session_id: str, mode: str) -> None:
    task_id = app.surface_task_for_session(session_id)
    app.surface.set_permission_mode(
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


def _run_turn(app: AgentOSApplication, session_id: str) -> str:
    task_id = app.surface_task_for_session(session_id)
    stream_id = app.subscribe_stream(session_id)
    app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text="do the edit",
            stream=SurfaceStreamBinding(runtime_boot_id=app.runtime_boot_id, stream_id=stream_id),
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"turn:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )

    def _completed():
        events = [
            event
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
        ]
        return events or None

    events = _wait_for(_completed, "turn completion")
    return json.loads(events[-1].payload_json)["stop_reason"]


def _verdicts(app: AgentOSApplication, task_id: str) -> list[dict]:
    return [
        json.loads(event.payload_json)
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.POLICY_VERDICT_RECORDED
    ]


def _events_of(app: AgentOSApplication, task_id: str, event_type: TaskEventType) -> list:
    return [event for event in app.store.read(task_id) if event.event_type is event_type]


def _tool_messages_seen_by_the_model(app: AgentOSApplication) -> list[dict]:
    """The provider's own view: the last request is the one carrying the tool
    result the kernel fed back for the denied proposal."""
    provider = app.provider
    if not isinstance(provider, DeterministicProvider):
        return []
    requests = provider.requests
    if len(requests) < 2:
        return []
    return [
        json.loads(message.content)
        for message in requests[-1].messages
        if message.role is ProviderMessageRole.TOOL
    ]


def test_rule_deny_records_the_denied_action_identity(tmp_path: Path) -> None:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = _chat_app(tmp_path, _edit_script())
    app.permission_rule_store.save(_rule())
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")
    task_id = app.surface_task_for_session(session.session_id)

    _run_turn(app, session.session_id)

    denials = [
        verdict
        for verdict in _verdicts(app, task_id)
        if verdict.get("verdict") == "DENY" and verdict.get("basis") == "rule"
    ]
    assert len(denials) == 1, f"expected exactly one rule denial, got {denials}"
    denial = denials[0]
    # The rule is named, with the operator's own reason.
    assert denial["rule_id"] == "rule-1"
    assert denial["rule_reason"] == "deploy freeze"
    # The refused action is identified: which action, which node, which arguments.
    assert denial["capability_id"] == "workspace.edit"
    assert denial["action_id"], "the denied action must be identified by id"
    assert denial["node_id"], "the denied action must be identified by node id"
    assert json.loads(denial["arguments_json"])["path"] == "fixture.txt"
    assert denial["action_digest"]
    # The refused action was never proposed for execution, never received, and the
    # workspace file is untouched: this denial is a refusal, not a request.
    assert _events_of(app, task_id, TaskEventType.ACTION_PROPOSED) == []
    assert _events_of(app, task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_rule_deny_tells_the_model_which_rule_and_capability(tmp_path: Path) -> None:
    app = _chat_app(tmp_path, _edit_script())
    app.permission_rule_store.save(_rule())
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    _set_mode(app, session.session_id, "ACCEPT_IN_WORKSPACE")

    _run_turn(app, session.session_id)

    tool_messages = _tool_messages_seen_by_the_model(app)
    assert tool_messages, "the model must receive a tool result for the denied proposal"
    denial = tool_messages[-1]
    assert denial["denied"] is True
    assert denial["rule_id"] == "rule-1"
    assert denial["basis"] == "rule"
    assert denial["capability_id"] == "workspace.edit"
    assert "rule-1" in denial["error"], "the model-visible error must name the rule"
    assert not denial.get("executed")


def test_out_of_allowlist_deny_is_also_self_describing(tmp_path: Path) -> None:
    app = _chat_app(tmp_path, _outsider_script())
    session, _loop = app.open_chat_session("hi", DeferredApprovalGateway())
    task_id = app.surface_task_for_session(session.session_id)

    assert _run_turn(app, session.session_id) == "unauthorized_proposal"

    denials = [
        verdict
        for verdict in _verdicts(app, task_id)
        if verdict.get("verdict") == "DENY"
    ]
    assert len(denials) == 1, f"expected one denial, got {denials}"
    denial = denials[0]
    assert denial["basis"] == "out_of_allowlist"
    assert denial["capability_id"] == "workspace.exfiltrate"
    assert json.loads(denial["arguments_json"])["path"] == "fixture.txt"
    assert denial["reason"]
    assert _events_of(app, task_id, TaskEventType.ACTION_PROPOSED) == []
    assert _events_of(app, task_id, TaskEventType.ACTION_RECEIPT_RECORDED) == []
