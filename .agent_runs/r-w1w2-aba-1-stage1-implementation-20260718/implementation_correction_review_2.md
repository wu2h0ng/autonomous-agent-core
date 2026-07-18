# Independent Correction Re-review 2

- Reviewer: `aba_implementation_reviewer`
- Exact head: `721928236cdfec3c13374bdd88c7cb17a3f75c39`
- Reviewed base: `07476e5a1d2b5fac20335906d61102db0f3e1166`
- Verdict: `REVISE`
- Findings: `P0=0 / P1=1 / P2=0`

## Remaining P1

The malformed-direct-bundle and malformed-direct-seal/receipt reproductions are
closed. The post-seal verifier also uses only the canonical reparsed objects.
The qualifier, however, reparsed and compared the inputs but then discarded its
canonical manifest/acceptance objects and reused the originals for counters,
relations, roots and projections.

A stateful manifest returned canonical mapping A during parser replay and mapping
B on later calls while forcing equality. The root then committed to B while the
projected stage-spec came from original object A:

```text
changing_object_qualifies=True
root_projection_diverge=True
```

The minimum correction is to retain canonical manifests and acceptances and use
only those snapshots after replay. No original input object may be called again.

This review does not accept B1-B5 or authorize experiment implementation,
freeze, run, a result or a research claim. The experiment remains
`EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE /
NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
