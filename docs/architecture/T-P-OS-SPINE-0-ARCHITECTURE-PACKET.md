# T-P-OS-SPINE-0 Executable Product Spine Architecture Packet

> Date: 2026-07-10
> Status: DESIGN ACCEPTED / INDEPENDENT CLAUDE RE-REVIEW APPROVE / IMPLEMENTATION PLAN NEXT
> Track: Product Track
> Product authority: `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
> Research boundary: `docs/research/AGENT-OS-RESEARCH-GAP-AND-BOTTLENECK-AUDIT-2026-07-10.md`
> Successor migration: `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`
> Cross-repository ADR: `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`
> Selected option: B - history-preserving migration plus modular monolith

## 0. Decision and authority

This packet defines the first executable Product Track body of Agent OS. It refines the
Blueprint target layout into an implementable modular monolith. The founder's Option B
decision remains the program migration strategy, but its execution is now separated from
SPINE-0:

```text
SPINE-0: prove the generic durable spine through one developer golden path.
SPINE-1: preserve the safe, approved history of ai-native-business-data-agent-os,
import it once, extract generic product capabilities, and move data semantics into
domain_packs/data_agent under ADR-0054.
```

Authority order for Product Track implementation is:

1. `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` for product identity and non-negotiable boundaries;
2. this packet for `T-P-OS-SPINE-0` architecture and acceptance;
3. accepted Product Track ADRs, including ADR-0054 for any cross-repository migration;
4. the reviewed implementation plan and tests for file-level execution;
5. historical `REF-ARCH-*` documents as Research Track references only.

This packet does not by itself authorize runtime code changes, donor migration, experiment
execution, deployment, a product-readiness claim, or a research promotion. Independent
Claude remediation re-review returned `APPROVE`. The next artifact is a separate,
test-first SPINE-0 implementation plan; implementation starts only after that plan's gate.

## 1. Objective, scope and non-goals

### 1.1 Objective

Deliver one real, restart-safe vertical slice:

```text
Goal
  -> negotiated Commitment
  -> immutable WorkflowGraph version
  -> durable AgentRun
  -> provider reasoning through CredentialRef
  -> typed capability calls
  -> deterministic policy/correction enforcement
  -> ExpectedOutcome evaluation
  -> ObservedOutcome with evidence
  -> persisted Task Workspace state
```

The slice is the first product runtime and the next research instrument. It must expose
a real API, CLI and minimal Task Workspace UI; survive process restart; exercise a live
OpenAI-compatible provider outside hermetic CI; perform real sandboxed tool effects; and
record a verified outcome rather than reporting model narration as success.

### 1.2 First vertical

The developer golden path is a sandboxed repository task:

1. read a repository fixture through a typed workspace capability;
2. ask a provider to produce a typed patch proposal;
3. admit or deny the proposed action through `PolicyKernel`;
4. apply the patch through an idempotent workspace capability;
5. run an allowlisted verification command;
6. record the command output and artifact digest as evidence;
7. evaluate the precommitted acceptance rule;
8. expose the final state and artifacts in the Task Workspace.

The first enterprise seam is the successor `T-P-OS-SPINE-1`: a Data Agent workflow calls a
versioned `data_agent.trusted_loop.evaluate` capability after history-safe donor migration
and package extraction. It must use the same task, run, policy, event and outcome contracts
as the developer path, but it is not a SPINE-0 completion condition.

### 1.3 Non-goals

`T-P-OS-SPINE-0` does not attempt to deliver:

- the complete visual Workflow Studio or plugin marketplace;
- arbitrary shell access, browser control or unbounded computer use;
- production KMS, SSO, private networking or compliance certification;
- multi-region scheduling, Kafka, Temporal, microservices or a graph database;
- automatic consequential enterprise actions;
- Data Agent donor import, package extraction or shared-spine seam acceptance; these belong
  to `T-P-OS-SPINE-1` under ADR-0054;
- product belief learning, CWM promotion, G10 promotion or subagent swarms;
- desktop packaging or all three Blueprint golden paths;
- a claim of Codex parity, Product Done, Moat Done or Superior Done.

## 2. Governing architecture decisions

| ID | Decision | Consequence |
|---|---|---|
| D1 | Start as a modular monolith | one deployable API, one worker family and one PostgreSQL authority; module boundaries remain explicit |
| D2 | Use one canonical contract package | API, worker, UI schemas, CLI and domain packs bind the same versioned objects |
| D3 | Use append-only task events plus relational projections | durable replay/audit without event-sourcing every domain object or adding Kafka |
| D4 | Separate semantic ranking from authority | `DecisionPolicy` advises; deterministic `PolicyKernel` admits/denies/escalates; `CapabilityBroker` executes |
| D5 | Put correction authority outside acting cognition | model, agent, workflow and plugin code cannot write correction state or mint approvals |
| D6 | Treat CWM as an optional port | no Product Track dependency on a universal causal brain; every world model declares applicability and fallback |
| D7 | Store references, never secrets, in product objects | `CredentialRef` crosses contracts; secret resolution occurs only inside the credential/capability boundary |
| D8 | Freeze workflow versions per run | edits create a new version or an explicit bounded replan; active history is never silently rewritten |
| D9 | Freeze expected evaluators before consequential action | tool acknowledgement is not outcome proof; evaluator/version drift is visible |
| D10 | Preserve only history that passes the ADR-0054 safety gate | SPINE-1 uses direct no-squash import only after full-history `PASS`; otherwise a filtered migration mirror or `ABORT`; no runtime federation |
| D11 | Keep current `src/aac` and `experiments` in Research Track | Product Track consumes only stable ports and promoted/reimplemented candidates |
| D12 | Start with web workspace and CLI | desktop packaging is deferred until the task/runtime contract is stable |
| D13 | Make side-effect guarantees connector-specific | controlled connectors can enforce commit-time epochs; external APIs receive dispatch-time guarantees plus cancel/compensate |
| D14 | Do not auto-deploy learning | observed outcomes may create proposals; policy, workflow, routing or memory changes require eval and promotion |

## 3. Logical architecture

```text
Task Workspace / CLI / Public API
                |
                v
       Task + Commitment service
                |
                v
    Workflow compiler/version store
                |
                v
      Durable Run Coordinator  <-------- Task event stream
                |
        +-------+---------+
        |                 |
        v                 v
 DecisionPolicy       Outcome/Evidence
   (advisory)          evaluator service
        |
        v
    PolicyKernel <---------- Approval + CorrectionAuthority
        |
        v
  CapabilityBroker
   +----+------+-------------------+
   |           |                   |
