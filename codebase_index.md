# codebase_index - autonomous-agent-core

> Last updated: 2026-07-13
> Purpose: fast map from Agent OS product authority and current research state to code, tests, experiments, and ADRs.
> First read: `docs/CURRENT_STATE.yaml` -> `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`.

## Product Authority

| File | Role |
|---|---|
| `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` | Final Agent OS Product Blueprint v1.1: unified Agent Surface, Ask/Work boundary, plural world models, canonical reusable assets, dual-track monorepo, market parity and evidence gates |
| `docs/adr/ADR-0055-agent-os-interaction-and-organ-boundaries.md` | Accepted docs-only boundary: LLM as probabilistic language/reasoning organ, optional evidence-gated CWM, no canonical Skill kernel object, deterministic authority retained |
| `docs/architecture/T-P-OS-SPINE-0-ARCHITECTURE-PACKET.md` | Accepted, independently re-reviewed architecture for the first executable Product Track spine: modular monolith, canonical contracts, durable runtime, provider/credentials, authority split, outcomes and acceptance gates |
| `docs/adr/ADR-0054-one-time-data-agent-history-migration.md` | Accepted bounded Hard Boundary #19 exception for a one-time history-safe Data Agent migration; planning authorized, execution remains gated |
| `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml` | Design-only SPINE-1 mapping with full-history safety scan, direct-or-filtered import, generic/domain extraction and no runtime federation; no migration executed |
| `docs/research/AGENT-OS-RESEARCH-GAP-AND-BOTTLENECK-AUDIT-2026-07-10.md` | Evidence-limited audit of research deficiencies, architecture corrections, breakthrough bottleneck and product-grounded portfolio decision |
| `docs/research/AGENT-OS-PRODUCT-GROUNDED-EXPERIMENT-MATRIX.yaml` | Twelve P0-P2 product/research eval candidates with prerequisites, baselines and kill gates; not preregistered or run-authorized |
| `docs/PRD.md` | Research Track historical requirements only; not the product PRD |
| `docs/PROJECT_PLAN.md` | Active Product/Research task handoff and immediate Product Track spine task |
| `ROADMAP.md` | Product dependency order plus preserved Research Track history |
| `ENGINEERING.md` | Dual-track engineering constraints; Research stdlib/falsification controls and Product dependency/authority boundaries |
| `.github/pull_request_template.md` | Track-aware Product/Research/Docs PR evidence and boundary checklist |
| `docs/superpowers/plans/2026-07-10-agent-os-product-blueprint-v1.md` | Docs-only finalization and verification plan |
| `docs/superpowers/plans/2026-07-10-t-p-os-spine-0-p0a-contracts-run-kernel.md` | Executed test-first P0A implementation plan for contracts, WorkflowGraph, event replay and TaskService |
| `docs/superpowers/specs/2026-07-12-agent-os-e2e-long-horizon-convergence-design.md` | Founder-authorized Product Track design for bounded wait/signal/rebind/restart/compensation and event-derived recovery; explicitly not `LH-RECOVERY-1` |
| `docs/superpowers/plans/2026-07-12-agent-os-e2e-long-horizon-implementation.md` | Executed multi-agent implementation plan and file-ownership boundary for `T-P-OS-LH-BOUND-1` |
| `docs/research/SPINE-E2E-1-result.md` | Binding fresh frozen evaluation result: `INVALID` due receipt-accounting instrumentation false positive; no Product failure, PASS, D2 or parent LH run claim |

Repository identity: complete Agent OS main monorepo. Current implementation reality:
research-heavy with SPINE-0 PM-accepted for the bounded local independent-developer golden
path. Market parity, enterprise production and the rest of the Blueprint are not delivered.
Existing `src/aac`, `experiments` and research adapters remain Research Track unless
explicitly promoted.

## Current Snapshot

```yaml
product: Agent OS
product_blueprint: FINAL_FOUNDER_RATIFIED_V1_1
product_architecture: T-P-OS-SPINE-0 PM_PRODUCT_ACCEPTED_LOCAL_DEVELOPER_SLICE
topology: dual-track layered monorepo
implementation: typed provider patch proposal + exact approval + durable wait/signal/rebind/restart + governed workspace tools/compensation + recovery projection + API/CLI/Task Workspace
long_horizon_product_slice: LH_PRODUCT_SLICE_E2 / BOUNDED_LONG_HORIZON_LOCAL_SLICE_VERIFIED
long_horizon_evidence_scope: PRODUCT_LOCAL_ACCEPTANCE_ONLY; SPINE-E2E-1 FRESH_FROZEN_INVALID_INSTRUMENT; LH-RECOVERY-1 BLOCKED_NOT_RUN
interaction_definition: one Agent Surface; Ask ephemeral; Work durable; governed-action escalation
organ_definition: provider-neutral LLM + plural task-appropriate world models; CWM optional/evidence-gated
skill_definition: external compatibility input only; no canonical Skill kernel object
research_source: reconcile/igi-organstack-into-open-world-arc-2026-07-10
research_stage: reconciled open-world + IGI organ-stack/CWM lines; exact verdicts in CURRENT_STATE
product_tests: 407 passed, 1 skipped; ruff clean on candidate 8bd5aec
full_tests_historical_baseline_not_rerun_on_branch: 1321 passed, 14 skipped, 5 subtests passed
product_claim_from_tests: SPINE-0 plus bounded local long-horizon acceptance only; no multi-hour/day advantage, 7x24 autonomy, physical exactly-once, LH-RECOVERY-1, Codex parity, Blueprint completion or superiority
```

Do not use older references that say the current stage is P1, P2, P3, or P4. They are historical.

## Product Track SPINE-0 - Accepted Local Developer Slice (2026-07-10)

| File | Role |
|---|---|
| `pyproject.toml` | Research root distribution remains zero-dependency; Product test tooling plus pytest/pyright source paths |
| `packages/contracts/pyproject.toml` | `agent-os-contracts` distribution metadata and Pydantic runtime dependency |
| `packages/os_core/pyproject.toml` | `agent-os-core` distribution metadata and exact contracts dependency |
| `packages/contracts/src/agent_os_contracts/common.py` | Strict immutable contract base, timezone normalization, canonical JSON and SHA-256 digest |
| `packages/contracts/src/agent_os_contracts/task.py` | `Goal` and `Commitment` with task/scope/authority fields |
| `packages/contracts/src/agent_os_contracts/workflow.py` | `WorkflowGraph` v1, bounded node families, typed WAIT_EVENT binding, max-replan budget, duplicate/endpoint/cycle/terminal validation and order-stable digest |
| `packages/contracts/src/agent_os_contracts/outcome.py` | Separate expected/observed outcome contracts; verified outcomes require score and evidence |
| `packages/contracts/src/agent_os_contracts/runtime.py` | Task/run states plus immutable canonical-payload events, WAITING_EVENT, ExternalSignal, WaitCondition, plan rebound, recovery and compensation contracts |
| `packages/os_core/src/agent_os_core/event_store.py` | `TaskEventStore` port and concurrency-safe in-memory adapter; explicitly not durable storage |
| `packages/os_core/src/agent_os_core/task_aggregate.py` | Event-rehydrated Task aggregate; explicit wait/signal/rebind/compensation replay plus scope, transition and workflow-digest invariants |
| `packages/os_core/src/agent_os_core/task_service.py` | Atomic create/commit/start/status/wait/signal/deadline/rebind/approval event commands with optimistic concurrency |
| `packages/os_core/src/agent_os_core/persistence.py` | SQLite WAL task events, idempotency, lease fencing and atomically advanced persistent correction epochs |
| `packages/os_core/src/agent_os_core/postgres.py` | PostgreSQL adapter for the same event/lease/idempotency/correction authority ports |
| `packages/os_core/src/agent_os_core/provider.py` | Credential broker, deterministic test provider and typed OpenAI-compatible provider adapter |
| `packages/os_core/src/agent_os_core/execution.py` | Durable coordinator for wait no-op/timeout, restart, suffix rebind, proposal/approval binding, lease recovery and governed automatic/manual patch compensation |
| `packages/os_core/src/agent_os_core/capability.py` | Path-confined workspace tools plus snapshot-before-write, digest-validated restart-safe patch/compensation state machine |
| `packages/os_core/src/agent_os_core/governance.py` | Persistent correction live reads plus final permit-expiry, halt and epoch checks at connector boundary |
| `packages/os_core/src/agent_os_core/recovery.py` | Pure event-derived recovery counters; never infers physical exactly-once or long-horizon superiority |
| `apps/api_server/` | Product composition root and HTTP entries for signal/replan/correction-resume/compensation/recovery, plus responsive Task Workspace and bounded static UX preview |
| `docs/superpowers/specs/2026-07-10-agent-os-unified-workbench-i18n-design.md` | Founder-approved UX model and verified static-prototype boundary: three workspace profiles, Ask/Work, soft scene presets, governed generative workspace and i18n separation |
| `apps/cli/` | Local CLI over the same application execution path, including signal, replan, correction-resume, compensation and recovery commands |
| `domain_packs/developer_agent/` | Versioned developer-agent domain manifest for the accepted golden path |
| `docs/product/PM-PRODUCT-ACCEPTANCE-SPINE-0-2026-07-10.md` | First PM reject, remediation evidence and final bounded `ACCEPT` verdict |
| `docs/product/AGENT-PRODUCT-DESIGN-SOURCE-STUDY-2026-07-10.md` | Dated commercial-product and pinned-source study; maps real agent-product pain points to Agent OS engineering mechanisms and recommends the next hardening packet without authorizing dependencies |
| `tests/product/test_e2_long_horizon_recovery.py` | Claude-authored three-scenario local composition-root acceptance: verified wait/rebind, NOT_MET compensation and C7-governed recovery |
| `tests/product/test_public_long_horizon_negative_paths.py` | OpenCode-authored real HTTP/CLI SQLite persistence, idempotency, scope, late-signal and replan-budget negative paths |
| `tests/product/test_rebind_partial_evidence_regression.py` | Kimi-authored real tool interruption/rebind regression for node/action binding and authoritative evidence filtering |
| `product_evals/spine_e2e_1/` | Fresh frozen SPINE evaluation protocol and CLI; first run preserved `INVALID` because total action-receipt accounting falsely classified a normal tests receipt as duplicate apply |
| `tests/product/` | Product Track contract, execution, security, provider, API, persistence and recovery tests; candidate-wide Product plus product-eval verification passed 407 with one live-provider skip |

