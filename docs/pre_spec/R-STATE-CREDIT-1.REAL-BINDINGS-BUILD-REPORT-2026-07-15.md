# R-STATE-CREDIT-1 Real-Binding Candidate Build Report

> Status: `READY_FOR_KIMI_TECHNICAL_REVIEW / INDEPENDENT_ACCEPTANCE_REQUIRED / NOT_FROZEN / NOT_RUN`
>
> Claim ceiling: `REAL_BINDING_CANDIDATE / INDEPENDENT_ACCEPTANCE_REQUIRED / NOT_FROZEN / NOT_RUN`
>
> Base: `3aba2bd08dd2293139e71ab90640310a032c074b`
>
> Branch: `codex/r-state-credit-1-real-bindings-20260715`

## Delivered

- Direct stdlib Responses API `ActorClient` candidate for the ARK Agent Plan
  profile. It binds the candidate base profile, `/responses`, `ark-code-latest`,
  deterministic decoding, timeout, exact prompt/schema hashes and the
  `ARK_API_KEY` environment reference. It has no arkcli transport, import-time
  credential read or import-time provider call.
- Closed actor response and failure contracts carrying actor/provider
  request/response/output digests, exact bound model identity, token usage,
  provider-reported-or-unavailable cost, latency, timeout and typed error state.
- Deterministic real repository corpus: seven public family JSONL files, twenty
  held-out seeds per family, 140 episodes, 560 checkpoints and four matched arm
  requests per checkpoint. Every episode contains actual repository file bytes,
  a mutation tree and exact rollback tree.
- Public and sealed manifests with exact byte hashes. Referee action-loss truth
  is confined to a separate sealed JSONL and never enters `ActorRequest`.
- Real sealed scorer plus frozen raw metric computation for exact 2,240-row
  coverage, episode/family macro means, A0-minus-A3 paired differences, exact
  one-sided sign probability, loss counts and unsafe replay counts. No verdict
  or route owner exists in this module.
- Read-only external C7 stop adapter using a stable regular-file descriptor and
  exact canonical signal bytes. Owner, epoch and capability-token digest are
  bound before start and checked on every observation. Pre-start stops leave no
  claim; mid-run stops create a permanent no-rerun terminal record.
- Stable-FD/TOCTOU artifact hashing, final-symlink rejection, atomic file plus
  parent-directory fsync, raw-result content digest verification, wrong-arm
  scorer rejection and actor-request-digest rejection.
- Formal YAML updated to real-candidate readiness, generated corpus `case_files`
  naming and explicit unsigned canary/reviewer/C7/run-authority blockers. The
  exact-content manifest covers all mechanism and generated corpus bytes without
  a spec/manifest cycle.

## TDD evidence

Each implementation boundary was first observed failing:

1. missing direct actor module;
2. missing external C7 adapter and owner/epoch/token binding;
3. missing real corpus renderer, public loader and repository rollback path;
4. missing sealed scorer and raw metric computation;
5. missing response-digest preservation and actor-request-digest enforcement;
6. stale exact-content manifest after mechanism changes.

Focused actor, C7, corpus, scorer, verdict-grammar and runner/prereg tests are
green. The corpus tests independently regenerate all bytes and compare them to
the committed corpus.

## Verification before review

- Full non-product Research suite: `1346 passed, 16 skipped, 5 subtests passed`.
- Native workflow prereg/review tests: `20 passed`.
- Native manifest compatibility and fail-closed freeze refusal: passed; manifest
  is `intact: true`, and freeze still refuses because no independent review
  acceptance exists.
- Existing Stage-A candidate validation: `VALID_CANDIDATE_ONLY`,
  `freeze_authority=false`, `run_authority=false`, `training_authority=false`.
- Ruff lint: clean.
- Ruff format check: clean.
- Pyright on every changed Python implementation/test file:
  `0 errors, 0 warnings, 0 informations`.
- Git diff check: clean.
- Connectivity canary: `UNRUN`; provider calls performed by this lane: `0`.

## Deliberately unresolved acceptance and run blockers

1. The Agent Plan endpoint/response envelope and resolved model revision remain
   unconfirmed until a separately authorized non-result connectivity canary.
2. Kimi technical review is review input only and does not create independent
   preregistration or RR-0029 architecture acceptance.
3. Independent exact-byte preregistration and architecture reviewers remain
   unsigned.
4. Per-run C7 owner, epoch, capability-token digest and owner acceptance remain
   unsigned.
5. Founder/CTO per-run result-bearing authorization remains unsigned.
6. No freezer has created a native lock.

No provider call, credential value, review acceptance, architecture acceptance,
freeze lock, result, verdict, model update, training artifact, push, merge or
release was created by this build lane.
