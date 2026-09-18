from __future__ import annotations

import argparse
import sys

from .eval_hub import EvalThresholdReporter, outcomes_from_json, thresholds_from_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an eval threshold report.")
    parser.add_argument("--thresholds-json", required=True)
    parser.add_argument("--outcomes-json", required=True)
    args = parser.parse_args(argv)

    report = EvalThresholdReporter(thresholds_from_json(args.thresholds_json)).build(
        outcomes_from_json(args.outcomes_json)
    )
    print(report.to_json())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
