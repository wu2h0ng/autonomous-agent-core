# Verification

Pre-implementation RED:

```text
ModuleNotFoundError: No module named 'agent_os_core.responsibility_loop'
```

Post-implementation targeted test:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
uv run --extra product-test pytest tests/product/test_responsibility_loop.py -q
8 passed
```

Quality:

```text
uv run ruff check packages/os_core/src/agent_os_core/responsibility_loop.py \
  tests/product/test_responsibility_loop.py
All checks passed
```

```text
uv run pyright packages/os_core/src/agent_os_core/responsibility_loop.py \
  tests/product/test_responsibility_loop.py
0 errors, 0 warnings, 0 informations
```

Independent exact-range review returned
`TECHNICAL_REVISE_FOUNDATION` with `P0=0 / P1=5 / P2=1`. No full Product
suite, CLI fixture, merge or release is claimed here.

Remediation verification:

```text
pytest tests/product/test_responsibility_loop.py -q
22 passed

pytest tests/product/test_responsibility_loop.py
  tests/product/test_mandate_outcome_portfolio.py
  tests/product/test_mandate_responsibility_store.py
  tests/product/test_mandate_active_perception.py -q
101 passed

ruff check responsibility_loop.py test_responsibility_loop.py
All checks passed

pyright responsibility_loop.py test_responsibility_loop.py
0 errors, 0 warnings, 0 informations
```

The full Product suite reached `1658 passed / 1 skipped / 18 failed`. All
failures are outside the changed files. A detached base `26c3f16` run over the
three failing test modules also produced 18 failures; the exact membership is
time/order-sensitive because those tests contain expired fixed timestamps and
existing policy/golden-path debt. This is explicit baseline debt, not a green
full-suite claim.

Second exact-head re-review at `b9bfa79` returned
`TECHNICAL_REVISE_FOUNDATION` with `P0=0 / P1=4 / P2=1`. The exact verdict is
preserved in `independent-foundation-rereview.md`.

Second remediation used failing attack tests before implementation:

- mutated APPLIED effect `task_id` and `intent_digest`;
- takeover fence sealing a prior-owner checkpoint;
- response-lost retry of a committed cycle receipt;
- `NOT_MET -> SETTLED_MET` semantic forgery;
- cross-workspace canonical portfolio substitution.

Post-remediation evidence:

```text
pytest tests/product/test_responsibility_loop.py -q
28 passed

pytest responsibility_loop + mandate_outcome_portfolio
  + mandate_responsibility_store + mandate_active_perception
107 passed

ruff check responsibility_loop.py test_responsibility_loop.py
All checks passed

pyright responsibility_loop.py test_responsibility_loop.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

The remediation also records explicit rebind provenance with previous and
replacement binding digests, actor, reason, authority reference and trusted
time. These results are not a technical approval; a new exact-head independent
review is still required.

Third exact-head review at `5d53811` again returned
`TECHNICAL_REVISE_FOUNDATION`, with `P0=0 / P1=2 / P2=1`. The exact verdict is
preserved in `independent-foundation-rereview-2.md`.

Third remediation added failing attacks for primary-key rename/delete and five
post-bind outcome-truth mutations. The implementation now uses a stable
companion effect identity reservation, revalidates the full
cycle-receipt/bridge/settlement/commitment/portfolio chain at measurement, and
provides a typed validating read path for rebind receipts bound to audit event
ids.

Post-remediation evidence:

```text
pytest tests/product/test_responsibility_loop.py -q
35 passed

pytest responsibility_loop + mandate_outcome_portfolio
  + mandate_responsibility_store + mandate_active_perception
114 passed

ruff check responsibility_loop.py test_responsibility_loop.py
All checks passed

pyright responsibility_loop.py test_responsibility_loop.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

This remains `FOUNDATION_NOT_APPROVED` until a new exact-head independent
review returns `TECHNICAL_APPROVE_FOUNDATION`.

Fourth exact-head review at `8b4066c` returned
`TECHNICAL_REVISE_FOUNDATION`, with `P0=0 / P1=1 / P2=1`. The exact verdict is
preserved in `independent-foundation-rereview-3.md`.

Fourth remediation adds stable scope to rebind audit linkage and validates
receipt, link and audit cardinality bidirectionally. It also records a
content-bound cycle-settlement reservation and compares it against the bridge
before HCW measurement. Isolated deletion of either authoritative projection
now fails closed.

Post-remediation evidence:

```text
pytest tests/product/test_responsibility_loop.py -q
36 passed

pytest responsibility_loop + mandate_outcome_portfolio
  + mandate_responsibility_store + mandate_active_perception
115 passed

ruff check responsibility_loop.py test_responsibility_loop.py
All checks passed

pyright responsibility_loop.py test_responsibility_loop.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

This remains `FOUNDATION_NOT_APPROVED` pending a new exact-head independent
review.

Sixth exact-head review at
`ddb021bead18151f3e97f8e8467473a89c068508` returned
`TECHNICAL_APPROVE_FOUNDATION` with `P0=0 / P1=0 / P2=0`. The durable verdict
is `independent-foundation-approval.md`.

The approval covers only the responsibility-loop persistence foundation.
Controller, CLI commands, Outcome/Help application integration and the complete
product loop remain incomplete. No merge, release, HCW reduction, sustained
responsibility, self-improvement or autonomy claim follows from this approval.

Fifth exact-head review at `feacc61` returned
`TECHNICAL_REVISE_FOUNDATION`, with `P0=0 / P1=1 / P2=0`. The exact verdict is
preserved in `independent-foundation-rereview-4.md`.

Fifth remediation adds a narrow, idempotent schema-v3 migration. It detects
prior audit/link column shapes with `PRAGMA table_info`, backfills stable scope
from canonical lease and rebind evidence, backfills content-bound
cycle-settlement reservations, and returns a typed migration-required error
when legacy provenance is ambiguous. A non-empty prior-exact-head database
fixture verifies rebind evidence, lease reacquire, effect preservation and HCW
truth after upgrade.

Post-remediation evidence:

```text
pytest tests/product/test_responsibility_loop.py -q
38 passed

pytest responsibility_loop + mandate_outcome_portfolio
  + mandate_responsibility_store + mandate_active_perception
117 passed

ruff check responsibility_loop.py test_responsibility_loop.py
All checks passed

pyright responsibility_loop.py test_responsibility_loop.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

This remains `FOUNDATION_NOT_APPROVED` pending a new exact-head independent
review.
