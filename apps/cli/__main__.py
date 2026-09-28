from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Keep the source checkout directly runnable without requiring a shell-specific
# PYTHONPATH. Packaging can later replace this with installed distributions.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _source_path in (
    _REPO_ROOT / "packages" / "contracts" / "src",
    _REPO_ROOT / "packages" / "os_core" / "src",
):
    if str(_source_path) not in sys.path:
        sys.path.insert(0, str(_source_path))

from agent_os_contracts import (  # noqa: E402
    ActionContract,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    WorkflowGraph,
)
from agent_os_core import (  # noqa: E402
    NonInteractiveDenyGateway,
    TASK_CONFIGURATION_CAPABILITY,
)
from agent_os_core.operator_metrics import OperatorEventLog  # noqa: E402
from apps.api_server.app import AgentOSApplication  # noqa: E402
from scripts.live_provider_outcome_smoke import (  # noqa: E402
    run_smoke as run_live_provider_outcome_smoke,
)


def _operator_log(args: argparse.Namespace) -> OperatorEventLog:
    """HCW-METRICS-0: operator event log lives beside the database file."""
    return OperatorEventLog(Path(str(args.database) + ".operator-events.jsonl"))


class TerminalConfirmationGateway:
    """Human-in-the-loop approval bridge for interactive chat sessions."""

    def __init__(self, operator_log: OperatorEventLog | None = None) -> None:
        self._operator_log = operator_log

    def confirm(self, action: ActionContract, preview: str) -> bool:
        print(f"\n[approval required] {action.capability_id}")
        print(preview)
        try:
            reply = input("Approve this action? [y/N] ")
        except EOFError:
            reply = ""
        approved = reply.strip().lower() in {"y", "yes"}
        if self._operator_log is not None:
            self._operator_log.append(
                "approval_action",
                verdict="approve" if approved else "reject",
                n=len(preview.splitlines()),
            )
        return approved


