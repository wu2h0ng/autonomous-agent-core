from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from product_evals.common.bank_generator import (
    build_provider_bank,
    canonical_json_bytes,
)
from product_evals.common.provider_bank import request_body_digest
from product_evals.common.spine_identity import SpineEvaluationIdentity


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parents[2]
ASSET_ROOT = REPO_ROOT / "product_evals/spine_e2e_4"
RUNNER_WORKTREE = (
    WORKSPACE_ROOT
    / "ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713"
)
RUNNER_PYTHON = WORKSPACE_ROOT / "ai-agent-engineering-workflow/.venv/bin/python"
RUNNER_BRANCH = "codex/team-event-contract-v1-20260713"
RUNNER_HEAD = "087f5907cd181c6e071fb24f135292abd9681ca7"
PREDECESSOR_IDENTITY = re.compile(
    rb"(?:spine-e2e-[123]|SPINE-E2E-[123]|spine_e2e_[123]|SPINE_E2E_[123])"
)


def _identity_module() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.identity")


def _json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _live_schema_bytes() -> bytes:
    completed = subprocess.run(
        [
            str(RUNNER_PYTHON),
            "-m",
            "agent_workflow_runner.cli",
            "team",
            "event-schema",
        ],
        cwd=RUNNER_WORKTREE,
        env={**os.environ, "PYTHONPATH": str(RUNNER_WORKTREE / "src")},
        check=True,
        capture_output=True,
    )
    return completed.stdout


def test_identity_is_derived_from_sequence_and_date_only() -> None:
    identity = _identity_module().IDENTITY
    expected = SpineEvaluationIdentity.create(sequence=4, run_date="20260713")

    assert identity == expected
    assert identity.experiment_id == expected.experiment_id
    assert identity.run_id == expected.run_id
    assert identity.provider_model == expected.provider_model
    assert identity.provider_bearer == expected.provider_bearer


def test_generated_provider_assets_have_no_copied_model_or_digest_constants() -> None:
    identity = _identity_module().IDENTITY
    template_path = ASSET_ROOT / "request_template.json"
    bank_path = ASSET_ROOT / "provider_responses.json"
    template = _json(template_path)
    bank = _json(bank_path)

    expected = build_provider_bank(identity, template)
    assert bank_path.read_bytes() == canonical_json_bytes(expected)
    assert bank == expected
    for entry in bank["entries"]:
        assert entry["digest"] == request_body_digest(entry["request"])
        assert entry["request"]["model"] == identity.provider_model
        assert entry["response"]["model"] == identity.provider_model


def test_runner_schema_snapshot_is_exact_live_export_not_a_handwritten_projection() -> (
    None
):
    snapshot = ASSET_ROOT / "runner_team_event_schema.json"
    raw = _live_schema_bytes()

    assert snapshot.read_bytes() == raw
    schema = json.loads(raw)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == schema["title"]


def test_combined_receipt_binds_identity_provider_and_runner_contract() -> None:
    identity = _identity_module().IDENTITY
    receipt = _json(ASSET_ROOT / "instrument_qualification_receipt.json")
    schema_raw = (ASSET_ROOT / "runner_team_event_schema.json").read_bytes()
    live_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=RUNNER_WORKTREE,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    live_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=RUNNER_WORKTREE,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    assert receipt["experiment_id"] == identity.experiment_id
    assert receipt["run_id"] == identity.run_id
    assert receipt["identity_sha256"] == identity.identity_sha256
    assert receipt["provider_model"] == identity.provider_model
    assert receipt["runner_contract"]["runner"]["head"] == live_head == RUNNER_HEAD
    assert (
        receipt["runner_contract"]["runner"]["branch"] == live_branch == RUNNER_BRANCH
    )
    assert receipt["runner_contract"]["runner"]["clean"] is True
    assert Path(receipt["runner_contract"]["runner"]["interpreter"]).samefile(
        RUNNER_PYTHON
    )
    assert (
        receipt["runner_contract"]["schema"]["raw_sha256"]
        == hashlib.sha256(schema_raw).hexdigest()
    )
    assert receipt["runner_contract"]["checks"]["scratch_formal_non_alias"] is True
    assert len(receipt["receipt_sha256"]) == 64


def test_e2e4_assets_contain_no_predecessor_identity_literal() -> None:
    checked = [
        path
        for path in ASSET_ROOT.iterdir()
        if path.is_file() and path.suffix in {".py", ".json"}
    ]

    assert {
        "__init__.py",
        "identity.py",
        "instrument_qualification_receipt.json",
        "provider_responses.json",
        "request_template.json",
        "runner_team_event_schema.json",
    } <= {path.name for path in checked}
    for path in checked:
        assert PREDECESSOR_IDENTITY.search(path.read_bytes()) is None, path


def test_e2e1_e2e2_e2e3_assets_remain_unchanged_since_e2e3_adjudication() -> None:
    adjudication_commit = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "--",
            "docs/research/SPINE-E2E-3-result.md",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    historical_paths = [
        path.relative_to(REPO_ROOT)
        for sequence in (1, 2, 3)
        for path in (REPO_ROOT / f"product_evals/spine_e2e_{sequence}").iterdir()
        if path.is_file()
    ]

    assert adjudication_commit
    for path in historical_paths:
        result = subprocess.run(
            ["git", "diff", "--quiet", adjudication_commit, "--", str(path)],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, path


def test_successor_python_keeps_numbered_identity_in_identity_module_only() -> None:
    numbered = re.compile(rb"(?:spine-e2e-4|SPINE-E2E-4|spine_e2e_4|SPINE_E2E_4)")

    for path in ASSET_ROOT.glob("*.py"):
        if path.name == "identity.py":
            continue
        assert numbered.search(path.read_bytes()) is None, path
