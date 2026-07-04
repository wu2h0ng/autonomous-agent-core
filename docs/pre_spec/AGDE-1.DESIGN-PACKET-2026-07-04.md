<!-- Produced by the #24 paradigm-loop workflow wf_399be9b4-294 (thesis -> Builder A/B + Skeptic C ->
adversarial debate -> packet; 6 agents). Authorizes NO mechanism code; founder casts route selection.
Provenance: B's chassis x C's arena/verdict geometry x A's integrity controls; BC-1..BC-10 incorporated. -->

# ARCHITECTURE DESIGN PACKET — AGDE-1: Active Governed Discovery Engine, Gate 1 + Dynamic-CWM Leg

**Status:** Design packet for founder route-selection cast. Authorizes NO mechanism code (boundary #24). Implementation requires its own prereg-freeze (builder_id ≠ reviewed_by per boundary #23), RR-0029 §5 re-review at freeze, Codex single-writer, author ≠ adjudicator, founder casts final.
**Date:** 2026-07-04. **Layer:** object (autonomous-agent-core), pure stdlib, generic scenarios only.
**Provenance:** merged from Builder A / Builder B / Skeptic C designs per the 2026-07-04 debate record: **B's chassis × C's arena and verdict geometry × A's integrity controls.** All ten binding constraints (BC-1..BC-10) are incorporated below and cross-referenced.
**Verified interfaces** (checked 2026-07-04 in `.worktrees/stage0-gate-sovereignty/src/aac/`): `InvariantStructureFilter.fit(envs: list[tuple[list[list[float]], list[int]]], seed: int = 0)` + `NoInvariantStructure` (invariant_structure.py:35,106,119); `BeliefLedger.record_verified / record_unidentified / demote / mark_conflict`, `VERIFIED_INTERVENTION` provenance, demote-protection for VERIFIED_INTERVENTION entries (belief_ledger.py:34,78,90,102,160,174); `GovernedDecisionGate.decide` (governed_gate.py:42,45).

---

## 1. Claim + Paradigm Thesis (one page)

**Foundational problem lock.** Observation identifies causal structure only up to the Markov-equivalence class: edge orientation, latent confounding, and do()-effect sign are generically underdetermined by any observational objective. This is why every passive route on our stack NULLed (LEARN-4: chance transfer; 5b: delta ~0.003; S1b: no increment at same distribution) — they fought for identifying signal provably absent from fixed observational data. The remaining closure: a governed system must **act to identify** — choose its own interventions under a deterministic, contentless governed rule — without (a) a learned model in the control path, (b) a third autonomy axis (RR-0034 forecloses it), or (c) repeating the passive NULLs.

**Paradigm thesis (locus claim).** Discovery does not live in a learning objective; it lives in the governed action loop: `{proposer → invariance-selection verifier (UNIDENTIFIED first-class) → deterministic intervention chooser → execute do() → belief-ledger transition}`. The load-bearing formal argument is an identifiability-**class** separation (Eberhardt/Hyttinen: interventions identify what no observational objective can), which is a theorem about the data channel — categorically different from the degeneracy engine that closed the autonomy axis, because φ* here is do()-accessible to **both** arms; the only measured variable is intervention-**choice policy**.

**The Gate-1 claim, in its earned form (BC-7 vocabulary, frozen).** The unbounded sentence "discovery lives in the governed loop" is NOT claimable from Gate 1. The MET sentence is the bounded locus + compatibility form:

> *Under governed budget scarcity — the native operating regime of a system where every do() is a costed, gated R0-R3 action — a deterministic, contentless, disposer-compatible intervention chooser inside our governed loop captures ≥50% of the measured oracle-over-random identification gap on families provably unidentified under observation, attributable to choice of data alone (not extraction, not machinery), with C7 intact and the LLM absent.*

Forbidden vocabulary in any verdict text: "autonomy" (RR-0034); "extracts more" (the loop *chose* better, it does not extract more — arm E enforces this mechanically); unbounded locus language before the temporal composition gate and 5e proposer gate land on the same side.

**Null hypothesis (live; a NULL is a deliverable, BC-10).** H0-CHOOSER: active ≤ random at equal budget (Eberhardt: random designs identify asymptotically; adaptive gains are bounded-budget). H0-PASSIVE-TIE: passive selector on the same interventional samples ties the loop (the S1b trap). H0-SCHEDULE: fixed round-robin ties active. The route is non-trivial only if it beats all three at matched sample budget on observation-unidentified families. Frozen prediction guidance: the skeptic's prior is credible; the run is designed so a controls-clean NULL is a publishable fact ("active choice ties random at equal budget; locus claim dies; CWM brain ceiling-bounded at the observational equivalence class pending a different lever"), sharpening the RR-0040 selection-works/discovery-fails boundary.

---

## 2. Prior-Negative Map (why this is not LEARN-4 / 5b / S1b / RR-0034 repetition)

| Prior negative | What died | Why AGDE-1 is a different channel | Guard built into the gate |
|---|---|---|---|
| **LEARN-4** (NULL): IRM/V-REx gradient-penalty representation learning from fixed observational multi-env data; chance transfer; penalty 0-for-3, destroys ERM | Passive penalty **learning** from a **fixed** dataset seeking signal **observation does not contain** | AGDE learns no representation and no penalty (it SELECTS over enumerated bases with the validated fit→select→refit verifier); consumes no fixed dataset (acquires new do()-generated regimes); the orientation signal is manufactured by do(), absent from LEARN-4's channel by construction | Selection-only verifier, reused verbatim; no gradient anywhere |
| **5b** (NULL): naive anchor appending — a few do() samples as one extra equal-weight env; delta ~0.003 | Passive appending of interventional data | AGDE **is** RR-0041's explicitly named "structured do()-exploitation" successor, and therefore carries a strictly sharper null: it must beat random/fixed do() at **equal interventional budget** via the choice mechanism, not merely beat N=0 | Arm D (passive-on-random-samples) is the 5b-form arm; symmetric MET geometry ID(A)−ID(D) ≥ 0.5·gap |
| **S1b** (NULL): self-built learned CWM at same distribution, no increment over statistical baseline | Extra machinery on the same information | AGDE operates where observation is insufficient; interventions change the distribution. On identical data the loop must claim **nothing**: arm E (passive-on-active-samples) is preregistered to **tie** the active arm within the noise band — the machinery-adds-nothing prediction armed in the positive direction | Arm E tie is a MET **requirement**, not an afterthought |
| **RR-0034 terminus**: no separable autonomy axis; degeneracy engine closes Version-B; discovery = organ capability under governance | Constitutive autonomy axis; unpaid-regret framing; SQ-hard secret held by one arm | AGDE makes no behavioral-advantage/unpaid-regret claim; φ* is do()-accessible and **both arms get do()**; the measured quantity is choice policy — a well-posed empirical difference, not a convention. Version-A-permitted organ capability, C7 untouched | Vocabulary ban enforced in the verdict template (BC-7); chooser deterministic/contentless/stateless; LLM absent from Gate 1 |

---

## 3. Architecture

### 3.1 The loop — five stations, four of them existing code (Builder B chassis)

```
PROPOSER (enumeration; S1a LLM slot wired but OFF)
  → VERIFIER (InvariantStructureFilter reused verbatim via thin verify-only adapter)
  → CHOOSER (NEW ~60 lines: deterministic min-max split; propose-only)
  → EXECUTOR (GovernedDecisionGate.decide + hard budget cap; sealed SCM lever env)
  → LEDGER (BeliefLedger verbatim, public API only)
  → loop until |surviving| == 1 or budget exhausted → fail-closed UNIDENTIFIED
```

**(1) PROPOSER** — Gate 1: exhaustive enumeration. `src/aac/hypothesis_pool.py` (NEW, ~80 lines, stdlib itertools) enumerates every DAG in the Markov-equivalence class of a GIVEN skeleton. Each `CausalHypothesis` is a frozen parent-set map `{node -> tuple(parents)}` — exactly a supplied basis per node, the object class the validated selector consumes (LEARN-2 supplied-basis transfer 0.89). The S1a real-LLM slot plugs into the same `CausalHypothesis` form in the later 5e-style p≫n gate only; it is **excluded from Gate 1** so a win cannot be attributed to knowledge priors (BC-9).

**(2) VERIFIER** — `InvariantStructureFilter.fit(envs, seed)` reused **verbatim**; `NoInvariantStructure` is the fail-closed exception. Thin adapter `src/aac/structure_consistency.py` (NEW, ~120 lines, verify-only, fail-closed): each data regime is one environment (env_0 = observational; env_k = samples from the k-th executed do()). Hypothesis h predicts, per node v, that v's mechanism (stdlib least-squares regression of v on h's claimed parents) is INVARIANT across every env not intervening on v and BROKEN where do(v) applies. Survival = predicted invariance/break pattern matches the measured pattern within a **calibration-seed-derived tolerance, frozen** (BC-3). Pool verdicts: IDENTIFIED (unique survivor), UNIDENTIFIED (>1 — first-class, never coerced), EXHAUSTED (0 survivors → fail-closed refutation of the whole pool, no silent fallback). Debate resolution: Builder A's new analytic moment-predictor verifier is **rejected** — the attribution logic requires that the choice rule be the only new mechanism on the verdict path.

