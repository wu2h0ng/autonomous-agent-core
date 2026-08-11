from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_os_contracts import (
    PrincipalIdentity,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolProposal,
    TaskEventType,
    TurnId,
)
from agent_os_core import (
    AgentLoopConfig,
    AutoApproveGateway,
    ChatSession,
    DeterministicProvider,
    SessionProjector,
    TaskConfigurationDrift,
)

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
