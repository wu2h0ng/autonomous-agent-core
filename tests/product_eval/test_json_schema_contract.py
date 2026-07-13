"""Contract tests for the pinned workflow-runner TeamEvent schema consumer."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from product_evals.common.bank_generator import canonical_json_bytes
from product_evals.common.json_schema_contract import (
    canonical_schema_sha256,
    normalize_timestamped_record,
    validate_closed_record,
)


RUNNER_WORKTREE = Path(
    "/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow/"
    ".worktrees/team-event-contract-v1-20260713"
)
RUNNER_BRANCH = "codex/team-event-contract-v1-20260713"
RUNNER_HEAD = "087f5907cd181c6e071fb24f135292abd9681ca7"
RUNNER_PYTHON = Path(
    "/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow/"
    ".venv/bin/python"
)


def _runner_subprocess(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RUNNER_PYTHON), *args],
        cwd=RUNNER_WORKTREE,
        env={**os.environ, "PYTHONPATH": str(RUNNER_WORKTREE / "src")},
        check=True,
        text=True,
        capture_output=True,
    )


def _assert_pinned_runner_identity() -> None:
    actual_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=RUNNER_WORKTREE,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    actual_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=RUNNER_WORKTREE,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=RUNNER_WORKTREE,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    interpreter = _runner_subprocess(
        "-c", "import sys; print(sys.executable)"
    ).stdout.strip()

    assert actual_branch == RUNNER_BRANCH
    assert actual_head == RUNNER_HEAD
    assert dirty == ""
    assert Path(interpreter) == RUNNER_PYTHON


def _live_schema() -> dict[str, Any]:
    _assert_pinned_runner_identity()
    completed = _runner_subprocess(
        "-m",
        "agent_workflow_runner.cli",
        "team",
        "event-schema",
    )
    exported = json.loads(completed.stdout)
    assert isinstance(exported, dict)
    return exported


def _governed_record(**overrides: Any) -> dict[str, Any]:
    _assert_pinned_runner_identity()
    completed = _runner_subprocess(
        "-c",
        "\n".join(
            [
                "import json",
                "from agent_workflow_runner.team_event_contract import "
                "build_team_event_record",
                "record = build_team_event_record(",
                "    ts='2026-07-13T10:00:00+00:00',",
                "    event_type='TASK_ASSIGNED',",
                "    agent_id='codex',",
                "    task_id='spine-e2e-4-contract-canary',",
                "    summary='exercise the pinned TeamEvent contract',",
                "    artifact='quality_report.md',",
                "    stream_file=None,",
                "    permission_action='team.event.record',",
                "    approval_request_id='approval-spine-e2e-4-contract-canary',",
                "    evidence_refs=['quality_report.md'],",
                "    source_evidence_refs=['goal_card.md', 'quality_report.md'],",
                "    source_decision_id='decision-spine-e2e-4',",
                "    source_goal_id='goal-spine-e2e-4',",
                "    source_decision_type='contract-review',",
                ")",
                "print(json.dumps(record, sort_keys=True))",
            ]
        ),
    )
    record = json.loads(completed.stdout)
    assert isinstance(record, dict)
    record.update(overrides)
    return record


def _extra_field(record: dict[str, Any]) -> None:
    record["unexpected_consumer_field"] = "must fail closed"


def _missing_schema_version(record: dict[str, Any]) -> None:
    record.pop("schema_version")


def _unknown_event_type(record: dict[str, Any]) -> None:
    record["type"] = "UNKNOWN_TEAM_EVENT_TYPE"


def _empty_approval_id(record: dict[str, Any]) -> None:
    record["approval_request_id"] = ""


def _mutated_schema_version(record: dict[str, Any]) -> None:
    record["schema_version"] = "team-event-v2"


def _non_string_evidence(record: dict[str, Any]) -> None:
    record["evidence_refs"] = ["quality_report.md", 7]


@pytest.mark.parametrize(
    "mutation",
    [
        _extra_field,
        _missing_schema_version,
        _unknown_event_type,
        _empty_approval_id,
        _mutated_schema_version,
        _non_string_evidence,
    ],
    ids=[
        "extra-field",
        "missing-schema-version",
        "unknown-event-type",
        "empty-approval-id",
        "mutated-schema-version",
        "non-string-evidence-item",
    ],
)
def test_live_schema_rejects_invalid_event_mutations(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    schema = _live_schema()
    record = _governed_record()
    mutation(record)

    with pytest.raises(ValueError):
        validate_closed_record(record, schema)


@pytest.mark.parametrize(
    "source_field",
    ["source_decision_id", "source_goal_id", "source_decision_type"],
)
def test_live_schema_rejects_slash_in_source_binding(source_field: str) -> None:
    schema = _live_schema()
    record = _governed_record()
    record[source_field] = "invalid/source-token"

    with pytest.raises(ValueError):
        validate_closed_record(record, schema)


def test_live_schema_accepts_conformant_governed_event() -> None:
    validate_closed_record(_governed_record(), _live_schema())


def test_validator_rejects_unsupported_schema_keyword() -> None:
    schema = _live_schema()
    schema["properties"]["summary"]["description"] = "unsupported annotation"

    with pytest.raises(ValueError):
        validate_closed_record(_governed_record(), schema)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda schema: schema.update(additionalProperties=True),
        lambda schema: schema.update(additionalProperties={}),
        lambda schema: schema.pop("additionalProperties"),
        lambda schema: schema["properties"]["type"].update(enum="TASK_ASSIGNED"),
        lambda schema: schema["properties"]["agent_id"].update(minLength=-1),
        lambda schema: schema["properties"]["agent_id"].update(type=["string", 7]),
        lambda schema: schema["properties"]["agent_id"].update(pattern=7),
    ],
    ids=[
        "open-root",
        "schema-valued-additional-properties",
        "missing-closed-root-declaration",
        "string-enum",
        "negative-min-length",
        "non-string-type-member",
        "non-string-pattern",
    ],
)
def test_validator_rejects_malformed_or_open_schema_keyword_values(
    mutation: Callable[[dict[str, Any]], Any],
) -> None:
    schema = _live_schema()
    mutation(schema)

    with pytest.raises(ValueError):
        validate_closed_record(_governed_record(), schema)


def test_canonical_schema_sha256_is_order_independent_and_mutation_sensitive() -> None:
    schema = _live_schema()
    reordered = dict(reversed(list(schema.items())))
    expected = hashlib.sha256(canonical_json_bytes(schema)).hexdigest()

    assert canonical_schema_sha256(schema) == expected
    assert canonical_schema_sha256(reordered) == expected

    mutated = copy.deepcopy(schema)
    mutated["properties"]["type"]["enum"].append("UNREVIEWED_EVENT")
    assert canonical_schema_sha256(mutated) != expected


def test_normalization_removes_only_timestamp_and_retains_authority_lineage() -> None:
    schema = _live_schema()
    record = _governed_record()

    normalized = normalize_timestamped_record(record, schema)

    assert normalized == {key: value for key, value in record.items() if key != "ts"}
    assert normalized["source_evidence_refs"] == ["goal_card.md", "quality_report.md"]
    assert normalized["source_decision_id"] == "decision-spine-e2e-4"
    assert normalized["source_goal_id"] == "goal-spine-e2e-4"
    assert normalized["source_decision_type"] == "contract-review"
    assert "ts" in record


def test_normalization_rejects_non_string_source_evidence_item() -> None:
    schema = _live_schema()
    record = _governed_record(source_evidence_refs=["goal_card.md", 7])

    with pytest.raises(ValueError):
        normalize_timestamped_record(record, schema)


def test_normalization_deep_isolates_nested_evidence_lists() -> None:
    schema = _live_schema()
    record = _governed_record()

    normalized = normalize_timestamped_record(record, schema)
    normalized["evidence_refs"].append("normalized-only.md")
    normalized["source_evidence_refs"].append("normalized-source-only.md")

    assert record["evidence_refs"] == ["quality_report.md"]
    assert record["source_evidence_refs"] == ["goal_card.md", "quality_report.md"]
