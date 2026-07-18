# R-W1W2-ABA-1 Revised Design Specification

> Status: `DESIGN_CANDIDATE / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`
> Track: `Research`
> Base: `8982cad9617794b6cc161ba1b4e449cc7f87f99b`
> Package id: `R-W1W2-ABA-1`
> Review disposition: `aba_skeptic = REVISE`
> Primary requirement class: `R`
> Non-authorizations: implementation, Product/Runtime integration, provider result call, private assignment, training, W3/W4 change, freeze, run permit, result run, commit, push, merge, release and autonomy claim

## 1. Design decision

### 1.1 Foundational question

Can bounded typed W1 state and candidate W2 in-envelope strategy selection add value during prospective real software `A1 -> B -> restart -> A2` shifts beyond bounded full-log reconstruction, W1-only state, version-keyed cache and saved workflow under the same observable information and resource rights?

W1 and W2 retain their ratified meanings: W1 is a direct update inside frozen keyspace/reader/retention/influence/invalidation/rollback semantics; W2 selects only among authorized strategies without permission expansion (`/Users/mima1234/Documents/AI-Agent-Projects/docs/research/founder-decision-2026-07-16-adaptive-write-channels-and-requirement-taxonomy.md:22-54`).

### 1.2 Why the current design is not implementation ready

The following are unresolved prerequisites, not implementation details:

- Stage 1 prospective sampling frame and three candidate-blind units do not exist;
- semantic novelty and difficulty-matching rules are not independently accepted;
- observable-information release, reread and static-build-corpus parity are not frozen;
- cache/workflow construction timing and usable bytes are not frozen;
- Stage 1 SESOI/dispersion protocol is not accepted;
- Stage 2 exact N, family-cluster count and inference are intentionally deferred;
- external non-LLM transcript-safe scorer/freezer custody is absent;
- the five content-addressed bundles in §12 are absent.

No implementation task may start from this document. The next permitted action is independent preregistration revision and evidence closure only.

### 1.3 Requirement receipt

```yaml
requirement_claim:
  id: R-W1W2-ABA-1
  primary_class: R
  secondary_class: null
  protects_or_delivers_ref: M3-BOUNDED-OUTCOME-DRIVEN-ADAPTATION
  state: SPECIFIED
  evidence_refs:
    - .agent_runs/r-w1w2-aba-1-design-20260718/research.md
    - .agent_runs/r-w1w2-aba-1-design-20260718/spec.md
  closed_by: null
```

This receipt cannot close a Product or user-outcome claim. Research-to-Product promotion would require a separate real Product entry point, contract and held-out gate (`docs/AGENT-OS-PRODUCT-BLUEPRINT.md:190-198`).

## 2. Normative language and stage separation

- `MUST`/`MUST NOT` define prerequisites for a future preregistration candidate.
- `SHOULD` is a reviewable recommendation, not frozen authority.
- Nothing in this file is a preregistration, freeze receipt or run authorization.
- Stage 1 and Stage 2 use **separate preregistrations, units, hidden manifests, freezes, run permits and adjudications**.
- Stage 1 outcomes may design Stage 2 only through the predeclared public nondominance-observation/dispersion output. No Stage 1 unit, hidden label or arm output enters Stage 2 scoring.

## 3. Two-stage topology

### 3.1 Stage 1 — prospective route kill

Purpose: cheaply screen whether a strong baseline matches/beats the candidate in any of exactly three family blocks and estimate family-blocked dispersion relative to a predeclared smallest effect of interest. Stage 1 cannot prove a mechanism reduction.

Required design:

```text
3 prospective independent units
× 3 distinct families
× 5 matched arms
= 15 arm-unit executions
```

Exactly one Stage 1 unit comes from each family. Units are selected prospectively from a frozen sampling frame by a candidate-blind curator.

Stage 1 arms:

1. `W1W2_CANDIDATE`
2. `W1_ONLY`
3. `VERSION_KEYED_CACHE`
4. `BOUNDED_FULL_LOG`
5. `SAVED_WORKFLOW`

Permitted scientific dispositions:

- `PARK_STAGE1_NONDOMINANCE / OBSERVED_VERSION_KEYED_CACHE_MATCH_IN_<BLOCK> / STOP`
- `PARK_STAGE1_NONDOMINANCE / OBSERVED_BOUNDED_FULL_LOG_MATCH_IN_<BLOCK> / STOP`
- `PARK_STAGE1_NONDOMINANCE / OBSERVED_SAVED_WORKFLOW_MATCH_IN_<BLOCK> / STOP`
- `PARK_STAGE1_NONDOMINANCE / OBSERVED_W1_ONLY_MATCH_IN_<BLOCK> / STOP`
- `PARK_INSUFFICIENT_FEASIBILITY / STOP`
- `ADVANCE_TO_STAGE2_DESIGN`

Stage 1 MUST NOT emit `MET`, `NARROW_MET`, “positive result,” Product evidence or autonomy evidence.

