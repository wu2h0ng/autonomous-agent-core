from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml

from current_state_verification_check import check_current_state_verification
from push_authorization_check import DEFAULT_DECISION_FILE, HOLD_TOKEN, check_push_authorization
from rc_branch_verification_check import DEFAULT_RECORD_FILE, check_rc_branch_verification


REQUIRED_IMMEDIATE_NEXT_ID = "deployment-hold-aware-candidate-maintenance"
REQUIRED_BOUNDARY_PHRASES = (
    "Phase-1 controlled-pilot RC branch",
    "do not add more P1 feature slices",
    "push origin/main",
    "create release tags",
    "publish external claims",
)
REQUIRED_BOUNDARY_ALTERNATIVES = (("R4/R5", "R4-R5"),)


def _load_current_state(repo_root: Path) -> dict:
    current_state_path = repo_root / "docs" / "CURRENT_STATE.yaml"
    if not current_state_path.exists():
        raise ValueError(f"CURRENT_STATE missing: {current_state_path}")
    data = yaml.safe_load(current_state_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("CURRENT_STATE is not a YAML mapping.")
    return data


def _current_head(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _check_immediate_next(repo_root: Path) -> tuple[int, str]:
    try:
        current_state = _load_current_state(repo_root)
        immediate_next = current_state["current_stage"]["immediate_next"]
        immediate_next_id = immediate_next["id"]
        description = immediate_next["description"]
    except (KeyError, TypeError, ValueError) as exc:
        return 2, f"controlled pilot readiness failed: immediate_next invalid: {exc}"

    if immediate_next_id != REQUIRED_IMMEDIATE_NEXT_ID:
        return (
            2,
            "controlled pilot readiness failed: immediate_next must remain "
            f"{REQUIRED_IMMEDIATE_NEXT_ID}.",
        )
    if not isinstance(description, str):
        return 2, "controlled pilot readiness failed: immediate_next description must be a string."

    missing = [phrase for phrase in REQUIRED_BOUNDARY_PHRASES if phrase not in description]
    if missing:
        return (
            2,
            "controlled pilot readiness failed: immediate_next is missing required "
            f"boundary phrase: {missing[0]}",
        )
    missing_alternatives = [
        alternatives
        for alternatives in REQUIRED_BOUNDARY_ALTERNATIVES
        if not any(phrase in description for phrase in alternatives)
    ]
    if missing_alternatives:
        return (
            2,
            "controlled pilot readiness failed: immediate_next is missing required "
            f"boundary phrase: {missing_alternatives[0][0]}",
        )
    return 0, "immediate_next candidate-maintenance boundary passed."


def check_controlled_pilot_readiness(
    repo_root: Path,
    decision_file: Path = DEFAULT_DECISION_FILE,
    rc_record_file: Path = DEFAULT_RECORD_FILE,
    remote: str = "origin",
    heads_file: Path | None = None,
    tags_file: Path | None = None,
    expected_head: str | None = None,
) -> tuple[int, str]:
    repo_root = repo_root.resolve()
    expected_head = expected_head or _current_head(repo_root)

    checks: list[tuple[int, str]] = []
    checks.append(check_current_state_verification(repo_root))
    checks.append(_check_immediate_next(repo_root))
    checks.append(
        check_rc_branch_verification(
            rc_record_file,
            remote=remote,
            heads_file=heads_file,
            tags_file=tags_file,
        )
    )

    push_status, push_message = check_push_authorization(
        decision_file,
        expected_head=expected_head,
    )
    if push_status != 2 or HOLD_TOKEN not in push_message:
        checks.append(
            (
                2,
                "controlled pilot readiness failed: push must remain HOLD for "
                f"origin/main promotion; observed: {push_message}",
            )
        )
    else:
        checks.append((0, push_message))

    failures = [message for status, message in checks if status != 0]
    if failures:
        return 2, "\n".join(failures)
    return 0, "controlled pilot readiness passed:\n" + "\n".join(
        f"- {message}" for _, message in checks
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Phase-1 controlled-pilot RC readiness without authorizing main push or release."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root containing docs/CURRENT_STATE.yaml.",
    )
    parser.add_argument(
        "--decision-file",
        type=Path,
        default=DEFAULT_DECISION_FILE,
        help="Deployment push decision record that must remain HOLD.",
    )
    parser.add_argument(
        "--rc-record-file",
        type=Path,
        default=DEFAULT_RECORD_FILE,
        help="Controlled-pilot RC branch record.",
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
    parser.add_argument(
        "--expected-head",
        help="Candidate commit hash used when evaluating the push decision.",
    )
    args = parser.parse_args(argv)

    status, message = check_controlled_pilot_readiness(
        args.repo_root,
        decision_file=args.decision_file,
        rc_record_file=args.rc_record_file,
        remote=args.remote,
        heads_file=args.heads_file,
        tags_file=args.tags_file,
        expected_head=args.expected_head,
    )
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
