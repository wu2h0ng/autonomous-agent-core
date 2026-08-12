# SELFDEV-7 Adequacy-Floor Round — Adjudication (FINAL, independently accepted as drafted)

> Prereg: `docs/product/AGENT-OS-SELFDEV-7-adequacy-floor-prereg-2026-08-08.md`
> (frozen at 4900bd72, manifest `.agent_runs/selfdev-7/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-7/round/`. Date: 2026-08-08.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored, no builder history) — ADJUDICATION_ACCEPTED. Envelope E7: aligned prompt (a496442) + 600s + ABAB +
> health gate + pause-on-403 + adequacy floor. Subset byte-identical to
> SELFDEV-4/5/6.

## Verdict (frozen rubric incl. §0.4): INSUFFICIENT_DATA

Numerically: chain pass@2 **1/12** < baseline pass@2 **2/12**. But the §0.4
adequacy floor binds: weather-free attempts are baseline 9/24 and chain
11/24 — BOTH below the frozen 12/24 threshold ⇒ the round records
INSUFFICIENT_DATA, not NEGATIVE and not SUPPORTS. No kill criterion fired.
This is the floor's first activation, working as designed after E6's
83%-weather NEGATIVE.

File-verified accounting:

- **Baseline (24)**: 3 solved (2 tasks: django-11066 a1+a2, pytest-5809 a2),
  6 DIFF_INVALID, 15 INVALID_PROVIDER. Weather-free: 9/24.
- **Chain (24)**: 2 solved (1 task: django-11066 a1+a2, independent
  verifier), 4 DIFF_INVALID, 2 INVALID_ENVELOPE, 3 APPLY_FAILED (denial
  reasons logged), 13 INVALID_PROVIDER. Weather-free: 11/24.

## What the thin data does and does not say

- django-11066 remains the chain's best task: solved 2/2 here, 2/2 in E6,
  1/1 in E5 — three rounds, five of five completed attempts solved. On this
  task the aligned-prompt chain matches the baseline exactly (2/2 vs 2/2).
- Failure-class rates on weather-free attempts are now COMPARABLE across
  arms for the first time: chain contract failures 9/11 (4 DIFF_INVALID +
  2 INVALID_ENVELOPE + 3 APPLY_FAILED) vs baseline 6/9 (6 DIFF_INVALID) —
  nothing like E5's 6.5× gap, but the sample is far too small to claim
  closure (the floor correctly refuses to).
- The E5 residual question (governed prompt/response contract) is
  NARROWED, not answered: chain weather-free solve 1/11 vs baseline 3/9
  this round, vs 1/13 vs 6/12 at E5 — directionally improved,
  statistically unresolved.

## Disclosures of record

1. One relabel: astropy-13579 chain a2 FAILED_UNCLASSIFIED →
   INVALID_PROVIDER (HTTP 429 rate-limited; stderr preserved).
2. No quota pauses fired (no 403s this round; the pause machinery was
   armed but unused — 429/timeout stayed consumed per §0.3's crisp line).
3. No driver drift, no workspace integrity failures; 48 invoked markers ==
   48 attempt records; all workspaces clean at pinned heads post-round.

## Negative map

1. **Provider weather is the dominant noise source of the series** (E1
   window, E4 wave, S5 403, E6 83% quota, E7 ~57% timeouts/rate-limits) —
   the series' most actionable infra lesson: rounds must run in verified
   healthy windows with the health gate AND a sustained-usage plan, or N
   must grow.
2. **The chain's diff-contract failure classes persist at baseline-like
   rates post-alignment** (9/11 vs 6/9 weather-free) — the E5 residual
   narrowed but did not close; the sample cannot distinguish "prompt
   fixed" from "prompt was never the whole story".
3. **APPLY_FAILED now logs reasons** (context mismatch) — the class is
   fully observable as of a496442.

## Paradigm learning

- The adequacy floor worked: a weather-dominated round records
  INSUFFICIENT_DATA instead of a misleading NEGATIVE. Keep it in every
  future prereg.
- If another attempt at this question is warranted: same envelope, larger
  N (or a verified sustained-healthy provider window), possibly a
  paid-tier quota check upfront. The floor + pause-on-403 + whitelist
  abort + health gate are now the series' standing machinery.

## Claim boundary

INSUFFICIENT_DATA is restricted to: this round cannot answer whether the
aligned-prompt chain matches the baseline on the frozen subset. NOT a
NEGATIVE, NOT a SUPPORTS, and not any claim about capability, governance,
HCW, release, or Autonomy(S,E,O,V,T).