def _chat(args: argparse.Namespace) -> int:
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    olog = _operator_log(args)
    if not app.provider_configured:
        print(
            "provider is not configured: set AGENT_OS_PROVIDER_BASE_URL, "
            "AGENT_OS_PROVIDER_MODEL and the API key env "
            "(AGENT_OS_PROVIDER_API_KEY_ENV, default OPENAI_API_KEY)",
            file=sys.stderr,
        )
        return 2
    if args.prompt is not None:
        session, loop = app.open_chat_session(
            args.prompt, NonInteractiveDenyGateway()
        )
        olog.append("prompt_sent", task_id=session.task_id, chars=len(args.prompt))
        try:
            result = loop.run_turn(session, args.prompt)
        except KeyboardInterrupt:
            olog.append("intervention", task_id=session.task_id)
            app.correct_task(
                session.task_id,
                "user interrupt from terminal",
            )
            print("[run interrupted; task correction-halted]", file=sys.stderr)
            return 130
        print(result.text)
        if result.stop_reason != "completed":
            print(f"[stopped: {result.stop_reason}]", file=sys.stderr)
            return 1
        return 0
    session, loop = app.open_chat_session(
        "interactive terminal chat session", TerminalConfirmationGateway(olog)
    )
    print(f"chat session started (task {session.task_id})")
    print("type /exit to quit, /status for session state")
    while True:
        try:
            line = input("you> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            olog.append("intervention", task_id=session.task_id)
            app.correct_task(
                session.task_id,
                "user interrupt at terminal prompt",
            )
            print("\n[session interrupted; task correction-halted]")
            break
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break
        if text == "/status":
            print(
                json.dumps(
                    {
                        "task_id": session.task_id,
                        "run_id": session.run_id,
                        "history_messages": len(loop.history),
                    },
                    indent=2,
                )
            )
            continue
        olog.append("prompt_sent", task_id=session.task_id, chars=len(text))
        try:
            result = loop.run_turn(session, text)
        except KeyboardInterrupt:
            olog.append("intervention", task_id=session.task_id)
            app.correct_task(
                session.task_id,
                "user interrupt from terminal",
            )
            print("[turn interrupted; task correction-halted]")
            continue
        if result.text:
            print(result.text)
        if result.stop_reason != "completed":
            print(f"[stopped: {result.stop_reason}]")
    return 0


def _print_status(app: AgentOSApplication) -> int:
    """Print the small, scan-friendly status surface used by daily CLI work."""
    workspace = app.workspace_status()
    provider = app.provider_status()
    tasks = app.list_tasks()
    print(f"Workspace  {'ready' if workspace['attached'] else 'missing'}  {workspace['root']}")
    print(f"Provider   {'ready' if provider['configured'] else 'not configured'}  {provider['model_id'] or '-'}")
    if not tasks:
        print("Tasks      none")
        return 0
    print("Tasks")
    for task in tasks[:8]:
        status = task.get("run_status") or task.get("status") or "unknown"
        statement = str(task.get("statement") or "").replace("\n", " ")
        print(f"  {task['task_id']}  {status:<12}  {statement[:72]}")
    if len(tasks) > 8:
        print(f"  ... {len(tasks) - 8} more")
    return 0


def _ask(args: argparse.Namespace) -> int:
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    session, loop = app.open_chat_session(
        "daily ask session", NonInteractiveDenyGateway()
    )
    _operator_log(args).append(
        "prompt_sent", task_id=session.task_id, chars=len(args.question)
    )
    result = loop.run_turn(session, args.question)
    if result.text:
        print(result.text)
    if result.stop_reason != "completed":
        print(f"stopped: {result.stop_reason}", file=sys.stderr)
        return 1
    return 0


def _daily_workflow(now: datetime) -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    return WorkflowGraph(
        schema_version="WorkflowGraph/dag_v1",
        workflow_id="workflow:daily-cli-work",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=(
            EdgeSpec(source="read", target="provider"),
            EdgeSpec(source="provider", target="approve"),
            EdgeSpec(source="approve", target="apply"),
            EdgeSpec(source="apply", target="tests"),
            EdgeSpec(source="tests", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        ),
    )


def _daily_commitment_payload(
    *,
    task_id: str,
    statement: str,
    now: datetime,
) -> dict[str, object]:
    return {
        "commitment": {
            "commitment_id": f"commitment:daily:{task_id}",
            "task_id": task_id,
            "goal_id": f"goal:{statement[:24]}",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "accepted_by": "user:local",
            "accepted_at": now,
            "deliverables": ["provider proposed repository patch"],
            "acceptance_criteria": ["configured verifier passes"],
            "authority_scopes": [
                "workspace:read",
                "workspace:write",
                TASK_CONFIGURATION_CAPABILITY,
            ],
            "budget": {
                "max_cost_usd": "5",
                "max_duration_seconds": 1800,
                "max_provider_tokens": 20000,
                "max_tool_calls": 40,
            },
            "risk_tier": 1,
            "exit_conditions": ["outcome verified or failed"],
            "expires_at": now + timedelta(hours=1),
        },
        "workflow": _daily_workflow(now).model_dump(mode="json"),
        "expected_outcome": {
            "expected_outcome_id": f"expected:daily:{task_id}",
            "task_id": task_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "evaluator_type": "pytest",
            "evaluator_version": "1",
            "evidence_requirements": ["test-report"],
            "failure_semantics": ["non-zero exit"],
            "threshold": 1,
            "observation_window_seconds": 1800,
            "frozen_at": now,
        },
    }


def _daily_inputs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "target_path": args.target_path,
        "test_command": args.test_command,
        "recover_stale_lease": True,
    }


def _task_summary(state: dict[str, object]) -> dict[str, object]:
    run = state.get("run")
    snapshot = state.get("configuration_snapshot")
    outcome = state.get("observed_outcome")
    return {
        "task_id": state.get("task_id"),
        "task_status": state.get("status"),
        "run_id": run.get("run_id") if isinstance(run, dict) else None,
        "run_status": run.get("status") if isinstance(run, dict) else None,
        "snapshot_id": snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None,
        "outcome_status": outcome.get("status") if isinstance(outcome, dict) else None,
        "outcome_evidence_valid": state.get("outcome_evidence_valid"),
        "proposed_action": state.get("proposed_action"),
    }


def _work(args: argparse.Namespace) -> int:
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    now = datetime.now(timezone.utc)
    task = app.create_task(
        {
            "goal_id": f"goal:{args.statement[:24]}",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": args.statement,
        }
    )
    if not args.run:
        print(json.dumps(_task_summary(app.task_json(task.task_id)), indent=2, default=str))
        return 0
    if not args.target_path:
        raise ValueError("--target-path is required with work --run")
    app.commit_task(
        task.task_id,
        _daily_commitment_payload(
            task_id=task.task_id,
            statement=args.statement,
            now=now,
        ),
    )
    snapshot = app.seal_task_configuration(task.task_id, {})
    app.run_task(
        task.task_id,
        _daily_inputs(args),
        recover_stale_lease=True,
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    print(json.dumps(_task_summary(app.task_json(task.task_id)), indent=2, default=str))
    return 0


def _approve(args: argparse.Namespace) -> int:
    if not args.target_path:
        raise ValueError("--target-path is required to resume an approved work task")
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    before = app.task_json(args.task_id)
    snapshot = before.get("configuration_snapshot")
    if not isinstance(snapshot, dict) or not snapshot.get("snapshot_id"):
        raise ValueError("task has no sealed configuration snapshot")
    app.record_approval(
        args.task_id,
        {"disposition": "APPROVE", "reason": args.reason},
    )
    app.run_task(
        args.task_id,
        _daily_inputs(args),
        recover_stale_lease=True,
        configuration_snapshot_id=str(snapshot["snapshot_id"]),
    )
    print(json.dumps(_task_summary(app.task_json(args.task_id)), indent=2, default=str))
    return 0


def _resume(args: argparse.Namespace) -> int:
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    task = app.resume_task(args.task_id)
    print(json.dumps(app.task_json(task.task_id), indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-os")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
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
    sub.add_parser("status", help="show workspace, provider and recent tasks")
    ask = sub.add_parser("ask", help="ask a read-only question in a fresh session")
    ask.add_argument("question")
    work = sub.add_parser("work", help="create a durable task")
    work.add_argument("statement")
    work.add_argument("--run", action="store_true", help="start the governed run")
    work.add_argument("--target-path", default="")
    work.add_argument("--test-command", default="python -m pytest")
    approve = sub.add_parser("approve", help="approve and resume a daily work task")
    approve.add_argument("task_id")
    approve.add_argument("--reason", required=True)
    approve.add_argument("--target-path", required=True)
    approve.add_argument("--test-command", default="python -m pytest")
    resume = sub.add_parser("resume", help="resume a durable task")
    resume.add_argument("task_id")
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
    live_smoke = sub.add_parser(
        "live-provider-outcome-smoke",
        help="run the opt-in live provider Outcome smoke",
    )
    live_smoke.add_argument("--workspace", type=Path, default=None)
    live_smoke.add_argument("--model-id", default=None)
    args = parser.parse_args()
    if args.command == "chat":
        raise SystemExit(_chat(args))
    if args.command == "live-provider-outcome-smoke":
        summary = run_live_provider_outcome_smoke(
            workspace_root=args.workspace,
            model_id=args.model_id,
        )
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        raise SystemExit(0 if summary.get("outcome_status") == "VERIFIED" else 1)
    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    if args.command == "status":
        raise SystemExit(_print_status(app))
    if args.command == "ask":
        raise SystemExit(_ask(args))
    if args.command == "work":
        raise SystemExit(_work(args))
    if args.command == "approve":
        raise SystemExit(_approve(args))
    if args.command == "resume":
        raise SystemExit(_resume(args))
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