ProviderPort  ToolPort         DomainPack capability
   |           |                   |
Credential   sandbox             Data Agent
  Broker     workspace           trusted loop

Persistent substrate: PostgreSQL events, projections, leases, outbox,
artifacts and immutable contract/version references.

Optional research/product ports, initially baseline-only:
WorldModelPort | BeliefUpdatePort | OutcomeAttributionPort
```

### 3.1 Authority flow

The Product Track does not use a contentless disposer as a semantic oracle.

1. A provider, rule or model organ emits typed proposals and evidence.
2. `DecisionPolicy` ranks or recommends among the declared candidate envelope. Its output
   is advisory, versioned and auditable.
3. `PolicyKernel` checks identity, tenant, capability scope, risk, budget, approvals,
   correction epoch, workflow version and evidence requirements. It returns only
   `ALLOW`, `DENY` or `ESCALATE` plus typed reasons.
4. `CapabilityBroker` accepts only an admitted, version-bound `ActionContract` and invokes
   the named provider/tool/domain capability.
5. The executor returns an `ActionReceipt`; outcome evaluation remains separate.

No model output, workflow node, plugin or domain pack can call a side-effect connector
outside `CapabilityBroker`.

### 3.2 Candidate-generation envelope

Open action spaces cannot prove that a full choice set was considered. Every decision
therefore records a `CandidateGenerationEnvelope`:

- generator and version;
- allowed action/tool classes;
- resource and search budget;
- candidate identifiers and dominance/deduplication result;
- excluded classes and reasons;
- coverage evidence appropriate to the task;
- whether abstain, ask and no-action candidates were present.

The envelope enables honest coverage comparison. It does not claim exhaustive search.

## 4. Physical monorepo target

The Blueprint's conceptual packages are implemented initially as fewer cohesive Python
packages to reduce coordination and deployment cost:

```text
apps/
  api_server/                 # FastAPI public API, SSE and principal-auth entry
  worker/                     # leased durable run and outcome workers
  workspace/                  # Next.js Task Workspace
  cli/                        # local/developer command surface

packages/
  contracts/                  # canonical Pydantic/JSON schemas and migrations
  os_core/
    task/                     # Goal, Commitment and Task lifecycle
    workflow/                 # WorkflowGraph validation, patching and execution
    runtime/                  # AgentRun coordinator and node state machine
    decision/                 # DecisionPolicy ports and baseline policy
    capability/               # broker, tool/provider/domain capability registry
    provider/                 # ProviderPort, routing and typed failures
    credentials/              # CredentialRef and broker interfaces
    knowledge/                # artifact/evidence/context ports; no learning yet
    governance/               # PolicyKernel, approval and correction checks
    outcome/                  # expected/observed outcome and evaluator registry
  persistence/                # PostgreSQL repositories, event store, leases, outbox
  sdk/                        # domain-pack, workflow, tool and provider authoring SDK

