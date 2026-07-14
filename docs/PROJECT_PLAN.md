# Agent OS Project Plan

> Status: `ACTIVE / AUTHORIZED-SEQUENCE ONLY`
> Updated: 2026-07-14
> Product authority: `AGENT-OS-PRODUCT-BLUEPRINT.md`
> Live truth: `CURRENT_STATE.yaml`
> This file is not a historical changelog and does not authorize work by itself.

## 1. Planning rule

The repository has two tracks under one architecture:

- **Product Track** builds the Agent OS product body.
- **Research Track** produces falsifiable mechanism evidence and negative results.

Work may proceed concurrently, but evidence cannot jump tracks. A Research Track win needs a named Product Track consumer, stable contract and product-side held-out gate. A Product Track milestone does not validate autonomy theory.

Every task must declare: track, claim class, authority, entry point, contract, failure path, bypass-detecting verification, C6/C7 boundary, evidence level and next gate.

## 2. Current priority order

### P0 — Finish document authority convergence

**Task:** `DOC-CONVERGENCE-2026-07-14`

**Status:** `IN_PROGRESS / DOCS_ONLY`

**Outcome:** one Goal Blueprint, one Agent OS Product Blueprint, compact CURRENT_STATE, one ADR-0037 and consistent README/plan/index routing across the workspace.

**Hard boundary:** no runtime, experiment, verdict, release or migration change.

**Exit:** YAML and links validate; no live refs point to removed authorities; current claims match dated source artifacts.

### P1 — Make SPINE-E2E-1 runnable, not yet run

**Task:** `SPINE-E2E-1` P-a

**Current status:** `PREREQUISITE_UNBLOCKED / EXECUTION_NOT_READY / NOT_PREREGISTERED / NOT_RUN`

**Purpose:** measure the value of durable Task/Run state against:

1. direct model-plus-tools without the durable spine;
2. a single-process non-resumable workflow.

**Required before preregistration:**

- close Task-1 time-attestation and live-runtime contract revisions;
- obtain independent acceptance of the plan and artifact kernel;
- freeze held-out task set, provider/model settings and failure schedule;
- freeze `ExpectedOutcome`/evaluator versions;
- define effect floors for verified success, duplicate effects, state equivalence and human intervention;
- bind real ProductFailureRef and baseline manifests;
- prove no arm bypasses ActionContract/policy/evidence paths.

**Implementation boundary:** product-eval feature branch/PR; reuse the existing AgentOSApplication/Task Workspace spine; no Research Track import and no Data Agent domain semantics.

**Stop/invalid conditions:**

- any accepted result can be produced without the declared authority/evidence path;
- a restart duplicates a committed side effect;
- baseline tools/data differ materially;
- hidden human correction or post-hoc evaluator change occurs;
- prereg spec or implementation bytes drift from the lock.

**Important:** P-a measures durable-spine value. It cannot satisfy the B1 multi-organ orchestration-cost Gate P by itself.

### P2 — Scope the true multi-organ Gate-P variant

**Task:** `SPINE-E2E-1-P-b` (new packet required)

**Status:** `DESIGN_REQUIRED / NOT_AUTHORIZED_TO_RUN`

**Purpose:** compare a workflow with at least two distinct model/organ calls against a fair unified-call alternative, measuring verified outcomes, latency, cost, model calls and planner/verifier consistency.

**Admission requirements:**

- P-a instrumentation and baselines exist;
- the multi-organ workflow solves a real product task, not a synthetic organ demo;
- the unified-call arm has the same task information and tools;
- architecture-theory review maps the result to B1 Gate P without claiming Gate R.

### P3 — Continue B1 only inside the confirmed sandbox

**Task:** `B1-UNIFIED-MODEL-SANDBOX`

**Status:** `SANDBOX_ONLY / HARNESS-BUILD CONFIRMED / TRAINING NOT AUTHORIZED`

**Allowed now:**

- build non-training falsifier harnesses bound to the reviewed sandbox contract;
- validate consumption-path isolation, no-hidden-policy checks, aggregate C6 falsifiers and deterministic data/arm manifests;
- record evidence without starting training or opening result-bearing held-out data.

**Not allowed:**

- model training or tuning;
- Gate R result claims;
- treating P-a as Gate P completion;
- Agent OS integration or runtime dependency;
- changing C6/C7 or using B1 output as promotion authority.

Any later stage requires a new founder cast and the full paradigm/prereg chain.

### P4 — Prepare SPINE-1 safety and provenance inputs

**Task:** `T-P-OS-SPINE-1`

**Status:** `DESIGN_AUTHORIZED / EXECUTION_GATED / NOT_EXECUTED`

**Allowed preparation:**

- pin donor refs and characterize the current donor without importing it;
- specify full-history secret/PII/customer-data/binary/license scan commands and review roles;
- define provenance manifest and filtered-mirror fallback;
- map generic versus Data Agent domain packages;
- design donor characterization and post-extraction tests;
- prepare isolated branch/rollback plan.

**Execution remains blocked until every ADR-0054 gate is accepted.** No subtree import, runtime cross-import, push, merge or “migrated” claim is permitted during preparation.

