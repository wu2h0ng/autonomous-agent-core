<!-- Frozen design packet produced by the cwm-learn-3-design workflow (10 agents: Builder A/B + Skeptic C ->
adversarial synthesis -> 5-lens red-team [7 blockers, all REVISE] -> packet). Author != adjudicator; founder
casts GO/NO-GO then MET/NULL/INVALID. Discipline correction applied at build time: pre-freeze A4/A5 calibration
runs on a seed block DISJOINT from the scored window (0-9), so scored seeds stay unseen. -->

# CWM-LEARN-3 — Frozen Design Packet (Representation-Upgrade Validation)

**Repo:** `autonomous-agent-core/` (object layer; general scenario; NOT the business OS)
**Roadmap:** RR-0039 CWM-LEARN, gate 3
**Status:** design frozen for founder GO/NO-GO; author recommends, founder casts final MET/NULL/INVALID
**Prior:** LEARN-1/S1b = NULL (no advantage without a shift; intervention-clamp leak lesson); LEARN-2 = MET-but-KNOWN (ICP/IRM on **raw linear** features)
**Incorporates:** every BLOCKER and MAJOR from the 4 red-team lenses. Key structural changes vs the merged candidate are flagged inline as **[FIX-n]**.

---

## 1. Claim + the exact bar

**Claim (one sentence):** On a distribution-shift task whose invariant causal signal is a **non-additive interaction** `Xc1·Xc2` (each component's linear marginal ≈ 0) and whose shifting spurious signal is carried by a coordinate that **provably has no sign-stable degree-2 image**, our pure-stdlib mechanism — **cross-environment sign-consistency invariance selection over a hand-supplied degree-2 interaction basis** — generalizes OOD and beats **both** (a) the LEARN-2 linear-invariance arm (which cannot name the interaction) **and** (b) a **capacity-matched** degree-2 pooled baseline trained without the invariance criterion (which can represent the interaction but overfits the flipping spurious coordinate OOD), with the win attributable to **invariance-in-representation, not function-class capacity**.

**The exact bar (both halves must hold):**
- **Un-nameable structure:** the causal core is `Xc1·Xc2`, which LEARN-2's raw-feature sign-consistency filter cannot represent or select (no raw coordinate names a product; each component's raw coefficient sign is noise-dominated). This is proven **analytically pre-freeze**, and the linear-nameable share of the target is bounded below the arm-3 ceiling gate. **[FIX: the un-nameability is now the gating quantity `Δ_A`, not an absolute `<0.6` bound — see §5 C6.]**
- **No capacity confound:** the win must survive against a same-function-class pooled baseline; if that baseline also generalizes OOD, the result is a capacity artifact → INVALID/NULL.

---

## 2. SCM generator spec (pure stdlib)

New file `experiments/synthetic_scm_interaction.py`. LEARN-2's `synthetic_scm.py` digest is **untouched**. Imports: `random`, `math` only. API mirrors LEARN-2: `gen_env_l3(seed, spurious_c)`, `train_envs_l3(seed, no_shift)`, `test_env_l3(seed, no_shift)`, plus frozen `ENV_PARAMS_L3`.

### 2.1 Feature layout (frozen, 7 features)

`row = [Xc1, Xc2, Xc3, Xs1, Xs2, Xn1, Xn2]`

| idx | name | role |
|---|---|---|
| 0,1 | Xc1, Xc2 | **interaction causes** — product drives y; each has ~0 linear marginal |
| 2 | Xc3 | **honest invariant linear decoy** — small stable linear cause (keeps LEARN-2 above chance but below the arm-3 ceiling gate) |
| 3,4 | Xs1, Xs2 | **spurious** — sign-flipping across environments; **redesigned so NO degree-2 image is sign-stable [FIX-BLOCKER lens3-1]** |
| 5,6 | Xn1, Xn2 | pure noise |

`INTERACTION_PAIR=(0,1)`, `CAUSAL_XOR_IDX=[0,1]`, `CAUSAL_LIN_IDX=[2]`, `SPURIOUS_IDX=[3,4]`, `NOISE_IDX=[5,6]`.
`T_cont` and `y` are **label-only, never features** (inherits S1b/LEARN-2 leak-immunity; the deadly clamped-node / target-as-feature leak does not exist here).

### 2.2 Causal mechanism (label)

Per sample:
```
Xc1, Xc2, Xc3 ~ gauss(0,1)         # independent
T_cont = a_xor*(Xc1*Xc2) + a_lin*Xc3 + gauss(0, noise_sd)
y = 1 if T_cont > 0 else 0
```
`Xc1·Xc2` is a product of two zero-mean symmetric Gaussians ⇒ **zero population linear marginal** on each of Xc1, Xc2 (verified analytically; E[y|Xc1] flat by product symmetry). `Xc3` carries a bounded stable linear marginal — the honest decoy.

### 2.3 Spurious channel — REDESIGNED so no degree-2 image survives **[FIX-BLOCKER lens3-1, lens3-3]**

