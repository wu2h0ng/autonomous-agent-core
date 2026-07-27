"""Agent CLI V0 — Mandate-top terminal bridge into governed AgentLoop."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TextIO

from agent_os_contracts import RunStatus, SessionRef, TaskEventType

from .agent_context import (
    AgentsMarkdownContext,
    agent_context_status_payload,
    agents_markdown_system_section,
    discover_agents_markdown,
)
from .agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    CHAT_CAPABILITY_IDS,
    CHAT_GRANT_MAX_RISK_TIERS,
    ChatSession,
    ConfirmationGateway,
)
from .mandate_terminal import (
    MandateAttachSession,
    ensure_local_mandate_session,
    mandate_status,
)
from .provider import DeterministicProvider
from .terminal_session import (
    history_from_messages,
    load_terminal_session,
    save_terminal_session,
)
from .trusted_commands import apply_trusted_shell_profile

_AGENT_SYSTEM_PROMPT = (
    "You are a governed Agent OS terminal agent operating under an external "
    "Mandate. Software engineering (read, search, edit, test, allowlisted shell) "
    "is your execution organ, not your product identity. Act only through the "
    "provided typed tools; never claim an action succeeded before its tool "
    "result confirms it. Prefer workspace.search and workspace.read before "
    "editing. If a tool reports an error, adjust arguments instead of repeating "
    "the identical call."
)

_HELP_TEXT = """\
Agent OS terminal commands:
  /exit, /quit   leave the session
  /status        show Mandate + session state
  /resume        reload saved transcript and continue
  /help          show this message
