<!-- Design by dedicated agent 2026-07-04; execution founder-gated (real LLM calls + n_raw degradation pilot). -->

# CWM-LEARN-5e — Data-blind knowledge pruning of the interaction hypothesis space (proposer/disposer, first LLM-capability gate)

## 1. Load-bearing question

Does a **data-blind** LLM's world-knowledge pruning of the pairwise-interaction space let the validated invariance verifier recover causal structure in a regime (p ≈ 1,800 basis coordinates ≫ n per env) where exhaustive cross2 enumeration + selection **demonstrably degrades** — i.e., does the proposer add *capability*, not just governance? LEARN-3 proved selection works when the space is small enough to enumerate (21 coords); a MET here proves the pipeline extends to spaces where enumeration fails, **and** (via the incongruence control) that the extension flows through the LLM's prior, not luck or format.

## 2. Task setting

**Semi-synthetic knowledge-proposer** (chosen over statistical proposer): with anonymized features + data summaries, any LLM win is dominated by a deterministic screening rule over the same summaries — a guaranteed near-NULL. World knowledge over *names* is the one channel no screening rule reaches, and it is the founder's stated route. Ground truth stays adjudicable because **labels are ours**: real-world-flavored generic-scientific feature names (physio/mechanical, preregistered schema of 60 names; lives in `experiments/` fixtures, never in core — no business semantics enters the object layer), labels generated from our SCM. No benchmark contamination is possible: the coefficient structure is invented here.

- **Dimensionality:** n_raw = 60 → cross2 = 60 + 1,770 = 1,830 coordinates.
- **True mechanism (condition A, congruent):** 4 interaction pairs a domain-literate reader would nominate from the names (e.g., mass×height⁻²-style pairings) + 2 linear terms; β fixed across envs.
- **Condition B (incongruent control):** identical schema/names, 4 *arbitrary* true pairs. Same LLM proposals re-scored — zero extra calls.
- **Nuisance:** 8 spurious raw channels (and their pairs) with env-flipping coefficient signs (LEARN-2/3 style), plus dense weak inter-feature correlation to worsen dilution. E = 4 train envs × 400 samples; OOD test env (fresh nuisance draw) × 2,000.

**Back-of-envelope degradation:** a null coordinate is sign-stable across 4 envs w.p. 2⁻³ → ~225 chance-stable nulls among 1,830; per-env logistic at p=1,830 ≫ n=400 shrinks true standardized coefficients toward/below the 0.15 floor while the max over ~225 survivors has a fat tail → false negatives (`found=False`) *and* slip-ins. Compute: per-env fits at 1,830 features × 200 epochs × 1,600 pooled rows ≈ 10⁹-scale multiply-adds in pure Python (hours/seed); a k≈30 candidate set is seconds and sits in the LEARN-3-validated p ≪ n regime. **Regime check (pre-freeze, disjoint pilot seeds):** arm (b) must actually degrade (median normalized score ≤ 0.6 or `found=False` in ≥ half of pilot seeds) at n_raw=60; if not, escalate to 100 (5,050 coords) *before* freezing. Calibration before freeze, never after.

**Leakage rules:** the LLM prompt is a **pure function of the preregistered schema** — feature names + generic outcome name + output format. Never: rows, summaries, statistics, env structure, labels, the SCM, seed values. Prompt hash preregistered; audit = recompute hash. One format-repair retry allowed, adding no information.

## 3. Arms (all verified by the *identical* code path)

Pre-expand each arm's candidate columns externally and call `InvariantStructureFilter(basis="raw")` on the expanded rows — **zero changes to the validated component**, and no arm gets a different verifier. Every arm = 60 raw features + its pair set (self-squares rejected by a candidate validator — LEARN-3's red-team trap stays closed).

- **(a) LLM-proposed:** m = 5 independent calls (S1a slot, preregistered temperature), ≤ 20 pairs each; primary aggregation = union capped at 30 by proposal-frequency. Prompt is data-free ⇒ one proposal set serves all seeds (proposal randomness cleanly separated from data randomness). Each of the 5 individual proposals also verified as sensitivity.
- **(b) Exhaustive cross2** (all 1,770 pairs): the cheap baseline that must be beaten or matched-at-lower-cost.
- **(c) Random-k:** 20 draws of |union| random pairs — luck control.
- **(d) Oracle:** the 4 true pairs — measured ceiling per seed.
- **(e) Screening:** top-|union| pairs by min-across-train-env |corr(xᵢxⱼ, y)| — the cheapest *data-using* proposer; the honest question is whether data-free knowledge is worth anything next to it.

## 4. Decision rule

Per seed (S = 10 frozen seeds), normalized score s = (AUC_OOD − 0.5)/(AUC_oracle − 0.5); `found=False` ⇒ s = 0 (reported separately). Structure recall/precision of kept-vs-true pairs reported alongside.

- **MET ("LLM proposer earns its keep"):** (i) median s_a ≥ 0.8; (ii) a > b in ≥ 9/10 seeds (exact binomial p ≈ 0.011, one-sided); (iii) a > median random draw in ≥ 9/10 seeds; (iv) **tiered vs screening:** MET-strong = a > e in ≥ 8/10; MET-weak = |s_a − s_e| ≤ 0.05 (data-free matching data-using is itself the finding — tier reported, never conflated).
- **Congruence check:** in condition B the same proposals must collapse to ~arm (c) level. If arm (a) *also* wins in B, the win is not knowledge → **INVALID** for the knowledge claim.
- **NULL paths:** b ≈ a (enumeration doesn't degrade — regime argument wrong); a ≈ c (prior no better than luck); e ≫ a (screening dominates knowledge — record as lesson, park the knowledge route).
- **INVALID:** prompt-hash mismatch / any data-derived token, post-hoc aggregation change, seed redraws, or the condition-B anomaly.

Author ≠ adjudicator; founder casts final; freeze via `prereg` with builder/reviewer identities per boundary #23.

## 5. Honest scope

A MET claims only: *on knowledge-congruent semi-synthetic structure*, data-free name-based pruning + validated invariance verification beats enumeration at this scale. It does **not** claim real-world validity, general LLM causal discovery, or anything about incongruent domains (condition B measures exactly how badly the prior misleads there — a deliverable, not a footnote). LLM stays proposer-only; the frozen fail-closed model is unchanged; C6/C7/SD4 untouched. Realistic NULLs above are all live: (e)-dominance is genuinely probable and would be a valuable negative.

## 6. Settled results this must not repeat — and how

1. **LEARN-3** (selection over small supplied basis works): excluded by construction — low-dim is out; the object of study is candidate-set *construction* at p ≫ n. 2. **LEARN-4 NULL** (representation discovery from data): no gradient/data-driven rep learning anywhere; the proposer is data-blind and symbolic over fixed raw features. 3. **S1b NULL** (in-distribution self-model adds nothing): increment here is OOD and measured against enumeration/screening/luck, never against nothing. 4. **Self-squares trap:** candidate validator rejects i=j. 5. **LLM-in-control-path:** proposer feeds the deterministic verifier offline; nothing the LLM emits reaches a control path. 6. **Gate-moving:** the only adaptive step (n_raw escalation) is a preregistered pre-freeze pilot on disjoint seeds.