SPINE-0 is accepted only for the local, single-workspace, one-file replacement path with an
allowlisted verifier. Production KMS/SSO/tenancy, general coding-agent execution, arbitrary
shell/browser control, visual workflow editing, marketplace, subagent swarms, CWM/belief
promotion and SPINE-1 migration remain absent.

## Bounded Long-Horizon Product Slice (2026-07-12)

`T-P-OS-LH-BOUND-1` is `LOCAL_ACCEPTANCE_VERIFIED` on
`codex/agent-os-e2e-long-horizon-20260712`. It adds durable typed waits/signals, immutable
deadlines, one bounded explicit suffix rebind, restart reconstruction, persistent C7 checks,
restart-safe patch compensation and an event-derived recovery projection. Application, HTTP and
CLI use the same service/coordinator path.

This is `LH_PRODUCT_SLICE_E2`, a Product implementation label, not the Blueprint's research
evidence level E2. Fresh frozen `SPINE-E2E-1` ended `INVALID` because its protocol counted a
normal tests receipt as a duplicate apply receipt; it is neither PASS nor Product NOT_PASS.
`LH-RECOVERY-1A D2` was not constructed and parent `LH-RECOVERY-1` remains blocked/not run. There is no
background scheduler, 7x24 fleet, multi-hour/day comparison, physical exactly-once claim,
automatic LLM replan, general loop/parallel/subworkflow runtime, CWM/Belief/AgentSelfModel
product integration, continual learning or self-evolution evidence.

## Strong-Locus Structure Crossover Harness (2026-07-06)

Stage 1 harness for the H_locus / H_process crossover per `PREREG-DRAFT-strong-locus-structure-crossover-2026-07-06.md`. Synthetic-data only; no real LLM calls; no external data. Builder self-review patched: placebo unified, prompt templates aligned/loaded, `GovernedDecisionGate` wired into loop/learned_select arms, likelihood/scorer thresholds locked. Stage 2 independent non-Claude firewall certification completed and CERTIFIED by opencode on 2026-07-06. Stage 3 harness now extends the certified Stage 1 harness with real-LLM backend support (Anthropic/OpenAI via stdlib), deterministic stub fallback, typed plumbing instrumentation, and pre-registered adjudication. Stage 4 blockers partially cleared: KEGG p53 pathway/gene list locked in `experiments/variable_selection_lock.json`; preprocessing `experiments/perturb_seq_preprocessing.py`, Perturb-seq placebo generator `src/aac/placebo_perturb_seq.py`, and leak-probe harness `experiments/strong_locus_leak_probe.py` implemented with unit tests; per-sample GSM2396858 files downloaded and diagnosed honest negative (0/10 KO targets overlap pathway). Replogle 2022 K562 genome-wide Perturb-seq Stage 4 preprocessing and real-LLM leak-probe completed: `experiments/replogle_2022_preprocessing.py` reads `experiments/data/perturb_seq/K562_gwps_normalized_bulk_01.h5ad` (figshare article 20029387, 374 MB), selects the 10 consultable locked KEGG p53-pathway genes, aggregates guide-level rows by target gene, splits 7 consultable / 3 held-out KO targets, and emits `experiments/replogle_2022_preprocessed.json` + CSV preview. Real-LLM leak-probe via Kimi OpenAI-compatible endpoint (`https://api.kimi.com/coding/v1/chat/completions`, model `kimi-k2-0711-preview`, temperature=1.0) produced `experiments/strong_locus_leak_probe_replogle_2022.result.json`: 5/5 seeds passed, failed_seeds empty, verdict RUNNABLE; the model returned empty `dataset_guess`, `pathway_guess`, and `gene_mapping`, indicating no re-identification from anonymized summary statistics. Assessment `experiments/replogle_2022_k562_gwps_gap_assessment.json` records 10/12 locked p53-pathway genes both measured and perturbed, exceeding the >=5 consultable-intervention threshold; verdict **CANDIDATE_FIT**. Added deterministic intervention-gap analyzer (`experiments/strong_locus_intervention_gap.py`) and LLM advisor (`experiments/strong_locus_intervention_advisor.py`) with stub fallback; advisor proposes missing interventions or dataset pivots but the deterministic protocol gate remains binding. `src/aac/llm_client.py` extended to support `ANTHROPIC_API_URL`, `OPENAI_API_URL`, `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_TEMPERATURE`, and `OPENAI_TEMPERATURE` environment variables for OpenAI/Anthropic-compatible proxies. No Stage 3 real-LLM result, Stage 4 real-data model run, product claim, autonomy claim, or C6/C7/SD4 change is authorized.

| File | Role |
|------|------|
| `experiments/scm_generator.py` | Nonlinear / heteroscedastic / saturating SCM generator + placebo world mode. Pure stdlib. Output clamp added for numerical stability at large k. |
| `src/aac/structure_scorer.py` | Held-out intervention scorer: AP/SHD with empirical truth, no ground-truth DAG read. `_std` uses Welford's algorithm for numerical stability at large k. |
| `src/aac/placebo_world.py` | Placebo non-causal world generator + §4.4 non-identifiability validation (permutation-null edge detection + covariance distance). |
| `src/aac/plumbing_instrument.py` | Typed FAILURE logging: `{clean_wrong, truncated, timeout, unparseable}` tracked separately; plumbing 0.0 never pooled with reasoning 0.0. |
| `experiments/phase_a_acceptance.py` | Phase A acceptance: mismatch, held-out AP/SHD, oracle-wrong-params, placebo §4.4, plumbing separation. |
| `src/aac/organ_tools.py` | `organ_tools` arm: LLM with `belief_update` + `info_gain` tools byte-identical to `GovernedDiBS`; `DeterministicStubBackend` for Stage 1. Stage 3: optional `PlumbingInstrument`, parses `tool_call` and `final_answer`, records `plumbing_counts`. |
| `src/aac/organ_tools_externalized.py` | Externalized-belief variant: belief state lives in `BeliefLedger`; LLM/stub reads/writes ledger only. Stage 3: optional instrument, final-edge parsing, plumbing counts. |
| `src/aac/llm_client.py` | Stage 3 Anthropic/OpenAI stdlib backends + deterministic stub fallback + on-disk response cache + `PlumbingInstrument` integration. |
| `src/aac/learned_select.py` | Online tabular-UCB learned selection arm; per-seed random init; no cross-env pretraining; proposes only. |
| `prompts/prompt_organ_alone.md` | Locked prompt for `organ_alone` scratchpad arm. |
| `prompts/prompt_organ_tools.md` | Locked prompt + tool schemas for `organ_tools` arm. |
| `experiments/strong_locus_structure_crossover.py` | Runner for all 7 arms across seeds/k; emits result JSON; C7 halt/rollback test; hyperparameter hash. Stage 3 CLI supports `--stage`, `--spec`, `--seeds`, `--backend`, `--result-path`, `--plumbing-path`. |
| `experiments/strong_locus_structure_crossover.result.json` | Example Stage 1 result artifact (synthetic, 2 seeds × 2 k values). |
| `experiments/strong_locus_stage3.spec.json` | Locked Stage 3 hyperparameters, ks, model lock, kill conditions, trend/effect-floor preregistration. |
| `experiments/strong_locus_stage3.seeds.json` | Fresh seed band 5000..5019 with SHA-256 digest. |
| `experiments/strong_locus_stage3_adjudicate.py` | Stage 3 adjudicator: drop INVALID seeds, bootstrap CIs, Spearman one-sided trend test, kill conditions, verdict JSON. |
| `experiments/variable_selection_lock.json` | Locked KEGG p53 signaling pathway (hsa04115) + alphabetically first 12 gene symbols; selection before data inspection. |
| `experiments/strong_locus_stage4.spec.json` | Locked Stage 4 parameters: GSE90063 sample, effect thresholds, budget, leak-probe seeds, consultable fraction, prereg reference. |
| `experiments/perturb_seq_preprocessing.py` | Extracts GEO per-sample MatrixMarket + cell/gene mappings, selects locked pathway genes, splits KOs into consultable/held-out, normalizes and standardizes, emits JSON. Pure stdlib. |
| `src/aac/placebo_perturb_seq.py` | Perturb-seq placebo generator: resamples observational cells for each KO label, destroying causal link while preserving marginals; §4.4 non-identifiability validation gate. |
| `experiments/strong_locus_leak_probe.py` | Anonymized correlation + marginal summary leak probe; presents anonymized tokens to locked LLM and checks re-identification of dataset/pathway/genes. Stub-only without API key. |
| `experiments/strong_locus_intervention_gap.py` | Deterministic gap analyzer: given a locked variable set and a Perturb-seq dataset, reports observable locked genes, available KO interventions, consultable interventions, and recommends PROCEED / REQUEST_INTERVENTIONS / PIVOT_DATASET / HONEST_NEGATIVE. |
| `experiments/strong_locus_intervention_advisor.py` | LLM advisor (stub fallback) that reads the gap report and proposes symbolic missing interventions or dataset pivots; deterministic protocol gate remains binding. |
| `experiments/replogle_2022_k562_gwps_gap_assessment.json` | Stage 4 dataset assessment for Replogle 2022 K562 genome-wide Perturb-seq: 10/12 locked p53 genes measured and perturbed; verdict CANDIDATE_FIT. |
| `experiments/replogle_2022_preprocessing.py` | h5ad preprocessing for Replogle 2022 K562 GWPS: selects locked genes, aggregates guide rows by target, splits consultable/held-out, normalizes and standardizes, emits JSON + CSV. |
| `experiments/strong_locus_stage4_replogle_2022.spec.json` | Locked Stage 4 parameters for Replogle 2022: accession, effect thresholds, budget, leak-probe seeds, consultable fraction, prereg reference. Model lock corrected to `kimi-k2-0711-preview`, temperature=1.0 to match actual backend. |
| `experiments/replogle_2022_preprocessed.json` | Preprocessed Stage 4 input for Replogle 2022: 200 observational rows + 7 consultable + 3 held-out interventions on 10 locked p53 genes. |
| `experiments/strong_locus_stage4_openai.result.json` | Stage 4 real-LLM harness result on Replogle 2022: all 7 arms executed, C7 halt test PASS, n_true=0, verdict INSUFFICIENT_DATA_HONEST_NEGATIVE. |
| `experiments/strong_locus_stage4_replogle_2022_diagnostic.py` | Diagnostic script computing held-out intervention effect sizes across thresholds. |
| `experiments/strong_locus_stage4_replogle_2022_diagnostic.json` | Diagnostic result: root cause is <=2 aggregated observations per held-out target and strongest effects ~1.2-1.4 below locked 1.5 threshold. |
| `docs/research/HONEST-NEGATIVE-strong-locus-stage4-replogle-2026-07-06.md` | Final honest-negative record for Stage 4 Replogle 2022: protocol followed, no post-hoc changes, disposition recorded. |
| `experiments/strong_locus_leak_probe_replogle_2022.result.json` | Real-LLM leak-probe result for Replogle 2022: 5/5 seeds passed, verdict RUNNABLE, stub_only=false, backend=kimi-k2-0711-preview. |
| `tests/test_replogle_2022_preprocessing.py` | Unit tests for h5ad preprocessing using synthetic in-memory AnnData; skips if anndata/numpy unavailable. |
| `docs/research/PREREG-DRAFT-strong-locus-structure-crossover-2026-07-06.md` | Preregistration draft with §7 kill conditions and analysis plan. |
| `docs/research/FIREWALL-CERTIFICATION-PACKET-strong-locus-perturb-seq-2026-07-06.md` | Certification packet updated to STAGE-2 CERTIFIED with artifact hashes and review file references. |
| `tests/test_llm_client.py` | Stub fallback, fake HTTP parsing, plumbing event emission, response caching. |
| `tests/test_organ_tools_plumbing.py` | `PlumbingInstrument` integration for `organ_tools` and `organ_tools_externalized`. |
| `tests/test_strong_locus_stage3.py` | Spec/seeds digest verification and tiny stub-only Stage 3 run + adjudication. |
| `tests/test_strong_locus_stage4.py` | Stage 4 stub harness runs all 7 arms and preserves preprocessed metadata. |
| `tests/test_perturb_seq_preprocessing.py` | End-to-end preprocessing test with synthetic tar archive. |
| `tests/test_placebo_perturb_seq.py` | Placebo count preservation, covariance symmetry, and §4.4 gate tests. |
| `tests/test_leak_probe.py` | Stub backend leak-probe run and `_score_leak` unit tests. |

