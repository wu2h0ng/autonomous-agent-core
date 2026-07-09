# Agent OS Product Blueprint v1

> Status: **FINAL / Founder-ratified product authority**
> Version: 1.0
> Date: 2026-07-10
> Product: **Agent OS**
> Repository: `autonomous-agent-core` (historical repository name; now the Agent OS monorepo)
> Architecture: **dual-track layered monorepo**
> Evidence boundary: product blueprint finalized; product runtime is not thereby delivered

## 0. Authority and decision

This document is the authoritative product definition for this repository. It supersedes narrower local statements that describe `autonomous-agent-core` as only an object-layer research prototype, as not a business product, or as a mechanism supplier to a separate final product.

The founder decision is:

```text
The same repository evolves directly into the complete Agent OS main repository.
It contains a Product Track and a Research Track under one architecture,
but research results never become product claims or runtime dependencies by implication.
```

Consequences:

1. **Agent OS is the product.** Agent Core is an internal runtime/kernel concept, not the product name.
2. **Research is part of the product program, not the whole product.** Existing experiments remain valid research assets with their original verdicts and limits.
3. **Data Agent is the first official enterprise domain pack and commercial vertical.** It is not the entire end state and must not inject data-domain semantics into OS core.
4. **The default front door is a Codex-style Task Workspace.** Chat is an interaction mode inside a persistent task, not the primary product container.
5. **Workflow authoring is bidirectional.** Users can visually drag and configure a graph or generate/edit the same graph through natural language.
6. **Market parity is mandatory but not the moat.** Provider access, BYOK, tools, plugins, knowledge/RAG, subagents, workflow, eval, governance and deployment must first reach credible product parity.
7. **The candidate moat is evidence-gated.** CWM, belief ledger and governed outcome learning earn promotion only through real workflow comparisons.
8. **No universal-superiority claim is authorized.** Superiority is decided per operating envelope by reproducible held-out tests against named baselines.

This decision changes repository identity and target architecture. It does **not** rewrite historical ADRs, turn `NOT_MET` into progress, authorize unsafe self-modification, or claim that the current research-heavy tree already implements the product below.

## 1. Product definition

### 1.1 One-sentence definition

**Agent OS is a persistent, governed work operating system that turns a person's or organization's goals into inspectable commitments, executable multi-step work, verified outcomes and reusable learning across models, tools, data and time.**

### 1.2 What it is

Agent OS is the shared runtime and user environment for:

- expressing intent and negotiating an executable commitment;
- compiling goals into editable workflow graphs;
- selecting models, agents, tools, knowledge and credentials;
- executing work over minutes, days or recurring schedules;
- pausing, resuming, recovering, escalating and correcting;
- measuring whether the promised outcome occurred;
- preserving evidence, beliefs, artifacts and lessons for future work;
- governing authority, cost, privacy and risk at every consequential action.

It serves three first-release audiences through one product spine:

| Audience | Primary job | First complete path |
|---|---|---|
| Individual | Delegate long-running research, planning and personal operations without losing control or context | private task workspace -> connected tools/knowledge -> reviewed outcome |
| Independent developer | Turn an issue or goal into an inspected change, tests and deliverable with a Codex-class task experience | repository task -> plan -> tool execution -> verification -> patch/PR artifact |
| Enterprise team | Turn governed business data into decisions and approved actions | Data Agent -> evidence -> proposal -> approval/policy -> action -> outcome learning |

These audiences do not require three products. They require shared task, workflow, execution, knowledge, provider, policy and evidence primitives plus audience-specific domain packs and defaults.

### 1.3 What it is not

Agent OS is not:

- a generic chat shell with more buttons;
- a workflow canvas that only routes prompts;
- a collection of agent demos or a thin wrapper around model APIs;
- an enterprise BI product renamed as an Agent OS;
- a research harness exposed directly to customers;
- a swarm whose activity is mistaken for intelligence;
- a promise of recursive self-improvement or metaphysical autonomy;
- a requirement that one world model, one planner or one foundation model solve every domain.

### 1.4 Product promise

The product promise is not "the agent thinks like a human." It is:

```text
Give Agent OS a consequential goal.
It will make its commitment explicit, work through governed capabilities,
show its evolving state and evidence, recover or ask when necessary,
and prove what outcome was or was not achieved.
```

## 2. First-principles view of general autonomous AI

### 2.1 Definition

A general autonomous AI system is **a persistent, adaptive perception-to-action system that can pursue a broad distribution of goals over extended time under uncertainty and bounded authority, while remaining corrigible, accountable and able to learn from observed consequences**.