domain_packs/
  data_agent/                 # migrated first enterprise vertical
  developer_agent/            # repository task defaults and sandbox tools
  personal/                   # reserved; no T-P implementation requirement

research/                     # future normalized Research Track layout
src/aac/                      # preserved current Research Track implementation
experiments/                  # preserved experiments and exact result history
tests/
  product/
  contracts/
  integration/
  security/
  comparative/
  research/                   # current tests may be moved only under a later plan
```

Hyphenated Blueprint package names remain conceptual ownership labels. Importable Python
modules use `snake_case`. Splitting `os_core` into independently released packages is
deferred until measured team, scaling or isolation pressure justifies it.

For SPINE-0, only `developer_agent` must be implemented. `domain_packs/data_agent` in this
tree is the post-SPINE-1 target location; an empty directory, copied contract or placeholder
does not count as Data Agent migration or seam delivery.

### 4.1 Dependency rule

```text
apps -> sdk/os_core/persistence/contracts
domain_packs -> sdk/contracts
sdk -> contracts
os_core -> contracts and declared ports
persistence -> contracts and repository ports
contracts -> Python/Pydantic standard dependencies only

Forbidden:
Product Track -> src/aac, experiments, raw research results, _migration staging
os_core -> domain_packs
domain_pack A -> domain_pack B internals
provider/tool/plugin -> persistence internals or correction writes
```

Dependency checks become CI gates. Domain capabilities register through the SDK and typed
contracts; they do not add domain conditionals to `os_core`.

### 4.2 Technology baseline

| Concern | T-P baseline | Deferred trigger |
|---|---|---|
| backend/runtime | Python 3.11+, FastAPI and Pydantic; no external agent framework in core authority paths | change only for measured capability, security or operations need |
| worker | same Python codebase, separate worker process using database leases | separate services after measured isolation/scale pressure |
| persistence | PostgreSQL with an in-memory test adapter | specialized stores only after a named query/scale bottleneck |
| frontend | Next.js + TypeScript Task Workspace | desktop shell after public task/runtime contracts stabilize |
| event delivery | PostgreSQL outbox plus SSE to workspace/CLI | message broker after measured throughput/fan-out need |
| artifacts | workspace-local adapter for T-P, object-store port retained | managed object storage for multi-user deployment |
| first provider | OpenAI-compatible HTTP adapter behind `ProviderPort` | additional native adapters through the same contract |

The implementation plan must reconcile exact library versions with the imported donor
lockfiles. This packet fixes architectural dependencies, not package-version pins.

## 5. Canonical contracts

All public objects carry `schema_version`, immutable identifier, tenant/workspace scope,
creation metadata and explicit references. Unknown fields are rejected at authority
boundaries until a declared compatibility policy says otherwise.

| Contract | Required meaning |
|---|---|
| `Goal` | principal-issued desired state, constraints and source; not an agent-generated score |
| `Commitment` | accepted scope, deliverables, acceptance criteria, budget, authority and expiry negotiated against a Goal |
| `WorkflowGraph` | immutable, canonical executable graph version plus policy/evaluator references |
| `GraphPatch` | typed, optimistic-concurrency edit from NL, visual or structured surface |
| `AgentRun` | one execution of a frozen Commitment and WorkflowGraph version |
| `NodeRun` | durable activation state, attempt, lease and typed input/output refs |
| `CandidateGenerationEnvelope` | bounded search/generation declaration and considered choices |
| `ActionContract` | proposed capability, typed arguments, risk, idempotency key, policy/correction epochs and expected effect |
| `ActionPermit` | short-lived PolicyKernel admission bound to exact action digest, identity, lease fence and epochs |
| `ActionReceipt` | dispatch/acknowledgement/unknown/failure record; never outcome proof by itself |
| `CapabilityGrant` | principal/tenant-scoped permission for a provider, tool or domain operation |
| `CredentialRef` | non-secret reference, owner/scope/provider metadata and lifecycle status |
| `ProviderProfile` | endpoint class, model capability, limits and routing metadata; no secret value |
| `PolicyDecision` | `ALLOW`, `DENY` or `ESCALATE` with policy version and typed reasons |
| `CorrectionState` | externally written epoch and run/task/capability halt scope |
| `ApprovalDecision` | actor-bound approval/revise/reject result over an immutable action digest |
| `TaskEvent` | append-only, sequenced state transition with correlation and causation IDs |
| `ArtifactRef` | content digest, media type, location class, ACL and retention metadata |
| `EvidenceRef` | source/provenance relation to artifacts, events or external observations |
| `EvidenceChain` | reserved generic grouping of evidence refs, claims, methods, observations, limitations, confidence and artifact bindings; SPINE-0 uses evidence primitives and does not require the full grouped schema |
| `ExpectedOutcome` | pre-action evaluator/version, threshold, evidence requirements and observation window |
| `ObservedOutcome` | measured result, evaluator output, evidence, confidence and unresolved gaps |

`Belief`, `ContextGraph`, `LearningProposal` and causal attribution contracts are reserved
extension points. They are not required for T-P completion and cannot be faked by storing
untyped text in a product ledger.

### 5.1 Versioning and canonicalization

- JSON Schema is the external contract; Pydantic models are the first Python binding.
- Canonical JSON uses sorted object keys, normalized enums/timestamps and no implicit
  defaults before SHA-256 digesting.
- Breaking schema changes require a new major version and deterministic migration.
- A run binds exact commitment, graph, policy, provider profile and evaluator versions.
- A serializer round trip must preserve semantic fields and canonical digest.
- Human-readable labels never serve as identity or authorization.

## 6. WorkflowGraph v1

### 6.1 Static representation

`WorkflowGraph v1` is a validated static graph with typed nodes and edges. The definition
is acyclic at the outer level. Repetition is represented only through a bounded `loop` or
`map` node whose iteration limit, body reference, stop predicate and budget are explicit.

Required initial node families are:

- `provider`;
- `tool`;
- `transform`;
- `decision`;
- `approval`;
- `evaluation`;
- `wait_event`;
- `loop` with a finite bound;
- `parallel_map` with a concurrency bound;
- `subworkflow` pinned to a version;
- `terminal`.

Every executable node declares input/output schemas, timeout, retry class, idempotency,
failure edge, risk tier and required capability. A node with a side effect must emit an
`ActionContract`; it cannot embed an untyped command.

### 6.2 Three editing surfaces

Natural-language, visual and structured editors all emit `GraphPatch` against an expected
graph revision. They never write an executable graph directly.

```text
user edit
  -> draft GraphPatch
  -> schema + semantic validation
  -> explicit diff including policy/evaluator/capability changes
  -> user or authorized policy acceptance
  -> new immutable WorkflowGraph version
