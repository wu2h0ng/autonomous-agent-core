from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from agent_os_contracts import (
    ActionContract,
    ApprovalDisposition,
    PendingSurfaceApproval,
    PrincipalIdentity,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolProposal,
    RunStatus,
    TaskEventDraft,
    TaskEventType,
    TurnId,
)
from agent_os_core import (
    AgentLoop,
    AgentLoopConfig,
    AutoApproveGateway,
    ChatSession,
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SessionProjector,
    TaskConfigurationDrift,
)
from agent_os_core.action_pipeline import ActionPipeline

from apps.api_server.app import AgentOSApplication


def proposal(
    call_id: str,
    capability_id: str,
    arguments: dict[str, object],
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def chat_app(
    root: Path,
    scripted=(),
    *,
    principal: PrincipalIdentity | None = None,
) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
        principal=principal,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _receipt_count(app: AgentOSApplication, task_id: str) -> int:
    return sum(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        for event in app.store.read(task_id)
    )


def _event_count(
    app: AgentOSApplication,
    task_id: str,
    event_type: TaskEventType,
) -> int:
    return sum(event.event_type is event_type for event in app.store.read(task_id))


def _approve_pending(
    app: AgentOSApplication,
    session: ChatSession,
    pending: PendingSurfaceApproval,
) -> Any:
    return app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )


def _pending_edit(
    tmp_path: Path,
) -> tuple[AgentOSApplication, ChatSession, PendingSurfaceApproval]:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = chat_app(
        tmp_path,
        scripted=(
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
        ),
    )
    session, loop = app.open_chat_session("edit", DeferredApprovalGateway())
    waiting = loop.run_turn(session, "edit fixture")
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert waiting.stop_reason == "approval_required"
    assert projected.pending_approval is not None
    assert projected.resumable_turn_id == waiting.turn_id.turn_id
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.WAITING_APPROVAL
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED) == 0
    return app, session, projected.pending_approval


def _pending_edit_then_read(
    tmp_path: Path,
    *,
    final_text: str | None = None,
) -> tuple[AgentOSApplication, ChatSession, PendingSurfaceApproval, TurnId]:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    scripted: tuple[tuple[str, tuple[ProviderToolProposal, ...]], ...] = (
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
                proposal(
                    "call-read",
                    "workspace.read",
                    {"path": "fixture.txt"},
                ),
            ),
        ),
    )
    if final_text is not None:
        scripted += ((final_text, ()),)
    app = chat_app(tmp_path, scripted=scripted)
    session, loop = app.open_chat_session("two tools", DeferredApprovalGateway())
    waiting = loop.run_turn(session, "edit then read")
    pending = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    ).pending_approval
    assert waiting.stop_reason == "approval_required"
    assert pending is not None
    return app, session, pending, waiting.turn_id


def _draft_has_message(
    drafts: tuple[TaskEventDraft, ...],
    *,
    role: str,
    tool_call_id: str | None = None,
    content: str | None = None,
) -> bool:
    for draft in drafts:
        payload_json = getattr(draft, "payload_json", "")
        payload = json.loads(payload_json)
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != role:
            continue
        if tool_call_id is not None and message.get("tool_call_id") != tool_call_id:
            continue
        if content is not None and message.get("content") != content:
            continue
        return True
    return False


def test_restart_reuses_durable_history_without_replaying_first_turn(
    tmp_path: Path,
) -> None:
    app1 = chat_app(tmp_path, scripted=(("first", ()),))
    session, loop = app1.open_chat_session("durable", AutoApproveGateway())
    assert loop.run_turn(session, "first request").text == "first"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("second", ()),))
    restored, restored_loop = app2.restore_chat_session(
        session.session_id, AutoApproveGateway()
    )
    result = restored_loop.run_turn(restored, "second request")

    assert result.text == "second"
    assert isinstance(app2.provider, DeterministicProvider)
    request_messages = app2.provider.requests[0].messages
    assert [message.content for message in request_messages if message.content] == [
        AgentLoopConfig().system_prompt,
        "first request",
        "first",
        "second request",
    ]


def test_restart_restores_non_default_prompt_and_step_limit(tmp_path: Path) -> None:
    config = AgentLoopConfig(
        max_steps_per_turn=1,
        loop_detection_threshold=2,
        system_prompt="frozen custom system prompt",
    )
    app1 = chat_app(tmp_path, scripted=(("first", ()),))
    session, loop = app1.open_chat_session(
        "custom durable",
        AutoApproveGateway(),
        loop_config=config,
    )
    assert loop.run_turn(session, "first request").text == "first"
    app1.store.close()

    app2 = chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            ("must not be reached", ()),
        ),
    )
    restored, restored_loop = app2.restore_chat_session(
        session.session_id, AutoApproveGateway()
    )
    result = restored_loop.run_turn(restored, "second request")

    assert result.stop_reason == "max_steps"
    assert isinstance(app2.provider, DeterministicProvider)
    assert len(app2.provider.requests) == 1
    assert app2.provider.requests[0].messages[0].content == config.system_prompt


