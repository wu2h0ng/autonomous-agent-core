"""``workspace.search`` must say *why* it stopped, not only *that* it stopped.

The grep branch collapsed three unrelated caps into a single ``truncated: true``:
the match cap, the returned-text cap and the file scan cap. In a workspace with
more scannable files than the scan cap, a unique match beyond the cap returned
``{"matches": [], "truncated": true}`` -- an empty match list that reads exactly
like a completed search which found nothing.

These tests pin the machine-readable report: ``truncated_reason`` names the cap
that stopped the search, and the scan-cap case reports how many files the walk
would read whose contents were never read. They fail on the previous behaviour
because ``truncated_reason``, ``scanned_files`` and ``unexamined_files`` did not
exist, so a consumer could not tell "searched everything, no match" from
"stopped early, may not have looked".

Two counting rules are pinned here because both produced numbers that did not
mean what they looked like:

* ``unexamined_files`` counts *files the walk would read*, under the same
  predicate as the walk, so ``scanned_files + unexamined_files`` is the
  workspace's scannable file total whatever mix of directories, empty
  directories, symlinks, skipped directories and oversized files it contains.
  It is not the number of enumerated paths left in the walk, which would report
  3001 unexamined entries for 1001 files plus 3000 empty directories.
* ``truncated`` means an entry was dropped. The glob branch used to raise it the
  moment the list reached ``_SEARCH_MAX_RESULTS``, so exactly
  ``_SEARCH_MAX_RESULTS`` matches -- a finished walk that lost nothing --
  reported ``result_cap``; the ls branch compares the complete listing with the
  cap and glob now follows the same rule.
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
SKIP_DIRS = DeveloperWorkspaceAdapter._SEARCH_SKIP_DIRS
MAX_FILE_BYTES = 1_000_000
NEEDLE = "SCAN_CAP_NEEDLE_SENTINEL"


def _scannable_files_on_disk(workspace: Path) -> int:
    """Independent recount of the files a grep walk of ``workspace`` would read.

    Written from the documented rule (skip directories, symlinks, oversized
    files and non-files are out) rather than from the adapter's own helper, so
    the assertions compare the payload with the filesystem instead of with a
    hard-coded count that only holds for one workspace shape.
    """

    return sum(
        1
        for path in sorted(workspace.rglob("*"))
        if not any(part in SKIP_DIRS for part in path.parts)
        and not path.is_symlink()
        and path.is_file()
        and path.stat().st_size <= MAX_FILE_BYTES
    )


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
    workspace.mkdir(parents=True)
    for index in range(count):
        (workspace / f"f{index:05d}.txt").write_text(
            f"filler line {index}\n", encoding="utf-8"
        )
    return workspace


def test_scan_cap_is_reported_with_the_unsearched_file_remainder(
    tmp_path: Path,
) -> None:
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
    # Documented meaning: files this walk would read whose contents it never
    # read. Compared with the filesystem rather than a hard-coded sum, so the
    # expectation does not depend on the workspace being flat and searchable.
    on_disk = _scannable_files_on_disk(workspace)
    assert on_disk == total
    assert result["unexamined_files"] == on_disk - SCAN_CAP
    assert result["scanned_files"] + result["unexamined_files"] == on_disk
    # The empty match list must never be readable as a completed search.
    assert not (result["matches"] == [] and result["truncated_reason"] is None)


def test_unexamined_files_are_files_not_the_enumerated_remainder(
    tmp_path: Path,
) -> None:
    """3000 unread directories are not 3000 unsearched files.

    A count of the remaining enumerated paths reported 3001 here -- the one file
    behind the cap plus every directory the walk had left -- so the number could
    not be read as "how much search space is left", which is the only question
    the field exists to answer.
    """

    directory_count = 3000
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(SCAN_CAP + 1):
        (workspace / f"a{index:05d}.txt").write_text(
            f"filler line {index}\n", encoding="utf-8"
        )
    for index in range(directory_count):
        (workspace / f"zdir{index:05d}").mkdir()
    # The only match sits in the file behind the scan cap.
    (workspace / f"a{SCAN_CAP:05d}.txt").write_text(
        f"filler\n{NEEDLE}\n", encoding="utf-8"
    )
    adapter = DeveloperWorkspaceAdapter(workspace)

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert result["matches"] == []
    assert result["truncated_reason"] == "scan_cap"
    assert len(list(workspace.glob("zdir*"))) == directory_count
    assert result["scanned_files"] == SCAN_CAP
    assert result["unexamined_files"] == 1
    on_disk = _scannable_files_on_disk(workspace)
    assert on_disk == SCAN_CAP + 1
    assert result["scanned_files"] + result["unexamined_files"] == on_disk
    # The directories are enumerated paths the walk never entered; they are not
    # search space, and the field must not count them as such. A path count
    # reported 1 + 3000 = 3001 here, which is the number this asserts against.
    assert result["unexamined_files"] != 1 + directory_count


def test_unexamined_files_exclude_paths_the_walk_would_not_read(
    tmp_path: Path,
) -> None:
    """A skipped directory, a symlink, an oversized file and a directory left
    behind the cap are not unread search space."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(SCAN_CAP):
        (workspace / f"a{index:05d}.txt").write_text("filler\n", encoding="utf-8")
    skipped = workspace / "node_modules"
    skipped.mkdir()
    (skipped / "b00000.txt").write_text("filler\n", encoding="utf-8")
    (workspace / "z_big.txt").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    (workspace / "z_link.txt").symlink_to(workspace / "a00000.txt")
    (workspace / "z_dir").mkdir()
    for index in range(4):
        (workspace / f"z{index:05d}.txt").write_text("filler\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(workspace)

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert result["truncated_reason"] == "scan_cap"
    assert result["scanned_files"] == SCAN_CAP
    on_disk = _scannable_files_on_disk(workspace)
    assert on_disk == SCAN_CAP + 4
    assert result["unexamined_files"] == 4
    assert result["scanned_files"] + result["unexamined_files"] == on_disk


def test_agent_state_directory_is_neither_searched_nor_counted(
    tmp_path: Path,
) -> None:
    """The containment rule survives the per-directory resolution cache.

    A state directory whose name is not in the skip list is excluded by
    resolving the path, not by its name, so this is where dropping or
    mis-caching that rule would show: the payload would carry the secret and
    the count would disagree with the files the walk may read.
    """

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = workspace / "state"
    (state / "deep").mkdir(parents=True)
    (state / "deep" / "secret.txt").write_text(f"{NEEDLE}\n", encoding="utf-8")
    (workspace / "plain.txt").write_text(f"{NEEDLE}\n", encoding="utf-8")
    (workspace / "other").mkdir()
    (workspace / "other" / "nested.txt").write_text(f"{NEEDLE}\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(workspace, artifacts=state)

    result = _search(adapter, {"mode": "grep", "pattern": NEEDLE})

    assert sorted(line.split(":", 1)[0] for line in result["matches"]) == [
        "other/nested.txt",
        "plain.txt",
    ]
    assert result["scanned_files"] == 2
    assert result["unexamined_files"] == 0
    assert result["scanned_files"] + result["unexamined_files"] == 2


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
    assert result["unexamined_files"] == 0


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
    # The file that filled the list was read; the 50 behind it were not.
    assert result["unexamined_files"] == total - RESULT_CAP
    assert (
        result["scanned_files"] + result["unexamined_files"]
        == _scannable_files_on_disk(workspace)
    )


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
    assert result["unexamined_files"] == 0
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


def test_exactly_the_result_cap_is_not_reported_as_truncation(tmp_path: Path) -> None:
    """A dropped entry is what ``truncated`` means, so nothing dropped, no cap.

    The glob branch used to set the flag as soon as the match list reached the
    cap, so a walk that had already finished over a tree with exactly
    ``RESULT_CAP`` matches reported ``result_cap`` -- a machine-readable false
    alarm pointing at a result the caller already had in full. The ls branch
    compares the complete listing with the cap; glob follows the same rule, and
    one entry past the cap is still reported.
    """

    exact = _workspace_with_files(tmp_path / "exact", RESULT_CAP)
    exact_adapter = DeveloperWorkspaceAdapter(exact)
    exact_glob = _search(exact_adapter, {"mode": "glob", "pattern": "*.txt"})
    exact_ls = _search(exact_adapter, {"mode": "ls"})

    assert len(exact_glob["matches"]) == RESULT_CAP
    assert exact_glob["truncated"] is False
    assert exact_glob["truncated_reason"] is None
    assert len(exact_ls["entries"]) == RESULT_CAP
    assert exact_ls["truncated"] is False
    assert exact_ls["truncated_reason"] is None

    over = _workspace_with_files(tmp_path / "over", RESULT_CAP + 1)
    over_glob = _search(
        DeveloperWorkspaceAdapter(over), {"mode": "glob", "pattern": "*.txt"}
    )

    assert len(over_glob["matches"]) == RESULT_CAP
    assert over_glob["truncated"] is True
    assert over_glob["truncated_reason"] == "result_cap"


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
