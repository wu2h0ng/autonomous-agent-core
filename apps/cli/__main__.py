from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    PrincipalIdentity,
    PrincipalRole,
    SelfDevelopmentAdmissionCommand,
    SrlHelpResponseKind,
)
from agent_os_core import DeterministicProvider
from agent_os_core.mandate_terminal import MandateTerminalError, load_attach_session
from agent_os_core.responsibility_surface import (
    ResponsibilitySurfaceError,
    answer_responsibility_help,
    correct_responsibility_work,
    responsibility_status_payload,
    resolve_agent_work_authority,
    run_responsibility_work,
)
from agent_os_core.selfdev_admission import admit_self_development
from apps.api_server.app import AgentOSApplication


class ProductHelpFormatter(argparse.HelpFormatter):
    """Keep internal parser aliases out of the default product navigation."""

    def add_arguments(self, actions) -> None:
        super().add_arguments(
            [action for action in actions if action.help != argparse.SUPPRESS]
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
        help="unused; retained for CLI compatibility",
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{command}",
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

    args = parser.parse_args(argv[1:])

    try:
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
    except (MandateTerminalError, ResponsibilitySurfaceError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

if __name__ == "__main__":
    main()