"""


class AgentCLIError(RuntimeError):
    """Fail-closed Agent CLI admission error."""


@dataclass(frozen=True)
class AgentCLIResult:
    exit_code: int
    last_text: str = ""
    stop_reason: str | None = None


def _default_loop_config() -> AgentLoopConfig:
    return AgentLoopConfig(system_prompt=_AGENT_SYSTEM_PROMPT)


def _loop_config_with_agents(
    config: AgentLoopConfig, workspace: Path
) -> tuple[AgentLoopConfig, AgentsMarkdownContext | None]:
    agents_ctx = discover_agents_markdown(workspace)
    if agents_ctx is None:
        return config, None
    return (
        replace(
            config,
            system_prompt=config.system_prompt + agents_markdown_system_section(agents_ctx),
        ),
        agents_ctx,
    )


def _build_chat_loop(
    app: Any,
    session: ChatSession,
    gateway: ConfirmationGateway,
    loop_config: AgentLoopConfig | None = None,
    *,
    stream: bool = True,
    on_text_delta: Any | None = None,
) -> AgentLoop:
    grants = dict(app.grants)
    for capability_id, max_tier in CHAT_GRANT_MAX_RISK_TIERS.items():
        grant = grants.get(capability_id)
        if grant is None:
            raise AgentCLIError(f"chat capability is not granted: {capability_id}")
        if grant.max_risk_tier < max_tier:
            raise AgentCLIError(
                f"chat capability risk tier is not granted: {capability_id}"
            )
    chat_grants = {
        capability_id: grants[capability_id] for capability_id in CHAT_CAPABILITY_IDS
    }
    config = loop_config or _default_loop_config()
    if not stream:
        config = replace(config, stream=False)
    return AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        sandbox=app.sandbox,
        grants=chat_grants,
        principal=app.principal,
        gateway=gateway,
        config=config,
        on_text_delta=on_text_delta,
    )


_RESUMABLE_RUN_STATUSES = frozenset(
    {
        RunStatus.RUNNING,
        RunStatus.QUEUED,
        RunStatus.PAUSED,
        RunStatus.WAITING_EVENT,
        RunStatus.WAITING_APPROVAL,
    }
)


def _resume_chat_session(
    app: Any,
    record: Any,
    gateway: ConfirmationGateway,
    *,
    workspace: Path,
    database: Path,
    mandate: MandateAttachSession,
    loop_config: AgentLoopConfig | None = None,
    stream: bool = True,
    on_text_delta: Any | None = None,
) -> tuple[ChatSession, AgentLoop]:
    workspace = Path(workspace).resolve()
    database = Path(database).resolve()
    if record.mandate_id != mandate.mandate_id:
        raise AgentCLIError(
            "saved session mandate_id does not match the attached Mandate"
        )
    if Path(record.repo_root).resolve() != workspace:
        raise AgentCLIError(
            "saved session repo_root does not match the current workspace"
        )
    if Path(record.database).resolve() != database:
        raise AgentCLIError(
            "saved session database does not match the current --database"
        )
    if Path(mandate.database).resolve() != database:
        raise AgentCLIError(
            "attached Mandate database does not match the current --database"
        )
    aggregate = app.tasks.get_task(record.task_id)
    if aggregate.run is None or aggregate.run.run_id != record.run_id:
        raise AgentCLIError("saved run is not active; start a fresh agent session")
    if aggregate.run.status not in _RESUMABLE_RUN_STATUSES:
        raise AgentCLIError(
            f"saved run status {aggregate.run.status.value} is not resumable; "
            "start a fresh agent session"
        )
    if app.correction.halted(record.task_id, record.run_id, "provider"):
        raise AgentCLIError(
            "saved run is correction-halted; start a fresh agent session"
        )
    if aggregate.expected_outcome is None:
        raise AgentCLIError("saved task has no expected outcome")
    session = ChatSession(
        ref=SessionRef(
            session_id=record.session_id,
            task_id=record.task_id,
            run_id=record.run_id,
            tenant_id=app.principal.tenant_id,
            workspace_id=app.principal.workspace_id,
        ),
        envelope_id=record.envelope_id,
        expected=aggregate.expected_outcome,
    )
    loop = _build_chat_loop(
        app, session, gateway, loop_config, stream=stream, on_text_delta=on_text_delta
    )
    loop.restore_history(history_from_messages(record.messages))
    return session, loop


def _configure_offline_provider(app: Any) -> None:
    if isinstance(app.provider, DeterministicProvider):
        app.provider_configured = True
        return
    try:
        binding = app.provider.invocation_binding
    except RuntimeError:
        binding = None
    if binding is None:
        raise AgentCLIError("offline mode requires a provider invocation binding")
    app.provider = DeterministicProvider(
        invocation_binding=binding,
    )
    app.provider_configured = True


def _persist_session(
    *,
    workspace: Path,
    database: Path,
    mandate: MandateAttachSession,
    session: ChatSession,
    goal: str,
    loop: AgentLoop,
) -> None:
    save_terminal_session(
        workspace=workspace,
        mandate_id=mandate.mandate_id,
        task_id=session.task_id,
        run_id=session.run_id,
        session_id=session.session_id,
        envelope_id=session.envelope_id,
        goal=goal,
        repo_root=workspace,
        database=database,
        messages=loop.history,
    )


def _print_status(
    *,
    workspace: Path,
    mandate: MandateAttachSession,
    session: ChatSession,
    loop: AgentLoop,
    goal: str,
    agents_ctx: AgentsMarkdownContext | None,
    out: TextIO,
) -> None:
    status = mandate_status(workspace=workspace, session=mandate)
    payload = {
        **status,
        "agent_session": {
            "goal": goal,
            "task_id": session.task_id,
            "run_id": session.run_id,
            "session_id": session.session_id,
            "history_messages": len(loop.history),
        },
        "agent_context": agent_context_status_payload(agents_ctx),
    }
    print(json.dumps(payload, indent=2), file=out)


def _emit_turn_output(
    result: Any,
    *,
    out: TextIO,
    streamed: bool,
) -> None:
    if result.text:
        if streamed:
            print(file=out)
        else:
            print(result.text, file=out)
    if result.stop_reason != "completed":
        print(f"[stopped: {result.stop_reason}]", file=out)


def run_agent_cli(
    *,
    app: Any,
    workspace: Path,
    database: Path,
    goal: str,
    gateway: ConfirmationGateway,
    prompt: str | None = None,
    resume: bool = False,
    offline: bool = False,
    loop_config: AgentLoopConfig | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    repl_banner_template: str | None = None,
    stream: bool = True,
) -> AgentCLIResult:
    """Programmatic Agent CLI entry for tests and the apps.cli wrapper."""
    workspace = Path(workspace).resolve()
    database = Path(database).resolve()
    out = output_stream or sys.stdout
    inp = input_stream or sys.stdin
    apply_trusted_shell_profile(app.sandbox)
    base_config = loop_config or _default_loop_config()
    config, agents_ctx = _loop_config_with_agents(base_config, workspace)

    def _stream_delta(delta: str) -> None:
        print(delta, file=out, end="", flush=True)

    on_text_delta = _stream_delta if stream else None

    if offline:
        _configure_offline_provider(app)

    mandate, _created = ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        goal_statement=goal,
    )

    if resume:
        record = load_terminal_session(workspace)
        session, loop = _resume_chat_session(
            app,
            record,
            gateway,
            workspace=workspace,
            database=database,
            mandate=mandate,
            loop_config=config,
            stream=stream,
            on_text_delta=on_text_delta,
        )
        goal = record.goal
    else:
        if not app.provider_configured:
            raise AgentCLIError(
                "provider is not configured: set AGENT_OS_PROVIDER_BASE_URL and "
                "AGENT_OS_PROVIDER_MODEL or pass offline=True"
            )
        session, _ = app.open_chat_session(goal, gateway, loop_config=config)
        loop = _build_chat_loop(
            app,
            session,
            gateway,
            config,
            stream=stream,
            on_text_delta=on_text_delta,
        )

    if prompt is not None:
        try:
            result = loop.run_turn(session, prompt)
        except KeyboardInterrupt:
            app.correct_task(session.task_id, "user interrupt during prompt turn")
            print("[turn interrupted; task correction-halted]", file=out)
            return AgentCLIResult(exit_code=130, stop_reason="correction_halted")
        _persist_session(
            workspace=workspace,
            database=database,
            mandate=mandate,
            session=session,
            goal=goal,
            loop=loop,
        )
        _emit_turn_output(result, out=out, streamed=stream)
        if result.stop_reason != "completed":
            return AgentCLIResult(
                exit_code=1,
                last_text=result.text,
                stop_reason=result.stop_reason,
            )
        return AgentCLIResult(exit_code=0, last_text=result.text)

    if repl_banner_template is not None:
        banner = repl_banner_template.format(
            task_id=session.task_id,
            mandate_id=mandate.mandate_id,
            session_id=session.session_id,
        )
    else:
        banner = (
            f"agent session started under {mandate.mandate_id} "
            f"(task {session.task_id})"
        )
    print(banner, file=out)
    print("type /exit to quit, /status for Mandate + session state", file=out)

    while True:
        print("you> ", file=out, end="", flush=True)
        try:
            line = inp.readline()
            if line == "":
                print(file=out)
                break
            text = line.strip()
        except KeyboardInterrupt:
            app.correct_task(session.task_id, "user interrupt at terminal prompt")
            print("\n[session interrupted; task correction-halted]", file=out)
            break
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break
        if text == "/help":
            print(_HELP_TEXT, file=out)
            continue
        if text == "/status":
            _print_status(
                workspace=workspace,
                mandate=mandate,
                session=session,
                loop=loop,
                goal=goal,
                agents_ctx=agents_ctx,
                out=out,
            )
            continue
        if text == "/resume":
            record = load_terminal_session(workspace)
            session, loop = _resume_chat_session(
                app,
                record,
                gateway,
                workspace=workspace,
                database=database,
                mandate=mandate,
                loop_config=config,
                stream=stream,
                on_text_delta=on_text_delta,
            )
            goal = record.goal
            print(
                f"[resumed session {session.session_id}; "
                f"{len(loop.history)} history messages]",
                file=out,
            )
            continue
        try:
            result = loop.run_turn(session, text)
        except KeyboardInterrupt:
            app.correct_task(session.task_id, "user interrupt from terminal")
            print("\n[turn interrupted; task correction-halted]", file=out)
            break
        _persist_session(
            workspace=workspace,
            database=database,
            mandate=mandate,
            session=session,
            goal=goal,
            loop=loop,
        )
        _emit_turn_output(result, out=out, streamed=stream)

    return AgentCLIResult(exit_code=0)


def event_types(app: Any, task_id: str) -> list[TaskEventType]:
    return [event.event_type for event in app.tasks._event_store.read(task_id)]