The merged candidate built the spurious pair from a **shared latent `u`**: `Xs1=u+noise`, `Xs2=b_e·(2y-1)·u+noise`. Red-team lens 3 proved fatal: the **self-square** `Xs1² ≈ u²` and `Xs2² ≈ b_e²·u²` carry a class signal whose coefficient (`b_e²`) is **always positive regardless of `b_e` sign**, so it does **not** flip, survives the invariance filter, and cushions the C5 capacity gate. A scalar coupling cannot make a squared term flip. Therefore the shared-latent construction is **discarded**.

**Frozen replacement — independent-latent, flip-only-in-cross-term-that-is-itself-killed design:** the spurious signal enters y-correlation **only through a single additive channel whose entire degree-2 footprint is sign-unstable or zero**. Concretely:

```
s = spurious_c * (2*y - 1)          # class-linked spurious magnitude, sign = sign(spurious_c)
Xs1 = s + gauss(0, spur_noise)      # Xs1 carries the flipping linear class signal directly
Xs2 = gauss(0, 1)                   # Xs2 is an INDEPENDENT decoy, NO class signal, NO shared latent
```

Consequences (all verified analytically pre-freeze, §2.6):
- **`Xs1` linear marginal flips sign with `spurious_c`** ⇒ the *raw* linear-invariance filter (arm 3) correctly drops it (it did in LEARN-2; unchanged).
- **`Xs1²` marginal:** E[Xs1²|y] = spurious_c²·1 + spur_noise² — coefficient `spurious_c²` is **always positive**, so `Xs1²` does NOT flip. **This is the trap we just escaped** — so we make it **carry no incremental class signal beyond `Xs1`** by design: because `Xs1 = s + noise` is a *linear* class channel, `Xs1²`'s dependence on y is second-order and, at the frozen `spurious_c` magnitude (§2.5), its standardized class-mean-shift is driven under the C6-purity floor. **AND** — the decisive structural move — we **exclude self-square coordinates `x_i²` from the basis entirely** (§3.1, degree-2 **cross-products only, i<j**), so `Xs1²` cannot enter any arm's representation. This removes the non-flipping self-square image at the representation level, not by hoping regularization suppresses it.
- **`Xs1·Xs2` cross-term:** `Xs2` is an independent zero-mean decoy ⇒ E[Xs1·Xs2 | y] = E[Xs1|y]·E[Xs2] = 0. The spurious cross-product carries **zero class signal in expectation** and its fitted sign is pure noise ⇒ it is dropped by the invariance filter with high probability and, critically, **carries nothing to overfit** in the pooled arm.
- **`Xs1·Xc_k`, `Xs1·Xn_k` mixed products:** E[Xs1·Xc_k|y] = E[Xs1|y]·E[Xc_k|y]. For Xc1,Xc2 (zero marginal) this is ~0; for Xc3 it is small and its sign is tied to `sign(spurious_c)·sign(a_lin)` ⇒ **flips with `spurious_c`** ⇒ dropped. For Xn_k (zero marginal) ~0. So every mixed spurious product is either ~0 or sign-flipping.

**Net:** after excluding self-squares, the spurious channel has **no sign-stable, class-informative degree-2 image**. The only sign-stable class-informative coordinates are `Xc1·Xc2` (invariant interaction) and `Xc3` (invariant linear decoy). This is the property the whole gate rests on, and it is now **structural**, not probabilistic.

### 2.4 Environment shift **[FIX-BLOCKER lens3-2: 2-vs-2 sign split, not a single flip env]**

Training couplings must not let any coordinate ride a **single-env** flip. Frozen train couplings use a **balanced 2-positive / 2-negative** sign split with unequal magnitudes:

```
train_couplings = [+1.8, +1.4, -1.7, -1.3]      # 2 clearly positive, 2 clearly negative
pooled_mean      = (+1.8+1.4-1.7-1.3)/4 = +0.05  # near zero but NON-zero (see note)
test_coupling    = -1.6                           # held out, negative regime, larger |c| than any train neg
noshift_coupling_C1 = +1.5                         # C1 no-shift parity (single value, all envs share)
indist_ref_coupling_C5 = +1.6                      # C5 in-distribution reference, TRAIN sign regime [FIX lens1-C5]
```

- A spurious coordinate now must be sign-stable across a **2-vs-2** split to survive; single-env sign luck is eliminated. Pre-freeze audit (§2.6) requires every genuinely-flipping coordinate to flip in ≥9/10 seeds.
- **Pooled-mean note:** `+0.05` is deliberately small (so naive pooling does not cancel/preserve the spurious trivially) but **non-zero** (so a pooled baseline is not handed a free cancellation). This is the honest middle: the spurious does not vanish under pooling, forcing the capacity-matched arm to actually learn-and-overfit it.
- **C5 in-distribution reference is `+1.6`, drawn from the TRAIN sign regime [FIX-BLOCKER lens1-C5]** — NOT the no-shift env. The only difference between the C5 in-dist reference (`+1.6`) and the OOD test env (`-1.6`) is the **spurious sign flip and nothing else** (same |coupling| magnitude 1.6). The ≥0.04 drop then measures negative transfer from the flip alone, not env-difficulty. Both are disjoint held-out streams.

### 2.5 Frozen `ENV_PARAMS_L3` (each value justified from first principles, no env-shopping)