## SELFDISCOVERY-A Stage A (2026-07-05)

| File | Role |
|------|------|
| `experiments/selfdiscovery_a_stage_a.py` | Spearman-rank skeleton probe (~5 lines over GGM pipeline). Pure stdlib. GATE: PASS on real Sachs (rank recovers 15/17 edges at tau=0.02 vs linear 14/17), but marginal gain — ~80% NULL prior holds. |
| `tests/test_selfdiscovery_a_stage_a.py` | 20 tests: rank transform correctness, linear/rank skeleton recovery, GATE boolean integrity. |

## Live Intervention Environment Binding (2026-07-08)

| File | Role |
|------|------|
| `src/aac/live_intervention_env.py` | Controllable linear-Gaussian SCM simulation environment with `observe(n)` and `intervene(node, value)`. Ground-truth DAG exposed for evaluation only. Verify-only: no execution authority. |
| `src/aac/interactive_discovery_loop.py` | `InteractiveDiscoveryLoop` subclasses `GovernedDiscoveryLoop` and routes BOED/EIG proposals to the live environment. Includes BOED vs random-baseline benchmark helper. |
| `experiments/live_intervention_binding.py` | Benchmark runner comparing BOED-driven live interventions to random interventions on a 4-node simulation DAG. Emits `experiments/live_intervention_binding.result.json`. |
| `experiments/live_intervention_binding.result.json` | Example benchmark artifact. |
| `tests/test_live_intervention_binding.py` | 6 tests: env observe/intervene shapes, SHD, full loop, BOED <= random SHD on a simple chain, C7-offline invariant (loop only reads env). |

## Regime-Shift / Online Live Intervention Binding (2026-07-08)

| File | Role |
|------|------|
| `src/aac/regime_shift_env.py` | `PiecewiseCausalSimulationEnv`: piecewise-stationary linear-Gaussian SCM with multiple regimes and changepoints. Exposes per-regime ground-truth DAGs and current-regime `observe(n)` / `intervene(node, value)`. Verify-only: no execution authority. |
| `src/aac/interactive_discovery_loop.py` | Extended with `OnlineInteractiveDiscoveryLoop`: multi-round observe→intervene loop with a sliding observation window so the posterior can adapt to regime shifts. Includes `run_regime_shift_benchmark` comparing online adaptive discovery to a static pre-shift baseline. |
| `experiments/regime_shift_binding.py` | Benchmark runner for regime-shift live interventions. Emits `experiments/regime_shift_binding.result.json`. |
| `experiments/regime_shift_binding.result.json` | Example benchmark artifact. |
| `tests/test_regime_shift_env.py` | 5 tests: single-regime equivalence, distribution change across changepoint, current-regime intervention, per-regime SHD, changepoint validation. |
| `tests/test_online_discovery_loop.py` | 4 tests: multi-round loop, online adaptation beats static baseline under regime shift, windowing discards old observations, C7-offline invariant. |

## Nonlinear (Polynomial) Live Intervention Binding (2026-07-08)

| File | Role |
|------|------|
| `src/aac/nonlinear_intervention_env.py` | `PolynomialCausalSimulationEnv`: quadratic SCM simulation environment. Each parent contributes `beta * x_parent^2` to its child. Exposes `observe(n)` and `intervene(node, value)` and the ground-truth DAG. Verify-only: no execution authority. |
| `src/aac/interactive_discovery_loop.py` | Reuses `OnlineInteractiveDiscoveryLoop` with `likelihood_mode="poly2"` to handle the quadratic parent effects. |
| `experiments/nonlinear_intervention_binding.py` | Benchmark runner comparing `linear` and `poly2` likelihood modes on the quadratic env. Emits `experiments/nonlinear_intervention_binding.result.json`. |
| `experiments/nonlinear_intervention_binding.result.json` | Example benchmark artifact. |
| `tests/test_nonlinear_intervention_env.py` | 4 tests: env observe/intervene shapes, quadratic intervention scaling, ground-truth SHD, and poly2 likelihood beating linear likelihood on nonlinear data in the online live loop. |

## Latent-Confounder / Partially-Observed Live Intervention Binding (2026-07-08)

| File | Role |
|------|------|
| `src/aac/latent_confounder_env.py` | `PartiallyObservedSCMEnv`: wraps a full linear-Gaussian SCM (`CausalSimulationEnv`) and exposes only a subset of observed nodes. Interventions are applied to observed nodes in the full SCM; only observed dimensions are returned. Exposes the observed-subgraph ground truth for evaluation. Verify-only: no execution authority. |
| `src/aac/interactive_discovery_loop.py` | Reuses `OnlineInteractiveDiscoveryLoop`; the discovery loop only sees observed nodes and can only intervene on observed nodes. |
| `experiments/latent_confounder_binding.py` | Benchmark runner measuring final SHD and maximum false-edge marginal under latent confounding. Emits `experiments/latent_confounder_binding.result.json`. |
| `experiments/latent_confounder_binding.result.json` | Example benchmark artifact. |
| `tests/test_latent_confounder_env.py` | 7 tests: observed-only observations/interventions, ground-truth filtering of latent edges, SHD, loop completion without high-confidence false edges, intervention identifies direct observed edge, C7-offline invariant. |

## Unified Live-Environment Harness + Multi-Seed Sweep (2026-07-08)

| File | Role |
|------|------|
| `src/aac/live_env_harness.py` | Consolidates the four live environments behind a common API: `EnvSpec` + factories (`make_linear_env`, `make_regime_shift_env`, `make_nonlinear_env`, `make_latent_env`), `run_env_single_seed`, and `run_suite`. Computes per-seed and aggregate SHD / precision / recall / F1 / confidence / false-edge-count metrics. |
| `src/aac/nonlinear_intervention_env.py` | Generalized to degree-2 polynomial parent effects with both linear and quadratic terms, making the nonlinear relationship more realistic and recoverable by `likelihood_mode="poly2"`. |
| `src/aac/latent_confounder_env.py` | Added `n_nodes` and `ground_truth_edges` aliases so it matches the harness API. |
| `src/aac/interactive_discovery_loop.py` | `InteractiveDiscoveryLoop.environment` annotation relaxed to `Any` so it can accept any harness-compatible env. |
| `experiments/live_env_suite.py` | Multi-seed sweep runner across seeds 0..9 for all four env families. Emits `experiments/live_env_suite.result.json`. |
| `experiments/live_env_suite.result.json` | Example 10-seed sweep artifact. |
| `tests/test_live_env_harness.py` | 8 tests: factory creation, single-seed runner, suite structure, determinism for fixed seeds. |

