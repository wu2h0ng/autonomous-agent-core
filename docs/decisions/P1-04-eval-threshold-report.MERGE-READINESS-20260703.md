# P1-04 Merge Readiness: Eval Threshold Report

Date: 2026-07-03
Status: READY FOR FOUNDER/CTO LOCAL MERGE DECISION - NOT MERGE/PUSH/RELEASE AUTHORIZATION
Branch: `codex/eval-threshold-report-20260703`
Target: deployment local `main`
Target head checked: `main@f56054c`
Implementation head checked before this readiness record: `e652db0`
Readiness metadata note: this packet is docs-only on top of the checked
implementation. The packet commit itself may create a later feature head.
Re-run the fast-forward checks below immediately before any authorized merge,
because either `main` or the feature head may move.

This packet is a merge-decision aid for the P1-04 eval threshold report slice.
It is not merge authorization, not a push request, not a release claim, not
production telemetry export, and not autonomous-core/G10 validation in the
product domain.

## Readiness Verdict

The branch is ready for explicit founder/CTO local merge decision under these
conditions:

1. fast-forward only from deployment local `main@f56054c`;
2. local deployment `main` only;
3. no push, release, PR, or external deployment in the same action;
4. post-merge `make ci` and PostgreSQL `ci-local-full` must pass on local
   `main`;
5. any release/pilot claim must separately review the generated threshold
   artifact and the current golden query coverage.

As checked on 2026-07-03 before writing this docs-only readiness packet,
implementation head `e652db0` was linear on local `main`:

```text
git merge-base --is-ancestor main e652db0
exit 0

git rev-list --left-right --count main...e652db0
0 1
```

Re-run these fast-forward checks against the then-current feature head
immediately before any authorized merge.

## Scope To Merge

The branch adds a branch-local internal eval-gate support surface:

- `EvalThresholdReport` / `EvalDimensionResult` stable JSON serialization;
- `python -m agent_os_core.eval_hub` CLI that consumes explicit
  outcomes/thresholds JSON and exits nonzero when any required dimension is
  missing, false, or below threshold;
- `python -m tests.eval.threshold_report` runner that executes the existing
  golden query pack through the Trusted Loop and emits the same report shape;
- `tests/eval/golden_thresholds.json` as the reviewable default threshold
  contract, currently requiring all eight golden dimensions to pass at `1.0`;
- `make eval-threshold-report` as the standard local gate-artifact command;
- `make ci` dependency wiring so the threshold report blocks the standard local
  CI path before OpenAPI contract verification;
- implementation record and current-state/decision-index documentation.

The changed files relative to local `main@f56054c` are:

```text
Makefile
docs/CURRENT_STATE.yaml
docs/decisions/P1-04-eval-threshold-report.IMPLEMENTATION-20260703.md
docs/decisions/README.md
packages/os_core/src/agent_os_core/__init__.py
packages/os_core/src/agent_os_core/eval_hub/__init__.py
packages/os_core/src/agent_os_core/eval_hub/__main__.py
tests/eval/golden_thresholds.json
tests/eval/test_eval.py
tests/eval/threshold_report.py
tests/unit/test_eval_hub.py
tests/unit/test_eval_threshold_report_runner.py
```

## Coverage

| Requirement | Evidence | Boundary |
|---|---|---|
| Reviewable gate artifact | `make eval-threshold-report` writes `.agent_runs/eval-threshold-report/golden-threshold-report.json` and `python -m tests.eval.threshold_report --output ...` writes the same JSON it prints. | Artifact generation is local gate support, not production telemetry or release automation. |
| Reviewable thresholds | `tests/eval/golden_thresholds.json` is wired through `EVAL_THRESHOLDS_FILE` and `--thresholds-file`; unit tests assert the Makefile wiring and expected threshold content. | Threshold changes still require review; this does not prove the golden pack is sufficient for release. |
| Fail-closed behavior | Unit tests cover missing/failed dimensions, empty outcomes, nonnumeric/boolean thresholds, CLI nonzero exit, and failure-report artifact writing. | The gate only covers represented eval dimensions; it does not replace broader product/eval design review. |
| Golden Trusted Loop path | `tests.eval.threshold_report` builds outcomes from `tests/eval/golden_queries.json` by running the existing Trusted Loop eval path. | This reuses current golden coverage; it does not add new business scenarios. |
| CI integration | `make ci` now includes `eval-threshold-report` before OpenAPI verification; full CI evidence below confirms the target ran. | Post-merge CI must be rerun on actual local `main`. |
| Product/process boundary | Implementation docs state the slice does not change SQL Safety, EvidenceChain, Approval, Trace, connectors, or R4/R5 behavior. | No customer-facing capability or autonomy claim is authorized by this merge. |

## Verification

Targeted suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors \
  .venv/bin/python3 -m unittest \
    tests.eval.test_eval \
    tests.unit.test_eval_threshold_report_runner \
    tests.unit.test_eval_hub -v
```

Result: 14 tests OK.

Manual gate artifact check:

```bash
tmpdir=$(mktemp -d)
make eval-threshold-report PYTHON=.venv/bin/python3 \
  EVAL_THRESHOLD_REPORT_OUT="$tmpdir/report.json"
test -s "$tmpdir/report.json"
.venv/bin/python3 -m json.tool "$tmpdir/report.json" >/dev/null
rm -rf "$tmpdir"
```

Result: exit 0.

Full local CI:

```bash
make ci PYTHON=.venv/bin/python3
```

Result: ruff clean, format check clean, 543 primary unittest tests OK with 4
skipped, 12 eval tests OK, threshold report gate ran through
`tests/eval/golden_thresholds.json` with 5 cases and 8 dimensions all passing
at `1.0`, OpenAPI contract up to date, and `=== All CI checks passed ===`.

PostgreSQL local parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result: 543 primary unittest tests OK with 4 skipped, 12 eval tests OK,
threshold report gate ran through `tests/eval/golden_thresholds.json`, OpenAPI
contract up to date, and `=== Full local CI parity checks passed ===`.

## Required Post-Merge Commands

If founder/CTO authorizes local merge, use a fast-forward merge only and then
run:

```bash
git switch main
git merge --ff-only codex/eval-threshold-report-20260703
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Do not push or release as part of this merge gate.

## Stop Conditions

Stop before merge if any of these become true:

- `git merge --ff-only` would not fast-forward cleanly.
- Local `main` moves and changes eval harness, golden query semantics,
  `EvalThresholdReporter`, Makefile CI wiring, OpenAPI generation, SQL Safety,
  EvidenceChain, Approval, Trace, or runtime contract behavior.
- The branch requires conflict resolution.
- The threshold file is lowered, made advisory-only, or bypassed by `make ci`.
- The report command can pass while required dimensions are missing, false, or
  below threshold.
- The generated report is not valid JSON or cannot be written to the requested
  output path.
- The slice starts persisting reports automatically, exporting production
  telemetry, or claiming release readiness by itself.
- The slice changes SQL Safety, EvidenceChain, Approval, Trace, connector,
  HTTP auth, or R4/R5 execution behavior.
- Post-merge `make ci` or PostgreSQL `ci-local-full` fails.

If any stop condition is hit, return to implementation/review instead of
merging, pushing, or claiming readiness.

## Remaining Gates

- Founder/CTO local merge authorization.
- Fresh fast-forward check immediately before merge.
- Post-merge `make ci` and PostgreSQL `ci-local-full` on actual local `main`.
- Separate push authorization.
- Separate release/pilot-readiness review, including whether the current
  golden query pack and eight-dimension threshold contract are sufficient for
  the release question being asked.
