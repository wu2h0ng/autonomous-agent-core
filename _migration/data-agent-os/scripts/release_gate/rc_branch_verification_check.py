from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


DEFAULT_RECORD_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "decisions"
    / "PR-15-controlled-pilot-rc-branch-20260704.md"
)

FULL_HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _extract_backtick_field(record_text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*`([^`]+)`\s*$", record_text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing record field: {label}")
    return match.group(1)


def _validate_hash(label: str, value: str) -> None:
    if not FULL_HASH_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full 40-character commit hash.")


def _parse_remote_refs(ref_text: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for raw_line in ref_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"invalid remote ref line: {raw_line}")
        refs[parts[1]] = parts[0]
    return refs


def _git_ls_remote(remote: str, *patterns: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", remote, *patterns],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "git ls-remote failed")
    return result.stdout


def _load_ref_text(path: Path | None, remote: str, *patterns: str) -> str:
    if path is not None:
        return path.read_text(encoding="utf-8")
    return _git_ls_remote(remote, *patterns)


def check_rc_branch_verification(
    record_file: Path,
    remote: str = "origin",
    heads_file: Path | None = None,
    tags_file: Path | None = None,
) -> tuple[int, str]:
    try:
        if not record_file.exists():
            raise ValueError(f"record file missing: {record_file}")
        record_text = record_file.read_text(encoding="utf-8")
        verified_head = _extract_backtick_field(record_text, "Verified local head")
        rc_branch = _extract_backtick_field(record_text, "RC branch")
        rc_branch_head = _extract_backtick_field(record_text, "RC branch head")
        remote_main_head = _extract_backtick_field(record_text, "Remote main head")
        if not rc_branch.startswith("rc/"):
            raise ValueError("RC branch must use refs/heads/rc/* naming.")
        _validate_hash("Verified local head", verified_head)
        _validate_hash("RC branch head", rc_branch_head)
        _validate_hash("Remote main head", remote_main_head)

        heads_text = _load_ref_text(
            heads_file, remote, f"refs/heads/{rc_branch}", "refs/heads/main"
        )
        heads = _parse_remote_refs(heads_text)
        actual_rc_head = heads.get(f"refs/heads/{rc_branch}")
        if actual_rc_head != rc_branch_head:
            return (
                2,
                f"RC branch head mismatch: expected {rc_branch_head}, got {actual_rc_head or 'missing'}.",
            )
        actual_main_head = heads.get("refs/heads/main")
        if actual_main_head != remote_main_head:
            return (
                2,
                f"Remote main head mismatch: expected {remote_main_head}, got {actual_main_head or 'missing'}.",
            )

        tags_text = _load_ref_text(tags_file, remote, "refs/tags/*")
        tags = _parse_remote_refs(tags_text)
        forbidden_heads = {verified_head, rc_branch_head}
        release_tag_refs = [
            ref
            for ref, commit in tags.items()
            if commit in forbidden_heads
            and (ref.startswith("refs/tags/release") or ref.startswith("refs/tags/rc"))
        ]
        if release_tag_refs:
            return (
                2,
                f"RC branch verification failed: release tag exists for candidate: {release_tag_refs[0]}",
            )
    except ValueError as exc:
        return 2, f"RC branch verification failed: {exc}"

    return (
        0,
        f"RC branch verification passed: {rc_branch} @ {rc_branch_head}; origin/main @ {remote_main_head}; no release/rc tag.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the controlled-pilot RC branch record against remote refs."
    )
    parser.add_argument(
        "--record-file",
        type=Path,
        default=DEFAULT_RECORD_FILE,
        help="Markdown record containing RC branch and remote main heads.",
    )
    parser.add_argument("--remote", default="origin", help="Git remote to inspect.")
    parser.add_argument(
        "--heads-file",
        type=Path,
        help="Optional test fixture containing git ls-remote --heads output.",
    )
    parser.add_argument(
        "--tags-file",
        type=Path,
        help="Optional test fixture containing git ls-remote --tags output.",
    )
    args = parser.parse_args(argv)

    status, message = check_rc_branch_verification(
        args.record_file,
        remote=args.remote,
        heads_file=args.heads_file,
        tags_file=args.tags_file,
    )
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
