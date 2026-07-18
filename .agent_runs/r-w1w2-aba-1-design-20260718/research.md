# R-W1W2-ABA-1 Research Basis

> Status: `DESIGN_CANDIDATE / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`
> Track: `Research`
> Base: `8982cad9617794b6cc161ba1b4e449cc7f87f99b`
> Review disposition: `aba_skeptic = REVISE`
> Scope: evidence and constraints for a prospective real replayable `A1 -> B -> restart -> A2` W1/W2 falsifier
> Non-authorization: no implementation, training, provider result call, freeze, private assignment, run permit, result run, Product integration, commit, push, merge, release or autonomy claim

## 1. Executive judgment

The first draft is **not implementation ready**. Its one-stage 8-arm/9-unit design mixed three questions:

1. whether the candidate survives strong cheap killers;
2. whether structured W1 state adds value beyond a bounded full-log representation;
3. whether candidate W2 selection adds value beyond a simple selector.

It also allowed “full log” to imply free unlimited rereads, proposed a 20% latency ratio that can be contradictory on small integer paths, and proposed positive gates before estimating family-blocked dispersion. Those defects make the exact design `PREREG_REVISE`, not a freeze or implementation candidate.

The corrected route is sequential:

- **Stage 1 — prospective route kill:** exactly 3 candidate-blind curated independent units from 3 families and 5 arms: `W1W2_CANDIDATE`, `W1_ONLY`, `VERSION_KEYED_CACHE`, `BOUNDED_FULL_LOG`, `SAVED_WORKFLOW`. Permitted scientific dispositions are only `PARK_STAGE1_NONDOMINANCE` or `ADVANCE_TO_STAGE2_DESIGN`; a park records one or more `OBSERVED_<KILLER>_MATCH_IN_<BLOCK>` observations. Stage 1 can never emit `MET` or a mechanism-reduction claim. Any killer match/beat, or candidate failure to beat W1-only, stops further route investment.
- **Stage 2 — disjoint factorial confirmation:** only after Stage 1 survives, create a new preregistration and new disjoint prospective units. Use a 2×2 design `state={FULL_LOG,W1_TYPED} × selector={SIMPLE_W2,CANDIDATE_W2}`, plus the predeclared strongest Stage 1 killer. Exact N, number of family clusters, SESOI and cluster-aware inference are frozen from a design-blind pilot/sensitivity analysis. If the final claim still says “beats every killer,” a further disjoint confirmation must re-admit the full killer set.

The scientific priority remains cheap-baseline route screening. `VERSION_KEYED_CACHE`, bounded full-log reconstruction and saved workflow are not weak controls; they are candidate explanations. A match is a route stop, not a reason to add memory/UCM/latent/recurrent architecture, but the exact three-block match is only sample-bound nondominance evidence.

## 2. Sources and authority

The task brief fixes the A/B/A question, real-lineage requirement, hidden-oracle boundary, strong baselines and prohibition on implementation/training/freeze/run (`.agent_runs/r-w1w2-aba-1-design-20260718/brief.md:3-44,55-71`). The current task status is being downgraded in response to the independent skeptic's `REVISE` verdict.

Local authority and negative evidence:

- M1/M2/M3 and claim discipline: `/Users/mima1234/Documents/AI-Agent-Projects/docs/GOAL-BLUEPRINT.md:10-68`;
- W1-W5 semantics: `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/founder-decision-2026-07-16-adaptive-write-channels-and-requirement-taxonomy.md:9-69,130-154`;
- current W1/W2 evidence boundary: `docs/CURRENT_STATE.yaml:283-318,544-581`;
- adaptation/evaluation requirements: `docs/AGENT-OS-PRODUCT-BLUEPRINT.md:164-198,236-284`;
- Research route/run gates: `docs/PROJECT_PLAN.md:135-177`;
- R-STATE invalidity findings: `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/portfolio-attack-review-synthesis-2026-07-16.md:69-80`;
- prior negative map and cheap baselines: `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/architecture-theory-review-unified-cognition-agent-os-joint-loop-2026-07-15.md:214-263`;
- adaptivity-gap `PARK`: `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/ROUTE-adaptivity-gap-2026-07-10/07-stage0-submodularity-gonogo-PARK.md:1-69`;
- anti-pseudoreplication, role separation and oracle reference: `docs/research/R-SRL-1-preregistration-2026-07-16.md:24-66,68-113,197-256`.

## 3. Facts

### F1. W1 and W2 are bounded write channels, not general learning labels

