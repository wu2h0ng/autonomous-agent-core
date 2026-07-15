# Agent OS Product Blueprint

> Status: **FINAL / FOUNDER-RATIFIED PRODUCT AUTHORITY**
> Version: 2.0
> Updated: 2026-07-14
> Product: **Agent OS**
> Repository: `autonomous-agent-core`
> Scope: 产品定义、用户体验、规范架构与产品完成门
> Live status: `docs/CURRENT_STATE.yaml`

## 0. Authority

This is the sole current product-definition document for Agent OS. It supersedes the versioned v1/v1.1 product blueprint retained in Git history and any older statement that treats this repository as only a research prototype, treats Data Agent as the entire product, or treats workflow orchestration as the product identity.

The parent `docs/GOAL-BLUEPRINT.md` owns the ultimate objective, autonomy definition and permanent governance boundaries. This file does not claim that the target product is already delivered.

## 1. Product thesis

**Agent OS is a persistent, governed work operating system that turns a person's or organization's goals into inspectable commitments, executable multi-step work, verified outcomes and reusable learning across models, tools, data and time.**

It exists because a model-plus-chat interface loses state, cannot reliably bind authority to action, treats verification as optional and rarely compounds trusted knowledge across tasks. Agent OS supplies the durable work and authority substrate around interchangeable probabilistic models.

The product promise is not “maximum autonomy.” It is:

> more verified work over time, with less repeated supervision, under explicit authority and correction boundaries.

## 2. Product identity

- **Agent OS** is the product and user environment.
- **Agent Core** is the internal provider-neutral Runtime/Kernel.
- **Agent Surface** is the coherent user-facing experience.
- **Task Workspace** is the durable environment for consequential or long-running work.
- **Data Agent** is the first enterprise domain pack and commercial vertical.
- **Research Track** supplies evidence-gated mechanism candidates; it is not a product capability ledger.
- **Engineering workflow** is internal development governance and is not product Runtime.

Agent OS is not:

- a chat wrapper;
- a workflow builder with agent branding;
- an external agent framework repackaged as OS core;
- a BI/data product renamed as a general Agent OS;
- a promise of AGI, recursive self-improvement or metaphysical autonomy;
- a system in which models, plugins or generated code hold final authority.

## 3. Users and jobs

| User | Primary job | Complete product path |
|---|---|---|
| Individual | research, plan, create and maintain durable personal work | goal -> commitment -> work -> evidence -> accepted artifact -> reusable context |
| Developer | change a codebase safely across long tasks and interruptions | issue -> repository model -> plan -> patch/action -> tests/review -> verified outcome |
| Enterprise team | turn governed domain data into decisions and approved action | intent -> domain contracts -> evidence -> proposal -> policy/approval -> action -> outcome |
| Operator/admin | control providers, credentials, capabilities, policies, budgets and incidents | configure -> observe -> intervene -> audit -> rollback |
| Domain builder | package domain semantics without forking the OS | domain contracts/adapters/evals/workflows -> reviewed DomainPack |

The same core primitives must serve these jobs; a vertical cannot fork its own identity, task runtime, provider layer or authority spine.

## 4. Agent Surface: Ask and Work

The default product is one Agent Surface with two explicit modes.

### Ask

For ephemeral, low-risk interaction that does not require durable commitments, consequential side effects or long-horizon recovery.

Ask may use models, read-only tools and bounded context. It must escalate to Work when persistence, approval, side effects, verification or recovery become material.

### Work

For consequential, long-running or outcome-verified activity. Work always creates or attaches to a Task Workspace with durable commitments, typed capabilities, events, evidence and terminal outcomes.

Routing between Ask and Work must be explainable. A convenience route cannot silently bypass a policy or authority requirement.

## 5. Task Workspace

A Task Workspace is the unit of persistent intelligent work. It contains:

- the user's goal and immutable/traceable constraints;
- task commitments and expected outcomes;
- typed workflow and current execution state;
- provider/model/tool/capability selections;
- approvals, policy decisions and authority scopes;
- artifacts, evidence, tests/evals and observed outcomes;
- failures, retries, interruption/recovery and compensation;
- relevant knowledge/beliefs with provenance and correction history.

The user can inspect what the system believes, what it plans to do, what authority it has, what changed, why an outcome was accepted and how to stop or correct it.

## 6. Canonical kernel objects