**(3) CHOOSER (NEW — the sole paradigm bet)** — `src/aac/intervention_chooser.py` (~60 lines): deterministic greedy min-max split. For each admissible action do(X_i = c) in the preregistered action set, partition the current surviving set S by the invariance-break **signature** each hypothesis entails under that do(); hypotheses are separated iff their entailed signatures differ detectably at N_int (detectability margin calibration-set, frozen). Score(a) = worst-case (max over partition cells) surviving-set size; pick the minimizer; ties broken by lowest node index. Contentless and disposer-compatible: a pure, seed-free, parameter-free, stateless function of (surviving-set signature table, remaining budget) — no learned state, no data values, no semantics, no LLM input. It PROPOSES only. Random / round-robin arms implement the same interface with the rule swapped, guaranteeing verifier-fixed comparison. Note the constitutional point defeating Skeptic C's Reduction 2: the chooser holds zero information beyond the verifier **by design** — the measured claim is a policy increment at equal information, never an information increment.

**(4) EXECUTOR** — every chooser proposal routes through the existing `GovernedDecisionGate.decide` (verify-or-escalate, ADR-0048) with the existing hard budget-cap pattern from `governed_loop.py`: budget exhaustion is a **gate refusal**, not a soft check; the terminal state is UNIDENTIFIED, a legitimate scored outcome. Environment: `envs/intervention_scm.py` (NEW, ~150 lines): seedable linear-Gaussian SCM, `observe(n, seed)` and `intervene(node, value, m, seed) -> rows`, same act→outcome interface shape as the existing lever-world envs so the M4 seam pattern applies unchanged later. Ground truth lives only inside the env; the loop touches it only through samples.