```

A natural-language compiler is a proposer. The visual editor is a projection over the
same graph. A conflict or information-losing edit is rejected; it is not silently merged.
`WFG-ROUNDTRIP-1` remains a later product-eval gate and is not passed by this document.

### 6.3 Replanning

T-P permits only bounded replanning at declared decision/replan nodes. A replan produces
a new graph version and a `RunPlanRebound` event that names preserved, invalidated and
new node activations. Completed side effects are never erased from history.

## 7. Durable state and execution

### 7.1 Aggregate state machines

Task aggregate:

```text
DRAFT -> COMMITTED -> RUNNING -> VERIFYING -> COMPLETED
                         |            |
                         v            v
                      WAITING       FAILED
                         |
                         v
                       PAUSED

From non-terminal states: CANCELLED where policy permits.
WAITING/PAUSED may return to RUNNING after the recorded condition is satisfied.
```

AgentRun:

```text
CREATED -> QUEUED -> RUNNING -> VERIFYING -> SUCCEEDED
                        |           |
                        +-> WAITING_APPROVAL
                        +-> WAITING_EVENT
                        +-> PAUSED
                        +-> FAILED
                        +-> CANCELLED
```

NodeRun:

```text
PENDING -> READY -> RUNNING -> SUCCEEDED
                       |          |
                       +-> WAITING_APPROVAL
                       +-> WAITING_EVENT
                       +-> FAILED
                       +-> COMPENSATING -> COMPENSATED
                       +-> SKIPPED
