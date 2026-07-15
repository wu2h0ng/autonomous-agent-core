# Agent OS Codebase Index

> Updated: 2026-07-15
> Purpose: module and evidence navigation only
> Live status: `docs/CURRENT_STATE.yaml`
> Product authority: `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`

## 1. Repository boundaries

This repository contains two tracks and a governed evaluation seam:

- `packages/`, `apps/`, `domain_packs/`, `tests/product/`: **Product Track**.
- `src/aac/`, `src/envs/`, most of `experiments/`, research tests/docs: **Research Track**.
- `product_evals/`, `tests/product_eval/`: frozen or pre-freeze Product-evaluation instruments; each exact artifact controls its own run authority.

Sharing a repository does not authorize imports across the evidence boundary. Product code must not consume raw research modules as runtime authority. Research promotion needs an explicit product contract, held-out comparison and review.

Ignored/local `.worktrees/`, caches and `.agent-os-artifacts/` are not source-of-truth content.

## 2. Top-level map

| Path | Role |
|---|---|
| `apps/api_server/` | Agent OS HTTP server and Task Workspace assets |
| `apps/cli/` | Local Product Track CLI |
| `packages/contracts/` | Provider-neutral Agent OS typed contracts |
| `packages/os_core/` | Agent Core durable task/runtime/authority implementation |
| `domain_packs/developer_agent/` | Developer golden-path domain manifest/adapters |
| `tests/product/` | Product Track unit/integration/acceptance tests |
| `product_evals/` | Product-evaluation instruments and frozen evidence; file existence is never run authority |
| `tests/product_eval/` | Product-evaluation contract and fail-closed regression tests |
| `src/aac/` | Research mechanisms and experimental integration code |
| `src/envs/` | Research environments and falsification fixtures |
| `experiments/` | Research/probe scripts and result artifacts; existence is not run authority |
| `tests/` | Research tests plus shared repository regressions |
| `docs/architecture/` | Product architecture packets and migration maps |
| `docs/product/` | Product acceptance/design evidence |
| `docs/adr/` | Repository decisions; see current state for active ones |
| `docs/research/` | Repository-local research records and historical snapshots |
| `adapters/` | External data/provider research adapters, not product authority by default |

## 3. Product contracts

Location: `packages/contracts/src/agent_os_contracts/`

| File | Responsibility |
|---|---|
| `task.py` | Task, commitment and task-state contracts |
| `workflow.py` | WorkflowGraph, nodes and workflow semantics |
| `runtime.py` | AgentRun/runtime event and execution contracts |
| `capability.py` | CapabilitySpec, calls and capability metadata |
| `authority.py` | authority, policy and approval-facing contracts |
| `evidence.py` | generic evidence/artifact contracts |
| `outcome.py` | ExpectedOutcome and ObservedOutcome |
| `provider.py` | provider/model/credential reference contracts |
| `resource.py` | budgets and resource constraints |
| `domain.py` | generic domain-pack boundary contracts |
| `materialization.py` | closed DomainCandidate, external evaluation receipt, promotion-decision and inert optional-prior contracts plus provenance, representation patches and content digests |
| `common.py` | shared identifiers, serialization and validation primitives |

These are generic OS contracts. Metric, SQL, DataProduct and business-action semantics belong to Data Agent, not this package.

## 4. Agent Core runtime

Location: `packages/os_core/src/agent_os_core/`

