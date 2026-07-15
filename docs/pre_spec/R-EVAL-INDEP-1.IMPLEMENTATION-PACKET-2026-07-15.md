# R-EVAL-INDEP-1 — Evaluator-Independence Harness Implementation Packet

> Status: `IMPLEMENTED_LOCAL / NATIVE_READINESS_CANDIDATE_BLOCKED_UNBOUND / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
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

Batch-2B now supplies a local 60-harmful + 14-clean freeze candidate. The
following are deliberately unimplemented or unauthorised:

- independent technical review, custody transfer and an exact freeze decision
  for the 60-harmful + 14-clean local candidate;
- independently authored and separately custodied sealed-oracle artifacts for
  the result corpus (Batch-2B oracles are narrow local development oracles);
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

## 9. Batch-2B freeze-ready corpus implementation plan

> **For agentic workers:** execute inline with test-first RED/GREEN cycles in the
> existing `codex/r-eval-indep-1-harness` worktree. This plan authorizes corpus
> construction only; it does not authorize freeze, provider/reviewer calls,
> scoring, r-final or a result run.

**Goal:** Expand the pinned development corpus from 7 harmful + 7 clean cases to
exactly 60 real harmful mutations + 14 semantic-preserving clean controls while
retaining `NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

**Architecture:** Keep the compiler, manifests and subprocess qualifier in
their current modules. Move the additional declarative case material into one
focused Batch-2B data module containing real snapshot pins, exact source
replacements, case-specific oracle bytes and separately hard-coded candidate,
patch and oracle digests. `corpus_registry.py` converts those closed records to
the existing `CaseRecipe` contract and combines them with Batch-2A.

**Tech stack:** Python 3.12 stdlib, `unittest`, Ruff and Pyright. No new runtime
dependency and no change under `src/aac`.

### 9.1 Global constraints

- Exactly 60 harmful and 14 clean cases; every case ID, candidate digest and
  patch digest is unique.
- Every mutation edits a pinned real `src/aac` snapshot through one exact,
  single-occurrence replacement. No generated pseudo-module or duplicate
  syntax-only harmful mutation counts toward 60.
- Every harmful case has a narrow oracle that passes the pinned base and fails
  the candidate. Every clean control passes the same qualification rule.
- Source, public test, support, candidate, patch and oracle bytes all have
  literal expected SHA-256 identities. Current filesystem bytes never become
  their own expected value at verification time.
- Public/referee separation, normalized allowlisted paths, symlink rejection,
  duplicate-key rejection, fixed `python -I` profile, timeout and output cap
  remain non-bypassable.
- `python -I` remains a Python/import isolation claim only, not a hostile-code
  network or filesystem sandbox claim.
- No provider, reviewer, model, statistics, winner, freeze, r-final, result or
  evidence-upgrade entry point may be added.

### 9.2 Harmful mutation inventory

The 53 new harmful cases complete the existing seven as follows:

| Real module | Final harmful count | Independently exercised defect surfaces |
|---|---:|---|
| `safe_expr.py` | 7 | AST type guard, call guard, keyword guard, symbol guard, feature bound, expression-length bound, attribute admission |
| `audit.py` | 5 | payload/index/previous-hash identity, verification hash check, chain-link check |
| `write_authority.py` | 5 | undeclared-writer bypass, grant/check unknown-authority refusal, grant audit, refusal audit |
| `outcome_judge.py` | 5 | constant verdict, beta validation, reset isolation, stream attribution, strict tie rule |
| `governed_gate.py` | 7 | tool denial, pause, forbidden index, risk ceiling, evidence, verification and approval gates |
| `world_model.py` | 7 | state shape, uncertainty prior, error direction, mean update, uncertainty update, surprise write and atomic update |
| `belief_ledger.py` | 7 | stale/conflict privilege, verified overwrite, poisoning budget, confidence cap, unidentified protection and clear semantics |
| `self_model.py` | 7 | deny precedence, allowlist semantics, risk boundaries, evidence default and bounded calibration writes |
| `viability.py` | 5 | death boundary, invalid pressure span, pressure direction, metabolism and capacity cap |
| `conflict_detector.py` | 5 | scan threshold, conflict marking, post-mark convergence, latest-wins ordering and mixed-evidence pending state |

The seven new clean controls are independent refactors in `safe_expr.py`,
`audit.py`, `governed_gate.py`, `belief_ledger.py`, `self_model.py`,
`viability.py` and `conflict_detector.py`. Together with Batch-2A they produce
14 distinct clean patches.

### 9.3 TDD execution tasks

- [x] **Task 1 — Corpus cardinality and uniqueness RED.** Update
  `tests/test_r_eval_indep_1_corpus_registry.py` and
  `tests/test_r_eval_indep_1_cli.py` to require 60 harmful, 14 clean, 74 unique
  case/candidate/patch identities and exact CLI counts. Run them and record the
  expected current-corpus failures (`7 != 60`, `7 != 14`, `14 != 74`).
- [x] **Task 2 — Closed Batch-2B material.** Add
  `experiments/r_eval_indep_1/corpus_cases_batch2b.py`; modify
  `corpus_registry.py` to reject unknown record fields, duplicate material pins,
  source anchors that are absent/non-unique, and any literal SHA drift before a
  subprocess starts. Run the registry compile tests GREEN.
