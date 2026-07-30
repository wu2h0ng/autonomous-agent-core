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

## Controller/CLI remediation candidate — 2026-07-30

The prior controller review returned
`TECHNICAL_REVISE_RESPONSIBILITY_SLICE / NOT_MERGE_READY`. The accepted
findings were converted into bypass-detecting tests and remediated before a new
exact-head review:

- lease heartbeat at every execution fence;
- Task tool effects execute through responsibility custody and become
  `UNKNOWN` when takeover occurs after the external callback;
- settlement, cycle receipt, settlement binding and HCW finalization are
  restart-idempotent;
- HCW uses one immutable evaluator root and idempotent measurement identity;
- terminal attach no longer self-creates the Mandate owner as `TENANT_ADMIN`;
- Ctrl-C invokes external Task correction and exits 130;
- status projects lease, unknown effects, HCW and named wake sources;
- SELFDEV is a typed `SELFDEV_ROUTE_NOT_BOUND` route with no execution;
- a real OS-subprocess A-to-B-to-A fixture restores one cycle from SQLite
  without `.agent_os/terminal_session.json`.

Verification:

```text
pytest tests/product/test_responsibility_controller.py -q
13 passed

pytest responsibility_loop + responsibility_controller + agent_cli_v0
  + long_horizon_execution + mandate_outcome_portfolio
  + mandate_outcome_portfolio_help_api
96 passed

ruff check <7 changed source/test files>
All checks passed

pyright <6 changed source files>
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

Repository-wide Product + product_eval:

```text
2616 passed, 1 skipped, 27 failed
```

The full suite is explicitly not green. Sixteen provider-trajectory failures
share expired dated fixture commitments on the current date. Other failures
include frozen source-byte/provider-bank/environment drift and formal-ledger
contamination. The two failures that traverse the changed shared execution path
were rerun in isolation and passed:

```text
test_developer_golden_path_real_read_patch_tests_and_outcome
test_correction_after_permit_blocks_actual_dispatch
2 passed
```

This evidence is a local review candidate only. It does not establish HCW
reduction, continuous daemon operation, SELFDEV execution, release, superiority
or `Autonomy(S,E,O,V,T)`.

## Exact-head review and second remediation

Independent review of `ddb021b..9471bc5` returned
`TECHNICAL_REVISE_RESPONSIBILITY_SLICE / P0=0 / P1=5 / P2=2 /
NOT_MERGE_READY`. The durable review is
`independent-controller-rereview.md`.

All five P1 findings now have bypass-detecting coverage:

- the portfolio creator binds an Agent Work bearer digest through the existing
  admin-authorized portfolio creation path; the CLI resolves that canonical
  creator and verifies the bearer instead of accepting an authority ID;
- `MandateTaskLink.work_route` is a backward-compatible persisted contract and
  the real Surface returns typed `SELFDEV_ROUTE_NOT_BOUND`;
- a tool-window `KeyboardInterrupt` is no longer caught as an ordinary effect
  exception and reaches Task correction/checkpoint/exit 130;
- status explicitly reports no resident watcher and only named manual resume
  triggers;
- status reconciles APPLIED responsibility receipts against canonical Task
  `ACTION_RECEIPT_RECORDED` events and counts missing bindings as unknown.

The P2 crash coverage now separately injects failure after cycle receipt,
settlement binding and HCW measurement. Each restart reuses one settlement,
cycle identity and HCW identity without re-executing the Task.

```text
pytest tests/product/test_responsibility_controller.py -q
20 passed

pytest responsibility loop/controller + Agent CLI + long horizon
  + Outcome/Help + responsibility store/API
122 passed

ruff check <changed source/test files>
All checks passed

pyright <changed source files>
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

The remaining P2 external-signal ingress limitation is explicit: the recovery
fixture uses real A/B/A CLI processes, but pytest injects the typed signal
through the canonical TaskService rather than a separate external ingress
process. No resident daemon, automatic wake or production authentication claim
is made.

## Controller and unique Agent Work surface candidate

The Controller/CLI candidate was verified after the foundation approval. The
first combined command used a nonexistent historical filename
`tests/product/test_long_horizon_runtime.py`; the Controller/CLI portion had
already completed with `55 passed`, but that command exited `4`. The adjacent
suite was rerun with the actual long-horizon module names.

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
uv run --extra product-test pytest \
  tests/product/test_responsibility_controller.py \
  tests/product/test_responsibility_loop.py \
  tests/product/test_agent_cli_v0.py -q
56 passed
```

The 56 include bypass checks for both AgentLoop and RunCoordinator: a stale
responsibility fence raised at `before_tool_effect` produces no action receipt
and no workspace mutation.

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
uv run --extra product-test pytest \
  tests/product/test_mandate_outcome_portfolio.py \
  tests/product/test_mandate_responsibility_store.py \
  tests/product/test_mandate_active_perception.py \
  tests/product/test_long_horizon_execution.py \
  tests/product/test_long_horizon_compensation.py -q
113 passed
```

```text
uv run ruff check <11 changed source/test files>
All checks passed

uv run pyright <11 changed source/test files>
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

This evidence creates only a review candidate. It does not yet close the
cross-process A-to-B-to-A fixture, Ctrl-C recovery, HCW receipt integration,
SELFDEV route denial, exact-head independent review, merge or release gates.

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
