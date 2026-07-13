from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from product_evals.common.bank_generator import canonical_json_bytes
from product_evals.common.json_schema_contract import (
    canonical_schema_sha256,
    normalize_timestamped_record,
    validate_closed_record,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parents[2]
RUNNER_WORKTREE = (
    WORKSPACE_ROOT
    / "ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713"
)
RUNNER_PYTHON = WORKSPACE_ROOT / "ai-agent-engineering-workflow/.venv/bin/python"
RUNNER_BRANCH = "codex/team-event-contract-v1-20260713"
RUNNER_HEAD = "087f5907cd181c6e071fb24f135292abd9681ca7"
CANARY_RUN_ID = "runner-contract-canary"
VERIFIED_REQUEST_ID_MARKER = "<verified-authority-request-id>"
CONSUMER_SOURCE = REPO_ROOT / "product_evals/common/json_schema_contract.py"
AUTHORITY_SOURCE = REPO_ROOT / "product_evals/common/authority_binding.py"


def _module() -> Any:
    return importlib.import_module("product_evals.common.runner_contract_qualification")


def _runner_env(runner_worktree: Path = RUNNER_WORKTREE) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(runner_worktree / "src"),
    }


def _run_runner(
    *args: str,
    runner_worktree: Path = RUNNER_WORKTREE,
    runner_python: Path = RUNNER_PYTHON,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(runner_python), "-m", "agent_workflow_runner.cli", *args],
        cwd=runner_worktree,
        env=_runner_env(runner_worktree),
        check=True,
        text=True,
        capture_output=True,
    )


def _live_schema() -> tuple[bytes, dict[str, Any]]:
    completed = _run_runner("team", "event-schema")
    return completed.stdout.encode("utf-8"), json.loads(completed.stdout)


def _emit_live_event(workspace: Path, *, run_id: str) -> dict[str, Any]:
    """Produce the fixture through the real pinned runner, never by dict literal."""

    _run_runner(
        "init",
        "--workflow",
        str(RUNNER_WORKTREE / "workflow.yaml"),
        "--workspace-root",
        str(workspace),
        "--run-id",
        run_id,
        "--objective",
        "Qualify the runner-owned event contract",
        "--task-type",
        "workflow",
    )
    request = _run_runner(
        "permission",
        "request",
        "--workspace-root",
        str(workspace),
        "--run-id",
        run_id,
        "--policy",
        str(RUNNER_WORKTREE / "recipes/autonomy.policy.yaml"),
        "--agent-id",
        "codex",
        "--action",
        "team.event.record",
        "--risk-level",
        "R2",
        "--note",
        "qualify the governed event producer",
        "--affected-path",
        f".agent_runs/{run_id}/agent_events.jsonl",
        "--evidence-ref",
        "quality_report.md",
        "--source-decision-id",
        "decision-runner-contract-canary",
        "--source-goal-id",
        "goal-runner-contract-canary",
        "--source-decision-type",
        "contract-qualification",
    )
    request_id = json.loads(request.stdout)["request"]["request_id"]
    _run_runner(
        "permission",
        "decide",
        "--workspace-root",
        str(workspace),
        "--run-id",
        run_id,
        "--request-id",
        request_id,
        "--decision",
        "approved_session",
        "--decided-by",
        "founder",
        "--note",
        "approve the runner contract canary",
    )
    _run_runner(
        "team",
        "event",
        "--workspace-root",
        str(workspace),
        "--run-id",
        run_id,
        "--type",
        "TASK_ASSIGNED",
        "--agent-id",
        "codex",
        "--summary",
        "qualify the runner-owned event contract",
        "--task-id",
        "runner-contract-canary",
        "--artifact",
        "quality_report.md",
        "--evidence-ref",
        "quality_report.md",
        "--source-decision-id",
        "decision-runner-contract-canary",
        "--source-goal-id",
        "goal-runner-contract-canary",
        "--source-decision-type",
        "contract-qualification",
        "--approval-request-id",
        request_id,
    )
    event_path = workspace / ".agent_runs" / run_id / "agent_events.jsonl"
    rows = [json.loads(line) for line in event_path.read_text().splitlines()]
    assert len(rows) == 1
    return rows[0]


