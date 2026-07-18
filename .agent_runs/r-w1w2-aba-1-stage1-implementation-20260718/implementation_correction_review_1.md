# Independent Correction Re-review 1

- Reviewer: `aba_implementation_reviewer`
- Exact head: `07476e5a1d2b5fac20335906d61102db0f3e1166`
- Reviewed base: `1792b7b523c3b6638e15219c24ca3761dda9b0a2`
- Verdict: `REVISE`
- Findings: `P0=0 / P1=1 / P2=0`

## Remaining P1

The original required-child, acceptance/review-root, exact Stage 1 topology,
canonical-order and Pyright-record findings are closed for parsed objects. The
public qualifier and post-seal verifier still trusted directly constructed
dataclasses without replaying their complete closed-schema parsers. Malformed
schema versions, package/subject/review digests, stage IDs, output digests,
cardinality and relation sets could therefore bypass parser invariants.

Reviewer reproductions returned:

```text
malformed_direct_bundle_dataclasses_qualify=True
malformed_direct_seal_receipt_validate=True
```

The minimum correction is to reparse `to_mapping()` at both public trust
boundaries and use only the canonical parsed values. A public qualification or
validated evidence projection remains an integrity projection, not provenance,
acceptance, freeze, run or authority.

This review does not accept B1-B5 or authorize experiment implementation,
freeze, run, a result or a research claim. The experiment remains
`EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE /
NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