### P5 — Convert governed-core-evolution intent into bounded packets

**Program:** `GOVERNED-CORE-EVOLUTION`

**Status:** `DESIGN_AND_PLAN_ONLY / NO_RUNTIME_AUTHORIZATION`

Prepare three independent successor packets rather than one self-improvement mega-project:

#### GCE-O1 — Orchestration candidate loop

- named orchestration bottleneck and product baseline;
- candidate generator runs outside the active runtime;
- frozen held-out workflows, latency/cost/reliability/effect metrics;
- independent approval, canary and rollback;
- no permission or evaluator writes.

#### GCE-M1 — Model/algorithm candidate loop

- explicit training data/held-out separation;
- fixed objective, budget and leakage checks;
- compare against provider/model upgrade and simpler fine-tune/prompt baselines;
- no training authorization until separate founder gate;
- product consumption requires its own contract and safety non-regression.

#### GCE-K1 — Functional-core implementation candidate loop

- versioned kernel interface and compatibility suite;
- isolated build/test environment;
- adversarial C6/C7, permission, audit and promotion-root tests;
- shadow/canary only after independent acceptance;
- external promotion controller retains final authority.

L4 active-runtime self-modification remains closed. L5 safety-substrate self-edit remains forbidden.

## 3. Product horizon after the current priorities

The dependency order, not a calendar commitment:

### H1 — One complete Agent OS spine

- persistent Task Workspace and task/run lifecycle;
- production-grade provider/credential plane;
- typed capability/plugin host;
- WorkflowGraph authoring and versioning;
- evidence/outcome and failure-attribution plane;
- identity, policy, C7 and operator controls.

### H2 — Three complete paths

- developer work with broad repository actions, review and recovery;
- private personal work with durable context and changing constraints;
- Data Agent on the shared spine after SPINE-1.

### H3 — Operational body

- tenancy, encrypted credentials, SSO/policy administration;
- deployment, observability, SLOs, backup/restore and incident response;
- admin and operator surfaces;
- supported capability/domain-pack ecosystem.

### H4 — Outcome compounding

- product belief ledger;
- staleness/conflict/correction and invalidation;
- governed model/tool/workflow selection;
- learned-procedure candidates with held-out eval and rollback;
- long-horizon planning/recovery benchmark.

### H5 — Evidence-gated research promotion

- CWM only in identifiable product workflows;
- G10-like decision policy only after product revalidation;
- additional mechanisms only through an explicit candidate manifest and fair product comparison.

## 4. Research route admission

No new Research Track route starts from an interesting paper, benchmark or component. Admission requires:

1. foundational problem lock;
2. frontier/anomaly intake where external evidence is involved;
3. paradigm thesis and null/reduction hypothesis;
4. independent architecture designs and skeptic reduction;
5. architecture-theory review with claim channel, product/process boundary, prior negative map, cheap baseline and C6/C7/SD4 analysis;
6. founder route cast;
7. formal/algorithm spec and implementation cast before mechanism files;
8. preregistration, independent review, manifest integrity and freeze;
9. one result-bearing run under locked rules;
10. independent adjudication, claim review, negative-map update and paradigm learning.

If a route reduces to a cheap baseline, lacks independent truth, depends on an oracle or cannot name a consumption path, use `PARK` rather than extending the ladder.

## 5. Existing results that constrain planning

- G10 remains a narrow positive task/regret result; Product Track must revalidate it before use.
- G13 and G-ECO-REOPEN-1 are final `NOT_MET`; no rescue runs.
- survival/risk/endogeny did not establish an independent axis.
- GSE42528 Branch-M and the adaptivity-gap route are parked.
- non-oracle real structure/mechanism discovery remains unresolved.
- CWM hard-form evidence is narrow and does not justify universal use.
- RR-0034/SD4 terminus is a scoped theoretical record; autonomy claims still use RR-0024.

These constraints narrow work; they do not imply that all future mechanisms are impossible.

## 6. Task completion gates

### Product implementation

Must identify the real entry point, typed contract, unsafe/invalid failure path, bypass-detecting test, integration surface, evidence/trace and deployment/authorization state.

### Research implementation

Must match frozen spec bytes, mechanism hashes, seed/data policy, baseline manifests and architecture/prereg reviews. Green unit tests do not authorize a run.

### Documentation

Must update CURRENT_STATE only for live truth, plans only for authorized next work and indexes only for routing. Historical detail belongs in ADR/RR/result/Git, not CURRENT_STATE.

### Git

Run `git status --short` and `git diff --check`; separate task changes from pre-existing experiment/worktree changes. Do not push, merge, migrate or release without separate authorization.

## 7. Explicitly not authorized by this plan

- Agent OS Product Alpha, production or superiority claims;
- B1 model training or result-bearing experiment;
- SPINE-1 import, push or merge;
- CWM real-actuator promotion;
- G13/G-Eco rescue, reseed or gate changes;
- general autonomy or AGI claims;
- L4 runtime self-modification or L5 safety-root editing;
- product execution by Research Track or workflow tooling.
