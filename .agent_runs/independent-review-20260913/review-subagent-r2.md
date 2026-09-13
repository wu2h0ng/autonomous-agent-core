# Independent Adversarial Re-Review (round 2) — I-23 trust anchoring

> Reviewer: independent adversarial subagent (read-only on source/test)
> Worktree: `autonomous-agent-core/.worktrees/srl-closed-loop-1`
> Branch: `feature/srl-closed-loop-1-20260913`
> Code head under review: `a2634d81` (`fix(srl): bind I-23 producer identity to the trusted authority record`)
> Base: `0045aeea`; immediate parent: `c76f28fa`
> Prior blocking review: `.agent_runs/independent-review-20260913/review-crossprovider.md` (NO_APPROVE)
> Artifacts written: this file only. No source/test edits, no worktrees, no /tmp.

## Scope

Resolve the cross-provider NO_APPROVE: was I-23 (`producer != acceptor`) still defeatable because the
producer identity came from caller-mutable `ProposedGoal.constraints`? Determine whether `a2634d81`
anchors I-23 to a trusted (digest-verified, registry-resolved) record and attempt the five specified
bypasses plus idempotency.

## Change under review (diff `c76f28fa..a2634d81`)

- `srl_ports.py:90` — added `producer_instance_id: NonEmptyStr` to `ActivationAuthority`; contract is
  `frozen=True`, `extra="forbid"`, `NonEmptyStr` strips whitespace and requires `min_length=1`.
- `srl_activation_gate.py:151-156` — resolves `authority.authority_id` via the injected trusted
  registry and rejects unless `content_digest(trusted) == content_digest(authority)`.
- `srl_activation_gate.py:177-185` — requires the caller goal's `assessor-instance:` to be present and
  equal to `authority.producer_instance_id` (fail-closed), then evaluates I-23 as
  `authority.authority_instance_id == authority.producer_instance_id` — i.e. entirely on the
  digest-verified authority record.
- `srl_runtime.py:319-328` — removed `_extract_producer_instance_id` (goal-constraint read); I-23 now
  evaluated from `authority.authority_instance_id == authority.producer_instance_id`.

## Verification (reviewer-run)

- `uv run --extra product-test pytest tests/product/test_srl_task_activation_gate.py tests/product/test_srl_runtime_invariants.py -q` → **63 passed**.
- `ruff check --no-cache` on the 5 touched files → **All checks passed**.
- `pyright` on `srl_ports.py` + `srl_activation_gate.py` + `srl_runtime.py` → **0 errors / 0 warnings**.
- `git diff --stat c76f28fa..a2634d81` → 7 files, source delta confined to `srl_ports.py` (+8/−1),
  `srl_activation_gate.py` (+10/−8), `srl_runtime.py` (+5/−20), plus 2 test files and 2 review docs.
  No contract/port drift; no production code constructs `ActivationAuthority` (only tests do).

## Core question — is I-23 now anchored to the trusted record? **YES**

`producer_instance_id` is now a field of the digest-verified `ActivationAuthority`. The gate compares
`content_digest(trusted) != content_digest(authority)` (`srl_activation_gate.py:155`) *before* any
binding/I-23 check, and `content_digest` serializes the full model (`model_dump(mode="json",
exclude_none=True)`, `sort_keys=True`). A caller can therefore no longer mutate `producer_instance_id`
(or any other authority field) without failing registry digest resolution. I-23 is decided from that
trusted record (`:184`), so mutating caller-supplied goal constraints can no longer influence it.

## Per-bypass results (reviewer-run, inline)

