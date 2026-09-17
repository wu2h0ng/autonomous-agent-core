"""Operator visibility for a tool call refused before dispatch.

Second failure-path round (2026-09-18). `workspace.edit` on a mode-0444 file is
refused by the connector preflight *before* the broker reserves anything
(`capability.py`, the pre-reservation deny check), so no `ActionReceipt` is
sealed and no `NODE_COMPLETED` exists. The model was told through the tool
result, but the durable stream - which is exactly what the TUI tool card and
`/export` project - held nothing at all for the call, so the card sat at
`⏵ pending` forever with no reason.

The fix is a node-level failure event carrying the reason. It is deliberately
NOT a receipt: a receipt attests that a dispatch executed and its effect is
known, and a refused call dispatched nothing. These tests pin the durable
signal, the absence of a receipt, and the negative control (a call that DID
execute must not look refused).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from agent_os_contracts import (
    ActionContract,
    ApprovalDisposition,
    ProviderMessageRole,
    ProviderToolProposal,
    TaskEventType,
)
from agent_os_core import (
    AutoApproveGateway,
    DeferredApprovalGateway,
    DeterministicProvider,
)
from apps.api_server.app import AgentOSApplication


def _proposal(
    call_id: str, capability_id: str, arguments: dict[str, Any]
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _app(root: Path, scripted: tuple[Any, ...] = ()) -> AgentOSApplication:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _payloads(
    app: AgentOSApplication, task_id: str, event_type: TaskEventType
) -> list[dict[str, Any]]:
    return [
        event.decoded_payload()
        for event in app.tasks._event_store.read(task_id)
        if event.event_type is event_type
    ]


def _event_types(app: AgentOSApplication, task_id: str) -> list[TaskEventType]:
    return [event.event_type for event in app.tasks._event_store.read(task_id)]


def _tool_messages(loop: Any) -> list[Any]:
    return [
        message for message in loop.history if message.role is ProviderMessageRole.TOOL
    ]


_NEEDS_UNPRIVILEGED_USER = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root writes through the read-only permission bit",
)


def _locked_file(root: Path) -> Path:
    locked = root / "locked.txt"
    locked.write_text("original\n", encoding="utf-8")
    os.chmod(locked, 0o444)
    return locked


@_NEEDS_UNPRIVILEGED_USER
def test_a_refused_write_records_a_node_failure_with_its_reason(
    tmp_path: Path,
) -> None:
    locked = _locked_file(tmp_path)
    app = _app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "locked.txt",
                            "old_string": "original",
                            "new_string": "changed",
                        },
                    ),
                ),
            ),
            ("it refused, so I stop here", ()),
        ),
    )
    session, loop = app.open_chat_session("edit the locked file", AutoApproveGateway())
    try:
        result = loop.run_turn(session, "edit it")

        # The model was told (that part always worked) ...
        tool_messages = _tool_messages(loop)
        assert len(tool_messages) == 1
        assert "is read-only (mode 0444)" in tool_messages[0].content
        assert result.stop_reason == "completed"
        # ... and the file is untouched, mode included.
        assert locked.read_text(encoding="utf-8") == "original\n"
        assert os.stat(locked).st_mode & 0o777 == 0o444

        # ... and the durable stream now says the same thing, so a surface that
        # projects it can converge the card instead of waiting forever.
        failures = _payloads(app, session.task_id, TaskEventType.NODE_FAILED)
        assert len(failures) == 1
        failure = failures[0]
        assert "is read-only (mode 0444)" in str(failure["error"])
        assert failure["exception"] == "CapabilityDenied"
        assert failure["capability_id"] == "workspace.edit"
        assert failure["provider_tool_call_id"] == "call-1"
        assert failure["agent_loop_dynamic_action"] is True

        # The refusal is NOT a dispatch: no receipt, no completion, no retry.
        events = _event_types(app, session.task_id)
        assert TaskEventType.ACTION_RECEIPT_RECORDED not in events
        assert TaskEventType.NODE_COMPLETED not in events
    finally:
        os.chmod(locked, 0o644)


@_NEEDS_UNPRIVILEGED_USER
def test_the_failure_event_binds_the_proposed_action_a_card_is_keyed_on(
    tmp_path: Path,
) -> None:
    """The tool card is created from ACTION_PROPOSED and updated by the action
    id (or the node id); a failure event that does not carry those keys cannot
    converge any card."""

    _locked_file(tmp_path)
    app = _app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "locked.txt",
                            "old_string": "original",
                            "new_string": "changed",
                        },
                    ),
                ),
            ),
            ("understood", ()),
        ),
    )
    session, loop = app.open_chat_session("edit the locked file", AutoApproveGateway())
    try:
        loop.run_turn(session, "edit it")
    finally:
        os.chmod(tmp_path / "locked.txt", 0o644)

    proposed = _payloads(app, session.task_id, TaskEventType.ACTION_PROPOSED)
    assert len(proposed) == 1
    action = ActionContract.model_validate(proposed[0]["action"])
    failure = _payloads(app, session.task_id, TaskEventType.NODE_FAILED)[0]

    assert failure["action_id"] == action.action_id
    assert failure["node_id"] == action.node_id
    assert failure["action_digest"] == action.action_digest()
    assert failure["error_code"] == "error:CapabilityDenied"


def test_a_policy_refusal_is_recorded_the_same_way(tmp_path: Path) -> None:
    """A refusal before dispatch is not only the connector's path: a correction
    halt denies the action in the policy kernel, and that call is equally
    invisible on the durable stream without a node failure."""

    app = _app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("cannot read, giving up", ()),
        ),
    )
    session, loop = app.open_chat_session("halted read", AutoApproveGateway())
    app.correction_admin.correct("capability", "workspace.read", "test halt")
    result = loop.run_turn(session, "read it")

    assert result.stop_reason == "completed"
    assert "policy denied" in _tool_messages(loop)[0].content

    failures = _payloads(app, session.task_id, TaskEventType.NODE_FAILED)
    assert len(failures) == 1
    assert "policy denied" in str(failures[0]["error"])
    assert TaskEventType.ACTION_RECEIPT_RECORDED not in _event_types(
        app, session.task_id
    )


@_NEEDS_UNPRIVILEGED_USER
def test_an_approved_call_refused_at_dispatch_is_also_recorded(
    tmp_path: Path,
) -> None:
    """The human approval gate is not the only way to reach a refusal: an
    approved edit whose file turns read-only between the approval request and
    the dispatch is refused by the same preflight, and that call used to leave
    the card pending too."""

    app = _app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "changed",
                        },
                    ),
                ),
            ),
            ("the edit did not land", ()),
        ),
    )
    session, loop = app.open_chat_session("edit the fixture", DeferredApprovalGateway())
    loop.run_turn(session, "edit it")
    projected = app.tasks.project_session(session.task_id, session.session_id)
    pending = projected.pending_continuation
    assert pending is not None, "the confirmation-required edit must park"

    locked = tmp_path / "fixture.txt"
    os.chmod(locked, 0o444)
    try:
        app.decide_session_approval(
            session.session_id,
            pending.action.action_digest(),
            ApprovalDisposition.APPROVE,
            "operator approves",
        )
    finally:
        os.chmod(locked, 0o644)

    failures = _payloads(app, session.task_id, TaskEventType.NODE_FAILED)
    assert len(failures) == 1
    assert "is read-only (mode 0444)" in str(failures[0]["error"])
    assert failures[0]["action_id"] == pending.action.action_id
    assert TaskEventType.ACTION_RECEIPT_RECORDED not in _event_types(
        app, session.task_id
    )
    assert locked.read_text(encoding="utf-8") == "stable\n"


def test_an_executed_call_is_not_reported_as_a_failure(tmp_path: Path) -> None:
    """Negative control: the signal must mean 'no result was sealed', not 'a
    tool was proposed'. An edit that really runs keeps its NODE_COMPLETED and
    never looks refused."""

    app = _app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "changed",
                        },
                    ),
                ),
            ),
            ("edited", ()),
        ),
    )
    session, loop = app.open_chat_session("edit the fixture", AutoApproveGateway())
    loop.run_turn(session, "edit it")

    events = _event_types(app, session.task_id)
    assert TaskEventType.NODE_FAILED not in events
    assert TaskEventType.NODE_COMPLETED in events
    assert TaskEventType.ACTION_RECEIPT_RECORDED in events
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "changed\n"
