from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    PrincipalIdentity,
    PrincipalRole,
    SelfDevelopmentAdmissionCommand,
    SrlHelpResponseKind,
)
from agent_os_core import DeterministicProvider
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    bootstrap_mandate,
    load_attach_session,
    load_mandate_json,
    load_relevance_context_json,
    mandate_status,
)
from agent_os_core.responsibility_surface import (
    ResponsibilitySurfaceError,
    answer_responsibility_help,
    correct_responsibility_work,
    responsibility_status_payload,
    resolve_agent_work_authority,
    run_responsibility_work,
)
from agent_os_core.selfdev_admission import admit_self_development
from apps.runtime_daemon import (
    DEFAULT_RUNTIME_DESCRIPTOR,
    RuntimeAlreadyRunning,
    daemon_status,
    daemon_stop,
)
from apps.runtime_daemon.descriptor import (
    RuntimeDescriptor,
    RuntimeDescriptorError,
    load_runtime_descriptor,
)
from apps.api_server.app import AgentOSApplication

from .surface_client import SurfaceClient


class ProductHelpFormatter(argparse.HelpFormatter):
    """Keep internal parser aliases out of the default product navigation."""

    def add_arguments(self, actions) -> None:
        super().add_arguments(
            [action for action in actions if action.help != argparse.SUPPRESS]
        )


_KNOWN_SUBCOMMANDS = frozenset(
    {
        "agent-run",
        "agent-status",
        "agent-answer",
        "agent-correct",
        "agent-resume",
        "agent-admit-selfdev",
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
        "session-show",
        "session-pause",
        "session-resume",
        "session-correct",
        "daemon-start",
        "daemon-status",
        "daemon-stop",
    }
)

_AGENT_WORK_COMMANDS = frozenset(
    {"run", "status", "answer", "correct", "resume", "admit-selfdev"}
)


def _normalize_argv(argv: list[str]) -> list[str]:
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"--database", "--workspace"}:
            index += 2
            continue
        if token.startswith("--database=") or token.startswith("--workspace="):
            index += 1
            continue
        break
    if (
        index < len(argv)
        and argv[index] == "agent"
        and index + 1 < len(argv)
        and argv[index + 1] in _AGENT_WORK_COMMANDS
    ):
        return [
            *argv[:index],
            f"agent-{argv[index + 1]}",
            *argv[index + 2 :],
        ]
    if index < len(argv) and argv[index] in _AGENT_WORK_COMMANDS:
        return [
            *argv[:index],
            f"agent-{argv[index]}",
            *argv[index + 1 :],
        ]
    return argv


def _status_value(status: object) -> str:
    return getattr(status, "value", str(status))


def load_surface_client(args: argparse.Namespace) -> SurfaceClient:
    path = Path(
        getattr(args, "descriptor", None) or DEFAULT_RUNTIME_DESCRIPTOR
    )
    return SurfaceClient(load_runtime_descriptor(path))


# DEPRECATED (Stage 2a): canonical headless entry is `agentos -p` (cli-ts).
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


def _work_applications(
    args: argparse.Namespace,
) -> tuple[AgentOSApplication, AgentOSApplication]:
    session = load_attach_session(Path(args.workspace))
    principal_values = {
        "principal_id": session.principal_id,
        "tenant_id": session.tenant_id,
        "workspace_id": session.workspace_id,
        "authenticated_at": datetime.now(timezone.utc),
    }
    execution_principal = PrincipalIdentity(
        **principal_values,
        role=PrincipalRole.PRINCIPAL,
    )
    authority_principal = resolve_agent_work_authority(
        database=Path(args.database),
        session=session,
        bearer=os.environ.get("AGENT_OS_AUTHORITY_BEARER", "").strip(),
    )
    execution_app = AgentOSApplication(
        database=args.database,
        workspace=Path(args.workspace),
        principal=execution_principal,
    )
    authority_app = AgentOSApplication(
        database=args.database,
        workspace=Path(args.workspace),
        principal=authority_principal,
    )
    if getattr(args, "offline", False):
        with execution_app._selfdev_configuration_write():
            if not isinstance(execution_app.provider, DeterministicProvider):
                execution_app.provider = DeterministicProvider(
                    invocation_binding=execution_app.provider.invocation_binding,
                )
            execution_app.provider_configured = True
    return authority_app, execution_app


def _load_inputs(path: Path | None) -> dict:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResponsibilitySurfaceError("responsibility inputs must be a JSON object")
    return payload