| File | Responsibility |
|---|---|
| `task_aggregate.py` | task aggregate and invariant-preserving state transitions |
| `task_service.py` | task/commitment/run application service |
| `event_store.py` | event-store interface and in-memory/durable semantics |
| `persistence.py` | SQLite/local persistence implementation |
| `postgres.py` | PostgreSQL persistence path |
| `execution.py` | run coordination, effects, retry/recovery and evaluator flow |
| `recovery.py` | event-derived recovery projection; no physical exactly-once or long-horizon superiority inference |
| `capability.py` | capability registry/broker and typed invocation |
| `provider.py` | provider adapters and bounded model proposal path |
| `governance.py` | policy/disposer, correction authority and minimal local-effect guard protocol |
| `materialization.py` | Task/Run/scope/C7-bound DomainCandidate sealing and listing service |
| `materialization_persistence.py` | isolated SQLite candidate store with transactional version, idempotency and parent-CAS semantics |
| `materialization_evaluation.py` | externally produced evaluation receipt recording/listing with exact scope, grant, evaluator-separation and C7 checks |
| `materialization_evaluation_persistence.py` | append-only SQLite evaluation receipt ledger with derived-key idempotency, versioning and parent CAS |
| `materialization_ledger.py` | shared SQLite connection/lock owner used to make evaluation-head and promotion writes transactionally comparable; injected stores borrow rather than close it |
| `materialization_promotion_policy.py` | digest-bound Product promotion-policy registry; production V1 deterministically returns `DEFER` for every current ADM-P2 receipt chain |
| `materialization_promotion.py` | fifth-party Task/Run/grant/C7-bound promotion-decision and inert-prior read service; no evaluator or activation path |
| `materialization_promotion_persistence.py` | append-only promotion/prior ledger with full-chain reload, derived idempotency, head/parent CAS, policy recomputation and atomic decision/prior persistence |
| `errors.py` | typed product failures |

The public Product Track path must pass through these state/authority contracts. Direct model output is never a consequential command.

## 5. Product applications

### `apps/api_server/`

- `app.py` / `server.py`: application composition and HTTP entry.
- `POST /v1/tasks/{task_id}/domain-candidates:seal` and `GET /v1/tasks/{task_id}/domain-candidates`: ADM-P1 inert candidate sealing/listing; no activation path.
- `POST /v1/tasks/{task_id}/domain-candidates/{candidate_digest}/evaluations:record` and matching `GET .../evaluations`: ADM-P2 inert external receipt recording/listing; no evaluator execution, promotion or activation path.
- `POST /v1/tasks/{task_id}/domain-candidates/{candidate_digest}/promotions:decide`, matching `GET .../promotions` and `GET .../domain-priors`: ADM-P3 Product-owned decision/inert-prior infrastructure. Production policy V1 always returns `DEFER`, so the production composition root creates no prior and exposes no activation path.
- `index.html`: Task Workspace surface.
- `preview-zh.html`: local prototype/preview; verify current status before treating it as a delivered surface.

### `apps/cli/`

Local Product Track command entry. CLI behavior must use the same application/state/authority services as HTTP; a CLI-only bypass is invalid.

### `domain_packs/developer_agent/`

The first local developer path. It is not a universal coding-agent claim or a substitute for Data Agent migration.

## 6. Product tests and evidence

