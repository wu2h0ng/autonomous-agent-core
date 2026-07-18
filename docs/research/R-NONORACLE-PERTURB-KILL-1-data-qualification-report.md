# R-NONORACLE-PERTURB-KILL-1 Data Qualification

> Status: `DATA_ACQUIRED / TARGET_SUPPORT_MET / MARGIN_0 / HMAC_ASSIGNMENT_COMMITTED / SELECTIVE_ZIP_PROVENANCE_BOUND / NOT_FROZEN / NOT_RUN`
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
- The qualification-only Zenodo allowlist is bound by
  `R-NONORACLE-PERTURB-KILL-1-selective-zip-provenance.json`: paired stable
  transport probes, the terminal EOCD, all `148` central-directory entries and
  five exact local-header-plus-compressed-member ranges were replayed through
  the fail-closed extractor. The resulting donor-call and four stimulated-well
  Souporcell files are byte-identical to the qualification inputs.

The earlier provisional value `41` is void. That scan incorrectly included
`CRISPR Guide Capture` rows in RNA total UMI and detected-feature metrics. The
authoritative scanner counts only the first `36,601` `Gene Expression` rows and
uses mitochondrial rows `36,560..36,572`; its output is byte-identical to the
RNA-only metrics digest above.

## Blocker status

1. `SINGLET_AUTHORITY_AMENDMENT_REQUIRED` — closed by the design amendment in
   this patch, pending independent review of exact bytes.
2. `SELECTIVE_ZIP_PROVENANCE_MANIFEST_REQUIRED` — **closed locally** by the
   real selective-range manifest. The allowlist contains only `donor_calls.txt`
   and stimulated-well `1..4` `clusters.tsv`; the outcome/category guide map is
   explicitly forbidden and absent. Independent exact-byte acceptance remains
   a separate pre-freeze review action, not a reason to reopen this data gap.
3. `NTC_HMAC_SPLIT_PENDING_SCORER_CUSTODY` — **closed as an assignment
   commitment only** by the custodian's one permitted draw. The public receipt
   SHA-256 is
   `7d679d8f5f98b56f183a0885350fa3d24468920781557eaa55eec0139f64c50a`.
   Its disjoint four-guide NTC sides contain `97..150` retained cells in every
   natural block, above the predeclared `>=25` gate. The public-side NTC A/B
   groups contain two guides each, both cover all eight blocks and expose only
   their `46..93` aggregate cell-count range. This public count projection was
   derived from the already committed assignment without re-keying or retry.
   The key and all guide/target identities remain scorer-private; the
   repository contains commitments and aggregate counts only.

Independent leakage finding/non-negotiable: the builder and canonical verifier
must never receive an outcome/category guide-map. Target families come only
from the terminal numeric suffix of GEO guide feature IDs. This finding is not
counted as a fourth blocker because the API and tests already enforce it.

No mechanism, outcome scorer, baseline, training, freeze or result run is
authorized or reported here. `HMAC_ASSIGNMENT_COMMITTED` is not split evidence
and does not authorize the builder to receive the hidden assignment.
