# R-ACTIVE-DISCOVERY-1 Hidden Scoring TDD and Validation Plan

> Status: `DESIGN_ONLY / SPEC_REVISE_REMEDIATION_CANDIDATE / NOT_IMPLEMENTED / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
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

Kimi review session `session_96d94f7e-8f05-4990-94c9-de347285ea71`, receipt
`R-ADS-REV-20260715-c64c3bee`, returned `SPEC_REVISE` on the prior exact head.
This plan remains non-executable until Kimi returns literal `SPEC_APPROVE` on
the revised exact head.

The first implementation is additive-only. It may add modules, tests, and exact
manifests named below, but may not modify these accepted Stage-A files:

```text
research_tools/active_discovery/referee.py
7f25d14b94f399626ff1681e8b73d82fb48804c41f282af3d10f46414b4fe925

research_tools/active_discovery/arm_runner.py
af1bbb940cd047406b699a84de8b1f2932b318d949a045aa11c233470ebea016

accepted Stage-A source_manifest_digest
f9f191f06a29ba6d2becd3f817dfd406f8721dcb128f704b3db0ea3d496b7192
```

Any old-source change requirement stops the task with
`REQUIRES_SUCCESSOR_LINEAGE`; it must name a new candidate/lineage, freeze a new
exact source manifest, and obtain fresh spec/architecture review before that
write. The implementer may not silently widen this plan.

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

### 1.1 Exhaustive trace-universe verifier

**Future files**

- Create: `research_tools/active_discovery/trace_universe_verifier.py`
- Test: `tests/research_tools/test_active_discovery_trace_universe_verifier.py`

**RED first**

Require rejection of one trace, 17 deduplicated traces, sampled/truncated
semantic domains, a missing configuration witness, an unwitnessed public trace,
duplicate/non-canonical traces, dirty resets, wrong step cardinality, and an
`OTHER` bucket. Test literal 2- and 16-trace boundaries and behavior-identical
configuration deduplication.

**GREEN gate**

The new verifier proves both directions of the complete-domain mapping, emits a
closed `TraceUniverseCertificate/v1`, exposes no semantic-to-trace truth map to
actors, and never modifies a family or Stage-A source file.

### 1.2 Canonical hidden-byte commitment codec

**Future files**

- Create: `research_tools/active_discovery/hidden_byte_codec.py`
- Test: `tests/research_tools/test_active_discovery_hidden_byte_codec.py`

**RED first**

Use literal byte vectors for the normative section-9.2 codec. Require exact
envelope and SHA-256 matches, round-trip replay, arbitrary raw-byte preservation,
and failures for wrong domain/version/order, unknown enum, invalid ASCII/UTF-8/
NFC, zero/overlong strings, short nonce, truncated/overlong length, raw-length
mismatch, trailing bytes, over-cap raw bytes, non-canonical re-encoding,
duplicate nonce, and cross-object commitment reuse.

**GREEN gate**

Exactly one prefix-free encoding is accepted. Split/role/schema/object/
custodian aliases change the commitment, actor echo strings never decode as a
reveal, and no permissive or legacy codec exists.

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

### 3.1 Scorer-candidate collusion falsifier

**Future files**

- Create: `research_tools/active_discovery/scoring_collusion.py`
- Create: `research_tools/active_discovery/scoring_collusion_manifest.json`
- Test: `tests/research_tools/test_active_discovery_scoring_collusion.py`

**Produces**

A closed provenance graph and `ScorerCandidateCollusionTrap/v1` for
implementer-visible Q-SCORE falsifiers only.

**RED first**

Require the trap to reject: candidate-supplied scorer path/config/weights/truth;
behavior-equivalent digest/ID padding that changes a metric; commitment/digest
echo accepted as reveal or truth; exact hidden outcomes/scores predictable by a
no-probe adversary from public ordering, commitments, manifest shape, generator
seed, or qualification leakage; one commitment reused across role/split/schema
objects; actor and hidden target/contrast/witness/scorer bytes sharing a
principal, writable workspace, source generator, prompt, or seed stream; and
score/error feedback before every model and human final seal. Include one
provenance-separated behavior-grounded control that must pass. Public knowledge
of deterministic score formulas alone is permitted; hidden-outcome recovery
without behavior evidence is not.

**GREEN gate**

Every adversarial fixture returns `INVALID_SCORER_CANDIDATE_COLLUSION`; none can
be thresholded to zero and retained. The manifest permanently labels every
fixture `Q_SCORE_ONLY / EXCLUDED_FROM_P_POWER_AND_E_SCORE`.

## 4. Content seal and one-way referee path

**Future files**

- Create: `research_tools/active_discovery/scoring_referee.py`
- Test: `tests/research_tools/test_active_discovery_scoring_referee.py`

**Produces**

- immutable bundle-byte custody, prefix/final sealing, post-seal content lookup,
  hidden execution, C7 checks, and score receipt without family-owned scoring.

**RED first**

Require rejection of digest-only scoring, mutable/missing bundle content,
pre-seal scorer calls, score feedback, score after halt, hidden access after
halt, post-final bundle/probe writes, private donor-state access, monkey-patching
or global mutation, and either accepted donor-file hash changing.

**GREEN gate**

Only the referee can retrieve validated bundle bytes; actor and matched runner
cannot import or call scorer/hidden-corpus APIs; existing development paths stay
`NOT_EVIDENCE`. `referee.py` remains byte-identical at
`7f25d14b94f399626ff1681e8b73d82fb48804c41f282af3d10f46414b4fe925`.

## 5. Prefix bundles and query-efficiency runner

**Future files**

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
all final seals; halt yields no partial scientific receipt. `arm_runner.py`
remains byte-identical at
`af1bbb940cd047406b699a84de8b1f2932b318d949a045aa11c233470ebea016`.

## 6. Strong baseline implementations

**Future files**

- Create: `research_tools/active_discovery/baselines.py`
- Test: `tests/research_tools/test_active_discovery_baselines.py`

**Produces**

- SYSTEMATIC_COVERING, RANDOM_STRATIFIED, PASSIVE_ZERO_QUERY, FREEFORM_ENGINEER,
  TRACE_MEMO, and GENERIC_TESTS contracts and parity receipts. HUMAN_STRONG uses
  `HumanBundleProtocol/v1` and losslessly emits the same bundle contract through
  a separate frozen operator/UI protocol.

**RED first**

Require systematic coverage of every frozen public stratum, random uniformity
over the same strata, fixed seed-set replay, passive zero-query accounting,
same-model/input/output budgets, and explicit human time/effort fields.
For HUMAN_STRONG require direct integer-micros vectors summing to `1_000_000`,
an explicit maximum-probability contract, `k=0..4` no-backfill seals, identical
inert TestIR constraints, exact UI/instruction/practice/event-log bindings,
single-operator source/network/model-assistance denial, wall-clock disposition,
and no narrative-to-score or probability imputation adapter.

**GREEN gate**

No baseline sees hidden bytes/outcomes or score feedback; no random best-seed or
weak stable-order baseline can enter a preregistration. Missing/invalid human
records block human/strongest-baseline claims and are never replaced after model
scores are visible.

## 7. Hidden-byte custody and leakage gates

**Future files**

- Create: `research_tools/active_discovery/hidden_corpus_contracts.py`
- Create: `research_tools/active_discovery/hidden_custody_design_manifest.json`
- Test: `tests/research_tools/test_active_discovery_hidden_custody.py`

**Produces**

- salted commitment/reveal validation, Q/P/E split refusal, custodian-role
  separation, behavior-distinct contrast witnesses, actor projection, and an
  honest `UNBOUND_DESIGN_ONLY` custody/run binding manifest whose future IDs are
  literal nulls.

**RED first**

Require rejection of unsalted/brute-forceable commitments, missing nonce,
post-output commitment, split reuse, writer-custodian collapse, reveal drift,
raw hidden projection, F4 author-unseen claims, placeholder/inferred/fake
custodian IDs, P/E custodian reuse, any sovereign-role collapse, and every
hidden-generation/commit/freeze/pilot/run entry while a required identity or
review receipt is null.

**GREEN gate**

Only public commitments/challenges reach actors; exact reveal verifies after all
seals; F4 remains allocation-only in every receipt. The tracked design manifest
stays `BLOCKED_UNBOUND`; tests may use test-local fake bindings only to prove the
brake and may not emit production authority.

## 8. Instrument qualification

**Future files**

- Create: `research_tools/active_discovery/scoring_source_manifest.json`
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
- all scorer-candidate collusion falsifiers are killed;
- the trace-universe verifier passes literal 2/16 boundaries and rejects 1/17;
- the canonical commitment codec matches frozen literal byte/digest vectors;
- current and adjacent active-discovery tests remain green;
- no family, `referee.py`, or `arm_runner.py` file changes;
- source/manifest digests and role separation are independently reviewed;
- status remains `QUALIFIED_INSTRUMENT / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

