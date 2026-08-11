from __future__ import annotations

import json
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
    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

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
        app1.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )
    monkeypatch.setattr(ActionPipeline, "execute", original_execute)

    assert _event_count(app1, session.task_id, TaskEventType.APPROVAL_RECORDED) == 1
    assert _receipt_count(app1, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("edit completed", ()),))
    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

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
        app1.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )

    assert _receipt_count(app1, session.task_id) == 1
    assert _event_count(
        app1,
        session.task_id,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    ) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("continued once", ()),))
    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

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


def test_correction_between_approval_and_execution_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("correction honored", ()),),
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
    resumed = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

    assert resumed.text == "correction honored"
    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    projected = SessionProjector(app.store).project(
        session.task_id,
        session.session_id,
    )
    tool_message = next(
        message
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    )
    assert "CORRECTION_HALTED" in tool_message.content


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
    result = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

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

    retry = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )
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


def test_stale_recorded_approve_remains_rejectable_after_c7_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, pending = _pending_edit(tmp_path)
    original_execute = ActionPipeline.execute

    def crash_before_execute(*_args: object, **_kwargs: object) -> None:
        raise _ProcessCrash("approval persisted")

    monkeypatch.setattr(ActionPipeline, "execute", crash_before_execute)
    with pytest.raises(_ProcessCrash, match="approval persisted"):
        app.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )
    monkeypatch.setattr(ActionPipeline, "execute", original_execute)
    app.correction.correct(
        "capability",
        "workspace.edit",
        "operator correction after approval persistence",
    )

    with pytest.raises(InvalidTransitionError, match="C7|correction|stale"):
        app.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )

    app.provider = DeterministicProvider(
        scripted=(("safely rejected", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    rejected = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.REJECT,
        reason="reject after correction",
    )
    assert rejected.stop_reason == "completed"
    assert rejected.text == "safely rejected"
    assert _receipt_count(app, session.task_id) == 0
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


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
        app1.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )
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
        resumed = app2.decide_session_approval(
            session.session_id,
            action_digest=pending.action_digest,
            disposition=ApprovalDisposition.APPROVE,
            reason="reviewed exact edit",
        )
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
