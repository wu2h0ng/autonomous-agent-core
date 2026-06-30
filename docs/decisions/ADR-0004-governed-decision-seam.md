# ADR-0004: Governed-decision injection seam (R0–R3 wire)

- Status: Accepted (implementation, feature branch). 2026-07-01.
- Cross-repo authorization: workspace RR-0032 (founder WIRE go 2026-07-01, scope R0–R3). This ADR records the OS-side decision; the sibling repo `autonomous-agent-core` is NOT imported.

## Context
The autonomous-agent-core research line produced a governed decision loop (verify-before-decide, stakes-gated, C7-wrapped). RR-0032 cast an RPC/service seam to consume its verdict inside the OS Trusted Loop without merging codebases (Hard Boundary: OS Core imports no sibling repo).

## Decision
Add an OPTIONAL `governance_decision_client` to `TrustedLoopRuntime`, consulted at the governance gate (after the ActionProposal is built, before the operation/approval gate). The client can only **TIGHTEN**:
- `DENY` → block the loop (`BlockCode.GOVERNANCE_DENIED`).
- `ESCALATE` / `VERIFY_MORE` → force the proposal through approval (`approval_required=True`).
- `ALLOW` → unchanged.

Default `None` → the seam is skipped and the loop is byte-for-byte unchanged (507 existing tests unaffected).

## Design (no sibling import; RPC boundary)
- **Contract** `agent_os_contracts/governance_decision_seam.py`: versioned (semver 1.0.0) `GovernanceDecisionRequest`/`GovernanceDecisionResponse` + JSON (de)serialize. The OS implements the shared spec NATIVELY.
- **Client** `agent_os_core/governance_decision_seam/`: `GovernanceDecisionClient` ABC; `RemoteGovernanceDecisionClient` (RPC stub — transport injected; the remote autonomous-agent-core service is not wired in this repo); `LocalGovernanceDecisionClient` (native reference impl of the five invariants for dev/tests); `CohortABVerifier` ABC (the OS-side interventional probe = a bounded cohort A/B test).
- **Wire** `trusted_loop.py`: additive optional param + gate call; new `BlockCode.GOVERNANCE_DENIED`.

## Invariants (acceptance-tested, `tests/unit/test_governance_decision_seam.py`, 13 tests)
1. act only on a VERIFIED candidate; 2. high-stakes (≥R4) never auto-allowed → escalate; 3. C7: a paused shell can only DENY; 4. deterministic (no LLM in the control path); 5. every response carries a resolving `audit_ref`. Plus contract-version rejection, JSON round-trip, and the integration wire (DENY blocks / ALLOW+None unchanged / ESCALATE recorded).

## Scope / boundaries
- R0–R3 only. **R4/R5 stay proposal-only** (unchanged) — the seam can only push toward approval, never authorize a high-risk write.
- The OS keeps SQL Safety, EvidenceChain, Approval, connectors. The seam adds a governance check, it does not replace any.
- Completion gate: entry point = `TrustedLoopRuntime` governance gate; contract = `GovernanceDecisionRequest/Response`; negative path = DENY block + version reject (tested); regression test = `test_governance_decision_seam.py` (fails if the wire is bypassed); trace/audit = `trace.record("governed_decision")` + shell `observe`; OS Core boundary intact (no sibling import; contract-only).

## Pending (not in this ADR)
The real `RemoteGovernanceDecisionClient` transport + a deployed autonomous-agent-core service; production metric/lever specifics for the first use-case (REF-ARCH-05 reference shape used until then). These need a follow-up once a live OS use-case is chosen.
