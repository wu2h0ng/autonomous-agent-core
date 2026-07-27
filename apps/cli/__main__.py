from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_os_contracts import ActionContract
from agent_os_core import NonInteractiveDenyGateway
from agent_os_core.agent_cli import run_agent_cli
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    bootstrap_mandate,
    load_mandate_json,
    load_relevance_context_json,
    mandate_status,
)
from apps.api_server.app import AgentOSApplication


class TerminalConfirmationGateway:
    """Human-in-the-loop approval bridge for interactive chat sessions."""

    def confirm(self, action: ActionContract, preview: str) -> bool:
        print(f"\n[approval required] {action.capability_id}")
        print(preview)
        try:
            reply = input("Approve this action? [y/N] ")
        except EOFError:
            return False
        return reply.strip().lower() in {"y", "yes"}


_KNOWN_SUBCOMMANDS = frozenset(
    {
        "agent",
        "chat",
        "task-create",
        "task-show",
        "task-run",
        "workflow-validate",
        "task-commit",
        "task-signal",
        "task-replan",
        "correction-resume",
        "task-compensate",
        "task-recovery",
        "mandate-bootstrap",
        "mandate-attach",
        "mandate-status",
    }
)


def _normalize_argv(argv: list[str]) -> list[str]:
    if len(argv) > 1 and not argv[1].startswith("-") and argv[1] not in _KNOWN_SUBCOMMANDS:
        return [argv[0], "agent", *argv[1:]]
    return argv


def _run_agent_command(
    args: argparse.Namespace,
    *,
    default_goal: str,
    repl_banner_template: str | None,
) -> int:
    goal = args.prompt or default_goal
    gateway = (
        NonInteractiveDenyGateway()
        if args.prompt is not None
        else TerminalConfirmationGateway()
    )
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    result = run_agent_cli(
        app=app,
        workspace=Path(args.workspace),
        database=Path(args.database),
        goal=goal,
        gateway=gateway,
        prompt=args.prompt,
        resume=args.resume,
        offline=args.offline,
        repl_banner_template=repl_banner_template,
    )
    return result.exit_code


def _agent(args: argparse.Namespace) -> int:
    return _run_agent_command(
        args,
        default_goal="interactive agent session",
        repl_banner_template=None,
    )


def _chat(args: argparse.Namespace) -> int:
    return _run_agent_command(
        args,
        default_goal="interactive terminal chat session",
        repl_banner_template=(
            None if args.prompt is not None else "chat session started (task {task_id})"
        ),
    )


