from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_DECISION_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "decisions"
    / "PR-10-deployment-push-hold-decision-20260704.md"
)

AUTHORIZED_TOKEN = "DEPLOYMENT_PUSH: AUTHORIZED"
HOLD_TOKEN = "DEPLOYMENT_PUSH: HOLD"


def check_push_authorization(
    decision_file: Path, expected_head: str | None = None
) -> tuple[int, str]:
    if not decision_file.exists():
        return (
            2,
            f"DEPLOYMENT_PUSH: UNKNOWN - decision file missing: {decision_file}",
        )

    decision_text = decision_file.read_text(encoding="utf-8")
    has_authorized = AUTHORIZED_TOKEN in decision_text
    has_hold = HOLD_TOKEN in decision_text
    if has_authorized and has_hold:
        return (
            2,
            "DEPLOYMENT_PUSH: UNKNOWN - ambiguous decision tokens; push is not authorized.",
        )
    if has_authorized:
        if expected_head:
            expected_line = f"candidate_head: {expected_head}"
            if expected_line not in decision_text:
                return (
                    2,
                    f"{AUTHORIZED_TOKEN} - candidate head mismatch; expected {expected_line}.",
                )
            return 0, f"{AUTHORIZED_TOKEN} - {expected_line} - push authorization check passed."
        return 0, f"{AUTHORIZED_TOKEN} - push authorization check passed."
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
        help="Optional candidate commit hash that must be named as candidate_head.",
    )
    args = parser.parse_args(argv)

    status, message = check_push_authorization(args.decision_file, expected_head=args.expected_head)
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