W1 can update task/belief/state only inside a pre-ratified keyspace, reader, retention, maximum-influence, invalidation and rollback envelope. Changing those semantics is W3 (`/Users/mima1234/Documents/AI-Agent-Projects/docs/research/founder-decision-2026-07-16-adaptive-write-channels-and-requirement-taxonomy.md:24-28`). W2 can select only among authorized strategies without permission expansion and with outcome, resource and stop records (`.../founder-decision-2026-07-16-adaptive-write-channels-and-requirement-taxonomy.md:30-34`).

### F2. No current result establishes W1/W2 effectiveness

Current state says the integrated SRL path remains proposal-only and real W1/W2 outcome-driven effectiveness is open (`docs/CURRENT_STATE.yaml:283-318`). The blocker list says W1/W2 direct adaptation and independent scorer/freezer custody remain incomplete (`docs/CURRENT_STATE.yaml:544-563`). Contracts and tests cannot backfill this missing result.

### F3. Prior R-STATE failed on leakage, pseudoreplication and treatment mismatch

The prior exact-head review found `family + checkpoint` metadata predicted hidden truth `560/560`, 140 seed pairs reduced to seven templates, authority records were self-fillable, arm order was fixed, one arm received a policy directive, and the environment was static classification (`/Users/mima1234/Documents/AI-Agent-Projects/docs/research/portfolio-attack-review-synthesis-2026-07-16.md:69-80`). These findings require prospective units, opaque identities, cluster-aware inference, equal instructions and interactive outcomes.

### F4. Synthetic adaptivity-gap revival remains prohibited

The prior route is `PARK`; its surviving synthetic construction was non-authorizing and reducible to an oracle/non-myopic planner (`/Users/mima1234/Documents/AI-Agent-Projects/docs/research/ROUTE-adaptivity-gap-2026-07-10/07-stage0-submodularity-gonogo-PARK.md:50-69`). This route therefore needs real, provenance-bound, locally replayable version/interface/policy rollbacks and cannot claim an exponential adaptivity gap.

### F5. Product evaluation already requires information, cost and stale-harm controls

The Product Blueprint requires provenance, conflict/invalidation and correction for beliefs (`docs/AGENT-OS-PRODUCT-BLUEPRINT.md:164-188`). Its benchmark dimensions include recovery, state equivalence, correction/rollback, cross-session retention without stale harm, cost and pinned provider/tool/retry/evaluator settings (`docs/AGENT-OS-PRODUCT-BLUEPRINT.md:236-262`). These are design constraints, not Product evidence.

### F6. Unit identity is a lineage, not a step or seed

The brief requires independent lineage/version/task units (`brief.md:17-23`). R-SRL-1 likewise defines a unit as a distinct lineage, snapshot, mission and sealed event sequence, never a call/event/seed (`docs/research/R-SRL-1-preregistration-2026-07-16.md:24-34`). Family clustering remains relevant even when lineages are distinct.

### F7. Freeze and run remain separate from design

Research admission requires a negative map, strong cheap baselines, architecture review, preregistration, exact manifests, independent review and freeze before one result-bearing run (`docs/PROJECT_PLAN.md:135-150`). Green implementation tests never authorize that run (`docs/PROJECT_PLAN.md:169-177`).

## 4. Inferences

### I1. Observable information must be frozen independently from representation

The treatment cannot be “candidate sees curated state while baseline has to rediscover everything” or “full-log gets unlimited free rereads.” Every arm must share a frozen `ObservableInformationContract`: source provenance, release timing, static prior/build corpus, reread rights and resource ceilings. Representation is the treatment: bounded chronological full-log projection versus bounded typed W1 state. Reread operations consume the same frozen budget.

### I2. Cache/workflow construction timing is part of treatment integrity

A saved workflow built after seeing candidate units or a cache preloaded with A1 answers is an oracle. The build corpus, build cutoff, builder identity and usable bytes must be frozen. `VERSION_KEYED_CACHE` begins each prospective unit with the predeclared initial state and may populate only from released public bytes on the frozen schedule; `SAVED_WORKFLOW` is built only from the static build corpus and cannot learn from result units.

### I3. Stage 1 can estimate route shape but cannot support a positive claim

One unit per family provides only three family blocks. It can reveal exact sample-bound killer matches, operational variance and a plausible smallest effect of interest, but it cannot establish mechanism inertness, a general reduction or a stable positive. Its only favorable disposition is `ADVANCE_TO_STAGE2_DESIGN`; any killer match produces `PARK_STAGE1_NONDOMINANCE` plus the exact block-level observation(s).

### I4. Stage 2 must separate state and selector effects

The 2×2 factorial distinguishes:

- typed W1 state effect at fixed selector;
- candidate W2 selector effect at fixed state representation;
- interaction between W1 and W2;
- comparison against the strongest Stage 1 comparator.

If full candidate does not beat `W1_TYPED × SIMPLE_W2`, no W2 claim is allowed. A future `REDUCES_TO_W1_ONLY` conclusion would require a separate independent, prefrozen negative-inference and precision gate on disjoint evidence; Stage 1 cannot mint that label.

