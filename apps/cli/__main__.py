from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from agent_os_contracts import ProviderToolProposal, RunStatus
from apps.api_server.app import AgentOSApplication
from agent_os_core import (
    DeterministicProvider,
    RUN_DENIED,
    SelfDevelopmentTaskSpec,
    SelfDevelopmentValidationError,
    build_self_development_baseline_record,
    build_self_development_comparison_receipt,
    build_self_development_run_record,
    evaluate_self_development_readiness,
    prepare_self_development_task_package,
    validate_self_development_task,
)
from agent_os_core.mandate_repl import run_mandate_repl
from agent_os_core.mandate_terminal import (
    MandateTerminalError,
    attach_mandate,
    bootstrap_mandate,
    emit_help_request,
    load_help_request_json,
    load_mandate_json,
    load_relevance_context_json,
    mandate_status,
)


_SUBCOMMANDS = frozenset(
    {
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
        "selfdev-validate",
        "selfdev-prepare",
        "selfdev-create",
        "selfdev-run-local",
        "selfdev-readiness",
        "selfdev-baseline-record",
        "selfdev-baseline-capture",
        "selfdev-run-provider",
        "selfdev-run-record",
        "selfdev-compare",
        "mandate",
        "mandate-bootstrap",
        "mandate-attach",
        "mandate-status",
        "mandate-help-request",
    }
)


def _normalize_argv(argv: list[str]) -> list[str]:
    """Bare `agent-os` (like `codex`) defaults to the Mandate REPL."""
    args = list(argv[1:])
    flags_passthrough = []
    for flag in (
        "--offline",
        "--no-tools",
        "--auto-approve-patches",
        "--continue",
        "--agent",
        "--resume",
        "--no-zero-config",
    ):
        if flag in args:
            flags_passthrough.append(flag)
            args = [token for token in args if token != flag]
    i = 0
    while i < len(args):
        token = args[i]
        if token in {
            "--database",
            "--workspace",
            "--repo",
            "--max-continuation-cycles",
            "--mission",
        }:
            i += 2 if i + 1 < len(args) else 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args) or args[i] not in _SUBCOMMANDS:
        args[i:i] = ["mandate"]
    for flag in reversed(flags_passthrough):
        args.insert(0, flag)
    return [argv[0], *args]


