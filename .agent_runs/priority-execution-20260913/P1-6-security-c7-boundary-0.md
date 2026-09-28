# Task Packet — SECURITY-C7-BOUNDARY-0

> Status: `GOAL_CARD_AND_VERIFICATION_PLAN / RECOMMEND_ONLY / NO_IMPLEMENTATION_AUTHORIZATION`
> Track: product
> primary_class: A  secondary_class: P/E
> Portfolio lane: SRL_CRITICAL_PATH
> Authority refs: `A-SRL-1-threat-model-and-authority-invariants.md`, `A-SRL-1-threat-model-review.md` (P2-1), `P-SRL-RUNTIME-VERIFICATION-MATRIX.md` rows for `P-SRL-EVENT-CONTRACT-1` and `P-SECURITY-BOUNDARY-0`

## 1. Goal Card

**Problem A (C7 fault domain).** C7 is semantically non-writable/non-bypassable but is composed in the same process as TaskService, event store, policy and correction authority. This proves normal-path enforcement, not survival under worker compromise, store replay or in-flight effect races. The independent review (P2-1) notes C7's contract-layer manifestation is unspecified.

**Problem B (security/tenant/credential).** `P-SECURITY-BOUNDARY-0` is a required pre-M1 gate and is still `V0_SPEC`. Without it, local slices cannot move to pilot.

**Target A/P.** (1) An explicit, testable C7 representation (external receipt/epoch attestation or an explicitly justified runtime gate) with a fault-injection suite; (2) tenant/workspace/principal scope, trace redaction and credential-lease non-disclosure enforced fail-closed.

**Non-goals.** No production KMS, no full tenancy buildout, no distributed runtime, no C7 semantics change.

## 2. First failing tests

```
tests/product/test_srl_event_contract.py
  test_unauthorized_event_binding_rejected
  test_duplicate_environment_event_is_idempotent
  test_event_schema_rejects_unknown_effect_payload

tests/product/test_security_boundary.py
  test_trace_does_not_leak_secret_payload
  test_cross_tenant_event_rejected
  test_credential_ref_never_serializes_secret
  test_revoked_mandate_reused_in_assessment_fails_closed

tests/product/test_c7_fault_injection.py
  test_c7_halt_blocks_later_commit_under_worker_compromise
  test_c7_epoch_replay_does_not_reauthorize
  test_c7_concurrent_inflight_effect_race_is_fail_closed
```

## 3. Gates

| Gate | Exit condition | Class |
|---|---|---|
| G1 event contract | authenticated + scoped + schema-valid events only reach the steward | P/A |
| G2 security boundary | no raw secret/PII in trace; tenant/workspace/principal enforced | A |
| G3 C7 fault injection | worker compromise / store replay / in-flight race all fail closed | A |
| G4 C7 manifestation decision | review P2-1 closed: signature field, external receipt digest, or justified Runtime gate | A |
| G5 boundary statement | explicit: does correction interrupt an in-flight effect or only block later commits? | A |
| G6 independent review | P0=0/P1=0, builder_id != reviewed_by | E |

## 4. Authority boundary

- Implementation requires a CTO gate; this packet is not that gate.
- Do not claim "non-bypassable" beyond what G3 actually tests.
- No production identity/KMS claim; local credential-lease scope only.