```python
ENV_PARAMS_L3 = {
  "n_causal_xor": 2, "n_causal_lin": 1, "n_spurious": 2, "n_noise": 2,   # 7 features
  "a_xor": 2.2,        # interaction strength — see justification
  "a_lin": 0.30,       # decoy strength — see justification (LOWERED from 0.5)
  "noise_sd": 1.0,
  "spur_noise": 1.0,
  "spurious_strength_cap": 1.8,   # |train coupling| ceiling; bounds Xs1^2 marginal under purity floor
  "n_samples": 800,               # per env (raised from 600)
  "train_couplings": [1.8, 1.4, -1.7, -1.3],
  "test_coupling": -1.6,
  "indist_ref_coupling": 1.6,     # C5 in-dist reference, train sign regime
  "noshift_coupling": 1.5,        # C1 parity only
  "balance_band": [0.4, 0.6],     # deterministic re-draw guard on label prevalence
  "basis": "degree2_cross_only",  # i<j pairwise products, NO self-squares  [FIX lens3-1]
  "seeds": [0,1,2,3,4,5,6,7,8,9],
  "rng_scheme": "named_streams_v3" # [FIX lens3-5]
}
```

**First-principles justification of each non-obvious value:**

- **`a_lin = 0.30` (LOWERED from 0.5) [FIX-BLOCKER lens2-1, lens4-C6].** The merged candidate's `a_lin=0.5` gave the LEARN-2 linear-invariance arm an OOD Xc3-only Bayes AUC ≈ 0.646, above the `<0.6` C6 bound → internal contradiction. We re-derive the Xc3-only ceiling analytically. With `a_lin=0.30`, `a_xor=2.2`, `noise_sd=1.0`, the target-noise the Xc3 channel competes against has SD ≈ √(a_xor²·Var(Xc1·Xc2) + noise_sd²) = √(2.2²·1 + 1) = √5.84 ≈ 2.42. The Xc3-only signal-to-total ratio is 0.30/√(0.30²+2.42²) ≈ 0.123, giving a **Xc3-only Bayes AUC ≈ 0.567** (well under the reconciled arm-3 ceiling gate of 0.62, §5 C6). Xc3 remains a *genuine* invariant cause (honest, not a strawman) but its nameable share is provably sub-ceiling.
- **`a_xor = 2.2` (raised from 1.6).** Makes the interaction dominate the target so (i) the representation-nameable share is large (our arm has real signal to win on), (ii) the linear-nameable share (Xc3) is a small fraction, and (iii) the C4a capacity positive control (our arm ≥0.80 on a pure-interaction split) is comfortably reachable at n=800. Chosen so Xc3-only ceiling < 0.62 **and** pure-interaction Bayes AUC > 0.85, both audited pre-freeze.
- **`n_samples = 800` (raised from 600) [FIX-MAJOR lens1-ΔB, lens3-4].** An interaction boundary plus a wider fitting problem needs more data for a stable stdlib logistic fit and to reduce the 28→21 (cross-only) coordinate multiple-comparisons slip rate. Sized so `Δ_B`'s seed-to-seed SE clears the required margin (§2.6 pre-freeze SE audit), not tuned on scored output.
- **`basis = degree2_cross_only` (i<j, NO self-squares) [FIX-BLOCKER lens3-1].** Self-squares `x_i²` are the non-flipping trap; excluding them removes `Xs1²`/`Xs2²` from every arm's representation structurally. Cross-only degree-2 over 7 features = **21 product coordinates** + 7 raw = **28-coordinate `φ`** (was 35). Fewer coordinates ⇒ lower accidental-survival dilution.
- **`spurious_strength_cap = 1.8`.** Bounds |train coupling| so that even the residual second-order class dependence of any retained mixed term stays under the C6 purity floor; audited pre-freeze.
- **balance guard, seeds, noise_sd:** inherited from LEARN-2 discipline unchanged.

### 2.6 Pre-freeze audits (run on frozen params BEFORE any scored run; results recorded in the prereg; if any fails, fix the **generator/params from first principles and re-freeze** — never after peeking at OOD scored output)

