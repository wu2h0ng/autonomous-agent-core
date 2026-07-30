# Agent CLI Continuous Responsibility and Self-Development Loop

> Status: `FOUNDER_APPROVED_DESIGN / IMPLEMENTATION_NOT_STARTED`
> Date: 2026-07-30
> Owner: Founder / CTO
> Primary class: `P`
> Secondary class: `A`
> Track: Product / Translational
> Product entry: `agent run`
> Base: `codex/agent-cli-v0-20260727@27f1643`
> Release authority: `NOT_AUTHORIZED`

## 1. User need and product outcome

The Founder needs one Agent OS surface that can remain responsible for an
externally supplied Mandate across tasks, interruptions, provider calls, process
restarts and self-development episodes without requiring the Founder to act as
the hidden state store, scheduler, relevance judge or result interpreter.

The product outcome is:

> One `agent run` process continuously restores Mandate-relative
> responsibilities, selects one admissible high-value work item, executes or
> develops a candidate through governed organs, observes and settles the
> outcome, asks for irreducible help, records operator cognitive work, persists
> a checkpoint and continues until it must wait, stop or be corrected.

This design combines the existing Agent CLI, Mandate stores, responsibility
projection, Outcome Portfolio, Help contracts, AgentLoop and SELFDEV execution
physics. It does not create another product shell.

## 2. Decisions

1. **Agent CLI is the only product Agent Surface.** Mandate, SELFDEV,
   Outcome/Help, HCW measurement and external-agent comparison are internal
   organs or administrative evidence surfaces.
2. **V1 runs as a foreground bounded resident loop.** `agent run` checkpoints
   after every responsibility cycle. `agent resume` restores it after process
   exit. No daemon, desktop supervisor or second workflow engine is added.
3. **There is no Founder-operated baseline mode.** Relative comparisons use
   external agent challengers at selected claim or promotion gates and do not
   consume Founder task time.
4. **The product is blueprint-gap driven.** When a ratified gap remains open,
   the system may select work or generate a self-development candidate. It may
   not lower the gate, close the gap, expand authority or promote its own
   candidate.
5. **Only one responsibility item executes per cycle.** Parallel internal work
   requires a later explicit design. V1 does not hide concurrency, ownership or
   authority races behind a multi-agent abstraction.
6. **SQLite ledgers are durable truth.** Terminal JSON files are reconstructable
   projections and may not become a second responsibility, outcome or authority
   root.

## 3. Rejected alternatives

### 3.1 Merge the canonical SELFDEV branch wholesale

Rejected. The Agent CLI and canonical SELFDEV branches have large, bidirectional
history divergence. A whole-branch merge would import benchmark harnesses,
parallel CLI surfaces and stale state narratives into the product entry. The
stable SELFDEV contracts and required adapter behavior will be ported
selectively.

### 3.2 Put the loop in the engineering workflow runner

Rejected. The workflow runner is internal development and research governance.
Making it own Mandate responsibility would turn a process tool into product
Runtime and make Agent OS evidence depend on the Meta layer.

### 3.3 Add a background daemon first

Rejected for V1. A daemon adds lifecycle, installation, supervision, security
and observability work before the responsibility loop has demonstrated product
value. Foreground residence plus durable restart recovery tests the decisive
semantics at lower cost.

## 4. System architecture

```text
agent run
  -> AgentCLI
  -> ResponsibilityLoopController
      -> MandateWorkspace / attached authority
      -> MandateResponsibilityProjector
      -> OutcomePortfolio / PersistentCommitments
      -> BlueprintGapReader
      -> MandateSteward proposal
      -> deterministic WorkAdmission
          -> AgentLoop organ
          -> SELFDEV organ
      -> Task / Run / Action / Evidence / ObservedOutcome
      -> Outcome settlement or typed HelpRequest
      -> OperatorWorkEvent / HcwMeasurementReceipt
      -> ResponsibilityCycleReceipt
      -> ResponsibilityLoopCheckpoint
  -> next cycle, WAITING_EVENT, BLOCKED or corrected stop
```

`ResponsibilityLoopController` coordinates existing services. It does not
replace TaskService, PolicyKernel, CapabilityBroker, the correction authority,
the Outcome Portfolio or the SELFDEV verifier.

## 5. Product command surface

The default help presents only:

```text
agent run
agent status
agent answer <help_id>
agent correct <reason>
agent resume
```

- `agent run` starts or restores the foreground responsibility loop.
- `agent status` returns a read-only Mandate-scoped projection: outstanding
  responsibilities, open gaps, active episode, checkpoint, evidence, outcome,
  open Help and measured operator work.
- `agent answer` validates and records a typed `HelpResponse`. Raw text does not
  become authority.
- `agent correct` invokes the existing external correction authority, halts the
  current scope and checkpoints before exit.
- `agent resume` verifies Mandate, database, repository, configuration and
  correction bindings before restoring work.