| Object | Responsibility | Must not become |
|---|---|---|
| `Task` / `Commitment` | goal, scope, constraints and accepted work contract | free-form prompt as authority |
| `WorkflowGraph` | typed executable dependency graph | product identity or untyped prompt chain |
| `AgentRun` / event log | durable execution, leases, retry, replay and terminal state | mutable chat transcript as state source |
| `CapabilitySpec` | typed operation, input/output, risk and policy requirements | skill name that grants authority |
| `CapabilityBroker` | resolve and invoke authorized capabilities | plugin-controlled dispatcher |
| `ModelProvider` / `CredentialRef` | provider-neutral model access without secret exposure | model-specific product identity |
| `WorldModelPort` | task-appropriate state/model interface | universal CWM requirement |
| `ActionContract` | exact proposed effect, digest, authority and rollback/compensation | raw model command |
| `Evidence` / artifact refs | provenance, validation and outcome support | Data Agent SQL-specific schema in OS core |
| `ExpectedOutcome` | frozen acceptance/evaluator contract | post-hoc success story |
| `ObservedOutcome` | measured terminal result and failure attribution | self-reported success alone |
| `BeliefRecord` | revisable claim, uncertainty, conflicts and provenance | uncorrectable hidden chain of thought |
| `KnowledgeAsset` | governed reusable information | unscoped vector-store memory |
| `LearnedProcedure` | versioned candidate derived from repeated verified work | auto-published behavior |
| `AuthorityPolicy` / disposer | deterministic decision over proposed action | model-held final authority |
| `CorrectionChannel` (C7) | external pause/correct/tighten/halt authority | writable or bypassable product setting |

`Skill` is not a kernel object. External skills are compatibility inputs that compile into capabilities, procedure/workflow candidates, knowledge requirements, credentials and policy requirements.

## 7. Reference work loop

```text
User/organization goal
  -> InteractionDecision (Ask or Work)
  -> Task + Commitment + ExpectedOutcome
  -> context/belief/world-state assembly
  -> WorkflowGraph and capability plan
  -> model/organ proposals
  -> typed ActionContract
  -> deterministic policy/disposer
  -> approval or bounded policy authorization
  -> execution with idempotency and audit
  -> evidence + ObservedOutcome
  -> accept / revise / compensate / recover
  -> governed knowledge, belief and procedure candidates
```

Every consequential effect passes through the same authority path. A model output, plugin callback, workflow edge or learned procedure cannot create a side channel around it.

## 8. Runtime requirements

Agent Core must provide:

1. durable Task/Run/event storage;
2. explicit state transitions and typed failures;
3. idempotency, leases, interruption recovery and effect reconciliation;
4. provider-neutral model routing and safe credential references;
5. typed capability/plugin hosting and policy checks;
6. evidence, artifact and outcome bindings;
7. budget, latency and authority ceilings;
8. pause/correct/tighten/halt dominance;
9. replay/audit without leaking secrets or unsafe payloads;
10. versioned evaluation, promotion, canary and rollback for learned candidates.

Market-parity integrations may use mature UI, database, queue, encryption, identity, model SDK, vector/search and observability libraries. Agent OS must not outsource its task state machine, authority/disposer, evidence/outcome model, correction root or promotion semantics to an external agent framework.

## 9. Authority and risk

Authority is typed and explicit, not inferred from “autonomy,” model quality or user convenience.

- Low-risk/read-only work may be policy-authorized within narrow scopes.
- Consequential effects require an `ActionContract`, evidence/policy decision and traceable authorization.
- Higher-risk actions require approval, dry-run, compensation/rollback and stronger outcome verification.
- Tenant or organization policy may permit selected automatic execution only within configured bounds and under C7 supremacy.
- Models, subagents, plugins and learned procedures receive only the capabilities required for the current task.

No outcome-learning mechanism may expand its own permission, rewrite its evaluator or promote itself.

## 10. Knowledge, belief and adaptation

Agent OS needs more than retrieval. It must distinguish:

- immutable source/evidence artifacts;
- revisable beliefs with uncertainty and conflict;
- task/session context;
- user or organization decisions;
- learned procedure candidates;
- domain knowledge assets;
- stale, revoked or superseded information.

An update must record source, affected claims, confidence, reviewer/authority, invalidation path and downstream consumers. Memory cannot silently turn a prior outcome into a policy or product fact.

Adaptation is allowed at different depths:

- update context, beliefs and rankings from verified outcomes;
- select among approved models/tools/workflows;
- propose new workflows, procedures, parameters or implementation candidates;
- evaluate candidates on frozen held-out tasks;
- promote only through independent policy/approval with canary and rollback.

Active-runtime self-rewrite and safety-substrate self-edit remain outside the product boundary.

## 11. World models and research organs

World models are plural and task-appropriate. A task may use symbolic state, code/repository structure, temporal process state, relational graphs, statistical models, CWM or no explicit learned world model.

CWM is a candidate planning/verification organ when variables, interventions, confounding and outcomes are sufficiently identifiable. It is not mandatory for every Agent, and a CWM result does not grant execution authority.

LLMs are probabilistic language/reasoning organs. They may interpret, propose, plan, generate and critique; their untyped output never directly becomes a consequential command.

Research mechanisms enter Product Track only through a stable contract, a named product failure, fair baseline/ablation, held-out evidence and safety/reliability/cost non-regression. Negative or inconclusive research remains in Research Track.

## 12. Domain packs

A `DomainPack` provides domain semantics without forking the OS. It may contain:

- domain contracts and ontologies;
- connectors/adapters and credential requirements;
- workflow templates and scene presets;
- evaluators and outcome definitions;
- policy defaults and risk classifications;
- domain knowledge and UI extensions.

It may not replace Agent Core state, provider, capability, identity, authority, evidence or correction primitives.

### Data Agent

