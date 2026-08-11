from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_DECISION_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "decisions"
    / "PR-11-deployment-push-authorization-20260705.md"
)

AUTHORIZED_TOKEN = "DEPLOYMENT_PUSH: AUTHORIZED"
HOLD_TOKEN = "DEPLOYMENT_PUSH: HOLD"


def _is_full_commit_hash(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def check_push_authorization(
    decision_file: Path, expected_head: str | None = None
) -> tuple[int, str]:
    if not decision_file.exists():
        return (
            2,
            f"DEPLOYMENT_PUSH: UNKNOWN - decision file missing: {decision_file}",
        )

    decision_text = decision_file.read_text(encoding="utf-8")
    stripped_lines = [line.strip() for line in decision_text.splitlines()]
    decision_token_lines = [
        line for line in stripped_lines if line in {AUTHORIZED_TOKEN, HOLD_TOKEN}
    ]
    has_authorized = AUTHORIZED_TOKEN in decision_token_lines
    has_hold = HOLD_TOKEN in decision_token_lines
    candidate_head_lines = [
        line.strip()
        for line in decision_text.splitlines()
        if line.strip().startswith("candidate_head:")
    ]
    if len(decision_token_lines) != 1 and decision_token_lines:
        return (
            2,
            "DEPLOYMENT_PUSH: UNKNOWN - ambiguous decision token lines; push is not authorized.",
        )
    if has_authorized:
        if not expected_head:
            return (
                2,
                f"{AUTHORIZED_TOKEN} - expected head required; push is not authorized.",
            )
        if not _is_full_commit_hash(expected_head):
            return (
                2,
                f"{AUTHORIZED_TOKEN} - expected head must be a full 40-character commit hash.",
            )
        if len(candidate_head_lines) != 1:
            return (
                2,
                f"{AUTHORIZED_TOKEN} - ambiguous candidate head; expected exactly one candidate_head line.",
            )
        expected_line = f"candidate_head: {expected_head}"
        if candidate_head_lines[0] != expected_line:
            return (
                2,
                f"{AUTHORIZED_TOKEN} - candidate head mismatch; expected {expected_line}.",
            )
        return 0, f"{AUTHORIZED_TOKEN} - {expected_line} - push authorization check passed."
    if has_hold:
        return 2, f"{HOLD_TOKEN} - push is not authorized."
    return (
        2,
        "DEPLOYMENT_PUSH: UNKNOWN - push is not authorized without an explicit decision token.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed deployment push authorization gate.")
    parser.add_argument(
        "--decision-file",
        type=Path,
        default=DEFAULT_DECISION_FILE,
        help="Markdown decision record containing DEPLOYMENT_PUSH token.",
    )
    parser.add_argument(
        "--expected-head",
        help="Candidate commit hash that an AUTHORIZED decision must name as candidate_head.",
    )
    args = parser.parse_args(argv)

    status, message = check_push_authorization(args.decision_file, expected_head=args.expected_head)
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
