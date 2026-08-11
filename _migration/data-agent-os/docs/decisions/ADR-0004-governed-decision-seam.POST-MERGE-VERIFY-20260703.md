# ADR-0004 Post-Merge Verification: Governed-decision Seam

Date: 2026-07-03
Status: LOCAL MAIN POST-MERGE VERIFICATION PASSED - NOT PUSHED/RELEASED
Branch merged: `feature/governance-decision-seam-2026-07-01`
Target: deployment local `main`
Pre-merge main head: `91ae01c`
Post-merge main head: `b2225ac`

## Merge

Founder/CTO authorization was given for a local fast-forward-only merge of the
ADR-0004 governed-decision seam into deployment `main`, followed by post-merge
`make ci` and PostgreSQL `ci-local-full`. Push and release were explicitly out
of scope.

The local merge used:

```bash
git switch main
git merge --ff-only feature/governance-decision-seam-2026-07-01
```

Result: fast-forward succeeded from `91ae01c` to `b2225ac`; no merge commit and
no conflict resolution were created.

## Post-Merge Verification

Full local CI:

```bash
make ci PYTHON=.venv/bin/python3
```

Result:

- ruff clean;
- format check clean;
- 534 primary unittest tests OK;
- 4 skipped;
- 12 eval tests OK;
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
- 534 primary unittest tests OK;
- 4 skipped;
- 12 eval tests OK;
- OpenAPI contract up to date;
- `=== Full local CI parity checks passed ===`.

## Boundaries

This local merge means ADR-0004 is present on deployment local `main`. It does
not mean:

- pushed to `origin/main`;
- released or externally deployed;
- production remote autonomous-core/CWM service wired;
- production service identity/auth complete;
- M4 `governed_loop` complete;
- product-domain validation of autonomous-core/G10 evidence;
- R4/R5 automatic business execution authorized.

The seam remains tighten-only: a governed-decision client can deny or escalate
within the R0-R3 governance path, but cannot bypass SQL Safety, EvidenceChain,
Approval, Trace, connectors, or R4/R5 proposal-only boundaries.