| Path | Purpose |
|---|---|
| `tests/product/test_spine0_golden_path.py` | durable developer path, interruption/recovery and outcome behavior |
| `tests/product/test_e2_long_horizon_recovery.py` | bounded local wait/rebind/compensation/C7 composition-root acceptance |
| `tests/product/test_public_long_horizon_negative_paths.py` | HTTP/CLI persistence, idempotency, scope, late-signal and replan-budget negative paths |
| `tests/product/test_rebind_partial_evidence_regression.py` | authoritative evidence filtering after an authorized suffix rebind |
| `tests/product/test_materialization_contracts.py` | closed channel/outcome, provenance, digest and forbidden-authority contract checks |
| `tests/product/test_materialization_service.py` | transactional sealing, C7/scope/CAS/idempotency/restart and no-TaskEvent checks |
| `tests/product/test_materialization_api.py` | real HTTP composition, typed failures, generic-cache bypass and no-workspace-mutation checks |
| `tests/product/test_materialization_evaluation_contracts.py` | closed receipt/evaluator identity, disposition-shape and mutation-sensitive digest checks |
| `tests/product/test_materialization_evaluation_persistence.py` | append-only version/CAS/idempotency/restart receipt-ledger checks |
| `tests/product/test_materialization_evaluation_service.py` | scope/grant/four-way identity/C7/no-TaskEvent receipt-service checks |
| `tests/product/test_materialization_evaluation_api.py` | dual-principal SQLite, six-segment HTTP, cache-bypass and no-mutation checks |
| `tests/product/test_materialization_promotion_contracts.py` | closed command, decision/prior lineage, mutation-sensitive digest and forbidden-authority checks |
| `tests/product/test_materialization_promotion_policy.py` | exhaustive production V1 all-DEFER reduction and immutable exact policy-registry checks |
| `tests/product/test_materialization_promotion_persistence.py` | full receipt-chain validation, ledger ownership, derived idempotency, CAS and atomic test-only PROMOTE/prior rollback checks |
| `tests/product/test_materialization_promotion_service.py` | fifth-party identity, Task/Run/grant/scope/C7 and no-mutation promotion-service checks |
| `tests/product/test_materialization_promotion_api.py` | real HTTP DEFER/replay/restart/cache-bypass/failure/no-provider/no-workspace-effect checks |
| `tests/product/` | Product Track contracts, persistence, provider, capability, governance, API/CLI and UI-facing regressions |
| `docs/product/PM-PRODUCT-ACCEPTANCE-SPINE-0-2026-07-10.md` | bounded PM acceptance record |
| `docs/product/PM-ADM-P1-CANDIDATE-SEALING-2026-07-15.md` | exact local implementation evidence and claim ceiling for ADM-P1 |
| `docs/product/PM-ADM-P2-EXTERNAL-EVALUATION-RECEIPTS-2026-07-15.md` | exact local implementation evidence and claim ceiling for ADM-P2 |
| `docs/product/PM-ADM-P3-PROMOTION-AND-OPTIONAL-PRIOR-2026-07-15.md` | exact local implementation evidence and claim ceiling for ADM-P3 infrastructure; production V1 is all-DEFER and has no activation authority |
| `docs/architecture/T-P-OS-SPINE-0-ARCHITECTURE-PACKET.md` | SPINE-0 architecture authority |
| `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml` | migration plan/map; not execution authority |
| `product_evals/spine_e2e_1/` through `product_evals/spine_e2e_4/` | preserved successor instruments; E2E-1/2/3 are immutable INVALID and E2E-4 is one bounded frozen local same-boot PASS |
| `docs/research/SPINE-E2E-1-result.md` through `docs/research/SPINE-E2E-4-result.md` | binding result artifacts; later narrative cannot rewrite their exact verdicts |
| `product_evals/lh_recovery_1a/` | branch-contained D1-E, fixed D1-F and combined-D1 candidate machinery; no D2 or formal result |
| `tests/product_eval/test_lh1a_design.py` | D1-E/fixed-baseline and frozen-boundary contract checks |
| `tests/product_eval/test_lh1a_combined_d1.py` | combined-D1 candidate binding and fail-closed checks |
| `docs/research/LH-RECOVERY-1-final-decision-2026-07-13.md` | parent chain remains OPEN/BLOCKED/NOT_RUN; child evidence cannot pass it by implication |

Test counts and verification dates live only in `docs/CURRENT_STATE.yaml` and their source evidence.
B1 harness completion and RTM-1 resource-v4 acceptance are separate-branch evidence recorded in CURRENT_STATE; they are intentionally not indexed as branch-contained files here.

## 7. Research mechanism map

The Research Track is broad; the groups below route reading without upgrading status.

### Governance, correction and authority

- `shell.py`, `shell_ipc.py`: corrigibility shell/control boundary.
- `audit.py`: append-only/hash-linked research audit.
- `governed_gate.py`, `gate_ipc.py`, `write_authority.py`: bounded gate/write paths.
- `organ_regulator.py`, `organ_tools*.py`: organ channel and tool restrictions.

### Belief, action and adaptation

- `world_model.py`, `policy.py`, `agent.py`: historical core loop.
- `belief_ledger.py`, `conflict_detector.py`, `evidence_assembly.py`: belief/provenance candidates.
- `residual_calibrator.py`, `consequence_prior.py`, `change_point_detector.py`: calibrated/bounded adaptation candidates.
- `goal_system.py`, `goal_formation.py`, `goal_proposer.py`: goal/subgoal research; read current verdict/boundary before use.