## Bounded Adaptive Optimization (2026-07-08)

| File | Role |
|------|------|
| `src/aac/change_point_detector.py` | `MeanDriftDetector`: lightweight standardized mean-drift detector between consecutive observation batches. Used by the online loop to trigger a posterior reset when a regime shift is detected. |
| `src/aac/interactive_discovery_loop.py` | Extended `OnlineInteractiveDiscoveryLoop` with `change_point_detector` (posterior reset on drift) and `min_edge_marginal` (removes low-confidence edges from the MAP DAG as a conservative orientation guard). |
| `src/aac/live_env_harness.py` | Added `run_suite_adaptive`: sweeps with change-point reset enabled for `regime_shift` and marginal filtering enabled for `latent`. |
| `experiments/live_env_suite_adaptive.py` | Adaptive 10-seed sweep runner. Emits `experiments/live_env_suite_adaptive.result.json`. |
| `experiments/live_env_suite_adaptive.result.json` | Example adaptive sweep artifact. Latent-confounder mean SHD improved from 1.9 to 1.0 and false-edge count from 1.2 to 0.3 with marginal filtering; regime-shift remained stable. |
| `tests/test_adaptive_discovery_loop.py` | 6 tests: drift/no-drift detection, empty-batch safety, change-point reset does not hurt (and can help) regime-shift recovery, marginal filtering reduces false edges under latent confounding, moderate threshold keeps true edges in some seeds. |

## Real-Data Intervention Binding Protocol (2026-07-09)

| File | Role |
|------|------|
| `docs/adr/ADR-0052-real-data-intervention-binding-protocol.md` | Accepted ADR with RR-0029 §5 architecture-theory review. Defines the protocol, claim class, channel map, control/consumption path, C6/C7/SD4 boundary, product/process boundary, and failure modes. |
| `src/aac/real_data_intervention_env.py` | `RealDataInterventionEnv` protocol + `GovernedInterventionBinding` C7 wrapper. Enforces allowed-handle whitelist, forbidden nodes/edges, value ranges, budget, dry-run default, mandatory external approval for live mode, and audit callback. |
| `tests/test_real_data_intervention_env.py` | 10 tests: observe pass-through, dry-run does not call actuator, forbidden/disallowed handles blocked, value out-of-range blocked, live path requires approval, live path applies when approved, budget exhausted blocks, readback missing logged, SHD pass-through. |

## Real-Data Adapter Examples and Ground-Truth-Free Metrics (2026-07-09)

| File | Role |
|------|------|
| `docs/adr/ADR-0053-real-data-adapter-examples-and-evaluation-metrics.md` | Accepted ADR with RR-0029 §5 architecture-theory review. Authorizes CSV/HTTP/queue adapters and `predictive_validation_score` / `interventional_agreement_score` metrics. |
| `docs/research/founder-cast-2026-07-09-live-adapter-examples.md` | Founder cast authorizing the adapter examples and metrics under dry-run-by-default and approval-gated live mode; forbids production connectors. |
| `adapters/csv_adapter.py` | CSV adapter: reads observations from CSV, logs intervention requests, optionally reads back samples from a second CSV. Pure stdlib. |
| `adapters/http_adapter.py` | HTTP webhook adapter: GET observations as JSON, POST intervention proposals, parse JSON read-back. Pure stdlib. |
| `adapters/queue_adapter.py` | Queue adapter: reads observations from `queue.Queue`, publishes requests to a request queue, consumes read-back samples. For local harnesses. |
| `src/aac/cwm_evaluation.py` | Ground-truth-free metrics: `predictive_validation_score` fits linear models implied by predicted DAG and scores held-out interventions vs a marginal-mean baseline; `interventional_agreement_score` compares empirical intervention shifts to model-predicted shifts. |
| `tests/test_csv_adapter.py` | 4 tests: observe last-n rows, intervention logging, read-back lookup, SHD with ground truth. |
| `tests/test_http_adapter.py` | 3 tests: observe JSON parse, POST intervention and sample parse, HTTP error returns `None`. |
| `tests/test_queue_adapter.py` | 3 tests: observe drain, request/read-back round-trip, timeout returns `None`. |
| `tests/test_cwm_evaluation.py` | 3 tests: true DAG beats empty DAG on predictive validation, true DAG improves interventional agreement, empty data returns `None`. |

## End-to-End Adapter Harness (2026-07-09)

| File | Role |
|------|------|
| `experiments/live_adapter_loop_harness.py` | Closed-loop harness: `OnlineInteractiveDiscoveryLoop` → `GovernedInterventionBinding` → `QueueInterventionAdapter` or `CSVInterventionAdapter` → `CausalSimulationEnv` (as external simulator). A worker thread applies interventions in the simulator and returns samples. After the run, `predictive_validation_score` and `interventional_agreement_score` score the predicted DAG without ground truth. |
| `tests/test_live_adapter_loop_harness.py` | 3 tests: queue harness runs and produces metrics, CSV harness runs and produces metrics, CSV harness actually consumes read-back samples. |
| `experiments/live_adapter_loop_harness.result.json` | Example output from running both harness variants on a 4-node chain with default seeds. |

## Bayesian DAG Posterior (Governed DiBS + nonlinear likelihood, 2026-07-05)

| File | Role |
|------|------|
| `src/aac/bayesian_dag_posterior.py` | **Governed DiBS** per M-GAP-2 Algorithm 1. Pure stdlib, n <= 15 nodes. Two classes: `BayesianDAGPosterior` (legacy) and `GovernedDiBS` (full version). Features: C7 constraints (`forbidden_edges`, `forbidden_parents`), credit-weighted prior (organ proposal agreement bonus), SVGD-style gradient-informed particle updates with RBF kernel over Hamming distance, BOED Expected Information Gain via nested Monte Carlo, posterior entropy, organ credit attribution. **Nonlinear likelihood**: `likelihood_mode="poly2"` — degree-2 polynomial feature expansion + OLS captures sigmoidal/quadratic/interaction effects. Posterior temperature parameter prevents mode collapse on real data. |
| `tests/test_bayesian_dag_posterior.py` | 83 tests: DAG utilities, C7 constraints, credit-weighted prior, gradient-informed perturb, RBF kernel, SVGD convergence, BOED/EIG, organ credit attribution, backward-compatible BDP, nonlinear poly2 likelihood, poly2 GovernedDiBS convergence/safety, data generation. |
| `experiments/sachs_dibs.py` | Sachs real-data GovernedDiBS validation: 11 proteins, 17 GT edges, loads+standardizes obs data, runs linear vs poly2 comparison, measures edge recovery metrics, tests Bayesian safety (confident-wrong). Result: poly2 F1=0.35 vs linear F1=0.26, 7/17 vs 5/17 true edges recovered. |
| `experiments/sector_dibs.py` | S&P 500 sector ETF causal discovery: 11 sectors (XLB..XLY), loads daily returns from CSV, runs GovernedDiBS with known economic sector priors (7 edges). Financial returns have low SNR for observational causal discovery → Bayesian uncertainty confirmed. |

## Multi-Seed Sachs CWM Benchmark Harness (2026-07-08)

| File | Role |
|------|------|
| `experiments/cwm_sachs_multiseed.py` | Deterministic multi-seed Sachs benchmark harness for the CWM discovery pipeline. Loads Sachs observational data, runs an observational GGM+DiBS baseline against a causal arm with offline simulated interventions using the consensus biology DAG. Reuses `ProductDiscoveryEngine`, `GovernedDiBS`, `CWMOrgan` utilities, and existing BOED/EIG intervention selection in `GovernedDiBS`. Outputs per-seed and aggregate F1/recall/precision causal advantage to `experiments/cwm_sachs_multiseed.result.json`. Verify-only: no live control-path inference. |
| `experiments/cwm_sachs_multiseed.result.json` | Example multi-seed benchmark artifact (budget=6, seeds=[100..104], linear likelihood). |
| `tests/test_cwm_sachs_multiseed.py` | 8 tests: Sachs data loading, ground-truth consistency, linear SCM oracle simulation, baseline and causal metric shapes, seed comparison shape, multi-seed aggregate schema. |

## Source Of Truth

