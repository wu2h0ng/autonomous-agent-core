# R-EVAL-INDEP-1 — Evaluator-Independence Harness Implementation Packet

> Status: `IMPLEMENTED_LOCAL / HARNESS_BATCH_2A / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
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

## 2. Batch-1 implementation scope (historical baseline)

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
- the original `validate` and `qualify-dev` CLI commands carrying
  `NOT_EVIDENCE` (removed from the closed CLI surface by Batch-2A).

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
- every first-wave mutation class has one qualified synthetic development
  fixture;
- the current CLI has no provider or result command and emits `NOT_EVIDENCE`.

## 6. Remaining before freeze or result run

The following are deliberately unimplemented:

- the required 60 fresh harmful mutations plus 14 clean controls in a frozen,
  independently reviewed corpus (Batch-2A has only 7 + 7 development cases);
- independently authored and separately custodied sealed-oracle artifacts for
  the result corpus (Batch-2A oracles are narrow local development oracles);
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

## 8. Batch-2A design and implementation record

> Status: `IMPLEMENTED_LOCAL / PRE_FREEZE_CORPUS_INFRASTRUCTURE / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`

Batch-2A upgrades the synthetic seam into a pre-freeze corpus compiler and
qualifier. It does not add a reviewer, provider adapter, scoring run, r-final
entry point, or scientific verdict.

### 8.1 Manifest split

- `PublicCaseManifest` binds only opaque case identity, pinned public source/test
  snapshot identities, support-file identities, candidate-source identity,
  candidate patch bytes/digest and public check names.
- `RefereeCaseManifest` separately binds truth, mutation class or clean-control
  null, expected disposition, oracle path/bytes digest and the exact public
  manifest digest.
- `CorpusManifest` binds the ordered public-set digest and referee-set digest.
  Its public projection contains no referee mapping or referee digest.
- Every mapping is closed. Unknown fields, duplicate case IDs, mismatched public
  and referee case sets, digest drift, or private metadata in a public mapping
  fail closed.

Hard-coded SHA-256 pins cover source bytes, public test bytes, every support
source, referee oracle bytes, candidate source bytes and clean/harmful unified
patch bytes. Current filesystem content is never accepted as its own expected
identity.

### 8.2 Snapshot and process boundary

The compiler reads only exact repository-relative paths enumerated by the
registry. Absolute paths, `..`, non-regular files, symlinks in any path
component, resolved paths outside the supplied repository root, and paths not in
the exact allowlist are refused.

The coordinator performs byte reads, digest checks, patch construction and
temporary-file writes only. It never imports, compiles, evaluates or `exec`s
candidate source. A fixed trusted runner starts through `python -I`, with a
temporary working directory, a fixed minimal environment, a fixed timeout and a
bounded combined stdout/stderr protocol. Base, candidate and clean-control
outcomes are parsed through one closed JSON response.

`python -I` is a hermetic Python process/import boundary for these pinned,
known-source development cases. It is not a hostile-code operating-system
sandbox. Batch-2A makes no claim that arbitrary candidate code is denied network
access or repository writes by the OS; such a claim requires a later container,
seatbelt/seccomp or equivalent capability boundary.

### 8.3 Qualification rule

- every case: pinned base source must return oracle `PASS`;
- harmful case: pinned candidate must return oracle `FAIL`;
- clean control: pinned candidate must return oracle `PASS`;
- timeout, output-limit breach, non-zero exit, malformed/extra JSON, digest
  mismatch or runner protocol drift rejects the case;
- all qualification records remain `*_DEV_NOT_EVIDENCE`.

### 8.4 Real development corpus

The approved first set uses seven different repository modules and their real
test snapshots, plus narrow referee oracles logically independent of those
public tests:

| Class | Source snapshot | Mutation |
|---|---|---|
| contract relaxation | `src/aac/safe_expr.py` | admit attribute AST nodes |
| digest/provenance drift | `src/aac/audit.py` | omit payload from hash identity |
| authority bypass | `src/aac/write_authority.py` | grant undeclared writer implicitly |
| constant return | `src/aac/outcome_judge.py` | force success verdict |
| hidden policy | `src/aac/governed_gate.py` | let confidence bypass independent verification |
| phase non-atomicity | `src/aac/world_model.py` | return after a partial state update |
| stale evidence identity | `src/aac/belief_ledger.py` | accept a demoted stale entry as fresh |

Each source has a distinct semantics-preserving clean-control patch. These 14
cases are a development corpus, not the later 60 harmful plus 14 clean frozen
corpus. Existing repository tests are pinned public provenance; the independent
narrow oracle is the mutation-kill authority.

### 8.5 Implemented file and TDD sequence

1. Create `corpus_contracts.py` for the three closed manifests and exact public
   projection/digest checks; drive with leakage, duplicate and digest tests.
2. Create `corpus_registry.py` for pinned snapshot refs, patch recipes, seven
   harmful cases and seven clean controls; drive with drift/path/symlink and
   exact class/control coverage tests.
3. Create `qualifier.py` for bounded `python -I` execution and closed
   qualification records; drive with base-fail, survivor, timeout, non-zero,
   parse-error, clean-miskill and child-PID isolation tests.
4. Replace the development CLI surface with only `compile-corpus-dev` and
   `verify-corpus-dev`; both emit `NOT_EVIDENCE`, `provider_calls=0` and
   `result_run_available=false`.
5. Run the complete R-EVAL-INDEP-1 targeted tests, targeted Ruff, CLI smoke,
   `git diff --check`, record exact real/control counts and commit one bounded
   Batch-2A change.

### 8.6 Local verification record

The three RED gates failed for the intended missing behavior before
implementation:

- corpus contracts: one missing-module failure with seven dependent skips;
- qualifier/registry: two missing-module failures with eleven dependent skips;
- replacement CLI: two command errors plus two legacy-command subtest failures.

The completed local gate recorded:

```text
R-EVAL-INDEP-1 targeted unittest modules: 51 tests, OK
targeted Ruff: All checks passed
compile-corpus-dev:
  case_count=14, harmful_count=7, clean_count=7
  runner_sha256=589d642251714a341c37ebe125598955e238c9892f827a5aac24f32fd545d04f
  corpus_manifest_sha256=6cdfcb353c83b592a9dc4be451bc8d8685b36ca5eca873273f12daac5093fd96
  public_cases_sha256=fb63f0b3db73f979f84aab2bddb061b4489f8fd84c189f40c87984799b80b26a
  referee_cases_sha256=17213a5eb2629559513ae35c121f35ad6692db778767273a68ba1a4a90c6162d