Existing `task-*`, `mandate-*` and future `selfdev-*` commands remain
administrative/debug surfaces. They are excluded from default product help and
product navigation. They cannot bypass the same stores or authority checks.

Equivalent slash commands may exist inside the interactive process, but they
must call the same application functions.

## 6. Responsibility cycle

Each cycle is atomic at the responsibility-selection level:

1. Load the attached Mandate, principal, correction epoch and latest valid
   checkpoint.
2. Project Persistent Commitments, linked Tasks, schedules, outcomes, failures,
   approvals, open Help and blueprint gaps.
3. Produce a `ResponsibilityWorkProposal` for one responsibility item.
4. Apply deterministic admission:
   - Mandate and scope match;
   - authority and correction epoch are current;
   - a named outcome/verifier and live consumer exist;
   - the hypothesis has remaining budget;
   - no negative-map or `PARK` rule forbids the route;
   - rollback or compensation is available for effects;
   - the proposal cannot modify its evaluator, gate or authority root.
5. Route the admitted item:
   - ordinary repository or information work to `AgentLoop`;
   - an Agent OS code/procedure/runtime improvement to `SelfDevelopmentOrgan`.
6. Record Task, Run, proposal, policy, permit, action, evidence and provider
   receipts through existing ledgers.
7. Produce or resolve an `ObservedOutcome`.
8. Settle the linked Persistent Commitment when evidence permits. If information,
   authority or an irreducible judgment is missing, emit typed Help instead.
9. Derive HCW telemetry and write a content-bound cycle receipt.
10. Persist the next checkpoint, then continue, wait or stop.

No model-generated text can directly create authority, close a gap, settle an
outcome, approve an action or promote a candidate.

## 7. Blueprint gap and self-development model

### 7.1 BlueprintGap

A later product slice introduces a Founder-ratified machine-readable gap record:

```text
gap_id
mountain: M1 | M2 | M3 | HCW | PRODUCT_LOOP
statement
current_evidence_refs
acceptance_gate_ref
independent_evaluator_ref
live_consumer_ref
authority_envelope_ref
budget
negative_map_refs
status
```

Statuses are:

```text
OPEN
ACTIVE
BLOCKED
NOT_MET
CLOSED_VERIFIED
PARK
```

The agent may propose new gaps, evidence or priority changes. Only the external
authority and independent evaluation path can admit a new gate or transition a
gap to `CLOSED_VERIFIED`.

### 7.2 ImprovementEpisode

An admitted attempt against one gap binds:

- the exact gap and gate version;
- the hypothesis and mechanism class;
- candidate write channel;
- repository/configuration head;
- provider/tool/permission/budget envelope;
- verifier and rollback;
- prior negative-map exclusions;
- external challenger requirement;
- terminal outcome and evidence.

Retry budgets are frozen. Exhaustion produces `NOT_MET`; it does not move the
gate, silently switch provider or repeat the same hypothesis.

### 7.3 SelfDevelopmentOrgan

The organ selectively ports the stable canonical SELFDEV behavior:

- Agent OS repository and target admission;
- isolated branch/worktree requirement;
- allowlisted verification;
- exact configuration and evidence binding;
- content-bound approval before consequential patch effect;
- measured post-run record;
- compensation/rollback;
- independent evidence refs;
- comparison and promotion receipts where required.

SELFDEV cannot write `main`, `master` or release branches, change C7, change its
own acceptance gate, approve itself or activate a new Runtime version in the
same cycle.

W1/W2 in-envelope cognitive and strategy state may update directly with
provenance and rollback. Code, procedure, algorithm, model and persistent
cross-task behavior changes are W3 candidates in shadow execution. W4 activation
requires an independent promoter and occurs only at a task boundary, checkpoint
or quiescent point.

## 8. External agent challengers

There is no user-facing baseline workflow. An external challenger is scheduled
only when:

- a W3/W4 change seeks promotion with a relative-improvement claim;
- the system claims lower HCW, better recovery or higher verified task yield;
- absolute correctness and safety gates cannot discriminate two candidates.

The challenger assignment binds the same:

- task and repository head;
- visible Mandate/task information;
- permissions and tools;
- time, token and cost budget;
- outcome verifier and failure semantics.

Available local external agents may include Codex, Kimi, Claude or another
explicitly identified coding agent. The receipt records provider, model,
version, command, environment, result and failure. Unavailability is
`CHALLENGER_UNAVAILABLE`; no silent fallback counts as the requested challenger.

An unavailable challenger does not block an ordinary change that independently
passes absolute correctness, safety and review gates. It blocks relative
superiority, HCW-reduction and capability-improvement claims.

## 9. HCW measurement

`OperatorWorkEvent` is append-only and bound to Mandate, cycle, task/run and
timestamp. V1 records:

- user prompt or missing-context supplement;
- approve or deny;
- correction;
- HelpResponse;
- manual recovery/restart action;
- request to reinterpret or re-explain a result.

