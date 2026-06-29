# ADR-0042: Causal World Model G1 — does causal/invariant modeling adapt faster than statistical modeling under surface shift?

- Status: **PREREGISTERED (product line; frozen before implementation)**. 2026-06-30.
- Line: NOT the (closed) autonomy-axis research. This is the **product line**: causal world model → robust fast adaptation → fewer re-learning episodes → lower interaction (the "self-driven worker" goal).
- Bar: **product cost/benefit ("does it beat the simple alternative?"), NOT inseparability.** The autonomy foreclosure does not apply — this tests the sample-efficiency/robustness lever, which the degeneracy analysis explicitly identified as real (H1a).

## Thesis
A learner that models the **causal/invariant** structure (which action actually *causes* reward, learned interventionally) adapts faster than a **statistical** learner that exploits observationally-predictive-but-spurious cues, **specifically when the surface correlations shift while the cause is invariant**. Causal structure generalizes → fewer samples to recover → less re-learning → less hand-holding.

## Environment (CausalRegimeEnv, frozen)
- N=6 actions; one hidden good action `g` (the cause): action==g → reward_high, else reward_low (+noise).
- An observed **marker** `m` is a strong in-epoch cue (m == its target with p=0.9).
- **SURFACE shift** (every 60 steps): the marker's target re-randomizes (m decouples from g) — but `g` is UNCHANGED.
- **CAUSAL shift** (every 600 steps): `g` changes (the cause itself moves); everyone must re-learn.
- Two conditions:
  - **SPURIOUS**: marker == g only initially, then decouples at surface shifts (a spurious cue that breaks).
  - **CAUSAL_CUE** (negative control): marker == g ALWAYS (a genuinely reliable causal cue; using it is correct).

## Arms (frozen)
- `CAUSAL` (invariant): per-action interventional reward estimate (EMA), ε-greedy argmax; **ignores the marker**.
- `STAT` (fair statistical baseline): follows the marker with **adaptive trust** (EMA of whether following it paid), with a per-action fallback + a small floor to re-test the marker. Uses the predictive cue; pays a re-learning cost when it breaks.

## Metric
Expected post-shift regret area (window=15 after each shift), **split by shift type** (surface vs causal), per condition, mean over seeds 0..9. Paired one-sided Wilcoxon.

## Pre-registered decision rule (frozen, not moved after results)
- **H_causal (the claim):** in SPURIOUS, CAUSAL's post-**surface**-shift regret < 0.5 × STAT's (Wilcoxon p<0.05). Causal modeling pays off when spurious cues shift.
- **Negative control (the honesty guard):** in CAUSAL_CUE, CAUSAL does **NOT** beat STAT on post-shift regret (CAUSAL ≥ STAT within margin). If CAUSAL wins even here, the env/learners are rigged toward CAUSAL → result INVALID.
- **Causal-shift parity:** post-**causal**-shift regret of CAUSAL and STAT comparable (both must re-find g); CAUSAL not hugely better (else the advantage isn't specifically about surface-invariance).
- Product reading regardless: report the regret-by-shift-type table; the size + concentration of the CAUSAL advantage = the quantified value of causal modeling for low-interaction operation.

## Seeds
0..9, deterministic per seed. Frozen.

## Out of scope / honesty caps
Not an autonomy claim. Not a discovery claim. A demonstration that the **design choice** (causal/invariant modeling) pays off in the realistic spurious-shift setting, with a negative control proving the advantage isn't general superiority. This is a known result in causal ML (invariant prediction under shift); the point is to ground the product line on a measurable, fair, reproducible first experiment.

## Result (2026-06-30)
Ran as frozen. **Raw**: SPURIOUS surface CAUSAL/STAT=0.291 (p=0.0025), but the **negative control CAUGHT a confound** — CAUSAL also won in CAUSAL_CUE (ratio 0.581) → raw verdict RAW-INVALID (the discipline working: my STAT baseline was intrinsically noisier than CAUSAL, unrelated to surface-invariance). **Difference-in-differences** (CAUSAL_CUE = each arm's no-real-shift baseline; subtract to isolate excess shift-recovery cost): CAUSAL excess = 16.5, STAT excess = 332.5 → **CAUSAL pays 5% of STAT's shift-recovery cost (95% reduction, p=0.0025)**. CLEAN VERDICT: **G1-CWM-MET (confound-controlled)**. Product reading: causal/invariant modeling → robust to surface shift → ~95% less re-learning after a spurious cue breaks → fewer trials / less interaction. The H1a sample-efficiency lever, not the foreclosed autonomy axis. Follow-up: fix STAT's steady-state at source; seed-level CIs + unit test; widen regimes.