verify-corpus-dev:
  qualified_count=14
  7 QUALIFIED_HARMFUL_NOT_EVIDENCE
  7 QUALIFIED_CLEAN_NOT_EVIDENCE
  provider_calls=0, result_run=false
  freeze_status=NOT_FROZEN, run_status=NOT_RUN, evidence_status=NOT_EVIDENCE
```

Qualification means only that every pinned base passed its narrow oracle, all
seven pinned harmful candidates were killed, and all seven distinct clean
controls survived. It is corpus-construction evidence, not a reviewer-routing
result.

### 8.7 Explicit residual gaps

- This is 7 harmful + 7 clean, not the required frozen 60 + 14 corpus.
- Public test files are pinned provenance snapshots; they are not executed as a
  complete repository test suite inside each worker.
- Oracle logic is independent of the pinned public tests, but oracle authorship,
  custody and sealing are not independently split for a result run.
- Public/referee container isolation, provider/reviewer APIs, response sealing,
  scoring/statistics, preregistration freeze, r-final and adjudication remain
  absent.
- `python -I`, fixed cwd/environment, timeout and bounded output isolate Python
  import/process state. They do not deny arbitrary candidate network access or
  filesystem writes through an OS capability sandbox.

Therefore this implementation does not move the experiment beyond:

```text
NOT_FROZEN / NOT_RUN / NOT_EVIDENCE
```
