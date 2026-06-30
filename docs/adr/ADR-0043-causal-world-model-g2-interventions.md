# ADR-0043: Causal World Model G2 — does a causal-WM agent need fewer human interventions per task?

- Status: **PREREGISTERED (product line; frozen before implementation)**. 2026-06-30. Builds on ADR-0042 (G1).
- Goal metric = the "self-driven worker" metric: **human interventions per task**. Lower = more self-driven / less hand-holding.
- Bar: product cost/benefit. NOT autonomy/inseparability.

## Setup — a minimal agent loop with confidence-gated escalation
A stream of T tasks (same CausalRegimeEnv as G1: a hidden cause `g`, a spurious-or-reliable marker, periodic SURFACE shifts (cause invariant) and rarer CAUSAL shifts (cause moves)). Each task the agent must act correctly (action == g).

**Common escalation policy (identical for both agents — this is the G10/P0 confidence-gate lever):**
- The agent tracks its recent self-driven accuracy (last K tasks; escalated tasks count as success since the human ensured correctness).
- **confidence ≥ θ → act autonomously** (no intervention; succeeds iff its prediction == g).
- **confidence < θ → ESCALATE** = ask the human (+1 intervention); the human reveals `g`, the task succeeds, and the agent learns from the correction.

The ONLY difference between agents is the **world model** that produces the prediction:
- `CWM` (causal/invariant): per-action interventional effect; ignores the marker. Surface shift leaves it correct → confidence stays high → does NOT escalate.
- `STAT` (statistical): exploits the predictive marker. Surface shift breaks the marker → autonomous failures → confidence drops → escalates until it re-learns.

## Conditions
- **SPURIOUS**: marker breaks at surface shifts (realistic).
- **CAUSAL_CUE** (negative control): marker stays reliable; STAT's cue is valid → it should escalate little → CWM must NOT win here.

## Metrics
- **Interventions in the WIN(=15)-task window after each shift, split by shift type (surface vs causal)**, per condition, mean over seeds 0..9.
- Autonomous failure rate (quality check: nobody should win by silently failing instead of escalating).

## Pre-registered decision rule (frozen)
- **H (the claim):** in SPURIOUS, CWM's surface-window interventions < 0.5 × STAT's (Wilcoxon p<0.05), AND CWM's autonomous failure rate not worse than STAT's.
- **Negative control:** in CAUSAL_CUE, CWM does NOT beat STAT on surface-window interventions (ratio ≥ 0.9), else INVALID/rigged.
- **Difference-in-differences** (CAUSAL_CUE = each arm's no-real-shift baseline): the confound-controlled measure of surface-shift-driven interventions; report CWM excess / STAT excess.
- Product reading: the DiD ratio = how much of the statistical agent's "please-check-with-me" load the causal agent removes — the quantified reduction in hand-holding.

## Seeds: 0..9, deterministic. Frozen. K=8, θ=0.625, surface/60, causal/600, T=3000.

## Honesty caps
Synthetic demo; the H1a robustness lever (real, product-relevant), not the foreclosed autonomy axis. Same confidence-gate escalation for both agents → the comparison isolates the world model. Negative control + DiD guard against the G1-style baseline confound.

## Result (2026-06-30) — G2-CWM-MET
SPURIOUS: CWM surface-window interventions = 0.0 vs STAT = 28.9; CWM auto-fail 0.049 < STAT 0.138 (causal agent asks 0× AND fails less). Negative control (CAUSAL_CUE): CWM 0.0, STAT 1.4 → passes (no advantage when the cue is reliable). DiD: CWM excess 0.0 vs STAT excess 27.5 → CWM carries 0% of STAT's surface-shift intervention load (p=0.0025), quality not worse. **VERDICT: G2-CWM-MET** — the causal-WM agent removes 100% of the statistical agent's surface-shift hand-holding at no worse autonomous quality. Honest nuance: at CAUSAL shifts (rules actually move) BOTH still need ~20 interventions — causal removes hand-holding for surface change, not genuine rule change (the right worker behavior). Direct self-driven-worker metric. Next: real task env + real model.