def test_resume_turn_rejects_fabricated_turn_before_provider_call(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=(("must not run", ()),))
    session, loop = app.open_chat_session("durable turn", AutoApproveGateway())
    fabricated = TurnId(
        turn_id="turn:fabricated",
        session_id=session.session_id,
    )
    initial_history = loop.history

    with pytest.raises(ValueError, match="durable started turn"):
        loop.resume_turn(session, fabricated)

    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    assert loop.history == initial_history


def test_resume_turn_rejects_completed_turn_before_provider_call(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=(("completed", ()),))
    session, loop = app.open_chat_session("completed turn", AutoApproveGateway())
    completed = loop.run_turn(session, "one request")
    completed_history = loop.history
    assert isinstance(app.provider, DeterministicProvider)
    request_count = len(app.provider.requests)

    with pytest.raises(ValueError, match="durable started turn"):
        loop.resume_turn(session, completed.turn_id)

    assert len(app.provider.requests) == request_count
    assert loop.history == completed_history


@pytest.mark.parametrize("tampered_binding", ("envelope", "expected"))
def test_resume_turn_rejects_forged_chat_session_before_provider_call(
    tmp_path: Path,
    tampered_binding: str,
) -> None:
    app = chat_app(tmp_path, scripted=(("must not run", ()),))
    session, loop = app.open_chat_session("scoped turn", AutoApproveGateway())
    started = TurnId(turn_id="turn:started", session_id=session.session_id)
    app.tasks.record_session_message(
        session.task_id,
        session.session_id,
        len(loop.history),
        ProviderMessage(role=ProviderMessageRole.USER, content="durable user"),
        turn_id=started.turn_id,
    )
    app.tasks.append_event(
        session.task_id,
        TaskEventType.SESSION_TURN_STARTED,
        {
            "turn_id": started.turn_id,
            "session_id": session.session_id,
            "user_text": "durable user",
        },
        correlation_id=session.run_id,
    )
    restored, restored_loop = app.restore_chat_session(
        session.session_id, AutoApproveGateway()
    )
    forged = (
        ChatSession(
            ref=restored.ref,
            envelope_id="envelope:forged",
            expected=restored.expected,
        )
        if tampered_binding == "envelope"
        else ChatSession(
            ref=restored.ref,
            envelope_id=restored.envelope_id,
            expected=restored.expected.model_copy(
                update={"expected_outcome_id": "expected:forged"}
            ),
        )
    )

    with pytest.raises(ValueError, match="session binding mismatch"):
        restored_loop.resume_turn(forged, started)

    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []


def test_run_turn_rejects_when_durable_turn_is_already_open(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=(("must not run", ()),))
    session, loop = app.open_chat_session("one open turn", AutoApproveGateway())
    started = TurnId(turn_id="turn:started", session_id=session.session_id)
    app.tasks.record_session_message(
        session.task_id,
        session.session_id,
        len(loop.history),
        ProviderMessage(role=ProviderMessageRole.USER, content="durable user"),
        turn_id=started.turn_id,
    )
    app.tasks.append_event(
        session.task_id,
        TaskEventType.SESSION_TURN_STARTED,
        {
            "turn_id": started.turn_id,
            "session_id": session.session_id,
            "user_text": "durable user",
        },
        correlation_id=session.run_id,
    )
    restored, restored_loop = app.restore_chat_session(
        session.session_id, AutoApproveGateway()
    )

    with pytest.raises(ValueError, match="already has an open durable turn"):
        restored_loop.run_turn(restored, "second request")

    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    assert (
        SessionProjector(app.store)
        .project(session.task_id, session.session_id)
        .resumable_turn_id
        == started.turn_id
    )


def test_history_does_not_advance_when_durable_sink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = chat_app(tmp_path, scripted=(("unreachable", ()),))
    session, loop = app.open_chat_session("durable", AutoApproveGateway())
    initial_history = loop.history

    def reject_message(*_args: object) -> None:
        raise RuntimeError("durable sink unavailable")

    monkeypatch.setattr(loop, "_message_sink", reject_message)
    with pytest.raises(RuntimeError, match="durable sink unavailable"):
        loop.run_turn(session, "must persist first")

    assert loop.history == initial_history
    assert SessionProjector(app.store).project(
        session.task_id, session.session_id
    ).history == initial_history


