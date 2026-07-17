"""Read immutable historical candidate bytes without checking out old code."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path


def git_blob(repo_root: Path, reference_head: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{reference_head}:{relative_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"historical blob unavailable: {reference_head}:{relative_path}"
        )
    return completed.stdout


def materialize_git_files(
    repo_root: Path,
    reference_head: str,
    relative_paths: Iterable[str],
    destination: Path,
) -> Path:
    for relative_path in relative_paths:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_blob(repo_root, reference_head, relative_path))
    return destination