| File | Role |
|---|---|
| `docs/CURRENT_STATE.yaml` | Machine-readable current state, read order, latest tests, active gate |
| `docs/P6-research-synthesis.md` | P6 synthesis package: claim ledger, negative-result map, mechanism lineage, reproducibility appendix, publication outline |
| `docs/P6-no-gate2-hold-brief-20260703.md` | Minimal founder/CTO decision brief for why research remains at `No Gate-2` and what kind of authorization could legitimately change that state |
| `docs/P6-adr0031-prereg-hash-drift-audit-20260703.md` | Drift audit showing that ADR-0031 historical authority is preserved, but the current worktree result/code/doc prereg-hash lineage is split and therefore not fresh verification |
| `docs/P6-research-next-hold-decision-20260704.md` | Historical recorded decision that `RESEARCH_NEXT: HOLD`; later superseded only for `G-ECO-REOPEN-1` packet preparation |
| `../docs/research/founder-decision-2026-07-04-reopen-g-eco.md` | Founder cast superseding HOLD only for `RESEARCH_NEXT: REOPEN_G_ECO_PACKET`; old VH/G-Eco halt remains binding |
| `../docs/research/G-ECO-REOPEN-1-foundational-problem-lock-2026-07-04.md` | Fresh-variant problem lock for the reopened G-Eco route; authorizes architecture-theory review only |
| `../docs/research/architecture-theory-review-G-ECO-REOPEN-1-2026-07-04.md` | RR-0029 review for G-ECO-REOPEN-1; machine architecture-review accepted before freeze |
| `docs/adr/ADR-0039-g-eco-reopen-1-nonbijective-stake-channel.md` | Accepted founder ADR for the one fresh NBSC attempt; result closed NOT_MET |
| `../docs/research/formal-model-spec-G-ECO-REOPEN-1-2026-07-04.md` | Frozen formal model spec bound into prereg lock |
| `../docs/research/algorithm-spec-G-ECO-REOPEN-1-2026-07-04.md` | Frozen algorithm spec bound into prereg lock |
| `../docs/research/implementation-cast-G-ECO-REOPEN-1-2026-07-04.md` | Implementation cast for the four NBSC code/test files |
| `../docs/research/G-ECO-REOPEN-1.PREREG-DRAFT-2026-07-04.yaml` | Frozen preregistration source; lock in `.agent_runs/geco-reopen-2026-07-04/prereg.lock` |
| `../docs/research/G-ECO-REOPEN-1-seed-allocation-2026-07-04.json` | Fresh seed allocation bands 7400..7629; r-final used 7500..7529 once |
| `../docs/research/G-ECO-REOPEN-1-rfinal-report-2026-07-04.md` | R-final report: NOT_MET, fair MINIMAX absorbs candidate probe path |
| `../docs/research/architecture-lesson-G-ECO-REOPEN-1-2026-07-04.md` | Negative architecture lesson from G-ECO-REOPEN-1 |
| `../docs/research/paradigm-learning-G-ECO-REOPEN-1-2026-07-04.md` | Loop learning record for the failed NBSC route |
| `../docs/research/route-product-projection-update-G-ECO-REOPEN-1-2026-07-04.md` | Route/product projection update: no product projection |
| `../.agent_runs/geco-reopen-2026-07-04/independent-review-019f2bc8-80ff-7fa3-8206-0bd9a7e586a2.md` | Run-local read-only independent review; `ACCEPT_FOR_SPEC`, no implementation/freeze/run |
| `../.agent_runs/geco-reopen-2026-07-04/cli-review-attempts-2026-07-04.md` | Run-local CLI review attempt log; runner review remains blocked by missing RR-0031 reviewer calibration and absent mechanism files |
| `docs/PROJECT_PLAN.md` | Human handoff plan and task cards |
| `ROADMAP.md` | Phase ledger and gate sequence |
| `ENGINEERING.md` | Engineering and experiment discipline, especially statistical rules |
| `AGENTS.md` | Agent rules and non-negotiable boundaries |
| `docs/PRD.md` | Four core claims |
| `docs/adr/` | Preregistered decisions and gate results |
| `../docs/research/RR-0001..0005` | Cross-repo research constitution and falsification record |

## Recent ADR Index

| ADR | Status | Meaning |
|---|---|---|
| `ADR-0020-g7-latent-regime-organ.md` | NOT MET | O4 beats O1 but not O2 at required dominance |
| `ADR-0021-p1-spectrum-ablation.md` | Implemented | O4 spectrum/ablation strengthening |
| `ADR-0022-g8-ensemble-regime-organ.md` | NOT MET | O5 ensemble did not improve over O4 |
| `ADR-0023-g9-confidence-gated-policy.md` | Accepted, implemented, formal NOT MET | P0 gate-alone decisive discovery; P4 preregistered candidate failed |
| `ADR-0024-g10-subject-side-win-confirmation.md` | MET | Fresh-seed confirmation of P0; first decisive positive gate |
| `ADR-0025-system-level-autonomy-signature-gate.md` | Route accepted, parked by ADR-0027 | G11 system-level vector gate needs a second independent winning axis |
| `ADR-0026-c3-idle-productivity-de-risk.md` | RED | Endogeny axis has no directed signal; dropped from C1 |
| `ADR-0027-post-c3-route-disposition.md` | Accepted | Consolidate G10; park G11/C1 until another axis wins |
| `ADR-0028-survival-axis-de-risk.md` | RED | Survival-under-cost is not independent; it shadows reframe/adaptation speed |
| `ADR-0029-risk-calibration-axis-de-risk.md` | RED | Stationary risk calibration not improved by the gate; cheap broad explorer wins |
| `ADR-0030-g10-completeness-trap-avoidance.md` | COMPLETENESS PASS | G10/P0 survives fixed-low-temp, metric, real-stake, structure-theft, and spectrum traps |
| `ADR-0031-prediction1-residual-calibrator-vs-g10.md` | PRED1-HOLDS | Residual self-calibrator did not beat frozen G10; RR-0019 Claim 1/3 survived the attack |
| `ADR-0032-frontier-architecture-intake-and-structured-env-route.md` | Accepted | Frontier systems enter only through classified lanes/channels; structured environments are the next admissible experiment family |
| `ADR-0033-hyperagents-dgm-assimilation-boundary.md` | Accepted | HyperAgents/DGM-style systems are external candidate generators only; runtime self-modification remains forbidden |
| `ADR-0034-relevance-aware-g10-theory-test.md` | Completed | Full-Agent B/R/K test: PRED-A/C pass, PRED-B fail; RSTAR explains part but not most of the old margin |
| `ADR-0035-p7-ecological-environment-axis.md` | Completed, inconclusive | P7/G12 mixed pattern; C01/C10/C11 win, C00 misses threshold, so no distinct ecological-irreversible axis isolated |
| `ADR-0036-bounded-consequence-prior-gate.md` | Completed, NOT MET | G13 tested a belief-only bounded consequence prior over P0 for scar-specific irreversible benefit |
| `ADR-0037-self-determination-depth-vs-corrigibility.md` | Proposed, docs-only / OPEN | Registers SD0-SD4 and the open SD4-separability question; parent SD4 VAL-DISENT-1 read-out adds negative H1 evidence but does not decide the ADR |
| `ADR-0038-g-eco-mechanism-lower-half.md` | Accepted, lower-half implemented + F1-F6 discipline fixes + hardened pre-Gate-2 candidate writer/verifier | G-Eco mechanism substrate/env/arms/refs/guards plus candidate rates/battery/threshold/audit JSON writer, calibration-selected VH parameter provenance, recursive AST static firewalls, calibration-ref-only rate witness, C3 verdict-mechanics leaves, and integrity/firewall verifier; current VH/G-Eco operationalization is PARK_BY_§7A_C_NOT_SUPPORTED; no co-signed freeze, no r-final, no verdict |
| `ADR-0039-g-eco-reopen-1-nonbijective-stake-channel.md` | Accepted, completed NOT_MET | Fresh NBSC reopen attempt; r-final seeds 7500..7529 show fair MINIMAX matches candidate probe path, so no distinct mechanism |
| `ADR-0038-g-eco-mechanism-lower-half.md` | Accepted, lower-half implemented + F1-F6 discipline fixes + hardened pre-Gate-2 candidate writer/verifier | G-Eco mechanism substrate/env/arms/refs/guards plus candidate rates/battery/threshold/audit JSON writer, calibration-selected VH parameter provenance, recursive AST static firewalls, calibration-ref-only rate witness, C3 verdict-mechanics leaves, and integrity/firewall verifier; no co-signed freeze, no r-final, no verdict |
| `ADR-0039-viability-empowerment-c1-formalization.md` | Proposed (open, founder-reserved); landed 2026-06-29 from branch | Viability/empowerment formalization of C1 + preregistered S1/S2 gate; not accepted, not funded, not run |

## Current Code Map

