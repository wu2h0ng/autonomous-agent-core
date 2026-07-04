# ADR-0007: Cross-process governed-decision seam — integrated real execution (S3)

- Status: Proposed on feature branch `codex/s3-cross-process-seam-real-execution-20260705`.
  Not merged, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2, slice **S3** (founder-authorized
  2026-07-05). Sequenced after **S2** (ADR-0006, local disposer) and **S1** (ADR-0005, execution-time
  recheck), on which it depends.
- Builds on: **ADR-0004** (seam contract, tighten-only) and **RR-0032** (RPC boundary, no import).
  The sibling repo `autonomous-agent-core` is NOT imported (Hard Boundary #19); the seam is a shared
  versioned JSON contract implemented independently on both sides.

## Context

S2 governed a real reversible action with the **in-process** native disposer
(`LocalGovernanceDecisionClient`). The RR-0032 architecture, though, is a **process/service boundary**:
the OS Trusted Loop consults an external governed-decision brain over JSON/HTTP (RPC, not import). The OS
side of that wire — `RemoteGovernanceDecisionClient`, `http_transport`, `FallbackGovernanceDecisionClient`
— was already on `main`, but nothing exercised the **full runtime across a real process boundary** in a
CI-verifiable way. The production research brain (`autonomous-agent-core`'s `aac.seam_service`) requires
that sibling checkout, so a test bound to it would skip in OS CI.

## Decision

1. **OS-side reference seam server.** Add `examples/reference_seam_service.py`: a pure-stdlib
   `POST /decide` server that **governs the OS-supplied `verified_candidates`** per the shared v1.1
   contract ("OS verifies → core governs") — it does not re-run verification (the remote side has no OS
   data) and never auto-allows an unverified candidate. It is the OS's **own** reference implementation of
   the remote contract side; it imports **no** `autonomous-agent-core` code (#19). The production research
   brain is a drop-in on the same wire.
2. **Full runtime across a real process boundary (CI-verifiable).**
   `tests/integration/test_s3_cross_process_seam_real_action.py` boots that server as a **separate
   process** and drives the full `TrustedLoopRuntime` through `RemoteGovernanceDecisionClient` — real
   socket, real JSON — proving:
   - verified cohort effect → OS verifies locally, ships `VerifiedCandidate`s over the wire, the remote
     brain governs → ALLOW → OS approval → ADR-0005 execution-time recheck **re-consulted over the socket**
     → `connector.execute` → a real reversible ledger write; reversible via `rollback`.
   - corrigibility (C7) halts a real action even with a remote brain — enforced **OS-side** before the
     remote is consulted; the runtime never delegates the pause to the remote.
   - resilience: with the brain **down**, `FallbackGovernanceDecisionClient` degrades safe — the loop
     never blocks and never auto-allows; the action is forced to human approval (ADR-0047).
3. **Production-shape rehearsal against the real brain.** Port `examples/m4_live_seam_rehearsal.py`, which
   boots the real `aac.seam_service` as a subprocess (when `AAC_REPO` is set; skips otherwise) and checks
   the five tighten-only invariants live.

## Honest finding (stranded nested-side fix)

Running the real-brain rehearsal against the current `autonomous-agent-core` HEAD re-surfaces the exact
invariant-5 gap the M4 history recorded: the brain's **version-mismatch DENY carries an empty
`audit_ref`** (`aac/seam_contract.py`), which the OS client correctly rejects (`_validate_remote_response`
requires a resolving `audit_ref`). The fix (`b9c51ae`, "version-reject responses now carry a resolving
audit_ref") exists in the object DB but is **not on the autonomous-core HEAD** — it is stranded, the same
pattern as the M4 seam work. The OS side is correct; landing `b9c51ae` on `autonomous-agent-core` is a
**separate #19-gated task in that repo**, not part of this OS slice. The CI-verifiable S3 proof therefore
stands on the OS reference server (which is conformant, including a resolving `audit_ref` on the
version-mismatch DENY); the real-brain rehearsal carries this documented caveat until the nested fix lands.

## Scope / non-goals

- **No production deployment.** This is a local process-boundary rehearsal; deploying the real research
  brain as a live service stays founder-reserved.
- **No contract change.** Reuses seam contract v1.1.0 and the existing OS client/transport/fallback.
- **No outcome learning.** The outcome→KnowledgeAsset compounding loop is **S4**.
- R4/R5 stay proposal-only; the seam can only tighten.

## Consequences

- Positive: the full governed loop is proven across a real process boundary, CI-verifiable and
  self-contained, with fail-safe degradation when the brain is unreachable. The reference server also gives
  the OS a permanent, repo-local rehearsal target for the seam.
- Cost: a small reference server to maintain alongside the contract. The real-brain rehearsal depends on a
  stranded nested-side fix landing before it passes end-to-end.

## Tests

- `tests/integration/test_s3_cross_process_seam_real_action.py` — cross-process real execution + rollback;
  C7 pause halts with a remote brain; brain-down degrades safe (never blocks, never auto-allows).
- `examples/reference_seam_service.py` — smoke-covered by the integration test (boots as a subprocess and
  governs every verdict path over the wire).
