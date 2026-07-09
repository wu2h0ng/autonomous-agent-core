# Strong-Locus Stage 4 — Honest Negative Record (2026-07-06)

> **Status:** final honest-negative / insufficient-data record for the strong-locus structure crossover Stage 4 real-data test on Replogle 2022 K562 GWPS Perturb-seq. The pre-locked protocol was followed exactly; no threshold, seed, model, or data-selection parameter was changed post hoc to improve scores. Negative results are first-class per AGENTS.md §2.5.

## What was tested

| Field | Value |
|---|---|
| Experiment | strong-locus structure crossover — Stage 4 fresh-domain real-data harness |
| Dataset | Replogle et al. 2022, K562 genome-wide CRISPRi Perturb-seq (Cell; PMID 35688146; figshare article 20029387) |
| Preprocessed input | `autonomous-agent-core/experiments/replogle_2022_preprocessed.json` |
| Locked pathway | KEGG p53 signaling pathway (hsa04115) |
| Locked gene-selection rule | First 12 gene symbols by alphabetical order inside the pathway; skip genes absent from the expression matrix |
| Consultable interventions | 7 (APAF1, ATM, ATR, BBC3, BID, CASP3, CASP8) |
| Held-out interventions | 3 (AIFM2, BAX, BCL2L1) |
| Locked likelihood mode | `linear` (intentionally mismatched) |
| Locked SEM effect threshold | 1.5 |
| Budget | 3 |
| LLM backend | Kimi OpenAI-compatible endpoint (`https://api.kimi.com/coding/v1/chat/completions`) |
| Locked model | `kimi-k2-0711-preview` |
| Locked temperature | 1.0 |
| Runner | `experiments/strong_locus_structure_crossover.py --stage 4 --backend openai` |
| Result file | `experiments/strong_locus_stage4_openai.result.json` |
| Leak-probe file | `experiments/strong_locus_leak_probe_replogle_2022.result.json` |
| Diagnostic file | `experiments/strong_locus_stage4_replogle_2022_diagnostic.json` |

## Leak-probe result

5/5 seeds passed. The model returned empty `dataset_guess`, `pathway_guess`, and `gene_mapping` for every seed. Verdict: **RUNNABLE**.

## Harness result

- C7 halt/rollback smoke test: **PASS**
- All 7 arms executed without crashing: **PASS**
- `n_true` on held-out interventions: **0**
- Verdict: **INSUFFICIENT_DATA_HONEST_NEGATIVE**

## Why it is an honest negative

The data were downloaded, preprocessed, and scored under the pre-locked protocol. The diagnostic (`experiments/strong_locus_stage4_replogle_2022_diagnostic.json`) shows:

- The pseudo-bulk h5ad provides **at most 1–2 aggregated observations per held-out perturbation target**.
- The strongest standardized mean shifts observed are **~1.2–1.4** (BAX→CASP3, AIFM2→BBC3).
- The locked SEM threshold is **1.5**; therefore **zero held-out edges cross the detection bar**.
- At a lower threshold of 1.0, only 2 edges would be declared; the locked threshold was not chosen to make this run pass.

This is a dataset-signal limitation, not a harness bug. No threshold, seed, preprocessing rule, or model parameter was altered after seeing the result.

## Discipline checks

| Check | Status | Evidence |
|---|---|---|
| Variable-selection lock frozen before data inspection | PASS | `experiments/variable_selection_lock.json` |
| Leak-probe passed before model run | PASS | `experiments/strong_locus_leak_probe_replogle_2022.result.json` |
| Locked SEM threshold unchanged | PASS | `experiments/strong_locus_stage4_replogle_2022.spec.json` (`score_effect_threshold=1.5`, `empirical_effect_threshold=1.5`) |
| No post-hoc reseed or model swap | PASS | spec updated only to reflect the actual backend that was authorized and used (`kimi-k2-0711-preview`, temperature=1.0) |
| C7 governance exercised | PASS | `_c7_halt_test()` returns true; disposer remains deterministic and belief-only |
| Plumbing failures recorded separately | PASS | `plumbing_summary` reports `organ_alone` unparseable=1, `organ_tools` timeout=3/unparseable=1, `organ_tools_externalized` clean |

## Disposition

Stage 4 of the strong-locus structure crossover **does not yield a measurable H_locus signal on Replogle 2022 K562 GWPS under the pre-registered protocol**. The honest negative is recorded and archived.

A future Stage 4 attempt requires:

1. A new dataset with **many replicates per held-out intervention** (e.g., single-cell-level counts, or a bulk screen with biological replicates), **or**
2. A new pre-registered ADR/CTO gate that explicitly lowers the effect threshold or changes the empirical-truth definition **before any data are inspected**.

No rescue, retune, reseed, or threshold relaxation is authorized by this record.

## References

- Preregistration draft: `docs/research/PREREG-DRAFT-strong-locus-structure-crossover-2026-07-06.md`
- Stage 2 firewall certification: `docs/research/FIREWALL-REVIEW-strong-locus-structure-stage1-opencode-2026-07-06.md`, `docs/research/FIREWALL-REVIEW-strong-locus-perturb-seq-opencode-2026-07-06.md`
- Dataset assessment: `experiments/replogle_2022_k562_gwps_gap_assessment.json`
- Preprocessing script: `experiments/replogle_2022_preprocessing.py`
- Runner: `experiments/strong_locus_structure_crossover.py`
- Tests: `tests/test_strong_locus_stage4.py`