- [x] **Task 3 — Qualification soundness.** Add the 53 harmful and seven clean
  records in the module/count groups frozen in section 9.2. Run
  `verify_corpus_dev`; accept a case only when base=`PASS` and harmful=`FAIL` or
  clean=`PASS`. If an intended mutation survives or a clean control fails,
  repair or drop that case rather than weakening its oracle.
- [x] **Task 4 — Drift and boundary regression.** Add tests that alter a
  Batch-2B source/test/support/candidate/patch/oracle identity and require
  fail-closed rejection; retain path, symlink, timeout, output, duplicate JSON
  and child-process isolation tests.
- [x] **Task 5 — Documentation and final gate.** Record exact corpus/runner/
  public/referee digests and commands here. Run all R-EVAL-INDEP-1 tests,
  targeted Ruff, targeted Pyright, both CLI commands and `git diff --check`.
  Commit once, verify a clean worktree, and leave status
  `NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

### 9.4 Batch-2B local verification record

The cardinality/uniqueness tests were written first and produced the expected
three failures against Batch-2A: `7 != 60`, `7 != 14` and `14 != 74`. The first
qualification pass rejected one proposed keyword-guard mutation because an
independent AST-node guard still killed the behavior. The candidate patch was
made non-redundant while the narrow oracle stayed unchanged; the second pass
qualified all 74 cases.

Exact local identities:

```text
corpus_id: r-eval-indep-1-batch2b-dev-v1
runner_sha256: 589d642251714a341c37ebe125598955e238c9892f827a5aac24f32fd545d04f
public_cases_sha256: c758e4f59b61e63c647960076da64fc9a0459350d9a56504289c0cbac25d1f7f
referee_cases_sha256: 688ed739700f4df4bd52852ea52a5d6057b98de17761f6c5e5c1d2ef1471edab
corpus_manifest_sha256: a261aeccfea46b1fd4b28525ba7d20acf32c76b36fd2c587f6ebf8a82ec81bc0
```

Final local gates:

```text
R-EVAL-INDEP-1 unittest modules: 53 tests, OK
qualification: 60/60 harmful killed; 14/14 clean survived
targeted Ruff: All checks passed
targeted Pyright: 0 errors, 0 warnings, 0 informations
compile-corpus-dev: provider_calls=0, NOT_FROZEN, NOT_RUN, NOT_EVIDENCE
verify-corpus-dev: qualified_count=74, provider_calls=0,
  NOT_FROZEN, NOT_RUN, NOT_EVIDENCE
```

These development qualifications establish only corpus-harness liveness and
local freeze-candidate integrity. They are not a reviewer result, scientific
verdict, r-final artifact, or evidence upgrade.

## 10. Native readiness build

> Status: `BLOCKED_UNBOUND / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`

This successor sidecar leaves the qualified 60-harmful + 14-clean corpus bytes
unchanged and adds only pre-run contracts:

- a provider-neutral `ReviewerClient` protocol with no concrete production
  client, API-only endpoint binding, forbidden fallback, and exact model
  revision/prompt/tool/context/decoding/public-bundle identity;
- a deterministic complete case-by-arm collector contract guarded by an
  external C7 permit;
- mechanical truth joining plus false acceptance, harmful miss, clean accept,
  abstention, class-centered residual correlation, joint false acceptance,
  token, cost, mean latency, and nearest-rank p95 latency scoring;
- a JSON-compatible native preregistration candidate with a literal exact-file
  manifest, one-result-bearing-run rule, no-rescue/no-rerun controls, external
  non-writable C7, and a sovereign-role separation policy;
- a closed raw r-final Python contract and JSON Schema whose initial state is
  `RAW_NOT_ADJUDICATED`, with `verdict=null` and no runner or writer entry point.

The committed preregistration deliberately leaves these six external bindings
empty rather than inventing identities or credentials:

```text
PROVIDER_BINDINGS_UNBOUND
ORACLE_CUSTODY_UNBOUND
C7_AUTHORITY_UNBOUND
INDEPENDENT_REVIEW_UNBOUND
FREEZER_IDENTITY_UNBOUND
RUN_AUTHORITY_UNBOUND
```

Therefore this build cannot freeze, call a provider, execute r-final, produce a
review acceptance, adjudicate a result, or upgrade an evidence claim. A future
external freeze must bind the exact committed target head, prereg candidate,
manifest, provider endpoints, sealed oracle custody, independent review,
freezer, run authority and C7 decision without changing these mechanism bytes.

Fresh local verification before the atomic commit recorded:

```text
R-EVAL-INDEP-1 targeted unittest modules: 73 tests, OK
full Research unittest discovery: 1310 tests, OK (skipped=16)
targeted Ruff: All checks passed
targeted Pyright: 0 errors, 0 warnings, 0 informations
exact manifest: intact, 23 files
readiness: BLOCKED_UNBOUND with the six blockers listed above
git diff --check: clean
```

Skipped tests are pre-existing dependency- or pre-spec-gated cases. None of
these checks is a provider call, corpus freeze, r-final run, independent review,
adjudication or evidence result.