def _mandate_bootstrap(args: argparse.Namespace) -> int:
    mandate = load_mandate_json(args.mandate_json)
    relevance = (
        load_relevance_context_json(args.relevance_context_json)
        if args.relevance_context_json is not None
        else None
    )
    payload = bootstrap_mandate(
        database=Path(args.database),
        mandate=mandate,
        relevance_context=relevance,
        workspace=Path(args.workspace) if relevance is not None else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


def _mandate_attach(args: argparse.Namespace) -> int:
    session = attach_mandate(
        workspace=Path(args.workspace),
        database=Path(args.database),
        mandate_id=args.mandate_id,
        environment_binding_id=args.environment_binding_id,
        principal_id=args.principal_id,
        tenant_id=args.tenant_id,
        workspace_id=args.workspace_id,
    )
    print(json.dumps(session.to_dict(), indent=2))
    return 0


def _mandate_status(args: argparse.Namespace) -> int:
    payload = mandate_status(workspace=Path(args.workspace))
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = _normalize_argv(list(sys.argv if argv is None else argv))
    parser = argparse.ArgumentParser(prog="agent-os")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    agent = sub.add_parser("agent", help="Mandate-top governed agent REPL")
    agent.add_argument("prompt", nargs="?", default=None)
    agent.add_argument("--prompt", "-p", dest="prompt_flag", default=None)
    agent.add_argument("--resume", action="store_true")
    agent.add_argument("--offline", action="store_true")
    agent.set_defaults(_uses_prompt_flag=True)

    chat = sub.add_parser("chat", help="deprecated alias for agent")
    chat.add_argument("prompt", nargs="?", default=None)
    chat.add_argument("--prompt", "-p", dest="prompt_flag", default=None)
    chat.add_argument("--resume", action="store_true")
    chat.add_argument("--offline", action="store_true")
    chat.set_defaults(_uses_prompt_flag=True)

    mandate_bootstrap = sub.add_parser("mandate-bootstrap")
    mandate_bootstrap.add_argument("mandate_json", type=Path)
    mandate_bootstrap.add_argument("--relevance-context-json", type=Path, default=None)

    mandate_attach = sub.add_parser("mandate-attach")
    mandate_attach.add_argument("--mandate-id", required=True)
    mandate_attach.add_argument("--environment-binding-id", required=True)
    mandate_attach.add_argument("--principal-id", required=True)
    mandate_attach.add_argument("--tenant-id", required=True)
    mandate_attach.add_argument("--workspace-id", required=True)

    sub.add_parser("mandate-status")

    create = sub.add_parser("task-create")
    create.add_argument("statement")
    show = sub.add_parser("task-show")
    show.add_argument("task_id")
    run = sub.add_parser("task-run")
    run.add_argument("task_id")
    run.add_argument("--prompt", default="Complete the repository task.")
    validate = sub.add_parser("workflow-validate")
    validate.add_argument("workflow_json", type=Path)
    commit = sub.add_parser("task-commit")
    commit.add_argument("task_id")
    commit.add_argument("commitment_json", type=Path)
    signal = sub.add_parser("task-signal")
    signal.add_argument("task_id")
    signal.add_argument("signal_json", type=Path)
    replan = sub.add_parser("task-replan")
    replan.add_argument("task_id")
    replan.add_argument("workflow_json", type=Path)
    replan.add_argument("--reason", required=True)
    correction_resume = sub.add_parser("correction-resume")
    correction_resume.add_argument("task_id")
    correction_resume.add_argument("--reason", required=True)
    compensate = sub.add_parser("task-compensate")
    compensate.add_argument("task_id")
    recovery = sub.add_parser("task-recovery")
    recovery.add_argument("task_id")

    args = parser.parse_args(argv[1:])

    if getattr(args, "_uses_prompt_flag", False) and args.prompt_flag is not None:
        args.prompt = args.prompt_flag

    try:
        if args.command == "agent":
            raise SystemExit(_agent(args))
        if args.command == "chat":
            raise SystemExit(_chat(args))
        if args.command == "mandate-bootstrap":
            raise SystemExit(_mandate_bootstrap(args))
        if args.command == "mandate-attach":
            raise SystemExit(_mandate_attach(args))
        if args.command == "mandate-status":
            raise SystemExit(_mandate_status(args))
    except MandateTerminalError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    if args.command == "task-create":
        task = app.create_task(
            {
                "goal_id": f"goal:{args.statement[:24]}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "user:local",
                "created_at": "2026-07-10T00:00:00Z",
                "statement": args.statement,
            }
        )
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-show":
        print(json.dumps(app.task_json(args.task_id), indent=2, default=str))
    elif args.command == "workflow-validate":
        from agent_os_contracts import WorkflowGraph

        workflow = WorkflowGraph.model_validate_json(
            args.workflow_json.read_text(encoding="utf-8")
        )
        print(json.dumps({"valid": True, "digest": workflow.canonical_digest()}, indent=2))
    elif args.command == "task-commit":
        payload = json.loads(args.commitment_json.read_text(encoding="utf-8"))
        task = app.commit_task(args.task_id, payload)
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-signal":
        payload = json.loads(args.signal_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("signal JSON must be an object")
        task = app.signal_task(args.task_id, payload)
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-replan":
        workflow = json.loads(args.workflow_json.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            raise ValueError("workflow JSON must be an object")
        task = app.replan_task(
            args.task_id,
            {"workflow": workflow, "reason": args.reason},
        )
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "correction-resume":
        task = app.resume_correction(args.task_id, args.reason)
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-compensate":
        task = app.compensate_task(args.task_id)
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-recovery":
        print(json.dumps(app.recovery_json(args.task_id), indent=2, default=str))
    elif args.command == "task-run":
        task = app.run_task(args.task_id, {"prompt": args.prompt})
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))


if __name__ == "__main__":
    main()
