from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_os_contracts import BenchmarkTaskValidationError
from agent_os_core import (
    BASELINE_DIFF_INVALID,
    BASELINE_DIFF_REJECTED,
    CHEAP_BASELINE_DIFF_MAX_BYTES,
    apply_unified_diff,
    validate_unified_diff,
)

GOOD_DIFF = """\
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,3 @@
 context
-old
+new
 tail
"""

GOOD_GIT_DIFF = """\
diff --git a/src/module.py b/src/module.py
index 1111111..2222222 100644
--- a/src/module.py
+++ b/src/module.py
@@ -1,3 +1,3 @@
 context
-old
+new
 tail
"""

TWO_FILE_DIFF = """\
--- a/one.py
+++ b/one.py
@@ -1,1 +1,1 @@
-a
+b
--- a/two.py
+++ b/two.py
@@ -1,1 +1,1 @@
-c
+d
"""

NO_HUNK_DIFF = """\
--- a/src/module.py
+++ b/src/module.py
"""

ABSOLUTE_PATH_DIFF = """\
--- /etc/module.py
+++ b/src/module.py
@@ -1,1 +1,1 @@
-a
+b
"""

NEW_FILE_DIFF = """\
--- /dev/null
+++ b/src/module.py
@@ -0,0 +1,1 @@
+a
"""

PARENT_SEGMENT_DIFF = """\
--- a/../evil.py
+++ b/../evil.py
@@ -1,1 +1,1 @@
-a
+b
"""

MISMATCHED_PATH_DIFF = """\
--- a/one.py
+++ b/other.py
@@ -1,1 +1,1 @@
-a
+b
"""


def _assert_invalid_diff(diff_text: str) -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        validate_unified_diff(diff_text)
    assert excinfo.value.code == BASELINE_DIFF_INVALID


def test_validate_unified_diff_accepts_single_file_diff() -> None:
    validate_unified_diff(GOOD_DIFF)
    validate_unified_diff(GOOD_GIT_DIFF)


def test_validate_unified_diff_rejects_two_file_diff() -> None:
    _assert_invalid_diff(TWO_FILE_DIFF)


def test_validate_unified_diff_rejects_diff_without_hunks() -> None:
    _assert_invalid_diff(NO_HUNK_DIFF)


def test_validate_unified_diff_rejects_absolute_paths() -> None:
    _assert_invalid_diff(ABSOLUTE_PATH_DIFF)
    _assert_invalid_diff(NEW_FILE_DIFF)


def test_validate_unified_diff_rejects_parent_segments() -> None:
    _assert_invalid_diff(PARENT_SEGMENT_DIFF)


def test_validate_unified_diff_rejects_mismatched_paths() -> None:
    _assert_invalid_diff(MISMATCHED_PATH_DIFF)


def test_validate_unified_diff_rejects_oversized_diff() -> None:
    lines = 9000
    diff = (
        "--- a/src/module.py\n"
        "+++ b/src/module.py\n"
        f"@@ -1,{lines} +1,{lines} @@\n"
        + " context\n" * lines
    )
    assert len(diff.encode("utf-8")) > CHEAP_BASELINE_DIFF_MAX_BYTES
    _assert_invalid_diff(diff)


def test_validate_unified_diff_rejects_truncated_hunk() -> None:
    _assert_invalid_diff(
        "--- a/src/module.py\n"
        "+++ b/src/module.py\n"
        "@@ -1,2 +1,2 @@\n"
        " context\n"
    )


def test_apply_unified_diff_check_failure_never_applies(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path, input: str
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, "", "error: patch failed")

    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        apply_unified_diff(tmp_path, GOOD_DIFF, runner=runner)
    assert excinfo.value.code == BASELINE_DIFF_REJECTED
    assert "error: patch failed" in excinfo.value.detail
    assert calls == [["git", "apply", "--check"]]


def test_apply_unified_diff_runs_check_then_apply_in_order(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, str]] = []

    def runner(
        argv: list[str], *, cwd: Path, input: str
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), cwd, input))
        return subprocess.CompletedProcess(argv, 0, "", "")

    apply_unified_diff(tmp_path, GOOD_DIFF, runner=runner)
    assert calls == [
        (["git", "apply", "--check"], tmp_path, GOOD_DIFF),
        (["git", "apply"], tmp_path, GOOD_DIFF),
    ]


def test_apply_unified_diff_validates_before_running(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(
        argv: list[str], *, cwd: Path, input: str
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        apply_unified_diff(tmp_path, "not a unified diff", runner=runner)
    assert excinfo.value.code == BASELINE_DIFF_INVALID
    assert calls == []