| # | Bypass | Result |
|---|---|---|
| (a1) | Trusted **same-instance** record; caller forges `producer_instance_id="someone-else"` to dodge I-23 | **REJECTED** `AUTHORITY_NOT_RECOGNIZED` (digest mismatch) |
| (a2) | Trusted distinct record; caller forges `producer_instance_id="forged-producer"` | **REJECTED** `AUTHORITY_NOT_RECOGNIZED` |
| (b) | Forged goal `assessor-instance:other-instance` ≠ trusted authority producer | **REJECTED** `AUTHORITY_BINDING_MISMATCH` |
| (c) | Same-instance authority (`authority_instance_id == producer_instance_id`) | **REJECTED** `SAME_INSTANCE_PROPOSE_AND_ACCEPT` |
| (d) | Empty goal producer `assessor-instance:` | **REJECTED** `PRODUCER_IDENTITY_UNAVAILABLE` |
| (d) | Whitespace goal producer `assessor-instance:   ` | **REJECTED** `PRODUCER_IDENTITY_UNAVAILABLE` (stripped → absent) |
| (d) | Whitespace `authority.producer_instance_id` | **REJECTED at construction** (`NonEmptyStr` ValidationError) |
| (e) | Cross-mandate authority (`mandate_id="mandate-2"` vs goal `mandate-ref:mandate-1`) | **REJECTED** `AUTHORITY_BINDING_MISMATCH` |
| rt | Runtime: forged authority producer (distinct trusted) | **REJECTED** `AUTHORITY_NOT_RECOGNIZED` (delegated gate) |
| rt | Runtime: same-instance authority | **REJECTED** `I-23: same instance cannot produce and accept evidence` |
| rt | Runtime: empty producer goal | **REJECTED** `denied:PRODUCER_IDENTITY_UNAVAILABLE` |

All five specified bypasses fail closed on both the gate and the runtime path.

## Idempotency — still idempotent

Via `TaskServiceCreationAdapter` over a real `TaskService`:
```
first  = gate.activate(goal, trusted) -> activated=True, task_id=task:srl:goal-1
second = gate.activate(goal, trusted) -> activated=True, task_id=task:srl:goal-1
first.task_id == second.task_id -> True
```
The idempotency key is deterministic from the proposal/`ensure_task` event identity; the newly added
`producer_instance_id` does not participate in the durable `Goal` construction, so identical
re-activation is unchanged. Conflicting re-activation remains fail-closed (`test_conflicting_authority_reactivation_fails_closed`).
No idempotency regression.

## Findings

### F1 — INFO (non-blocking) — no independent assessment→producer authority; latent, documented
`srl_activation_gate.py:166-173`, `srl_ports.py:90`. The authority record's `producer_instance_id` is
trusted only because the *authority registry* is trusted and digest-bound. There is still no independent
assessment registry proving that `producer_instance_id` actually produced `source_assessment_id`; a
trusted registry populated with an incorrect producer would admit. This is the pre-existing latent H3
gap recorded by `review-r3.md`/`review-r4.md`, explicitly outside this fix's mandate (no assessment
registry in scope). Not a regression, not blocking.

### F2 — INFO (non-blocking) — runtime precheck is not independently anchored
`srl_runtime.py:319`. The runtime has no registry reference, so its own I-23 precheck compares two
caller-supplied authority fields; the security guarantee on the runtime path still comes from the
injected trusted `TaskActivationPort` (the gate) re-verifying via digest. This is intended
defense-in-depth (the port is the trusted boundary), but worth stating: end-to-end safety on this path
presupposes the injected port is `TrustedTaskActivationGate`. Non-blocking.

### F3 — INFO (non-blocking) — test intent drift
`tests/product/test_srl_runtime_invariants.py:453-485`. `test_p0_runtime_rejects_mismatched_authority_without_producer_metadata`
now rejects because `authority_instance_id == producer_instance_id` (same-instance I-23), not because
of the wholly-mismatched mandate/mission/assessment fields its name/docstring imply. The assertion is
genuine and bypass-detecting for the new anchor, but the test no longer exercises the "mismatched
authority" case it was named for. Non-blocking test-quality note.

### F4 — INFO (pre-existing, non-blocking) — unused members
`ActivationDenialReason.TRUSTED_AUTHORITY_MISSING` and `CreatedTask.run_id` remain unused (carried from
`review-r3.md` H5). Not part of this fix.

## Required changes

None. The cross-provider blocking finding is resolved. F1–F4 are informational and/or pre-existing and
do not re-open the trust boundary.

## Final verdict

**APPROVE**

The prior NO_APPROVE (I-23 producer identity derived from caller-mutable `ProposedGoal.constraints`) is
resolved: `producer_instance_id` now travels in the digest-verified, registry-resolved
`ActivationAuthority`, and I-23 is evaluated on that record. All five specified bypasses and both
caller-forgery variants fail closed; empty/whitespace producers fail closed; cross-mandate fails closed;
idempotency is intact; 63 targeted tests pass; ruff/pyright clean. No push/merge performed.