def _qualify(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "runner_worktree": RUNNER_WORKTREE,
        "runner_python": RUNNER_PYTHON,
        "expected_branch": RUNNER_BRANCH,
        "expected_head": RUNNER_HEAD,
        "canary_run_id": CANARY_RUN_ID,
        "schema_path": tmp_path / "runner_team_event_schema.json",
        "scratch_workspace": tmp_path / "scratch",
        "formal_paths": (
            tmp_path / "formal/evaluation/phases.jsonl",
            tmp_path / "formal/evaluation/provider_calls.jsonl",
            tmp_path / "formal/agent_events.jsonl",
        ),
        "consumer_source_path": CONSUMER_SOURCE,
        "authority_source_path": AUTHORITY_SOURCE,
    }
    arguments.update(overrides)
    return _module().qualify_runner_contract(**arguments)


def _verify(
    tmp_path: Path, expected_receipt: Mapping[str, Any], **overrides: Any
) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "expected_receipt": expected_receipt,
        "runner_worktree": RUNNER_WORKTREE,
        "runner_python": RUNNER_PYTHON,
        "expected_branch": RUNNER_BRANCH,
        "expected_head": RUNNER_HEAD,
        "canary_run_id": CANARY_RUN_ID,
        "schema_path": tmp_path / "runner_team_event_schema.json",
        "scratch_workspace": tmp_path / "verify-scratch",
        "formal_paths": (
            tmp_path / "formal/evaluation/phases.jsonl",
            tmp_path / "formal/evaluation/provider_calls.jsonl",
            tmp_path / "formal/agent_events.jsonl",
        ),
        "consumer_source_path": CONSUMER_SOURCE,
        "authority_source_path": AUTHORITY_SOURCE,
    }
    arguments.update(overrides)
    return _module().verify_runner_contract_receipt(**arguments)


def test_real_pinned_runner_canary_binds_schema_fixture_sources_and_import(
    tmp_path: Path,
) -> None:
    raw_schema, schema = _live_schema()
    independent_event = _emit_live_event(tmp_path / "independent", run_id=CANARY_RUN_ID)
    validate_closed_record(independent_event, schema)

    receipt = _qualify(tmp_path)

    authority_module = importlib.import_module("product_evals.common.authority_binding")
    binding = authority_module.verify_authority_binding(
        tmp_path / "scratch/.agent_runs" / CANARY_RUN_ID,
        run_id=CANARY_RUN_ID,
        action="team.event.record",
        affected_path=f".agent_runs/{CANARY_RUN_ID}/agent_events.jsonl",
    )
    canary_event_path = (
        tmp_path / "scratch/.agent_runs" / CANARY_RUN_ID / "agent_events.jsonl"
    )
    canary_event = json.loads(canary_event_path.read_text().splitlines()[0])
    normalized_canary = normalize_timestamped_record(canary_event, schema)
    assert canary_event["approval_request_id"] == binding.request_id
    assert canary_event["source_decision_id"] == binding.source_decision_id
    assert canary_event["source_goal_id"] == binding.source_goal_id
    assert canary_event["source_decision_type"] == binding.source_decision_type
    assert tuple(canary_event["evidence_refs"]) == binding.evidence_refs
    normalized_canary["approval_request_id"] = VERIFIED_REQUEST_ID_MARKER

    assert (tmp_path / "runner_team_event_schema.json").read_bytes() == raw_schema
    assert receipt["runner"]["branch"] == RUNNER_BRANCH
    assert receipt["runner"]["head"] == RUNNER_HEAD
    assert receipt["runner"]["clean"] is True
    assert Path(receipt["runner"]["interpreter"]).samefile(RUNNER_PYTHON)
    assert Path(receipt["runner"]["import_path"]).is_relative_to(
        RUNNER_WORKTREE / "src"
    )
    assert receipt["runner"]["common_dir"] == str(
        (WORKSPACE_ROOT / "ai-agent-engineering-workflow/.git").resolve()
    )
    assert receipt["schema"]["raw_sha256"] == hashlib.sha256(raw_schema).hexdigest()
    assert receipt["schema"]["canonical_sha256"] == canonical_schema_sha256(schema)
    assert receipt["schema"]["version"] == schema["title"]
    assert (
        receipt["emitted_fixture_sha256"]
        == hashlib.sha256(canonical_json_bytes(normalized_canary)).hexdigest()
    )
    assert receipt["source_sha256"] == {
        "authority_binding.py": hashlib.sha256(
            AUTHORITY_SOURCE.read_bytes()
        ).hexdigest(),
        "json_schema_contract.py": hashlib.sha256(
            CONSUMER_SOURCE.read_bytes()
        ).hexdigest(),
    }
    assert receipt["checks"] == {
        "authority_binding_exact": True,
        "formal_ledgers_absent": True,
        "runner_clean": True,
        "runner_import_bound": True,
        "scratch_formal_non_alias": True,
        "schema_closed": True,
    }
    stable_receipt_bytes = canonical_json_bytes(receipt)
    for ephemeral_authority_value in (
        binding.request_id,
        binding.request_sha256,
        binding.approval_sha256,
    ):
        assert ephemeral_authority_value.encode() not in stable_receipt_bytes
    assert _verify(tmp_path, receipt) == receipt
    assert not any(path.exists() for path in _formal_paths(tmp_path))


