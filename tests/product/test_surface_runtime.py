from __future__ import annotations

from pathlib import Path

import pytest
from agent_os_contracts import PrincipalIdentity, ProviderMessage, ProviderMessageRole
from agent_os_core import (
    AgentLoopConfig,
    AutoApproveGateway,
    DeterministicProvider,
    SessionProjector,
    TaskConfigurationDrift,
)

from apps.api_server.app import AgentOSApplication


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