**(5) LEDGER** — `belief_ledger.py` verbatim, zero changes, public API only. Pool creation: `record_unidentified(claim_id=f"edge:{i}->{j}", group=f"scm:{family_seed}")` for every orientation-contested edge (VERIFIED_INTERVENTION demote-protection at belief_ledger.py:102 remains live). Refuted hypotheses trigger `demote()` on edge-claims they uniquely carried; survivor disagreement → `mark_conflict`. Unique survivor + held-out interventional confirmation slice → `record_verified(provenance=VERIFIED_INTERVENTION)` — the ledger's only existing path to fresh FACT. Per the debate (Q2, Reduction 3): the ledger trace is **run-integrity** (dirty trace = INVALID) but the claim sentence may **not** cite the ledger as a capability source — ledger and gate are the COMPATIBILITY half of the claim, not the CAPABILITY half.

### 3.2 NEW code inventory (total; nothing else may be new)

| File | ~Lines | Role |
|---|---|---|
| `src/aac/hypothesis_pool.py` | 80 | MEC enumeration → frozen CausalHypothesis list |
| `src/aac/structure_consistency.py` | 120 | Verify-only adapter: hypothesis ↔ InvariantStructureFilter regime pattern |
| `src/aac/intervention_chooser.py` | 60 | Deterministic min-max split rule + swappable random/round-robin/oracle policies |
| `src/aac/discovery_loop.py` | 150 | Orchestrator wiring stations 1–5 through the gate |
| `envs/intervention_scm.py` | 150 | Seedable linear-Gaussian SCM lever env with do() API |
| `experiments/agde_gate1.py` | — | Runner: arms, controls, seed discipline, artifact emission |
| tests-first suites for each | — | §8 |