This is a system property. It is not equivalent to a foundation model, a CWM, a planner, a memory store, a multi-agent topology or a particular theory of intrinsic stake.

### 2.2 Necessary functional organs

A credible system needs at least these functions, even if implementations change:

1. **Context construction:** turn observations, documents, events and human intent into a task-relevant state.
2. **Belief state:** represent claims, uncertainty, provenance, conflict, staleness and invalidation rather than storing undifferentiated text.
3. **Plural world models:** combine broad model priors, causal models, simulators, rules and learned domain models according to the problem.
4. **Commitment and temporal planning:** transform goals into bounded promises, subgoals, schedules and replanning policies across long horizons.
5. **Capability-scoped action:** act only through typed tools and permissions with explicit side effects, budgets and failure semantics.
6. **Outcome verification:** compare expected and observed outcomes and distinguish completion from plausible narration.
7. **Credit assignment and continual learning:** update beliefs, policies, workflows and tool choices without silently corrupting prior knowledge.
8. **Self-model and calibration:** estimate competence, uncertainty, limits, resource state and when to ask, retry, delegate or stop.
9. **Human and institutional correction:** expose pause, override, approval, appeal and audit surfaces that the acting cognition cannot bypass.
10. **Resource governance:** manage time, tokens, money, rate limits, privacy, risk and service-level objectives.
11. **Optional collective cognition:** create supervised specialist agents when parallelism, diversity or adversarial review has measurable value.

No single organ is the subject. The product-level agent is the governed closed loop formed by their coordination and its durable state.

### 2.3 Autonomy is operational, not mystical

Autonomy should be measured along separable operational dimensions:

- **duration:** how long work continues coherently;
- **initiative:** which useful next steps can be proposed without prompting;
- **authority:** which side effects may be executed within policy;
- **adaptation:** how behavior changes when the environment changes;
- **recovery:** how often failure is diagnosed and repaired without restart;
- **intervention load:** how much human attention is required per verified outcome.

Raw benchmark intelligence and operational autonomy interact, but they are not the same measurement. The project's narrow result that no independent "autonomy axis" was established in a tested prototype family must not be promoted into a universal theorem that autonomy cannot be measured separately.

### 2.4 Generality is an operating envelope

"Arbitrary domains" is not a useful product claim. Generality is demonstrated by:

- a stable goal/task/action/outcome substrate;
- zero-code or low-code adaptation through tools, knowledge and workflow composition;
- transfer to held-out task and domain distributions;
- graceful abstention outside the operating envelope;
- bounded cost of adding a new domain pack.

The system may use specialized agents and models. Generality resides in the shared substrate and adaptation process, not in forcing one policy to be optimal everywhere.

### 2.5 Corrections to inherited project assumptions

The following corrections are binding for product architecture:

1. **C7 need not be unknowable.** Any observable correction mechanism can be modeled. Safety must rely on non-writability, non-bypassability, capability isolation and external authority, not on assuming the agent cannot predict correction.
2. **A deterministic disposer is not a semantic oracle.** It can enforce policy, evidence and authority and make deterministic selections over typed surfaces; proposing, estimating and verifying still require intelligent organs.
3. **CWM is not universally applicable.** It is valuable when variables, interventions and outcomes can be identified and measured. Observational, partially observable, irreversible and semantic work needs other models and explicit fallbacks.
4. **Novel commitments are allowed under staged risk.** "Only commit to demonstrated actions" would prevent useful open-ended work. Models may nominate; evidence calibrates; policy limits; staged execution contains risk.
5. **External tools and RAG are legitimate cognitive scaffolds.** The hard problems are provenance, permissions, maintenance, contamination and evaluation, not their external origin.
6. **Swarm topology is not intelligence.** Subagents are justified by measured specialization, parallelism or review value and remain under one accountable run, authority envelope and budget.
7. **Useful self-improvement is mostly governed artifact evolution.** Prompts, workflows, tools, memory policies, evaluators and configurations may generate candidates and pass sandbox/eval/approval. Runtime safety and correction substrates do not self-authorize rewrites.

## 3. User experience and product surfaces

### 3.1 Task Workspace: the primary container

Every consequential activity lives in a persistent Task Workspace containing:

- goal, scope, constraints and acceptance criteria;
- negotiated commitment and current plan;
- conversation and structured decisions;
- workflow graph and active node state;
- agents, providers, tools, credentials and knowledge in use;
- event stream, evidence, approvals, costs and artifacts;
- expected outcomes, observed outcomes and unresolved gaps;
- pause, resume, branch, replay, correct and terminate controls.

