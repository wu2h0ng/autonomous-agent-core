# Agent OS Capability Implementation Map

> Status: `IMPLEMENTATION_MAP / NOT_PRODUCT_CLAIM / REVISE_ACCEPTED`
> Updated: 2026-07-17
> Scope: Map interview-pressure pain points to blueprint solution, source checkout, current state, gap and next engineering gate.
> Authority: `../AGENT-OS-PRODUCT-BLUEPRINT.md` and parent `../../../docs/GOAL-BLUEPRINT.md` remain authoritative. This file does not upgrade any capability status.

## 1. Purpose

This file answers:

```text
When we say Agent OS solves autonomy, domain adaptation, evidence, knowledge, runtime and learning problems, what is already implemented, what is only specified, and what must be built next?
```

It is a bridge from product/research architecture to implementation. It is not a north-star blueprint, release note, or completion claim.

## 2. Status and lane language

| Field | Values |
|---|---|
| Capability state | `IMPLEMENTED_LOCAL`, `PARTIAL`, `DESIGN_ONLY`, `RESEARCH_ONLY`, `NOT_IMPLEMENTED` |
| Lane type | `SRL_CRITICAL_PATH`, `FOUNDATION_DEPENDENCY`, `DATA_AGENT_DONOR`, `INDEPENDENT_LANE`, `DEFERRED_VERIFICATION_SEED`, `PARKED` |
| Requirement class | `U`, `P`, `A`, `E`, `R` with one primary class first |

Source checkout matters. Some current SRL contracts exist only on `autonomous-agent-core/.worktrees/canonical-convergence-20260715`, not in the main checkout. This map must not be read as "merged to main" or "released".

## 3. Map