def _agent_work_run(args: argparse.Namespace, *, resume: bool) -> int:
    app, execution_app = _work_applications(args)
    try:
        payload = run_responsibility_work(
            app=app,
            execution_app=execution_app,
            workspace=Path(args.workspace),
            database=Path(args.database),
            inputs=_load_inputs(args.inputs_json),
            resume=resume,
            max_cycles=args.max_cycles,
        )
    except KeyboardInterrupt:
        payload = correct_responsibility_work(
            app=app,
            execution_app=execution_app,
            workspace=Path(args.workspace),
            database=Path(args.database),
            reason="operator interrupted Agent Work",
        )
        print(json.dumps(payload, indent=2, default=str))
        return 130
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _agent_work_status(args: argparse.Namespace) -> int:
    app, execution_app = _work_applications(args)
    payload = responsibility_status_payload(
        app=app,
        execution_app=execution_app,
        workspace=Path(args.workspace),
        database=Path(args.database),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _agent_work_answer(args: argparse.Namespace) -> int:
    app, execution_app = _work_applications(args)
    payload = answer_responsibility_help(
        app=app,
        execution_app=execution_app,
        workspace=Path(args.workspace),
        database=Path(args.database),
        help_request_id=args.help_request_id,
        payload={
            "response_kind": SrlHelpResponseKind.OPERATOR_DECISION.value,
            "decision": args.decision,
            "notes": args.notes,
        },
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _agent_work_correct(args: argparse.Namespace) -> int:
    app, execution_app = _work_applications(args)
    payload = correct_responsibility_work(
        app=app,
        execution_app=execution_app,
        workspace=Path(args.workspace),
        database=Path(args.database),
        reason=args.reason,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _agent_work_admit_selfdev(args: argparse.Namespace) -> int:
    raw = args.admission_json.read_bytes()
    try:
        command = SelfDevelopmentAdmissionCommand.model_validate_json(raw)
    except ValueError as exc:
        raise ResponsibilitySurfaceError(
            f"invalid SELFDEV admission JSON: {exc}"
        ) from exc
    app, execution_app = _work_applications(args)
    receipt = admit_self_development(
        app=app,
        execution_app=execution_app,
        workspace=Path(args.workspace),
        database=Path(args.database),
        command=command,
        source_digest=hashlib.sha256(raw).hexdigest(),
    )
    print(receipt.model_dump_json(indent=2))
    return 0


def _wait_for_daemon_health(
    descriptor_path: Path,
    expected_pid: int,
    *,
    timeout: float = 10.0,
) -> RuntimeDescriptor:
    """Wait until the daemon descriptor exists and its health is authenticated."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            descriptor = load_runtime_descriptor(descriptor_path)
        except RuntimeDescriptorError:
            time.sleep(0.05)
            continue
        if descriptor.pid != expected_pid:
            time.sleep(0.05)
            continue
        try:
            request = urllib.request.Request(
                descriptor.base_url + "/v1/health",
                headers={
                    "Authorization": f"Bearer {descriptor.bearer_token}"
                },
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return descriptor
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.05)
    raise RuntimeDescriptorError(
        f"runtime daemon did not become healthy within {timeout:.0f}s"
    )


def _daemon_start(args: argparse.Namespace) -> int:
    descriptor_path = Path(
        getattr(args, "descriptor", None) or DEFAULT_RUNTIME_DESCRIPTOR
    )
    database = Path(args.database)
    workspace = Path(args.workspace)
    if descriptor_path.exists():
        try:
            existing = load_runtime_descriptor(descriptor_path)
        except RuntimeDescriptorError:
            existing = None
        if existing is not None:
            try:
                os.kill(existing.pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
            if alive:
                raise RuntimeAlreadyRunning(
                    f"runtime {existing.boot_id} is already running "
                    f"(pid {existing.pid})"
                )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.runtime_daemon",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
            "--descriptor",
            str(descriptor_path),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        start_new_session=True,
        env=dict(os.environ),
    )
    try:
        descriptor = _wait_for_daemon_health(
            descriptor_path, process.pid, timeout=10.0
        )
    except Exception:
        process.terminate()
        raise
    print(
        json.dumps(
            {
                "status": "running",
                "pid": descriptor.pid,
                "boot_id": descriptor.boot_id,
                "port": descriptor.port,
                "descriptor": str(descriptor_path),
            },
            indent=2,
        )
    )
    return 0


def _daemon_status(args: argparse.Namespace) -> int:
    descriptor_path = Path(
        getattr(args, "descriptor", None) or DEFAULT_RUNTIME_DESCRIPTOR
    )
    print(json.dumps(daemon_status(descriptor_path), indent=2))
    return 0


def _daemon_stop(args: argparse.Namespace) -> int:
    descriptor_path = Path(
        getattr(args, "descriptor", None) or DEFAULT_RUNTIME_DESCRIPTOR
    )
    result = daemon_stop(
        descriptor_path,
        expected_database=Path(args.database),
        expected_workspace=Path(args.workspace),
    )
    print(json.dumps(result, indent=2))
    return 0


def _session_command(
    client: SurfaceClient,
    command: str,
    session_id: str,
    reason: str | None,
) -> None:
    if command == "session-show":
        snapshot = client.get_session(session_id)
        print(
            json.dumps(
                {
                    "session_id": session_id,
                    "status": _status_value(snapshot.status),
                    "event_sequence": snapshot.event_sequence,
                    "message_count": snapshot.message_count,
                },
                indent=2,
            )
        )
        return
    if command == "session-pause":
        snapshot = client.pause(session_id, "paused by user")
    elif command == "session-resume":
        snapshot = client.resume(session_id, "resumed by user")
    else:
        snapshot = client.correct(session_id, reason or "operator correction")
    print(
        json.dumps(
            {
                "session_id": session_id,
                "status": _status_value(snapshot.status),
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> None:
    argv = _normalize_argv(list(sys.argv if argv is None else argv))
    parser = argparse.ArgumentParser(
        prog="agent-os",
        formatter_class=ProductHelpFormatter,
    )
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--descriptor",
        default=None,
        help="path to the private runtime descriptor (chat/session/daemon modes)",
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{command}",
    )

    session_show = sub.add_parser("session-show", help=argparse.SUPPRESS)
    session_show.add_argument("session_id")
    session_pause = sub.add_parser("session-pause", help=argparse.SUPPRESS)
    session_pause.add_argument("session_id")
    session_resume = sub.add_parser("session-resume", help=argparse.SUPPRESS)
    session_resume.add_argument("session_id")
    session_correct = sub.add_parser("session-correct", help=argparse.SUPPRESS)
    session_correct.add_argument("session_id")
    session_correct.add_argument("reason")

    daemon_start = sub.add_parser("daemon-start", help=argparse.SUPPRESS)
    daemon_start.add_argument(
        "--descriptor",
        default=None,
        help="path to the private runtime descriptor",
    )
    daemon_status = sub.add_parser("daemon-status", help=argparse.SUPPRESS)
    daemon_status.add_argument(
        "--descriptor",
        default=None,
        help="path to the private runtime descriptor",
    )
    daemon_stop = sub.add_parser("daemon-stop", help=argparse.SUPPRESS)
    daemon_stop.add_argument(
        "--descriptor",
        default=None,
        help="path to the private runtime descriptor",
    )

    for command, description in (
        ("agent-run", "run supervised Agent Work to completion (--max-cycles)"),
        ("agent-resume", "resume suspended Agent Work"),
    ):
        work = sub.add_parser(command, help=description)
        work.add_argument("--inputs-json", type=Path, default=None)
        work.add_argument("--max-cycles", type=int, default=16)
        work.add_argument("--offline", action="store_true")

    sub.add_parser("agent-status", help="show Agent Work status")
    answer = sub.add_parser("agent-answer", help="answer an Agent Work help request")
    answer.add_argument("help_request_id")
    answer.add_argument(
        "--decision",
        choices=("APPROVE", "REJECT", "MORE_INFO"),
        required=True,
    )
    answer.add_argument("--notes", default=None)
    correct = sub.add_parser(
        "agent-correct", help="operator correction for Agent Work"
    )
    correct.add_argument("reason")
    admit_selfdev = sub.add_parser(
        "agent-admit-selfdev", help="admit one bounded SELFDEV responsibility"
    )
    admit_selfdev.add_argument("admission_json", type=Path)

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

    _visible_work_commands = {
        "agent-run",
        "agent-resume",
        "agent-status",
        "agent-answer",
        "agent-correct",
        "agent-admit-selfdev",
    }
    sub._choices_actions = [  # type: ignore[attr-defined]
        action
        for action in sub._choices_actions  # type: ignore[attr-defined]
        if action.dest in _visible_work_commands
    ]
    args = parser.parse_args(argv[1:])

    try:
        if args.command == "daemon-start":
            raise SystemExit(_daemon_start(args))
        if args.command == "daemon-status":
            raise SystemExit(_daemon_status(args))
        if args.command == "daemon-stop":
            raise SystemExit(_daemon_stop(args))
        if args.command in {
            "session-show",
            "session-pause",
            "session-resume",
            "session-correct",
        }:
            client = load_surface_client(args)
            _session_command(
                client,
                args.command,
                args.session_id,
                getattr(args, "reason", None),
            )
            return
        if args.command == "agent-run":
            raise SystemExit(_agent_work_run(args, resume=False))
        if args.command == "agent-resume":
            raise SystemExit(_agent_work_run(args, resume=True))
        if args.command == "agent-status":
            raise SystemExit(_agent_work_status(args))
        if args.command == "agent-answer":
            raise SystemExit(_agent_work_answer(args))
        if args.command == "agent-correct":
            raise SystemExit(_agent_work_correct(args))
        if args.command == "agent-admit-selfdev":
            raise SystemExit(_agent_work_admit_selfdev(args))
        if args.command == "mandate-bootstrap":
            raise SystemExit(_mandate_bootstrap(args))
        if args.command == "mandate-attach":
            raise SystemExit(_mandate_attach(args))
        if args.command == "mandate-status":
            raise SystemExit(_mandate_status(args))
    except (MandateTerminalError, ResponsibilitySurfaceError) as exc:
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
