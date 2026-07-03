# ADR-0039: Viability/Empowerment Formalization of C1

- Status: **Proposed** — research/candidate; founder-reserved decision, agent-recommended (per ADR-0003 founder tier). **NOT accepted.** No code, gate, parameter, test, or current-state semantics changed by this document.
- Date: 2026-06-24
- Deciders: founder (founder-reserved). Claude recommends only and does not self-cast. Derived from parent `../docs/research/ADR-DRAFT-viability-empowerment-c1-formalization-2026-06-23.md` and `../docs/research/RR-0026-minimal-autonomy-theoretical-path.md` (adversarially audited; all 8 verification claims returned `holds=false` as originally stated — this ADR adopts the corrections, not the rejected results).
- Predecessors: ADR-0028 (survival = shadow of reframe-speed), ADR-0033 (external-only modification), ADR-0037 (SD0–SD4; open Q2 SD4-separability), parent `../docs/research/RR-0019-channel-decomposition-principle.md` (B/R/K channels, `pressure→R` coupling), parent `../docs/research/RR-0026-...`, and the FROZEN parent G-Eco records (untouched).

## Context

C1 (viability) is named as a core commitment but is currently a *posture*, not a *formal object*. RR-0019 gives a `pressure→R` valence coupling; ADR-0028 already recorded that re-metrics (survival, risk) collapse into monotone functions of recovery-after-perturbation. There is no single, falsifiable, non-probabilistic-at-commit statement of *what viability is*, *what the world model optimizes*, and *how the two are budgeted under finite resources*.

This ADR proposes one candidate formalization **and** a preregistered could-fail experiment. It is written to pre-empt the RR-0026 audit verdicts (C1–C3 `holds=false`), not to assert the convergence those verdicts reject. Binding premises carried from the audit, treated here as **not open**:

1. **No "5-discipline convergence" is invoked as evidence** (verdict C4): the cross-discipline corroboration is a pre-committed engineering synthesis with shared cybernetic/Markov lineage; independent inputs collapse to ~2.
2. **Empowerment must not be the maximized control objective** (verdict C3): an unconstrained empowerment maximizer disables off-switches by construction.
3. **"Deterministic disposer at non-toy scale" is unproven** (verdict C2): the determinism / sovereignty / scale trilemma is real; only tractable implementations of empowerment-argmax / viability-kernel / MPC are learned approximators.
4. **SD4-separability (ADR-0037 Q2) is OPEN and reserved to G-Eco** (verdict C1; G-Eco FROZEN): not decided here.

## Options Considered

- **Option A — adopt the formalization now, without experiment.** Rejected: asserts exactly the results the audit graded `holds=false`.
- **Option B — adopt conditionally on a preregistered cheap experiment (proposed).** Scope the formal object to a low-dimensional conservative macrostate `z = π(x)` (`dim(Z) ≤ 6`); demote empowerment to a constrained, organ-proposed maximand; keep corrigibility as an external lexicographic barrier outside the objective. Cost: the experiment may return negatives that drop or demote the formalization — which is the point. Strongest counter-argument (recorded): the trilemma may permit only *gate-and-narrowed-set determinism*, never purity; if the abstraction `π` is ungrounded or the feasible set collapses, the disposer is bookkeeping over an organ-collapsed choice and the thesis is refuted for this formalization.
- **Option C — keep C1 as a posture, drop the formalization.** The viable null; the experiment's N1/N2 negatives route here.

C1–C7 compatibility: the proposal is constructed to keep C6 (organ ≠ subject) and C7 (corrigibility) intact by construction (see Consequences). It does not touch C1's status as a commitment; it proposes a *formal reading* of it, under test.

## Decision (proposed; preregistered gate)

**Proposed (NOT accepted):** adopt a single constrained formalization, conditional on the preregistered experiment passing its frozen thresholds.

**Formal object (one constrained problem, not three):** maximize empowerment `E(z)` (organ-proposed, interventional capacity over `z`) **subject to** `z ∈ Viab(K)` ∧ `B(t) > 0` (deterministic-disposer-enforced), with the world-model/prediction term as the budget currency. Valence `v(z) = -∇ d_K(z)` is the existing `pressure→R` coupling re-expressed over `z` (not new machinery). Corrigibility `Σ_corr` is a **lexicographically dominant barrier evaluated before** the viability check.

