"""Agent CLI V0 — Mandate-top terminal bridge into governed AgentLoop."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from agent_os_contracts import SessionRef, TaskEventType

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


def _build_chat_loop(
    app: Any,
    session: ChatSession,
    gateway: ConfirmationGateway,
    loop_config: AgentLoopConfig | None = None,
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
        config=loop_config or _default_loop_config(),
    )


def _resume_chat_session(
    app: Any,
    record: Any,
    gateway: ConfirmationGateway,
    loop_config: AgentLoopConfig | None = None,
) -> tuple[ChatSession, AgentLoop]:
    aggregate = app.tasks.get_task(record.task_id)
    if aggregate.run is None or aggregate.run.run_id != record.run_id:
        raise AgentCLIError("saved run is not active; start a fresh agent session")
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
    loop = _build_chat_loop(app, session, gateway, loop_config)
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
        messages=loop.history,
    )


def _print_status(
    *,
    workspace: Path,
    mandate: MandateAttachSession,
    session: ChatSession,
    loop: AgentLoop,
    goal: str,
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
    }
    print(json.dumps(payload, indent=2), file=out)


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
) -> AgentCLIResult:
    """Programmatic Agent CLI entry for tests and the apps.cli wrapper."""
    workspace = Path(workspace).resolve()
    database = Path(database)
    out = output_stream or sys.stdout
    inp = input_stream or sys.stdin
    config = loop_config or _default_loop_config()

    if offline:
        _configure_offline_provider(app)

    mandate, _created = ensure_local_mandate_session(
        workspace=workspace,
        database=database,
        goal_statement=goal,
    )

    if resume:
        record = load_terminal_session(workspace)
        session, loop = _resume_chat_session(app, record, gateway, config)
        goal = record.goal
    else:
        if not app.provider_configured:
            raise AgentCLIError(
                "provider is not configured: set AGENT_OS_PROVIDER_BASE_URL and "
                "AGENT_OS_PROVIDER_MODEL or pass offline=True"
            )
        session, loop = app.open_chat_session(goal, gateway, loop_config=config)

    if prompt is not None:
        result = loop.run_turn(session, prompt)
        _persist_session(
            workspace=workspace,
            mandate=mandate,
            session=session,
            goal=goal,
            loop=loop,
        )
        if result.text:
            print(result.text, file=out)
        if result.stop_reason != "completed":
            print(f"[stopped: {result.stop_reason}]", file=sys.stderr)
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
                out=out,
            )
            continue
        if text == "/resume":
            record = load_terminal_session(workspace)
            session, loop = _resume_chat_session(app, record, gateway, config)
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
            print("[turn interrupted; task correction-halted]", file=out)
            continue
        _persist_session(
            workspace=workspace,
            mandate=mandate,
            session=session,
            goal=goal,
            loop=loop,
        )
        if result.text:
            print(result.text, file=out)
        if result.stop_reason != "completed":
            print(f"[stopped: {result.stop_reason}]", file=out)

    return AgentCLIResult(exit_code=0)


def event_types(app: Any, task_id: str) -> list[TaskEventType]:
    return [event.event_type for event in app.tasks._event_store.read(task_id)]
