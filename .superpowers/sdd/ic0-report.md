# P-SRL-E2E-FALSIFIER IC-0 implementation report

- Status ceiling: `IMPLEMENTED_NOT_FROZEN / RUN_DENIED / TRAINING_DENIED / CHARACTERIZATION_ONLY`
- Base: `a8c71b152b57ab78720ce8bd09f1ab2f7eed78e9`
- Branch: `codex/p-srl-e2e-ic0-20260717`
- Initial implementation: `6db6f0d`
- First leakage repair: `f4a9aef`
- Custody repair: recorded by the commit containing this report

## Current implementation

`product_evals/srl_e2e_falsifier/contracts.py` now provides:

- closed `PublicContentRole` values `MISSION`, `EVENT`, `PROJECTION`,
  `EVIDENCE`, and `STATIC_BUDGET`;
- closed `PublicContentMediaType` values with no silent default;
- content-addressed `PublicContentManifestEntry` objects binding role, media
  type, exact SHA-256 content digest, and canonical entry digest;
- an ordered, duplicate-free, content-addressed `PublicContentManifest` whose
  root changes when entries or their order change;
- a content-addressed `StaticBudgetConfiguration` and canonical budget bytes;
- a digest-only `PublicResponsibilityState`: manifest root, mandate/binding
  digests, correction epoch, one mission entry digest, ordered event,
  projection and evidence entry digests, one static-budget entry digest, and
  its derived state digest;
- `PublicResponsibilityStateVerifier`, the required trusted construction and
  verification seam. It checks every manifest entry against supplied canonical
  bytes, exact roles, referenced-entry presence, state/manifest root equality,
  and static-budget contract/bytes equality before returning a verified state;
- the existing proposal-only `DecisionCandidate`, separate `BudgetFeedback`,
  and no-authority `ControllerBindingReceipt` contracts.

The former `PublicContentRef`, free-text event/projection/evidence IDs,
arbitrary media strings, `state_id`, raw payload/value channels, and defaulted
`ARM_NEUTRAL_PUBLIC` class were removed. This supersedes the earlier report's
denylist/raw-payload and opaque-ref descriptions.

## TDD and attack coverage

The custody tests were written first. The recorded RED result was collection
failure because the new manifest and verifier API did not exist. The final
focused suite covers:

- self-minted entry, manifest-root and state digests;
- mismatched and missing content bytes;
- wrong role, missing entry/root, duplicate entry and stale root after reorder;
- verification against a different manifest root;
- random/static-budget digest and canonical-byte mismatch;
- absence of free-text IDs, raw values and media fields from state;
- required closed media type rather than a silent content-class default;
- identical canonical state bytes for identical public inputs, with no arm
  metadata accepted by the builder;
- candidate-kind digest sensitivity isolated through the canonical digest
  helper;
- the pre-existing proposal shape, no-effect and binding-receipt attack cases.

## Verification

| Gate | Result |
| --- | --- |
| Focused `tests/product_eval/test_srl_e2e_contracts.py` | `83 passed` |
| Product `tests/product` | `742 passed, 1 skipped` |
| Scoped/project Ruff command | `All checks passed` |
| Project Pyright | `0 errors, 0 warnings` |
| `git diff --check` | clean |

The three known full `tests/product_eval` failures documented on the initial
branch were not modified or rerun for this custody-only repair.

## Claim and authority boundary

This implementation proves deterministic contract and byte/manifest binding
only. It does **not** prove that content is semantically arm-neutral, that an
independent evaluator owns custody, or that a public pack is frozen. Those
claims require a separate independently produced freeze/custody receipt, which
IC-0 does not implement.

No provider or model was called. No controller arm, scored task, reserve task,
training, Task activation, external effect, merge, push, PR, or release was
performed. All disclosed leads remain `CHARACTERIZATION_ONLY`.
