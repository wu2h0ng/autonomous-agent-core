# R-EVAL-INDEP-1 — Evaluator-Independence Harness Implementation Packet

> Status: `IMPLEMENTATION_PACKET / HARNESS_BATCH_1 / NOT_FROZEN / NOT_RUN`
> Date: 2026-07-15
> Track: Research infrastructure
> Authority: root `docs/research/foundational-loop-experiments-2026-07-15.md`
> Result boundary: this packet and its deterministic tests are not a result.

## 1. Exact claim and ceiling

The future experiment may measure false acceptance, clean acceptance, abstention,
joint escape, and residual-error correlation for exact reviewer identities on a
frozen executable mutation corpus.

The maximum permitted claim is:

```text
MEASURED_REVIEWER_ROUTING_ON_FROZEN_MUTATION_CORPUS
```

It is not evidence of general cognitive independence, model superiority,
scientific discovery, autonomy, self-evaluation authority, product capability,
or promotion authority.

## 2. Batch-1 implementation scope

This batch implements only:

- closed contracts with unknown-field refusal;
- canonical JSON SHA-256 identities;
- exact reviewer identity records with provider fallback forbidden;
- mutation-builder/oracle-author/reviewer/adjudicator separation guards;
- public case-bundle rejection of hidden referee paths, labels, and oracle refs;
- obvious separator/case variants of those private tokens as defense-in-depth;
- complete Cartesian response-matrix validation without `zip` truncation;
- unsafe-release, clean-accept, abstention, joint-escape, and non-constant
  residual-correlation primitives;
- always-reject and constant-verdict anti-Goodhart status;
- a deterministic seven-class synthetic mutation registry and development-only
  qualification seam;
- `validate` and `qualify-dev` CLI commands carrying `NOT_EVIDENCE`.

No provider transport, model call, result-bearing runner, adjudication verdict,
training, Product Runtime change, `src/aac` change, or workflow-repository change
is included.

## 3. Identity and truth isolation

The frozen experiment must preserve:

```text
oracle author / hidden referee
  != deterministic mutation builder
  != participating reviewers
  != result adjudicator
```

Different prompts, served model IDs, checkpoints, or providers are experimental
cells, not presumed independent identities. A provider fallback changes the cell
and is therefore forbidden.

Batch-1 deliberately does not require `reviewer_id` uniqueness across arms.
Cross-arm reuse can be intentional; its exact identity and independence semantics
must be frozen in the later experiment specification rather than inferred here.

The public bundle contains only opaque case identity, source snapshot digest,
candidate patch, public requirements, and public checks. Mutation class, truth,
hidden-oracle identity/path, and expected verdict remain referee-only.

The public-bundle lexical/path guard is defense-in-depth only. It rejects obvious
snake/camel/separator variants and relative `referee/` paths, but does not claim to
detect arbitrary encoding, paraphrase, semantic leakage, or steganography. It does
not replace the still-unimplemented public/referee filesystem isolation, sealed
manifest review, or independent oracle custody required before a result run.

## 4. Batch-1 mutation fixtures

One deterministic synthetic fixture is supplied for each first-wave defect class:

1. contract relaxation;
2. constant/provenance-insensitive digest;
3. stale correction-epoch authority bypass;
4. constant-return decision logic;
5. model-confidence hidden policy;
6. completion-only non-atomic phase;
7. stale-evidence acceptance.

The development qualifier compiles the mutant, confirms the clean/base behavior
with a private mechanical predicate, and confirms that the same predicate rejects
the mutant. These fixtures prove harness liveness only. They are not the 60-case
corpus and cannot support a reviewer-routing result.

## 5. Required falsifiers in this batch

- unknown contract fields refuse;
- hidden paths/labels/oracle tokens refuse public serialization;
- role identity collapse refuses;
- duplicate, missing, unexpected, or ragged response cells refuse;
- semantic digest changes do not collapse to a constant;
- always-reject cannot win through zero false acceptance;
- constant verdict vectors are not routing evidence;
- constant residual vectors return `UNDEFINED`;
- a known response matrix yields exact mechanical metrics;
- every first-wave mutation class has one qualified development fixture;
- CLI has no provider or result command and emits `NOT_EVIDENCE`.

## 6. Remaining before freeze or result run

The following are deliberately unimplemented:

- 60 fresh harmful mutations plus 14 clean controls;
- real pinned repository snapshots and independently authored sealed oracles;
- public/referee filesystem or container isolation;
- generated-evaluator sandbox and sibling-generalization scoring;
- same-checkpoint, same-family, and cross-lineage API adapters;
- response sealing, run-manifest locking, prompt/tool/context drift checks;
- Wilson intervals, McNemar, stratified bootstrap, residual class-centering, and
  leave-one-class-out analysis;
- exact preregistration, architecture review, freeze, r-final, and independent
  adjudication.

Until those exist and freeze, status remains:

```text
HARNESS_IMPLEMENTED_LOCAL != CORPUS_FROZEN != RESULT_RUN != ROUTING_VALIDATED
```

## 7. P2 hardening implementation record

This bounded follow-up changed only:

- `experiments/r_eval_indep_1/contracts.py`;
- `experiments/r_eval_indep_1/metrics.py`;
- the three directly corresponding test modules; and
- this implementation packet.

The TDD RED command produced six expected failures: five uncovered lexical/path
variants and one open-string routing status. The first GREEN run completed 22
contract, metric, and registry tests. The post-documentation gate recorded:

```text
targeted unittest modules: 25 tests, OK
targeted Ruff: All checks passed
git diff --check: clean
development validate CLI: NOT_EVIDENCE, provider_calls=0,
  provider_fallback=FORBIDDEN, result_run_available=false
```

These verification results do not change the
`NOT_FROZEN / NOT_RUN / NOT_EVIDENCE` state.
