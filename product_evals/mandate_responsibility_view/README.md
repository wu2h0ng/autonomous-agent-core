# Mandate Responsibility View Falsifier

Status: `DESIGN_ONLY / NOT_FROZEN / NOT_RUN`

This directory contains measurement machinery for a future matched human
comparison inside `META-SHADOW-MANDATE-0`. It contains no participant data,
result, run authority, reduced-cognitive-load claim, or autonomy evidence.

## Comparison contract

- Baseline: existing Task, event and log surfaces plus direct model-and-tools use.
- Treatment: the same surfaces plus the Mandate-scoped responsibility view.
- Unit: the same operator on paired, same-complexity hidden snapshots.
- Order: frozen seeded randomization or a mechanically balanced counterbalance.
- Timing: from receipt of the responsibility question through final prioritized
  submission. Only explicit, non-overlapping system-load intervals inside that
  boundary are excluded.
- Missing or abandoned arms invalidate the pair. The scorer never imputes.

The scorer derives one `operator_attention_set` from submitted rows in
`NEEDS_ATTENTION` or `UNKNOWN`. Mandatory recall and false-attention scoring use
that same set. The false-attention denominator is every frozen non-gold linked
item, not only inspected items. An `UNKNOWN` row receives mandatory-event credit
only when its submitted reason set is the exact singleton frozen gold reason and
that reason belongs to the scorer's closed canonical source-gap taxonomy. The
same exact-singleton rule applies to `NEEDS_ATTENTION`; extra reasons receive no
recall credit.

Every gold and order manifest must be accompanied by its expected full-manifest
canonical SHA-256 from an independent external freeze receipt. The scorer never
derives that expected hash from the received manifest. A manifest's self-reported
`manifest_digest` remains an integrity check, not a trust root.

Order labels are also mechanically verified. For `RANDOMIZED`, the supplied
frozen seed material must hash to `randomization_seed_digest`; the low bit of
`SHA-256(seed_material + NUL + pair_id)` determines each pair's direction. For
`COUNTERBALANCED`, the canonical hash of the key plus sorted pair IDs determines
the starting direction, then directions alternate in pair-ID order. The scorer
only validates these proofs; it does not generate, freeze, or assign orders.

## Frozen inputs required before any run

1. Hidden paired portfolio snapshots and their exact hashes
   (`hidden_snapshots`).
2. Frozen gold items/reasons, scorer input manifests, and their external
   expected manifest hashes
   (`frozen_gold_reasons_and_scorer_input_manifests`).
3. Frozen randomized or counterbalanced order assignments, their external
   expected manifest hash, and any randomized seed material
   (`frozen_order_assignments`).
4. A named independent adjudicator identity
   (`independent_adjudicator_identity`).
5. Founder participant timing and the exact timing-capture procedure
   (`founder_participant_timing`).

Until all five exist and an independent freeze review accepts their exact
content, `preregistration.json` remains `NOT_FROZEN` and no participant run is
authorized.

## Mechanical gates

The future primary gate is at least 30% lower median operator seconds in the
treatment arm. Mandatory-event recall must remain 100%, false `DONE_VERIFIED`
must remain zero, false attention cannot exceed baseline, and the treatment may
add no execution authority or external effect. Green tests here validate only
schema and scoring mechanics; they do not satisfy any gate.
