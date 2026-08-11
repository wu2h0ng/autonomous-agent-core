# ADR-0004 Merge Readiness: Governed-decision Seam

Date: 2026-07-02
Status: READY FOR FOUNDER/CTO LOCAL MERGE DECISION - NOT MERGE/PUSH/RELEASE AUTHORIZATION
Branch: `feature/governance-decision-seam-2026-07-01`
Target: deployment local `main`
Target head checked: `main@91ae01c`
Implementation code commit checked: `be0c511`
Feature head checked after docs-sync and before this rehearsal record: `640ac7b`
Readiness metadata note: `640ac7b` adds docs-only readiness boundary sync on
top of the checked implementation. This rehearsal record may itself create a
later docs-only feature head. Re-run the HEAD fast-forward checks below
immediately before any authorized merge, because either `main` or the feature
head may move.
Remote feature note: `origin/feature/governance-decision-seam-2026-07-01@5a4e86e` is older than the checked local branch; do not treat the remote branch as current readiness evidence.

This packet is the RR-0033 M3 PREPARE deliverable for ADR-0004/RR-0032. It is
a merge-decision aid only. It is not merge authorization, not a push request,
not an external release claim, not M4 CWM wiring, and not R4/R5 arming.

## Readiness Verdict

The branch is ready for explicit founder/CTO local merge decision under these
conditions:

1. fast-forward only from deployment local `main@91ae01c`;
2. local deployment `main` only;
3. no push, release, PR, or external deployment in the same action;
4. post-merge `make ci` and `ci-local-full` must pass on local `main`;
5. founder/CTO must separately approve any cross-repo service deployment,
   production metric/lever binding, or M4 CWM `governed_loop` wiring.

As checked during the implementation PREPARE pass, implementation code commit
`be0c511` was linear on local `main`:

```text
git merge-base --is-ancestor main be0c511
exit 0

git rev-list --left-right --count main...be0c511
0 5
```

Re-run these fast-forward checks immediately before any authorized merge.

As checked after the docs-sync commit, the then-current feature head `640ac7b`
remained linear on local `main`:

```text
git merge-base --is-ancestor main 640ac7b
exit 0

git rev-list --left-right --count main...640ac7b
0 7
```

## Scope To Merge

The branch adds an optional governed-decision seam at the
`TrustedLoopRuntime` governance gate:

- versioned `GovernanceDecisionRequest` / `GovernanceDecisionResponse`
  contract with v1.1 `VerifiedCandidate` support;
- native OS-side seam implementation, with no `autonomous-agent-core` import;
- `RemoteGovernanceDecisionClient`, injected transport, HTTP transport helper,
  `FallbackGovernanceDecisionClient`, and `LocalGovernanceDecisionClient`;
- OS-side candidate verification before the remote wire;
- response validation for task id, major contract version, verdict membership,
  and `audit_ref`;
- tighten-only behavior: `DENY` blocks, `ESCALATE` / `VERIFY_MORE` force
  approval, and `ALLOW` preserves the existing decision;
- fail-closed behavior on client failures, invalid responses, and unknown
  verdicts;
- trace-safe projection that withholds remote free-text reasons while retaining
  `audit_ref` plus OS `trace_id` / `evidence_chain_id` anchors for controlled
  audit lookup;
- ADR/review/current-state documentation for the branch-local seam.

The changed files relative to local `main@91ae01c` are:

```text
AGENTS.md
README.md
docs/CURRENT_STATE.yaml
docs/decisions/ADR-0003-agent-runtime-capability-gap-audit-20260626.md
docs/decisions/ADR-0004-governed-decision-seam.MERGE-READINESS-20260702.md
docs/decisions/ADR-0004-governed-decision-seam.REVIEW-20260702.md
docs/decisions/ADR-0004-governed-decision-seam.md
docs/decisions/README.md
packages/contracts/src/agent_os_contracts/governance_decision_seam.py
packages/contracts/src/agent_os_contracts/trusted_loop.py
packages/os_core/src/agent_os_core/governance_decision_seam/__init__.py
packages/os_core/src/agent_os_core/trusted_loop.py
tests/unit/test_governance_decision_seam.py
```

## RR-0033 M3 Coverage

| M3 requirement | Evidence | Boundary |
|---|---|---|
| Additive seam | `TrustedLoopRuntime` accepts optional `governance_decision_client`; the default `None` path is covered by `test_no_client_is_unchanged`. | Existing Trusted Loop remains the authority when no seam client is configured. |
| Default `None` unchanged | `tests.unit.test_governance_decision_seam.TrustedLoopSeamWire.test_no_client_is_unchanged` passed in targeted and full CI runs. | This proves the tested Trusted Loop output path; post-merge CI is still required. |
| Five tighten-only invariants | `LocalClientInvariants` tests cover verified-only action, high-stakes escalation, paused-shell DENY, deterministic behavior/no LLM control path, and required `audit_ref`; Trusted Loop integration tests bind governed-decision trace events to OS `trace_id` / `evidence_chain_id`. | R4/R5 remain proposal-only and are not armed. |
| Completed RR-0032 steps | OS-side v1.1 contract, OS-side verification before remote wire, HTTP transport, fallback, response validation, and native tests are present; RR-0032 production items remain pending. | Deployed core service, production service identity, real business metric/lever, and concrete `CohortABVerifier` are M4/founder/PM work, not this merge. |
| No cross-repo import | Implementation is native in OS contracts/core. Existing import-boundary test `test_product_core_does_not_import_external_agent_frameworks` passed in full CI. | This is a contract/RPC seam, not a library dependency on `autonomous-agent-core`. |
| SQL Safety / EvidenceChain / Approval / Trace not bypassed | Seam is consulted after ActionProposal construction and before operation/approval gate; full Trusted Loop, SQL Safety, EvidenceChain, approval, trace, and eval suites passed. | Seam can only tighten; it does not replace SQL Safety, EvidenceChain, Approval, or Trace. |
| Trace safety | Remote free-text reasons are withheld from trace/block details; tests cover safe projection, invalid-response/unknown-verdict non-leakage, and OS trace/evidence anchors on governed-decision events. | `audit_ref` is retained with OS trace/evidence anchors; raw remote explanations are not product trace payloads. |

