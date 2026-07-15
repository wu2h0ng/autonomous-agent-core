# R-ACTIVE-DISCOVERY-1 Referee-Owned Hidden Scoring Specification

> Status: `DESIGN_ONLY / NOT_IMPLEMENTED / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
>
> Date: 2026-07-15
>
> Exact design base: `0f0a3d75fc80e8f82cc57f11058f014c87013aa5`
>
> Writer lane: `codex/r-active-discovery-hidden-scoring-spec-20260715`
>
> Claim class: `research-environment` (evaluation instrument), not a Product,
> Runtime, autonomy, model-quality, or scientific-result claim
>
> Scope: successor scoring design for R-ACTIVE-DISCOVERY-1 only

## 0. Decision and authority ceiling

The next admissible scoring design is a **referee-owned, behavior-grounded,
content-sealed scorer**. It scores a closed final bundle against independently
committed held-out behavior, contract predictions, and generated stateful tests.
It must not derive score from a digest, opaque label, family code, seed, case ID,
or any post-hoc human judgment.

This document does not modify the existing Stage-A qualification candidate. In
particular, it does not modify:

- `research_tools/active_discovery/stage_a_prereg_candidate.json` or its raw
  SHA-256
  `de05497e5058e650742550d7d2c7b5ec0a4fe0bac3ea576f1b72355a87f51c85`;
- the F1-F4 allocation, existing four-unit budget, or verdict grammar;
- any opaque family implementation, including `opaque_graph.py`;
- any current `hidden_score` implementation;
- a preregistration, freeze lock, model/provider call, run, score, result,
  r-final artifact, product capability, or `CURRENT_STATE` entry.

The current Stage-A candidate remains a historical qualification candidate. A
future scoring implementation is a successor lineage, not a post-hoc rescue or
silent amendment. If implementation discovers that the Stage-A mechanism or
budget must change, it must stop and request a new founder-authorized lineage;
it may not edit the historical candidate to make scoring work.

The maximum outcome of this document is:

```text
SPEC_CANDIDATE_READY_FOR_INDEPENDENT_ARCHITECTURE_REVIEW
```

It is not `ACCEPT_FOR_SPEC`, `FREEZE_READY`, `PASS`, `MET`, `NOT_MET`, or
evidence. The writer is different from the original Stage-A writer lane, but
that does not make this document an independent review. A separate reviewer
must own the binding RR-0029 decision.

## 1. Goal Card

### 1.1 Foundational problem lock

At the exact base, all four family-level `hidden_score` methods return
`score_micros=0`. Family seed changes alter opaque vocabulary, while hidden
semantics remain fixed. The sealed referee receives only `bundle_digest` and a
probe transcript, not the final bundle content. It therefore has no lawful
input from which to score behavior predictions, a predicted contract, or
generated tests.

Consequences:

1. every arm is mechanically tied at zero regardless of discovery quality;
2. repeated seeds are label permutations, not independent behavior samples;
3. a VOI advantage gate would be pseudoreplicated or predetermined;
4. F4 is only an allocation holdout and cannot support an author-unseen transfer
   claim;
5. Stage-A cannot become a claim-ready scientific preregistration.

### 1.2 Goal

Specify the smallest evaluator-sovereign scoring architecture that can, on
fresh behavior-varying bytes:

- distinguish better from worse held-out behavioral predictions;
- distinguish better from worse contract predictions;
- reward generated tests only when they are valid on the target and kill
  referee-owned behavior-distinct contrasts;
- measure calibration and query efficiency under matched budgets;
- remain invariant to family/case/opaque-label renaming;
- preserve C6, external C7, hidden-byte custody, and no-feedback-before-seal;
- make a later bounded VOI preregistration scientifically possible.

### 1.3 Non-goals

- no score or result is generated here;
- no threshold, sample size, winner, model, provider, or human performance is
  selected here;
- no claim of general discovery, autonomy, intelligence, transfer, Agent OS
  capability, or product value is permitted;
- no runtime self-modification, training, promotion, activation, or feedback
  learning is permitted;
- no F4 semantic or source change is permitted.

### 1.4 Completion condition for this lane

This docs-only lane is complete when one exact spec:

1. defines score inputs and deterministic component formulas;
2. defines content sealing, hidden-byte custody, anti-leakage, and stop rules;
3. names strong matched baselines and fairness limits;
4. passes the RR-0029 writer-side gate checklist;
5. defines TDD and independent validation steps on fresh non-result bytes;
6. is committed on this isolated branch with no other repository change.

Evidence ceiling remains `E0 / DESIGN_ONLY`.

## 2. Facts, inferences, judgments, and recommendations

| Type | Statement |
|---|---|
| Fact | F1-F4 currently return the constant hidden score zero. |
| Fact | The current sealed scoring call receives a bundle digest and transcript, but not bundle bytes. |
| Fact | `UnifiedFamilyAdapter.build` fixes one semantic configuration per family; seed changes rename public/opaque tokens. |
| Fact | Existing Stage-A binds F1-F3 as qualification families and F4 as an allocation holdout. |
| Fact | Existing `TestIR` is inert and literal-bound, but it represents independent single-step cases rather than stateful held-out sequence contracts. |
| Inference | A non-zero function of only digest/label/ID would be pseudorandom identity scoring, not behavioral scoring. |
| Inference | Family-owned scoring couples mechanism bytes and evaluator bytes under one authoring surface. |
| Judgment | Scoring must move to a separate referee-owned component that consumes sealed final-bundle content and separately custodied hidden behavior bytes. |
| Recommendation | Use public challenge inputs with hidden outcomes, proper categorical scoring, exact contract accuracy, and valid-test/contrast-kill scoring. |

## 3. Considered approaches

### A. Referee-owned behavior-contract challenges — selected

The actor sees a public challenge catalogue containing query sequences and a
configuration-independent exhaustive behavior-trace universe for each complete
sequence. The actor cannot execute challenge sequences. After the four-unit
probe phase, it seals probability distributions, explicit contract
predictions, and generated stateful tests. The referee then executes held-out
challenge and contrast bytes and computes the frozen score.

Advantages:

- score is grounded in executed behavior;
- probability calibration is measurable with a bounded proper rule;
- exact contract prediction and generated-test value remain separately visible;
- input parity and no-hidden-output leakage are mechanically testable;
- labels and IDs can be permuted without changing the score.

Cost: it requires a new closed final-bundle contract and central scorer. The
current digest-only interface is insufficient.

### B. Direct hidden-semantic truth-table scoring — rejected as primary

Scoring the probability assigned to a named hidden semantic configuration is
easy, but it risks measuring recovery of author-known labels rather than
prediction of unqueried behavior. It also makes the small F1-F4 semantic spaces
easy to enumerate. Semantic truth may generate hidden challenges, but semantic
labels may not be the scored object.

### C. Mutation or generated-test kill score only — rejected as primary

Mutation score is useful for generated-test value, but alone it measures fit to
a chosen mutant set and can reward invalid tests. It cannot establish calibrated
behavior prediction or contract accuracy. Contrast killing is retained only as
one gated component after target validity is established.

## 4. Bounded future claim and nulls

This spec does not freeze a claim. It defines the instrument needed for a later
preregistration whose maximum bounded selection claim may be:

> On independently committed, behavior-varying hermetic software instances,
> with the same actor model, public interface, final-bundle budget, and four
> unit-cost probes, typed ACTIVE_VOI selection improves paired held-out
> behavior-contract score and score-versus-query area over predeclared strong
> systematic and stratified-random selection, without worse calibration or
> generated-test validity.

The wording “strongest matched-budget baseline” is forbidden unless the active
arm also clears every applicable model/free-form and human reference defined in
section 11. If it clears only automated selection baselines, the claim must say
`model-arm selection benefit`, not general superiority.

Live nulls and killers:

- `H0_SCORE`: the proposed scorer remains constant, saturated, label-sensitive,
  or insensitive to controlled behavior/prediction/test changes;
- `H0_ACTIVE`: ACTIVE_VOI does not beat strong systematic and stratified random
  under paired matched conditions;
- `H0_REGISTRY`: typed registry/VOI does not beat a strong free-form engineering
  workflow with the same model and probe budget;
- `H0_CALIBRATION`: any score gain is purchased by worse probability
  calibration;
- `H0_TEST_VALUE`: generated tests replay seen/challenge cases, fail on the true
  target, or do not kill hidden behavior-distinct contrasts;
- `H0_QUERY_EFFICIENCY`: final-score gains disappear when score-versus-query area
  is compared;
- `H0_HUMAN`: the active arm remains below the matched-interaction human strong
  reference;
- `H0_TRANSFER`: any within-family benefit disappears on a genuinely
  author-unseen family.

F4 cannot adjudicate `H0_TRANSFER`. Its family and implementation were visible
to the original mechanism author. F4 may test allocation-holdout performance
only.

## 5. Required architecture

### 5.1 Role separation

```text
scoring spec writer
    != scoring implementer where practicable
    != hidden evaluation-byte custodian
    != actor/model arm
    != runner operator
    != independent architecture reviewer
    != result adjudicator