Any killer matching or beating the candidate under §10.2 stops further route investment. Candidate failure to beat `W1_ONLY` does the same. All matching killer/block observations MUST be retained; none supports a general or mechanism-reduction inference. `ADVANCE_TO_STAGE2_DESIGN` means only that no Stage 1 route killer fired; it is not evidence that W1/W2 works.

### 3.2 Stage 2 — disjoint factorial confirmation

Stage 2 may be designed only after `ADVANCE_TO_STAGE2_DESIGN`. It requires:

- a new founder/CTO route continuation decision;
- a new preregistration;
- a new prospective sampling frame or a precommitted disjoint remainder of the original frame;
- new candidate-blind curated lineages/tasks with no Stage 1 overlap;
- a design-blind pilot/sensitivity analysis;
- exact N and exact number of independent family clusters;
- cluster-aware inference and frozen SESOI;
- new scorer/freezer commitments and run authority.

Factorial arms:

| State treatment | Selector treatment | Arm id |
|---|---|---|
| `FULL_LOG` | `SIMPLE_W2` | `FL_SIMPLE` |
| `FULL_LOG` | `CANDIDATE_W2` | `FL_CANDIDATE` |
| `W1_TYPED` | `SIMPLE_W2` | `W1_SIMPLE` |
| `W1_TYPED` | `CANDIDATE_W2` | `W1_CANDIDATE` |

Add `SELECTED_STAGE1_KILLER` as a fixed comparator. The strongest-killer selection algorithm is frozen in Stage 1 (§10.4). If the selected killer is behaviorally identical to a factorial cell, that cell is designated as the killer and is not executed twice.

Stage 2 may support only the claims explicitly powered and frozen in its new preregistration:

- typed-state main effect at fixed selector;
- candidate-selector main effect at fixed state;
- W1×W2 interaction;
- comparison against the selected Stage 1 killer.

It cannot claim “beats every killer” unless the confirmation extension in §3.3 runs.

### 3.3 Stage 2C — optional all-killer confirmation extension

This remains part of the second-stage program, not a third discovery stage. It is required only if the intended final claim still says the candidate beats all Stage 1 killers.

Stage 2C requires another disjoint confirmation pack and new preregistration that re-admits:

- `VERSION_KEYED_CACHE`;
- `BOUNDED_FULL_LOG` under the frozen information contract;
- `SAVED_WORKFLOW`;
- `W1_ONLY`/`W1_SIMPLE` where the claim includes W2 value;
- `W1W2_CANDIDATE`/`W1_CANDIDATE`.

No Stage 1 result can substitute for this confirmation.

## 4. Prospective sampling and unit construction

### 4.1 `ProspectiveSamplingFrameV1`

Before candidate code, prompts or pilot outcomes are exposed to the curator, freeze:

```yaml
frame_id: opaque_string
eligibility_rule_digest: sha256
exclusion_rule_digest: sha256
source_registry_digest: sha256
candidate_family_ids: [opaque_string]
candidate_transition_commitments: [sha256]
license_policy_digest: sha256
local_replay_policy_digest: sha256
selection_algorithm_digest: sha256
curator_role_commitment: sha256
cutoff_timestamp: rfc3339
```

The frame lists eligible real reversible CLI/API/package version/interface/policy transitions. It MUST NOT be constructed by searching for candidate wins.

### 4.2 Candidate-blind curator

The curator:

- may know the generic A/B/A question and eligibility rubric;
- MUST NOT see candidate code, prompt, W1 schema details, selector logic, pilot direction or arm outcomes;
- MUST NOT author or operate the candidate;
- selects Stage 1 units using the frozen frame/algorithm;
- signs a `CandidateBlindCurationReceiptV1`;
- transfers private hidden material directly to the external scorer/freezer, never through an LLM/reviewer/tool transcript.

### 4.3 Unit identity and family independence

A unit is:

```text
real source family
+ independent lineage
+ pinned A revision
+ pinned B revision
+ A1/B/A2 public task sequence
+ semantic novelty/difficulty receipt
+ hidden mechanical outcome manifest commitment
+ restart point
```

Tasks, events, calls, retries and seeds do not increase N. Family is the inference cluster. Stage 1 has three family blocks. Stage 2 exact N cannot be achieved by adding many lineages to too few families if the selected inference requires more clusters.

### 4.4 `SemanticNoveltyDifficultyReceiptV1`

A2 novelty is not established by unequal digests alone. The receipt binds:

```yaml
unit_id: opaque_string
a1_semantic_task_class: closed_enum
a2_semantic_task_class: closed_enum
a1_required_behavior_commitment: sha256
a2_required_behavior_commitment: sha256
behavior_overlap_verdict: DISJOINT_TASK|INVALID_OVERLAP
static_difficulty_features_a1: object
static_difficulty_features_a2: object
mechanical_minimum_steps_a1: nonnegative_integer
mechanical_minimum_steps_b: nonnegative_integer
mechanical_minimum_steps_a2: nonnegative_integer
difficulty_match_verdict: MATCHED|INELIGIBLE
curator_id: string
verifier_id: string
```

Requirements:

- A2 is a novel task in the returned A regime, not an A1 answer replay.
- Expected behavior and hidden assertions are semantically disjoint even if the API surface overlaps.
- Difficulty matching uses only pre-outcome static descriptors and mechanically derived minimum paths.
- No arm performance or hidden score may tune matching.

### 4.5 Claim envelope

All claims are limited to:

> prospectively curated, locally replayable, reversible software version/interface/policy rollback environments represented by the frozen sampling frame and task strata.

No claim extends to arbitrary non-stationarity, irreversible real-world action, other domains or production.

## 5. Observable information and representation treatment

### 5.1 Principle

All arms MUST receive the same potential observable information under the same release schedule and reread/resource rights. **Representation is the treatment; information availability is not.**

Neither “full log” nor “typed W1” receives free unlimited access. Every read/reread is explicit and charged.

### 5.2 `ObservableInformationContractV1`

```yaml
unit_id: opaque_string
source_provenance_manifest_digest: sha256
observable_object_ids: [opaque_string]
release_schedule_digest: sha256
static_prior_corpus_digest: sha256
static_build_corpus_digest: sha256
reread_policy:
  max_operations_per_phase: integer
  max_bytes_per_phase: integer
  max_wall_seconds_per_phase: integer
  allowed_object_classes: [closed_enum]
resource_ceiling_digest: sha256
public_version_projection_digest: sha256
forbidden_observation_classes: [closed_enum]
```

The release schedule freezes exactly when each public observation and past public outcome becomes available. An arm cannot read future-released bytes even if those bytes already exist on disk.

### 5.3 Static prior and build corpus

- `STATIC_PRIOR_CORPUS` is common to all arms and frozen before unit selection.
- `STATIC_BUILD_CORPUS` is the only corpus usable to construct saved workflows or optional warm cache entries.
- Neither corpus contains Stage 1/2 unit tasks, hidden manifests, future outcomes, scorer artifacts or candidate-derived labels.
- Every usable byte is content-addressed; unlisted bytes fail closed.

### 5.4 Representation treatments

`FULL_LOG` representation:

- stores released observations in bounded chronological form;
- may reread only through `RereadLedgerV1` under the common reread ceiling;
- cannot receive a curator summary, hidden index or free retrieval oracle;
- uses the same static prior/build corpus as W1 arms.

`W1_TYPED` representation:

- transforms only already released observations into typed, provenance-bound records;
- uses the same total observable source universe and reread ceiling;
- cannot add semantic labels unavailable in the released bytes;
- must record invalidation, rollback, reader, retention and decision-influence bounds.

### 5.5 `RereadLedgerV1`

Every access after first release records:

```yaml
arm_id: opaque_string
unit_id: opaque_string
phase_slot: opaque_integer
object_id: opaque_string
byte_count: integer
operation_index: integer
wall_seconds_charged: finite_number
budget_before_digest: sha256
budget_after_digest: sha256
```

Unlogged rereads invalidate the unit.

## 6. Cache and workflow construction integrity

### 6.1 `ConstructionBoundaryManifestV1`

```yaml
arm_id: VERSION_KEYED_CACHE|SAVED_WORKFLOW
implementation_digest: sha256
construction_started_at: rfc3339
construction_sealed_at: rfc3339
static_build_corpus_digest: sha256
usable_input_byte_digests: [sha256]
forbidden_after_cutoff_inputs: [closed_enum]
initial_state_digest: sha256
online_update_policy_digest: sha256
builder_id: string
independent_verifier_id: string
```

### 6.2 Version-keyed cache

- Implementation and keying algorithm are frozen before prospective units are exposed.
- Default initial cache is empty unless the preregistration explicitly permits a common warm prior from `STATIC_BUILD_CORPUS`.
- During a unit, it may store only released public-derived state at the frozen post-release update points.
- A1 entries may be restored at A2 by public version key; this is intended killer behavior.
- It cannot store hidden outcomes, expected answers, scorer output or unreleased bytes.
- Its storage/reread/resource ceilings match the observable information contract.

### 6.3 Saved workflow

- Workflow bytes are constructed and sealed only from `STATIC_BUILD_CORPUS` before prospective unit exposure.
- The workflow cannot be edited, regenerated or selected using Stage 1/2 result-unit outcomes.
- Version selection uses only frozen public version metadata.
- Failure remains visible; fallback to a model-generated new workflow is forbidden.

### 6.4 Construction-time violations

Any unlisted input byte, late build, result-unit exposure, hidden-material contact or post-cutoff regeneration is `INVALID_CONSTRUCTION_ORACLE` and stops the stage.

## 7. Arm definitions

### 7.1 Common selector vocabulary

All selector-using arms choose from the same frozen authorized strategy set. No selector can create a strategy, capability, evaluator, permission or W3/W4 candidate.

`SIMPLE_W2` is a closed deterministic selector using frozen recent public outcome statistics and current public context. Its algorithm, tie-break and parameters are frozen before units.

`CANDIDATE_W2` is the proposed selector. It consumes only its assigned state representation and released public outcomes, stays within the same strategy/action set and emits a decision receipt.

### 7.2 Stage 1 arms

