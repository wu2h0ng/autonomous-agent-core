from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from apps.api_server.app import AgentOSApplication
from agent_os_core import (
    SelfDevelopmentTaskSpec,
    prepare_self_development_task_package,
    validate_self_development_task,
)


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
    selfdev_validate = sub.add_parser("selfdev-validate")
    selfdev_validate.add_argument("spec_json", type=Path)
    selfdev_prepare = sub.add_parser("selfdev-prepare")
    selfdev_prepare.add_argument("spec_json", type=Path)
    selfdev_prepare.add_argument("--task-id", required=True)
    selfdev_prepare.add_argument("--created-at")
    args = parser.parse_args()
    if args.command == "selfdev-validate":
        receipt = validate_self_development_task(_selfdev_spec_from_file(args.spec_json))
        print(json.dumps(asdict(receipt), indent=2, default=str))
        return
    if args.command == "selfdev-prepare":
        created_at = (
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
            if args.created_at
            else None
        )
        package = prepare_self_development_task_package(
            _selfdev_spec_from_file(args.spec_json),
            task_id=args.task_id,
            created_at=created_at,
        )
        print(json.dumps(asdict(package), indent=2, default=str))
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


def _selfdev_spec_from_file(path: Path) -> SelfDevelopmentTaskSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SELFDEV spec JSON must be an object")
    verifiers = payload.get("verifier_commands", ())
    if not isinstance(verifiers, list | tuple):
        raise ValueError("SELFDEV verifier_commands must be an array")
    return SelfDevelopmentTaskSpec(
        mandate_id=str(payload.get("mandate_id", "")),
        repository_id=str(payload.get("repository_id", "")),
        repository_head=str(payload.get("repository_head", "")),
        isolated_workspace=str(payload.get("isolated_workspace", "")),
        isolated_branch=str(payload.get("isolated_branch", "")),
        target_path=str(payload.get("target_path", "")),
        verifier_commands=tuple(str(command) for command in verifiers),
        expected_outcome_id=str(payload.get("expected_outcome_id", "")),
        rollback_strategy=str(payload.get("rollback_strategy", "")),
        operator_intervention_count=int(payload.get("operator_intervention_count", -1)),
        hcw_minutes=float(payload.get("hcw_minutes", -1)),
        baseline_assignment_id=str(payload.get("baseline_assignment_id", "")),
    )


if __name__ == "__main__":
    main()