```

The qualification-fixture author may equal the scoring implementer because
qualification bytes are public `NOT_EVIDENCE`. The hidden evaluation-byte
custodian may not equal the mechanism/scorer writer, actor, or result
adjudicator.

### 5.2 Control and data path

```text
public descriptor + probe catalogue + public challenge inputs
                         |
                         v
actor selects at most four allowed probes and receives public observations
                         |
                         v
actor commits prefix bundles k=0..4 (predictions + contract + TestIRV2)
                         |
                         v
final content seal closes probe and bundle channels for all arms
                         |
                         v
external C7 check -> custodian materializes committed hidden bytes
                         |
                         v
referee executes challenge target and contrast instances from clean resets
                         |
                         v
referee-owned scorer computes fixed components and details digest
                         |
                         v
runner emits sealed metric receipt; independent adjudicator applies prereg
```

No metric, hidden outcome, contrast kill, or score is returned to an actor
before every arm for that hidden instance is sealed. Scoring output never enters
probe selection, hypothesis updates, model context, training, Runtime action,
policy, permission, audit, promotion, or activation.

### 5.3 Why the existing interface cannot be reused unchanged

`hidden_score(bundle_digest, transcript)` cannot inspect predictions or tests.
Any varying score computed only from the digest would make an identity hash a
pseudo-oracle. A future implementation must seal validated bundle **bytes** or a
content-addressed immutable object whose bytes the referee can retrieve and
re-hash. The scorer receives validated content, not an untrusted actor path.

Scoring must be centralized in a new referee-owned scorer. Family-level
`hidden_score` methods are not extended with scientific logic. No file under
`research_tools/active_discovery/families/` is modified by the first scoring
implementation. In particular:

```text
research_tools/active_discovery/families/opaque_graph.py
raw SHA-256 at design base:
1a2a3565035422a7ee60aac2e193a17e475307ecda08b18dc5c837f3c11cf405
```

## 6. Public challenge and final-bundle contracts

### 6.1 Public challenge catalogue

Each hidden instance exposes a closed `ChallengeCatalogue/v1` before probing:

- `instance_public_digest`;
- ordered `ChallengeSequence` records;
- each sequence starts from a named clean-reset slot;
- each step contains the exact public operation and canonical payload bytes;
- each sequence contains an exhaustive `TraceUniverse` of 2-16 mutually
  exclusive canonical complete behavior traces;
- every trace contains exactly one ordered behavior atom for every step, so a
  prediction cannot splice incompatible stateful marginals into one contract;
- challenge inputs and trace universes are identical for every arm;
- challenge sequences are disjoint from the executable probe catalogue.

A canonical per-step behavior atom contains only behavior-grounded fields:

```text
status_code
stdout
stderr
canonical output_json
state_relation = SAME | CHANGED
```

The trace universe is generated from the public schema and the full admissible
semantic domain, not from the selected hidden configuration. Behaviorally
identical traces are canonicalized to one trace atom. The universe may not
reveal which trace is true. If the executed true trace is outside the
precommitted universe, the instance is `INVALID_HIDDEN_CORPUS`; `OTHER` is not
added after execution.

Challenge IDs are content digests for binding only. Their spelling and order do
not enter scoring. Family code, seed, case ID, source path, implementation class,
hidden semantic name, and opaque token spelling are unavailable to the scorer's
numeric function.

### 6.2 `DiscoveryScoreBundle/v1`

Every arm produces the same closed data-only bundle schema at each prefix
`k=0,1,2,3,4`:

- exact experiment, instance-public, arm, model/prompt/context, and prefix
  bindings;
- parent prefix-bundle digest, with `k=0` using null parent;
- one probability vector for every challenge sequence and every exact trace
  atom;
- integer `probability_micros` values in `[0, 1_000_000]` summing exactly to
  `1_000_000` per trace universe;
- one explicit `predicted_trace_digest` per challenge sequence, referencing a
  maximum-probability trace atom; ties are permitted and this field chooses one
  tied maximum as the exact contract;
- one `StatefulTestIR/v2` candidate;
- transcript prefix digest and consumed-unit receipt;
- final canonical bundle digest.

The actor cannot omit a challenge, add a trace, use a probability outside the
closed scale, select a non-maximum or out-of-universe contract trace, or revise
an earlier prefix bundle. Unknown fields fail closed. Allowing probability ties
preserves a calibrated symmetric prior at `k=0`; the explicit contract field
keeps exact-accuracy scoring deterministic.

### 6.3 `StatefulTestIR/v2`

The current single-step TestIR is insufficient for expiry, quota, and graph
dynamics. The successor remains inert and data-only but adds reset-bound
sequences:

- 1-16 test cases per bundle;
- 1-8 ordered steps per test;
- every test starts from an independent clean reset;
- canonical literal payloads only;
- fixed literal assertions over status, stdout, stderr, output JSON, and
  same/changed state relation;
- no Python, expression language, callback, dynamic expected value, actor file,
  network, shell, import, or generated executable code;
- provenance may reference only public descriptor, actor-visible probe receipts,
  and prior prefix-bundle digests;
- request-sequence digests must be disjoint from both executed probes and public
  challenge sequences.

Copying a probe or public challenge into generated tests invalidates the test
component; it is not treated as a held-out hit.

## 7. Deterministic hidden score

All calculations use exact integers and rational arithmetic. Implementations
must not use platform floating point to determine a receipt.

Let `M = 1_000_000`.

### 7.1 Behavior probability and calibration component `H`

For complete challenge sequence `i`, actor probability `p_i(t)` and one-hot
true behavior trace `y_i(t)` are scaled by `M`. The bounded quadratic score is:

```text
q_i = 1 - 1/2 * sum_t ((p_i(t) - y_i(t)) / M)^2
H   = mean_i(q_i)
```

Because the trace universe is fixed before prediction and exhaustive, this is a
proper categorical score over coherent stateful contracts.
`H_micros = floor(M * H)`.

Calibration diagnostics are mandatory and separately reported:

- multiclass Brier loss (`1 - H`);
- log loss with a reporting-only fixed floor of one micro-probability;
- reliability/ECE using frozen bins
  `[0,.1), [.1,.2), ..., [.9,1]`, with empty bins omitted and no adaptive
  rebinning;
- count and mean assigned probability for correct and incorrect explicit
  contract predictions.

Log loss and ECE do not replace `H` and cannot be selected post-hoc as the
ranking metric.

### 7.2 Exact behavior-contract component `C`

For every challenge sequence, `predicted_trace_digest` is the actor's exact
contract prediction. A contract is correct only if every ordered step atom
matches the executed trace. Partial-step or partial-field credit is forbidden.

```text
C = exact predicted-trace matches / total challenge sequences
C_micros = floor(M * C)
```

This prevents an always-diffuse prediction from receiving a high contract score
while preserving calibration information in `H`.

### 7.3 Generated-test component `T`

The referee runs every generated test from a clean reset against:

1. the true target instance;
2. a precommitted set of behavior-distinct hidden contrast instances.

A contrast instance is admissible only if the custodian's independent witness
suite proves that it differs from the target on at least one legal request
sequence. Contrast identity and semantic reason remain hidden until reveal.

```text
P = target-valid generated tests / submitted generated tests
R = contrast instances killed by at least one target-valid test
    / admissible contrast instances