def main(argv: list[str] | None = None) -> None:
    raw = list(sys.argv if argv is None else argv)
    normalized = _normalize_argv(raw)
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description=(
            "Agent OS CLI. Bare `agent-os` launches the Mandate terminal agent "
            "(same usage pattern as `codex` / `kimi`)."
        ),
    )
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Mandate REPL: force DeterministicProvider (no live model)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Sandbox root for terminal tools (default: cwd)",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Chat-only Mandate REPL (disable workspace tools)",
    )
    parser.add_argument(
        "--auto-approve-patches",
        action="store_true",
        help="CI/test only: apply_patch/shell without interactive y/N",
    )
    parser.add_argument(
        "--continue",
        dest="continue_autonomous",
        action="store_true",
        help="After the initial goal, auto-continue until DONE/BLOCKED/max cycles",
    )
    parser.add_argument(
        "--agent",
        dest="continue_autonomous",
        action="store_true",
        help="Alias for --continue (Codex-like agent mode)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume prior terminal session transcript from workspace",
    )
    parser.add_argument(
        "--max-continuation-cycles",
        type=int,
        default=8,
        help="Max autonomous continuation cycles (default 8)",
    )
    parser.add_argument(
        "--no-zero-config",
        action="store_true",
        help="Require prior mandate-attach (disable auto bootstrap)",
    )
    parser.add_argument(
        "--mission",
        default=None,
        help="Mission statement used when zero-config bootstraps a local Mandate",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Streaming rich TUI (Rich Live if installed; else ANSI progressive)",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Disable MCP tool loading from .agent_os/mcp.json",
    )
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
    selfdev_create = sub.add_parser("selfdev-create")
    selfdev_create.add_argument("spec_json", type=Path)
    selfdev_create.add_argument("--created-at")
    selfdev_create.add_argument("--run-until-approval", action="store_true")
    selfdev_run_local = sub.add_parser("selfdev-run-local")
    selfdev_run_local.add_argument("spec_json", type=Path)
    selfdev_run_local.add_argument("--patch-content-file", type=Path, required=True)
    selfdev_run_local.add_argument("--created-at")
    selfdev_run_local.add_argument("--approve", action="store_true")
    selfdev_readiness = sub.add_parser("selfdev-readiness")
    selfdev_readiness.add_argument("spec_json", type=Path)
    selfdev_readiness.add_argument("--baseline-record", type=Path)
    selfdev_baseline_record = sub.add_parser("selfdev-baseline-record")
    selfdev_baseline_record.add_argument("baseline_json", type=Path)
    selfdev_baseline_capture = sub.add_parser("selfdev-baseline-capture")
    selfdev_baseline_capture.add_argument("spec_json", type=Path)
    selfdev_baseline_capture.add_argument(
        "--operator-intervention-count",
        type=int,
        required=True,
    )
    selfdev_baseline_capture.add_argument("--hcw-minutes", type=float, required=True)
    selfdev_baseline_capture.add_argument("--evidence-ref", action="append", default=[])
    selfdev_run_provider = sub.add_parser("selfdev-run-provider")
    selfdev_run_provider.add_argument("spec_json", type=Path)
    selfdev_run_provider.add_argument("--baseline-record", type=Path, required=True)
    selfdev_run_provider.add_argument("--created-at")
    selfdev_run_provider.add_argument("--approve", action="store_true")
    selfdev_run_provider.add_argument("--duration-seconds", type=int, default=300)
    selfdev_run_provider.add_argument("--statement")
    selfdev_run_record = sub.add_parser("selfdev-run-record")
    selfdev_run_record.add_argument("spec_json", type=Path)
    selfdev_run_record.add_argument(
        "--operator-intervention-count",
        type=int,
        required=True,
    )
    selfdev_run_record.add_argument("--hcw-minutes", type=float, required=True)
    selfdev_run_record.add_argument("--outcome-status", required=True)
    selfdev_run_record.add_argument("--evidence-ref", action="append", default=[])
    selfdev_compare = sub.add_parser("selfdev-compare")
    selfdev_compare.add_argument("spec_json", type=Path)
    selfdev_compare.add_argument("baseline_record_json", type=Path)
    selfdev_compare.add_argument("selfdev_run_record_json", type=Path)
    mandate_repl = sub.add_parser(
        "mandate",
        help="Interactive Mandate terminal agent (default when no subcommand)",
    )
    mandate_repl.add_argument(
        "prompt",
        nargs="*",
        help="Optional initial prompt (Codex-style: agent-os \"...\")",
    )
    mandate_bootstrap = sub.add_parser(
        "mandate-bootstrap",
        help="Admin: persist RatifiedMandateRef (not the agent entry)",
    )
    mandate_bootstrap.add_argument("mandate_json", type=Path)
    mandate_bootstrap.add_argument("--relevance-context", type=Path)
    mandate_attach = sub.add_parser(
        "mandate-attach",
        help="Admin: bind durable Mandate session before REPL",
    )
    mandate_attach.add_argument("--mandate-id", required=True)
    mandate_attach.add_argument("--environment-binding-id", required=True)
    mandate_attach.add_argument("--principal-id", required=True)
    mandate_attach.add_argument("--tenant-id", required=True)
    mandate_attach.add_argument("--workspace-id", required=True)
    mandate_attach.add_argument("--evaluated-at")
    mandate_status_cmd = sub.add_parser(
        "mandate-status",
        help="Admin: print Mandate JSON status",
    )
    mandate_status_cmd.add_argument("--evaluated-at")
    mandate_help = sub.add_parser(
        "mandate-help-request",
        help="Admin: emit HelpRequest from JSON file",
    )
    mandate_help.add_argument("help_request_json", type=Path)
    mandate_help.add_argument("--evaluated-at")
    args = parser.parse_args(normalized[1:])
    if args.command == "mandate":
        initial = " ".join(args.prompt).strip() or None
        try:
            run_mandate_repl(
                workspace=Path(args.workspace),
                database=Path(args.database),
                offline=bool(args.offline),
                initial_prompt=initial,
                tools_enabled=not bool(args.no_tools),
                repo_root=Path(args.repo),
                auto_approve_patches=bool(args.auto_approve_patches),
                continue_autonomous=bool(args.continue_autonomous),
                max_continuation_cycles=int(args.max_continuation_cycles),
                zero_config=not bool(args.no_zero_config),
                mission_statement=args.mission,
                resume_session=bool(args.resume),
                enable_tui=bool(args.tui),
                enable_mcp=not bool(args.no_mcp),
            )
        except MandateTerminalError as exc:
            print(f"MandateTerminalError: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        return
    if args.command in {
        "mandate-bootstrap",
        "mandate-attach",
        "mandate-status",
        "mandate-help-request",
    }:
        try:
            _run_mandate_terminal_command(args)
        except MandateTerminalError as exc:
            print(f"MandateTerminalError: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        return
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
    if args.command == "selfdev-readiness":
        report, provider = _evaluate_selfdev_readiness_from_env(
            _selfdev_spec_from_file(args.spec_json),
            baseline_record=(
                _selfdev_baseline_record_from_file(args.baseline_record)
                if args.baseline_record
                else None
            ),
        )
        output = asdict(report)
        output["provider"] = provider
        print(json.dumps(output, indent=2, default=str))
        return
    if args.command == "selfdev-baseline-record":
        record = _selfdev_baseline_record_from_file(args.baseline_json)
        print(json.dumps(asdict(record), indent=2, default=str))
        return
    if args.command == "selfdev-baseline-capture":
        output = _capture_selfdev_baseline(
            _selfdev_spec_from_file(args.spec_json),
            operator_intervention_count=args.operator_intervention_count,
            hcw_minutes=args.hcw_minutes,
            extra_evidence_refs=tuple(args.evidence_ref),
        )
        print(json.dumps(output, indent=2, default=str))
        return
    if args.command == "selfdev-run-record":
        record = build_self_development_run_record(
            _selfdev_spec_from_file(args.spec_json),
            operator_intervention_count=args.operator_intervention_count,
            hcw_minutes=args.hcw_minutes,
            outcome_status=args.outcome_status,
            evidence_refs=tuple(args.evidence_ref),
        )
        print(json.dumps(asdict(record), indent=2, default=str))
        return
    if args.command == "selfdev-compare":
        spec = _selfdev_spec_from_file(args.spec_json)
        comparison = build_self_development_comparison_receipt(
            spec,
            baseline_record=_selfdev_baseline_record_from_file(
                args.baseline_record_json,
            ),
            selfdev_run_record=_selfdev_run_record_from_file(
                args.selfdev_run_record_json,
                spec=spec,
            ),
        )
        print(json.dumps(asdict(comparison), indent=2, default=str))
        return

    app = AgentOSApplication(database=args.database, workspace=Path(args.workspace))
    if args.command == "selfdev-create":
        spec = _selfdev_spec_from_file(args.spec_json)
        receipt = validate_self_development_task(spec)
        created_at = (
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
            if args.created_at
            else datetime.now().astimezone()
        )
        created = app.create_task(
            {
                "goal_id": f"goal:selfdev:{receipt.receipt_digest[:12]}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "user:local",
                "created_at": created_at.isoformat(),
                "statement": (
                    "Agent OS self-development repository task for "
                    f"{receipt.target_path}"
                ),
            }
        )
        package = prepare_self_development_task_package(
            spec,
            task_id=created.task_id,
            created_at=created_at,
        )
        committed = app.commit_task(created.task_id, package.task_commit_payload)
        output: dict[str, object] = {
            "task": app.task_json(committed.task_id),
            "package": asdict(package),
        }
        if args.run_until_approval:
            proposed = app.run_task(committed.task_id, package.run_inputs)
            output["task"] = app.task_json(proposed.task_id)
        print(json.dumps(output, indent=2, default=str))
    elif args.command == "selfdev-run-provider":
        spec = _selfdev_spec_from_file(args.spec_json)
        baseline_record = _selfdev_baseline_record_from_file(args.baseline_record)
        readiness, provider = _evaluate_selfdev_readiness_from_env(
            spec,
            baseline_record=baseline_record,
        )
        if not readiness.ready:
            raise SelfDevelopmentValidationError(
                RUN_DENIED,
                "selfdev-run-provider readiness failed: "
                + ",".join(readiness.blockers),
            )
        runtime_provider = _selfdev_provider_runtime_binding(app, provider)
        receipt = validate_self_development_task(spec)
        created_at = (
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
            if args.created_at
            else datetime.now().astimezone()
        )
        statement = args.statement or (
            "Real provider Agent OS self-development run for "
            f"{receipt.target_path}"
        )
        created = app.create_task(
            {
                "goal_id": f"goal:selfdev:{receipt.receipt_digest[:12]}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "user:local",
                "created_at": created_at.isoformat(),
                "statement": statement,
            }
        )
        package = prepare_self_development_task_package(
            spec,
            task_id=created.task_id,
            created_at=created_at,
            statement=statement,
            duration_seconds=args.duration_seconds,
        )
        committed = app.commit_task(created.task_id, package.task_commit_payload)
        snapshot = app.seal_task_configuration(committed.task_id, {})
        proposed = app.run_task(
            committed.task_id,
            package.run_inputs,
            configuration_snapshot_id=snapshot.snapshot_id,
        )
        waiting_approval = (
            proposed.run is not None
            and proposed.run.status is RunStatus.WAITING_APPROVAL
        )
        mode = (
            "REAL_PROVIDER_READY_UNTIL_APPROVAL"
            if waiting_approval
            else "REAL_PROVIDER_RUN_FINISHED"
        )
        task = proposed
        if waiting_approval and args.approve:
            app.record_approval(
                committed.task_id,
                {
                    "disposition": "APPROVE",
                    "reason": (
                        "Approved exact-digest SELFDEV provider patch proposal "
                        "via CLI --approve"
                    ),
                },
            )
            task = app.run_task(
                committed.task_id,
                package.run_inputs,
                configuration_snapshot_id=snapshot.snapshot_id,
            )
            mode = "REAL_PROVIDER_RUN_COMPLETED"
        print(
            json.dumps(
                {
                    "mode": mode,
                    "provider": provider,
                    "runtime_provider": runtime_provider,
                    "readiness": asdict(readiness),
                    "baseline_record": asdict(baseline_record),
                    "configuration_snapshot_id": snapshot.snapshot_id,
                    "approval_required": waiting_approval and not args.approve,
                    "task": app.task_json(task.task_id),
                    "package": asdict(package),
                },
                indent=2,
                default=str,
            )
        )
    elif args.command == "selfdev-run-local":
        spec = _selfdev_spec_from_file(args.spec_json)
        receipt = validate_self_development_task(spec)
        patch_content = args.patch_content_file.read_text(encoding="utf-8")
        created_at = (
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
            if args.created_at
            else datetime.now().astimezone()
        )
        created = app.create_task(
            {
                "goal_id": f"goal:selfdev:{receipt.receipt_digest[:12]}",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "created_by": "user:local",
                "created_at": created_at.isoformat(),
                "statement": (
                    "Local controlled Agent OS self-development run for "
                    f"{receipt.target_path}"
                ),
            }
        )
        package = prepare_self_development_task_package(
            spec,
            task_id=created.task_id,
            created_at=created_at,
            statement=(
                "Local controlled Agent OS self-development run for "
                f"{receipt.target_path}"
            ),
        )
        committed = app.commit_task(created.task_id, package.task_commit_payload)
        app.provider = DeterministicProvider(
            text="",
            tool_proposals=(
                ProviderToolProposal(
                    proposal_id=f"proposal:selfdev:{receipt.receipt_digest[:12]}",
                    capability_id="workspace.apply_patch",
                    arguments_json=json.dumps(
                        {"path": receipt.target_path, "content": patch_content}
                    ),
                ),
            ),
        )
        app.provider_configured = True
        waiting = app.run_task(committed.task_id, package.run_inputs)
        output = {
            "mode": "LOCAL_CONTROLLED_DETERMINISTIC_PROVIDER",
            "task": app.task_json(waiting.task_id),
            "package": asdict(package),
        }
        if args.approve:
            app.record_approval(
                committed.task_id,
                {
                    "disposition": "APPROVE",
                    "reason": "Approved explicit local SELFDEV patch content",
                },
            )
            result = app.run_task(committed.task_id, package.run_inputs)
            output["task"] = app.task_json(result.task_id)
        print(json.dumps(output, indent=2, default=str))
    elif args.command == "task-create":
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


def _selfdev_baseline_record_from_file(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SELFDEV baseline record JSON must be an object")
    evidence_refs = payload.get("evidence_refs", ())
    if not isinstance(evidence_refs, list | tuple):
        raise ValueError("SELFDEV baseline evidence_refs must be an array")
    return build_self_development_baseline_record(
        baseline_assignment_id=str(payload.get("baseline_assignment_id", "")),
        repository_id=str(payload.get("repository_id", "")),
        target_path=str(payload.get("target_path", "")),
        operator_intervention_count=int(
            payload.get("operator_intervention_count", -1)
        ),
        hcw_minutes=float(payload.get("hcw_minutes", -1)),
        outcome_status=str(payload.get("outcome_status", "")),
        evidence_refs=tuple(str(ref) for ref in evidence_refs),
    )


def _selfdev_run_record_from_file(path: Path, *, spec: SelfDevelopmentTaskSpec):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SELFDEV run record JSON must be an object")
    evidence_refs = payload.get("evidence_refs", ())
    if not isinstance(evidence_refs, list | tuple):
        raise ValueError("SELFDEV run evidence_refs must be an array")
    return build_self_development_run_record(
        spec,
        operator_intervention_count=int(
            payload.get("operator_intervention_count", -1)
        ),
        hcw_minutes=float(payload.get("hcw_minutes", -1)),
        outcome_status=str(payload.get("outcome_status", "")),
        evidence_refs=tuple(str(ref) for ref in evidence_refs),
    )


def _evaluate_selfdev_readiness_from_env(
    spec: SelfDevelopmentTaskSpec,
    *,
    baseline_record,
):
    credential_env = os.environ.get("AGENT_OS_PROVIDER_API_KEY_ENV", "OPENAI_API_KEY")
    provider = {
        "base_url_configured": bool(os.environ.get("AGENT_OS_PROVIDER_BASE_URL")),
        "model_configured": bool(os.environ.get("AGENT_OS_PROVIDER_MODEL")),
        "credential_env": credential_env,
        "credential_available": bool(os.environ.get(credential_env)),
    }
    return (
        evaluate_self_development_readiness(
            spec,
            provider_configured=provider["base_url_configured"],
            provider_model=os.environ.get("AGENT_OS_PROVIDER_MODEL"),
            credential_available=provider["credential_available"],
            baseline_record=baseline_record,
        ),
        provider,
    )


def _selfdev_provider_runtime_binding(
    app: AgentOSApplication,
    provider: dict[str, object],
) -> dict[str, object]:
    if not getattr(app, "provider_configured", False):
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "selfdev-run-provider runtime provider is not configured",
        )
    profile = getattr(app, "provider_profile", None)
    model_id = getattr(profile, "model_id", None)
    endpoint_class = getattr(profile, "endpoint_class", None)
    configured_model = os.environ.get("AGENT_OS_PROVIDER_MODEL")
    if configured_model and model_id != configured_model:
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "selfdev-run-provider runtime provider model does not match readiness",
        )
    if provider["base_url_configured"] and endpoint_class != "openai-compatible":
        raise SelfDevelopmentValidationError(
            RUN_DENIED,
            "selfdev-run-provider runtime provider endpoint is not live-compatible",
        )
    return {
        "configured": True,
        "profile_id": getattr(profile, "profile_id", "UNKNOWN"),
        "provider_id": getattr(profile, "provider_id", "UNKNOWN"),
        "model_id": model_id or "UNKNOWN",
        "model_revision_digest": getattr(
            profile,
            "model_revision_digest",
            None,
        ),
        "endpoint_class": endpoint_class or "UNKNOWN",
    }


def _capture_selfdev_baseline(
    spec: SelfDevelopmentTaskSpec,
    *,
    operator_intervention_count: int,
    hcw_minutes: float,
    extra_evidence_refs: tuple[str, ...],
) -> dict[str, object]:
    receipt = validate_self_development_task(spec)
    verifier_command = receipt.verifier_commands[0]
    completed = subprocess.run(
        shlex.split(verifier_command),
        cwd=receipt.isolated_workspace,
        check=False,
        capture_output=True,
        timeout=300,
    )
    stdout_digest = hashlib.sha256(completed.stdout).hexdigest()
    stderr_digest = hashlib.sha256(completed.stderr).hexdigest()
    verifier_payload = {
        "command": verifier_command,
        "exit_code": completed.returncode,
        "stdout_sha256": stdout_digest,
        "stderr_sha256": stderr_digest,
        "target_path": receipt.target_path,
        "receipt_digest": receipt.receipt_digest,
    }
    verifier_digest = hashlib.sha256(
        json.dumps(
            verifier_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    record = build_self_development_baseline_record(
        baseline_assignment_id=receipt.baseline_assignment_id,
        repository_id=receipt.repository_id,
        target_path=receipt.target_path,
        operator_intervention_count=operator_intervention_count,
        hcw_minutes=hcw_minutes,
        outcome_status="VERIFIED" if completed.returncode == 0 else "NOT_MET",
        evidence_refs=tuple(sorted((*extra_evidence_refs, f"verifier:{verifier_digest}"))),
    )
    return {
        "admission_receipt": asdict(receipt),
        "baseline_record": asdict(record),
        "verifier": {**verifier_payload, "evidence_ref": f"verifier:{verifier_digest}"},
    }


def _run_mandate_terminal_command(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    database = Path(args.database)
    evaluated_at = (
        datetime.fromisoformat(args.evaluated_at.replace("Z", "+00:00"))
        if getattr(args, "evaluated_at", None)
        else None
    )
    if args.command == "mandate-bootstrap":
        relevance = (
            load_relevance_context_json(args.relevance_context)
            if args.relevance_context
            else None
        )
        output = bootstrap_mandate(
            database=database,
            mandate=load_mandate_json(args.mandate_json),
            relevance_context=relevance,
            workspace=workspace if relevance is not None else None,
        )
        print(json.dumps(output, indent=2, default=str))
        return
    if args.command == "mandate-attach":
        session = attach_mandate(
            workspace=workspace,
            database=database,
            mandate_id=args.mandate_id,
            environment_binding_id=args.environment_binding_id,
            principal_id=args.principal_id,
            tenant_id=args.tenant_id,
            workspace_id=args.workspace_id,
            evaluated_at=evaluated_at,
        )
        print(json.dumps(session.to_dict(), indent=2, default=str))
        return
    if args.command == "mandate-status":
        output = mandate_status(workspace=workspace, evaluated_at=evaluated_at)
        print(json.dumps(output, indent=2, default=str))
        return
    if args.command == "mandate-help-request":
        output = emit_help_request(
            workspace=workspace,
            help_request=load_help_request_json(args.help_request_json),
            evaluated_at=evaluated_at,
        )
        print(json.dumps(output, indent=2, default=str))
        return
    raise MandateTerminalError(f"unknown mandate command: {args.command}")


if __name__ == "__main__":
    main()