**Reused untouched:** `invariant_structure.py`, `belief_ledger.py`, `governed_gate.py`, budget-cap machinery from `governed_loop.py`, audit/observe hooks, S1a LLM slot (dormant), env interface shape. Zero edits to governed_gate/C7/disposer code (BC-9).

---

## 4. FIRST GATE SPEC — AGDE-1 "Choice-vs-Random Under Budget Scarcity"

Preregister + freeze before any scored run; tests-first; pure stdlib; runtime minutes on a laptop.

### 4.1 Environment and arena validity (BC-1)

- Linear-Gaussian SCMs, **n = 5–6 nodes** (debate resolution: n=4 risks too few actions for the scarcity fraction to bind), edge weights and noise scales drawn from frozen ranges per family-seed; skeleton GIVEN (this gate isolates ORIENTATION — the provably observation-unidentified fraction; skeleton recovery is a separate claim).
- Families exhaustively pre-verified **at prereg time** by machine check: (i) MEC size ≥ 4; (ii) **informative-node fraction ≤ 1/3** (Skeptic C's scarcity construction — at most ~1/3 of single-node interventions materially split the MEC; disclosed openly as favorable-to-active: if active loses here it loses everywhere); (iii) observational floor at MEC-chance on calibration seeds; (iv) measured oracle−random gap ≥ preregistered minimum, else **INVALID-BY-CONSTRUCTION** (no thesis verdict either way).
- Budget **B ∈ {1, 2, 3}** single-node hard interventions do(X_i = c), c preregistered; B frozen strictly below the measured B_rand(0.95) on calibration seeds.
- 20–30 scored families (final count frozen at prereg).

### 4.2 Sample accounting (BC-4 — the unit of cost is SAMPLES, not do()-operations)

1. **Equal total samples** across all comparison arms: every intervention arm consumes exactly N_obs + B·N_int. Passive arms D/E receive exactly their donor arm's collected sample set.
2. **Forced full-B spend** for the accuracy metric M1: no arm banks unspent samples by identifying early; early identification is recorded for M2 (interventions-to-identification, censored at B) only.
3. **OBS+ sample-matched observational arm (new, from the debate)**: receives N_obs + B·N_int samples, ALL observational; must remain at MEC-chance. This demonstrates the identifiability-class separation **on-stack** — the win is the interventional channel, not raw sample count.
4. **Confirmation-slice symmetry**: the reserved held-out slice for VERIFIED_INTERVENTION confirmation is carved identically in every arm and excluded from the identification-decision sample count.
5. **N_int is a calibration-set parameter** (neither A's 500 nor C's 40 asserted a priori): chosen so (a) a single informative do() is detectable above tolerance and (b) the oracle−random gap stays above the validity minimum; then frozen. A low-N_int stress sub-arm may be included, preregistered.
6. **Gate-trace budget audit** (A's C4): GovernedDecisionGate trace must show exactly B approved do() proposals per arm; any excess = INVALID run.

### 4.3 Arms (BC-2; identical frozen verifier and thresholds in every arm)

| Arm | Policy | Role |
|---|---|---|
| **A** ACTIVE | min-max split chooser | the claim |
| **R** RANDOM | uniform-random admissible node per step (seeded fresh draws), equal budget | H0-CHOOSER null arm; ceiling-reference |
| **RR** ROUND-ROBIN | deterministic node cycle | kills "any fixed schedule suffices" |
| **D** PASSIVE-on-RANDOM-samples | arm R's interventional dataset handed as batch envs to the identical verifier, one-shot, no loop/chooser/ledger | the 5b-form / H0-PASSIVE-TIE trap: if D ties A, the win was the do() **data** |
| **E** PASSIVE-on-ACTIVE-samples | same passive selector fed arm A's own collected samples | S1b-form equivalence sanity: **expected to TIE A** within the noise band — the loop machinery must add nothing beyond data choice |
| **OBS** floor | N_obs only | must sit at MEC-chance, else family leaks → INVALID |
| **OBS+** sample-matched | N_obs + B·N_int all-observational | proves interventional channel, not sample count |
| **O** ORACLE | ground-truth-informed best-split sequence | measured ceiling; all grading relative to the (O − R) gap |

### 4.4 Controls — all eight binding (BC-5); any failure = INVALID, no thesis verdict

1. **P1/C1 outcome-permute**: do() outcome rows shuffled against intervention labels → every arm collapses to chance band, else the scorer leaks.
2. **P2 label-permute** on the consistency test → survival verdicts collapse to uniform.
3. **P3 budget-zero degenerate** → all arms output UNIDENTIFIED with untouched protected ledger entries.
4. **C2 severed-environment** (Builder A): do() wired to no effect → active arm must fail-closed to UNIDENTIFIED; any identification claim = INVALID.
5. **C3 chooser byte-determinism**: byte-identical action sequence on rerun at identical state (deterministic unit test, prerequisite to any scored run — makes "contentless" mechanically checkable).
6. **C4 budget audit** (§4.2.6).
7. **N2 node-relabel** (Skeptic C): permute node indices → active arm's identification distribution invariant, else the tie-break is secretly content-bearing.
8. **N3 wrong-skeleton fail-closed**: verifier given a perturbed skeleton must emit UNIDENTIFIED/REFUTED, never confident wrong orientations (mirrors `NoInvariantStructure` discipline).

### 4.5 Seeds and calibration split (BC-3)

Calibration seeds (e.g. 0–9) measure: consistency tolerances, detectability margin, N_int, random-arm rate R and oracle rate O (gap G = O − R), seed-noise band, B_rand(0.95), and host the pre-freeze kills (§7). Scored seeds (e.g. 100–129) are disjoint by construction and checked by the runner. Both lists frozen in `prereg.lock` with `spec_file_sha256` + every mechanism-file digest per boundary #23; r-final run gate rejects on any byte drift. **No naked absolute thresholds anywhere** — three past false verdicts came from naked thresholds; every band is measured-then-frozen.

### 4.6 Decision rule (measured-ceiling-relative; frozen before any scored run)

Primary statistic: gap-closure fraction (ID(A) − ID(R)) / (ID(O) − ID(R)). Metrics: M1 = identification accuracy at forced full-B spend; M2 = interventions-to-identification (censored at B).

- **MET** requires ALL of:
  (i) active captures ≥ 50% of the measured oracle−random gap at **both B=1 and B=2**, with sign (A > R) on ≥ 80% of scored seeds, and stochastic dominance on M2 at B=3;
  (ii) **ID(A) − ID(D) ≥ 0.5·gap** (symmetric geometry — Builder A's 50%/80% asymmetry is rejected: it left a window where a 5b-shaped result gets stamped MET);
  (iii) **E ties A** within the calibration noise band (machinery-voodoo falsifier);
  (iv) RR does not tie A;
  (v) OBS at MEC-chance, OBS+ at MEC-chance, all eight controls pass, oracle−random validity precondition holds, ledger-trace audit clean on every IDENTIFIED family.
- **PARTIAL** (preregistered, not post-hoc): (i) holds at B=1 only → recorded as "active earns only in the extreme-scarcity regime"; no paradigm language permitted. Or: A > R with ≥ 25% closure but D also closes ≥ 80% → "interventions help; adaptive choice not established" (5b-with-a-scheduler outcome).
- **NULL**: gap-closure < 0.2 with all validity checks passing. Recorded per BC-10: locus claim dies; chooser demoted to at most a bounded-budget efficiency knob; CWM brain ceiling-bounded at the observational equivalence class pending a different lever; fallback truth "interventions identify" retained iff R beats OBS. Publishable as-is; sharpens RR-0040.
- **UNIDENTIFIED middle band** (0.2–0.5 closure): exactly one follow-up permitted, as a fresh preregistration with a new frozen seed list. Gates do not move (boundary #20).
- **INVALID**: any control failure, arena-validity failure, budget-audit failure, or ledger-trace failure — no thesis verdict in either direction.

Adjudication: builder writes no verdict; independent adjudicator re-runs prereg/result integrity through the machine gate (`paradigm-gate result-adjudication` citing `prereg_lock_run_id`, `prereg_target`, `result_artifact` per boundary #24); founder casts final.

---

## 5. Dynamic-CWM Leg — debate verdict and sequencing (BC-8)

**Verdict from debate: SEQUENCED AND GATED; the leg as originally submitted (supplied windows) is LEARN-2 relabeled and earns zero claim content.** Skeptic C's characterization was accepted by both builders.

- **AGDE-T1 (prerequisite reuse-sanity gate; NO claim content).** Piecewise-stationary VAR-1 SCM; supplied time-window segments-as-environments fed to `InvariantStructureFilter` **unchanged**; must beat the pooled-fit static baseline on prediction-under-temporal-shift (held-out final regime), bands relative to the measured oracle-segmentation ceiling, with a **matched-capacity static baseline mandatory** (LEARN-3 capacity-confound lesson). Written up as reuse, never as a dynamics result. No dynamics claim of any kind may cite AGDE-T1 alone.
- **Tier-1 dynamics claims require AGDE-1 MET first**, then exactly one of two separately preregistered gates (own frozen seed lists):
  - **Unsupplied-changepoint gate**: a deterministic segmentation rule + temporal invariance selection must land within the measured band of the ORACLE-segmented LEARN-2 ceiling while pooled-static sits at the floor. New claim class: regime identification — the system supplies the partition LEARN-2 was handed for free. **PARK on miss** (then the leg is LEARN-2 with windows renamed).
  - **AGDE-T2 interventions-in-time**: the chooser's action set gains a WHEN coordinate (node, segment); active (node, segment) choice vs temporal-random at equal do()-budget under the identical verdict machinery. New claim class: temporal discrimination policy — the composition the thesis promises. Hypothesis class: SSM-style lagged parent-set maps (which lag-1 edges are mechanism-stable across regimes).

---

## 6. RR-0029 §5 Mapping

- **Claim class:** mechanism-level organ-capability identification claim — deterministic intervention-choice-policy increment over random/fixed at equal do()-budget and equal total samples, on orientation-only identification of observation-unidentified families, in the budget-scarcity regime. Explicitly NOT: autonomy (RR-0034 vocabulary ban enforced in the verdict template), product capability, scaling claim, representation-learning claim, general discovery, or a new identifiability theorem.
- **Write channel:** BeliefLedger public API only (`record_unidentified` / `demote` / `mark_conflict` / `record_verified(VERIFIED_INTERVENTION)`). New files only (§3.2). Zero writes to gate, chooser state (stateless), C7, constitution, or config. No weight updates, no self-modification surface.
- **Control/consumption path:** LLM absent from Gate 1 and forever proposer-side (S1a slot, wall-clock capped, later 5e gate only). Chooser deterministic, contentless, stateless, propose-only. Execution authority solely in `GovernedDecisionGate` + hard budget cap. Sealed R0-R3 lever env. No learned model anywhere in the action path. Any OS consumption via founder-approved seam ADR (RR-0032/ADR-0004 pattern), never cross-repo import; the "OS action→outcome loop is an interventional channel" line is a research-direction projection, not an authorized integration.
- **Prior negatives:** mapped in full in §2 (LEARN-4 / 5b / S1b / RR-0034), each with its in-gate guard arm.
- **Cheap baseline:** random arm R (ceiling-reference), round-robin, passive-tie D, observational floors OBS/OBS+, noiseless pilot pre-freeze.
- **C6/C7/SD4 boundary:** untouched; no self-modification surface exists in the design; discovery capability is Version-A organ capability under governance; SD4 remains founder-reserved.
- **Product/process boundary:** object-layer research evidence only. A MET authorizes at most a seam-contract PROPOSAL toward the OS governed action→outcome channel; zero product language, zero R4/R5 implication. Prereg/freeze/adjudication machinery is internal engineering process, never a product feature claim.

---

## 7. Honest Scope + Kill Experiments

**Honest scope.** Even a full MET licenses only: *"A deterministic min-max discrimination rule beats random intervention selection, and beats the same interventional data consumed passively, under budget scarcity (B < B_rand) on edge-orientation identification with a given skeleton, in small linear-Gaussian stdlib SCMs — realized inside the governed loop with C7 intact and the LLM absent."* The win region was constructed favorable (informative-node fraction ≤ 1/3) and is disclosed as such; Eberhardt-line theory guarantees the arms converge at generous budget, and we claim the bounded-budget regime deliberately because budget scarcity is the governed system's native operating point — but a skeptic reading MET as "active beats random in general" is overclaiming. Known-theory honesty: interventions-orient-what-observation-cannot is Eberhardt/Hyttinen; adaptive-design gains at small budget are known optimal-experiment-design territory (Hauser–Bühlmann-line active learning). The genuinely new content is narrow and architectural: a **locus + compatibility** result — first on-stack evidence that governed ACTION, not a learning objective, is where identification capability enters this architecture. Gate 1 shows nothing about: LLM proposer value (OFF; separate 5e p≫n gate), skeleton discovery, latent confounders, soft interventions, nonlinearity, scaling in n, real data (a Sachs-style interventional-replay gate is a separate design), dynamics (§5 gating), or any OS/product capability. Paradigm-language graduation requires at minimum the temporal composition gate and the 5e proposer gate landing on the same side. A NULL is equally load-bearing (BC-10).

**Pre-freeze kills (BC-6; calibration seeds only, all three must pass BEFORE freeze so a scored NULL is a fact about noisy governed choice, not a degenerate arena):**
1. **Noiseless combinatorial pilot** (Builder B; subsumes A's single-step probe): in the zero-noise limit every do() answers its signature question exactly, so active-vs-random identification counts at B=1,2 are computable by pure enumeration — seconds of compute, no sampling. If the min-max chooser cannot beat random even noiselessly (split-degenerate families), the design dies for cents: either fix the family construction (asymmetric split structure) or, if NO small-MEC class exists where choice matters combinatorially, the Gate-1 form of the claim itself is dead — a choice that cannot matter noiselessly can never matter under noise.
2. **Oracle-vs-random budget sweep** (Skeptic C; ~200 lines, needs only env + verifier + oracle/random policies): sweep B=1..5; if the measured oracle−random gap is ~0 at every budget, no realizable chooser can earn anything and the design dies at pilot cost — the small-hypothesis-collapse prediction codified as a machine check.
3. **Observational-floor leak check**: if the verifier extracts above-MEC-chance orientation from observational data alone on these families, the "provably unidentified under observation" premise is false for the concrete construction; redesign before freezing. (Permuted-outcome N1 also runs in this pilot: if scores don't collapse to chance, the scorer leaks and everything downstream is void.)

---

## 8. Implementation Order + Tests-to-Write-First

No mechanism code is authorized by this packet. When implementation is separately authorized (prereg-freeze, builder_id ≠ reviewed_by, RR-0029 §5 re-review at freeze, Codex single-writer on a feature branch), the order is:

**Phase 0 — tests first (all must fail for the right reason before any implementation):**
1. `test_scm_env.py`: seed determinism (same seed → byte-identical rows); do() changes only the intervened node's mechanism; severed-mode fixture for C2.
2. `test_hypothesis_pool.py`: MEC enumeration correctness against hand-computed small cases; frozen-list stability; parent-set-map form matches the supplied-basis contract.
3. `test_structure_consistency.py`: verify-only (raises on any attempt to fit outside supplied envs); fail-closed EXHAUSTED on zero survivors; UNIDENTIFIED never coerced; N3 wrong-skeleton fail-closed; tolerance is injected, never hard-coded.
4. `test_intervention_chooser.py`: C3 byte-determinism at identical state; statelessness (no attribute mutation across calls); contentlessness proxy — N2 node-relabel invariance of the choice distribution; min-max correctness on hand-computed signature tables; tie-break lowest-index.
5. `test_discovery_loop.py`: budget exhaustion terminates UNIDENTIFIED via gate refusal (never a soft check); C4 exactly-B approved proposals in the gate trace; P3 budget-zero leaves protected ledger entries untouched; full ledger trace UNIDENTIFIED → demotions → VERIFIED_INTERVENTION on a scripted identifiable fixture; chooser proposal cannot execute without gate approval (bypass test — would fail if the gate were skipped, per boundary #13).
6. `test_arms.py`: verifier-fixed property (all arms share one frozen verifier object/thresholds); passive arms consume exactly the donor arm's sample set; equal-total-sample accounting assertion.

**Phase 1 — pilot apparatus:** `intervention_scm.py` + `hypothesis_pool.py` + `structure_consistency.py` + oracle/random policies only → run the three pre-freeze kills (§7) on calibration seeds. Any kill fires → back to design, nothing scored, honest record.
**Phase 2 — chooser + loop:** `intervention_chooser.py`, `discovery_loop.py`, arm harness, all eight controls wired.
**Phase 3 — prereg freeze:** spec + seed lists + bands + N_int + B + family list frozen; `prereg.lock` binds spec digest, `spec_file_sha256`, and every mechanism-file digest; `prereg review` with builder_id ≠ reviewed_by; RR-0029 §5 re-review; `paradigm-gate record` for the implementation-cast stage.
**Phase 4 — scored run:** seeds 100–129 once; artifacts emitted; no reruns.
**Phase 5 — adjudication:** independent adjudicator re-runs integrity through the machine gate; verdict from the frozen template (BC-7 vocabulary); founder casts final; NULL/INVALID → negative-result map + paradigm-learning record per boundary #24; MET → seam-contract proposal only.

**Gate 1 exit → next gates (each separately preregistered):** AGDE-T1 reuse-sanity (may run in parallel, zero claim content) → on AGDE-1 MET: unsupplied-changepoint gate or AGDE-T2 (§5), and the 5e p≫n LLM-proposer gate (already designed) for the proposer's own earning region.

---

**Grounding paths:** `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/stage0-gate-sovereignty/src/aac/invariant_structure.py`, `.../src/aac/belief_ledger.py`, `.../src/aac/governed_gate.py`, `.../src/aac/governed_loop.py`.
**This packet goes to the founder for the route-selection cast. It authorizes no mechanism code.**