T = 0                         if P = 0 or R = 0
T = 2 * P * R / (P + R)      otherwise
T_micros = floor(M * T)
```

A test that fails on the true target is never credited with a contrast kill.
Empty tests, zero contrasts, duplicate tests, seen probe sequences, public
challenge copies, dynamic expected values, or actor code make the instance
invalid rather than assigning zero silently.

### 7.4 Composite `score_micros`

The compatibility scalar must respond to every component even when another
component is zero; otherwise early prefixes can collapse back to a constant-zero
transport. Use the predeclared weighted sum:

```text
S = 0.50 * H + 0.25 * C + 0.25 * T
score_micros = floor(M * S)
```

For every component, improving it while holding the others fixed strictly
increases `S`, including at zero boundaries. The fixed weights are transport
weights, not scientific trade-off authority.

The scalar is a compatibility transport, not sufficient scientific evidence.
Every receipt must expose `H_micros`, `C_micros`, `T_micros`, target-valid test
count, contrast-kill count, challenge count, and calibration diagnostics. A
future preregistration must analyze component outcomes as frozen co-gates and
may not rescue a failed component with the weighted composite. Thus the
non-degenerate transport does not permit calibration to compensate for no exact
contract or useless tests in a scientific verdict.

### 7.5 Query-efficiency component

Each prefix bundle is committed before the next probe. Hidden scoring occurs
only after all final bundles are sealed, so prefix scoring cannot influence
selection.

For the existing four-unit budget:

```text
AUC_QE = (S_0 / 2 + S_1 + S_2 + S_3 + S_4 / 2) / 4
AUC_QE_micros = floor(M * AUC_QE)
```

Final score `S_4` and `AUC_QE` are co-primary instrument outputs. Passive uses
`S_0` and is reported on the score/cost Pareto surface; it is not padded with
four fake probes.

### 7.6 Required score receipt

`HiddenScoreReceipt/v2` binds:

- scorer schema and exact source digest;
- hidden-byte commitment and reveal-policy digest;
- challenge, target, contrast, transcript, prefix-bundle, and final-bundle
  digests;
- `H/C/T/S/AUC_QE` micros;
- calibration and count fields;
- budget and C7 receipts;
- deterministic details digest.

Raw hidden outcomes and semantic labels remain outside actor-visible receipts.
They may be revealed only to the independent adjudicator after every arm and
human reference for the frozen run is sealed.

## 8. Score non-degeneracy on fresh qualification bytes

Implementation may not proceed directly to evaluation bytes. It first creates
an implementer-visible `NOT_EVIDENCE` qualification set with exactly 16 fresh
records:

```text
F1-F4 x two behavior-distinct semantic configurations
      x two opaque label permutations