| Arm | State/representation | Selector/procedure | Construction boundary |
|---|---|---|---|
| `W1W2_CANDIDATE` | `W1_TYPED` | `CANDIDATE_W2` | candidate code/prompts frozen; no curator/private access |
| `W1_ONLY` | `W1_TYPED` | `SIMPLE_W2` | same W1 treatment as candidate; selector fixed |
| `VERSION_KEYED_CACHE` | bounded version-keyed public-derived state | frozen cache retrieval policy | §6.2 |
| `BOUNDED_FULL_LOG` | `FULL_LOG` | `SIMPLE_W2` | same reread/resource rights; no free log scan |
| `SAVED_WORKFLOW` | frozen workflow state only | static version-keyed workflow dispatch | §6.3 |

`W1_ONLY` is the candidate's W2 ablation. Any candidate failure to beat it stops Stage 1.

### 7.3 Stage 2 factorial arms

The two state treatments and two selector treatments are crossed without changing any other budget, prompt, tool, strategy set, observation or release rule.

- `FL_SIMPLE`: `FULL_LOG × SIMPLE_W2`
- `FL_CANDIDATE`: `FULL_LOG × CANDIDATE_W2`
- `W1_SIMPLE`: `W1_TYPED × SIMPLE_W2`
- `W1_CANDIDATE`: `W1_TYPED × CANDIDATE_W2`

The candidate W2 implementation is byte-identical across `FL_CANDIDATE` and `W1_CANDIDATE` except for the typed input adapter required by the frozen state schema. The simple W2 implementation is byte-identical across its two cells under the same constraint.

### 7.4 Strongest-killer comparator

The Stage 1 preregistration freezes the deterministic selector in §10.4. The selected killer enters Stage 2 unchanged, with new-unit state and the same construction policy.

## 8. Core objects and receipts

All schemas are closed, canonically serialized, versioned and content-addressed. Unknown fields fail closed.

### 8.1 `AdaptationEnvelopeV1`

```yaml
w1:
  allowed_record_types: [closed_enum]
  keyspace_digest: sha256
  allowed_readers: [string]
  retention_horizon: integer
  max_persisted_bytes: integer
  max_decision_influence: closed_enum
  invalidation_rules_digest: sha256
  rollback_rules_digest: sha256
w2:
  authorized_strategy_ids: [opaque_string]
  resource_ceiling_digest: sha256
  stop_rules_digest: sha256
authority:
  permission_ceiling_digest: sha256
  c7_subject_digest: sha256
  w5_forbidden_fields: [string]
```

Any attempt to change schema, readers, retention, maximum influence, default procedure, strategy set or permission returns `OUT_OF_ENVELOPE_W3_REQUIRED` and cannot affect the active arm.

### 8.2 `W1StateRecordV1`

```yaml
record_id: opaque_string
unit_id: opaque_string
arm_id: opaque_string
state_type: fact|belief|confidence|plan|task_state|retrieval_ref
source_observation_refs: [sha256]
claim_or_state_digest: sha256
validity: ACTIVE|DISPUTED|INVALIDATED|ROLLED_BACK|EXPIRED
version: positive_integer
supersedes_record_id: opaque_string|null
invalidation_reason_ref: sha256|null
rollback_target_version: integer|null
created_after_release_index: integer
```

Every source ref must already be released under `ObservableInformationContractV1`.

### 8.3 `W2DecisionReceiptV1`

```yaml
decision_id: opaque_string
unit_id: opaque_string
arm_id: opaque_string
release_index: integer
selected_strategy_id: opaque_string
consumed_state_refs: [sha256]
consumed_public_outcome_refs: [sha256]
budget_before_digest: sha256
permission_ceiling_digest: sha256
stop_condition_ref: sha256
```

### 8.4 Stage and execution receipts

Future artifacts include:

- `StagePreregistrationCommitmentV1`
- `FamilyUnitManifestV1`
- `CandidateBlindCurationReceiptV1`
- `SemanticNoveltyDifficultyReceiptV1`
- `ObservableInformationContractV1`
- `ConstructionBoundaryManifestV1`
- `ArmTreatmentManifestV1`
- `ResourceParityReceiptV1`
- `PhaseTransitionReceiptV1`
- `RestartReceiptV1`
- `RollbackReceiptV1`
- `GlobalArmOutputSealV1`
- `ClosedScoreReceiptV1`
- `StageAdjudicationReceiptV1`

These are grouped into five freeze bundles in §12; they are not 20 independent governance layers.

## 9. Metrics

### 9.1 Verified-outcome loss

For arm `a`, unit/family block `u`, task `t`:

```text
verified[a,u,t] in {0,1}
task_loss[a,u,t] = 1 - verified[a,u,t]
unit_loss[a,u] = mean_t(task_loss[a,u,t])
```

- Every frozen outcome-bearing task has equal weight unless a pre-outcome external risk rationale freezes another weight.
- Partial credit is forbidden in Stage 1.
- Unsupported/unknown evaluation fails closed according to the frozen failure table.
- Safety and integrity are vetoes, not weighted loss penalties.

