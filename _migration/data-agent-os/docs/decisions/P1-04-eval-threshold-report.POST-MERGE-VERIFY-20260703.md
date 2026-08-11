# P1-04 Post-Merge Verification: Eval Threshold Report

Date: 2026-07-03
Status: LOCAL MAIN VERIFIED - NOT PUSHED/RELEASED
Authorized action: founder/CTO authorized local `ff-only` merge, with
post-merge `make ci` and PostgreSQL `ci-local-full`; no push and no release.
Source branch: `codex/eval-threshold-report-20260703`
Merged implementation/readiness head: `4fb4591`
Target before merge: deployment local `main@f56054c`
Merge result: fast-forward to `4fb4591`
Remote baseline at verification time: `origin/main@dba87bc`

## Merge

Pre-merge checks on the feature branch:

```text
git merge-base --is-ancestor main HEAD
exit 0

git rev-list --left-right --count main...HEAD
0 2
```

Merge command:

```bash
git switch main
git merge --ff-only codex/eval-threshold-report-20260703
```

Result: fast-forward succeeded from `f56054c` to `4fb4591`; no conflict
resolution was needed. The merge was local only. No push, release, PR, or
external deployment was performed.

## Post-Merge Verification

Local CI:

```bash
make ci PYTHON=.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- 543 primary unittest tests OK;
- 4 skipped;
- 12 eval tests OK;
- threshold report gate ran through
  `python -m tests.eval.threshold_report --thresholds-file tests/eval/golden_thresholds.json --output .agent_runs/eval-threshold-report/golden-threshold-report.json`;
- generated report covered 5 golden cases and 8 dimensions, all passing at
  `1.0`;
- OpenAPI contract up to date;
- `=== All CI checks passed ===`.

PostgreSQL local parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- 543 primary unittest tests OK;
- 12 eval tests OK;
- threshold report gate ran through `tests/eval/golden_thresholds.json`;
- OpenAPI contract up to date;
- `=== Full local CI parity checks passed ===`.

## Boundaries

This verification confirms only the local deployment main state after the
authorized merge. It does not authorize or imply:

- push to `origin/main`;
- external release, pilot readiness, or customer guarantee;
- production telemetry export or automatic report persistence;
- autonomous-core/G10 validation in the product domain;
- any change to SQL Safety, EvidenceChain, Approval, Trace, connectors, HTTP
  auth, or R4/R5 execution behavior beyond the eval-gate support surface.

The `.agent_runs/eval-threshold-report/golden-threshold-report.json` artifact is
a local gate artifact and remains untracked.