The workspace must support foreground interaction and background execution. A process restart, browser close or provider failure must not erase the task's durable state.

### 3.2 Workflow Studio

Workflow authoring has one canonical `WorkflowGraph` representation and three synchronized views:

1. natural-language generation and editing;
2. visual drag-and-drop graph editing;
3. structured configuration/code view for developers.

Round-trip integrity is mandatory: a natural-language change produces a graph diff; a visual edit changes the same typed graph; neither silently discards policies, variables, failure branches or outcome tests.

Required node families include agent, model, tool, knowledge retrieval, transform, decision, approval, evaluation, wait/event, loop, parallel map, subworkflow and terminal outcome. Every node defines input/output contracts, retries, timeout, idempotency and error routing.

### 3.3 Agent Studio

Users may create domain agents, but an agent is a versioned configuration over stable OS primitives rather than an unconstrained persona prompt. It binds:

- role and goals;
- allowed providers/models;
- tools and capability scopes;
- knowledge/context policy;
- workflow templates;
- memory and retention policy;
- autonomy/risk level;
- evaluators and escalation rules;
- budget, latency and quality objectives.

Agent templates, workflow templates, tools, domain packs and evaluators are separate composable assets. This prevents plugin-market prompts from bypassing runtime governance.

### 3.4 Integration Center

The Integration Center provides:

- provider registry and model capability discovery;
- user BYOK and organization-managed credentials;
- encrypted secret references, rotation and revocation;
- OAuth/service-account/API-key connection flows;
- MCP and native plugin installation;
- connector health, scopes, rate limits and data-boundary display;
- per-task/provider routing and fallback policy;
- local, cloud and private endpoint support.

Credentials are never embedded in workflows, prompts, events or model-visible memory. Product objects use `CredentialRef`; resolution occurs only at the capability boundary.

### 3.5 Knowledge and context

Knowledge is not one vector database. Agent OS needs a governed `ContextGraph` spanning:

- documents and retrieval indexes;
- structured records and semantic objects;
- task events, artifacts and decisions;
- beliefs with provenance and uncertainty;
- user/team preferences and policies;
- temporal validity, access control, deletion and invalidation.

RAG is one retrieval strategy. Every retrieved claim must retain source, tenant, access scope, timestamp and confidence. Memory promotion is outcome-informed and reversible; a successful-looking model response alone cannot become durable truth.

### 3.6 Operations, evaluation and administration

The product includes run monitoring, approval inbox, policy management, eval suites, cost/latency dashboards, incident/replay tools, identity/RBAC, tenant/data retention controls, audit export and deployment/version management. These are runtime product capabilities only when implemented in the product path; the internal research workflow is not a substitute.

## 4. Canonical product model

### 4.1 Core objects

| Object | Responsibility |
|---|---|
| `Goal` | Desired state, constraints, priority and acceptance intent |
| `Commitment` | Negotiated promise: scope, assumptions, deadline, budget, risk and exit conditions |
| `Task` | Persistent unit of accountable work and user interaction |
| `WorkflowGraph` | Versioned executable graph with typed nodes, policies and failure paths |
| `AgentRun` | One resumable execution of a task/workflow under a fixed authority envelope |
| `Agent` | Versioned role/capability/knowledge/eval configuration |
| `Provider` | Model or service provider and its declared capabilities/health |
| `CredentialRef` | Non-secret reference to a separately protected credential |
| `ToolPlugin` | Typed capability, permissions, side effects and lifecycle metadata |
| `ContextGraph` | Governed graph of sources, state, relations and retrieval views |
| `Belief` | Claim plus confidence, provenance, validity interval, conflicts and revision history |
| `ActionContract` | Preconditions, authority, inputs, risk, expected outcome and failure/rollback semantics |
| `ExpectedOutcome` | Observable success/failure measures and verification window |
| `ObservedOutcome` | Measurements, evidence, attribution and unresolved uncertainty after action |
| `Evidence` | Source-bound support for a decision, action or outcome claim |
| `Policy` | Machine-enforced authority, privacy, risk, budget and retention rule |
| `Approval` | Scoped authorization bound to subject, version, evidence and expiry |
| `Correction` | Pause, override, amendment, rollback or appeal event |
| `Event` | Immutable task/run state transition record |
| `Artifact` | Versioned output with provenance, ownership and retention metadata |

### 4.2 Golden lifecycle

