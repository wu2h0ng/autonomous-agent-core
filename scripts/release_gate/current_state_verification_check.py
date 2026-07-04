from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import yaml


VERIFIED_HEAD_RE = re.compile(r"Verified local head:\s*`([0-9a-fA-F]{7,40})`")


def _git_is_available(repo_root: Path) -> bool:
    return (repo_root / ".git").exists()


def _is_ancestor(repo_root: Path, ancestor: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _load_current_state(repo_root: Path) -> dict:
    current_state = repo_root / "docs" / "CURRENT_STATE.yaml"
    if not current_state.exists():
        raise ValueError(f"CURRENT_STATE missing: {current_state}")
    data = yaml.safe_load(current_state.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("CURRENT_STATE is not a YAML mapping.")
    return data


def check_current_state_verification(repo_root: Path) -> tuple[int, str]:
    try:
        data = _load_current_state(repo_root)
        tests_source = data["last_verified_tests"]["source"]
        eval_source = data["last_verified_eval"]["source"]
    except (KeyError, TypeError, ValueError) as exc:
        return 2, f"CURRENT_STATE verification source invalid: {exc}"

    if tests_source != eval_source:
        return 2, "CURRENT_STATE verification source mismatch between tests and eval."

    source_path = repo_root / tests_source
    if not source_path.exists():
        return 2, f"CURRENT_STATE verification source missing: {tests_source}"

    source_text = source_path.read_text(encoding="utf-8")
    match = VERIFIED_HEAD_RE.search(source_text)
    if not match:
        return 2, f"CURRENT_STATE verification source has no verified head: {tests_source}"

    verified_head = match.group(1)
    if _git_is_available(repo_root) and not _is_ancestor(repo_root, verified_head):
        return (
            2,
            f"CURRENT_STATE verified head is not an ancestor of HEAD: {verified_head}",
        )

    return (
        0,
        f"CURRENT_STATE verification source check passed: {tests_source} @ {verified_head}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed check for CURRENT_STATE verification source freshness."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root containing docs/CURRENT_STATE.yaml.",
    )
    args = parser.parse_args(argv)

    status, message = check_current_state_verification(args.repo_root.resolve())
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
