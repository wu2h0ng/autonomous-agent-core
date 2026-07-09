# Strong-Locus Structure Crossover — Preregistration Draft

> Status: Stage 3 harness implementation draft. Stage 1 synthetic harness built and Stage 2 independent non-Claude firewall certification completed 2026-07-06. Stage 3 is founder/CTO-authorized for harness extension with real-LLM backend support and deterministic stub fallback; no autonomy/SD4/C6/C7 claim.

## 1. Research question

Does a governed causal discovery loop (`governed_loop`) show a statistically significant positive advantage over an LLM reasoner using identical discovery tools (`organ_tools`) as the causal structure becomes richer (larger `k`), on held-out interventions in synthetic nonlinear/heteroscedastic SCM worlds?

## 2. Design

- Synthetic SCM worlds per `experiments/scm_generator.py` (nonlinear, saturating, heteroscedastic, Gaussian-mixture noise).
- Held-out intervention scoring per `src/aac/structure_scorer.py`; ground-truth DAG never read by discovery arms.
- Seven arms: `corr`, `organ_alone`, `organ_tools`, `organ_tools_externalized`, `governed_loop`, `passive_loop`, `learned_select`.
- LLM backend is belief-only/proposal-only; deterministic disposer executes all interventions (C6/C7 intact).

## 3. Hyperparameters (locked)

| Parameter | Value |
|---|---|
| seeds | 5000..5019 (20 seeds) |
| k | 3, 8, 15, 25, 40 |
| n_obs | 200 |
| budget | 3 |
| likelihood_mode | linear (intentionally mismatched) |
| score_effect_threshold | 1.5 |
| empirical_effect_threshold | 1.5 |
| model_lock | claude-sonnet-4-20250514 |
| temperature | 0.0 |
| max_tokens | 4096 |
| N_PARTICLES | 20 |
| N_MC_SAMPLES | 3 |
| UCB_ALPHA | 1.0 |

## 4. Success criteria (H_locus)

1. **Trend**: Spearman one-sided `p <= 0.05` on `median(AP(governed_loop) - AP(organ_tools))` vs `k`.
2. **Effect floor**: Bootstrap 95% CI lower bound on the pooled delta for the two largest `k` excludes 0.

## 5. Backend and plumbing

- Real calls use `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` from environment, pinned model, temperature=0.
- Responses cached on disk in `.cache/llm_calls/`.
- Typed plumbing instrumentation tracks `clean_wrong`, `truncated`, `timeout`, `unparseable` separately.
- If no API key is present, the harness falls back to `DeterministicStubBackend` and annotates the run as `stub_only=True`.

## 6. Arms

- `organ_alone`: LLM with locked prompt `prompts/prompt_organ_alone.md`, no tools, returns `final_answer.edges`.
- `organ_tools`: LLM with tools `belief_update` and `info_gain` (byte-identical to governed loop), returns tool calls or final edges.
- `organ_tools_externalized`: LLM reads/writes only an external `BeliefLedger` summary.
- `governed_loop`: deterministic disposer + info-gain selection.
- `passive_loop`: random intervention selection.
- `learned_select`: online tabular UCB selector.
- `corr`: correlation baseline.

## 7. Kill conditions

A seed is marked INVALID and excluded from H_locus inference if any of the following hold:

1. `placebo_passes == false` (the world fails the §4.4 non-identifiability gate).
2. `n_true == 0` on the held-out set (no detectable empirical signal).
3. Any LLM-driven organ arm (`organ_alone`, `organ_tools`, `organ_tools_externalized`) records a plumbing failure (`truncated`, `timeout`, or `unparseable`).

The whole run is downgraded from H_locus inference if:

4. More than 25% of organ-arm calls across all seeds record a plumbing failure.
5. More than 10% of seeds fail the placebo gate.
6. `governed_loop` median AP is not positive for the two largest `k`.

If `stub_only == true`, `organ_tools` and `organ_tools_externalized` are invalid for H_locus inference; the `governed_loop - organ_alone_stub` delta may be reported for diagnostics only and the verdict must be `INVALID`/`INSUFFICIENT_DATA` for H_locus.

## 8. Analysis plan

- Drop INVALID seeds.
- For each `k`, compute `delta_ap = AP(governed_loop) - AP(organ_tools)` across valid seeds.
- Bootstrap 95% CI per `k` and pooled over the two largest `k`.
- Spearman one-sided trend test on median `delta_ap` vs `k`.
- Emit verdict JSON: `MET`, `NOT_MET`, `INVALID`, or `INSUFFICIENT_DATA`.
