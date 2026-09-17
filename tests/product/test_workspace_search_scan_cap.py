"""``workspace.search`` must say *why* it stopped, not only *that* it stopped.

The grep branch collapsed three unrelated caps into a single ``truncated: true``:
the match cap, the returned-text cap and the file scan cap. In a workspace with
more scannable files than the scan cap, a unique match beyond the cap returned
``{"matches": [], "truncated": true}`` -- an empty match list that reads exactly
like a completed search which found nothing.

These tests pin the machine-readable report: ``truncated_reason`` names the cap
that stopped the search, and the scan-cap case reports how much of the walk was
never searched. They fail on the previous behaviour because ``truncated_reason``,
``scanned_files`` and ``unexamined_paths`` did not exist, so a consumer could not
tell "searched everything, no match" from "stopped early, may not have looked".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from agent_os_contracts import ActionContract, CorrectionEpochVector, ResourceBudget

from domain_packs.developer_agent import DeveloperWorkspaceAdapter

SCAN_CAP = DeveloperWorkspaceAdapter._SEARCH_MAX_SCANNED_FILES
RESULT_CAP = DeveloperWorkspaceAdapter._SEARCH_MAX_RESULTS
OUTPUT_CAP = DeveloperWorkspaceAdapter._SEARCH_MAX_OUTPUT_CHARS
NEEDLE = "SCAN_CAP_NEEDLE_SENTINEL"


def _search(
    adapter: DeveloperWorkspaceAdapter, arguments: dict[str, object]
) -> dict[str, Any]:
    action = ActionContract(
        action_id="action:search-scan-cap",
        task_id="task:search-scan-cap",
        run_id="run:search-scan-cap",
        node_id="node:search-scan-cap",
        principal_id="principal:search-scan-cap",
        tenant_id="tenant:search-scan-cap",
        workspace_id="workspace:search-scan-cap",
        capability_id="workspace.search",
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=1,
        idempotency_key="idempotency:search-scan-cap",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=120,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:search-scan-cap",
        candidate_envelope_id="envelope:search-scan-cap",
        created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    return cast("dict[str, Any]", adapter.execute(action).output)


def _workspace_with_files(tmp_path: Path, count: int) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(count):
        (workspace / f"f{index:05d}.txt").write_text(
            f"filler line {index}\n", encoding="utf-8"
        )
    return workspace


def test_scan_cap_is_reported_with_the_unsearched_remainder(tmp_path: Path) -> None:
    total = SCAN_CAP + 500
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)
    last = sorted(workspace.glob("*.txt"))[-1]
    last.write_text(f"filler\n{NEEDLE}\n", encoding="utf-8")

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert result["matches"] == []
    assert result["truncated"] is True
    # Not the match cap and not the text cap: the walk itself stopped early.
    assert result["truncated_reason"] == "scan_cap"
    assert result["scanned_files"] == SCAN_CAP
    # Exact count of enumerated paths whose contents were never searched.
    assert result["unexamined_paths"] == total - SCAN_CAP
    assert result["scanned_files"] + result["unexamined_paths"] == total
    # The empty match list must never be readable as a completed search.
    assert not (result["matches"] == [] and result["truncated_reason"] is None)


def test_completed_scan_reports_no_truncation_and_the_full_file_count(
    tmp_path: Path,
) -> None:
    total = 40
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert result["matches"] == []
    assert result["truncated"] is False
    assert result["truncated_reason"] is None
    assert result["scanned_files"] == total
    assert result["unexamined_paths"] == 0


def test_result_cap_is_distinguished_from_scan_cap(tmp_path: Path) -> None:
    total = RESULT_CAP + 50
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)
    for path in workspace.glob("*.txt"):
        path.write_text(f"{NEEDLE}\n", encoding="utf-8")

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert len(result["matches"]) == RESULT_CAP
    assert result["truncated"] is True
    assert result["truncated_reason"] == "result_cap"
    assert result["scanned_files"] == RESULT_CAP
    assert result["scanned_files"] + result["unexamined_paths"] == total


def test_output_cap_is_distinguished_from_the_other_caps(tmp_path: Path) -> None:
    long_line = "x" * 500
    total = 60
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)
    for path in workspace.glob("*.txt"):
        path.write_text(f"{long_line}{NEEDLE}\n", encoding="utf-8")

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    # The walk finished; only the returned text was trimmed.
    assert result["scanned_files"] == total
    assert result["unexamined_paths"] == 0
    assert len(result["matches"]) < total
    assert len("".join(result["matches"])) <= OUTPUT_CAP
    assert result["truncated"] is True
    assert result["truncated_reason"] == "output_cap"


def test_glob_and_ls_report_the_result_cap_reason(tmp_path: Path) -> None:
    total = RESULT_CAP + 10
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)

    glob_result = _search(adapter, {"mode": "glob", "pattern": "*.txt"})
    assert len(glob_result["matches"]) == RESULT_CAP
    assert glob_result["truncated"] is True
    assert glob_result["truncated_reason"] == "result_cap"

    ls_result = _search(adapter, {"mode": "ls"})
    assert len(ls_result["entries"]) == RESULT_CAP
    assert ls_result["truncated"] is True
    assert ls_result["truncated_reason"] == "result_cap"


def test_small_glob_and_ls_report_no_truncation_reason(tmp_path: Path) -> None:
    workspace = _workspace_with_files(tmp_path, 5)
    adapter = DeveloperWorkspaceAdapter(workspace)

    glob_result = _search(adapter, {"mode": "glob", "pattern": "*.txt"})
    assert len(glob_result["matches"]) == 5
    assert glob_result["truncated"] is False
    assert glob_result["truncated_reason"] is None

    ls_result = _search(adapter, {"mode": "ls"})
    assert ls_result["truncated"] is False
    assert ls_result["truncated_reason"] is None


def test_diagnostics_precede_the_payload_in_the_serialized_result(
    tmp_path: Path,
) -> None:
    total = RESULT_CAP + 10
    workspace = _workspace_with_files(tmp_path, total)
    adapter = DeveloperWorkspaceAdapter(workspace)
    for path in workspace.glob("*.txt"):
        path.write_text(f"{NEEDLE}\n", encoding="utf-8")

    grep_result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})
    glob_result = _search(adapter, {"mode": "glob", "pattern": "*.txt"})
    ls_result = _search(adapter, {"mode": "ls"})

    # The chat loop replaces any tool result longer than its 8000-char budget
    # with a raw preview of the serialized JSON, so a reason serialized after
    # the payload is cut off exactly when the payload is largest.
    grep_rendered = json.dumps(grep_result)
    assert grep_rendered.index('"truncated_reason"') < grep_rendered.index('"matches"')
    glob_rendered = json.dumps(glob_result)
    assert glob_rendered.index('"truncated_reason"') < glob_rendered.index('"matches"')
    ls_rendered = json.dumps(ls_result)
    assert ls_rendered.index('"truncated_reason"') < ls_rendered.index('"entries"')