```text
Goal
  -> Context construction
  -> Commitment negotiation
  -> WorkflowGraph compile/edit
  -> Policy and capability binding
  -> AgentRun
  -> Observe -> Believe -> Plan -> Act -> Verify -> Revise
  -> ExpectedOutcome vs ObservedOutcome
  -> User/Policy acceptance, correction or escalation
  -> Outcome-informed memory/workflow update
```

### 4.3 Executable-action invariant

No consequential action becomes executable unless its `ActionContract` binds:

- actor and target;
- typed inputs and preconditions;
- capability and credential scope;
- policy decision and approval when required;
- risk, budget, timeout and idempotency;
- expected outcome and measurement method;
- evidence used to justify the action;
- failure, compensation and rollback semantics;
- audit/event destination.

Low-risk actions may be automatically approved by explicit policy. Higher-risk actions require human or external-system approval. Human review is risk-adaptive, not a mandatory click on every step.

## 5. Dual-track layered monorepo

### 5.1 Target topology

The repository evolves toward:

```text
apps/
  desktop/                 # primary Codex-style workspace
  web/                     # collaborative and administrative surface
  api/                     # public/control APIs
  worker/                  # durable background execution

packages/
  contracts/               # canonical product schemas and versioning
  task-runtime/            # Task/Commitment/AgentRun lifecycle
  workflow/                # WorkflowGraph compiler, editor and executor
  agent-runtime/           # observe/plan/act/verify orchestration
  provider/                # provider registry, routing and health
  credentials/             # secret references and broker interfaces
  tools/                   # capability registry, MCP/native plugin host
  knowledge/               # ContextGraph, retrieval and memory lifecycle
  belief-ledger/            # provenance, uncertainty, conflict and revision
  governance/              # policy, approval, correction and audit
  outcome/                 # Expected/ObservedOutcome and learning
  eval/                    # task, workflow, safety and comparative evals
  sdk/                     # plugin, workflow, agent and embedding SDKs

domain_packs/
  data_agent/              # first official enterprise vertical
  developer_agent/         # product dogfood and developer workflow defaults
  personal/                # private personal workflow defaults

research/
  mechanisms/              # candidate mechanisms, formal models and probes
  experiments/             # preregistered experiments and result artifacts
  benchmarks/              # research baselines and falsifiers
  promotion/               # candidate manifests and product revalidation

tests/
  product/
  contracts/
  integration/
  comparative/
  research/
```

This is a target architecture, not a claim that these directories already exist. Existing `src/aac`, `experiments`, `adapters` and research tests remain the Research Track until explicitly migrated or promoted.

### 5.2 Layer rules

**Product Track** owns customer-visible runtime, API, UI, contracts, identity, secrets, providers, tools, knowledge, task execution, policy, eval, deployment and domain packs.

**Research Track** owns mechanism hypotheses, simulations, formal models, preregistrations, baselines, negative results and candidate evidence.

The tracks share a repository and governance, but not truth by association:

- product code never imports experiment scripts or result artifacts as runtime logic;
- a research pass does not authorize a product claim;
- a product success does not validate an autonomy theory;
- promotion requires a versioned product contract, operating envelope and independent product benchmark;
- negative and null research results remain first-class assets and are not rewritten during productization.

### 5.3 Research-to-product promotion contract

Every candidate mechanism must provide a `ResearchCandidateManifest` containing:

- problem and product failure addressed;
- stable interface and proposed consumption path;
- evidence level, preregistration and exact result artifacts;
- cheap and current-product baselines;
- operating envelope and known failure modes;
- safety/correction implications;
- latency, cost and state requirements;
- product revalidation tests and rollback plan;
- owner and expiry/review date.

Promotion means implementing or packaging the mechanism behind a stable product interface and passing product tests. It does not mean importing a research module because it exists in the same repository.

### 5.4 Build-versus-buy boundary

The authority spine must be self-developed: task/commitment semantics, workflow IR, capability policy, action contracts, belief/outcome model, correction boundaries and promotion rules.

Agent OS may use mature libraries and services for UI, databases, queues, encryption, identity protocols, model SDKs, vector/search engines and observability. It may support MCP and third-party plugins. It must not outsource its core authority model to an external agent framework or let a plugin bypass it.

## 6. Market-parity layer

Before research differentiation matters commercially, Agent OS must provide credible baseline capability in all of these areas:

| Capability | Required product behavior |
|---|---|
| Task workspace | persistent tasks, streaming events, artifacts, background work, pause/resume/branch/replay |
| Workflow | visual + natural-language + structured editing over one typed graph; versions and reusable templates |
| Providers | multiple providers, local/private endpoints, capability discovery, routing, fallback, budgets and health |
| BYOK/secrets | encrypted credential broker, scopes, rotation, revocation, audit and tenant isolation |
| Tools/plugins | typed native tools, MCP, plugin lifecycle, permissions, sandboxing and developer SDK |
| Knowledge/RAG | governed ingestion, hybrid retrieval, provenance, ACL, freshness, deletion and evaluation |
| Agents/subagents | user-defined agents, templates, bounded delegation, shared budgets and accountable parent run |
| Runtime | durable execution, retries, idempotency, scheduling, event waits, crash recovery and compensation |
| Governance | risk-tier policy, approvals, correction, audit, identity/RBAC and data controls |
| Evaluation | task acceptance tests, regression packs, policy/safety tests, outcome verification and replay |
| Enterprise | tenants, teams, SSO interfaces, private networking/deployment options, retention and export |
| Developer platform | API/CLI/SDK, local development, test harness, versioning and packaging |

These are product requirements, not evidence that the current repository already matches Codex, Claude or enterprise agent platforms.

## 7. Differentiation and moat

### 7.1 Product moat

The near-term moat is the compounding system around work:

- a durable Work Graph linking goal, commitment, workflow, action, evidence and outcome;
- a governed runtime that can safely remain active over long horizons;
- an ecosystem of providers, tools, agents, workflows and domain packs under one capability model;
- verified outcome history that improves future commitments, routing, workflows and intervention timing.

This can create switching cost and learning advantage even before any novel autonomy mechanism is proven.

### 7.2 Research moat candidates

The primary research candidates are:

1. **Causal World Models (CWM):** improve planning and intervention selection where causal variables and outcomes are sufficiently identifiable.
2. **Belief ledger:** maintain explicit, revisable claims with provenance, uncertainty, conflict and failure attribution across long-running work.
3. **Governed outcome learning:** update model/tool/workflow/agent choices from verified outcomes while preventing silent self-authorization and contamination.

These form a candidate closed loop:

```text
Belief state
  -> model/policy proposes intervention
  -> governed ActionContract executes
  -> ObservedOutcome is measured
  -> causal and non-causal attribution
  -> belief/workflow/routing update
  -> independently evaluated next task
```

### 7.3 Moat rule

A mechanism is not a moat because it is novel, mathematically interesting or internally tested. It becomes a product moat only if it yields a reproducible improvement in at least one valuable workflow without unacceptable regressions in safety, intervention load, reliability, latency or cost.

### 7.4 Competitive stance

This is a target-position comparison, not a claim that the current repository already wins:

| Reference category | What Agent OS must first match | Intended difference | Current honest disadvantage |
|---|---|---|---|
| Codex/Claude-style task agents | direct task interaction, strong model/tool execution, artifact feedback and low-friction developer UX | provider-neutral persistent Work Graph, user-editable workflow, explicit commitment/outcome semantics and cross-domain/domain-pack continuity | no comparable product UI/runtime or field reliability yet |
| Enterprise agent platforms | connectors, identity, permissions, workflow, deployment, administration and supportability | one personal/developer/enterprise task substrate plus evidence-bound action, belief revision and outcome learning rather than only orchestration | far fewer integrations, no production compliance/deployment maturity and no customer evidence yet |
| Visual automation/agent builders | accessible graph authoring, templates, triggers and integrations | natural-language/visual/structured round-trip over a typed graph, with long-running agent state, recovery and verified outcomes | no mature editor, marketplace or operational ecosystem yet |
| Model-plus-tools baselines | broad reasoning and rapid adoption of better models | durable state, authority, correction, evaluation and compounding across interchangeable models | additional system complexity, latency and cost must prove their value |

The credible differentiation is therefore not "more autonomous" as a slogan. It is **better verified work over time under real authority and failure constraints**. If the added OS layers do not beat a simpler model-plus-tools baseline, they are overhead rather than a moat.

## 8. Data Agent: first official vertical

Data Agent is the first enterprise domain pack because data-to-decision-to-action has measurable outcomes, strong governance needs and a plausible fit for causal and belief mechanisms.

Its trusted loop is:

```text
Business intent
  -> semantic/data contracts
  -> evidence-producing analysis
  -> decision or action proposal
  -> policy/approval
  -> governed execution
  -> observed business outcome
  -> belief and workflow update
```

