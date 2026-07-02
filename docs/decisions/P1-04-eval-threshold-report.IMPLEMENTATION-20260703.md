# P1-04 Implementation: Eval Threshold Report

Date: 2026-07-03
Status: BRANCH-LOCAL IMPLEMENTATION VERIFIED - NOT MERGED/PUSHED/RELEASED
Branch: `codex/eval-threshold-report-20260703`
Base: deployment local `main@f56054c`

## Purpose

P1-04 needs eval results to become a reviewable gate artifact, not just a
passing unittest stream. This slice adds a small self-developed report surface
around the existing `EvalThresholdReporter` so release and pilot-readiness
reviews can inspect per-dimension pass rates and fail closed when a threshold is
missed.

## Entry Point

Library:

- `EvalThresholdReport.to_dict()`
- `EvalThresholdReport.to_json()`

Command:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src \
  python -m agent_os_core.eval_hub \
    --thresholds-json '{"intent":1.0,"evidence":1.0}' \
    --outcomes-json '[{"case_id":"gmv_daily","checks":{"intent":true,"evidence":true}}]'
```

The command prints stable JSON with:

- overall `passed`;
- `case_count`;
- per-dimension `passed`, `total`, `threshold`, `pass_rate`, and
  `meets_threshold`;
- explicit `failures`.

Golden eval runner:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors \
  python -m tests.eval.threshold_report \
    --thresholds-file tests/eval/golden_thresholds.json \
    --output .agent_runs/p1-04/golden-threshold-report.json
```

This runner executes the existing `tests/eval/golden_queries.json` cases through
the Trusted Loop and emits the same threshold-report shape to stdout and,
optionally, to a JSON artifact file. It is the first reviewable P1-04 gate
artifact for the current golden query pack.

Reviewable threshold contract:

- `tests/eval/golden_thresholds.json`

The default file currently requires every reported golden-eval dimension to
meet a `1.0` pass rate. The runner also keeps `--thresholds-json` for direct
CLI checks, but `--thresholds-json` and `--thresholds-file` are mutually
exclusive so a gate invocation has one explicit threshold source.

Standard local gate command:

```bash
make eval-threshold-report PYTHON=.venv/bin/python3
```

By default this writes
`.agent_runs/eval-threshold-report/golden-threshold-report.json`. The output path
can be overridden with `EVAL_THRESHOLD_REPORT_OUT=/path/to/report.json`, and the
threshold file can be overridden with
`EVAL_THRESHOLDS_FILE=/path/to/thresholds.json`. `make ci` depends on this target
so the threshold report is now part of the standard local CI path.

## Failure Path

If any required dimension is missing or false, or if an explicit case reason is
present, the report includes failures and the CLI exits nonzero. This makes the
surface usable as a release-gate support command instead of an advisory-only
summary.

## Tests

RED was observed before implementation:

- missing `to_dict` failed the serialization test;
- missing `agent_os_core.eval_hub.__main__` failed the CLI test.

Targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src \
  .venv/bin/python3 -m unittest tests.unit.test_eval_hub -v
```

Result: 6 tests OK before the golden eval runner extension.

Runner extension targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors \
  .venv/bin/python3 -m unittest \
    tests.eval.test_eval \
    tests.unit.test_eval_threshold_report_runner \
    tests.unit.test_eval_hub -v
```

Result: 13 tests OK after adding output-file, fail-closed artifact, Makefile
gate-command coverage, and `make ci` dependency coverage.

Threshold-file extension targeted GREEN:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors \
  .venv/bin/python3 -m unittest \
    tests.eval.test_eval \
    tests.unit.test_eval_threshold_report_runner \
    tests.unit.test_eval_hub -v
```

Result: 14 tests OK after adding reviewable threshold-file wiring.

Full branch verification:

```bash
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- 543 primary unittest tests OK;
- 4 skipped;
- 12 eval tests OK;
- threshold report gate ran inside `make ci`, writing
  `.agent_runs/eval-threshold-report/golden-threshold-report.json` with 5 cases
  and 8 dimensions all meeting the reviewable
  `tests/eval/golden_thresholds.json` 1.0 thresholds;
- OpenAPI contract up to date;
- `=== All CI checks passed ===`;
- `=== Full local CI parity checks passed ===`.

Covered behavior:

- all dimensions meeting thresholds pass;
- missing/failed dimensions produce failures;
- empty outcomes are rejected;
- reports serialize into stable gate-ready dictionaries;
- CLI emits JSON and exits `1` when a threshold report fails.
- boolean threshold JSON values are rejected instead of being treated as `1.0`
  or `0.0`;
- `python -m tests.eval.threshold_report` runs golden queries into a passing
  threshold report;
- `python -m tests.eval.threshold_report --output ...` writes the same JSON
  artifact it prints to stdout;
- a fail-closed golden runner invocation with a missing required dimension exits
  `1` and still writes the failure report JSON artifact;
- `tests/eval/golden_thresholds.json` stores the default reviewable threshold
  contract and is wired through `make eval-threshold-report`;
- `python -m tests.eval.threshold_report --thresholds-file ...` reads
  thresholds from disk, while `--thresholds-file` and `--thresholds-json` are
  mutually exclusive;
- `make eval-threshold-report` writes a valid local gate artifact and supports
  `EVAL_THRESHOLD_REPORT_OUT` and `EVAL_THRESHOLDS_FILE` overrides;
- `make ci` includes `eval-threshold-report` so threshold failure blocks the
  standard local CI path.

## Boundaries

This slice does not:

- replace the existing golden eval tests;
- create production telemetry export or persist reports automatically;
- claim release readiness by itself;
- change SQL Safety, EvidenceChain, Approval, Trace, connectors, or R4/R5
  behavior;
- validate autonomous-core/G10 claims in the product domain.

The eval_hub report consumes explicit eval outcomes. The golden eval runner
constructs those outcomes from the current test golden pack, but it remains a
local gate artifact producer rather than production telemetry or release
automation.