`HcwMeasurementReceipt` deterministically derives:

- operator intervention count;
- active operator time with a declared idle cutoff;
- Help burden;
- correction/recovery burden;
- result-interpretation burden;
- event refs and measurement-policy digest.

The system does not estimate HCW from model prose and does not require manual
minute entry. Missing or ambiguous telemetry yields `HCW_INSUFFICIENT_DATA`, not
a favorable estimate.

## 10. Failure semantics

- **Authority or checkpoint drift:** do not execute; record
  `BLOCKED_AUTHORITY_DRIFT` and emit the minimum sufficient Help when needed.
- **Temporary provider failure:** retry only inside the frozen attempt budget.
  Exhaustion is `NOT_MET_PROVIDER`.
- **Effect without provable receipt:** recover through idempotency/effect
  ledgers. If proof cannot be reconstructed, record `OUTCOME_UNKNOWN`.
- **Verifier failure:** preserve evidence, compensate or roll back and record
  `NOT_MET`.
- **Evaluator/candidate conflict:** do not promote.
- **External challenger unavailable:** record the failure and suppress relative
  claims.
- **No admissible responsibility:** enter `WAITING_EVENT`; do not fabricate work.
- **Irreducible information, authority or judgment gap:** emit typed Help and
  continue only explicitly declared continuable work.
- **Ctrl-C:** write correction halt and checkpoint before returning exit code
  130.

Every terminal state is projected by `agent status`.

## 11. Persistence and recovery

The application database owns:

- Mandate authority and environment bindings;
- responsibility links and Outcome Portfolio;
- Tasks, Runs, Actions, evidence and outcomes;
- open Help and responses;
- operator work events and HCW receipts;
- responsibility cycle receipts and checkpoints;
- later BlueprintGap and ImprovementEpisode records.

The checkpoint binds:

- Mandate/version/digest;
- principal, tenant and workspace;
- correction epoch;
- repository root and head;
- active responsibility, episode, task and run;
- last completed durable event sequence;
- configuration/provider/grant digests;
- next legal transition.

A session transcript is an optional projection. Recovery must succeed from the
database and evidence ledgers without asking the Founder to restate Mandate,
completed work or known failures.

## 12. Delivery decomposition

### 12.1 P-AGENT-RESPONSIBILITY-LOOP-1

First implementation slice:

- unique `agent run/status/answer/correct/resume` surface;
- `ResponsibilityLoopController`;
- deterministic responsibility admission;
- Outcome/Help settlement path;
- OperatorWorkEvent, HCW receipt, cycle receipt and checkpoint;
- cross-process A-to-B-to-A recovery fixture.

SELFDEV is represented by a denied/not-yet-bound organ route in this slice.

### 12.2 P-AGENT-SELFDEV-ORGAN-1

- port stable SELFDEV contracts and execution adapter;
- route Agent OS improvement work internally;
- isolated candidate execution, rollback and measured run record;
- no second product CLI.

### 12.3 P-AGENT-BLUEPRINT-EVOLUTION-1

- BlueprintGap and ImprovementEpisode;
- negative-map route changes;
- external challenger assignments;
- independent promotion and atomic activation.

No MCP, TUI, general daemon, AWL-2 breadth or extra terminal tools enter active
capacity before the first slice closes.

## 13. Acceptance strategy

The first slice requires bypass-detecting tests:

1. Process A creates a responsibility cycle and performs a partial step.
2. Process A exits after a durable checkpoint.
3. Process B restores the exact responsibility without user restatement.
4. A missing-information state emits typed Help and causes no unauthorized work.
5. A typed HelpResponse resumes the same cycle.
6. A VERIFIED outcome settles the commitment.
7. NOT_MET, INVALID, UNRESOLVED and UNKNOWN outcomes cannot settle it as met.
8. HCW receipts contain only durable operator events under the frozen
   measurement policy.
9. A model proposal cannot close a blueprint gap, approve an action, expand a
   permission or promote a candidate.
10. Ctrl-C records correction and a recoverable checkpoint.
11. Default product help exposes one Agent Surface and hides internal organs.
12. Returning constants or bypassing PolicyKernel, permit, outcome evidence,
    Help validation or C7 makes the suite fail.

Targeted tests, Ruff, Pyright, diff checks and a clean isolated-worktree
verification are required. Repository-wide pre-existing failures remain
separate baseline debt and cannot be called green.

## 14. Claim and release boundary

Closing the first slice permits only:

> Agent CLI implements and tests a bounded, restart-safe Mandate responsibility
> cycle with Outcome/Help settlement and automatic operator-work telemetry in a
> named local software-repository envelope.

It does not establish sustained autonomy, general cognition, self-improvement
superiority, durable HCW reduction, production readiness or
`Autonomy(S,E,O,V,T)`.

Push, merge, activation and release remain separate actions. Release is not
authorized by this design.
