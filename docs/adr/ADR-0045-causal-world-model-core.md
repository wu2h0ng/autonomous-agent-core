# ADR-0045: Causal World Model Core — the real thing (intervention vs correlation), shared by tracks A & B

- Status: **PREREGISTERED (research prototype; frozen before running)**. 2026-06-30.
- Line: resumed core. Founder chose **both tracks**: (A) LLM + causal world model (general worker), (B) causal world model as core intelligence (narrow). **This builds the SHARED core: the causal world model itself.** (A) = (B) + LLM.
- Fixes the drift the founder caught: an LLM is a correlational model, "running tests" is verification — neither is a causal world model. This builds an explicit one.

## What a causal world model IS (and the falsifiable hallmark)
An agent component that learns, by INTERVENTION (do), an explicit model of which variables CAUSE the outcome, and can PREDICT the effect of interventions. The hallmark that separates it from any statistical/correlational model (incl. an LLM): **given the SAME observational data, it correctly predicts that `do(decoy)` does NOT change the outcome, where a correlational model — fooled by a confounder — predicts that it does.**

## Setup (CausalStructureEnv, frozen)
- D=4 binary features the agent can set. Hidden: one CAUSAL feature `c` and target `t`; reward = 1 iff `x[c]==t`. The other 3 features are DECOYS (no causal effect).
- A confounded OBSERVATIONAL dataset: a confounded expert set `x[c]=t` AND a fixed `x[decoy]=t` (decoy tracks the cause), other features random → in OBS data, BOTH `x[c]` and `x[decoy]` perfectly predict reward.

## Agents
- **CWM (causal)**: spends an INTERVENTIONAL budget — toggles each feature independently (do) and observes whether reward changes → builds an explicit causal mask (which features cause reward) + the causal function. Predicts interventions from the mask.
- **STAT (correlational, the stand-in for "LLM/statistical")**: learns each feature's correlation with reward from the OBS data only (no interventions) → both `c` and `decoy` look predictive. Predicts interventions from correlation.

## Falsifiable tests (frozen)
1. **Interventional prediction accuracy** (the hallmark): over random `do(x[i]=flip)` queries, predict whether reward changes (truth: iff i==c). **Claim: CWM ≈ 100%; STAT fails specifically on decoy queries** (predicts the decoy changes reward — the confounding error).
2. **Action under decoupling** (robustness): both must set `x` to maximize reward when the decoy is decoupled from the cause. CWM acts on `c` → high reward; STAT misled by the decoy → lower.
3. **Negative control**: if the decoy is GENUINELY causal (not a confound), CWM must NOT out-predict STAT (both correct) — else the env is rigged.

## Metric / decision rule
CWM interventional-prediction accuracy − STAT accuracy on decoy queries > 0.4 (frozen); negative control: equal when decoy is real. Seeds 0..19.

## Honesty caps
Minimal explicit causal world model (a causal-mask + function over 4 features). This is the SHARED CORE for tracks A/B; (B) runs it standalone (narrow), (A) adds an LLM as the general proposer with the CWM grounding/correcting it. Not a benchmark; the point is to build a REAL causal world model (the founder's keystone) and show the intervention-vs-correlation hallmark concretely.

## Result (2026-06-30) — CWM-CORE-MET
MAIN (decoy is a confound): interventional-prediction accuracy CWM=1.00 vs STAT=0.75; on do(decoy) queries (the tell) CWM=1.00 vs **STAT=0.00** (the correlational/LLM-style learner is fooled by the confound; the causal model knows do(decoy) does nothing). NEGATIVE CONTROL (decoy genuinely causal): CWM=STAT=1.00 → the advantage is specific to confounds, not general superiority. **VERDICT: CWM-CORE-MET** — a real causal world model (causal mask learned by intervention + interventional prediction), the founder's keystone, distinct from an LLM and from verification. Honest nuance: the action-reward test didn't differentiate (the cause is predictive for STAT too); the causal advantage lives in PREDICTION / not-being-fooled, which compounds in planning/transfer and in **catching an LLM's correlational errors (track A)**. This is the SHARED core: (B)=standalone narrow; (A)=this + LLM (CWM grounds/corrects the LLM).