### I5. Latency must subtract mechanical minimum

Raw ratios are unstable for small integer paths. Each unit/phase needs a hidden mechanically verified minimum number of actions/tool calls. Score `EXCESS_STEPS = observed_steps - mechanical_minimum`. Zero excess versus zero excess is a tie and a baseline win. Stage 1 estimates dispersion only; Stage 2 freezes any SESOI on excess steps.

### I6. Positive all-killer language requires all-killer confirmation

Stage 2's strongest-killer arm supports only a component/factorial claim against that predeclared killer. It cannot justify “beats every Stage 1 killer.” That wider wording requires a new disjoint confirmation preregistration that includes version cache, bounded full log and saved workflow again.

### I7. Hidden custody must exclude all model/reviewer transcripts

An external non-LLM scorer/freezer must keep keys, hidden identities, hidden manifests and raw hidden rows outside every LLM, reviewer, chat and tool transcript. Reviewers verify public commitments, dataflow/egress policy and closed receipts only. Output is released only after a global arm-output seal.

## 5. Assumptions requiring review

### A1. Prospective sampling frame exists

Before candidate implementation or unit selection, an independent curator can enumerate an eligible sampling frame of real reversible A/B/A version transitions across at least three families, including provenance and mechanical outcome feasibility.

### A2. Candidate-blind curation is feasible

The curator can select units and create semantic novelty/difficulty strata without access to candidate code, prompts, W1 schema details, pilot direction or arm outcomes.

### A3. Semantic novelty is mechanically auditable

A2 tasks can be shown not to replay A1 answers through semantic task/expected-behavior checks, not merely distinct filenames or digests, while difficulty is matched using pre-outcome descriptors.

### A4. External custody is available

A non-LLM process/service with independent principal, transcript-safe private input handling, frozen egress policy and global-seal semantics can be bound before any stage freeze.

### A5. Stage 2 power is affordable

A design-blind pilot can estimate family-blocked dispersion and support an exact N with enough independent families/clusters for cluster-aware inference. Until this is demonstrated, Stage 2 is not implementation ready.

## 6. Baseline nondominance screen

| Comparator | Cheap explanation | Stage 1 consequence if match/beat |
|---|---|---|
| `VERSION_KEYED_CACHE` | Public version key restores bounded prior state/procedure | `PARK_STAGE1_NONDOMINANCE / OBSERVED_VERSION_KEYED_CACHE_MATCH_IN_<BLOCK> / STOP` |
| `BOUNDED_FULL_LOG` | Reconstruct from released observations under identical reread/resource rights | `PARK_STAGE1_NONDOMINANCE / OBSERVED_BOUNDED_FULL_LOG_MATCH_IN_<BLOCK> / STOP` |
| `SAVED_WORKFLOW` | Static prebuilt procedure explains adaptation | `PARK_STAGE1_NONDOMINANCE / OBSERVED_SAVED_WORKFLOW_MATCH_IN_<BLOCK> / STOP` |
| `W1_ONLY` | Typed state/invalidation explains gain; candidate W2 adds no value in the observed block | `PARK_STAGE1_NONDOMINANCE / OBSERVED_W1_ONLY_MATCH_IN_<BLOCK> / STOP` |

Stage 1 ties are killer wins for the investment stop rule. Multiple matching killers/blocks produce multiple durable observations under the single `PARK_STAGE1_NONDOMINANCE` disposition. These are exact three-block screen observations, not mechanism-reduction proof. A true future `REDUCES_TO_*` label requires independent disjoint evidence and a separately prefrozen negative-inference/precision gate. There is no Stage 1 `MET` label.

## 7. Revised negative map

1. **Information-set confounding:** all arms bind the same observable provenance, release times, static prior/build corpus and reread ceilings.
2. **Free full-log reread:** full log is a bounded representation, not a zero-cost oracle; every reread is charged.
3. **Cache/workflow oracle:** construction cutoff and usable bytes are frozen before prospective unit exposure.
4. **Retrospective unit shopping:** sampling frame and selection occur prospectively under candidate-blind curation.
5. **Digest-only novelty:** A2 needs semantic novelty plus difficulty matching, not only byte inequality.
6. **Pseudoreplication:** tasks/steps/seeds do not increase N; inference clusters by family.
7. **Inference from three units:** `PARK_STAGE1_NONDOMINANCE` and its block observations are durable, but mean only nondominance in the exact three prospectively curated sample blocks. They neither prove a mechanism reduction nor support a general claim. Reopening requires a newly authorized foundational question plus new disjoint evidence; adding architecture vocabulary, post-hoc subgroups/thresholds/families or rerunning the same sample cannot rescue the route.
8. **Small-integer latency ratio:** use mechanically normalized excess steps, not the removed 80% ratio.
9. **One-stage kitchen sink:** Stage 1 kills routes; Stage 2 separately identifies state/selector effects.
10. **Strongest-killer laundering:** one selected killer cannot support an all-killer claim.
11. **Hidden transcript exposure:** no LLM/reviewer/tool transcript may contain keys, identities, hidden manifests or raw hidden truth.
12. **Infrastructure-as-evidence:** bundles, receipts, tests and scorer services are not adaptation results.
13. **Synthetic adaptivity-gap rescue:** no gated cascade, oracle planner or relabeled recurrent-state rerun.
14. **Authority drift:** W1/W2 cannot change readers, retention, decision influence, permissions, evaluator, audit or W5.