| Path | Role | Key symbols |
|---|---|---|
| `src/aac/viability.py` | Viability core | `ViabilityCore` |
| `src/aac/world_model.py` | Action-outcome belief and uncertainty | `ActionOutcomeModel` |
| `src/aac/policy.py` | EFE policy plus G9 confidence gate | `PolicySelector` |
| `src/aac/agent.py` | Main loop wiring, shell view, optional prior organ, policy gate | `Agent` |
| `src/aac/shell.py` | Corrigibility shell and read-only view | `CorrigibilityShell`, `ShellView` |
| `src/aac/self_model.py` | Agent capability/risk/boundary self-knowledge | `AgentSelfModel`, `ActionRequest` |
| `src/aac/self_model_updater.py` | **E6** runtime self-model calibration from governed outcomes | `AgentSelfModelUpdater` |
| `src/aac/organ_regulator.py` | **C7-on** credit-driven organ de-weighting and self-calibration | `OrganRegulator`, `OrganCredit` |
| `src/aac/self_maintenance.py` | **E9** governed persistence self-production loop under C7 | `SelfMaintenanceLoop`, `HealthCheck`, `MaintenanceAction` |
| `src/aac/audit.py` | Append-only audit chain | `AuditLog` |
| `src/aac/prior_organ.py` | P4 belief-only organ interface | `PriorOrgan`, `OrganAdvice`, `BeliefSnapshot`, `merge_organ_advice` |
| `src/aac/prior_organ_o1.py` | Cheap deterministic reset scaffold | `ResetScaffoldOrgan` |
| `src/aac/prior_organ_o2.py` | Adaptive hazard organ, G5 archived | `AdaptiveHazardOrgan` |
| `src/aac/prior_organ_library.py` | Regime library organ, G6a | `RegimeLibraryOrgan` |
| `src/aac/prior_organ_latent.py` | Bayesian latent regime organ, G7/O4 | `LatentRegimeOrgan` |
| `src/aac/prior_organ_ensemble.py` | Ensemble regime organ, G8/O5 | `EnsembleRegimeOrgan` |
| `src/aac/prior_organ_llm.py` | LLM organ scaffold, no live key/control path | `LLMPriorOrgan`, `DeterministicStubBackend` |
| `src/aac/consequence_prior.py` | ADR-0036 bounded consequence-prior organ and cheap CAUTIOUS control | `ConsequencePriorRecord`, `BoundedConsequencePriorOrgan`, `CautiousScarOrgan` |
| `src/aac/causal_governed_bandit.py` | M-GAP-3 causal governed bandit: Thompson sampling from DiBS posterior, peril-modulated exploration (gamma = gamma0*(1-peril)), C7+D constrained arm selection, cumulative/governance regret tracking, UCB1 baseline for comparison | `CausalBanditArm`, `CausalGovernedBandit`, `ucb1_baseline` |
| `src/aac/bayesian_dag_posterior.py` | **Governed DiBS** per M-GAP-2 Algorithm 1. Pure stdlib, n <= 15 nodes. `BayesianDAGPosterior` (legacy), `GovernedDiBS` (C7, credit-weighted prior, SVGD+RBF kernel, BOED, poly2 nonlinear likelihood, posterior temperature). | |
| `tests/test_causal_governed_bandit.py` | 33 tests: arm construction, peril kernel, Thompson sampling, causal effect estimation, information gain, reward/update/regret, C7 governance, UCB1 baseline. | |
| `src/aac/g_eco.py` | ADR-0038 G-Eco lower-half shared substrate, value aggregators, frozen-source battery adapters, truth-privileged cheat refs, metrics, pre-Gate-2 candidate freezes, content-hash verifier, recursive AST static firewalls, calibration-ref-only rate witness, audit guards, Gate-2 guards | `GEcoSharedSubstrate`, `GEcoArm`, `GEcoArmSource`, `GEcoVHParams`, `build_g_eco_arms`, `scan_rate_grid`, `select_vh_parameters`, `freeze_battery_parameters`, `derive_threshold_freeze`, `build_baseline_audit`, `verify_content_hash`, `assert_g_eco_static_firewalls`, `assert_static_firewall`, `assert_no_calibration_refs_in_rfinal`, `GEcoMetrics` |
| `src/aac/g_eco_reopen.py` | ADR-0039/G-ECO-REOPEN-1 NBSC battery, fair cheap baselines, seed guards, static C6/C7 scanner, and adjudicator | `build_nbsc_battery`, `run_nbsc_battery`, `adjudicate_nbsc_result`, `finalize_locked_nbsc_result`, `assert_fresh_seed_allocation`, `assert_c6_c7_static_boundary` |
| `src/aac/rap.py` | RAP field/messages, archived after G4 | `Need`, `Bid`, `Bond`, `Trace`, `Dissolve`, `RAPField` |
| `src/aac/rap_coordinator.py` | RAP coordinator, archived after G4 | `RAPCoordinator` |
| `src/aac/outcome_judge.py` | Grounded RAP outcome judge | `OutcomeJudge` |
| `src/aac/idle_drives.py` | Idle endogenous drives, G3/C3 input | `IdleDrives` |
| `src/aac/residual_calibrator.py` | ADR-0031 subject-side belief calibrator | `ResidualCalibrator` |
| `src/aac/commitment_ledger.py` | R-CSL-1 no-model commitment-ledger mechanism (preserved-failed-baseline; builder!=reviewer separation enforced in its harness) | `CommitmentLedgerPolicy` |
| `src/envs/structured_regime.py` | Reusable structured regime env for G6/G7/G8/G9/G10 | `StructuredRegimeEnv` |
| `src/envs/staleness.py` | P4 staleness-only environment | `StalenessEnv` |
| `src/envs/semantic_regime.py` | Offline semantic de-risk env | `SemanticRegimeEnv` |
| `src/envs/idle_windows.py` | Idle window wrapper used by C3 | `IdleWindowEnv` |
| `src/envs/ecological_regime.py` | ADR-0035/G12 2x2 environment cells | `EcologicalRegimeEnv` |
| `src/envs/consequence_scar.py` | ADR-0036/G13 public-affordance scar environment | `ConsequenceScarEnv`, `ConsequenceFeature` |
| `src/envs/ecological_4cond.py` | ADR-0038 G-Eco four-condition environment with partial/lagged/noisy observation; no rate-grid scan or divergence detector | `Ecological4CondEnv`, `GEcoState`, `GEcoRates`, `GEcoObservation`, `transition_state` |
| `src/envs/geco_nonbijective_stake.py` | ADR-0039 NBSC hidden-basin environment with public probe action and non-bijective visible stake | `NonBijectiveStakeEnv`, `NBSCState`, `NBSCObservation`, `NBSCOutcome` |
| `src/envs/commitment_correction.py` | R-CSL-1 commitment/correction environment | `CommitmentCorrectionEnv`, `CorrectionSignal` |

## Current Experiments

