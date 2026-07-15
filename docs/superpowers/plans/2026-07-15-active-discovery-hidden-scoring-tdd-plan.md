# R-ACTIVE-DISCOVERY-1 Hidden Scoring TDD and Validation Plan

> Status: `DESIGN_ONLY / NOT_IMPLEMENTED / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
>
> Date: 2026-07-15
>
> Exact design base: `0f0a3d75fc80e8f82cc57f11058f014c87013aa5`
>
> Writer lane: `codex/r-active-discovery-hidden-scoring-spec-20260715`
>
> Normative companion spec:
> `docs/superpowers/specs/2026-07-15-active-discovery-hidden-scoring-spec.md`

## 0. Authority ceiling

This is a future implementation plan, not implementation or authorization.
Every task begins only after an independent RR-0029 review accepts the exact
normative spec bytes. No task may modify files under
`research_tools/active_discovery/families/`, create result-bearing hidden bytes,
freeze a preregistration, call a model/provider, or execute a scientific run.

The tasks below are ordered RED-first. A GREEN test is instrument evidence only
and cannot authorize the next governance or scientific state.

## 1. Closed scoring contracts

**Future files**

- Create: `research_tools/active_discovery/scoring_contracts.py`
- Test: `tests/research_tools/test_active_discovery_scoring_contracts.py`

**Produces**

- `ChallengeCatalogue`, `BehaviorTrace`, `OutcomeAtom`, `TraceProbability`,
  `DiscoveryScoreBundle`, `StatefulTestIR`, and `HiddenScoreReceipt` closed
  contracts with canonical digests.

**RED first**

```text
pytest tests/research_tools/test_active_discovery_scoring_contracts.py -q
```

Expected failures: module missing; then unknown/missing fields, non-canonical
payload, non-exhaustive probability vector, contract trace outside the universe
or below maximum probability, broken prefix chain, executable TestIR content,
and probe/challenge overlap accepted.

**GREEN gate**

All malformed records fail closed; canonical round-trip and digest replay pass.

## 2. Referee-owned scorer math

**Future files**

- Create: `research_tools/active_discovery/hidden_scoring.py`
- Test: `tests/research_tools/test_active_discovery_hidden_scoring.py`

**Produces**

- exact rational `H/C/T/S/AUC_QE` computation and `HiddenScoreReceipt/v2`.

**RED first**

Add tests for the six normative-spec section-8 metamorphic properties, exact
integer boundary vectors, zero components, tie-aware explicit contract scoring,
target-invalid test exclusion, contrast witness validation, and cross-process
replay. Run the test module and require failures because no scorer exists.

**GREEN gate**

All expected micros values and receipt digests match literal fixtures; no float,
ID, label, seed, arm, family, or digest numeric input exists in the scorer.

## 3. Fresh qualification fixture bytes

**Future files**

- Create: `research_tools/active_discovery/scoring_qualification.py`
- Create: `research_tools/active_discovery/scoring_qualification_manifest.json`
- Test: `tests/research_tools/test_active_discovery_scoring_qualification.py`

**Produces**

- exactly 16 Q-SCORE records from explicit behavior-distinct semantics and
  label permutations, with no family source edit.

**RED first**

Require exact count/split, behavior-difference witness, label-isomorphism map,
raw-byte SHA, unique record identity, and permanent exclusion flags. Require
failure against the current fixed-semantics/seed-only builder.

**GREEN gate**

All records are behavior-varying or declared label-isomorphic as specified;
`opaque_graph.py` raw SHA remains
`1a2a3565035422a7ee60aac2e193a17e475307ecda08b18dc5c837f3c11cf405`.

## 4. Content seal and one-way referee path

**Future files**

- Modify: `research_tools/active_discovery/referee.py`
- Create: `research_tools/active_discovery/scoring_referee.py`
- Test: `tests/research_tools/test_active_discovery_scoring_referee.py`

**Produces**

- immutable bundle-byte custody, prefix/final sealing, post-seal content lookup,
  hidden execution, C7 checks, and score receipt without family-owned scoring.

**RED first**

Require rejection of digest-only scoring, mutable/missing bundle content,
pre-seal scorer calls, score feedback, score after halt, hidden access after
halt, and post-final bundle/probe writes.

**GREEN gate**

Only the referee can retrieve validated bundle bytes; actor and matched runner
cannot import or call scorer/hidden-corpus APIs; existing development paths stay
`NOT_EVIDENCE`.

## 5. Prefix bundles and query-efficiency runner

**Future files**

- Modify: `research_tools/active_discovery/arm_runner.py`
- Create: `research_tools/active_discovery/scored_arm_runner.py`
- Test: `tests/research_tools/test_active_discovery_scored_arm_runner.py`

**Produces**

- `k=0..4` immutable prefix bundles, exact four-unit parity, delayed scoring,
  and AUC_QE receipts.

**RED first**

Require failures for prefix rewriting, missing prefix, early scoring, score-fed
selection, differing bundle budgets, adapter reuse, budget mismatch, and partial
receipt after halt.

**GREEN gate**

All arms commit identical-schema prefix chains; hidden scoring begins only after
all final seals; halt yields no partial scientific receipt.

## 6. Strong baseline implementations

**Future files**

- Create: `research_tools/active_discovery/baselines.py`
- Test: `tests/research_tools/test_active_discovery_baselines.py`

**Produces**

- SYSTEMATIC_COVERING, RANDOM_STRATIFIED, PASSIVE_ZERO_QUERY, FREEFORM_ENGINEER,
  TRACE_MEMO, and GENERIC_TESTS contracts and parity receipts. HUMAN_STRONG uses
  the same external bundle contract and a separate operator protocol.

**RED first**

Require systematic coverage of every frozen public stratum, random uniformity
over the same strata, fixed seed-set replay, passive zero-query accounting,
same-model/input/output budgets, and explicit human time/effort fields.

**GREEN gate**

No baseline sees hidden bytes/outcomes or score feedback; no random best-seed or
weak stable-order baseline can enter a preregistration.

## 7. Hidden-byte custody and leakage gates

**Future files**

- Create: `research_tools/active_discovery/hidden_corpus_contracts.py`
- Test: `tests/research_tools/test_active_discovery_hidden_custody.py`

**Produces**

- salted commitment/reveal validation, Q/P/E split refusal, custodian-role
  separation, behavior-distinct contrast witnesses, and actor projection.

**RED first**

Require rejection of unsalted/brute-forceable commitments, missing nonce,
post-output commitment, split reuse, writer-custodian collapse, reveal drift,
raw hidden projection, and F4 author-unseen claims.

**GREEN gate**

Only public commitments/challenges reach actors; exact reveal verifies after all
seals; F4 remains allocation-only in every receipt.

## 8. Instrument qualification

**Future files**

- Create: `docs/pre_spec/R-ACTIVE-DISCOVERY-1-HIDDEN-SCORING-QUALIFICATION.md`
- Test: all scoring and active-discovery test modules

**Future required commands**

```text
uv run --extra product-test pytest tests/research_tools/test_active_discovery_*.py -q
uv run --extra product-test ruff check research_tools/active_discovery tests/research_tools
uv run --extra product-test pyright research_tools/active_discovery tests/research_tools
```

These commands are specified but not executed by this docs-only lane.

**Qualification gate**

- all normative-spec section-8 metamorphic tests pass on Q-SCORE;
- current and adjacent active-discovery tests remain green;
- no family file changes;
- source/manifest digests and role separation are independently reviewed;
- status remains `QUALIFIED_INSTRUMENT / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

Any score value generated on Q-SCORE is a test fixture, not a research result.

## 9. Separate claim-ready preregistration cast

Only after Tasks 1-8 and independent review may a new task create a
preregistration candidate. It must additionally freeze:

- exact model/human arms and all bytes;
- practical effect floor, P-POWER-derived sample size, paired analysis, and
  multiplicity correction;
- calibration non-inferiority and test-value co-gates;
- E-SCORE commitments and custodian identities;
- C7, missing-data, invalidation, stopping, reveal, and adjudication rules;
- interpretation caps for F4 and the absence/presence of a genuine F5.

The preregistration writer may not be the hidden-byte custodian or final
adjudicator. There is no authorization to execute this task in this document.

## 10. Completion and next action

This plan is complete as a `DESIGN_ONLY` companion when the normative spec and
this file are committed atomically. The only allowed successor is independent
review of both exact document bytes. No implementation or run follows by
implication.