Data Agent is the first official domain pack. Its loop is:

```text
business intent
  -> semantic/data contracts
  -> safe evidence-producing analysis
  -> decision or action proposal
  -> policy/approval
  -> governed execution or dry-run
  -> observed business outcome
  -> corrected knowledge and workflow candidates
```

Metric, SemanticObject, ProviderContract, DataProduct, SQL, query-result and business-action semantics stay in `domain_packs/data_agent`. Data Agent `EvidenceChain` projects into generic Agent OS evidence; it does not define OS core.

The existing `ai-native-business-data-agent-os` repository remains physically independent until ADR-0054/SPINE-1 passes all history-safety, provenance, extraction and review gates. There is no runtime cross-import and no migration-complete claim before that event.

## 13. Product evaluation

Agent OS must be compared with named baselines on end-to-end work, not only component tests.

Minimum benchmark families:

1. personal multi-source work with changing constraints and delayed information;
2. developer repository work with tests, review, interruption and recovery;
3. Data Agent work from governed question to evidence, decision/action and measured outcome.

Each suite includes provider/tool failures, stale/conflicting knowledge, permission denial, ambiguous goals, interruption, adversarial inputs and compensation/rollback cases.

Primary measures:

- verified outcome success and severe failure rate;
- human intervention minutes per accepted outcome;
- time, cost and model/tool calls;
- recovery and state-equivalence after interruption;
- unauthorized or duplicate side effects;
- act/ask/abstain calibration;
- evidence completeness and provenance accuracy;
- correction, invalidation and rollback success;
- cross-session retention without stale-memory harm;
- domain onboarding and zero-code transfer effort.

The mandatory baselines include direct model-plus-tools, non-durable/single-process variants, simple non-learning/non-causal arms and the previous released Agent OS version. External comparisons must pin versions, tools, provider settings, retries and evaluator rules.

## 14. Completion gates

### Product slice verified

A slice is verified only when a real accepted entry point reaches real logic, has a typed contract, negative/failure path, bypass-detecting test or eval, evidence/trace and an honest deployment/authorization statement.

### Product Alpha

All three benchmark families execute end to end through the real Task Workspace, provider/credential path, capabilities, durable runtime, evidence/outcomes and failure recovery. Mock-only or fixture-only paths do not satisfy this gate.

### Production Ready

Requires production identity/tenancy, encrypted credentials, policy administration, observability, incident recovery, backup/restore, privacy/security review, deployment/SLOs and controlled real-user evidence. Alpha or CI green is insufficient.

### Moat validated

At least one Agent OS mechanism must beat the current fair product baseline on held-out valuable workflows with predefined useful effect and no unacceptable safety, reliability, cost or latency regression.

### Superior in a named envelope

Requires independent reproducible wins against named external baselines on a declared workflow envelope, with losses and constraints reported. It never means universal superiority.

### Terminal-goal evidence

Product gates do not by themselves prove general intelligence or autonomy. Those claims remain governed by the parent Goal Blueprint and RR-0024.

## 15. Product sequence

The dependency order is:

1. **Persistent spine** — Task Workspace, commitments/outcomes, durable runs, provider/credentials, typed capabilities, evidence and correction.
2. **Complete work paths** — developer, personal and Data Agent paths on one authority spine.
3. **Operational body** — workflow authoring, knowledge lifecycle, subagents, admin, deployment, tenancy, reliability and ecosystem interfaces.
4. **Outcome compounding** — belief ledger, correction/invalidation, learned procedures and governed model/tool/workflow selection.
5. **Research promotion** — CWM and other mechanisms only after product-side falsifiers and held-out comparisons.

These are dependency stages, not calendar promises or current completion claims. Current status and authorized next work live only in `docs/CURRENT_STATE.yaml` and `docs/PROJECT_PLAN.md`.

## 16. Non-negotiable product boundaries

1. Product and Research Track evidence remain separate.
2. No raw research mechanism becomes runtime authority by import or narrative.
3. Domain packs cannot place domain semantics in OS core.
4. Credentials and sensitive tenant data are not model-visible memory by default.
5. Plugins, models, subagents and learned procedures act only through scoped capabilities.
6. C7 is non-writable and non-bypassable.
7. No untyped model output directly becomes a consequential command.
8. Outcome learning cannot auto-deploy changes to its own safety, permission, evaluator or promotion substrate.
9. Negative research results keep their exact verdicts.
10. Contracts, UI shells and mocked success do not count as delivered capability.
11. Generality, autonomy and superiority claims name an operating envelope and comparison evidence.
12. Migration, push, merge, automatic execution and release each require their own explicit authorization.

## 17. Final product statement

```text
Foundation models provide broad probabilistic priors and generation.
Agent OS provides persistent work state, typed capabilities, authority and correction.
Evidence, outcomes and belief systems provide accountable learning.
Task-appropriate world models improve selected planning and verification problems.
Humans and institutions retain legitimacy and final correction authority.
Real comparisons decide whether the system is better.
```

That is the product route to increasingly capable and scoped autonomous work without turning an unverified autonomy story into product architecture or surrendering correction authority.
