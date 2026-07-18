# R-NONORACLE-PERTURB-KILL-1 Data Qualification

> Status: `DATA_ACQUIRED / TARGET_SUPPORT_MET / MARGIN_0 / NTC_SPLIT_PENDING / DESIGN_PROVENANCE_REVISE / NOT_FROZEN / NOT_RUN`
> Scope: pre-freeze data qualification only
> Base: `6204666232683836226d2fe51c970abeb75acb84`

## Independent evidence

- GEO matrix SHA-256: `38113a6099f117ed1449cfde2f9f61bf10379da262af49364308f1a0602e3fc1`.
- RNA-only metrics SHA-256: `701827190ea31d9e3aecb7722e3022b02fe1ebd880e94c483b6d6425f4e58104`.
- Independent qualification script SHA-256: `eebe346759d28e401fc5d9f4fd4382f7cf91889bbff1555790316dca2cddcbee`.
- Fixed QC plus raw-status `singlet` join leaves `28,412` stimulated cells.
- Exactly `40` targets meet both-guide support in all eight opaque
  `donor x well` blocks. The gate is `>=40`, therefore the margin is `0`.
- The surviving support table has `640` guide-by-block aggregates with counts
  from `10` through `77`, inclusive at the observed extrema.
- The canonical aggregate-only verifier independently reproduced the same
  `28,412 / 40 / 640 / 10..77` qualification and emitted no target IDs.

The earlier provisional value `41` is void. That scan incorrectly included
`CRISPR Guide Capture` rows in RNA total UMI and detected-feature metrics. The
authoritative scanner counts only the first `36,601` `Gene Expression` rows and
uses mitochondrial rows `36,560..36,572`; its output is byte-identical to the
RNA-only metrics digest above.

## Open blockers

1. `SINGLET_AUTHORITY_AMENDMENT_REQUIRED` — closed by the design amendment in
   this patch, pending independent review of exact bytes.
2. `SELECTIVE_ZIP_PROVENANCE_MANIFEST_REQUIRED` — tooling is implemented, but
   the real allowlisted-member manifest has not been produced or accepted.
3. `NTC_HMAC_SPLIT_PENDING_SCORER_CUSTODY` — no key or split was generated.
   The custodian gets one attempt; either side below 25 cells in any block is
   immediate `PARK` with no retry.

Independent leakage finding/non-negotiable: the builder and canonical verifier
must never receive an outcome/category guide-map. Target families come only
from the terminal numeric suffix of GEO guide feature IDs. This finding is not
counted as a fourth blocker because the API and tests already enforce it.

No mechanism, scorer, baseline, training, freeze, HMAC selection or result run
is authorized or reported here.