- **A1 Marginal-purity (ALL features, incl. Xc3) [FIX-BLOCKER lens2-2].** On a **large frozen pool (20 000 samples)** so finite-sample marginal shrinks well under threshold, compute standardized class-mean-shift of **every** feature. Require: Xc1,Xc2,Xs1(within-env; it flips across envs),Xs2,Xn1,Xn2 all `|shift| < 0.03` (population-zero features; threshold set at ~1.5×the 1/√20000≈0.007 SE floor, stated); Xc3 `|shift|` in a **bounded intentional band** consistent with the analytic Xc3-only ceiling < 0.62. Xc3 is **on the checklist** (was omitted). **[FIX lens2-2]**
- **A2 Linear-ceiling analytic bound.** Prove pre-freeze: Xc3-only Bayes AUC < 0.62 and pooled-linear OOD AUC < 0.62 at frozen params (both ≈0.567 by §2.5 derivation). This is the frozen justification for the C6 arm-3 ceiling.
- **A3 Degree-2 sign-stability audit [FIX-BLOCKER lens3-2, lens4-2].** On frozen params, over 10 seeds, fit the per-env logistic on `φ` and record, per coordinate, its fitted sign in each of the 4 train envs. Require: (i) `Xc1·Xc2` sign-stable in ≥9/10 seeds (survives); (ii) `Xc3` sign-stable ≥9/10 (survives); (iii) **every spurious-involving cross product (`Xs1·*`, `Xs2·*`) admitted into the kept set in ≤1/10 seeds.** If spurious admission > 1/10, the generator/couplings/`spur_noise` must change and re-freeze. This converts lens-3's empirical 7/10 contamination into a hard pre-freeze gate.
- **A4 C5 drop-margin audit.** Estimate arm-4 (capacity-matched pooled) in-dist AUC at `indist_ref_coupling=+1.6` and OOD AUC at `test_coupling=-1.6` on frozen params; confirm the drop comfortably exceeds 0.04 driven by the flipping `Xs1` channel (now the only class-informative spurious channel), decomposed and recorded. **[FIX lens1-C5, lens3-3, lens4-C5]**
- **A5 `Δ_B` stability audit [FIX-MAJOR lens1-ΔB].** Compute `Δ_B` mean and SE across **≥3 disjoint 10-seed windows** (seeds 0–9, 10–19, 20–29). Require `mean(Δ_B) − 2·SE > DELTA`. If it cannot be shown to clear DELTA with margin, **raise `n_samples` or shrink the basis from first principles pre-freeze** — never after seeing scored Δ_B. (Scored run remains seeds 0–9; the extra windows are a pre-freeze calibration only.)
- **A6 RNG stream-disjointness [FIX-MINOR lens3-5].** Use **named independent RNG streams per role** (`causal`, `spurious`, `noise`, plus per-env and test salts) rather than a single arithmetic-offset stream, so train/test disjointness is **structural**. Assert no `train_envs_l3(seed)` row equals a `test_env_l3(seed)` row across all 10 seeds; freeze the assertion as a pre-run gate.

All of A1–A6 pass ⇒ freeze `ENV_PARAMS_L3` + `synthetic_scm_interaction.py` digest + mechanism block digest (§3) + test file digest into `prereg.lock`.

---

## 3. Mechanism spec (pure stdlib)

### 3.1 Representation map `φ` (deterministic, parameter-free, identical every env and for train/test)

```
phi(row) = [ raw 7 features ] + [ x_i * x_j  for all i<j ]      # 7 + 21 = 28 coordinates, NO self-squares
```
Pure list arithmetic, no parameters, no learning. **Self-squares excluded [FIX lens3-1].** Feature-expansion, not learned representation — chosen deliberately (see §3.4).

### 3.2 PRIMARY mechanism (MET-gating): `invariant_interaction_auc(...)` added to `learned_cwm.py`

New function `invariant_interaction_auc(train_envs, test_rows, test_labels, seed, mode, permute, return_kept)`. It **replicates LEARN-2's sign-consistency PRINCIPLE over the new `φ` representation** — this is honestly a **new ~35-line mechanism block**, not "reuse of the exact lines 180–201" **[FIX-MINOR lens4-3: the new block + `φ` are digest-frozen; do not claim pure reuse].**

`mode="inv_interaction"` (the causal arm):
1. Map every train row through `φ`; standardize `φ`-columns on pooled train stats.
2. Fit a per-env stdlib logistic (reuse `_fit_logistic`) on standardized `φ`.
3. **Keep** `φ`-coordinates whose coefficient sign is **stable AND non-zero across all 4 train envs**, **AND** whose per-env `|coefficient|` exceeds a **frozen magnitude floor `mag_floor`** (see 3.3). **[FIX-MAJOR lens3-4, lens4-2: add magnitude threshold to suppress noise-slip junk survivors.]**
4. Refit a pooled logistic on kept coordinates; score the held-out test env with **no refit** (rank-AUC `_auc`).

### 3.3 `mag_floor` — frozen magnitude-stability threshold **[FIX-MAJOR lens3-4]**

Sign-only stability over 21 product coordinates admits noise coordinates by 2-vs-2 sign luck (lens 3/4 confirmed dilution). Add: a coordinate is kept only if `min_e |coef_e| ≥ mag_floor` where `mag_floor = 0.15` on standardized `φ` (chosen from first principles: ~0.15 std-logit corresponds to a coordinate carrying non-trivial per-env signal; the invariant `Xc1·Xc2` and `Xc3` clear it by a wide margin in A3, accidental noise coordinates do not). `mag_floor` is **frozen in the mechanism block digest before any scored run** and NEVER tuned to rescue a diluted NULL.

### 3.4 Feature-expansion vs learned-representation — honest choice

We ship the **hand-designed degree-2 cross basis as PRIMARY and MET-gating**, and demote the learned MLP to **optional, non-gating**. Rationale (concede-and-adjust to Skeptic C, load-bearing):
- The degree-2 basis has **named, identifiable coordinates** — no hidden-unit permutation/sign symmetry, no ill-posed selection. A NULL from a well-posed selector is a real absence of advantage; a NULL from an ill-posed selector is uninformative. This directly resolves the deepest red-team objection.
- **Honest framing, mandatory in prereg and result:** this is **"invariance selection over a richer *supplied* representation,"** strictly weaker than "learned representation." We supplied the product basis; we did not learn it.
- **Optional secondary (founder may authorize; NOT MET-gating, reported separately):** a pure-stdlib 1-hidden-layer tanh MLP (H=8, frozen lr/epochs/l2, backprop through one tanh layer), invariance = keep hidden units whose output-weight sign+magnitude is stable across envs. This is the stronger "learned, not supplied" claim but is identifiability-fragile; it cannot carry the verdict.