Data Agent reuses OS primitives and adds domain contracts, connectors, evaluators and workflow templates. It must not fork its own task runtime, provider layer, plugin system, identity model or governance spine.

The existing `ai-native-business-data-agent-os` repository remains an implementation/history source during transition. It must not be cross-imported at runtime. Migration into `domain_packs/data_agent` requires explicit package-by-package ownership, contract and test reconciliation; this blueprint does not pretend that migration has already happened.

## 9. Research portfolio audit against product needs

### 9.1 Evidence scale

| Level | Meaning |
|---|---|
| E0 | concept, formal argument or docs-only proposal |
| E1 | deterministic unit test or toy mechanism |
| E2 | controlled simulation with meaningful baselines/ablations |
| E3 | offline public/real dataset or realistic replay |
| E4 | shadow mode or controlled customer pilot |
| E5 | production outcome evidence across customers/tasks |

Current research is mostly E1-E3. That is valuable mechanism evidence, but it cannot satisfy E4-E5 product claims.

### 9.2 Line-by-line assessment

| Research line | Product need | Current evidence-limited result | Fit verdict | Portfolio decision |
|---|---|---|---|---|
| Corrigibility shell, C7, audit and gates | non-bypassable pause/override, policy and accountability | strong structural/unit-level patterns; current shell is not a production sandbox or security boundary | **High, partial** | Promote principles; build process/account isolation, signed capabilities, recovery and security tests in Product Track |
| G10 confidence-gated belief->action policy | calibrated act/ask/retry/abstain behavior | decisive win in its frozen synthetic family; no product-workflow validation | **High, narrow** | Revalidate behind a product decision-policy interface on held-out workflows before promotion |
| CWM causal discovery, real-data binding and live-intervention loop | planning interventions and attributing outcomes | useful simulation and offline/controlled real-data progress; live actuation remains dry-run/verify-only and scope-limited | **High for suitable domains, not universal** | Continue for Data Agent/operations; require identifiability and observational fallback; benchmark against non-causal baselines |
| Belief ledger, provenance, conflict and failure attribution | durable trustworthy context and learning | architecture and mechanisms exist; not yet a persistent multi-user product ledger | **Foundational, incomplete** | Highest product priority; implement product schema/storage/API and evaluate correction/staleness behavior |
| Goal formation and self-proposed goals | goal compilation, subgoals and bounded initiative | extrapolated goal routes repeatedly weak; demonstrated/grounded variants more credible | **Medium, immature** | Build human-goal compilation first; limit self-proposed goals to policy-bounded proposals with acceptance tests |
| Temporal options and long-horizon planning | multi-day execution, replanning, recovery | proposal-only/pre-spec work; no established capability gain | **Critical gap** | Make a product-pressure research priority; benchmark on interruption, dependency and recovery tasks |
| Online adaptation and regime shift | provider/tool/environment changes without restart | controlled sim-to-sim and reranking/regime evidence; no real-task forgetting or contamination proof | **High, partial** | Continue with real task streams, stale-memory tests, rollback and held-out post-update evals |
| Ontology/context/world-state construction | typed workflow, tool effects, domain adaptation and explainable state | early ontology/LLM-assisted modeling; no production semantic substrate | **Critical gap** | Productize typed context/action semantics; use LLM as proposer, validators and owners as authority |
| LLM as bounded organ / hybrid cognition | language, broad prior, code and semantic coverage | necessary and useful, but provider fragility/hangs observed; current research restrictions are not a product architecture | **Essential** | Permit LLMs in cognitive paths; deny unscoped final authority; add provider reliability and adversarial evals |
| RAP, subagents and swarms | specialization, parallelism and independent review | RAP did not establish itself as a core intelligence mechanism | **Optional** | Ship governed subagents for measurable workflow value; park swarm-as-foundation claims |
| Viability, endogenous drives, relevance, G-Eco and autonomy-axis search | resource awareness and initiative | substantial negative/inconclusive evidence; narrow experiments do not establish a universal autonomy ontology | **Low near-term product fit** | Harvest budget/surprise/correction ideas; park new metaphysical-axis routes unless tied to a concrete product falsifier |
| Self-modification, OEE and SD4 | system improvement and extensibility | external candidate generation boundaries are useful; runtime/safety self-edit remains unsafe and unproven | **Medium future, low MVP** | Allow L0-L3 candidate generation in Evolution Lab; keep L4 runtime core and L5 safety self-edit forbidden |
| Open-world self-discovery and strong-locus route | low-supervision structure discovery | honest negative/insufficient-data boundaries plus narrow offline progress; oracle dependence remains in important cases | **Long-horizon** | Cap budget and use milestone gates; do not block product; continue only with cheaper discriminating tests or a named product consumer |
| Real-data adapters and evaluation metrics | provider/connector integration and outcome measurement | useful controlled adapters/harnesses; they are not production connectors | **High as substrate, incomplete** | Reuse lessons, build supported Product Track connectors with auth, retries, observability and tenancy |
| CWM-LEARN-5e hard functional forms / knowledge pruning | specialized non-enumerable relation discovery | preregistered positive result in a narrow hard-form channel only | **Narrow** | Preserve as candidate; no product priority until a workflow exposes this exact bottleneck |
| Formal models, lemmas and architecture gates | invariants, falsifiers and safe boundaries | valuable where consumed by executable tests; otherwise can accumulate as theory debt | **Conditional** | Continue only with a named runtime/eval consumer, cheap baseline and stop condition |
| Preregistration, paradigm loop and research workflow | evidence integrity and anti-self-deception | strong internal process contribution | **High internal value, not a product feature** | Keep as development governance; never market it as customer runtime capability |

