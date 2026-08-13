# Independent Qualification Scaffold Implementation Review

- Reviewer: `aba_implementation_reviewer`
- Exact head: `1792b7b523c3b6638e15219c24ca3761dda9b0a2`
- Base: `669e81933efaa4fb4e5938fc12abc0c48f3d2cae`
- Verdict: `REVISE`
- Findings: `P0=0 / P1=3 / P2=2`

## P1

1. `parse_bundle_manifest(..., enforce_required_children=False)` is a public escape hatch, and qualification does not independently restore required B1-B5 semantic children. Single-child bundles can qualify.
2. The qualification root binds only manifest digests. It does not bind acceptance/review digests or an external expected acceptance root, so review provenance can be changed without moving the root.
3. Global seal and closed receipt accept arbitrary 15-slot, stage-spec, block and exact-subject values rather than exact public commitments projected from the admitted bundles. Caller-minted inputs can reach `ADVANCE_TO_STAGE2_DESIGN`.

## P2

1. Child order is treated as a set for validation but affects the manifest digest. Canonicalize by `child_id`.
2. Verification must record the exact Pyright command/environment; direct invocation and `uv run` do not have identical import-path behavior.

## Confirmed

- `121 passed`; Ruff clean; Pyright clean only under the recorded `uv`/`PYTHONPATH=src` environment.
- Safety, integrity, feasibility and nondominance precedence is correct.
- No file, environment, network, provider, runner, executor, scorer, freezer, signer, freeze, run or private-custody API exists.

This review does not authorize experiment implementation, B1-B5 acceptance, freeze, run or research evidence. The experiment remains `EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