| Path | Gate | Status |
|---|---|---|
| `experiments/svar_scm.py` | AGDE-T3 | SVAR trajectory arena for temporal active-discovery pilots; contemporaneous MEC × lag-support pool with window-clamp interventions |
| `experiments/agde_t3_pilot.py` | AGDE-T3 pilot v1/v2 | Calibration-only apparatus pilot; exact fixed-point clamp predictor after v1 caught truth-self-survival bug |
| `experiments/agde_t3_costgap.py` | AGDE-T3 pilot v3 | Calibration-only cost/gap pilot; exposed insufficient arena separation before freeze |
| `experiments/agde_t3_separation.py` | AGDE-T3 pilot v4 | Calibration-only separation measurement; diagnosed nested lag-superset equivalence / causal-minimality issue |
| `experiments/agde_t3_pilot5.py` | AGDE-T3 pilot v5 | Calibration-only causal-minimality collapse pilot; v5 inputs make T3 freeze-packet-ready, no verdict |
| `experiments/agde_t3_pilot5.result.json` | AGDE-T3 pilot v5 | Calibration result schema; `do_value=3.2`, `budget=4` gives active_id 0.750 vs random_id 0.417 on calib families |
| `tests/test_agde_t3_pilot5.py` | AGDE-T3 pilot v5 | Guards explicit minimality collapse and calibration-only / no-freeze result schema |
| `docs/pre_spec/AGDE-T3.PREREG-2026-07-04.md` | AGDE-T3 fresh scored gate | Frozen inputs and mechanical result; scored NULL on fresh families, controls pass, no rescue/re-cut |
| `experiments/agde_t3_freeze.py` | AGDE-T3 fresh scored gate | Uses v5 inputs with fresh families, ACTIVE/RANDOM/BLIND_CEILING arms, C7 halt guard, bounded result schema |
| `experiments/agde_t3_freeze.result.json` | AGDE-T3 fresh scored gate | Fresh scoring artifact: ACTIVE 0.5000, RANDOM 0.2083, BLIND_CEILING 0.5000, verdict NULL |
| `tests/test_agde_t3_freeze.py` | AGDE-T3 fresh scored gate | Guards frozen constants, calibration-family exclusion, paused-shell zero-intervention behavior, and non-claim schema |
| `docs/pre_spec/5E-2.ZERO-SHOT-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 zero-shot calibration | Records no freeze-ready region: zero-shot signal exists near n=38/40, but cheap screening does not collapse enough |
| `experiments/cwm_learn_5e2.py` | CWM-LEARN-5e-2 zero-shot calibration | Calibration-only runner using frozen data-blind 5e union before data; compares later-data screening, random, and oracle across train-size sweep |
| `experiments/cwm_learn_5e2.result.json` | CWM-LEARN-5e-2 zero-shot calibration | Calibration artifact for n_train 30/36/38/40/60/80; all candidate_freeze_region=false |
| `tests/test_cwm_learn_5e2.py` | CWM-LEARN-5e-2 zero-shot calibration | Guards frozen proposal source, no-claim schema, later-data screening arm, and train-size restoration |
| `docs/pre_spec/5E-2.FORMS-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 functional-forms calibration | Records typed forms signal with clean Condition-B collapse, but no freeze-ready region because pair screening remains high |
| `experiments/cwm_learn_5e2_forms.py` | CWM-LEARN-5e-2 functional-forms calibration | Calibration-only non-enumerable form runner: threshold/saturation/ratio proposals vs finite pair-product screening, random forms, oracle, and Condition-B |
| `experiments/cwm_learn_5e2_forms.result.json` | CWM-LEARN-5e-2 functional-forms calibration | Calibration artifact: proposed forms median_s=1.0000, pair-screening median_s=0.7823, Condition-B collapse ok, candidate_freeze_region=false |
| `tests/test_cwm_learn_5e2_forms.py` | CWM-LEARN-5e-2 functional-forms calibration | Guards typed non-pair form specs, finite feature expansion, bounded no-claim schema, Condition-B control, and pair-screening comparison |
| `docs/pre_spec/5E-2.HARD-FORMS-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms calibration | Records freeze-candidate bandpass arena: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse ok |
| `experiments/cwm_learn_5e2_forms_hard.py` | CWM-LEARN-5e-2 hard functional-forms calibration | Calibration-only bandpass-product form arena that breaks finite pair-product proxies while preserving typed-form verifier health |
| `experiments/cwm_learn_5e2_forms_hard.result.json` | CWM-LEARN-5e-2 hard functional-forms calibration | Calibration artifact for seeds 30..33; candidate_freeze_region=true, not a verdict |
| `tests/test_cwm_learn_5e2_forms_hard.py` | CWM-LEARN-5e-2 hard functional-forms calibration | Guards bandpass-form arena, bounded no-claim schema, and smoke seed pair-proxy gap |
| `docs/pre_spec/5E-2.HARD-FORMS-FRESH-SCORED-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Records disjoint-seed fresh scored MET for hard bandpass forms; not r-final and no autonomy/product/C6-C7 claim |
| `experiments/cwm_learn_5e2_forms_hard_freeze.py` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Uses frozen hard-form arena with calibration seeds 30..33 and fresh scoring seeds 40..45; mechanical MET/NULL/INVALID verdict |
| `experiments/cwm_learn_5e2_forms_hard_freeze.result.json` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Fresh scored artifact: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse, verdict MET |
| `tests/test_cwm_learn_5e2_forms_hard_freeze.py` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Guards disjoint seeds, Condition-B invalidation, no-claim schema, and verdict domain |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL.PREREG-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms r-final | Preregistered seeds, decision rule, lock scope, and non-claim boundaries for the hard non-enumerable form channel |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL.lock.json` | CWM-LEARN-5e-2 hard functional-forms r-final | SHA-256 lock binding prereg, hard-form mechanism runner, r-final runner, and r-final tests before r-final execution |
| `experiments/cwm_learn_5e2_forms_hard_rfinal.py` | CWM-LEARN-5e-2 hard functional-forms r-final | Lock-verified r-final runner for seeds 60..69; emits MET/NULL/INVALID with bounded non-claim schema |
| `experiments/cwm_learn_5e2_forms_hard_rfinal.result.json` | CWM-LEARN-5e-2 hard functional-forms r-final | R-final artifact: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse, verdict MET |
| `tests/test_cwm_learn_5e2_forms_hard_rfinal.py` | CWM-LEARN-5e-2 hard functional-forms r-final | Guards disjoint seed bands, prereg lock drift refusal, bounded r-final schema, and non-claim fields |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL-RESULT-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms r-final | Human result record and route decision: continue only through scale/cross-domain transfer, governed seam-lane design, or park |
| `experiments/confidence_gated_g9.py` | G9 | Implemented and run; formal NOT MET, P0 discovery positive |
| `experiments/confidence_gated_g10.py` | G10 | MET on fresh seeds 800..829 |
| `tests/test_confidence_gated_g10.py` | G10 | Exists; C6/C7 and determinism guards |
| `experiments/completeness_g10.py` | ADR-0030 | COMPLETENESS PASS; P0 survives flip-the-conclusion traps |
| `tests/test_completeness_g10.py` | ADR-0030 | additive `base_temperature` wiring and B-temp guard |
| `experiments/prediction1_residual_calibrator.py` | ADR-0031 | PRED1-HOLDS; residual calibrator vs frozen G10 |
| `tests/test_residual_calibrator.py` | ADR-0031 | calibrator math, default-off wiring, C6/C7 guards |
| `tests/test_self_model_updater.py` | **E6** | 16 tests: confidence calibration, tool reliability, evidence adjustment, full-action update, state roundtrip |
| `tests/test_organ_regulator.py` | **C7-on organ** | 20 tests: registration, credit update, effective weight, de-weight/reweight, self-calibration, state roundtrip |
| `tests/test_self_maintenance.py` | **E9** | 16 tests: health check, C7 compliance, maintenance ledger, maintainability gate, state roundtrip |
| `experiments/relevance_aware_g10.py` | ADR-0034 | Completed; RSTAR calibration + r-final B/R/K attribution |
| `tests/test_relevance_aware_g10.py` | ADR-0034 | severity/noise env, policy diagnostics, RSTAR freeze/r-final guards |
| `experiments/ecological_g12.py` | ADR-0035/G12 | Completed; P7 transferable ecological-structure 2x2 r-final |
| `tests/test_ecological_g12.py` | ADR-0035/G12 | 2x2 env, reset boundary, RSTAR control, cell-win guards |
| `experiments/consequence_prior_g13.py` | ADR-0036/G13 | Completed; development and one r-final harness |
| `experiments/consequence_prior_g13.development.json` | ADR-0036/G13 | Development audit artifact; scar screen PASS, gate preview NOT MET |
| `experiments/consequence_prior_g13.freeze.json` | ADR-0036/G13 | Founder unlock artifact for the one r-final |
| `experiments/consequence_prior_g13.result.json` | ADR-0036/G13 | R-final artifact; G13 NOT MET |
| `tests/test_consequence_prior_g13.py` | ADR-0036/G13 | CP interface, C6/C7, scar env, collapse, denominator, r-final guard tests |
| `experiments/direction1_rate_sensitivity.py` | Direction 1 pre-build cheap falsifier | Tracked rate-sensitivity scaffold only; digest-verifying CLI, no default seeds/freeze/r-final |
| `experiments/direction1_rate_sensitivity.spec.json` | Direction 1 exploratory input | Locked pre-build spec for FAST/DEFAULT/SLOW period cells and gated/fixed arm table |
| `experiments/direction1_rate_sensitivity.seeds.json` | Direction 1 exploratory input | Tracked not-r-final seed list for the 30-seed run-local sweep (`2400..2429`) |
| `experiments/direction1_rate_sensitivity.lock.json` | Direction 1 exploratory input | Run-local digest lock over spec, implementation, tests, and seed list |
| `experiments/direction1_rate_sensitivity.development.json` | Direction 1 exploratory artifact | 30-seed run-local readout; verdict `NO_NEW_DIRECTION_1_MECHANISM`, not an ADR/prereg/freeze/r-final artifact |
| `tests/test_direction1_rate_sensitivity.py` | Direction 1 pre-build cheap falsifier | Spec surface, digest-verifying CLI, result-schema, and C6/C7 guard tests |
| `experiments/g_eco.py` | ADR-0038/G-Eco + r-final harness | Lower-half smoke/mechanism-check + `pregate2-candidates`/`pregate2-verify` + `gate2-cosign`. r-final harness: `assert_gate2_unlocked` (founder-cosign-gated verifier), `run_rfinal` (faithful frozen-candidate replay -> RAW only, C6/C7 + Stage-2 prereg.lock double-bind), `verify_prereg_lock` (mechanism-code drift gate), `build_adjudication_packet` + `verify_adjudication_integrity` (kimicode handoff + Claude verify-and-narrate incl. gate-4 Wilcoxon/bootstrap). freeze/r-final/verdict CLI still refuse; verdict is kimicode's |
| `tests/test_g_eco.py` | ADR-0038/G-Eco | Shared substrate, r-final cheat-ref firewall, truth-state separation, frozen-source battery adapters, de-complete observation, active lookahead, VH_noStake, deterministic replay, reset boundary, calibration-selected VH params, recursive static firewalls, C3 verdict-mechanics leaves, pre-Gate-2 candidate writer/verifier/audit guards, C6/C7, Gate-2 refusal guards |
| `tests/test_gate2_unlock.py` | G-Eco r-final harness | Gate-2 unlock verifier: locked-by-default, founder co-sign exact-bytes binding, audit-halt/incomplete, seed-band, tamper guards |
| `tests/test_rfinal_runner.py` | G-Eco r-final harness | run_rfinal: refuses-when-locked, faithful-replay drift, RAW-only no-verdict, determinism, C6/C7 (multi-seed, non-acting-arm rejected) |
| `tests/test_adjudication.py` | G-Eco r-final harness | Packet assembly + verify-and-narrate integrity (fabrication/non-frozen-theta/ragged-rows/alpha-drift caught); gate-4 Wilcoxon+bootstrap known-answers |
| `tests/test_prereg_lock.py` | G-Eco r-final harness Stage-2 | prereg.lock double-bind: no-lock-not-ready, verified-lock-ready, mechanism drift / traversal / non-object / missing rejected |
| `experiments/g_eco_reopen_1.py` | ADR-0039/G-ECO-REOPEN-1 | Smoke / r-final / adjudication CLI; r-final requires prereg lock, source spec, seed-allocation lock coverage; result NOT_MET |
| `tests/test_g_eco_reopen_1.py` | ADR-0039/G-ECO-REOPEN-1 | NBSC env tests, fair MINIMAX, fresh seed allocation, static C6/C7 scanner, prereg metrics, final result hash coverage, NOT_MET overlap guard |
| `experiments/idle_productivity_c3.py` | C3 | RED; DIRECTED/RANDOM/POLICY statistically indistinguishable |
| `tests/test_idle_productivity_c3.py` | C3 | determinism and C6/C7 guards |
| `experiments/survival_axis_c1.py` | ADR-0028 | RED; survival shadows adaptation speed |
| `tests/test_survival_axis_c1.py` | ADR-0028 | determinism, arm wiring, C6/C7 guards |
| `experiments/risk_calibration_c1.py` | ADR-0029 | RED; no independent stationary risk advantage |
| `tests/test_risk_calibration_c1.py` | ADR-0029 | deterministic risk-env and C6/C7 guards |
| `experiments/ensemble_regime_g8.py` | G8 | NOT MET |
| `experiments/latent_regime_g7.py` | G7 | NOT MET |
| `experiments/structured_g6a.py` | G6a | MET |
| `experiments/semantic_g6b_offline.py` | G6b de-risk | semantic-exploitable YES, live LLM parked |
| `experiments/prior_organ_g5.py` | G5 | NOT MET |
| `experiments/rap_g4.py` | G4 | NOT MET, RAP archived |
| `experiments/metabolic_g3.py` | G3 | NOT MET overall; claim 1 supported |
| `experiments/causal_relevance_g2.py` | G2 | NOT MET, claim 2 hard-stopped |
| `experiments/sachs_dibs.py` | M-GAP-2 | Sachs GovernedDiBS validation: poly2 F1=0.35 vs linear F1=0.26 |
| `experiments/sector_dibs.py` | M-GAP-2 | S&P 500 sector ETF causal discovery: Bayesian uncertainty confirmed |
| `experiments/r_csl_1.py` | R-CSL-1 | Preserved-failed-baseline no-model commitment-ledger mechanism + harness; preregistered, NOT run (landed 2026-06-29 from probe branch) |
| `experiments/direction1_coupling_sweep.py` | Direction-1 | confidence->temperature coupling falsifier; FLAT / record-and-stop (max frozen-vs-best gap 3.3%) |
| `experiments/parity_lag_falsifier.py` | parity-lag | structural-vs-artifact falsifier; INCONCLUSIVE (kimicode flagged the clean re-prereg as unfair-baseline OVERCLAIM) |
| `experiments/parity_lag_largelag_falsifier.py` | parity-lag | clean large-lag re-prereg; ARTIFACT (structural foreclosure refuted) |

## Current Tests

Current verification truth:

```text
Product Track on current branch: 166 passed, 1 skipped; Ruff clean; Pyright 0 errors
Whole-repository historical baseline from 2026-07-10, not rerun on this branch:
1321 passed, 14 skipped, 5 subtests passed
```

Important current test files:

| Path | Covers |
|---|---|
| `tests/product/test_e2_long_horizon_recovery.py` | bounded local `LH_PRODUCT_SLICE_E2` composition-root wait/rebind/compensation/C7 acceptance |
| `tests/product/test_public_long_horizon_negative_paths.py` | real HTTP/CLI long-horizon negative paths and durable store effects |
| `tests/product/test_rebind_partial_evidence_regression.py` | real execution partial-artifact filtering after authorized suffix rebind |
| `tests/test_confidence_gated_policy.py` | G9 policy gate, C6/C7 guards, deterministic replay |
| `tests/test_confidence_gated_g10.py` | G10 fresh-seed confirmation guards |
| `tests/test_completeness_g10.py` | G10 completeness additive temperature wiring |
| `tests/test_residual_calibrator.py` | ADR-0031 residual self-calibrator C6/C7 guards |
| `tests/test_relevance_aware_g10.py` | ADR-0034 severity env, policy diagnostics, RSTAR calibration/r-final guards |
| `tests/test_idle_productivity_c3.py` | C3 idle-productivity de-risk guards |
| `tests/test_consequence_prior_g13.py` | ADR-0036 bounded consequence-prior organ, scar env, r-final lock, collapse/denominator guards |
| `tests/test_g_eco.py` | ADR-0038 lower-half G-Eco mechanism, pre-Gate-2 verifier/recursive static-firewall hardening, and Gate-2 refusal guards |
| `tests/test_g_eco_reopen_1.py` | ADR-0039 NBSC reopen guard tests and NOT_MET cheap-baseline kill condition |
| `tests/test_survival_axis_c1.py` | ADR-0028 survival-axis de-risk guards |
| `tests/test_risk_calibration_c1.py` | ADR-0029 stationary risk-axis de-risk guards |
| `tests/test_prior_organ_ensemble.py` | G8 ensemble organ |
| `tests/test_prior_organ_latent.py` | G7/O4 latent regime organ |
| `tests/test_prior_organ_o1.py` | O1 reset scaffold |
| `tests/test_prior_organ_o2.py` | O2 adaptive hazard |
| `tests/test_prior_organ_llm.py` | LLM organ parser/scaffold, no trust boundary violation |
| `tests/test_rap_*` | RAP field/coordinator/baselines/G4 archived line |
| `tests/test_idle_drives.py` | Idle drives baseline and C3 input |

## G9/G10/C3 Truth

G9 frozen parameters:

```text
gate_kappa = 0.5
gate_temp_floor = 0.1
```

G9 r-final:

| Arm | Mean post-shift regret area |
|---|---:|
| A0 baseline + none | 1361.6 |
| A1 baseline + O1 | 1325.6 |
| A4 baseline + O4 | 1224.3 |
| P0 gated + none | 746.5 |
| P4 gated + O4 | 893.4 |

G9 verdict:

- Formal gate: **NOT MET** because P4 was preregistered and failed G9-2.
- Research finding: P0 gate-alone is decisive, C6-preserving, and beats A0/A1/A4.
- G10 confirmed P0 on fresh seeds 800..829:
  - A0 1304.7 / A1 1268.6 / P0 759.8.
  - P0 beats A1 by 40.1%, 30/30, p<1e-6, bootstrap CI [457.0, 562.9].
- ADR-0030 completeness strengthened G10:
  - B-temp fixed-low baseline 1292.9 window area vs P0 739.8.
  - T1 P0<B-temp 30/30, p<1e-6.
  - T3 real-stake survival PASS: P0 1734.8 vs A0 1245.3 and B-temp 1482.6.
  - T5b StalenessEnv PASS: P0 advantage 36.4%, GENERAL FIX not structure theft.
  - Interpretation: the subject-side belief-to-action coupling survives all flip-the-conclusion traps.
- ADR-0031 residual-calibrator attack returned PRED1-HOLDS:
  - frozen lambda/eta = 0.8 / 0.1; prereg hash f87c23a43d2e0abd0130cee1ffab34b5741018ec8376f291139c2a5928abc936.
  - P0 788.8 vs PR 793.3; PR margin -0.006, wins 13/30, p=0.550830, CI [-30.8, 19.0].
  - PR-B vs A1 margin -0.039, CI [-67.9, -32.6].
  - Interpretation: residual calibration is not an independent second axis over frozen G10.
- ADR-0034 relevance-aware G10 theory test returned PARTIAL:
  - RSTAR frozen on seeds 1400..1419 as base_temperature=0.03, inertia=0.25, surprise_gain=1.0.
  - r-final seeds 1500..1529: PRED-A PASS, PRED-B FAIL, PRED-C PASS.
  - Mild severity: P0 loses to RSTAR (adv -0.089), as predicted.
  - Severe/default: P0 beats RSTAR decisively (adv +0.235, 30/30, CI [495.7,605.3]).
  - share_R=0.373: relevance-aware exploration explains part, not most, of the old margin.
  - Interpretation: G10 empirical result preserved; trajectory account weakened to B/R/K with a decisive K residue.
- ADR-0035/G12 P7 ecological environment axis returned INCONCLUSIVE:
  - C00 thin/reversible: P0 adv vs RSTAR +0.175, 30/30, but below the +0.20 cell-win threshold -> no win.
  - C01 thin/irreversible: P0 win, adv +0.340, damage_adv +0.436.
  - C10 ecological/reversible: P0 win, adv +0.208.
  - C11 ecological/irreversible: P0 win, adv +0.300, damage_adv +0.340.
  - Mixed pattern C01/C10/C11 without C00 does not isolate a distinct ecological-irreversible axis.
  - Interpretation: record as inconclusive; no G12 retuning or G11/C1 revival.
- ADR-0036/G13 completed NOT MET:
  - Candidate `CP = P0 + bounded consequence prior`; baseline `P0-alone`.
  - It is not a G12 rescue. G12 remains inconclusive.
  - Gate requires irreversible/scarred benefit over P0, scar specificity versus reversible cells, stale-prior safety, and C6/C7 invariants.
  - Fresh seeds: development `1750..1769`, r-final `1800..1829`.
  - Implementation and development audit are complete:
    - `experiments/consequence_prior_g13.development.json` records the development run.
    - Scar validity screen PASS; CAUTIOUS capture is `0.470`, so the apparatus is not cheap-trivially avoided on development seeds.
    - R1 irreversible preview: `adv=+0.048`, `wins=14/20`, `p=0.00604`, `damage_adv=+0.434`.
    - R0 reversible preview: `adv=-0.274`, first-window `stale_prior_harm=13.094`, any reversible-cell harm seeds `17/20`; stale-prior guard fails.
  - R-final:
    - `experiments/consequence_prior_g13.freeze.json` records founder unlock.
    - `experiments/consequence_prior_g13.result.json` records the one r-final.
    - Scar validity screen PASS.
    - R1 irreversible: `adv=+0.083`, `wins=25/30`, `p=0.000001895`, CI `[291.66,589.94]`, `damage_adv=+0.463`.
    - R0 reversible: `adv=-0.255`, first-window `stale_prior_harm=12.679`, any reversible-cell harm seeds `21/30`.
    - Specificity PASS: contrast `+0.317`, CI lower `+0.150`.
    - CAUTIOUS captures `0.533` of CP's irreversible damage reduction.
    - Verdict: NOT MET. G13-1 and G13-3 fail; G13-2 and C6/C7 pass.
- C3 returned RED:
  - DIRECTED 1.691 / RANDOM 1.676 / POLICY 1.701.
  - Endogeny has no directed post-idle signal and is dropped from C1.
- ADR-0028 returned RED:
  - EXPLORER regret/budget 1.876 / 549.
  - EXPLOITER regret/budget 1.613 / 1709.
  - GATED regret/budget 1.048 / 2787.
  - Gated policy wins the measured metrics, but validity fails: survival is not independent of reframe/adaptation speed.
- ADR-0029 returned RED:
  - EXPLORER survival 1814 / EXPLOITER survival 1335 / GATED survival 1313.
  - GATED beats the best cheap arm in only 2/30 seeds, p=0.97, gap CI [-570, -321].
  - Stationary risk calibration is not an independent gate advantage.
- Next: do not rerun or retune G13. G-Eco lower-half plus F1-F6 discipline fixes and hardened pre-Gate-2 candidate writer/verifier exist on `feat/g-eco-pre-gate2-hardening`, but founder/CTO co-signed freeze, Gate-2, r-final, and verdict remain locked behind the parent Route C protocol and founder-reserved gates.

## Drift Prevention

When a gate, ADR, module, or test count changes, update:

1. `docs/CURRENT_STATE.yaml`
2. `docs/PROJECT_PLAN.md`
3. `codebase_index.md`
4. `ROADMAP.md` if phase/route changed
5. relevant ADR status/result section
6. root `../code_index.md` if workspace-level truth changed
7. root `../MEMORY.md` only as concise cross-agent memory

If these disagree, `docs/CURRENT_STATE.yaml` is the first place to repair, then propagate outward.