## Verification

Targeted seam suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  .venv/bin/python3 -m unittest tests.unit.test_governance_decision_seam -v
```

Result: 29 tests OK, including the five invariants, default-None unchanged
path, v1.1 OS-side verification, remote response validation, HTTP transport,
fallback behavior, and trace-safe projection tests.

Full local CI:

```bash
make ci PYTHON=.venv/bin/python3
```

Result: ruff clean, format clean, 534 primary unittest tests OK with 4 skipped,
12 eval tests OK, OpenAPI contract up to date, and
`=== All CI checks passed ===`.

PostgreSQL local parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result: ruff clean, format clean, 534 primary unittest tests OK with 4 skipped,
12 eval tests OK, OpenAPI contract up to date, and
`=== Full local CI parity checks passed ===`.

## Merge Rehearsal Verification

After the docs-sync commit, Codex created an isolated rehearsal worktree from
local `main@91ae01c`, fast-forwarded it to then-current feature head `640ac7b`,
and verified the post-merge tree shape without moving `main`:

```bash
git worktree add .worktrees/governance-seam-merge-rehearsal-20260702 \
  -b codex/governance-seam-merge-rehearsal-20260702 main
git -C .worktrees/governance-seam-merge-rehearsal-20260702 \
  merge --ff-only feature/governance-decision-seam-2026-07-01
```

Result: fast-forward succeeded from `91ae01c` to `640ac7b`; no conflict
resolution was needed, and local `main` was not moved.

Rehearsal targeted suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors:apps/api_server/src \
  ../../.venv/bin/python3 -m unittest tests.unit.test_governance_decision_seam \
  tests.unit.test_trusted_loop tests.integration.test_trusted_loop_agent_runtime_adapter -v
```

Result: 50 tests OK.

Rehearsal full CI:

```bash
make ci PYTHON=../../.venv/bin/python3
```

Result: ruff clean, format clean, 534 primary unittest tests OK with 4 skipped,
12 eval tests OK, OpenAPI contract up to date, and
`=== All CI checks passed ===`.

Rehearsal PostgreSQL local parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=../../.venv/bin/python3
```

Result: 534 primary unittest tests OK with 4 skipped, 12 eval tests OK,
OpenAPI contract up to date, and `=== Full local CI parity checks passed ===`.

This rehearsal is stronger evidence than branch-only verification, but it is
still not merge authorization. A real local-main merge must be explicitly
authorized and must rerun the post-merge commands on actual `main`.

## Required Post-Merge Commands

If founder/CTO authorizes local merge, use a fast-forward merge only and then
run:

```bash
git switch main
git merge --ff-only feature/governance-decision-seam-2026-07-01
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Do not push or release as part of this merge gate.

## Stop Conditions

Stop before merge if any of these become true:

- `git merge --ff-only` would not fast-forward cleanly.
- Local `main` moves and changes `TrustedLoopRuntime`, `RuntimePolicyGate`,
  ActionProposal, Approval, EvidenceChain, SQL Safety, trace, HTTP auth, or
  OpenAPI contract behavior.
- The branch requires conflict resolution.
- The seam requires importing or copying code from `autonomous-agent-core`.
- The seam would auto-execute R4/R5 business actions or weaken proposal-only
  enforcement.
- `ALLOW` from a seam client would bypass existing SQL Safety, EvidenceChain,
  Approval, Trace, or connector governance.
- Client failure, unknown verdict, missing `audit_ref`, mismatched task id, or
  incompatible contract version would fail open.
- Trace/block details would expose raw remote free-text reasons, raw SQL, raw
  connector payloads, raw args/output, secrets, or credentials.
- A completed RR-0032 step loses OS-side acceptance-test coverage.
- Post-merge `make ci` or `ci-local-full` fails.

If any stop condition is hit, return to implementation/review instead of
merging, pushing, or claiming readiness.

## Remaining Gates

- Founder/CTO local merge authorization.
- Cross-repo injection ADR/approval for any production service boundary beyond
  the accepted design and branch-local OS implementation.
- Deployed autonomous-core seam service reachable by OS.
- Production service identity/authentication and timeout policy for the RPC
  boundary.
- Concrete production metric/lever and `CohortABVerifier` for the first M4
  R0-R3 use case.
- Execution-time seam recheck policy, if a live use case requires it.
- Separate founder decision for any R4/R5 arming.
- SD4/final-authority decisions remain founder-reserved.

## Non-Claims

This branch does not prove autonomous intelligence, does not implement or
import the autonomous-core object layer, does not deploy the CWM
`governed_loop`, does not implement M4, does not arm R4/R5, does not replace
Trusted Loop, SQL Safety, EvidenceChain, Approval, or Trace, does not make
Agent Runtime a workflow engine, does not introduce an external agent framework
runtime dependency, and does not authorize push or release.

## Gate Outcome

Outcome: READY FOR EXPLICIT FOUNDER/CTO LOCAL MERGE DECISION.

Keep the branch unmerged to `main`, unpushed, and unreleased unless explicitly
authorized. If merged locally, record post-merge verification before any later
push or release discussion.