### Causal/world-model research

- `cwm_organ.py`, `learned_cwm.py`, `nn_cwm_organ.py`, `transfer_cwm.py`.
- `discovery_loop.py`, `interactive_discovery_loop.py`, `governed_discovery_loop.py`.
- `bayesian_dag_posterior.py`, `fci_latent.py`, `interventional_orient.py`, `differential_intervention.py`.
- `causal_representation.py`, `causal_transformer.py`, `causal_prior_transfer.py`.
- `structure_*`, `hypothesis_pool.py`, `ontology_engine.py`.

### Planning, action and outcome

- `planner.py`, `intervention_chooser.py`, `online_intervention_opt.py`.
- `execution_bridge.py`, `governed_loop.py`, `outcome_judge.py`, `failure_attributor.py`.
- `commitment_ledger.py`, `self_model.py`, `self_model_updater.py`.

### LLM and external organs

- `llm_client.py`, `llm_organ.py`, `llm_prompts.py`, `language_orientation_organ.py`.
- `prior_organ*.py`, `llm_weight_organ.py`, `torch_attention_prior.py`.

These modules are research candidates. “No LLM in control path” means their output cannot write final action/policy/shell authority; it does not prohibit all Product Track language/reasoning use.

### Historical/negative routes

- `relevance.py`, `rap*.py`, `idle_drives.py`, `g_eco*.py`, `consequence_prior.py` and related environments/results include failed, negative or closed routes.
- File presence does not mean the route is active or authorized.
- Consult `docs/CURRENT_STATE.yaml`, the parent research ledger and the exact ADR/result before reuse.

## 8. Research environments

Location: `src/envs/`

Groups include survival/regime environments, ecological/viability variants, commitment/correction, staleness, consequence-scar, semantic and `φ_S` reopening environments.

An environment is a falsification instrument, not a product simulator. Do not change environment, seeds, axis or gate to rescue a completed result.

## 9. Experiment handling

`experiments/` may contain:

- exploratory scripts;
- preregistered runners;
- calibration outputs;
- frozen specs/locks;
- r-final results;
- stale or superseded probes;
- uncommitted local work.

Before running anything, locate its route decision, architecture review, preregistration, lock, seed/data policy and current authorization. `NOT_MET`, `INVALID`, `PARK`, `INSUFFICIENT_DATA` and `HOLD` are terminal constraints unless a new founder-authorized route explicitly supersedes them.

## 10. Document authority

| Need | Read |
|---|---|
| Product identity/architecture | `docs/AGENT-OS-PRODUCT-BLUEPRINT.md` |
| Live status and evidence boundary | `docs/CURRENT_STATE.yaml` |
| Authorized next sequence | `docs/PROJECT_PLAN.md` |
| Dependency horizons | `ROADMAP.md` |
| Product requirements | `docs/PRD.md` |
| Engineering/research discipline | `ENGINEERING.md`, `AGENTS.md`, parent `.agent` |
| Self-determination boundary | `docs/adr/ADR-0037-self-determination-boundaries.md` |
| Data Agent migration | `docs/adr/ADR-0054-one-time-data-agent-history-migration.md` |
| Ask/Work, organs and skill boundary | `docs/adr/ADR-0055-agent-os-interaction-and-organ-boundaries.md` |
| Adaptive materialization and optional-prior boundary | `docs/adr/ADR-0057-adaptive-domain-materialization-and-optional-priors.md` |
| Autonomy claim language | parent `docs/research/RR-0024-operational-foundations-cleanup.md` |

Historical snapshots under `docs/research/autonomous-agent-core-v0.*` and `docs/research/Kimi_Agent_终极自主智能蓝图/` are evidence/reference archives, not current authority.

## 11. Update rule

Update this index only when a major module, package, public entry point or authority file is added, removed or reclassified. Do not append task history, test counts or route narratives; those belong in CURRENT_STATE or the exact evidence artifact.
