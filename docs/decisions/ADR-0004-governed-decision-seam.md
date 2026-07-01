# ADR-0004: Governed-decision injection seam (R0-R3 wire)

- Status: Accepted on feature branch `feature/governance-decision-seam-2026-07-01`.
  Rebased onto deployment local `main@91ae01c`, independently reviewed,
  remediated, and verified on 2026-07-02.
  Not merged to `main`, not pushed after the rebase, not released.
- Cross-repo authorization: workspace RR-0032 (founder WIRE go 2026-07-01,
  scope R0-R3). This ADR records the OS-side decision; the sibling repo
  `autonomous-agent-core` is NOT imported.

## Context
The autonomous-agent-core research line produced a governed decision loop (verify-before-decide, stakes-gated, C7-wrapped). RR-0032 cast an RPC/service seam to consume its verdict inside the OS Trusted Loop without merging codebases (Hard Boundary: OS Core imports no sibling repo).

## Decision
Add an OPTIONAL `governance_decision_client` to `TrustedLoopRuntime`, consulted
at the governance gate (after the ActionProposal is built, before the
operation/approval gate). The client can only **TIGHTEN**:

- `DENY` -> block the loop (`BlockCode.GOVERNANCE_DENIED`).
- `ESCALATE` / `VERIFY_MORE` -> force the proposal through approval
  (`approval_required=True`).
- `ALLOW` -> unchanged.

Default `None` -> the seam is skipped and the loop is unchanged.

## Design (no sibling import; RPC boundary)
- **Contract** `agent_os_contracts/governance_decision_seam.py`: versioned
  semver `1.1.0` `GovernanceDecisionRequest`/`GovernanceDecisionResponse`,
  `VerifiedCandidate`, and JSON (de)serialize. The OS implements the shared
  spec natively.
- **Client** `agent_os_core/governance_decision_seam/`:
  `GovernanceDecisionClient` ABC; `RemoteGovernanceDecisionClient` (RPC stub,
  transport injected, with OS-side verification before the wire and response
  validation for task id, major contract version, verdict membership, and
  `audit_ref`);
  `http_transport`; `FallbackGovernanceDecisionClient`; and
  `LocalGovernanceDecisionClient` (native reference impl of the five invariants
  for dev/tests). The remote autonomous-agent-core service is not wired in this
  repo.
- **Wire** `trusted_loop.py`: additive optional param + gate call; new
  `BlockCode.GOVERNANCE_DENIED`; client failures and unknown verdicts fail
  closed to approval; remote free-text reasons are withheld from runtime trace
  and block details.

## Invariants (acceptance-tested, `tests/unit/test_governance_decision_seam.py`, 29 tests)

1. act only on a verified candidate; 2. high-stakes (>=R4) never auto-allowed
-> escalate; 3. C7: a paused shell can only DENY; 4. deterministic (no LLM in
the control path); 5. every response carries a resolving `audit_ref`. Plus
contract-version rejection, JSON round-trip, HTTP transport/fallback behavior,
remote response validation, unknown-verdict fail-closed behavior, safe reason
projection, and the integration wire (DENY blocks / ALLOW+None unchanged /
ESCALATE/VERIFY_MORE force approval).

## Scope / boundaries
- R0-R3 only. **R4/R5 stay proposal-only** (unchanged) - the seam can only push
  toward approval, never authorize a high-risk write.
- The OS keeps SQL Safety, EvidenceChain, Approval, connectors. The seam adds a governance check, it does not replace any.
- Completion gate: entry point = `TrustedLoopRuntime` governance gate; contract = `GovernanceDecisionRequest/Response`; negative path = DENY block + version/task/verdict/audit_ref reject + unknown-verdict fail-closed (tested); regression test = `test_governance_decision_seam.py` (fails if the wire is bypassed); trace/audit = safe `trace.record("governed_decision")` + shell `observe` + `audit_ref`; OS Core boundary intact (no sibling import; contract-only).
- Known boundary: this seam is consulted at initial proposal time. Approval-resume
  execution does not re-consult the seam in this slice; add a follow-up ADR/gate
  if a live use-case requires execution-time governance recheck.

## Review

- 2026-07-02 independent diff review and remediation:
  `docs/decisions/ADR-0004-governed-decision-seam.REVIEW-20260702.md`.

## Verification

Initial 2026-07-02 verification after rebase onto deployment local `main@91ae01c`,
before independent review remediation:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  .venv/bin/python3 -m unittest tests.unit.test_governance_decision_seam -v
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Initial result: seam suite 21 OK; `make ci` passed with ruff clean, format clean, 526
tests OK / 4 skipped, 12 eval OK, and OpenAPI up to date; PostgreSQL
`ci-local-full` passed with the same 526 tests OK / 4 skipped, 12 eval OK, and
OpenAPI up to date.

Fresh 2026-07-02 verification after independent review remediation:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors:apps/api_server/src \
  .venv/bin/python3 -m unittest tests.unit.test_governance_decision_seam \
  tests.unit.test_trusted_loop tests.integration.test_trusted_loop_agent_runtime_adapter -v
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result: targeted seam/adjacent suite 50 tests OK; `make ci` passed with ruff
clean, format clean, 534 tests OK / 4 skipped, 12 eval OK, and OpenAPI up to
date; PostgreSQL `ci-local-full` passed with the same 534 tests OK / 4 skipped,
12 eval OK, and OpenAPI up to date.

## Pending

Deployed autonomous-agent-core seam service, production authentication/service
identity for the RPC boundary, production metric/lever specifics for the first
live OS use-case, and any execution-time seam recheck policy. These need a
follow-up once a live OS use-case is chosen.
