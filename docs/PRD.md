# Agent OS Product Requirements

> Status: `ACTIVE / PRODUCT REQUIREMENTS`
> Version: 2.0
> Updated: 2026-07-14
> Product authority: `AGENT-OS-PRODUCT-BLUEPRINT.md`
> Live delivery status: `CURRENT_STATE.yaml`

## 1. Product objective

Agent OS must turn a goal into durable, inspectable and governed work across models, tools, data and time, then bind completion to evidence and observed outcomes.

It must reduce repeated human supervision without transferring final authority or correction power to a model, plugin, subagent or learned procedure.

## 2. Primary users

- Individuals managing multi-step personal/research/creative work.
- Developers changing repositories through reviewable, testable actions.
- Enterprise teams using domain packs such as Data Agent.
- Operators administering identity, providers, capabilities, policy and incidents.
- Domain builders adding semantics and workflows without forking Agent Core.

## 3. Required user outcomes

### R1 — Start correctly

The user can enter through one Agent Surface. The system explains whether a request remains ephemeral `Ask` or becomes durable `Work`. Consequential or long-running work cannot remain in a bypassing chat path.

### R2 — Commit before acting

Work records a goal, constraints, expected outcome, authority scope and workflow before consequential effects. Material changes create versioned commitments rather than rewriting history.

### R3 — Execute through typed capabilities

Models and workflows propose typed capability calls. Consequential effects compile into exact `ActionContract`s and pass deterministic policy/disposer checks. Untyped model text never becomes direct authority.

### R4 — Survive failure and time

Task/Run state is durable. The system supports typed failure, retry, lease recovery, idempotency, effect reconciliation and resumption without duplicate committed side effects.

### R5 — Prove outcomes

Completion binds `ObservedOutcome` to `ExpectedOutcome`, evidence, evaluator version and artifacts. Self-reported success, UI state or a green mock does not complete work.

### R6 — Remain correctable

An external principal can inspect, pause, correct, tighten, reject, compensate, roll back or halt. C7 dominates every model, tool, workflow, subagent and learned artifact.

### R7 — Learn without self-authorizing

Verified outcomes may update context, beliefs, rankings and learned-procedure candidates. Updates are versioned, correctable, evaluated on held-out tasks and promoted externally; they cannot expand their own authority or rewrite their evaluator.

### R8 — Support domain depth

Domain packs can add contracts, connectors, evaluators, policy defaults, knowledge and UI extensions without moving domain semantics into Agent Core or forking the authority spine.

## 4. Functional requirements

| Area | Required behavior |
|---|---|
| Agent Surface | Explainable Ask/Work routing; visible escalation and authority requirements |
| Task Workspace | Goal, commitments, graph, state, evidence, approvals, artifacts, failures and outcomes |
| Runtime | Durable events, deterministic transitions, leases, retry, recovery, idempotency and compensation |
| Providers | Provider-neutral registry/routing, safe CredentialRef, connection health and bounded failure |
| Capabilities | Typed schema, risk/effect metadata, scopes, policy and invocation receipts |
| Workflow | Typed WorkflowGraph, natural-language/visual/structured round-trip and versioning |
| Evidence/outcomes | ExpectedOutcome, ObservedOutcome, evaluator, provenance and failure attribution |
| Authority | Policy/disposer, approvals, C7, budgets and tenant/organization bounds |
| Knowledge/beliefs | Provenance, uncertainty, conflict, staleness, correction, invalidation and downstream refs |
| Adaptation | Candidate-only learning, held-out eval, independent promotion, canary and rollback |
| Admin/ops | Identity, tenancy, policy, audit, observability, backup/restore and incident controls |
| Domain packs | Isolated domain semantics over shared OS primitives |

## 5. Non-functional requirements

- **Safety:** no authority or secret bypass; deny by default on unknown risk/policy states.
- **Reliability:** durable state, reproducible transition semantics and bounded recovery.
- **Security/privacy:** least privilege, credential isolation, tenant separation, safe audit projection and data minimization.
- **Explainability:** expose decisions, evidence and authority without requiring private chain-of-thought.
- **Portability:** provider-neutral contracts and clear adapter boundaries.
- **Performance:** measure latency, cost, model/tool calls and human intervention per accepted outcome.
- **Operability:** health, metrics, traces, incident recovery, migrations and version compatibility.
- **Correctability:** correction and rollback remain available across updates and failures.

## 6. Domain-pack requirements

Data Agent is the first official domain pack. It must reuse the common Task/Run, provider, capability, identity, authority, evidence and outcome primitives.

Data-specific contracts such as Metric, SemanticObject, ProviderContract, DataProduct, SQL and business action remain inside the pack. Data Agent may project its `EvidenceChain` into generic Agent OS evidence but may not redefine OS core.

ADR-0054/SPINE-1 governs the one-time donor migration. Planning authorization is not execution, merge or release authorization.

## 7. Research-promotion requirements

A Research Track candidate is product-admissible only when it has:

1. a named product failure or measurable opportunity;
2. a stable Product Track consumption contract;
3. a current fair baseline and necessary ablations;
4. held-out evidence in the intended workflow envelope;
5. safety, reliability, latency and cost non-regression gates;
6. versioning, monitoring, rollback and a non-self-approval promotion path;
7. an explicit statement of what the research result does not prove.

CWM, G10-like policies, belief mechanisms or learned procedures receive no special exemption.

## 8. Acceptance contract for every slice

Before a slice is called implemented or complete, answer:

- **Entry point:** which real API/CLI/UI/function invokes it?
- **Contract:** what typed input/output or schema is consumed/produced?
- **Failure:** what happens for unsafe, invalid, missing, denied or unsupported input?
- **Bypass:** which test fails if the new behavior is skipped or replaced with a constant/mock?
- **Integration:** where is it connected to the real Task/Run/capability/evidence/outcome path?
- **Observability:** what event, trace, evidence or outcome proves behavior?
- **Authority:** who may invoke, approve, promote, roll back and correct it?
- **Claim state:** specified, implemented, tested, integrated, verified, released or generally validated?

## 9. Product-level gates

### Golden-path gate

Developer, personal and Data Agent paths each complete through real providers/capabilities, durable Runtime, evidence/outcome and negative cases.

### Alpha gate

The three paths share one authority spine and recover from interruption, provider/tool failure, stale/conflicting knowledge and permission denial.

### Production gate

Identity, tenancy, encrypted credentials, policy administration, deployment, observability, backup/restore, incident response and real-user evidence meet explicit release criteria.

### Moat gate

At least one Agent OS mechanism beats a simpler fair baseline on held-out valuable work without unacceptable safety, reliability, cost or latency regression.

Product gates do not prove general autonomy or AGI; those claims follow the parent Goal Blueprint and RR-0024.

## 10. Explicit non-goals

- Model or plugin final authority.
- Runtime self-rewrite or safety-substrate self-edit.
- Universal CWM use.
- Domain semantics in Agent Core.
- Automatic publication of learned procedures.
- External agent framework as the core authority/runtime model.
- Claiming completion from contracts, UI shells, mock providers, fixture-only tests or research results.