### 9.3 Direct answer: can current research satisfy product requirements?

**No, not by itself.** It supports several important organs and design constraints, especially correction, belief/action calibration, causal modeling, provenance and evidence discipline. It does not yet provide the complete user experience, durable runtime, workflow system, provider/credential/plugin lifecycle, production knowledge plane, tenancy, reliability or real-world evaluation required by Agent OS.

The correct conclusion is neither "the research failed" nor "the research already proves the product." It has produced reusable hypotheses, mechanisms, negative-result maps and governance patterns. Product engineering must now create the operating body in which a small subset can be tested for actual value.

## 10. Research-product alignment decision

### 10.1 Has research drifted from product needs?

**Yes, partially and materially.** The drift is concentrated in route selection, not in all outputs.

The largest detours were:

- searching for an essential or separable autonomy axis without a product failure that required it;
- treating viability/endogeneity as candidate proof of subjecthood rather than testing whether they improve useful long-horizon behavior;
- extending toy gate ladders after cheap baselines had absorbed the candidate mechanism;
- debating whether C7 is unmodelable instead of engineering non-bypassable authority;
- allowing product architecture to wait on unresolved autonomy ontology;
- over-investing in falsification of narrow internal axes while under-investing in task UX, planning/recovery, provider operations, credentials, plugins, knowledge lifecycle and reliability.

The research did **not** become worthless. Negative results prevented weak mechanisms from being branded as intelligence and revealed that broad baselines often absorb bespoke autonomy stories. That lesson should now change the portfolio.

### 10.2 New admission rule for research

Every new Track R route must answer before authorization:

1. Which observed product or benchmark failure does it address?
2. What is the current product and cheap baseline?
3. Through which stable contract would the product consume a win?
4. What evidence would falsify or park the route?
5. What is the maximum time/compute budget before a decision?
6. Does it threaten correction, privacy, tenancy or product reliability?

Foundational research without an immediate product consumer remains allowed, but it is a bounded option rather than the default roadmap driver.

### 10.3 Portfolio allocation for the current resource reality

Until a credible Agent OS alpha exists, default founder-level allocation should be:

- **70% Product Track:** Task Workspace, workflow IR/editor, runtime, provider/BYOK, tools/plugins, knowledge, eval and Data Agent integration;
- **20% translational moat:** belief ledger, outcome contracts/learning, long-horizon planning/recovery and CWM product comparisons;
- **10% frontier research:** bounded open-world/autonomy hypotheses with explicit kill tests.

This allocation is a planning default, not an evidence claim. It should be revisited when product bottlenecks or real customer outcomes justify a change.

## 11. Comparative evaluation and superiority gates

### 11.1 Three benchmark suites

Agent OS starts with three end-to-end benchmark families:

1. **Personal work:** multi-source research/planning with private knowledge, changing constraints, delayed events and an inspectable deliverable.
2. **Developer work:** issue -> repository understanding -> plan -> code/tool execution -> tests -> reviewable patch/PR artifact, including interruption and recovery.
3. **Enterprise Data Agent:** governed business question -> evidence -> decision/action proposal -> approval/policy -> execution or dry-run -> measured outcome.

Each suite includes happy paths, provider/tool failures, stale/conflicting knowledge, permission denial, ambiguous goals, interrupted runs and adversarial instructions.

### 11.2 Baselines

Comparisons must name and pin:

- leading task-oriented coding/agent products used in the target workflow;
- leading enterprise agent/workflow platforms used in the target workflow;
- direct model-plus-tools baselines without Agent OS mechanisms;
- simple non-causal, non-learning and single-agent ablations;
- the previous released Agent OS version.

The benchmark harness stores versions, provider/model settings, tool scopes, prompts/configuration, retries, cost and evaluator rules. No competitor or internal arm receives hidden data or unfair tools.

### 11.3 Metrics

Primary metrics are verified outcome success and severe failure rate. Supporting metrics include:

- human intervention minutes per accepted outcome;
- time and cost to accepted outcome;
- recovery rate after injected failures;
- calibration of act/ask/abstain decisions;
- policy violations and unauthorized side effects;
- rollback/compensation success;
- evidence completeness and provenance accuracy;
- cross-session retention, staleness and correction quality;
- domain onboarding effort and zero-code transfer rate.

### 11.4 Three Done gates

**Product Done** requires all three golden paths to run end to end through the real Task Workspace, workflow, provider/credential, tool, knowledge, governance and outcome paths, including negative cases and crash recovery. A demo or mocked provider is insufficient.

**Moat Done** requires at least one candidate mechanism to beat the current Agent OS baseline on held-out real workflows with a predefined useful effect, while meeting safety, reliability, latency and cost non-regression gates. CWM, belief ledger and outcome learning are judged separately and in combination.

**Superior Done** requires reproducible wins against named external baselines on a defined workflow envelope, no severe-governance regression, independent reruns and publication of losses as well as wins. It never means "completely superior at all agent tasks."

Until these gates pass, the authorized language is "target," "candidate," "implemented," or "validated in [specific envelope]" rather than "surpassed" or "general autonomous intelligence achieved."

## 12. Product sequence

### Phase A: product spine

- canonical contracts and event model;
- persistent Task Workspace and durable AgentRun;
- provider registry, BYOK credential broker and model routing;
- typed tool/plugin host with policy enforcement;
- WorkflowGraph IR plus natural-language compiler and visual editor foundation;
- ExpectedOutcome/ObservedOutcome and baseline eval harness.

### Phase B: three complete paths

- developer workflow as internal dogfood and Codex-experience benchmark;
- Data Agent migration as the first enterprise domain pack;
- private personal workflow using the same product spine;
- knowledge/context graph, subagents, approvals, recovery and operations surfaces.

### Phase C: outcome compounding

- product belief ledger;
- outcome-based model/tool/workflow selection;
- correction, invalidation and rollback for learned artifacts;
- long-horizon planning/recovery benchmarks.

### Phase D: evidence-gated research promotion

- CWM in qualifying Data Agent/operations workflows;
- G10-like calibrated action policy if product revalidation passes;
- additional mechanisms only through `ResearchCandidateManifest` and held-out comparisons.

Phases define dependency order, not calendar promises. Product work and bounded research can proceed concurrently, but later claims cannot jump earlier gates.

## 13. Non-negotiable boundaries

1. Research evidence and product capability remain separate ledgers.
2. Product runtime never imports raw experiments as authority.
3. Domain packs do not place domain semantics in core contracts or runtime.
4. Credentials and sensitive tenant data never enter model-visible memory by default.
5. Plugins, models and subagents act only through capability-scoped contracts.
6. Correction authority is non-writable and non-bypassable; it is not assumed unmodelable.
7. Low-risk autonomy is policy-configurable; consequential authority remains explicit and auditable.
8. Outcome learning cannot auto-deploy changes to its own safety, permission or correction substrate.
9. LLMs may propose, reason, plan and verify; no untyped model output directly becomes a consequential command.
10. Negative, null and invalid research results keep their exact verdicts.
11. Market-parity features require real entry points, failure paths and tests; contracts or UI shells are not completion.
12. Claims of generality or superiority name an operating envelope and comparison evidence.

## 14. Final product thesis

The project should not try to win by claiming that it has discovered the essence of autonomy. It should win by building the best governed substrate for persistent intelligent work, then using unusually disciplined research to improve the parts that determine verified outcomes.

The architectural thesis is:

```text
Foundation models provide broad priors and generation.
Agent OS provides persistent work state, commitments, capabilities and authority.
Belief and outcome systems provide accountable learning.
Causal models improve selected intervention problems.
Humans and institutions retain correction and legitimacy.
Real comparisons, not internal narrative, decide whether the system is better.
```

That is a credible route toward increasingly general autonomous behavior without making the product wait for a metaphysical proof, and without diluting the long-run ambition into a workflow wrapper.