**Four pinned rules** (each pre-empts a named verdict objection):
- **R-A:** empowerment is the maximand evaluated by a *belief-channel organ*; it is never the disposer criterion and never enters the same expression as corrigibility (pins verdict C3).
- **R-B:** the object is defined over `z = π(x)`, `dim(Z) ≤ 6`; the disposer commits via deterministic argmax/feasibility over a *narrowed feasible set*; scale beyond `Z` is preregistered as an expected break and recorded as a negative result (pins verdict C2).
- **R-C:** `Viab(K)`, `v(z)`, `B(t)`, and the corrigibility barrier are deterministic at commit; the only probabilistic component is the upstream organ, whose output is a *proposal* (pins C2(i); no softmax/Boltzmann commit).
- **R-D:** corrigibility stays in the external C7 shell and as a lexicographic barrier over `Σ_corr`; it shrinks K and never enters `E`. This ADR makes **no** claim that corrigibility "lives in K" (pins verdict C3 misattribution by agreeing with it).

**Preregistered gate (metrics/baselines/seeds/thresholds FROZEN before any run; never edited to pass — AGENTS.md §2.5):**
- **S1 (cheap, decisive-first):** tabular/low-dim MDP, `dim(Z) ≤ 6`, explicit death region; arms **VEB** (proposal), **B1** viability-only greedy, **B2** budget-governor-only, **B3** empowerment-as-disposer (forbidden config, adversarial control), **B4** softmax/Boltzmann commit (adversarial control). 30 fresh seeds in **900–929** (disjoint from any G-Eco run). Metrics **M1** survival, **M2** regret vs offline oracle, **M3** off-switch integrity, **M4** budget honesty, **M5** commit-determinism (bit-identical reruns). PASS-S1 requires VEB to beat B1/B2 on regret by a frozen margin, `M3 = 1.0`, `M5` holds, B3 shows off-switch erosion, and VEB ≤ B4 on regret.
- **S2 (conditional on S1 PASS):** sweep `dim(Z)` and `|A|` upward; **M6** kernel wall-clock/memory, **M7** non-trivial deterministic feasible set (sovereignty-vs-bookkeeping), **M8** whether the VEB advantage survives. PASS-S2 (strong, not expected) vs **PARTIAL-S2** (the defensible outcome: advantage only over organ-narrowed sets — adopt only under the hedged *"determinism of the gate and of selection over a narrowed set,"* never purity).
- **Pre-declared negatives (kills/honest negatives):** N1 empowerment decorative (drop it), N2 budget is just a governor (demote it), N3 forbidden config does not erode the off-switch (don't over-claim R-A), N4 deterministic commit underperforms the stochastic control (kill-relevant for the deterministic-disposer thesis), N5 feasible set collapses to 1 (sovereignty is bookkeeping — *refuted for this formalization*), N6 no sound low-dim corrigibility-complete `π` exists (ungrounded — not adoptable). **A clean N5 or N6 ⇒ recommend-against.** Full preregistration detail: parent `../docs/research/ADR-DRAFT-viability-empowerment-c1-formalization-2026-06-23.md` §3.

## Consequences

- **No LLM / no probabilistic inference in the control/decision path:** the only probabilistic component is the upstream empowerment/world-model organ (a proposal); commit is deterministic argmax over a feasible set (no softmax — B4 is an adversarial baseline only). **C6:** the organ is confined to the belief/proposal channel, ablatable (arm B1) and auditable. **C7 unmoved:** external pause/rollback/tighten stay on the operator shell outside the agent's edit scope; corrigibility is a lexicographic barrier + external shell, shrinks K, is not in-K and not in the objective. **ADR-0033:** no L4/L5 runtime self-modification — `π`, `Viab(K)`, and any reward target `r` are pinned to the external K spec and discovered/certified offline; `r` is never a learned proxy. **FROZEN Route C / G-Eco untouched:** disjoint seeds, independent thresholds, no separability claim routed through G-Eco; ADR-0037 Q2 remains open. No falsified ideas reintroduced (empowerment constrained; no FEP-as-law; no softmax-in-control; no AIXI/Gödel-machine-as-runtime; no IIT/Orch-OR/homunculus).
- **Founder-reserved (NOT cast here):** whether to fund S1/S2 and its ordering vs the §5.1-class corrigibility-vs-empowerment tabular test (the audit's single cheapest decisive program-level test); whether a PARTIAL-S2 (hedged-determinism) outcome qualifies as the *formal* meaning of C1; whether any S1/S2 result may inform ADR-0037 Q2 framing given G-Eco's frozen status.
- **PROJECT_PLAN:** no task card changed. If the founder funds the experiment, a new card is added at that time. This ADR is a Proposed research record only; the repo's engineering verdict (P7.x / ADR-0036·G13 NOT MET) is unchanged.
