# P1-6 SECURITY-C7-BOUNDARY-0 — Gap Assessment + Implementation Cast

> Status: `CTO_GATE_ISSUED 2026-09-14` / pre-implementation
> Track: product  primary_class: A  secondary_class: P/E
> Base: origin/main `a50d1be0` (contains the 2026-09-14 refresh-merge)
> Worktree/branch: `.worktrees/security-c7-boundary` / `feature/security-c7-boundary-0-20260914`
> Authority refs: `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md`, `A-SRL-1-threat-model-review.md` (P2-1), `P-SRL-RUNTIME-VERIFICATION-MATRIX.md`

## 1. What is already implemented (measured on this base)

`uv run --extra product-test pytest tests/product/test_srl_event_admission.py test_srl_event_admission_contracts.py test_srl_event_authority.py test_srl_event_store.py test_srl_security_boundary.py -q` → **243 passed**.

So the following are DONE, not gaps:

- `P-SRL-EVENT-CONTRACT-1` (G1): typed `EnvironmentEvent` admission, authenticated source refs, idempotent dedupe/replay, tenant/workspace/principal scope binding, fail-closed on forged/cross-scope/deleted rows (`srl_event_admission.py`, `srl_event_authority.py`, `srl_event_ledger.py`, `srl_event_store.py`).
- Much of `P-SECURITY-BOUNDARY-0` (G2): credential refs never return resolver material, root surface does not export the full credential reader, no direct operational-proposal bypass, injected situated authority is rejected, scoped reader hides foreign receipt/event/trace, scope-column tamper fails closed, restart/concurrency preserve isolation.

## 2. Genuine gaps (this task)

- **G3 — C7 is a logical, in-process invariant, not a separate fault domain.** `CorrectionAuthority` (`governance.py:99`) with `guard_unchanged` runs in the same process as TaskService/event store/policy. A worker compromise, a store replay, or an in-flight effect race is not tested to fail closed.
- **G4 — A-SRL-1 review P2-1 is open.** The contract layer does not show how C7 manifests (signature field / external receipt digest / runtime-only gate). This weakens audit replayability of the correction root.
- **G5 — The exact interruption semantics are unstated.** Does a correction interrupt an already-in-flight effect, or only block later commits, and is compensation guaranteed?

## 3. Design options for G3/G4 (pick in CTO review; not yet chosen)

| Option | C7 manifestation | Fault domain | Cost/risk |
|---|---|---|---|
| A | external receipt digest field on authority records + runtime check | still in-process; attestation is cryptographic | low; does not isolate a compromised process |
| B | C7Checker as a separate OS process/endpoint (like `shell_ipc`), runtime calls it before activation/commit | real process boundary | medium; needs IPC, availability handling, fail-closed |
| C | hybrid: external ed25519 correction-epoch attestation + a process-separated verifier | strong | highest; needs key custody |

Recommendation (CTO to confirm): **B for the first slice** (real fault domain, no key custody), with the external receipt digest from A recorded on every activation/commit for audit replayability. C can later replace B's verifier.

## 4. RED tests to write (must fail before implementation)

```
tests/product/test_srl_c7_fault_injection.py
  test_c7_halt_blocks_later_commit_under_worker_compromise
  test_c7_epoch_replay_does_not_reauthorize
  test_c7_inflight_effect_race_is_fail_closed
  test_c7_verifier_unavailable_fails_closed
  test_c7_external_receipt_digest_is_bound_on_activation_and_commit
  test_c7_boundary_statement_matches_behavior   # interrupts-in-flight vs blocks-later
```

Each test must fail if the C7 check is skipped, if a replayed epoch re-authorizes, if an unavailable verifier fails open, or if the receipt digest is not bound.

## 5. Gates

| Gate | Exit condition |
|---|---|
| G1 event contract | already green (243 tests) — keep green |
| G2 security boundary | already green — keep green |
| G3 C7 fault injection | worker compromise / store replay / in-flight race / verifier-unavailable all fail closed |
| G4 C7 manifestation | decision recorded; external receipt digest bound; audit replay possible |
| G5 boundary statement | behavior matches a written statement (in-flight interrupt vs later-commit block) |
| G6 independent review | cross-provider APPROVE at the exact merged head |

## 6. Authority and claim boundary

- C7 semantics must not be weakened; this task only adds a fault domain + attestation, never a bypass.
- No production key custody, no release; C7 remains founder/founder-reserved.
- This is a `A` (architecture invariant) capability; it protects the permanent correction-root boundary, not a user-facing feature.

## 7. Explicit non-claims

- No autonomy, Alpha, release or HCW claim.
- "Non-bypassable" may only be asserted to the extent G3 actually tests.
