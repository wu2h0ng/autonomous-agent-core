from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_os_contracts import (
    ApprovalDisposition,
    SurfaceSessionStatus,
    SurfaceTurnResponse,
)

from apps.api_server.app import AgentOSApplication
from apps.runtime_daemon.descriptor import load_runtime_descriptor

from .surface_client import (
    SurfaceClient,
    SurfaceClientError,
)

DEFAULT_RUNTIME_DESCRIPTOR = Path.home() / ".agent-os" / "runtime.json"


def load_surface_client(args: argparse.Namespace) -> SurfaceClient:
    path = Path(
        getattr(args, "descriptor", None) or DEFAULT_RUNTIME_DESCRIPTOR
    )
    return SurfaceClient(load_runtime_descriptor(path))


def _status_value(status: object) -> str:
    return getattr(status, "value", str(status))


def _print_pending_approval(pending: object) -> None:
    capability_id = getattr(pending, "capability_id", "unknown capability")
    preview = getattr(pending, "preview", "")
    print(f"\n[approval required] {capability_id}")
    if preview:
        print(preview)


def _handle_approval(
    client: SurfaceClient,
    session_id: str,
    pending: object,
) -> SurfaceTurnResponse | None:
    if pending is None:
        return None
    _print_pending_approval(pending)
    try:
        reply = input("Approve this action? [y/N] ")
    except EOFError:
        return None
    digest = getattr(pending, "action_digest", "")
    if reply.strip().lower() in {"y", "yes"}:
        resumed = client.decide_approval(
            session_id,
            digest,
            ApprovalDisposition.APPROVE,
            "approved from terminal",
        )
        if resumed.text:
            print(resumed.text)
        if resumed.stop_reason != "completed":
            print(f"[stopped: {resumed.stop_reason}]")
        return resumed
    denied = client.decide_approval(
        session_id,
        digest,
        ApprovalDisposition.REJECT,
        "rejected from terminal",
    )
    if denied.text:
        print(denied.text)
    return denied


def _chat(args: argparse.Namespace) -> int:
    client = load_surface_client(args)
    if args.prompt is not None:
        snapshot = client.open_session(args.prompt)
        session_id = snapshot.session.session_id
        response = client.run_turn(session_id, args.prompt)
        if response.text:
            print(response.text)
        if (
            response.snapshot.status == SurfaceSessionStatus.WAITING_APPROVAL
        ):
            resumed = _handle_approval(
                client, session_id, response.snapshot.pending_approval
            )
            if resumed is not None:
                response = resumed
        if response.stop_reason != "completed":
            print(f"[stopped: {response.stop_reason}]", file=sys.stderr)
        return 0 if response.stop_reason == "completed" else 1
    if args.session:
        snapshot = client.get_session(args.session)
    else:
        snapshot = client.open_session("interactive terminal chat session")
    session_id = snapshot.session.session_id
    print(f"chat session started (session {session_id})")
    print("type /exit to quit, /status for session state")
    while True:
        try:
            line = input("you> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            try:
                client.correct(session_id, "user interrupt at terminal prompt")
            except SurfaceClientError:
                pass
            print("\n[session interrupted; task correction-halted]")
            break
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break
        if text == "/status":
            current = client.get_session(session_id)
            print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "status": _status_value(current.status),
                        "event_sequence": current.event_sequence,
                        "message_count": current.message_count,
                    },
                    indent=2,
                )
            )
            continue
        if text == "/pause":
            paused = client.pause(session_id, "paused by user")
            print(f"[paused: {_status_value(paused.status)}]")
            continue
        if text == "/resume":
            resumed = client.resume(session_id, "resumed by user")
            print(f"[resumed: {_status_value(resumed.status)}]")
            continue
        if text == "/correct" or text.startswith("/correct "):
            reason = text[len("/correct") :].strip()
            if not reason:
                print("[usage: /correct REASON]")
                continue
            halted = client.correct(session_id, reason)
            print(f"[correction halted: {_status_value(halted.status)}]")
            continue
        response = client.run_turn(session_id, text)
        if response.text:
            print(response.text)
        if (
            response.snapshot.status == SurfaceSessionStatus.WAITING_APPROVAL
        ):
            _handle_approval(
                client, session_id, response.snapshot.pending_approval
            )
            continue
        if response.stop_reason != "completed":
            print(f"[stopped: {response.stop_reason}]")
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-os")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--descriptor",
        default=None,
        help="path to the private runtime descriptor "
        f"(default {DEFAULT_RUNTIME_DESCRIPTOR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("task-create")
    create.add_argument("statement")
    show = sub.add_parser("task-show")
    show.add_argument("task_id")
    run = sub.add_parser("task-run")
    run.add_argument("task_id")
    run.add_argument("--prompt", default="Complete the repository task.")
    chat = sub.add_parser("chat")
    chat.add_argument(
        "--prompt",
        "-p",
        default=None,
        help="run a single non-interactive prompt and exit",
    )
    chat.add_argument(
        "--session",
        default=None,
        help="resume an existing session instead of opening a new one",
    )
    session_show = sub.add_parser("session-show")
    session_show.add_argument("session_id")
    session_pause = sub.add_parser("session-pause")
    session_pause.add_argument("session_id")
    session_resume = sub.add_parser("session-resume")
    session_resume.add_argument("session_id")
    session_correct = sub.add_parser("session-correct")
    session_correct.add_argument("session_id")
    session_correct.add_argument("reason")
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
    args = parser.parse_args()
    if args.command == "chat":
        raise SystemExit(_chat(args))
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
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    if args.command == "task-create":
        task = app.create_task({
            "goal_id": f"goal:{args.statement[:24]}", "tenant_id": "tenant:local",
            "workspace_id": "workspace:local", "created_by": "user:local",
            "created_at": "2026-07-10T00:00:00Z", "statement": args.statement,
        })
        print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    elif args.command == "task-show":
        print(json.dumps(app.task_json(args.task_id), indent=2, default=str))
    elif args.command == "workflow-validate":
        from agent_os_contracts import WorkflowGraph
        workflow = WorkflowGraph.model_validate_json(args.workflow_json.read_text(encoding="utf-8"))
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
