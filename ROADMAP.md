# Agent OS Roadmap

> Status: `DEPENDENCY ROADMAP / NOT A CALENDAR PROMISE`
> Updated: 2026-07-14
> Product authority: `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`
> Current position and active tasks: `docs/CURRENT_STATE.yaml` and `docs/PROJECT_PLAN.md`

## Roadmap rule

The roadmap names dependency horizons. A horizon is complete only when its exit gate is evidenced in the real product or research path. Documentation, contracts, mocks and green local tests cannot skip a horizon.

Product and Research Track may run in parallel, but research cannot become product capability by proximity and product progress cannot validate autonomy theory.

## Horizon 0 — Truth and authority spine

**Purpose:** eliminate competing project/product definitions and make current state machine-readable.

Required:

- one Goal Blueprint and one Agent OS Product Blueprint;
- compact root and repository CURRENT_STATE files;
- one autonomy claim gate and one ADR-0037;
- explicit product/research/process evidence separation;
- freshness, handoff and Git finalization rules.

**Exit gate:** all current entry docs route to the same identity and no live reference points to superseded authorities.

## Horizon 1 — Persistent Agent Core

**Purpose:** provide the minimum durable work and authority substrate.

Required:

- Task, Commitment, WorkflowGraph, AgentRun and durable event state;
- provider-neutral model access and safe credential references;
- typed capabilities and ActionContract;
- deterministic policy/disposer and C7;
- approvals, idempotency, recovery and effect reconciliation;
- evidence, ExpectedOutcome and ObservedOutcome;
- Task Workspace UI/API/CLI.

**Exit gate:** a real provider and real capability complete a bounded task through approval, verification and interruption recovery; every negative path leaves consistent durable state.

## Horizon 2 — Measured spine value

**Purpose:** prove the durable substrate adds value over simpler alternatives.

Required:

- fair direct model-plus-tools and non-resumable baselines;
- held-out tasks and injected failures;
- verified outcome, duplicate effect, state-equivalence, intervention-time, latency and cost metrics;
- frozen evaluator and independent adjudication.

**Exit gate:** SPINE-E2E evidence meets preregistered useful-effect and safety/reliability gates. A mechanism test alone is insufficient.

## Horizon 3 — Three complete product paths

### Developer path

Repository understanding, multi-file changes, bounded command/tool execution, tests, reviewable artifacts, interruption and recovery.

### Personal path

Private multi-source work, changing constraints, durable context, delayed events, accepted deliverables and correction.

### Data Agent path

Business intent, domain contracts, safe analysis, evidence, governed decision/action, approval/policy, outcome and corrected knowledge on the shared Agent OS spine.

**Exit gate:** all three use the same Task/Run, provider, capability, authority, evidence/outcome and correction primitives; no vertical forks the spine.

## Horizon 4 — Operational product body

Required:

- production identity, tenancy, encrypted credentials and organization policy;
- provider/tool operations, quotas, budget and reliability controls;
- visual/natural-language/structured WorkflowGraph round-trip;
- knowledge/belief lifecycle and conflict/staleness controls;
- admin/operator surfaces, observability and incident response;
- deployment, migrations, backup/restore and SLO evidence;
- supported capability/domain-pack interfaces.

**Exit gate:** controlled real-user operation meets explicit security, privacy, reliability and release criteria. Local alpha evidence does not satisfy this gate.

## Horizon 5 — Outcome compounding

Required:

- revisable product belief ledger;
- outcome-linked failure attribution;
- governed model/tool/workflow selection;
- learned-procedure candidates;
- held-out evaluation, independent promotion, canary and rollback;
- long-horizon planning and recovery under changing environments.

**Exit gate:** accepted outcomes improve future performance on held-out work without stale-memory, permission, safety, latency or cost regression.

## Horizon 6 — Evidence-gated research moat

Candidate families include CWM for identifiable interventions, G10-like action calibration, belief revision and additional planning/recovery mechanisms.

Every promotion requires:

- a named product failure or opportunity;
- stable Product Track contract;
- fair current baseline and ablations;
- held-out workflow evidence;
- safety/reliability/cost non-regression;
- version, monitor, rollback and external promotion authority.

**Exit gate:** at least one candidate produces a reproducible useful product improvement over the simpler current Agent OS baseline.

## Horizon 7 — Governed evolution

Required:

- orchestration/model/kernel candidate loops with isolated builders;
- frozen evaluator and independent review identity;
- tamper-evident candidate/evidence/promotion records;
- shadow/canary/rollback and bounded blast radius;
- immutable C7, permission, audit, evaluator and promotion roots;
- explicit accounting against ordinary human engineering and provider/model upgrades.

**Exit gate:** the system repeatedly proposes useful improvements that independent gates accept, while never self-approving, expanding authority or degrading correction.

L4 active-runtime self-modification remains closed and L5 safety-root self-edit remains forbidden unless a separate founder ADR changes the operating boundary after all required falsifiers. Horizon 7 does not presume that change.

## Horizon 8 — Terminal-goal evidence

This horizon is not satisfied by finishing the Agent OS feature list.

It requires evidence across the parent Goal Blueprint's three mountains:

1. generalization and world modeling in multiple unbuilt-for domains;
2. scoped long-horizon autonomy under non-trivial disturbance and limited intervention;
3. governed sustained improvement without self-authorization or loss of C7;
4. real product value, reliability, safety and sustainable economics.

Claims must specify the operating envelope, human/system baselines, migration cost, failure distribution and independent replication. “AGI achieved” is not a roadmap milestone that can be checked by narrative.

## Permanent stops

The roadmap never authorizes:

- moving a preregistered gate to save a result;
- turning `NOT_MET`, `INVALID`, `PARK` or `HOLD` into progress language;
- product projection without a real runtime/contract path;
- domain semantics in Agent Core;
- research code as product authority;
- model/plugin/subagent final execution authority;
- self-modification of C7, permissions, audit, evaluator or promotion roots;
- migration, push, merge, automatic execution or release without its specific gate.