| Pain point | Req | Lane type | Blueprint solution | Current state | Source checkout / repo | Current gap | Next gate |
|---|---|---|---|---|---|---|---|
| Event input to SRL must be typed and authenticated | `A/P` | `SRL_CRITICAL_PATH` | Environment bindings under ratified Mandate | `DESIGN_ONLY` | Canonical SRL contracts exist, but no `EnvironmentEvent` contract | No event source auth, schema, source binding, replay/idempotency, tenant scope, or Mandate-to-binding resolver | `P-SRL-EVENT-CONTRACT-1` |
| User should not drive every next task | `U/P` | `SRL_CRITICAL_PATH` | Mandate-driven SRL above Task/AWL | `PARTIAL` | `.worktrees/canonical-convergence-20260715`: `situated.py`, `situated_persistence.py` | No product `MandateSteward` loop that observes events, emits drafts and maintains attention | `P-SRL-RUNTIME-M1-plus` |
| User should not reconstruct prompt context | `P/A` | `SRL_CRITICAL_PATH` | Compile a minimal situated cognitive working set from persistent typed state | `PARTIAL/DESIGN_ONLY` | `MandateRelevanceContext`, `OperationalProjectionRef` and UCM envelope/reference exist on separate Product/Research slices | No product assembler/selection receipt; no included/excluded reason manifest, mandatory-missing state, budgeted degradation or strong full-log/summary/RAG baseline | `P-SRL-SITUATED-WORKING-SET-1` inside M1-plus |
| Draft creation must not trigger effects | `A/P` | `SRL_CRITICAL_PATH` | TaskDraft is proposal; TaskActivation is separate effect boundary | `DESIGN_ONLY` | No dedicated TaskDraft/TaskActivation gate in current docs/code | Direct MandateSteward-to-TaskService activation could bypass policy/capability gate | `P-SRL-DRAFT-ACTIVATION-BOUNDARY-1` |
| Agent detects relevance and chooses method | `P/A` | `SRL_CRITICAL_PATH` | Dispatch returns disposition plus method under deterministic policy | `DESIGN_ONLY` | Relevance assessor exists on canonical-convergence; MethodSelector does not | Attention and method selection are currently labels, not one machine-checkable scoring/dispatch function | `P-SRL-DISPATCH-1` |
| Operator cognitive load reduction must be measurable | `U/R` | `SRL_CRITICAL_PATH` | HCW/founder-load measured against baselines | `DESIGN_ONLY` | R-SRL-1 harness has relevant methodology; no product acceptance binding here | No held-out task set, direct model+tools baseline, scheduled-workflow baseline, hidden scorer or numeric gates | `P-SRL-E2E-FALSIFIER-1` |
| Task execution must be durable and recoverable | `P/A` | `FOUNDATION_DEPENDENCY` | Task, Commitment, WorkflowGraph, AgentRun, event log, lease/idempotency | `IMPLEMENTED_LOCAL` bounded slice | canonical-convergence and product slices: `TaskService`, `TaskAggregate`, `WorkflowGraph`, `postgres.py` | Bounded local/developer path only; not broad production runtime | `P-RUNTIME-DURABILITY-1` |
| Model output must not directly execute effects | `A/P` | `FOUNDATION_DEPENDENCY` | Typed ActionContract, policy/disposer, capability broker | `IMPLEMENTED_LOCAL` | canonical-convergence: `authority.py`, `governance.py`, `capability.py` | More real connectors, policy admin and TaskActivation integration missing | `P-CAPABILITY-GATEWAY-1` |
| Verified outcome must not be self-reported | `A/P/E` | `FOUNDATION_DEPENDENCY` | Frozen ExpectedOutcome and deterministic ObservedOutcome | `IMPLEMENTED_LOCAL` on canonical convergence | canonical-convergence: `execution.py`, `outcome.py`, `test_outcome_evaluator.py` | OutcomeLearningGate is not wired into SRL M1/M4; broader evaluators pending | `P-OUTCOME-EVAL-2` |
| M1-M3 need security, tenancy and credential boundary | `A/P` | `SRL_CRITICAL_PATH` | Tenant-scoped mandate, binding, credential and trace boundaries | `DESIGN_ONLY` | Data Agent has some tenant/runtime policy substrate; Agent OS SRL path does not | No minimal SRL tenant/security schema, trace redaction, credential lease or event-source auth tests | `P-SECURITY-BOUNDARY-0` |
| Every SRL package needs cost/SLO/observability | `E/P` | `SRL_CRITICAL_PATH` | Structured trace, cost ledger, latency and false-positive gates | `DESIGN_ONLY` | Existing runtime traces are not bound to SRL M1/M2/M3 | No p99 latency, token budget, false positive rate, throughput, or trace schema | `P-OBSERVABILITY-LEDGER-0` |
| Business data analysis needs semantic assets | `P` | `DATA_AGENT_DONOR` | MetricContract, DataProduct, SemanticRegistry, EvidenceChain | `IMPLEMENTED_LOCAL` in donor | `ai-native-business-data-agent-os`: `trusted_loop.py`, `semantic_runtime`, `data_product_compiler`, `evidence_chain` | Data Agent not migrated; SRL Dispatch must adapt existing donor path, not reinvent it | `SPINE-1` then `P-DATA-AGENT-ADAPTER-1` |
| Cross-module data consistency | `P/A` | `DATA_AGENT_DONOR` | Metric/data contracts, SQL safety, lineage, evidence, confidence derivation | `IMPLEMENTED_LOCAL` in donor | Data Agent `sql_safety`, `evidence_chain`, `trusted_loop.py` | No unified Agent OS domain-asset contract yet | `P-DATA-ASSET-CONTRACT-1` |
| Rules, defects and methods become callable assets | `P/R` | `SRL_CRITICAL_PATH` | KnowledgeAsset lifecycle and outcome/feedback path | `PARTIAL` in donor; `DESIGN_ONLY` in Agent OS | Data Agent `knowledge_memory`; Agent OS lacks Rule/Pattern/Procedure/Case/Method contracts | Automatic candidate generation is premature without seeded assets and verified outcome gate | `P-KNOWLEDGE-ASSET-TYPES-1` with M4a/M4b/M4c |
| Domain expertise without hand-built vertical agents | `R/P` | `DEFERRED_VERIFICATION_SEED` | Domain Adaptation Engine plus optional priors | `DESIGN_ONLY/PARTIAL` | Goal Blueprint plus Data Agent donor | Generic domain-model generation is too broad for near-term product path | Narrow to `P-DOMAIN-PRIOR-INGEST-1` |
| Multimodal inputs | `P/A` | `DEFERRED_VERIFICATION_SEED` | Modality IR plus evidence anchors | `NOT_IMPLEMENTED` | None | Needs stable task/evidence/outcome spine and a concrete use case that text-only fails | Defer `P-MULTIMODAL-IR-1` until M1-M3 + outcome gate |
| SFT/RLHF/GRPO | `R/P` | `DEFERRED_VERIFICATION_SEED` | Training only after trace/outcome loop and shadow/canary/rollback | `DESIGN_ONLY` | Goal Blueprint five write channels | No training data pipeline, model registry, or proof tools/schema/RAG are insufficient | Defer `R/P-MODEL-TRAINING-LOOP-1` |
| Million-agent production runtime | `P/A/E` | `DEFERRED_VERIFICATION_SEED` | Virtual actor/durable workflow, sharding, backpressure, cost ledger | `NOT_IMPLEMENTED` at production scale | Local durability exists in TaskService/Postgres | No scheduler, queue, actor sharding, production SLO or multi-tenant cost plane | Defer `P-DISTRIBUTED-RUNTIME-1` |

## 4. Current honest summary

The project has implemented the trusted execution spine, capability gate, local durable task/run state, deterministic outcome truth, and a substantive Data Agent governed analysis loop. It has partially implemented Mandate/SRL contracts, relevance assessment, HelpRequest and knowledge candidate sedimentation on canonical-convergence.

The project has not yet implemented a complete autonomous MandateSteward, situated working-set assembler, generic domain adaptation engine, production distributed runtime, multimodal chain, or training loop. The immediate critical path is not those deferred systems; it is `P-SRL-RUNTIME-M1-plus` with event/security/working-set/held-out/baseline/HCW and TaskDraft/TaskActivation gates.

## 5. Completion discipline

No item in this map may be called complete unless the implementation package identifies:

- public entry point;
- typed input/output contract;
- failure and denial path;
- tests that fail on bypass or constant success;
- evidence/outcome binding;
- authority/correction behavior;
- cost/SLO/observability boundary;
- current deployment state and source checkout.
