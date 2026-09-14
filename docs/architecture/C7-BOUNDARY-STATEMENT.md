# C7 Boundary Statement (option A)

> Status: `ACTIVE / SCOPED` (2026-09-14)
> Scope: how C7 manifests at the contract layer, and exactly what the current slice does and does not enforce.
> Related: `A-SRL-1-threat-model-and-authority-invariants.md` (review P2-1), `P1-6` gap assessment.

## 1. Manifestation

C7 is manifested to the runtime as a **digest-bound `C7ClearanceReceipt`** issued by the externally-owned `CorrectionAuthority` (`CorrectionReadPort`) and verified before a commit:

- `C7ReceiptIssuer.issue(task, run, capability)` reads the external authority's correction epoch vector and halt flag, and produces a receipt whose `receipt_digest` binds every field.
- `C7ReceiptVerifier.verify(receipt)` re-reads the live authority and fails closed (typed error) if the scope is halted, the epoch vector changed (replay), or the authority is unavailable.
- The contract's own validator rejects any persisted receipt whose digest does not match its fields (write-tamper rejected at load).

This closes A-SRL-1 review **P2-1** at the contract level: C7 is no longer only "asserted"; it has a machine-checkable, auditable artifact.

## 2. Interruption semantics (G5)

A receipt is a **pre-commit linearization token**, not an interrupt:

- It blocks commits made after verification when the epoch has changed or the scope is halted.
- It does **not** interrupt an effect that was already dispatched before the correction. Cancellation/compensation of in-flight effects remains the existing `RunCoordinator` effect-custody/compensation path.
- Therefore the correct statement is: *correction prevents later commits and drives compensation where the effect contract supports it; it is not a synchronous interrupt of an executing effect.*

## 3. Enforced vs not enforced

| Property | Status |
|---|---|
| epoch replay / epoch change rejected | enforced (`C7EpochReplay`) |
| halted scope rejected | enforced (`C7AuthorityHalted`) |
| scope binding (tenant/workspace/task/run/capability) | enforced (`C7ReceiptScopeMismatch`); the verification scope is a required argument object, so it cannot be omitted |
| write-tamper of a persisted receipt | enforced (contract validator) |
| authority unavailable | enforced fail-closed (`C7AuthorityUnavailable`) |
| **worker/process compromise** | **NOT enforced by option A** |

Worker/process compromise — a compromised caller that simply never calls `verify` — is not stopped by this module. That requires an external *signed* correction attestation whose key the runtime does not hold (C-lite), which is explicitly a later slice gated on a live consumer. Until then, no "resistant to a compromised process" claim is made.

## 4. Evidence

`tests/product/test_c7_receipt_fault_injection.py`: issue/verify, epoch replay, pre-halt issue, post-halt verify, authority-unavailable, scope mismatch, write-tamper, digest-tamper, and an explicit worker-compromise boundary test.

## 5. Non-claims

No autonomy, Alpha, release or HCW claim. "Non-bypassable" is asserted only to the extent section 3 enforces; the permanent C7 authority itself is unchanged and remains founder-reserved.
