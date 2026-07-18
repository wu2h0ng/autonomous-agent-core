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
only when its submitted reason exactly matches a frozen `SOURCE_GAP` gold reason.

## Frozen inputs required before any run

1. Hidden paired portfolio snapshots and their exact hashes.
2. Frozen gold items/reasons and scorer input manifests.
3. Frozen randomized or counterbalanced order assignments.
4. A named independent adjudicator identity.
5. Founder participant timing and the exact timing-capture procedure.

Until all five exist and an independent freeze review accepts their exact
content, `preregistration.json` remains `NOT_FROZEN` and no participant run is
authorized.

## Mechanical gates

The future primary gate is at least 30% lower median operator seconds in the
treatment arm. Mandatory-event recall must remain 100%, false `DONE_VERIFIED`
must remain zero, false attention cannot exceed baseline, and the treatment may
add no execution authority or external effect. Green tests here validate only
schema and scoring mechanics; they do not satisfy any gate.