def _formal_paths(tmp_path: Path) -> tuple[Path, ...]:
    return (
        tmp_path / "formal/evaluation/phases.jsonl",
        tmp_path / "formal/evaluation/provider_calls.jsonl",
        tmp_path / "formal/agent_events.jsonl",
    )


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("runner", "head"),
        ("runner", "branch"),
        ("runner", "interpreter"),
        ("runner", "import_path"),
        ("schema", "raw_sha256"),
        ("schema", "canonical_sha256"),
        (None, "emitted_fixture_sha256"),
        ("source_sha256", "json_schema_contract.py"),
        ("source_sha256", "authority_binding.py"),
    ],
)
def test_receipt_reverification_rejects_every_bound_mutation(
    tmp_path: Path, section: str | None, field: str
) -> None:
    receipt = _qualify(tmp_path)
    mutated = json.loads(json.dumps(receipt))
    target = mutated if section is None else mutated[section]
    target[field] = "0" * 64

    with pytest.raises(ValueError, match="INVALID_RUNNER_CONTRACT_QUALIFICATION"):
        _verify(tmp_path, mutated)


def test_schema_snapshot_mutation_invalidates_reverification(tmp_path: Path) -> None:
    receipt = _qualify(tmp_path)
    schema_path = tmp_path / "runner_team_event_schema.json"
    schema = json.loads(schema_path.read_text())
    schema["title"] = "mutated"
    schema_path.write_bytes(canonical_json_bytes(schema))

    with pytest.raises(ValueError, match="INVALID_RUNNER_CONTRACT_QUALIFICATION"):
        _verify(tmp_path, receipt)


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("expected_head", "0" * 40),
        ("expected_branch", "codex/not-the-pinned-runner"),
    ],
)
def test_qualification_rejects_wrong_runner_identity_before_scratch_write(
    tmp_path: Path, override: str, value: str
) -> None:
    with pytest.raises(ValueError, match="INVALID_RUNNER_IDENTITY"):
        _qualify(tmp_path, **{override: value})

    assert not (tmp_path / "scratch").exists()


def test_qualification_rejects_dirty_runner_worktree(tmp_path: Path) -> None:
    clone = tmp_path / "dirty-runner"
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--branch",
            RUNNER_BRANCH,
            "--single-branch",
            str(RUNNER_WORKTREE),
            str(clone),
        ],
        check=True,
    )
    (clone / "untracked-dirty-marker").write_text("dirty", encoding="utf-8")

    with pytest.raises(ValueError, match="INVALID_RUNNER_IDENTITY"):
        _qualify(tmp_path, runner_worktree=clone)


def test_qualification_rejects_scratch_formal_alias(tmp_path: Path) -> None:
    scratch = tmp_path / "aliased"
    formal_event = scratch / ".agent_runs/canary/agent_events.jsonl"

    with pytest.raises(ValueError, match="INVALID_QUALIFICATION_PATHS"):
        _qualify(
            tmp_path,
            scratch_workspace=scratch,
            formal_paths=(formal_event, *(_formal_paths(tmp_path)[:2])),
        )

    assert not scratch.exists()


def test_reverification_rejects_consumer_source_drift(tmp_path: Path) -> None:
    consumer_copy = tmp_path / "json_schema_contract.py"
    shutil.copyfile(CONSUMER_SOURCE, consumer_copy)
    receipt = _qualify(tmp_path, consumer_source_path=consumer_copy)
    consumer_copy.write_text(
        consumer_copy.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="INVALID_RUNNER_CONTRACT_QUALIFICATION"):
        _verify(tmp_path, receipt, consumer_source_path=consumer_copy)


def test_reverification_rejects_non_pinned_interpreter(tmp_path: Path) -> None:
    receipt = _qualify(tmp_path)
    product_python = Path(os.environ.get("PYTHON", os.sys.executable))

    with pytest.raises(ValueError, match="INVALID_RUNNER_CONTRACT_QUALIFICATION"):
        _verify(tmp_path, receipt, runner_python=product_python)
