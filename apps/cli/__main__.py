from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.api_server.app import AgentOSApplication


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