## 8. Risks

### R1. Stage 1 underpower

Three family blocks cannot reliably establish a positive effect or a mechanism reduction and may give unstable dispersion. The design handles this by prohibiting `MET`/`REDUCES_TO_*` and using Stage 1 only for exact-block nondominance observations, operational feasibility and Stage 2 planning.

### R2. Candidate-blindness leakage

High-level route knowledge may still influence curator choices. The sampling frame, eligibility rules, novelty/difficulty rubric and selection seed/process must be committed before the curator sees candidate artifacts.

### R3. Representation purity

Typed W1 can smuggle extra information through labels or structured fields; full log can smuggle extra computation through rereads. Bundle-level information accounting and adversarial parity tests are required.

### R4. Strongest-killer selection bias

Choosing a Stage 2 killer from Stage 1 outcomes uses Stage 1 data. The deterministic selection rule and claim ceiling must be preregistered before Stage 1. Stage 2 units are disjoint, and the selected killer is treated as a fixed comparator, not a discovery claim.

### R5. Semantic difficulty mismatch

Even candidate-blind tasks can differ across phases/families. Difficulty descriptors must use public static features and mechanical path minima only; no hidden outcome performance may tune matching.

### R6. External scorer operational failure

A transcript-safe service may still leak through logs, crash dumps, metrics or exception text. Dataflow and egress must be fail-closed, with hidden storage inaccessible to reviewer/tool processes.

### R7. Stage 2 cluster count

Large within-family N cannot compensate for too few families. Exact N must include enough independent family clusters for the selected inference; otherwise the claim remains descriptive inside the sampled families.

### R8. Claim inflation

Even a Stage 2 positive remains limited to prospectively curated, reversible software version-rollback environments. It does not establish arbitrary non-stationarity, Product value or autonomy.

## 9. Open questions

1. What prospective sampling-frame sources yield at least three eligible families without retrospective winner selection?
2. What static descriptors define semantic task class and difficulty before hidden outcomes?
3. What exact observable release schedule and reread budget make full-log and typed-state comparison fair?
4. Does version cache start empty, or is a common static warm prior allowed? If warm, what exact corpus/cutoff is shared?
5. What deterministic rule selects the strongest Stage 1 killer for Stage 2?
6. What externally justified SESOI reflects enough value to pay for typed W1/W2 complexity?
7. How many Stage 2 families/clusters and units are required under cluster-aware inference?
8. What non-LLM scorer/freezer service supplies independent custody without exposing private metadata to review tools?
9. What failure policy applies if a Stage 1 arm or scorer fails operationally before global seal?
10. Will the final claim be factorial/component-specific, or does it require a further all-killer confirmation?

## 10. Revised design decisions

1. Downgrade to `DESIGN_CANDIDATE / PREREG_REVISE / NOT_IMPLEMENTATION_READY`.
2. Use Stage 1 with 3 prospective units, 3 families and exactly 5 arms; never emit `MET`.
3. Stop further route investment if any killer matches/beats or candidate does not beat W1-only; record `PARK_STAGE1_NONDOMINANCE` plus every exact `OBSERVED_<KILLER>_MATCH_IN_<BLOCK>` without claiming mechanism reduction.
4. Admit Stage 2 only with a new disjoint preregistration and units.
5. Use the 2×2 state/selector factorial plus a predeclared strongest Stage 1 killer.
6. Freeze observable information separately from representation and charge all rereads.
7. Freeze static build corpus plus cache/workflow construction cutoff and usable bytes.
8. Replace raw/ratio latency with mechanically normalized excess steps.
9. Let Stage 1 estimate family-blocked dispersion and compare against a predeclared SESOI; freeze Stage 2 N and cluster-aware inference later.
10. Require prospective sampling and candidate-blind semantic novelty/difficulty curation.
11. Require an external non-LLM transcript-safe scorer/freezer with global seal and closed output.
12. Collapse freeze prerequisites into five content-addressed bundles without dropping semantic gates.