### 9.2 Mechanical minimum and excess steps

For phase `p in {B,A2}`:

```text
mechanical_minimum_steps[u,p] =
  shortest mechanically valid authorized action/tool path
  computed from hidden exact task mechanics before freeze

observed_recovery_steps[a,u,p] =
  actions/tool calls from first released phase observation
  through the first predeclared recovery condition

excess_steps[a,u,p] =
  observed_recovery_steps[a,u,p] - mechanical_minimum_steps[u,p]
```

Requirements:

- `mechanical_minimum_steps` is computed by a non-LLM mechanical enumerator/verifier in private custody.
- It is committed before arm execution and never exposed online.
- Excess steps cannot be negative.
- Failure to recover receives `phase_action_ceiling + 1 - mechanical_minimum_steps`.
- Zero versus zero is a tie and a killer win in Stage 1.
- The removed 80% raw-latency ratio is not used.

### 9.3 Stale-belief harm

A stale-harm event requires:

1. frozen truth contradicts an active state/cache/workflow item;
2. the decision receipt cites that item as consumed input;
3. the resulting outcome fails or requires rollback;
4. the external scorer mechanically verifies the causal consumption chain.

Correlation alone does not count.

### 9.4 Repeated error and rollback

- `REPEATED_ERROR`: a frozen failure signature recurs after a released correction/outcome that should invalidate its cause.
- `ROLLBACK_SUCCESS`: all declared readers stop consuming invalid state before the next consequential decision.
- `ROLLBACK_FAILURE`: partial reader update, stale descendant, missing provenance or reuse after rollback.

### 9.5 Resource accounting

Report per arm/unit:

- provider calls/input/output tokens;
- tool calls/retries/actions;
- wall time;
- first reads and rereads by bytes/operations/time;
- persisted state bytes/writes/retention;
- direct provider/tool cost where available.

Resource mismatch is an integrity failure, not an adjustment covariate chosen after results.

### 9.6 Stage 1 family-blocked dispersion and SESOI

Before Stage 1 hidden opening, an independent route owner freezes externally justified SESOI candidates for:

- unit-loss difference;
- B excess-step difference;
- A2 excess-step difference;
- maximum acceptable stale-harm/rollback regression.

Stage 1 reports the three family-block differences and their range/robust descriptive dispersion. With only three blocks it MUST NOT claim a stable standard error, significance, confidence interval or positive effect. The public Stage 1 output may recommend Stage 2 sensitivity scenarios, but cannot choose the most favorable SESOI from observed direction.

### 9.7 Stage 2 inference

The Stage 2 preregistration must freeze:

- exact N and family-cluster count;
- family sampling/allocation;
- primary estimand(s);
- SESOI;
- cluster-aware estimator and uncertainty interval/test;
- multiplicity policy for state main effect, selector main effect and interaction;
- missing-unit handling;
- stopping and confirmation rules.

No exact N or positive gate is authorized in this design. The design-blind pilot cannot use candidate-vs-baseline outcome direction.

## 10. Stage gates and dispositions

### 10.1 Precedence

For each stage:

1. `KILL_CURRENT_IMPLEMENTATION / SAFETY_REGRESSION`
2. `INVALID`
3. `PARK_STAGE1_NONDOMINANCE` or another prefrozen `PARK`
4. `ADVANCE_TO_STAGE2_DESIGN` for Stage 1 only
5. Stage 2 scientific verdict defined by its future preregistration

### 10.2 Stage 1 comparison rule

Within each of the three family blocks, compare the candidate with each killer using this frozen lexicographic vector:

```text
1. lower unit_loss
2. if tied, lower A2 excess_steps
3. if tied, lower B excess_steps
4. if tied, lower stale_harm count
5. if still tied, tie = killer win
```

Stage 1 stops if:

- any of `VERSION_KEYED_CACHE`, `BOUNDED_FULL_LOG` or `SAVED_WORKFLOW` matches/beats the candidate in any family block;
- `W1_ONLY` matches/beats the candidate in any family block;
- candidate has any rollback/safety regression beyond a comparator;
- any arm is not operationally qualified;
- family-block dispersion or feasibility makes Stage 2 power/resource needs unacceptable.

Only strict candidate wins over all four comparators in all three family blocks, plus no safety/integrity failure, permits `ADVANCE_TO_STAGE2_DESIGN`. This is deliberately a harsh route-kill rule, not a positive gate.

### 10.3 Stage 1 dispositions

If multiple comparators match/beat in multiple blocks, report every `OBSERVED_<KILLER>_MATCH_IN_<BLOCK>` under one `PARK_STAGE1_NONDOMINANCE` disposition. Do not select the most flattering observation. Stage 1 observations are exact sample-bound nondominance only and cannot emit `REDUCES_TO_*`. `ADVANCE_TO_STAGE2_DESIGN` carries the literal boundary `NO_MET / NEW_PREREG_REQUIRED`.

### 10.4 Strongest Stage 1 killer selection

Before Stage 1, freeze this selection among `VERSION_KEYED_CACHE`, `BOUNDED_FULL_LOG`, `SAVED_WORKFLOW`:

1. lowest mean family-block unit loss;
2. then lowest mean A2 excess steps;
3. then lowest mean B excess steps;
4. then lowest measured direct resource cost;
5. fixed tie order: `VERSION_KEYED_CACHE`, `SAVED_WORKFLOW`, `BOUNDED_FULL_LOG`.

The selected id is emitted only after the Stage 1 global seal. It becomes a fixed Stage 2 comparator. This data-dependent selection is allowed only because Stage 2 uses new disjoint units and the selection rule is predeclared.

### 10.5 Stage 2 positive/negative gate

This document does not set a Stage 2 positive or negative-inference threshold. The new preregistration must derive and freeze exact gates from an externally justified SESOI, design-blind dispersion/power work and cluster-aware inference. Only such an independent, disjoint, prefrozen negative-inference/precision design may authorize a true `REDUCES_TO_*` conclusion. It must retain:

- ties/uncertainty favoring the relevant baseline;
- zero safety/C7/W5/permission/audit violations;
- no stale-harm/rollback regression beyond the frozen tolerance;
- explicit reduction to W1-only if candidate W2 adds no value;
- explicit reduction to full-log if typed state adds no value;
- claim restriction to the selected killer unless Stage 2C re-admits all killers.

## 11. External non-LLM scorer/freezer custody

### 11.1 Required topology

```text
candidate-blind curator
  -> private direct channel
external non-LLM freezer/private store
  -> public commitments only
arm executor(s)
  -> sealed arm outputs
global arm-output seal
  -> external non-LLM scorer
  -> closed public score receipt
public-only verifier/adjudicator
```

Required identity separation:

```text
curator_id != candidate_builder_id
candidate_builder_id != scorer_id
freezer_id != executor_id
scorer_id != public_adjudicator_id
c7_owner_id != executor_id
```

### 11.2 Absolute transcript prohibition

The following MUST never enter an LLM, reviewer, chat, agent-tool or ordinary CI transcript:

- keys or key-derived secrets;
- hidden source identities;
- unit-to-family private mappings where hidden;
- hidden manifests or raw hidden rows;
- hidden tests/expected outcomes;
- mechanical-minimum private paths;
- arm-result labels before global seal;
- scorer intermediate objects, debug dumps or exception payloads.

Prompt instructions, later redaction and transcript deletion do not satisfy this boundary.

### 11.3 Frozen dataflow and egress policy

Before stage freeze, `PrivateDataflowEgressPolicyV1` binds:

- allowed private input principals and endpoints;
- storage/mount/process namespace;
- log, stdout/stderr, metrics and crash-dump suppression;
- network and filesystem egress denylist/allowlist;
- allowed public commitment schema before execution;
- global-seal condition;
- allowed closed score schema after seal;
- immutable incident receipt on any breach;
- no re-key/retry after hidden opening.

### 11.4 Global seal and closed output

Before global seal, the service may emit only public digests, aggregate eligibility counts and predeclared integrity booleans that reveal no hidden identity/outcome direction.

`GlobalArmOutputSealV1` binds all arm/unit output digests, missing-output status, stage spec, provider/tool subjects and execution receipts. Only after this seal may scoring begin.

Post-seal output is schema-closed to:

- opaque unit/family block ids;
- task-level verified/not-verified bits where allowed;
- predeclared metric components;
- integrity/safety booleans;
- named nondominance-observation/advance inputs;
- selected strongest-killer id;
- exact subject digests.

No reviewer loads private objects. The public adjudicator verifies receipts and applies frozen precedence only.

## 12. Five content-addressed prerequisite bundles

The former 20-item list is replaced by five bundles. Each bundle has one canonical manifest, exact-content child digests, owner/reviewer identities and an acceptance receipt. This compression does not remove semantic gates.

### B1. `DESIGN_AUTHORITY_BUNDLE`

Contains:

- exact research basis/spec/preregistration;
- foundational problem, null/nondominance thesis and claim ceiling;
- prior negative map and C6/C7/W3-W5 analysis;
- stage separation and stop rules;
- SESOI rationale and Stage 1/2 decision policy;
- role-separation manifest;
- founder/CTO route and later run-authority placeholders.

Acceptance: independent methodology/skeptic review of exact bytes with no unresolved P0/P1.

### B2. `SAMPLING_INFORMATION_BUNDLE`

Contains:

- prospective sampling frame;
- source/license/provenance manifests;
- family/unit manifests and independence witnesses;
- candidate-blind curation receipts;
- semantic novelty/difficulty receipts;
- observable information contracts and release schedules;
- static prior/build corpus;
- cache/workflow construction cutoffs and usable-byte manifests;
- private hidden commitments only, never private bytes in public bundle.

Acceptance: independent curator/verifier identities, reproducible public source bytes, candidate-blindness and no information shortcut.

### B3. `ARM_TREATMENT_BUNDLE`

Contains:

- exact arm code/prompts/configuration;
- W1 and W2 contracts/envelopes;
- Stage 1 or Stage 2 treatment matrix;
- selector/strategy vocabulary;
- observable-information and resource-rights parity; representation intentionally differs;
- reread policy and ledgers;
- baseline/candidate liveness qualification;
- provider/model/tool/container exact subjects.

