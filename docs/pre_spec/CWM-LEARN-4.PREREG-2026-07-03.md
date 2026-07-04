# CWM-LEARN-4 preregistration — cross-domain transfer of a LEARNED invariant representation

- **Date:** 2026-07-03 · **Program:** CWM-LEARN (RR-0039), gate 4 (transfer axis — RR-0039's "weakest leg").
- **Author/builder:** Claude. **Adjudicator:** founder (casts MET/NULL/INVALID).
- **Discipline:** tests-first; frozen before the scored run; never tune to pass (AGENTS.md §2.5); author ≠
  adjudicator. Control thresholds are **measured-ceiling-relative** (positive controls empirical), fixing the
  LEARN-2/3 absolute-threshold false-verdict pattern.
- **Branch/HEAD at freeze:** `research/stage0-gate-sovereignty-2026-07-03` @ `de9342b`.
- **Design provenance:** a 10-agent design workflow (Builder A/B + Skeptic C → 5-lens red-team) returned **8
  blockers, two REJECTs** and could not certify a clean MET path; combined with a direct feasibility spike
  (a stdlib V-REx/ERM MLP collapses to chance on a non-exploitable novel family; oracle 0.99), the honest
  expectation is NULL. This gate is built to make that NULL **rigorous and informative**, not to hunt a MET.

## 1. Load-bearing question

Does a SELF-LEARNED representation (a stdlib MLP trained with a V-REx invariance penalty) — trained on one
environment FAMILY — transfer to a COMPLETELY ISOLATED novel family whose nuisance is **independent of y**
(non-exploitable), so that only a representation that truly isolated the invariant interaction (Xc1·Xc2) can
generalise? Two upgrades over LEARN-3: the representation is **learned, not supplied**, and the test family is
held out at the **family level**.

## 2. Files + digests (rechecked at run; drift ⇒ INVALID)

| artifact | sha256[:16] |
|---|---|
| `experiments/synthetic_scm_transfer.py` | `7255e939326b595d` |
| `src/aac/transfer_cwm.py` | `2d6eebd1f22e310b` |
| `experiments/cwm_learn_4.py` | `b60256d176a3dd34` |
| `ENV_PARAMS_T` (canonical JSON) | `9ef4eca145271913` |

- Generator (`synthetic_scm_transfer.py`): invariant `y=1[Xc1·Xc2+noise>0]` shared by all families; TRAIN family
  = 3 envs with a sign-varying exploitable spurious on slot 2; NOVEL-A = isolated family with an **independent**
  slot-2 nuisance (nothing exploitable → the family-isolation "leakage" failure cannot occur); NOVEL-B = a
  relocated nonlinear nuisance (secondary). Named RNG streams → structural family disjointness.
- Mechanism (`transfer_cwm.py`): 2-layer tanh MLP; V-REx penalty (`lam>0`, invariance as a smooth training
  penalty — no hidden-unit selection, so identifiability-robust and a NULL is informative); `lam=0` = the
  capacity-matched ERM baseline. LEARN-2/3 files stay byte-frozen (this is a new file).

## 3. Arms (NOVEL-A, primary) + decision rule (DELTA=0.05, sign test 8/10)

- **vrex** (learned invariant rep, thesis arm) · **erm** (capacity-matched, no invariance) · **supplied**
  (LEARN-3 degree-2 basis + invariance selection, cross-family) · **oracle** (MLP on causal slots 0,1) ·
  **pooled** (statistical).
- **Positive controls (transfer achievable):** `oracle ≥ 0.85` AND `supplied ≥ 0.70`. These are the empirical
  ceilings — a MET is judged relative to them, not to an absolute number.
- **MET** iff positives hold AND `vrex ≥ 0.65` AND `(vrex−erm) ≥ DELTA` AND `(vrex−pooled) ≥ DELTA` AND
  `vrex ≥ supplied − 0.10` (the learned arm approaches the achievable ceiling) AND vrex>erm in ≥8/10 seeds.
- **NULL** iff positives hold but the learned arm does not clear the MET bar (expected: vrex ≈ erm ≈ pooled ≈
  chance, far below supplied/oracle). **Informative:** transfer is achievable, but our learned representation
  does not achieve it — the invariant structure still has to be *supplied* (LEARN-3), our model cannot yet
  *discover* it and carry it across an isolated family.
- **INVALID** iff permute does not collapse (`|perm−0.5|≥0.08`), or positives fail so the null is uninformative
  (ORGAN-CAPACITY: the MLP can't even represent the interaction), or a frozen digest drifts.

## 4. Frozen honest prediction (before the scored run)

**NULL (high confidence).** Feasibility spike: a stdlib V-REx MLP at several λ, and ERM, all collapse to chance
on a novel family whose nuisance is independent of y (the earlier apparent "transfer" was degenerate spurious-
*inversion*, which vanishes when the nuisance is non-exploitable), while the oracle causal-only MLP reaches
0.99 and the LEARN-3 supplied basis transfers. IRM/V-REx-style invariant-representation learning is known to be
finicky and to often fail to beat ERM in low-dim/small-data regimes (Rosenfeld et al.). **I will not tune** the
MLP, λ, architecture, generator params, or thresholds to move off a NULL after the scored run.

## 5. Honest scope

- A **NULL** (expected) means: our own pure-stdlib model does **not** yet learn an invariant representation from
  scratch that transfers across an isolated family — a real boundary on "intelligence on our own model." It is
  *informative* (not an optimisation artifact) because the positive controls prove transfer is achievable and
  permute collapses. It sharpens the LEARN-2/3 result: invariance **selection over a supplied/observed**
  representation works; **learning** the invariant representation to transfer does not (here).
- A **MET** (unexpected) would prove the learned representation earned cross-family transfer over a capacity-
  matched ERM baseline and approached the supplied-basis ceiling — still a KNOWN idea (V-REx/IRM) on our stdlib
  model, internal comparison, one synthetic family pair; not a novel mechanism, not an autonomy claim (RR-0034).

## 6. Result (scored seeds 0–9; frozen digests rechecked, no drift): **NULL — as frozen-predicted**

| arm (NOVEL-A, isolated family) | AUC |
|---|---|
| **vrex (LEARNED invariant rep, ours)** | **0.4947** — chance |
| erm (capacity-matched, no penalty) | 0.6229 |
| supplied basis (LEARN-3, positive ctrl) | **0.8939** ✓ |
| oracle causal-only (positive ctrl) | **0.8813** ✓ |
| pooled statistical | 0.4855 — chance |

- vrex − erm = **−0.128** (0/10 — the V-REx penalty actively *hurt*); vrex − pooled = +0.009; vrex vs supplied
  gap = **−0.399**. NOVEL-B (secondary) same shape: vrex 0.473 / erm 0.675 / supplied 0.893.
- Controls: positives hold (transfer IS achievable), permute collapses (0.515) → the NULL is **informative**.
- **The frozen verdict held without any post-hoc correction** — the first gate in the series where it did,
  validating the measured-ceiling-relative control design after the LEARN-2/3 threshold lessons.

### Honest reading (net)
Our own pure-stdlib model **cannot yet learn** an invariant representation from scratch that transfers across
an isolated environment family — while the same transfer is demonstrably achievable (oracle 0.88; the LEARN-3
**supplied** basis carries 0.89 across both novel families). Two sharp findings inside the NULL:
1. **The invariance penalty hurt, not helped:** ERM partially transfers (0.62 — it partly learns the real
   interaction alongside the spurious), while V-REx (λ=1e4) *degrades* it to chance (0.49). The penalty did
   not isolate the invariant; it damaged learning — consistent with the IRM/V-REx fragility literature
   (Rosenfeld et al.), now reproduced on our model.
2. **The program's current boundary is precise:** invariance **selection over a supplied/observed**
   representation works (LEARN-2 raw MET, LEARN-3 degree-2 MET, and the supplied basis *also wins the
   LEARN-4 cross-family task*); invariant-representation **learning** does not (LEARN-4 NULL). "Intelligence
   on our own model" today = *selection*, not *discovery*, of invariant structure. Discovery is the honest
   open frontier for any next gate (e.g. richer data regimes, staged/curriculum representation learning),
   and this NULL is the preregistered evidence of where it stops.

Author ≠ adjudicator: recommended verdict **NULL** (informative, publishable); **founder casts final.**