Any score value generated on Q-SCORE is a test fixture, not a research result.
The first implementation commits no qualification narrative, provider/model/
human output, hidden E-SCORE bytes, freeze artifact, r-final, or result. The
exact source manifest binds only new modules/tests/manifests plus the unchanged
accepted donor hashes.

## 9. Separate claim-ready preregistration cast

Only after Tasks 1-8 and independent review may a new task create a
preregistration candidate. It must additionally freeze:

- exact model/human arms and all bytes;
- practical effect floor, P-POWER-derived sample size, paired analysis, and
  multiplicity correction;
- calibration non-inferiority and test-value co-gates;
- E-SCORE commitments and custodian identities;
- C7, missing-data, invalidation, stopping, reveal, and adjudication rules;
- exact non-null, pairwise-valid Q/P/E custodian, runner operator, C7 authority,
  independent adjudicator, and human-protocol operator IDs plus review receipts;
- the exact `HiddenByteCommitmentEnvelope/v1` byte vectors, raw-size caps, nonce
  uniqueness policy, and decoder error grammar;
- interpretation caps for F4 and the absence/presence of a genuine F5.

The preregistration writer may not be the hidden-byte custodian or final
adjudicator. A null, placeholder, inferred, collapsed, or post-generation role
binding returns `BLOCKED_UNBOUND` before hidden bytes, provider/model/human calls,
freeze, or run. There is no authorization to execute this task in this document.

## 10. Completion and next action

This plan is complete as a `DESIGN_ONLY` companion when the normative spec and
this file are committed atomically. The only allowed successor is exact-head
Kimi re-review of both document bytes and the prior remediation diff. If and
only if that review returns literal `SPEC_APPROVE`, a separately named branch
and worktree may execute the RED-first plan by adding only the listed new
modules, tests, and manifests. `SPEC_REVISE`, `PARK`, ambiguity, reviewer
identity drift, or review transport failure leaves the lane docs-only. No
implementation, freeze, provider/model/human call, run, or result follows by
implication.