= 16 qualification records
```

These are new fixture/manifest bytes, not additional seeds over the current
fixed semantics. Family source files remain unchanged. The qualification
records can instantiate existing family classes with explicit semantic
configurations through a new referee-fixture factory.

The scorer qualifies only if all metamorphic checks pass:

1. **Behavior sensitivity:** same public labels and same sealed bundle, but a
   hidden semantic change that changes a scored outcome, changes `H`, `C`, and
   `S` for a deliberately discriminating prediction.
2. **Label invariance:** behavior-preserving permutation of family/case/probe/
   opaque labels plus equivariant bundle relabeling leaves every numeric metric
   unchanged.
3. **Prediction monotonicity:** correcting one wrong probability vector and top
   contract, with other inputs fixed, strictly increases `H`, `C`, and `S`.
4. **Generated-test monotonicity:** replacing one invalid/non-killing test with
   a target-valid contrast-killing test, with other inputs fixed, strictly
   increases `T` and `S`.
5. **Perfect and null anchors:** a fully correct calibrated bundle with complete
   contrast kills reaches `1_000_000`; a literal all-zero `H/C/T` fixture yields
   zero, while changing any single component changes the scalar.
6. **Replay:** identical canonical bytes reproduce the exact receipt digest
   across processes and supported interpreters.
7. **Constant-zero rejection:** returning the current family-level zero score
   cannot satisfy the qualification contract.

Qualification is an instrument test only. The 16 records are permanently
excluded from model pilots, power estimation, evaluation, and scientific
claims.

## 9. Hidden evaluation bytes and custody

### 9.1 Byte sets

Three disjoint sets are mandatory:

| Set | Visibility | Purpose | Scientific use |
|---|---|---|---|
| `Q-SCORE` | scorer implementer-visible | 16-record non-degeneracy and metamorphic qualification | permanently excluded |
| `P-POWER` | independent pilot custodian; never evaluation | variance/resource estimation for the later prereg only | permanently excluded |
| `E-SCORE` | hidden evaluation custodian only until reveal | frozen result-bearing target/challenge/contrast bytes | only set eligible for a run |

No raw bytes, outcomes, semantic configurations, or contrast identities from
`E-SCORE` enter this branch.

### 9.2 Commitment and reveal

The existing small semantic spaces are brute-forceable from an unsalted digest.
Every hidden byte object therefore uses a 256-bit random custodian nonce and an
unambiguous binary encoding:

```text
commitment = SHA256(
  UTF8("active-discovery-hidden-byte/v1") || 0x00 || nonce_32
  || U64BE(byte_length) || raw_bytes
)
```

The public manifest includes commitment, byte length, schema, role, split, and
custodian identity, but not nonce or raw bytes. The custodian seals nonce and raw
bytes before any actor run. The runner verifies the commitment inside the
referee environment. Nonce/raw-byte reveal occurs only after all arms are
sealed, and only to the independent reviewer/adjudicator.

Creating, replacing, or reordering hidden bytes after any actor output is
`INVALID_HIDDEN_BYTES`. A missing reveal or commitment mismatch is invalid, not
missing data.

### 9.3 What “held out” means

- F1-F3 evaluation configurations can be **configuration-unseen** to actors if
  committed by the custodian after scorer freeze.
- F4 remains an **allocation holdout**. It is not family-author-unseen, because
  its code and semantic axes already exist at the design base.
- Seed-only opaque relabeling is never a new behavioral sample.
- `H0_TRANSFER` requires a future F5/new-family byte set whose family behavior
  and implementation were authored under custody after the mechanism and scorer
  bytes were frozen and were not read by those authors. Without that set, all
  transfer language is invalid.

## 10. Anti-leakage and anti-Goodhart contract

Before final seal, actors may see only:

- public descriptor;
- legal probe catalogue and exact cost;
- public challenge input sequences and configuration-independent outcome
  universes;
- their own probe observations, budget receipts, registry state, and prefix
  bundle receipts.

They may not see:

- hidden semantic configuration, target outcomes, contrast identity, witness
  sequences, score components, scorer details, other-arm artifacts, custodian
  nonce, raw hidden bytes, or reveal receipts;
- family/source/class/version labels not already present on the public Stage-A
  surface;
- any score feedback between prefixes or arms;
- filesystem, source, network, arbitrary code, or hidden-runner access.

Score code is prohibited from reading or branching on:

```text
family_code, seed, case_id, challenge_id spelling, probe_id spelling,
opaque token spelling, arm label, model label, or bundle digest as a number
```

Content digests may join and bind records, but may not contribute numeric score.
Tests must permute every identifier while preserving behavior and require exact
metric equality.

## 11. Strong baselines and matched budget

### 11.1 Required arms

1. `ACTIVE_VOI`: typed registry plus deterministic information-value selection.
2. `SYSTEMATIC_COVERING`: a public-schema-derived covering plan spanning
   boundaries, pairwise field interactions, repetition, ordering, state change,
   and error/recovery; current stable catalogue order is not automatically a
   strong systematic baseline.
3. `RANDOM_STRATIFIED`: uniform without replacement within the same public
   strata used by SYSTEMATIC; random seeds and aggregation are frozen before
   hidden bytes and no best-seed selection is allowed.
4. `FREEFORM_ENGINEER`: the same model/checkpoint and tools with a strong frozen
   generic software-investigation workflow, but no typed registry or VOI
   selector.
5. `PASSIVE_ZERO_QUERY`: same actor, descriptor, challenge catalogue, bundle
   schema, generation budget, and hidden instances, with no probes; reported as
   a score/cost Pareto baseline.
6. `HUMAN_STRONG`: independent experienced software engineers with the same
   public interface, four-probe budget, no source/hidden access, and a frozen
   wall-clock/final-bundle protocol.
7. `TRACE_MEMO` and `GENERIC_TESTS`: cheap anti-Goodhart controls for exact seen
   replay/abstention and schema-only test generation.

### 11.2 Exact parity for model arms

All non-passive model arms bind the same:

- model provider, served model/checkpoint, decoding parameters, and model seed;
- system/task prompt bytes and context-window/token limits;
- public descriptor, probe candidates, challenges, trace universes, and
  hidden instance commitments;
- four unit-cost probes, reset semantics, retry/error policy, timeout, and
  output cap;
- reasoning/tool-call/final-bundle token budget and bundle-size cap;
- prefix commitment schedule and no-score-feedback rule;
- scorer, target, contrast, and adjudication bytes.

The intended causal contrast between ACTIVE_VOI, SYSTEMATIC, and RANDOM is probe
selection. FREEFORM changes registry/selection structure and is analyzed as a
separate mechanism contrast, not pooled silently.

### 11.3 Human-reference boundary

Human cognition cannot be token-matched to a model. Human parity therefore binds
interaction budget, public information, forbidden access, final schema, and a
predeclared wall-clock cap, then reports time and operator effort separately.
If the human reference is absent, underpowered, or exposed to source/hidden
bytes, the run may still test model-arm selection but may not claim superiority
to the strongest baseline or human-level discovery.

## 12. Architecture-Theory Review Gate (writer-side packet)

### 12.1 Claim class and exact claim

- Claim class: `research-environment` / evaluation instrument.
- Exact design claim: a behavior-grounded, referee-owned scorer can be specified
  so that its output is non-degenerate, calibration-aware, query-cost-aware,
  and invariant to identity relabeling while remaining outside actor control.
- It is not a claim that ACTIVE_VOI wins.

### 12.2 Null and route killer

`H0_SCORE` is the route killer. Any constant/saturated score, label sensitivity,
digest dependence, target-invalid test credit, hidden-byte custody collapse, or
failure to distinguish controlled behavior changes stops the scoring route
before a preregistration.

### 12.3 Channel map and write matrix

| Component | Channel | May write | May not write |
|---|---|---|---|
| actor registry | `B` | research hypotheses/probabilities | Runtime policy, shell, gate, score, verdict |
| probe selector | bounded research `K` analogue | next legal research probe ID | Product action, permissions, hidden score |
| final bundle | `X` | predictions, contract, inert TestIRV2 | executable code, hidden bytes, verdict |
| hidden scorer | `X` | immutable metric receipt | actor context, probe choice, baseline, gate, verdict, training |
| independent adjudicator | external research authority | frozen-prereg disposition | Runtime action/promotion |
| C7 halt | `S` | stop/no-verdict boundary | score optimization or arm selection |

No component in this design writes Product `P`, Runtime action policy, shell,
permission, audit history, promotion, or C7.

### 12.4 Control and consumption path

The scorer consumes only sealed bundle content and executed hidden behavior
after probe closure. The resulting metric is consumed only by an independent
adjudicator under a future frozen preregistration. It cannot return to the actor,
selector, model context, or training loop. Aggregate multi-organ C6 erosion is
blocked by the same one-way receipt path.

### 12.5 Value/norm source

The value source is operational: prediction of unqueried legal behavior,
calibration, valid contrast-discriminating tests, and query cost. No essence of
autonomy, intelligence, selfhood, or norm correctness is encoded.

### 12.6 Prior-negative mapping

- The current constant-zero score directly motivates `H0_SCORE` and provides no
  positive prior.
- Seed-only relabeling warns against pseudoreplication.
- G7/G8/G13 belief-channel ceilings are not claimed to be escaped; a strong
  free-form/cheap-baseline win closes the active route.
- G10 is unrelated narrow task/regret evidence and cannot support this scorer.
- G12/G13 environment-shopping and rescue risks require fixed new bytes,
  commitment-before-run, and no post-hoc family/split changes.
- Existing non-oracle discovery insufficiency remains unchanged.

### 12.7 Environment pressure and cheap baselines

The pressure is bounded information acquisition in opaque stateful software:
unqueried behavior must be predicted after four legal probes. SYSTEMATIC,
RANDOM, PASSIVE, FREEFORM, TRACE_MEMO, GENERIC_TESTS, and HUMAN_STRONG can each
kill a different claimed advantage.

### 12.8 Consumption-path proof

Scoring happens only after all prefix/final bundles are immutable. No score is
available during selection. Static tests forbid scorer imports in actor/selector
modules; dynamic trap tests fail if any scorer or hidden-byte method is invoked
before final seal.

### 12.9 Representation and abstraction ownership

The referee owns canonical outcome atoms grounded in actual execution. The
actor owns only probability assignments, exact top contracts, and inert tests.
Identity strings are bindings, not semantic coordinates. Outcome-universe
completeness is independently checked against the admissible semantic domain.

### 12.10 C6/C7/SD4 boundary

The scorer is an external evaluator, not a subject organ. C7 remains external,
non-writable, and checked before every new hidden execution and score access.
A halt produces no score or partial scientific verdict. SD4 is outside scope;
no result can move ADR-0037 or support an autonomy claim.

### 12.11 Legal interaction budget

All interactions are local, deterministic, hermetic, reversible software
operations with no network, credential, customer data, real actuator, or unsafe
intervention. Four probe units are fixed for successor compatibility; changing
that budget requires a new lineage before any evaluation-byte access.

### 12.12 Product/process boundary

This is Research Track evaluation infrastructure. Test success is process/
instrument evidence only. It does not become Agent OS Runtime, Data Agent,
customer capability, commercial evidence, or general discovery evidence.

### 12.13 Decision owner and gate outcome

- Writer recommendation: `ACCEPT_FOR_SPEC` after independent review.
- Binding current outcome: `NOT_READY / NOT_INDEPENDENTLY_REVIEWED`.
- Independent reviewer owns RR-0029 acceptance.
- Founder owns any new preregistration/run cast and any claim expansion.
- Runner/adjudicator owns later mechanical validity and result disposition.

### 12.14 Strongest skeptical attack

The strongest objection is that F1-F4 are small, author-known semantic spaces;
a model can exploit catalogue regularities, and a composite can encode arbitrary
weights or overfit referee contrasts. F4 does not cure this. The design reduces
but does not eliminate that defect by:

- scoring executed behavior rather than semantic labels;
- using a proper probability component and separately visible co-gates;
- requiring target validity before contrast kills;
- committing fresh behavior-varying bytes under independent custody;
- making systematic, random, free-form, passive, and human baselines mandatory;
- capping any result at within-family/configuration generalization;
- requiring a future author-unseen F5 before a transfer claim.

If the independent reviewer judges the finite-family/catalogue structure too
enumerable even under these controls, the correct outcome is `PARK` or a fresh
environment design, not metric or corpus tuning.

### 12.15 RR-0031 cognitive-calibration disclosure

For this writer-side packet, the writer read the Goal Blueprint, root and target
`CURRENT_STATE`, RR-0029/RR-0031 and the relevant negative-result map before the
bounded Stage-A/code slice. The writer then inspected the constant-zero scoring
path and current contracts. This sequencing reduces unanchored narrative drift,
but it is not a blind independent review and cannot satisfy the reviewer-side
RR-0031 obligation. The binding reviewer must create a fresh calibration record
before broader code/history exposure and must not inherit this writer's
recommendation as an anchor.

## 13. Falsifiers, invalidation, and stop rules

### 13.1 Instrument falsifiers

Stop before hidden evaluation bytes if any is true:

- any required non-degeneracy metamorphic test fails;
- score changes under identity-only permutation;
- controlled behavior/prediction/test improvements do not change the required
  components and scalar in the specified direction;
- any true challenge outcome falls outside its precommitted universe;
- the scorer requires a family semantic label, case ID, seed, or digest-derived
  numeric feature;
- qualification receipts differ across supported processes/interpreters;
- actor-visible data reveal target outcomes, contrasts, hidden semantics, or
  score feedback;
- `opaque_graph.py` or another family source must change to make the scorer pass.

Disposition: `REVISE_SCORER` or `REJECT_SCORER`; no preregistration.

### 13.2 Run-invalidating conditions

- hidden commitment created or changed after actor output;
- nonce/raw-byte custody or reveal mismatch;
- scorer, actor, prompt, model, challenge, baseline, budget, contrast, or metric
  bytes drift after freeze;
- hidden access or score access before all relevant bundles are sealed;
- budget, reset, retry, timeout, context, token, or final-bundle parity differs
  across matched model arms;
- missing/duplicate/extra instance, arm, prefix, challenge, test, or receipt;
- generated tests overlap probes/challenges or contain dynamic/executable
  expected values;
- C7 halt is followed by adapter, hidden-byte, scorer, or reveal access;
- post-hoc arm/family dropping, imputation, threshold change, weight change,
  metric substitution, sample-size extension, or random-seed selection.

Disposition: matching `INVALID_*` or `STOPPED_NO_VERDICT`, never `NULL` or a
partial winner.

### 13.3 Scientific stop rules

- If strong systematic or stratified random matches ACTIVE_VOI, record the null;
  do not weaken those baselines.
- If FREEFORM matches ACTIVE_VOI, do not claim typed-registry value.
- If PASSIVE lies on the preferred score/cost frontier, do not claim query
  efficiency.
- If calibration worsens beyond a future frozen non-inferiority margin, no
  accuracy-only rescue is allowed.
- If generated-test validity or contrast recall fails its future frozen gate,
  the composite cannot rescue the evaluator claim.
- If HUMAN_STRONG is missing or wins, no strongest-baseline or human-level claim
  is allowed.
- If only F4 holds out, no author-unseen transfer claim is allowed.
- Existing candidates, Q-SCORE, and P-POWER may not be moved into E-SCORE after
  observing a favorable pattern.

Scientific effect thresholds, multiplicity correction, and sample size are
deliberately not frozen by this design-only artifact. The next preregistration
must lock them from a practical effect floor and P-POWER variance before
E-SCORE commitments are revealed. That next artifact is a separate founder and
independent-review gate, not unfinished work inside this spec.

## 14. Companion TDD and validation plan

The non-authorizing RED-first implementation and validation sequence is kept in
the dedicated companion:

`docs/superpowers/plans/2026-07-15-active-discovery-hidden-scoring-tdd-plan.md`

The two files form one atomic `DESIGN_ONLY` packet. Neither file authorizes
implementation, qualification, hidden-byte creation, preregistration, freeze,
model/provider calls, or a scientific run.

## 15. Self-review and allowed next action

### 15.1 Internal consistency checks

- The score is behavior-derived and cannot be computed from bundle digest alone.
- `H`, `C`, and `T` each affect the compatibility scalar and remain visible
  co-gates.
- Query efficiency uses immutable prefixes and delayed scoring.
- Complete-trace universes are public, exhaustive, and
  configuration-independent.
- Tests are held out from probes and challenges and must be valid on target.
- Hidden evaluation bytes are salted, separately custodied, and committed before
  actor output.
- F4 is never called author-unseen.
- No family or runtime code is changed by this lane.
- C6/C7 and product/research/process boundaries remain explicit.
- Existing negative and null outcomes are not rewritten.

### 15.2 Allowed next action

The only allowed successor action is an independent technical and
architecture-theory review of both exact packet documents. A reviewer may return
`ACCEPT_FOR_SPEC`, `REVISE_TO_SPEC`, `PARK_AS_DUE_DILIGENCE`, or rejection under
RR-0029. No implementation, freeze, run, or result follows by implication.