Acceptance: every arm qualified, representation-only treatment confirmed, no free reread or unequal instruction.

### B4. `SCORER_CUSTODY_BUNDLE`

Contains:

- external non-LLM freezer/scorer identity and service digest;
- private dataflow/egress policy;
- public commitment and closed output schemas;
- metric/gate code commitments and canonical public test vectors;
- global-seal protocol;
- key/hidden-material custody attestation;
- public-only verifier and incident schema.

Acceptance: no LLM/reviewer/tool private access, fail-closed egress and independent custody proof.

### B5. `EXECUTION_INTEGRITY_BUNDLE`

Contains:

- stage exact-content manifest root;
- arm-order/blinding schedule;
- one-shot execution plan and provider drift canary;
- C7 pre/post subject bindings;
- budget/state/reread enforcement;
- execution/restart/rollback/global-seal receipts;
- external freeze receipt;
- separate one-shot Founder/CTO run authorization requirement;
- adjudication precedence and negative-map update contract.

Acceptance: exact-head independent review, replay refusal, one-shot CAS semantics and no missing executable/prompt/unit/metric/gate byte.

No bundle exists yet. The design remains `NOT_IMPLEMENTATION_READY`.

## 13. Future test plan

This section specifies tests required before implementation readiness; it does not authorize writing them.

### 13.1 Sampling and curation

- reject retrospective frame creation or post-candidate unit selection;
- verify curator cannot read candidate artifacts or Stage 1 outcomes;
- reject fewer than three Stage 1 families or lineage reuse;
- detect shared templates disguised by opaque ids;
- reject digest-distinct but semantically equivalent A1/A2 tasks;
- reject difficulty matching that uses arm performance/hidden outcomes.

### 13.2 Observable information parity

- all arms receive the same released object universe at every release index;
- future-released bytes remain unreadable even if present on disk;
- every reread charges operations, bytes and time;
- unlogged/free full-log scans fail;
- W1 typed records cannot introduce labels absent from released sources;
- static prior/build corpus drift fails all dependent arms.

### 13.3 Cache/workflow construction

- late build or result-unit byte access fails;
- warm cache bytes outside the common static corpus fail;
- version cache restores A entries only from allowed public-derived state;
- saved workflow is executable, fixed and visibly fails on unsupported paths;
- no hidden/task-answer/scorer bytes enter either artifact.

### 13.4 W1/W2 authority

- W1 cannot add readers, extend retention, increase influence or change default semantics;
- invalidation/rollback closes all declared descendants/readers;
- W2 cannot add strategy/capability/permission or write W5/evaluator/audit;
- candidate and simple selectors share the same authorized strategy set;
- candidate W2 code is invariant across the two Stage 2 state cells apart from frozen adapter typing.

### 13.5 Stage logic

- Stage 1 can emit only `PARK_STAGE1_NONDOMINANCE` with exact block observations, another prefrozen `PARK`, or `ADVANCE_TO_STAGE2_DESIGN`; never `MET` or `REDUCES_TO_*`;
- any killer tie triggers STOP;
- candidate tie/loss to W1-only triggers STOP;
- strongest-killer selection follows the frozen lexicographic rule;
- Stage 2 rejects any Stage 1 unit/hidden/task overlap;
- all-killer wording is rejected without Stage 2C receipts.

### 13.6 Metrics

- mechanical minimum is nonnegative, exact-subject bound and private;
- excess steps equal observed minus minimum and cannot be negative;
- zero/zero latency is a tie;
- no 80% raw-latency rule remains;
- Stage 1 output contains family-block values/dispersion only, no significance/MET;
- Stage 2 refuses missing exact N, cluster estimator, SESOI or multiplicity policy.

### 13.7 Scorer/freezer custody

- attempt key/hidden-manifest access from LLM, reviewer, tool and CI identities and assert refusal;
- suppress/inspect stdout, stderr, metrics, crash dumps and exception egress;
- reject scoring before global seal;
- reject partial/per-unit directional output before all arms seal;
- reject unknown closed-output fields;
- any breach produces immutable incident and no retry.

### 13.8 Integrity and safety

- tamper every bundle/child digest, role, subject, provider/tool version and assert rejection;
- replay freeze/run/global-seal receipts and assert refusal;
- force C7 correction before/during/after action and verify dominance;
- reject permission expansion, W5 write and audit deletion;
- prove green design/qualification tests cannot mint freeze or run authority.

## 14. Missing-data, failure and one-shot rules

### 14.1 Stage 1

- No reserve replacement is allowed after any hidden directional output exists.
- An arm operational failure before global seal follows a predeclared retry policy identical for model-using arms; exhausted retries produce `PARK_INSUFFICIENT_FEASIBILITY` or `INVALID` per frozen cause table, never candidate advantage.
- A baseline that fails liveness blocks stage freeze; it cannot be dropped.
- Scientific underperformance never permits unit replacement or rerun.

### 14.2 Stage 2

