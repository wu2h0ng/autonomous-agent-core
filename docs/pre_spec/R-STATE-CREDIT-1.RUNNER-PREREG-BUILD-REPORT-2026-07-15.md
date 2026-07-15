# R-STATE-CREDIT-1 Runner/Prereg Build Report

> Status: `IMPLEMENTED_LOCAL / BINDINGS_REQUIRED / NOT_REVIEW_ACCEPTED / NOT_FROZEN / NOT_RUN`
>
> Base: `9db9ad9de824a795399ea2e2dc249690b169bf7e`
>
> Branch: `codex/r-state-credit-1-runner-prereg-20260715`

## Delivered

- Provider-neutral, API-only typed `ActorClient`, request, response, actor,
  corpus, scorer, C7, run-authority, and native-freeze contracts.
- Fail-closed verification of the native lock, target Git head, candidate,
  exact-content manifest, corpus artifacts, and scorer artifacts before the
  atomic execution claim.
- One-shot raw runner with `O_EXCL` start/result/terminal records, pre-start C7
  refusal, post-start C7 invalidation, interruption invalidation, contract-fault
  invalidation, and permanent same-lock no-rerun behavior.
- Raw `R_FINAL_RAW / RAW_NOT_ADJUDICATED` schema. It contains no verdict,
  winner, selected arm, or training trigger.
- Native preregistration YAML and exact-content manifest covering all 13
  declared `mechanism.files` artifacts without a spec/manifest hash cycle.
- Tests-only fakes. There is no production provider, corpus, or scorer
  implementation and no CLI entry point.

## TDD evidence

The implementation was driven through separate failing tests for missing typed
contracts, native freeze verification, formal YAML/manifest compatibility,
one-shot execution, C7 abort, interruption, and untyped scorer output. Each was
made green before the next boundary was added. The final new test module has 27
passing tests.

## Verification

- New and directly related Research tests: `91 passed`.
- Full Research suite: `1237 passed, 16 skipped`.
- Native workflow prereg review/freezer compatibility: `20 passed`.
- Ruff lint: clean.
- Ruff format check: clean.
- Pyright: `0 errors, 0 warnings, 0 informations`.
- Native exact-content manifest verification: `intact: true`, no drift.
- Existing candidate validation:
  `VALID_CANDIDATE_ONLY`, 11 source files,
  `freeze_authority=false`, `run_authority=false`,
  `training_authority=false`.
- Git diff check: clean.

## Deliberately unresolved freeze blockers

The formal preregistration remains fail-closed until a later lane supplies real,
exact artifacts for all of the following:

1. actor provider/model/API binding and prompt/tool-schema bytes;
2. held-out public and sealed-referee corpus artifacts;
3. scorer source and metric/verdict-grammar tests;
4. independent reviewer identity and accepted exact-content review;
5. independent RR-0029 architecture-theory review with RR-0031 binding;
6. externally owned C7 abort identity;
7. explicit founder/CTO result-bearing run authorization.

No `prereg_review.json`, `architecture_theory_review.json`, RR-0031 record,
native lock, result, training artifact, provider call, push, merge, or release was
created by this build lane.

## Claim ceiling

`IMPLEMENTED_LOCAL_RUNNER_PREREG_DRAFT / BINDINGS_REQUIRED /
NOT_REVIEW_ACCEPTED / NOT_FROZEN / NOT_RUN / NO_TRAINING`