def test_restore_rejects_closed_session(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session, _loop = app.open_chat_session("closed", AutoApproveGateway())
    app.tasks.close_session(session.task_id, session.session_id)

    with pytest.raises(ValueError, match="closed"):
        app.restore_chat_session(session.session_id, AutoApproveGateway())


def test_restore_rejects_corrupt_history_with_second_system_message(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path)
    session, loop = app.open_chat_session("corrupt", AutoApproveGateway())
    app.tasks.record_session_message(
        session.task_id,
        session.session_id,
        len(loop.history),
        ProviderMessage(
            role=ProviderMessageRole.SYSTEM,
            content=AgentLoopConfig().system_prompt,
        ),
        turn_id=None,
    )

    with pytest.raises(ValueError, match="exactly one leading"):
        app.restore_chat_session(session.session_id, AutoApproveGateway())


def test_restore_rejects_principal_scope_mismatch(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session, _loop = app.open_chat_session("scoped", AutoApproveGateway())
    other_principal = app.principal.model_copy(
        update={"workspace_id": "workspace:other"}
    )
    other_app = chat_app(tmp_path, principal=other_principal)

    with pytest.raises(PermissionError, match="scope mismatch"):
        other_app.restore_chat_session(session.session_id, AutoApproveGateway())


def test_restore_rejects_terminal_run(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session, _loop = app.open_chat_session("terminal", AutoApproveGateway())
    app.cancel_task(session.task_id)

    with pytest.raises(ValueError, match="terminal"):
        app.restore_chat_session(session.session_id, AutoApproveGateway())


def test_restore_rejects_configuration_profile_drift(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session, _loop = app.open_chat_session("bound", AutoApproveGateway())
    app.provider_profile = app.provider_profile.model_copy(
        update={"model_id": "drifted-model"}
    )

    with pytest.raises(TaskConfigurationDrift):
        app.restore_chat_session(session.session_id, AutoApproveGateway())


def test_pending_approval_survives_restart_and_executes_once(
    tmp_path: Path,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("edit completed", ()),))
    resumed = _approve_pending(app2, session, pending)

    assert resumed.stop_reason == "completed"
    assert resumed.text == "edit completed"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    assert _receipt_count(app2, session.task_id) == 1
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.pending_approval is None
    assert projected.resumable_turn_id is None


def test_stale_approval_digest_does_not_execute(tmp_path: Path) -> None:
    app, session, _pending = _pending_edit(tmp_path)

    with pytest.raises(InvalidTransitionError, match="digest"):
        app.decide_session_approval(
            session.session_id,
            action_digest="0" * 64,
            disposition=ApprovalDisposition.APPROVE,
            reason="wrong action",
        )

    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_proposed_action_and_pending_state_append_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = chat_app(
        tmp_path,
        scripted=(
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
        ),
    )
    session, loop = app.open_chat_session("atomic pending", DeferredApprovalGateway())
    original_append_batch = app.tasks._append_batch

    def reject_pending_batch(*args: Any, **kwargs: Any) -> Any:
        events = args[1]
        if any(
            event_type is TaskEventType.SESSION_APPROVAL_PENDING
            for event_type, _payload in events
        ):
            raise RuntimeError("pending batch unavailable")
        return original_append_batch(*args, **kwargs)

    monkeypatch.setattr(app.tasks, "_append_batch", reject_pending_batch)
    with pytest.raises(RuntimeError, match="pending batch unavailable"):
        loop.run_turn(session, "edit fixture")

    events = app.store.read(session.task_id)
    assert not any(
        event.event_type is TaskEventType.ACTION_PROPOSED for event in events
    )
    assert not any(
        event.event_type is TaskEventType.SESSION_APPROVAL_PENDING
        for event in events
    )
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_rejected_approval_appends_tool_denial_and_allows_replan(
    tmp_path: Path,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    app1.store.close()
    app2 = chat_app(tmp_path, scripted=(("kept stable", ()),))

    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="do not edit this file",
    )

    assert resumed.stop_reason == "completed"
    assert resumed.text == "kept stable"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _receipt_count(app2, session.task_id) == 0
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    tool_messages = tuple(
        message
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    )
    assert len(tool_messages) == 1
    denial = json.loads(tool_messages[0].content)
    assert denial["rejected"] is True
    assert "do not edit this file" in denial["error"]


class _ProcessCrash(BaseException):
    pass


def test_restart_after_approval_recorded_before_execution_reuses_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    original_execute = ActionPipeline.execute

    def crash_before_execute(*_args: object, **_kwargs: object) -> None:
        raise _ProcessCrash("after approval before execution")

    monkeypatch.setattr(ActionPipeline, "execute", crash_before_execute)
    with pytest.raises(_ProcessCrash, match="before execution"):
        _approve_pending(app1, session, pending)
    monkeypatch.setattr(ActionPipeline, "execute", original_execute)

    assert _event_count(app1, session.task_id, TaskEventType.APPROVAL_RECORDED) == 1
    assert _receipt_count(app1, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("edit completed", ()),))
    resumed = _approve_pending(app2, session, pending)

    assert resumed.stop_reason == "completed"
    assert _event_count(app2, session.task_id, TaskEventType.APPROVAL_RECORDED) == 1
    assert _receipt_count(app2, session.task_id) == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"


def test_restart_after_receipt_before_tool_continues_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    original_append_batch = app1.tasks._append_batch

    def crash_before_resolution(*args: Any, **kwargs: Any) -> Any:
        events = args[1]
        if any(
            event_type is TaskEventType.SESSION_APPROVAL_RESOLVED
            for event_type, _payload in events
        ):
            raise _ProcessCrash("after receipt before TOOL resolution")
        return original_append_batch(*args, **kwargs)

    monkeypatch.setattr(app1.tasks, "_append_batch", crash_before_resolution)
    with pytest.raises(_ProcessCrash, match="after receipt"):
        _approve_pending(app1, session, pending)

    assert _receipt_count(app1, session.task_id) == 1
    assert _event_count(
        app1,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    ) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued once", ()),))
    resumed = _approve_pending(app2, session, pending)

    assert resumed.text == "continued once"
    assert _receipt_count(app2, session.task_id) == 1
    assert _event_count(
        app2,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    ) == 1
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    assert len(
        [
            message
            for message in projected.history
            if message.role is ProviderMessageRole.TOOL
        ]
    ) == 1


def test_effect_and_receipt_cannot_be_rewritten_as_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    original_append_batch = app1.tasks._append_batch

    def crash_before_resolution(*args: Any, **kwargs: Any) -> Any:
        events = args[1]
        if any(
            event_type is TaskEventType.SESSION_APPROVAL_RESOLVED
            for event_type, _payload in events
        ):
            raise _ProcessCrash("after receipt before TOOL resolution")
        return original_append_batch(*args, **kwargs)

    monkeypatch.setattr(app1.tasks, "_append_batch", crash_before_resolution)
    with pytest.raises(_ProcessCrash, match="after receipt"):
        _approve_pending(app1, session, pending)

    assert _receipt_count(app1, session.task_id) == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued from success", ()),))
    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="too late to reject an executed action",
    )

    assert resumed.stop_reason == "completed"
    assert resumed.text == "continued from success"
    assert _receipt_count(app2, session.task_id) == 1
    approvals = [
        event.decoded_payload()["approval"]
        for event in app2.store.read(session.task_id)
        if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert [approval["disposition"] for approval in approvals] == ["APPROVE"]
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    tools = [
        json.loads(message.content)
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    ]
    assert len(tools) == 1
    assert tools[0].get("rejected") is not True
    assert tools[0]["path"] == "fixture.txt"


def test_paused_pending_approval_cannot_dispatch(
    tmp_path: Path,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.pause_task(session.task_id)

    with pytest.raises(InvalidTransitionError):
        app.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="must not execute while paused",
        )

    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _event_count(app, session.task_id, TaskEventType.POLICY_DECIDED) == 0


def test_reject_from_paused_clears_pending_without_provider_continuation(
    tmp_path: Path,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("must not continue", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.pause_task(session.task_id)

    result = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="reject without executing while paused",
    )

    assert result.stop_reason == "paused"
    assert _receipt_count(app, session.task_id) == 0
    assert _event_count(app, session.task_id, TaskEventType.POLICY_DECIDED) == 0
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.pending_continuation is None
    assert projected.resolved_continuation is not None
    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []


@pytest.mark.parametrize("resume_mode", ("decision", "turn"))
def test_paused_resolved_approval_requires_explicit_run_resume(
    tmp_path: Path,
    resume_mode: str,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("continued only after explicit resume", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.pause_task(session.task_id)
    rejected = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="reject without executing while paused",
    )
    assert rejected.stop_reason == "paused"
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.resolved_continuation is not None

    def resume() -> Any:
        if resume_mode == "decision":
            return app.decide_session_approval(
                session.session_id,
                action_digest=pending.action_digest,
                disposition=ApprovalDisposition.REJECT,
                reason="reject without executing while paused",
            )
        restored, restored_loop = app.restore_chat_session(
            session.session_id,
            DeferredApprovalGateway(),
        )
        assert projected.resumable_turn_id is not None
        return restored_loop.resume_turn(
            restored,
            TurnId(
                turn_id=projected.resumable_turn_id,
                session_id=session.session_id,
            ),
        )

    with pytest.raises(InvalidTransitionError, match="RUNNING|resume"):
        resume()

    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    assert _receipt_count(app, session.task_id) == 0

    app.resume_task(session.task_id)
    resumed = resume()
    assert resumed.stop_reason == "completed"
    assert resumed.text == "continued only after explicit resume"
    assert len(app.provider.requests) == 1
    assert _event_count(app, session.task_id, TaskEventType.RUN_RESUMED) == 1


def test_run_turn_on_paused_run_fails_before_provider_call(tmp_path: Path) -> None:
    app = chat_app(tmp_path, scripted=(("must not run while paused", ()),))
    session, loop = app.open_chat_session("paused-probe", AutoApproveGateway())
    app.resume_task(session.task_id)
    app.pause_task(session.task_id)
    restored, restored_loop = app.restore_chat_session(
        session.session_id,
        AutoApproveGateway(),
    )

    with pytest.raises(InvalidTransitionError, match="runnable|resume"):
        restored_loop.run_turn(restored, "new request while paused")

    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    assert (
        _event_count(app, session.task_id, TaskEventType.SESSION_TURN_STARTED) == 0
    )


class _RaisingProvider(DeterministicProvider):
    def __init__(self, binding: Any) -> None:
        super().__init__(scripted=(), invocation_binding=binding)
        self.calls = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1
        raise RuntimeError("provider mid-turn failure")


def test_generic_resume_turn_on_paused_run_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path)
    raising = _RaisingProvider(app.provider.invocation_binding)
    app.provider = raising
    session, loop = app.open_chat_session("paused-resume-probe", AutoApproveGateway())
    app.resume_task(session.task_id)
    with pytest.raises(RuntimeError, match="mid-turn"):
        loop.run_turn(session, "first request")
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.resumable_turn_id is not None
    assert raising.calls == 1
    app.pause_task(session.task_id)

    restored, restored_loop = app.restore_chat_session(
        session.session_id,
        AutoApproveGateway(),
    )
    with pytest.raises(InvalidTransitionError, match="runnable|resume"):
        restored_loop.resume_turn(
            restored,
            TurnId(
                turn_id=projected.resumable_turn_id,
                session_id=session.session_id,
            ),
        )
    assert raising.calls == 1
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED


@pytest.mark.parametrize(
    "loser_disposition",
    [ApprovalDisposition.REJECT, ApprovalDisposition.APPROVE],
)
def test_concurrent_approve_claim_has_one_winner_without_run_poisoning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    loser_disposition: ApprovalDisposition,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    app1.provider = DeterministicProvider(
        scripted=(("winner continued", ()),),
        invocation_binding=app1.provider.invocation_binding,
    )
    app2 = chat_app(tmp_path, scripted=(("loser must not continue", ()),))
    entered = threading.Event()
    release = threading.Event()
    original_dispatch = app1.sandbox._dispatch

    def blocking_dispatch(
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        entered.set()
        assert release.wait(timeout=5)
        return original_dispatch(capability_id, args, action_key)

    monkeypatch.setattr(app1.sandbox, "_dispatch", blocking_dispatch)
    winner_results: list[object] = []
    winner_errors: list[BaseException] = []

    def approve() -> None:
        try:
            winner_results.append(_approve_pending(app1, session, pending))
        except BaseException as exc:  # pragma: no cover - asserted below
            winner_errors.append(exc)

    thread = threading.Thread(target=approve)
    thread.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(InvalidTransitionError, match="claim|APPROVE|progress"):
            app2.decide_session_approval(
                session.session_id,
                action_digest=pending.action_digest,
                disposition=loser_disposition,
                reason=(
                    "reject raced too late"
                    if loser_disposition is ApprovalDisposition.REJECT
                    else "duplicate approve caller"
                ),
            )
        assert _event_count(app2, session.task_id, TaskEventType.RUN_PAUSED) == 0
    finally:
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert winner_errors == []
    assert len(winner_results) == 1
    winner = winner_results[0]
    assert getattr(winner, "stop_reason") == "completed"
    assert getattr(winner, "text") == "winner continued"
    assert _receipt_count(app1, session.task_id) == 1
    assert _event_count(
        app1,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_EXECUTION_CLAIMED,
    ) == 1
    approvals = [
        event.decoded_payload()["approval"]["disposition"]
        for event in app1.store.read(session.task_id)
        if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert approvals == ["APPROVE"]
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    assert isinstance(app2.provider, DeterministicProvider)
    assert app2.provider.requests == []


def test_duplicate_approve_without_claim_ownership_cannot_reserve_or_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending = _pending_edit(tmp_path)
    app1.provider = DeterministicProvider(
        scripted=(("owner continued", ()),),
        invocation_binding=app1.provider.invocation_binding,
    )
    app2 = chat_app(tmp_path, scripted=(("non-owner must not continue", ()),))
    claim_committed = threading.Event()
    release_owner = threading.Event()
    original_record = app1.tasks.record_or_reuse_session_approval

    def claim_then_block(*args: Any, **kwargs: Any) -> Any:
        authority = original_record(*args, **kwargs)
        if authority.acquired:
            claim_committed.set()
            assert release_owner.wait(timeout=5)
        return authority

    monkeypatch.setattr(
        app1.tasks,
        "record_or_reuse_session_approval",
        claim_then_block,
    )
    owner_results: list[object] = []
    owner_errors: list[BaseException] = []

    def approve_as_owner() -> None:
        try:
            owner_results.append(_approve_pending(app1, session, pending))
        except BaseException as exc:  # pragma: no cover - asserted below
            owner_errors.append(exc)

    owner = threading.Thread(target=approve_as_owner)
    owner.start()
    assert claim_committed.wait(timeout=5)
    try:
        with pytest.raises(InvalidTransitionError, match="progress|in progress"):
            _approve_pending(app2, session, pending)
        assert _receipt_count(app2, session.task_id) == 0
        assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
        assert isinstance(app2.provider, DeterministicProvider)
        assert app2.provider.requests == []
    finally:
        release_owner.set()
        owner.join(timeout=5)

    assert not owner.is_alive()
    assert owner_errors == []
    assert len(owner_results) == 1
    assert getattr(owner_results[0], "stop_reason") == "completed"
    assert _receipt_count(app1, session.task_id) == 1
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    assert _event_count(
        app1,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_EXECUTION_CLAIMED,
    ) == 1


def test_correction_between_approval_and_execution_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("must not continue", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    original_execute = ActionPipeline.execute

    def correct_then_execute(
        pipeline: ActionPipeline,
        action: ActionContract,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        app.correction.correct(
            "capability",
            action.capability_id,
            "operator correction during approval continuation",
        )
        return original_execute(pipeline, action, *args, **kwargs)

    monkeypatch.setattr(ActionPipeline, "execute", correct_then_execute)
    stopped = _approve_pending(app, session, pending)

    assert stopped.stop_reason == "correction_blocked"
    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.pending_continuation is not None
    assert all(
        message.role is not ProviderMessageRole.TOOL
        for message in projected.history
    )
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    app.cancel_task(session.task_id)
    assert SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    ).pending_continuation is None


def test_correction_change_cannot_race_approval_claim_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    original_append_guarded = app.store.append_guarded

    def correct_before_guarded_append(*args: Any, **kwargs: Any) -> Any:
        app.correction.correct(
            "capability",
            "workspace.edit",
            "operator correction before approval claim commit",
        )
        return original_append_guarded(*args, **kwargs)

    monkeypatch.setattr(app.store, "append_guarded", correct_before_guarded_append)

    with pytest.raises(InvalidTransitionError, match="correction|C7|stale"):
        _approve_pending(app, session, pending)

    assert _event_count(app, session.task_id, TaskEventType.APPROVAL_RECORDED) == 0
    assert _event_count(
        app,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_EXECUTION_CLAIMED,
    ) == 0
    assert _event_count(app, session.task_id, TaskEventType.POLICY_DECIDED) == 0
    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


def test_unknown_effect_keeps_pending_and_stops_provider_continuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("must not replan", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    dispatches = 0

    def effect_then_disconnect(
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        nonlocal dispatches
        dispatches += 1
        (tmp_path / "unknown-effect.txt").write_text(
            "effect may have happened\n",
            encoding="utf-8",
        )
        raise RuntimeError("connector disconnected after effect")

    monkeypatch.setattr(app.sandbox, "_dispatch", effect_then_disconnect)
    result = _approve_pending(app, session, pending)

    assert result.stop_reason == "unknown_requires_review"
    assert dispatches == 1
    assert isinstance(app.provider, DeterministicProvider)
    assert app.provider.requests == []
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.pending_approval == pending
    assert not any(
        message.role is ProviderMessageRole.TOOL for message in projected.history
    )
    assert _event_count(
        app, session.task_id, TaskEventType.SESSION_APPROVAL_RESOLVED
    ) == 0
    assert _event_count(
        app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED
    ) == 0
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED

    retry = _approve_pending(app, session, pending)
    assert retry.stop_reason == "unknown_requires_review"
    assert dispatches == 1
    assert app.provider.requests == []
    with pytest.raises(InvalidTransitionError, match="UNKNOWN_REQUIRES_REVIEW"):
        app.resume_task(session.task_id)


def test_non_deferred_unknown_stops_without_tool_reply_or_replan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = chat_app(
        tmp_path,
        scripted=(
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
            ("must not replan", ()),
        ),
    )
    session, loop = app.open_chat_session("unknown", AutoApproveGateway())
    dispatches = 0

    def effect_then_disconnect(
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        nonlocal dispatches
        dispatches += 1
        (tmp_path / "unknown-effect.txt").write_text("applied\n", encoding="utf-8")
        raise RuntimeError("connector disconnected after effect")

    monkeypatch.setattr(app.sandbox, "_dispatch", effect_then_disconnect)
    result = loop.run_turn(session, "edit")

    assert result.stop_reason == "unknown_requires_review"
    assert dispatches == 1
    assert isinstance(app.provider, DeterministicProvider)
    assert len(app.provider.requests) == 1
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert not any(
        message.role is ProviderMessageRole.TOOL for message in projected.history
    )
    assert projected.resumable_turn_id == result.turn_id.turn_id
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED


def test_reject_after_c7_change_clears_pending_and_allows_replan(
    tmp_path: Path,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("rejected after correction", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.correction.correct(
        "capability",
        "workspace.edit",
        "operator correction before rejection",
    )

    result = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="reject stale proposal",
    )

    assert result.stop_reason == "completed"
    assert result.text == "rejected after correction"
    assert _receipt_count(app, session.task_id) == 0
    assert SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    ).pending_approval is None


def test_cancel_after_c7_change_clears_pending_and_ends_turn(
    tmp_path: Path,
) -> None:
    app, session, _pending = _pending_edit(tmp_path)
    app.correction.correct(
        "capability",
        "workspace.edit",
        "operator correction before cancellation",
    )

    cancelled = app.cancel_task(session.task_id)

    assert cancelled.run is not None
    assert cancelled.run.status is RunStatus.CANCELLED
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    assert projected.pending_approval is None
    assert projected.pending_continuation is None
    assert projected.resumable_turn_id is None
    assert _receipt_count(app, session.task_id) == 0


def test_stale_claimed_approve_cannot_be_rewritten_to_reject_and_can_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    original_execute = ActionPipeline.execute

    def crash_before_execute(*_args: object, **_kwargs: object) -> None:
        raise _ProcessCrash("approval persisted")

    monkeypatch.setattr(ActionPipeline, "execute", crash_before_execute)
    with pytest.raises(_ProcessCrash, match="approval persisted"):
        _approve_pending(app, session, pending)
    monkeypatch.setattr(ActionPipeline, "execute", original_execute)
    app.correction.correct(
        "capability",
        "workspace.edit",
        "operator correction after approval persistence",
    )

    with pytest.raises(InvalidTransitionError, match="C7|correction|stale"):
        _approve_pending(app, session, pending)

    with pytest.raises(InvalidTransitionError, match="claim|APPROVE|progress"):
        app.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.REJECT,
            reason="reject after correction",
        )
    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert _event_count(
        app,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    ) == 0
    assert not any(
        message.role is ProviderMessageRole.TOOL
        for message in SessionProjector(app.store)
        .project(session.task_id, session.session_id)
        .history
    )

    cancelled = app.cancel_task(session.task_id)
    assert cancelled.run is not None
    assert cancelled.run.status is RunStatus.CANCELLED
    assert SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    ).pending_approval is None


@pytest.mark.parametrize("resume_mode", ("decision", "turn"))
def test_restart_after_resolution_batch_resumes_exact_remaining_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resume_mode: str,
) -> None:
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app1 = chat_app(
        tmp_path,
        scripted=(
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
                    proposal(
                        "call-read",
                        "workspace.read",
                        {"path": "fixture.txt"},
                    ),
                ),
            ),
        ),
    )
    session, loop = app1.open_chat_session("two tools", DeferredApprovalGateway())
    waiting = loop.run_turn(session, "edit then read")
    pending = SessionProjector(app1.store).project(
        session.task_id,
        session.session_id,
    ).pending_approval
    assert waiting.stop_reason == "approval_required"
    assert pending is not None
    original_drive = AgentLoop._drive

    def crash_after_resolution(*_args: object, **_kwargs: object) -> None:
        raise _ProcessCrash("after resolution batch")

    monkeypatch.setattr(AgentLoop, "_drive", crash_after_resolution)
    with pytest.raises(_ProcessCrash, match="resolution batch"):
        _approve_pending(app1, session, pending)
    monkeypatch.setattr(AgentLoop, "_drive", original_drive)

    checkpoint = SessionProjector(app1.store).project(
        session.task_id,
        session.session_id,
    )
    assert checkpoint.pending_approval is None
    assert checkpoint.resolved_continuation is not None
    assert checkpoint.resolved_continuation.next_proposal_index == 1
    assert checkpoint.resolved_continuation.steps == 1
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued exactly", ()),))
    if resume_mode == "decision":
        resumed = _approve_pending(app2, session, pending)
    else:
        restored, restored_loop = app2.restore_chat_session(
            session.session_id,
            DeferredApprovalGateway(),
        )
        resumed = restored_loop.resume_turn(
            restored,
            TurnId(
                turn_id=waiting.turn_id.turn_id,
                session_id=session.session_id,
            ),
        )

    assert resumed.stop_reason == "completed"
    assert resumed.text == "continued exactly"
    assert resumed.steps == 2
    assert _receipt_count(app2, session.task_id) == 2
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    tool_ids = [
        message.tool_call_id
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    ]
    assert tool_ids == ["call-edit", "call-read"]
    assert projected.resolved_continuation is None
    assert projected.resumable_turn_id is None


def test_restart_after_second_receipt_before_tool_reuses_exact_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending, turn_id = _pending_edit_then_read(tmp_path)
    original_append = app1.store.append

    def crash_before_second_tool(
        task_id: str,
        *,
        expected_sequence: int,
        drafts: tuple[TaskEventDraft, ...],
    ) -> object:
        if _draft_has_message(drafts, role="TOOL", tool_call_id="call-read"):
            raise _ProcessCrash("after second receipt before TOOL")
        return original_append(
            task_id,
            expected_sequence=expected_sequence,
            drafts=drafts,
        )

    monkeypatch.setattr(app1.store, "append", crash_before_second_tool)
    with pytest.raises(_ProcessCrash, match="second receipt"):
        _approve_pending(app1, session, pending)

    events_before = app1.store.read(session.task_id)
    read_actions_before = [
        ActionContract.model_validate(event.decoded_payload()["action"])
        for event in events_before
        if event.event_type is TaskEventType.ACTION_PROPOSED
        and event.decoded_payload()["action"]["capability_id"] == "workspace.read"
    ]
    assert _receipt_count(app1, session.task_id) == 2
    assert len(read_actions_before) == 1
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued exactly", ()),))
    restored, restored_loop = app2.restore_chat_session(
        session.session_id,
        DeferredApprovalGateway(),
    )
    resumed = restored_loop.resume_turn(
        restored,
        TurnId(turn_id=turn_id.turn_id, session_id=session.session_id),
    )

    assert resumed.stop_reason == "completed"
    assert resumed.text == "continued exactly"
    assert _receipt_count(app2, session.task_id) == 2
    read_actions_after = [
        ActionContract.model_validate(event.decoded_payload()["action"])
        for event in app2.store.read(session.task_id)
        if event.event_type is TaskEventType.ACTION_PROPOSED
        and event.decoded_payload()["action"]["capability_id"] == "workspace.read"
    ]
    assert read_actions_after == read_actions_before
    projected = SessionProjector(app2.store).project(
        session.task_id,
        session.session_id,
    )
    assert [
        message.tool_call_id
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    ] == ["call-edit", "call-read"]


def test_restart_after_second_tool_checkpoint_skips_exact_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app1, session, pending, turn_id = _pending_edit_then_read(tmp_path)
    original_append = app1.store.append

    def crash_after_second_tool(
        task_id: str,
        *,
        expected_sequence: int,
        drafts: tuple[TaskEventDraft, ...],
    ) -> object:
        appended = original_append(
            task_id,
            expected_sequence=expected_sequence,
            drafts=drafts,
        )
        if _draft_has_message(drafts, role="TOOL", tool_call_id="call-read"):
            raise _ProcessCrash("after second TOOL checkpoint")
        return appended

    monkeypatch.setattr(app1.store, "append", crash_after_second_tool)
    with pytest.raises(_ProcessCrash, match="second TOOL"):
        _approve_pending(app1, session, pending)
    checkpoint = SessionProjector(app1.store).project(
        session.task_id,
        session.session_id,
    )
    assert checkpoint.resolved_continuation is not None
    assert checkpoint.resolved_continuation.next_proposal_index == 2
    assert _receipt_count(app1, session.task_id) == 2
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued exactly", ()),))
    restored, restored_loop = app2.restore_chat_session(
        session.session_id,
        DeferredApprovalGateway(),
    )
    resumed = restored_loop.resume_turn(
        restored,
        TurnId(turn_id=turn_id.turn_id, session_id=session.session_id),
    )

    assert resumed.stop_reason == "completed"
    assert resumed.text == "continued exactly"
    assert _receipt_count(app2, session.task_id) == 2
    assert isinstance(app2.provider, DeterministicProvider)
    assert len(app2.provider.requests) == 1


def test_final_assistant_and_turn_completion_commit_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_text = "continued exactly"
    app1, session, pending, _turn_id = _pending_edit_then_read(
        tmp_path,
        final_text=final_text,
    )
    original_append = app1.store.append

    def crash_after_final_assistant(
        task_id: str,
        *,
        expected_sequence: int,
        drafts: tuple[TaskEventDraft, ...],
    ) -> object:
        appended = original_append(
            task_id,
            expected_sequence=expected_sequence,
            drafts=drafts,
        )
        if _draft_has_message(drafts, role="ASSISTANT", content=final_text):
            raise _ProcessCrash("after final assistant transaction")
        return appended

    monkeypatch.setattr(app1.store, "append", crash_after_final_assistant)
    with pytest.raises(_ProcessCrash, match="final assistant"):
        _approve_pending(app1, session, pending)

    projected = SessionProjector(app1.store).project(
        session.task_id,
        session.session_id,
    )
    assert [message.content for message in projected.history].count(final_text) == 1
    assert _event_count(
        app1,
        session.task_id,
        TaskEventType.SESSION_TURN_COMPLETED,
    ) == 1
    assert projected.resumable_turn_id is None
    assert projected.resolved_continuation is None
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("follow-up complete", ()),))
    restored, restored_loop = app2.restore_chat_session(
        session.session_id,
        DeferredApprovalGateway(),
    )
    follow_up = restored_loop.run_turn(restored, "follow-up")

    assert follow_up.text == "follow-up complete"
    assert isinstance(app2.provider, DeterministicProvider)
    assert len(app2.provider.requests) == 1
    assert [
        message.content for message in app2.provider.requests[0].messages
    ].count(final_text) == 1
