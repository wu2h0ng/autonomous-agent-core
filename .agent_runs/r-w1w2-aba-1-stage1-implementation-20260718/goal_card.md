# Goal Card

- Objective: Define a qualification-only public protocol, validator/state-machine cast and unresolved preregistration template for `R-W1W2-ABA-1` Stage 1. No arm execution, research evidence, freeze or run readiness may be produced by this package.
- Business value: Reject an invalid, unfair or custody-unsafe preregistration before another large harness is built, and reduce the cost of any later independently authorized freeze.
- Task type: research
- Requirement class: `R`
- Risk level: `R3`
- Owner/coordinator: `root`
- Canonical clean base: Agent OS `origin/main@6c94bd8c6f27da6d327a6841fd5c434e8e555206`
- Imported approved design: `76c92c531d2f00fe2ddca754495f14079fedebf8`, cherry-picked as `61f417599bdab9a6410125a184590dbaec75a242`

## Current Authority

- Authorized now: exact-byte route cast, unresolved public preregistration template, legacy implementation characterization, public qualification-scaffold design and independent review.
- Not authorized now: candidate/baseline/scorer code, hidden unit selection, hidden material handling, provider result calls, training, freeze, run permit, result run, merge to `main`, release or any autonomy/value claim.
- The public code scopes below remain write-closed until the exact decision is `QUALIFICATION_SCAFFOLD_CAST_APPROVED`.
- Any post-review change to a reserved source path re-closes that path until an exact path-delta review approves it.
- That decision never changes the concurrent experiment state: `EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.

## Scope Include

- `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/**`
- reserved after cast approval only: `src/aac/r_w1w2_aba/contracts.py`
- reserved after cast approval only: `src/aac/r_w1w2_aba/canonical.py`
- reserved after cast approval only: `src/aac/r_w1w2_aba/validators.py`
- reserved after cast approval only: `src/aac/r_w1w2_aba/stage1_state.py`
- reserved after cast approval only: `src/aac/r_w1w2_aba/public_custody.py`
- reserved after cast approval only: `tests/research/r_w1w2_aba/**`

The `src/aac/` location is mandatory because `codebase_index.md` classifies it as the canonical Research Track package. This scaffold must not create a second top-level Python namespace or enter Product packages.

## Scope Exclude

- private scorer/freezer storage and every `scorer-private/**` path
- hidden source identities, hidden unit mappings, hidden tests, mechanical paths, keys and key-derived material
- result artifacts and every `results/**` path
- `**/scorer.py`, `**/freezer.py`, `**/curator.py`, `**/runner.py`, `**/executor.py`, `**/candidate.py`
- private scorer/freezer service, arm behavior/executor, real curator, provider/tool adapter, freeze/run issuer or local signer implementation
- Product Runtime, Task activation, capabilities, permissions, C7, W5 and release surfaces

## Required Outputs

- `context_pack.json`
- `implementation_plan.md`
- `preregistration_candidate.md`
- `verification_report.md`
- `advisory_cast_review.md`
- `qualification_cast_review.md`
- future after code only: `implementation_review.md`
- `messages.jsonl`

## Admission Checks

- approved design bytes and source commit are exact-bound
- Stage 1 remains exactly 3 families × 1 independent unit × 5 arms
- dispositions cannot emit `MET`, `NARROW_MET`, `REDUCES_TO_*`, Product evidence or autonomy evidence
- the five prerequisite bundle states are explicit and fail closed when unaccepted
- no LLM, reviewer, tool or ordinary CI path can receive private custody material
- legacy code is `CHARACTERIZATION_ONLY` unless an independent review proves exact treatment compatibility

## Exit State For This Package

Exactly one of:

- `QUALIFICATION_SCAFFOLD_CAST_APPROVED / EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`; or
- `QUALIFICATION_SCAFFOLD_CAST_REVISE / EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`; or
- `PARK_UNGROUNDABLE_OR_CUSTODY_UNAVAILABLE / NOT_FROZEN / NOT_RUN`.
