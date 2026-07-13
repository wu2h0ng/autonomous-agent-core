# SPINE-E2E-2 Fresh Instrument-Validity Successor Plan

Status: `DRAFT_NOT_REVIEWED_NOT_FROZEN_NOT_RUN`

## Objective

Build a fresh successor instrument that preserves the Product, lease, provider,
timing, corpus, workspace, terminal replay, baseline, and adjudication gates
while replacing the predecessor's invalid total-receipt observation variable.

## TDD sequence

1. Freeze successor RED tests for strict receipt parsing, apply-key extraction,
   interrupt prefix-plus-one, resume equality, composition behavior, and
   dependency preflight.
2. Implement only `product_evals.spine_e2e_2`; predecessor paths stay immutable.
3. Bind interrupt to one appended `workspace.apply_patch` idempotency key and
   resume to byte-for-byte equality of the complete apply-key sequence.
4. Preserve total action receipt telemetry and allow a legitimate
   `workspace.run_tests` receipt during normal resume.
5. Require Product and runner interpreter imports before evaluation genesis.
6. Verify focused successor, unchanged predecessor, full Product/eval, Ruff,
   formatting, and excluded-path diff gates.

## Authorization boundary

The preregistration remains an unfrozen draft. No predecessor permission,
review, lock, ledger, anchor, context digest, or result is successor authority.
This task performs no freeze, phase execution, adjudication, commit, or result
claim; independent review and new authorization remain mandatory.
