# SPINE-E2E-2 Result

Date: 2026-07-13

Track: Product evaluation

Verdict: **INVALID — frozen provider-bank binding defect, not Product failure**

## Result boundary

The single fresh, frozen SPINE-E2E-2 run failed fail-closed during prepare before any Product
case, provider HTTP call, workspace fixture, or case database existed. It is neither PASS nor
Product NOT_PASS and supplies no long-horizon evidence.

- Candidate target: ec6c07fa43dcc92b23e510e69991ed841a5c85e4
- Runner target: 804c8d54bf5b78d9d850edb452db4affe3c1cd22
- Frozen mechanisms: 50; post-failure drift zero
- Frozen context: 458004cd5a8117b38115ad2dfc72cc6e0915b7bc38d3bb51e788c635e54ff658
- Phase chain: prepare_started -> prepare_failed, ordinals 0..1
- Failure code: INVALID_INTERNAL_ERROR
- Provider ledger: absent
- Result JSON: intentionally absent; external result verification reports result-missing

## Mechanical evidence

- prereg lock SHA-256: 2d17e51086d5437f4cbeef929f675e332dcea7793a057589c9da59106d48f4b2
- canonical prereg SHA-256: 2a83760d4a9ec816b152c3e7ff5fbb2ecb4731d5030c4cd87fb29d2a1a402210
- source spec SHA-256: 4481b1801de7772f0e7006a86ad75206f389f8fe169fd6d917ad59e136caba75
- phase ledger SHA-256: fab12205df29794d1d52970ef30f0f8cbfa7d9ff662dfb2d81461c006162f516
- prepare failure SHA-256: 17e21531c88f9cc59b87e9551ed3a64374a7c346bf8469c8d42418f7763e7ceb
- exact-content manifest SHA-256: 586942dab04559003041e8fc26a5926bb5e069f9be4cfdae0977ffa438c5bd55

## Root cause

All twelve frozen provider-bank requests changed model identity to spine-e2e-2-frozen while their
declared request digests remained the predecessor SPINE-E2E-1 values. Recalculation with the
frozen request_body_digest function yields 12/12 mismatches. FrozenProviderServer therefore
raised invalid provider bank entry while loading the first row.

A second frozen incompatibility was also confirmed but not reached: the shared provider server
still requires bearer spine-e2e-1-local-dummy while the successor surface supplies
spine-e2e-2-local-dummy.

Post-run verification exposed a third evaluator defect: the no-argument preflight unit test reads
the real fixed run-root phase ledger. Once the legitimate failed-run ledger exists, that test
raises INVALID_EVALUATION_GENESIS instead of using an isolated temporary ledger. The post-run
suite therefore records 424 passed, 1 failed, 1 skipped. This is evaluator-test contamination by
preserved evidence, not a Product regression: the separate post-run Product suite passed 169 with
1 skipped. The frozen evaluator test is not repaired or bypassed.

These are instrument/input defects inside correctly frozen bytes, not post-freeze drift and not a
Product outcome.

## Binding disposition

- Preserve this run unchanged as INVALID.
- Do not modify the bank, continue, retry, rerun, or rescue this identity.
- Do not fabricate evaluation/result.json after the failed phase.
- SPINE-E2E-2 PASS is absent.
- LH-RECOVERY-1A D2 is not constructed.
- Parent LH-RECOVERY-1 remains BLOCKED_NOT_RUN.
- Any further successor would require another new identity, preregistration, independent reviews,
  freeze, and fresh run.

Independent result adjudication: **ACCEPT INVALID**.