```

All transitions are enumerated and append a `TaskEvent`. Invalid transitions fail closed.

### 7.2 PostgreSQL authority

The initial persistence layer uses PostgreSQL for:

- task, commitment and immutable workflow versions;
- run/node projections;
- append-only `task_events` with per-run sequence numbers;
- action contracts, permits and receipts;
- expected and observed outcomes;
- worker leases with fencing tokens;
- idempotency records;
- approval and correction metadata;
- transactional outbox and delivery attempts;
- credential reference metadata only;
- artifact/evidence metadata; artifact bytes may use local/object storage adapters.

An in-memory adapter is allowed for unit tests but is not acceptance evidence for restart
or concurrency behavior.

### 7.3 Worker and transaction model

1. The coordinator writes state transition, projection change and outbox entry in one
   database transaction.
2. A worker claims a ready node with a time-bounded lease and monotonic fencing token.
3. Before dispatch, the broker verifies lease, action digest, capability grant, policy
   version, approval and current correction epoch.
4. The broker records dispatch intent and idempotency key before the external call.
5. The connector returns a typed receipt. Retry reuses the same logical idempotency key.
6. A crash with unknown external state becomes `UNKNOWN_OUTCOME`; it is reconciled through
   connector lookup, compensation or human decision, never silently retried as new work.
7. Rehydration uses the durable projection and missing event tail; model conversation is
   context data, not the state machine authority.

Kafka, Temporal and a separate scheduler service are not required. PostgreSQL polling,
`SKIP LOCKED`, leases and an outbox are sufficient until measured load proves otherwise.

### 7.4 Side-effect guarantee levels

The system does not claim universal exactly-once physical side effects.

| Connector class | Guarantee |
|---|---|
| transactional/internal | correction epoch and idempotency checked at side-effect commit; zero commits under a stale permit |
| idempotent external API | at-most-one logical action under stable idempotency key; correction prevents new dispatch |
| cancellable/compensatable external API | correction prevents new dispatch and triggers cancel/compensate for in-flight work |
| idempotent/cancellable sandbox | correction prevents new dispatch; in-flight work is terminated where possible and all persistent changes are compensated from an immutable sandbox snapshot; no cross-system atomicity claim |
| non-idempotent/non-queryable external API | unsupported for automatic consequential execution; require human confirmation or dry-run |

This envelope is part of `ToolSpec` and visible to policy and the user.

## 8. Provider, credentials and capabilities

### 8.1 ProviderPort v1

The first adapter is OpenAI-compatible and implements:

- typed request/response and tool-call proposals;
- explicit model/profile selection;
- connect/read/overall timeouts;
- stream completion/abort semantics;
- typed `RATE_LIMITED`, `TIMEOUT`, `MALFORMED`, `REFUSED`, `UNAVAILABLE` and
  `AUTHENTICATION_FAILED` errors;
- bounded retry and optional fallback selected by policy;
- cost/usage metadata without secret or sensitive prompt leakage.

Hermetic CI uses a deterministic test provider for contract and failure injection. A
release candidate must also pass an opt-in live-provider end-to-end smoke through the same
`ProviderPort` and `CredentialRef` path. Fake-provider success alone cannot complete T-P.

### 8.2 Credential boundary

Product contracts and PostgreSQL store only `CredentialRef` and non-secret metadata.

For T-P:

- `EnvCredentialBroker` resolves an allowlisted reference to an environment variable for
  local development and CI secret injection;
- secret bytes are returned only to the provider/connector adapter and are never placed in
  prompts, graph JSON, events, traces, errors or artifacts;
- redaction uses both structural filtering and secret-value canaries in tests;
- revocation marks the reference unusable and invalidates cached resolutions.

Production keychain/KMS and user BYOK setup are later adapters behind the same interface.
`EnvCredentialBroker` is not described as production secret management.

### 8.3 CapabilityBroker and tools

Every provider, tool and domain operation registers a `CapabilitySpec` containing input
and output schema, side-effect level, idempotency support, credential class, data boundary,
risk tier, timeout, cancellation/compensation behavior and audit policy.

The developer vertical initially exposes only workspace-scoped capabilities:

- `workspace.read`: read-only, no side effect;
- `workspace.apply_patch`: `idempotent/cancellable sandbox`, using a stable action key,
  immutable pre-action snapshot and compensation on correction/failure;
- `workspace.run_tests`: `idempotent/cancellable sandbox`, running in a disposable copy,
  terminating on correction and persisting only a typed result artifact;
- `artifact.read`: read-only;
- `artifact.write`: `idempotent/cancellable sandbox`, content-addressed and compensatable.

These local filesystem/process operations are not classified as
`transactional/internal`: PostgreSQL correction state and filesystem/process effects do
not share one atomic commit. Their honest guarantee is no new dispatch after correction,
best-effort cancellation and verified compensation inside the disposable sandbox. Only a
future connector with a real shared commit boundary may claim stale-epoch zero-commit.

Path traversal, symlink escape, undeclared executable, network egress and writes outside
the sandbox fail closed. A general shell tool is outside T-P.

## 9. Governance and correction boundary

### 9.1 Principals and enforcement

The human or organization is a principal that issues goals, grants authority and records
approval/correction. The principal is not the enforcement mechanism. `CorrectionAuthority`
stores and serves the externally written correction epoch; `PolicyKernel` and the broker
enforce it.

The acting worker/model/plugin identity cannot:

- update correction state;
- mint or alter approval decisions;
- grant itself capabilities;
- change the policy version bound to an action;
- resolve arbitrary credential references;
- write outcome evaluator results directly.

For the low-risk T-P sandbox, these are separate application roles and database write
paths with adversarial tests. Before consequential deployment they require separate
service identity/database privileges or an equivalent external enforcement boundary.

### 9.2 Correction epochs and races

Each `ActionContract` and `ActionPermit` binds the observed correction epoch. The broker
checks the latest epoch immediately before dispatch. Controlled connectors recheck it at
commit. A stale lease or stale epoch fails closed.

For a connector, including the SPINE-0 sandbox tools, that cannot atomically recheck Agent
OS correction state at its physical side-effect commit, the honest guarantee is "no new
dispatch after correction commit," not "no effect can occur after correction commit."
In-flight risk, cancellation and compensation behavior must be declared and used by
policy. Unsupported irreversible connectors remain proposal-only.

## 10. Outcome, evidence and learning boundary

An `ExpectedOutcome` is accepted with the Commitment or frozen before its first relevant
side effect. It names evaluator type/version, evidence requirements, threshold, observation
window and failure semantics.

The developer slice uses deterministic evidence:

- patch/artifact content digests;
- allowlisted test command exit status and captured output reference;
- required file/schema assertions;
- run/event completeness.

An `ActionReceipt` can show that a tool accepted or completed a call. Only the evaluator
can create the measured portion of `ObservedOutcome`. Provider self-report is supporting
evidence at most.

Outcome data may generate a `LearningProposal` after T-P, but cannot automatically alter
PolicyKernel, correction, credential scopes, workflow versions, evaluators or promoted
memory. `OUTCOME-CREDIT-1` governs later outcome learning.

## 11. Research promotion ports

Research mechanisms may enter Product Track only through stable interfaces:

| Port | Baseline T-P implementation | Candidate route |
|---|---|---|
| `DecisionPolicyPort` | explicit rule/provider ranking with no authority | G10-like calibrated act/ask/retry policy |
| `WorldModelPort` | no-op/declared not applicable | qualifying CWM implementations |
| `BeliefUpdatePort` | evidence/artifact append only; no adaptive belief influence | persistent governed belief ledger |
| `OutcomeAttributionPort` | deterministic evaluator result, no causal credit | delayed/causal outcome attribution |

Every non-baseline implementation requires a `ResearchCandidateManifest`, product task
baseline, operating envelope, rollback and held-out revalidation. Product code never
imports experiment runners or interprets result JSON as executable authority.

## 12. Domain pack contract

A domain pack may contribute:

- versioned capability/tool registrations;
- workflow and agent templates;
- contract extensions under its own namespace;
- provider/connectors and credential requirements;
- knowledge ingestion and context policies;
- evaluators, fixtures and comparative tests;
- UI extensions through declared slots.

A domain pack may not:

- fork task, run, event, identity, policy, approval or correction semantics;
- write core database tables except through SDK/repository interfaces;
- bypass `CapabilityBroker`;
- introduce domain fields into generic core contracts;
- claim product-wide promotion from a vertical result.

`data_agent` owns Metric/Semantic/DataProduct/SQL Safety, data-specific evidence adapters
and business action semantics. The generic spine owns Goal, Commitment, WorkflowGraph,
AgentRun, capability, credential, policy, correction, task events, generic evidence
primitives and outcome envelopes. Data Agent `EvidenceChain` is a projection into generic
Agent OS evidence, not a model that imports SQL/metric vocabulary into OS Core.

## 13. Successor SPINE-1 migration architecture

Data Agent migration is an approved program decision but not part of SPINE-0 completion.
Its execution authority and gates are `ADR-0054` plus
`docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`.

### 13.1 Import rule

After SPINE-0 acceptance and every ADR-0054/migration-map gate, the SPINE-1 branch will:

1. pin the reviewed full donor commit of `ai-native-business-data-agent-os`;
2. scan the donor's complete reachable history for secrets, customer/PII data, oversized
   objects and licensing/provenance exceptions;
3. import directly without `--squash` only after a `PASS`; for `REMEDIATE`, build and
   rescan a filtered migration mirror; for `ABORT`, stop;
4. add the accepted donor or filtered mirror once under `_migration/data-agent-os` and
   record provenance/old-to-new commit mapping where filtering changed SHAs;
5. move/extract generic code into Product Track packages and data-specific code into
   `domain_packs/data_agent` using reviewable commits;
6. prohibit all runtime imports from `_migration/data-agent-os`;
7. remove the staging tree after extraction while retaining only approved history.

The observed donor head during design was short ref `a406508`; it is not the execution
pin. The implementation plan must resolve and record a full immutable commit after review.

### 13.2 What is reused

Candidate generic donors include existing real `AgentRunContext`, `ToolSpec`, runtime
policy gate, checkpoints, workflow persistence, tenant/RBAC, approvals, traces, FastAPI,
PostgreSQL and Next.js surfaces. Reuse is conditional on contract reconciliation,
domain-independence and negative-path tests; donor presence is not automatic acceptance.

Data-specific trusted-loop, semantic/data contract, SQL safety, evidence-chain and
business operation code moves to `domain_packs/data_agent`.

Release documents, stale governance and duplicate product identity text remain reachable
as Git history/provenance but are not copied into a new authoritative docs tree by default.
Only records required to explain retained behavior are re-homed, with explicit
`HISTORICAL_NON_AUTHORITY` metadata. Exact mapping is machine-readable in the migration
YAML.

## 14. Public surfaces for T-P

### 14.1 API

The minimum versioned API surface is:

- create/read a task and commitment;
- create/validate/read a WorkflowGraph version;
- start/read a run;
- stream sequenced run events through SSE;
- pause, resume and cancel where state/policy permit;
- submit an approval/correction through principal-authenticated paths;
- read artifacts, evidence and observed outcome.

Mutation endpoints use idempotency keys and optimistic concurrency. Public responses never
expose secret values, raw internal exceptions or cross-tenant identifiers.

### 14.2 CLI

The CLI covers local task creation, workflow validation, run start/watch, pause/resume,
artifact inspection and outcome display through the public service/SDK contract. It does
not create a second execution path.

### 14.3 Task Workspace UI

The minimal web workspace shows and operates the actual task aggregate:

- goal and commitment;
- immutable workflow version and active node;
- streaming events and typed failures;
- approval/correction controls allowed to the current principal;
- artifacts/evidence;
- expected and observed outcome.

It is an operational surface, not a marketing page. A decorative mock disconnected from
the API does not satisfy acceptance.

## 15. Failure model

| Failure class | Runtime behavior |
|---|---|
| invalid contract/graph/transition | reject before persistence or append explicit rejection; never execute |
| missing/revoked credential | typed `CREDENTIAL_UNAVAILABLE`; wait for principal or fail by workflow policy |
| policy denial | terminal denied node/action with reason; never retry |
| approval required | enter `WAITING_APPROVAL`; immutable action digest must match later approval |
| correction/stale lease | fail closed, revoke pending dispatch, cancel/compensate when supported |
| provider timeout/429/unavailable | bounded typed retry/fallback; preserve attempt/cost events |
| malformed provider output | reject typed proposal; no tool dispatch |
| transient tool error | retry only if ToolSpec and idempotency allow it |
| unknown external outcome | reconcile, compensate or escalate; never report success or issue a fresh logical action |
| evaluator error/missing evidence | outcome remains unresolved/failed, not successful |
| projection/event mismatch | quarantine run and rebuild projection from verified event sequence |
| process restart | new worker acquires a higher fence and resumes from durable node state |

Retries are policy, not a catch-all. Authorization, validation, correction and deterministic
contract errors are non-retryable.

## 16. Threat model and deployment boundary

Primary protected assets are tenant data, credentials, repository files, approvals,
correction state, action authority, event integrity and outcome evidence.

Required T-P attacks and controls include:

- prompt injection requests a forbidden tool: typed capability/policy denial;
- model fabricates tool success: receipt/evaluator separation;
- worker replays an approved action: immutable action digest and idempotency record;
- worker races a pause: lease fence and correction epoch checks;
- plugin reads another tenant: scope-bound capability and repository query guards;
- path/symlink escape: sandbox canonical-path checks and deny-by-default filesystem;
- secret appears in output/error: structural redaction plus canary scanning;
- forged approval: principal identity and approval-to-action digest binding;
- event deletion/reordering: append-only sequence and integrity checks;
- domain pack bypasses broker: dependency and integration tests fail build.

T-P is authorized only for local/controlled low-risk sandbox work. Consequential external
actions, public multi-tenant deployment and enterprise claims require later security,
identity, operations and release gates.

## 17. Acceptance contract

`T-P-OS-SPINE-0` is complete only when all of the following are evidenced:

1. **Entry point:** API, CLI and Task Workspace invoke the same real task/run path.
2. **Contracts:** Goal through ObservedOutcome use versioned canonical contracts and exact
   graph/policy/evaluator references.
3. **Live provider:** an opt-in live OpenAI-compatible run resolves a real `CredentialRef`;
   hermetic tests cover the same port and failure classes.
4. **Real tools:** the developer fixture performs real sandbox read/patch/test effects.
5. **Denial path:** an invalid graph, forbidden path/tool and missing capability each fail
   before side effect.
6. **Durability:** a worker is terminated after a committed node; another worker resumes
   and reaches the same terminal state.
7. **Idempotency:** retry/restart creates zero duplicate logical patch/tool actions; unknown
   external state is not reported as success.
8. **Correction:** stale workers cannot dispatch after correction. Transactional connectors
   commit zero effects under a stale epoch. SPINE-0 sandbox connectors are instead tested
   for no new dispatch, bounded cancellation and verified compensation from an immutable
   snapshot; they do not claim cross-system atomicity.
9. **Secrets:** credential values are absent from prompts, graph JSON, database events,
   traces, errors and artifacts under canary tests.
10. **Outcome:** success resolves to a precommitted evaluator and evidence; tool/provider
    acknowledgement alone cannot pass.
11. **SPINE-1 readiness boundary:** Product Track exposes a versioned domain-capability
    registration contract exercised by `developer_agent`; no donor code, staging import or
    Data Agent success is required or claimed by SPINE-0.
12. **Boundary:** Product Track has no import from `src/aac`, `experiments` or `_migration`.
13. **Observability:** every state/action/outcome is correlated in the task event stream,
    including failures and approvals.
14. **Test validity:** removing PolicyKernel, credential broker, event persistence,
    idempotency or evaluator consumption makes at least one acceptance test fail.

Passing this contract establishes one executable product spine. It does not establish the
full market-parity layer or any research superiority claim.

## 18. Verification strategy

Implementation follows test-first slices:

1. contract and canonicalization tests;
2. state-machine and invalid-transition tests;
3. PostgreSQL event/projection/lease/idempotency integration tests;
4. policy/correction race and replay tests;
5. credential non-observability and tenant-isolation tests;
6. provider chaos and malformed-output tests;
7. developer golden-path end-to-end test with forced restart;
8. live-provider controlled smoke with a strict cost cap;
9. browser verification of Task Workspace desktop/mobile state and controls.

Data Agent donor characterization, migration and shared-spine seam tests belong to
SPINE-1. They may consume accepted SPINE-0 contracts but cannot be used to complete or
rescue SPINE-0.

`SPINE-E2E-1`, `WFG-ROUNDTRIP-1`, `CORRECTION-BOUNDARY-1` and
`PROVIDER-CHAOS-1` are separate product-eval specifications. Their thresholds and fixtures
must be preregistered/frozen before they are used as superiority or research evidence.

## 19. Architecture milestones and task split

These are dependency gates, not the detailed implementation plan:

SPINE-0:

1. reconcile parent/root identity documents that still describe the old three-repo product
   topology or C7 as unmodelable;
2. independently re-review and ratify this remediated packet;
3. write the test-first SPINE-0 implementation plan and file ownership map;
4. establish contracts, persistence, runtime, provider/credential and developer path;
5. run SPINE-0 architecture, security, UI and live-provider acceptance;
6. update product/research ledgers without rewriting historical verdicts.

SPINE-1, only after SPINE-0 acceptance:

1. verify ADR-0054 and the migration map remain accepted authority;
2. pin the full donor commit, scan full history and produce the provenance/safety manifest;
3. characterize donor behavior before import/extraction;
4. perform the accepted direct or filtered history import on an isolated branch;
5. extract generic packages and Data Agent domain pack;
6. pass the shared-spine seam plus retained SQL Safety/Evidence/Approval negative tests;
7. remove staging and verify no runtime dependency remains;
8. request explicit founder push/merge authorization.

No runtime implementation should begin from this packet until the written specification
has been reviewed and the implementation plan has been separately accepted.

## 20. Review checklist

The reviewer must decide whether this packet:

- preserves the complete Agent OS product identity and dual-track evidence boundary;
- gives Product Track one non-duplicated authority model;
- uses the Data Agent donor without preserving domain leakage or cross-repo runtime coupling;
- keeps the Data Agent migration out of SPINE-0 completion and behind ADR-0054 history
  safety/provenance gates;
- defines an executable first slice rather than schemas and mocks;
- states honest guarantees for correction, idempotency, providers and outcomes;
- provides enough contract/state/failure detail for a test-first implementation plan;
- keeps CWM, G10, belief learning and subagents as evidence-gated extensions;
- fits founder resource constraints without pre-optimizing for distributed scale.

Current status is:

```text
ARCHITECTURE REVIEWED AND ACCEPTED
IMPLEMENTATION PLAN NEXT
RUNTIME IMPLEMENTATION NOT STARTED
MIGRATION NOT EXECUTED
PRODUCT DELIVERY NOT CLAIMED
```