The new preregistration freezes missing-cluster/unit handling and any prospectively selected reserve policy before hidden opening. Replacement cannot depend on result direction and must preserve cluster allocation.

### 14.3 One-shot

After a stage's private hidden material is mounted or first arm execution begins, there is no re-key, reseed, task substitution, threshold change, arm change, provider change or selective rerun. Run-wide invalidity requires a new package decision and preserves the failed receipts.

## 15. Stop rules

### Stop now — before implementation

Stop while any of these remain unresolved:

- five accepted bundles absent;
- prospective candidate-blind frame/curator absent;
- observable information/reread/build corpus not frozen;
- external scorer/freezer custody absent;
- SESOI and Stage 1 dispersion protocol unaccepted;
- semantic novelty/difficulty protocol unaccepted.

### Stop Stage 1 design/freeze

Stop if:

- fewer than three eligible independent families;
- candidate-blindness cannot be proven;
- unit truth is not mechanically groundable;
- representation cannot be isolated from information availability;
- any killer/candidate arm fails liveness;
- external private dataflow cannot exclude all LLM/reviewer/tool transcripts;
- complete 15-execution design exceeds the accepted resource ceiling.

### Stop after Stage 1

Stop further route investment on any killer match/beat observation, W1-only failure, integrity/safety failure or unacceptable Stage 2 feasibility. Preserve `PARK_STAGE1_NONDOMINANCE`, all exact block observations, `INVALID` and safety-kill outcomes without narrative rescue.

### Stop Stage 2

Stop if no exact N/cluster-aware prereg can be justified, new units are not disjoint, selected-killer treatment drifts, or the claim exceeds the frozen comparator set.

## 16. Claim ceiling

### 16.1 Stage 1

Permitted favorable statement:

> Across three prospectively curated independent family blocks, no predeclared Stage 1 route killer fired under the frozen information/resource contract; the route may design a disjoint Stage 2 preregistration.

This is `ADVANCE_TO_STAGE2_DESIGN / NO_MET`, not evidence of adaptation value.

### 16.2 Stage 2

A future positive claim, if supported, is limited to the exact factorial effect(s) and selected killer in:

> prospectively curated, locally replayable, reversible software version/interface/policy rollback environments within the frozen sampling frame.

It cannot claim all-killer superiority unless Stage 2C confirms the full killer set on disjoint units.

### 16.3 Permanent non-claims

- general online learning;
- arbitrary-domain transfer;
- a general catastrophic-forgetting solution;
- Product capability/value/release readiness;
- W3/W4/core-evolution evidence;
- general intelligence, AGI or `Autonomy(S,E,O,V,T)`.

### 16.4 Negative/integrity outcomes

`PARK_STAGE1_NONDOMINANCE` and every attached `OBSERVED_<KILLER>_MATCH_IN_<BLOCK>` remain durable, but mean only nondominance in the exact three prospectively curated sample blocks under the frozen contract. They are not a general proof and do not establish mechanism reduction. The parked route may be reopened only by a newly authorized foundational question plus new disjoint evidence; new architecture vocabulary, post-hoc subgroup/threshold changes, added families or reruns of the same sample cannot rescue it. `INVALID` and safety-kill outcomes remain durable under their own scopes. A true future `REDUCES_TO_*` label requires an independent, disjoint, prefrozen negative-inference/precision design.

## 17. Acceptance updates required before the next review

The next exact-byte review should accept or reject these revisions:

1. Status is `DESIGN_CANDIDATE / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
2. Stage 1 is exactly 3 prospective units/3 families × 5 arms and cannot emit MET.
3. Any killer match/beat or candidate failure versus W1-only stops the route.
4. Stage 2 requires new disjoint units and a new preregistration.
5. Stage 2 uses the 2×2 state/selector factorial plus the predeclared strongest Stage 1 killer.
6. Any all-killer final claim requires Stage 2C full-killer confirmation.
7. Observable information provenance/release/static prior/build corpus/reread rights/resource ceilings are frozen independently from representation.
8. Cache/workflow construction cutoff and usable bytes are exact-bound.
9. Latency uses excess steps over mechanical minimum; the 80% raw ratio is removed.
10. Stage 1 reports only family-block dispersion/SESOI comparisons and exact sample-bound nondominance observations with PARK/ADVANCE decisions; it cannot emit a mechanism-reduction conclusion.
11. Stage 2 freezes exact N and cluster-aware inference after design-blind pilot work.
12. Sampling is prospective and candidate-blind with semantic novelty plus difficulty matching.
13. Scorer/freezer is external, non-LLM and transcript-safe with global seal and closed egress.
14. Prerequisites are five content-addressed bundles preserving all semantic gates.
15. No implementation work is authorized from this revision.

## 18. Current completion state

```text
research basis: revised after skeptic REVISE
design specification: revised candidate
implementation readiness: NOT READY
preregistration: REVISE / absent as accepted exact artifact
independent acceptance: pending
five prerequisite bundles: absent
implementation: not started / not authorized
freeze: absent
run authority: absent
result: absent
Product integration: absent
release: absent
```