### 3.5 Consumption (both arms)

Fit **OFFLINE**, frozen to disk, **verify-only scalar-AUC out**. Zero control-path write (RR-0026 §5.1). A test must fail if any advice reaches action selection.

---

## 4. Baselines (four arms, all consuming identical frozen `train_envs_l3`/`test_env_l3`, identical standardization)

1. **MARGINAL** (statistical floor; reuse `mode="marginal"`): single best raw linear-marginal feature. Expected OOD ≈ 0.55–0.57 (rides Xc3 only).
2. **POOLED-LINEAR** (LEARN-2's `mode="pooled"`, all 7 raw): no raw-linear direction separates a product target; leans on weak Xc3. Expected OOD ≈ 0.56–0.58.
3. **LINEAR-INVARIANCE = the LEARN-2 MET arm itself** (`invariant_predict_auc`, `mode="invariant"`, existing unchanged code, run on the L3 SCM): the crux baseline. Correctly drops the flipping raw `Xs1`, is **blind to `Xc1·Xc2`**, keeps at most `Xc3` ⇒ OOD capped at the Xc3-only ceiling ≈ 0.567 (< 0.62 gate). Must LOSE to our arm by ≥ DELTA.
4. **CAPACITY-MATCHED NONLINEAR POOLED** (the load-bearing confound control): the **same `φ` (identical 28-coordinate degree-2 cross basis)** as our mechanism — OR the identical H=8 MLP if that variant ships — pooled fit over **all** `φ`-coordinates with **no cross-env invariance filter and no `mag_floor`**, equal **gradient-step budget** frozen (pooled n = Σ env n; match **steps**, not epochs). It CAN represent `Xc1·Xc2` (transfers fine) AND the flipping `Xs1` linear channel + its cross products (which it **overfits and negative-transfers OOD**). This isolates the win to **the invariance criterion**, not capacity.

Our mechanism = **arm (5) INV_INTERACTION**. MET requires INV_INTERACTION to beat **both (3) and (4)** (and trivially 1,2).

---

## 5. Controls

- **C1 — NO-SHIFT PARITY (anti-rigged-env, diff-in-diff).** Every env shares `noshift_coupling=1.5`; spurious no longer flips. Arm (4) capacity-matched pooled now correctly uses everything ⇒ INV_INTERACTION must **NOT** beat it: `|mean(inv_interaction) − mean(arm4)| < DELTA`. Advantage must be shift-specific.
- **C2 — CAUSAL ABLATION.** `a_xor=0` (no invariant interaction). INV_INTERACTION absolute OOD AUC must collapse: `mean < 0.60`.
- **C3 — PERMUTE.** Shuffle labels within every env; all arms → chance: `|mean(inv_interaction) − 0.5| < 0.05`.
- **C4 — CAPACITY / REPRESENTATION POSITIVE CONTROL (ADR-0042 / RR-0039 §4.1; disambiguates thesis-death from organ-too-small).** On a pure-interaction single-env split (`a_xor` only, no spurious, no shift): **C4a** our mechanism ≥ 0.80 (representation CAN capture the interaction); **C4b** pooled-linear (arm 2) < 0.60 on the same split (structure is genuinely linear-invisible). Per LEARN-2's C4 false-INVALID lesson, C4 tests **capability, not exact coordinate recovery**. **C4c (soft, reported, NOT gating):** the `Xc1·Xc2` coordinate is kept; precision-tolerant (harmless noise-only survivors tolerated). **[FIX-BLOCKER lens1-1, lens2-3: C4c is explicitly demoted; the attribution claim is carried by C7-attribution below, not by an exact kept-set predicate.]**
- **C5 — CAPACITY-CONFOUND CONTROL (THE decisive gate).** Arm (4) MUST FAIL OOD: `arm4_indist_AUC(@ +1.6) − arm4_OOD_AUC(@ −1.6) ≥ 0.04` **AND** `mean(inv_interaction) − mean(arm4) ≥ DELTA`. The in-dist reference is **`+1.6`, same |magnitude| as OOD, train sign regime** — the only difference is the spurious sign flip **[FIX-BLOCKER lens1-C5]**. If arm (4) also generalizes OOD (drop < 0.04) → **CAPACITY ARTIFACT → INVALID/NULL**, not a representation-causal win.
- **C6 — ENV-VALIDITY / LINEAR-CEILING (reconciled; run-time + pre-freeze) [FIX-BLOCKER lens2-1, lens4-1; FIX-MINOR lens1-5].** Replaces the self-contradictory `<0.6` chance-band. Two parts:
  - **Pre-freeze (A2):** analytic Xc3-only and pooled-linear OOD ceiling < **0.62** at frozen params (≈0.567 by derivation).
  - **Run-time:** both linear arms (2) and (3) must sit **below 0.62** OOD (consistent with the intentional Xc3 decoy — they hit ~0.57, not forced under an impossible 0.60), **AND** the **gating un-nameability quantity is `Δ_A ≥ DELTA` with a 9/10 sign test**, NOT the absolute ceiling. The absolute `<0.62` is a sanity check; `Δ_A` is the decision quantity. If either linear arm reaches ≥0.62 OOD → INVALID (env leaks more linear signal than the frozen ceiling permits).
- **C7 — ATTRIBUTION (NEW, gating) [FIX-BLOCKER lens1-1, lens2-3, lens3-4].** Replaces the false "spurious is cleanly dropped" narrative with a **leave-one-coordinate-out ablation on the winning kept set**, frozen as a gating control: (a) dropping `Xc1·Xc2` from the kept set must **collapse** OOD AUC by ≥ DELTA (the interaction coordinate is load-bearing); (b) dropping **all** retained spurious-involving coordinates (if any survive despite `mag_floor`) must **NOT** improve OOD AUC by more than 0.01 (retained spurious is not what carries the win). If (a) fails, the win is not the interaction → NULL/collapse-to-LEARN-2. If (b) fails, a retained spurious coordinate is load-bearing → INVALID (contaminated win). This makes the causal attribution **measured, not asserted**.

---

## 6. Primary metric + decision rule

**Primary metric:** held-out shifted-env prediction AUC (rank-based `_auc`) of INV_INTERACTION over seeds 0–9 on `test_env_l3` (`test_coupling=-1.6`). Load-bearing comparison is the **double-baseline separation**, two paired per-seed contrasts both required:
- `Δ_A = mean(inv_interaction) − mean(arm 3 linear-invariance)` — win is NOT reproducible by the prior gate.
- `Δ_B = mean(inv_interaction) − mean(arm 4 capacity-matched pooled)` — win is invariance, not capacity.

**DELTA = 0.05** (frozen; above LEARN-2's 0.03 — representation-space claims are noisier in stdlib, bigger margin buys honesty; pre-freeze A5 confirms `mean(Δ_B) − 2·SE > 0.05`).
**Sign test:** ≥ **9/10** wins per contrast (exact binomial p = 11/1024 < 0.05; stricter than LEARN-2 because two contrasts multiply the false-positive surface).

**MET (author recommends; founder casts) iff ALL:**
(a) `Δ_A ≥ DELTA` AND inv_interaction > arm3 in ≥9/10 seeds;
(b) `Δ_B ≥ DELTA` AND inv_interaction > arm4 in ≥9/10 seeds;
(c) C1 no-shift parity passes;
(d) C2 causal ablation passes;
(e) C3 permute passes;
(f) C4 capacity positive control passes (C4a AND C4b);
(g) C5 capacity-confound passes (arm4 in-dist@+1.6 − OOD@−1.6 ≥ 0.04 AND beaten by ≥ DELTA);
(h) C6 env-validity passes (both linear arms < 0.62 OOD; pre-freeze A1/A2 clean);
(i) **C7 attribution passes** (dropping `Xc1·Xc2` collapses ≥ DELTA; dropping retained spurious does not help > 0.01).

**NULL** if all controls pass but `Δ_A` or `Δ_B` < DELTA or a sign test < 9/10. Preserve the statistical/linear implementation; do NOT rescue. If additionally **C4a fails** → re-label **ORGAN-CAPACITY NULL** (opposite phase-2 investment meaning). If the over-selection diagnostic (§5 C7 / A3) shows the NULL is driven by basis-width dilution, re-label **DESIGN NULL** (basis too wide / too few envs), not thesis-death **[FIX-MAJOR lens3-4]**.

**INVALID** if: any of C1–C3, C6 fails (leak / rigged-env / env-invalid); OR **C5 shows arm (4) also generalizes OOD** (capacity artifact); OR **C7(b) shows a retained spurious coordinate is load-bearing** (contaminated win); OR a post-MET read shows the winning kept-set is effectively linear-on-Xc3 (collapse-to-LEARN-2, re-labeled NULL); OR any frozen digest drifts at run (`ENV_PARAMS_L3` canonical JSON, `synthetic_scm_interaction.py`, `learned_cwm.py` `invariant_interaction_auc` + `φ` + `mag_floor` block, MLP hyperparam block if shipped, test file, and both `spec_file_sha256` + `prereg.lock` per boundary #23).

---

## 7. Frozen honest prediction (before any run) + realistic NULL paths

**Frozen prediction:** ~**45–55% MET** — slightly above the merged candidate's 40–50% because the structural fixes (self-square exclusion, 2-vs-2 split, `mag_floor`, `n=800`) remove the two biggest self-inflicted INVALID paths (C5-cushioning squares, C6 self-contradiction) that the red-team proved *would* have fired. A too-easy MET here would itself be the capacity confound, so a NULL-leaning posture remains correct.

**Named realistic NULL/INVALID paths:**
1. **CAPACITY-ARTIFACT INVALID (still the biggest risk, C5).** If the flipping `Xs1` in-distribution signal is weak enough that l2 down-weights it, arm (4) transfers fine, drop < 0.04, `Δ_B → 0`. Mitigated by A4 pre-freeze drop audit but not eliminated.
2. **`Δ_B` THIN → NULL.** If seed variance pushes `Δ_B` below 0.05 on the scored window despite A5. Honest NULL; no rescue.
3. **OVER-SELECTION DILUTION (now DESIGN NULL, not thesis-death).** If `mag_floor=0.15` is too low and junk product coordinates still dilute the refit. Re-labeled DESIGN NULL via C7/A3 diagnostics.
4. **ORGAN-CAPACITY NULL (only if MLP variant authorized).** 8-unit stdlib tanh MLP at n=800 may not reliably fit the quadrant boundary → C4a fails.
5. **COLLAPSE-TO-LEARN-2 (INVALID/NULL).** If C7(a) shows the win is really Xc3-linear, the upgrade bought nothing.
6. **RESIDUAL SPURIOUS SURVIVOR (INVALID via C7(b)).** If a mixed spurious cross product slips `mag_floor` and is load-bearing.

**I will NOT tune** `a_xor`, `a_lin`, couplings, `spur_noise`, `mag_floor`, l2, epochs, basis degree, or `n_samples` to move off a NULL after any scored run.

---

## 8. RR-0029 §5 mapping (complete)

- **CLAIM CLASS:** capability-under-governance ONLY — a stronger learned-representation *organ* on our own built model under the SAME governance. NOT discovery, NOT emergence, NOT a third autonomy axis (RR-0034 ceiling binds: learned CWM is an organ).
- **WRITE CHANNEL:** zero control-path write; representation + model fit OFFLINE, frozen to disk, verify-only scalar-AUC out; zero write to value/policy/temperature/shell/audit/gate/C7 (RR-0026 §5.1; channel = X/analysis only).
- **CONSUMPTION PATH:** frozen-organ-in / scalar-view-out; a test must fail if any advice reaches action selection; produces only AUC scalars for adjudication, never an action; OS consumes only via an approved verify-only seam (#19), never import.
- **PRIOR-NEGATIVE RELATIONSHIP:** LEARN-1/S1b NULL (no advantage without a shift; intervention-clamp leak) → here a shift+structure exists to exploit and no clamp/target feature exists to leak. LEARN-2 MET-but-KNOWN (ICP/IRM on raw linear features) → LEARN-3 targets exactly the "structure the invariance principle cannot already name" that LEARN-2's honest scope excluded, **re-runs LEARN-2's linear arm (3) as a gating baseline that must FAIL**, and adds the NEW **capacity-confound prior-negative** (nonlinear-beats-linear-is-trivial → arm 4 + C5). ADR-0042 (causal advantage under shift + no-shift negative control) → C1 inherited. ADR-0045 (confounder design) → spurious channel + C7 attribution.
- **CHEAP BASELINE (the killer):** the capacity-matched nonlinear pooled arm (arm 4 / C5) — if it generalizes OOD the whole claim dies for one experiment's cost.
- **C6/C7/SD4 BOUNDARY:** untouched; no self-modification, no control-path model, no autonomy claim; SD4 forbidden/founder-reserved; does not cross RR-0034's sealed third axis.
- **PRODUCT/PROCESS BOUNDARY:** object-layer research supply only; a MET is research evidence, NOT an OS product-runtime claim and NOT an engineering-process control; enters OS (if ever) only via approved seam, never cross-repo import (#19).

---

## 9. Honest scope of a MET

**A MET WOULD PROVE:** our own pure-stdlib model, given a richer *supplied* representation (a degree-2 **cross-product** basis) plus cross-environment sign+magnitude invariance selection, generalizes OOD on **non-additive interaction structure that LEARN-2's linear invariance-selection provably cannot name** (verified against the actual filter code and analytically), beating **both** the LEARN-2 linear arm (nothing linear to keep beyond the sub-ceiling Xc3 decoy) **AND** a capacity-matched degree-2 pooled arm of the same function class (which can represent the interaction but overfits the flipping spurious channel OOD, C5), with the win **attributed to invariance-in-representation by measured leave-one-out attribution (C7), not asserted from a kept-set narrative**.

**A MET WOULD NOT PROVE:**
1. It is a **KNOWN** idea — invariant-representation / IRM-over-features (Arjovsky et al.; kernel-ICP) instantiated on our stdlib model, NOT a novel mechanism.
2. The shipped primary representation is **HAND-DESIGNED** — "invariance selection over a richer **supplied** representation," strictly weaker than "learned representation." Only the optional non-gating MLP arm, if authorized and passed, would upgrade that to "learned."
3. It does NOT beat a strong modern nonlinear OOD method — only our capacity-matched baseline; the claim is **internal** (invariance-criterion vs same-capacity-no-criterion).
4. It does NOT beat the borrowed LLM organ and does not claim to (RR-0039 §3 PARKed that).
5. It establishes NO third autonomy axis (RR-0034) — capability-under-governance only.
6. One synthetic SCM at one chosen scale is an **existence proof**, not real-data generality (a later gate).

A NULL honestly says either **no advantage beyond capacity** (C5/Δ_B), or **DESIGN NULL** (basis too wide), or **ORGAN-CAPACITY NULL** (C4a fails — our stdlib representation too small) — three outcomes with different phase-2 investment meaning, which is why C4/C7/A3 disambiguate them. Author recommends; founder casts.

---

## 10. GO / NO-GO recommendation + tests-to-write-first

**Recommendation: GO — conditional on the six pre-freeze audits (A1–A6) passing on the frozen params before `prereg freeze`.**

Rationale: every BLOCKER and MAJOR is now resolved **structurally at the generator/threshold/control level**, not by prose: the C6 self-contradiction is gone (`a_lin=0.30`, ceiling gate `<0.62`, `Δ_A` is the gating quantity); the C5-cushioning non-flipping spurious images are gone (self-squares excluded from the basis; independent-latent spurious); the kept-set contamination is gated (A3 pre-freeze + `mag_floor` + C7 attribution); the C5 in-dist reference is pinned to the same-magnitude train-sign env; `Δ_B` margin is calibrated pre-freeze (A5); RNG disjointness is structural (A6). The design is falsifiable, honestly scoped, and buildable in pure stdlib reusing `_fit_logistic`/`_standardize`/`_predict`/`_auc`. If any of A1–A6 fails, the correct move is **re-derive params from first principles and re-freeze**, not proceed — and NO-GO until they pass.

**Author != adjudicator:** builder recommends GO and, after the scored run, recommends MET/NULL/INVALID; **founder casts final**.

**Tests to write FIRST (tests-first discipline, before any scored run; each must fail if the target behavior is absent — no constant-return passes):**

1. `test_generator_marginal_purity` — A1: every feature's standardized class-mean-shift on a 20 000-sample pool within its frozen band (population-zero features `<0.03`; Xc3 in its intentional sub-ceiling band). **Fails if any component leaks a linear marginal.**
2. `test_linear_ceiling_analytic` — A2: Xc3-only and pooled-linear OOD AUC `< 0.62` at frozen params. **Fails if the env leaks more linear signal than the ceiling.**
3. `test_no_self_squares_in_basis` — `φ` contains exactly 28 coordinates, none of form `x_i²`. **Fails if a self-square (the non-flipping trap) is present.**
4. `test_degree2_sign_stability_audit` — A3: `Xc1·Xc2` and `Xc3` sign-stable ≥9/10 seeds; any spurious-cross admitted ≤1/10. **Fails if spurious contaminates the kept set.**
5. `test_rng_streams_disjoint` — A6: no train row equals a test row across all 10 seeds; named-stream construction. **Fails on train/test leakage.**
6. `test_capacity_matched_arm_is_step_matched` — arm 4 uses identical `φ` and equal gradient-step budget, no invariance filter, no `mag_floor`. **Fails if the capacity match is not exact.**
7. `test_invariant_interaction_auc_offline_verify_only` — mechanism writes nothing to any control path; returns only a scalar AUC. **Fails if any advice reaches action selection (RR-0026 §5.1).**
8. `test_mag_floor_frozen` — `mag_floor=0.15` read from the frozen mechanism block, not a live argument. **Fails if it is tunable at run.**
9. `test_c5_indist_reference_is_train_sign_env` — C5 in-dist reference coupling is `+1.6` (train sign regime, same magnitude as OOD), NOT the no-shift env. **Fails if the decisive gate's reference is mis-pinned.**
10. `test_c7_attribution_leave_one_out` — dropping `Xc1·Xc2` from a synthetic kept set collapses OOD ≥ DELTA; dropping a retained spurious coordinate does not help > 0.01. **Fails if attribution is not actually measured.**
11. `test_digest_lock_covers_new_mechanism` — `prereg.lock` binds `ENV_PARAMS_L3` canonical JSON + `synthetic_scm_interaction.py` + the new `invariant_interaction_auc`/`φ`/`mag_floor` block + test file + `spec_file_sha256`; an r-final run rejects on any drift (boundary #23). **Fails if the new mechanism bytes are not frozen.**
12. `test_permute_and_ablation_hit_chance` — C3 permute → 0.5±0.05; C2 `a_xor=0` → `<0.60`. **Fails if the controls do not bite.**

Implementation order after freeze: generator + `φ` + `invariant_interaction_auc` + arm 4, satisfy tests 1–12, run A1–A6 as the freeze gate, then the single scored run on seeds 0–9.

---

### Files this packet governs (absolute paths)

- `autonomous-agent-core/experiments/synthetic_scm_interaction.py` (NEW — frozen generator; LEARN-2's `synthetic_scm.py` untouched)
- `autonomous-agent-core/src/aac/learned_cwm.py` (EXTEND — add `phi`, `invariant_interaction_auc`, `mag_floor`; existing `invariant_predict_auc` reused unchanged as arm 3)
- `autonomous-agent-core/experiments/tests/test_cwm_learn3_*.py` (NEW — tests 1–12, written first)
- `autonomous-agent-core/docs/research/RR-0039-*` (CWM-LEARN roadmap — record LEARN-3 prereg + honest scope)
- prereg + `prereg.lock` per the meta runner (boundary #23: `builder_id != reviewed_by`, `spec_file_sha256`, mechanism-file digests)

**Author recommends GO conditional on A1–A6. Founder casts final GO/NO-GO and, post-run, MET/NULL/INVALID.**