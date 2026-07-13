"""Subprocess-only pinned-runner contract qualification and receipt reverification.

The pinned workflow runner at ``codex/team-event-contract-v1-20260713``,
commit ``3a3224a7af7da724d8b6ec82d34ed47d938620e4``, is the sole producer of
the ``TeamEvent`` JSON Schema, the governed event record, and the permission
sequence used to construct the qualification receipt.

This module invokes the runner exclusively through its interpreter and CLI.
No runner package is imported into Product or evaluation runtime.  Every
receipt field is computed from live subprocess output and validated against
the typed authority binding and the strict JSON-Schema consumer.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from product_evals.common.artifacts import canonical_sha256
from product_evals.common.authority_binding import verify_authority_binding
from product_evals.common.bank_generator import canonical_json_bytes
from product_evals.common.json_schema_contract import (
    canonical_schema_sha256,
    normalize_timestamped_record,
    validate_closed_record,
)

_CANARY_OBJECTIVE = "Qualify the runner-owned event contract"
_CANARY_TASK_TYPE = "workflow"
_CANARY_AGENT_ID = "codex"
_CANARY_ACTION = "team.event.record"
_CANARY_RISK_LEVEL = "R2"
_CANARY_REQUEST_NOTE = "qualify the governed event producer"
_CANARY_DECIDER = "founder"
_CANARY_DECISION = "approved_session"
_CANARY_DECISION_NOTE = "approve the runner contract canary"
_CANARY_EVENT_TYPE = "TASK_ASSIGNED"
_CANARY_EVENT_SUMMARY = "qualify the runner-owned event contract"
_CANARY_TASK_ID = "runner-contract-canary"
_CANARY_ARTIFACT = "quality_report.md"
_CANARY_EVIDENCE_REF = "quality_report.md"
_CANARY_SOURCE_DECISION_ID = "decision-runner-contract-canary"
_CANARY_SOURCE_GOAL_ID = "goal-runner-contract-canary"
_CANARY_SOURCE_DECISION_TYPE = "contract-qualification"
_QUALIFICATION_ERROR = "INVALID_RUNNER_CONTRACT_QUALIFICATION"
_SECOND_BOUNDARY_TIMEOUT_SECONDS = 2.0
_VERIFIED_REQUEST_ID_MARKER = "<verified-authority-request-id>"


def _runner_env(runner_worktree: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(runner_worktree / "src"),
    }


def _run_runner(
    *args: str,
    runner_worktree: Path,
    runner_python: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(runner_python), "-m", "agent_workflow_runner.cli", *args],
        cwd=runner_worktree,
        env=_runner_env(runner_worktree),
        check=True,
        text=True,
        capture_output=True,
    )


def _check_clean(runner_worktree: Path) -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=runner_worktree,
        check=True,
        text=True,
        capture_output=True,
    )
    if completed.stdout.strip():
        raise ValueError("INVALID_RUNNER_IDENTITY")


def _check_branch(runner_worktree: Path, expected_branch: str) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=runner_worktree,
        check=True,
        text=True,
        capture_output=True,
    )
    if completed.stdout.strip() != expected_branch:
        raise ValueError("INVALID_RUNNER_IDENTITY")


def _check_head(runner_worktree: Path, expected_head: str) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=runner_worktree,
        check=True,
        text=True,
        capture_output=True,
    )
    if completed.stdout.strip() != expected_head:
        raise ValueError("INVALID_RUNNER_IDENTITY")


def _check_interpreter(runner_python: Path) -> Path:
    absolute = Path(os.path.abspath(runner_python))
    if not absolute.is_file():
        raise ValueError("INVALID_RUNNER_IDENTITY")
    return absolute


def _wait_until_after_runner_second(request_ts: object) -> None:
    """Wait for a real later runner timestamp without modifying its ledgers."""

    if not isinstance(request_ts, str):
        raise ValueError(_QUALIFICATION_ERROR)
    try:
        request_instant = datetime.fromisoformat(request_ts)
    except ValueError as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc
    if request_instant.tzinfo is None or request_instant.utcoffset() is None:
        raise ValueError(_QUALIFICATION_ERROR)

    deadline = time.monotonic() + _SECOND_BOUNDARY_TIMEOUT_SECONDS
    while datetime.now(tz=UTC).replace(microsecond=0) <= request_instant:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(_QUALIFICATION_ERROR)
        time.sleep(min(0.01, remaining))


def _check_import(runner_worktree: Path, runner_python: Path) -> str:
    completed = subprocess.run(
        [
            str(runner_python),
            "-c",
            "import agent_workflow_runner; print(agent_workflow_runner.__file__)",
        ],
        cwd=runner_worktree,
        env=_runner_env(runner_worktree),
        check=True,
        text=True,
        capture_output=True,
    )
    import_path = completed.stdout.strip()
    if not import_path:
        raise ValueError("INVALID_RUNNER_IDENTITY")
    return import_path


def _common_dir(runner_worktree: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=runner_worktree,
        check=True,
        text=True,
        capture_output=True,
    )
    relative = completed.stdout.strip()
    return str((runner_worktree / relative).resolve())


def _verify_runner_identity(
    *,
    runner_worktree: Path,
    runner_python: Path,
    expected_branch: str,
    expected_head: str,
) -> tuple[Path, str, str, bool, str]:
    worktree = Path(runner_worktree).resolve()
    if not worktree.is_dir():
        raise ValueError("INVALID_RUNNER_IDENTITY")
    _check_branch(worktree, expected_branch)
    _check_head(worktree, expected_head)
    clean = True
    try:
        _check_clean(worktree)
    except ValueError:
        clean = False
        raise
    interpreter = _check_interpreter(runner_python)
    import_path = _check_import(worktree, runner_python)
    if not Path(import_path).is_relative_to(worktree / "src"):
        raise ValueError("INVALID_RUNNER_IDENTITY")
    git_dir = _common_dir(worktree)
    return interpreter, import_path, git_dir, clean, expected_branch


def _check_paths_non_alias(
    scratch_workspace: Path,
    formal_paths: tuple[Path, ...],
) -> None:
    resolved_scratch = Path(scratch_workspace).resolve()
    resolved_formal = tuple(Path(p).resolve() for p in formal_paths)
    for fp in resolved_formal:
        try:
            fp.relative_to(resolved_scratch)
            raise ValueError("INVALID_QUALIFICATION_PATHS")
        except ValueError as exc:
            if "INVALID_QUALIFICATION_PATHS" in str(exc):
                raise
        try:
            resolved_scratch.relative_to(fp.parent)
            raise ValueError("INVALID_QUALIFICATION_PATHS")
        except ValueError as exc:
            if "INVALID_QUALIFICATION_PATHS" in str(exc):
                raise


def _export_schema(
    schema_path: Path,
    runner_worktree: Path,
    runner_python: Path,
    *,
    write_snapshot: bool,
) -> tuple[bytes, dict[str, Any]]:
    completed = _run_runner(
        "team",
        "event-schema",
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )
    raw_schema = completed.stdout.encode("utf-8")
    schema = json.loads(completed.stdout)
    if write_snapshot:
        # A qualification snapshot is an immutable input to later receipt
        # verification.  Exclusive creation prevents a stale or already-bound
        # digest from being silently replaced.
        Path(schema_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(schema_path).open("xb") as snapshot:
            snapshot.write(raw_schema)
    return raw_schema, schema


def _run_scratch_canary(
    scratch_workspace: Path,
    canary_run_id: str,
    runner_worktree: Path,
    runner_python: Path,
) -> dict[str, Any]:
    workspace = Path(scratch_workspace)
    _require_fresh_scratch_run(workspace, canary_run_id)
    workspace.mkdir(parents=True, exist_ok=True)

    _run_runner(
        "init",
        "--workflow",
        str(runner_worktree / "workflow.yaml"),
        "--workspace-root",
        str(workspace),
        "--run-id",
        canary_run_id,
        "--objective",
        _CANARY_OBJECTIVE,
        "--task-type",
        _CANARY_TASK_TYPE,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )
    request_completed = _run_runner(
        "permission",
        "request",
        "--workspace-root",
        str(workspace),
        "--run-id",
        canary_run_id,
        "--policy",
        str(runner_worktree / "recipes/autonomy.policy.yaml"),
        "--agent-id",
        _CANARY_AGENT_ID,
        "--action",
        _CANARY_ACTION,
        "--risk-level",
        _CANARY_RISK_LEVEL,
        "--note",
        _CANARY_REQUEST_NOTE,
        "--affected-path",
        f".agent_runs/{canary_run_id}/agent_events.jsonl",
        "--evidence-ref",
        _CANARY_EVIDENCE_REF,
        "--source-decision-id",
        _CANARY_SOURCE_DECISION_ID,
        "--source-goal-id",
        _CANARY_SOURCE_GOAL_ID,
        "--source-decision-type",
        _CANARY_SOURCE_DECISION_TYPE,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )
    request = json.loads(request_completed.stdout)["request"]
    request_id = request["request_id"]
    _wait_until_after_runner_second(request.get("ts"))
    _run_runner(
        "permission",
        "decide",
        "--workspace-root",
        str(workspace),
        "--run-id",
        canary_run_id,
        "--request-id",
        request_id,
        "--decision",
        _CANARY_DECISION,
        "--decided-by",
        _CANARY_DECIDER,
        "--note",
        _CANARY_DECISION_NOTE,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )
    _run_runner(
        "team",
        "event",
        "--workspace-root",
        str(workspace),
        "--run-id",
        canary_run_id,
        "--type",
        _CANARY_EVENT_TYPE,
        "--agent-id",
        _CANARY_AGENT_ID,
        "--summary",
        _CANARY_EVENT_SUMMARY,
        "--task-id",
        _CANARY_TASK_ID,
        "--artifact",
        _CANARY_ARTIFACT,
        "--evidence-ref",
        _CANARY_EVIDENCE_REF,
        "--source-decision-id",
        _CANARY_SOURCE_DECISION_ID,
        "--source-goal-id",
        _CANARY_SOURCE_GOAL_ID,
        "--source-decision-type",
        _CANARY_SOURCE_DECISION_TYPE,
        "--approval-request-id",
        request_id,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )
    event_path = workspace / ".agent_runs" / canary_run_id / "agent_events.jsonl"
    rows = [json.loads(line) for line in event_path.read_text().splitlines()]
    if len(rows) != 1:
        raise ValueError(_QUALIFICATION_ERROR)
    return rows[0]


def _require_fresh_scratch_run(scratch_workspace: Path, canary_run_id: str) -> None:
    run_root = Path(scratch_workspace) / ".agent_runs" / canary_run_id
    # lexists also rejects a dangling symlink occupying the run identity.
    if os.path.lexists(run_root):
        raise ValueError(_QUALIFICATION_ERROR)


def _compute_source_sha256(
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, str]:
    return {
        "json_schema_contract.py": hashlib.sha256(
            Path(consumer_source_path).resolve().read_bytes()
        ).hexdigest(),
        "authority_binding.py": hashlib.sha256(
            Path(authority_source_path).resolve().read_bytes()
        ).hexdigest(),
        "runner_contract_qualification.py": hashlib.sha256(
            Path(__file__).resolve().read_bytes()
        ).hexdigest(),
    }


def _single_ledger_row(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(_QUALIFICATION_ERROR)
    return rows[0]


def _authority_semantic_sha256(run_root: Path) -> str:
    """Bind stable authority semantics without timestamps or random IDs.

    The typed verifier remains authoritative.  This projection only makes its
    already-verified request/approval semantics receipt-stable across fresh
    canaries, whose timestamps and request identifiers necessarily differ.
    """

    request = _single_ledger_row(run_root / "approval_requests.jsonl")
    approval = _single_ledger_row(run_root / "approvals.jsonl")
    request_projection = {
        key: value for key, value in request.items() if key not in {"request_id", "ts"}
    }
    approval_projection = {
        key: value for key, value in approval.items() if key not in {"request_id", "ts"}
    }
    request_projection["request_id"] = _VERIFIED_REQUEST_ID_MARKER
    approval_projection["request_id"] = _VERIFIED_REQUEST_ID_MARKER
    semantic_projection = {
        "request": request_projection,
        "approval": approval_projection,
    }
    return canonical_sha256(semantic_projection)


def _verify_schema_snapshot(
    schema_path: Path,
    expected_receipt: Mapping[str, Any],
) -> None:
    try:
        expected_schema = expected_receipt["schema"]
        raw_schema = Path(schema_path).read_bytes()
        schema = json.loads(raw_schema)
        raw_sha256 = hashlib.sha256(raw_schema).hexdigest()
        canonical_sha256 = canonical_schema_sha256(schema)
        if (
            raw_sha256 != expected_schema["raw_sha256"]
            or canonical_sha256 != expected_schema["canonical_sha256"]
            or schema.get("title") != expected_schema["version"]
        ):
            raise ValueError(_QUALIFICATION_ERROR)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc


def _require_formal_genesis(formal_paths: tuple[Path, ...]) -> None:
    if any(Path(path).exists() for path in formal_paths):
        raise ValueError("INVALID_EVALUATION_GENESIS")


def _build_receipt(
    *,
    runner_worktree: Path,
    runner_python: Path,
    expected_branch: str,
    expected_head: str,
    canary_run_id: str,
    schema_path: Path,
    scratch_workspace: Path,
    formal_paths: tuple[Path, ...],
    consumer_source_path: Path,
    authority_source_path: Path,
    write_schema_snapshot: bool,
) -> dict[str, Any]:
    _check_paths_non_alias(scratch_workspace, formal_paths)
    _require_formal_genesis(formal_paths)

    if write_schema_snapshot and Path(schema_path).exists():
        raise ValueError(_QUALIFICATION_ERROR)

    _require_fresh_scratch_run(scratch_workspace, canary_run_id)

    resolved_interpreter, import_path, git_dir, clean_ok, actual_branch = (
        _verify_runner_identity(
            runner_worktree=runner_worktree,
            runner_python=runner_python,
            expected_branch=expected_branch,
            expected_head=expected_head,
        )
    )

    raw_schema, schema = _export_schema(
        schema_path=schema_path,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
        write_snapshot=write_schema_snapshot,
    )

    schema_closed = schema.get("additionalProperties") is False

    raw_sha256 = hashlib.sha256(raw_schema).hexdigest()
    can_sha256 = canonical_schema_sha256(schema)
    schema_version = schema["title"]

    event = _run_scratch_canary(
        scratch_workspace=scratch_workspace,
        canary_run_id=canary_run_id,
        runner_worktree=runner_worktree,
        runner_python=runner_python,
    )

    # The producer identity is a live execution dependency, not just a setup
    # assertion.  Recheck it after the canary to close branch/head/dirty/import
    # TOCTOU between qualification and receipt construction.
    post_canary_identity = _verify_runner_identity(
        runner_worktree=runner_worktree,
        runner_python=runner_python,
        expected_branch=expected_branch,
        expected_head=expected_head,
    )
    if post_canary_identity != (
        resolved_interpreter,
        import_path,
        git_dir,
        clean_ok,
        actual_branch,
    ):
        raise ValueError("INVALID_RUNNER_IDENTITY")

    validate_closed_record(event, schema)

    canary_run_root = Path(scratch_workspace) / ".agent_runs" / canary_run_id
    try:
        authority_binding = verify_authority_binding(
            canary_run_root,
            run_id=canary_run_id,
            action=_CANARY_ACTION,
            affected_path=f".agent_runs/{canary_run_id}/agent_events.jsonl",
        )
    except ValueError as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc
    authority_binding_exact = (
        event["approval_request_id"] == authority_binding.request_id
        and event["permission_action"] == _CANARY_ACTION
        and event["permission_action"] == authority_binding.action
        and event["source_decision_id"] == authority_binding.source_decision_id
        and event["source_goal_id"] == authority_binding.source_goal_id
        and event["source_decision_type"] == authority_binding.source_decision_type
        and tuple(event["evidence_refs"]) == authority_binding.evidence_refs
    )
    if not authority_binding_exact:
        raise ValueError(_QUALIFICATION_ERROR)

    # Reverify before consuming ledger semantics so the projection cannot be
    # confused with an unverified row parse.
    try:
        if (
            verify_authority_binding(
                canary_run_root,
                run_id=canary_run_id,
                action=_CANARY_ACTION,
                affected_path=f".agent_runs/{canary_run_id}/agent_events.jsonl",
            )
            != authority_binding
        ):
            raise ValueError(_QUALIFICATION_ERROR)
        authority_semantic_sha256 = _authority_semantic_sha256(canary_run_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc

    normalized = normalize_timestamped_record(event, schema)
    normalized["approval_request_id"] = _VERIFIED_REQUEST_ID_MARKER
    emitted_fixture_sha256 = hashlib.sha256(
        canonical_json_bytes(normalized)
    ).hexdigest()

    source_sha256 = _compute_source_sha256(
        consumer_source_path=consumer_source_path,
        authority_source_path=authority_source_path,
    )

    try:
        _check_paths_non_alias(scratch_workspace, formal_paths)
    except ValueError as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc
    scratch_formal_non_alias = True

    _require_formal_genesis(formal_paths)
    formal_ledgers_absent = True

    runner_import_bound = Path(import_path).is_relative_to(
        Path(runner_worktree).resolve() / "src"
    )

    checks = {
        "authority_binding_exact": authority_binding_exact,
        "formal_ledgers_absent": formal_ledgers_absent,
        "runner_clean": clean_ok,
        "runner_import_bound": runner_import_bound,
        "scratch_formal_non_alias": scratch_formal_non_alias,
        "schema_closed": schema_closed,
    }
    if not all(checks.values()):
        raise ValueError(_QUALIFICATION_ERROR)

    return {
        "runner": {
            "branch": actual_branch,
            "head": expected_head,
            "clean": clean_ok,
            "interpreter": str(resolved_interpreter),
            "import_path": import_path,
            "common_dir": git_dir,
        },
        "schema": {
            "raw_sha256": raw_sha256,
            "canonical_sha256": can_sha256,
            "version": schema_version,
        },
        "emitted_fixture_sha256": emitted_fixture_sha256,
        "authority_semantic_sha256": authority_semantic_sha256,
        "source_sha256": source_sha256,
        "checks": checks,
    }


def qualify_runner_contract(
    *,
    runner_worktree: Path,
    runner_python: Path,
    expected_branch: str,
    expected_head: str,
    canary_run_id: str,
    schema_path: Path,
    scratch_workspace: Path,
    formal_paths: tuple[Path, ...],
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, Any]:
    try:
        return _build_receipt(
            runner_worktree=runner_worktree,
            runner_python=runner_python,
            expected_branch=expected_branch,
            expected_head=expected_head,
            canary_run_id=canary_run_id,
            schema_path=schema_path,
            scratch_workspace=scratch_workspace,
            formal_paths=formal_paths,
            consumer_source_path=consumer_source_path,
            authority_source_path=authority_source_path,
            write_schema_snapshot=True,
        )
    except ValueError as exc:
        if str(exc) in {
            "INVALID_RUNNER_IDENTITY",
            "INVALID_QUALIFICATION_PATHS",
            "INVALID_EVALUATION_GENESIS",
        }:
            raise
        raise ValueError(_QUALIFICATION_ERROR) from exc
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc


def verify_runner_contract_receipt(
    *,
    expected_receipt: Mapping[str, Any],
    runner_worktree: Path,
    runner_python: Path,
    expected_branch: str,
    expected_head: str,
    canary_run_id: str,
    schema_path: Path,
    scratch_workspace: Path,
    formal_paths: tuple[Path, ...],
    consumer_source_path: Path,
    authority_source_path: Path,
) -> dict[str, Any]:
    try:
        _verify_schema_snapshot(schema_path, expected_receipt)
        receipt = _build_receipt(
            runner_worktree=runner_worktree,
            runner_python=runner_python,
            expected_branch=expected_branch,
            expected_head=expected_head,
            canary_run_id=canary_run_id,
            schema_path=schema_path,
            scratch_workspace=scratch_workspace,
            formal_paths=formal_paths,
            consumer_source_path=consumer_source_path,
            authority_source_path=authority_source_path,
            write_schema_snapshot=False,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(_QUALIFICATION_ERROR) from exc
    if receipt != dict(expected_receipt):
        raise ValueError(_QUALIFICATION_ERROR)
    return receipt
