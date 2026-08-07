from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol

from agent_os_contracts import BenchmarkTaskValidationError


BASELINE_DIFF_INVALID = "BASELINE_DIFF_INVALID"
BASELINE_DIFF_REJECTED = "BASELINE_DIFF_REJECTED"

CHEAP_BASELINE_DIFF_MAX_BYTES = 65536


def extract_unified_diff(text: str) -> str | None:
    """Locate the unified diff in provider output; deterministic, no repair.

    From the first line starting with '--- ' through EOF, with trailing
    markdown fence lines dropped (fenced and raw output both resolve).
    Returns None when no diff header exists. Shared by the cheap baseline
    CLI and the governed diff-mode provider node (ADR-0059).
    """

    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith("--- ")),
        None,
    )
    if start is None:
        return None
    body = lines[start:]
    while body and body[-1].strip().startswith("```"):
        body.pop()
    return "\n".join(body) + "\n"
"""Fail-closed cap on one-shot baseline diff output (64 KiB).

Comfortably above the largest legitimate single-file diff inside the 19,000
byte gold-file envelope (a full rewrite with context is ~2x the file) while
bounding malformed or runaway provider output before git ever sees it.
"""

_HUNK_HEADER_PATTERN = re.compile(
    r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?"
)


class GitApplyRunner(Protocol):
    """Subprocess-like callable injected for the fail-closed git apply steps."""

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        input: str,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_git_apply(
    argv: list[str],
    *,
    cwd: Path,
    input: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        check=False,
    )


def validate_unified_diff(diff_text: str) -> None:
    """Fail closed unless diff_text is a plausible single-file unified diff.

    Required: exactly one '--- '/'+++ ' header pair naming the same single
    relative path, at least one well-formed '@@' hunk whose body line counts
    match the header ranges, no content introducing a second file, no
    absolute paths, no '..' segments and a total size within
    CHEAP_BASELINE_DIFF_MAX_BYTES.
    """

    if not isinstance(diff_text, str) or not diff_text.strip():
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff text is required",
        )
    if len(diff_text.encode("utf-8")) > CHEAP_BASELINE_DIFF_MAX_BYTES:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff exceeds {CHEAP_BASELINE_DIFF_MAX_BYTES} bytes",
        )
    old_path: str | None = None
    new_path: str | None = None
    file_path: str | None = None
    hunks = 0
    old_pending = 0
    new_pending = 0
    for line in diff_text.splitlines():
        if old_pending or new_pending:
            old_pending, new_pending = _consume_hunk_line(
                line, old_pending, new_pending
            )
            continue
        hunk = _HUNK_HEADER_PATTERN.fullmatch(line)
        if hunk is not None:
            hunks += 1
            old_pending = int(hunk.group(2) or "1")
            new_pending = int(hunk.group(4) or "1")
            continue
        if line.startswith("diff --git "):
            git_old, git_new = _parse_git_header(line)
            file_path = _bind_single_path(file_path, git_old)
            file_path = _bind_single_path(file_path, git_new)
            continue
        if line.startswith("index "):
            continue
        if line.startswith("--- "):
            if old_path is not None or new_path is not None:
                raise BenchmarkTaskValidationError(
                    BASELINE_DIFF_INVALID,
                    "baseline diff introduces a second file",
                )
            old_path = _parse_file_header(line[4:], "---")
            file_path = _bind_single_path(file_path, old_path)
            continue
        if line.startswith("+++ "):
            if old_path is None or new_path is not None:
                raise BenchmarkTaskValidationError(
                    BASELINE_DIFF_INVALID,
                    "baseline diff has a '+++' header without a '---' header",
                )
            new_path = _parse_file_header(line[4:], "+++")
            file_path = _bind_single_path(file_path, new_path)
            continue
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff has unexpected content outside hunks: {line!r}",
        )
    if old_pending or new_pending:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff ends inside a truncated hunk",
        )
    if old_path is None or new_path is None:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff requires '---' and '+++' file headers",
        )
    if old_path != new_path:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff headers must name the same single file",
        )
    if hunks == 0:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff requires at least one '@@' hunk",
        )


def apply_unified_diff(
    repo_root: Path,
    diff_text: str,
    *,
    runner: GitApplyRunner = _run_git_apply,
) -> None:
    """Apply a validated single-file diff via git, fail closed.

    Runs ``git apply --check`` first; any failure raises
    BenchmarkTaskValidationError (BASELINE_DIFF_REJECTED) with the git stderr
    detail and the apply step never runs. Malformed diffs are rejected before
    git is invoked at all (ADR-0056 decision 4: no human repair).
    """

    validate_unified_diff(diff_text)
    check = runner(["git", "apply", "--check"], cwd=repo_root, input=diff_text)
    if check.returncode != 0:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_REJECTED,
            "git apply --check rejected baseline diff: " + _stderr_detail(check),
        )
    applied = runner(["git", "apply"], cwd=repo_root, input=diff_text)
    if applied.returncode != 0:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_REJECTED,
            "git apply failed after a clean check: " + _stderr_detail(applied),
        )


def _consume_hunk_line(
    line: str,
    old_pending: int,
    new_pending: int,
) -> tuple[int, int]:
    if line.startswith("\\"):
        return old_pending, new_pending
    prefix = line[:1]
    if prefix == " ":
        old_pending -= 1
        new_pending -= 1
    elif prefix == "-":
        old_pending -= 1
    elif prefix == "+":
        new_pending -= 1
    else:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff hunk body line is malformed: {line!r}",
        )
    if old_pending < 0 or new_pending < 0:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff hunk body exceeds its header ranges",
        )
    return old_pending, new_pending


def _parse_git_header(line: str) -> tuple[str, str]:
    parts = line[len("diff --git ") :].split(" ")
    if (
        len(parts) != 2
        or not parts[0].startswith("a/")
        or not parts[1].startswith("b/")
    ):
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff has a malformed diff --git header: {line!r}",
        )
    old = _require_safe_relative_path(parts[0][2:], "diff --git")
    new = _require_safe_relative_path(parts[1][2:], "diff --git")
    if old != new:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff diff --git header must name one single file",
        )
    return old, new


def _parse_file_header(raw: str, marker: str) -> str:
    token = raw.split("\t")[0]
    if token != token.strip():
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff '{marker}' header path has stray whitespace",
        )
    path = token[2:] if token.startswith(("a/", "b/")) else token
    return _require_safe_relative_path(path, marker)


def _require_safe_relative_path(path: str, source: str) -> str:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(char.isspace() for char in path)
        or any(segment in ("", ".", "..") for segment in path.split("/"))
    ):
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            f"baseline diff {source} path is not a safe relative path: {path!r}",
        )
    return path


def _bind_single_path(bound: str | None, path: str) -> str:
    if bound is not None and bound != path:
        raise BenchmarkTaskValidationError(
            BASELINE_DIFF_INVALID,
            "baseline diff must target exactly one file",
        )
    return path


def _stderr_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or "").strip()
    return detail if detail else f"exit code {result.returncode}"
