# Mandate-Scoped Responsibility View Design

> Status: `FOUNDER_APPROVED / EXACT_REVIEW_CORRECTED`
> Track: Product
> Requirement classes: `U` operator responsibility visibility; `P` responsibility projection; `A` scoped linking and fail-closed truth; `E` implementation and falsifier gates
> Base: Agent OS `946d428` (Product runtime through `4ba2612`)
> Release: not authorized

## 1. User result

An operator can open one Mandate-scoped, read-only responsibility view and see:

- the Mandate's desired outcomes;
- which existing Tasks are explicitly linked to it;
- each linked Task's canonical Commitment, ExpectedOutcome and current trusted ObservedOutcome;
- known Task blockers that are present in canonical Task state;
- the next configured observation time; and
- exactly which items require operator attention and why.

The slice is successful only if it reduces hidden operator work needed to
restate, locate, interpret and prioritize responsibility state. A view that is
technically correct but does not reduce that burden is an engineering feature,
not evidence that Founder cognitive load decreased.

## 2. Non-goals

This slice does not:

- create, revise or retire a Product Commitment;
- activate a Task or turn a `TaskDraftProposal` into a Task;
- accept or manufacture an ObservedOutcome;
- call a provider, tool or capability;
- change an active-perception schedule;
- create a second Goal, Commitment, Outcome, Help or Mandate truth system;
- implement a general portfolio engine, dashboard framework or workflow layer;
- establish sustained responsibility or `Autonomy(S,E,O,V,T)`; or
- authorize release.

## 3. Alternatives considered

### Selected: explicit link plus live projection

Persist one minimal `MandateTaskLink` authority record, then compute the view
from existing Mandate, Task event stream, current outcome and active-perception
sources. This adds the missing cross-layer join without
copying the joined state.

### Rejected: independent portfolio ledger

Copying Commitment and Outcome state into a new aggregate would make reads
simple but would immediately create synchronization, recovery and competing
truth problems.

### Rejected: infer ownership from relevance context or `active_commitment_ids`

Those are currently projections or unmaintained fields. Treating them as
ownership authority would allow stale context to silently assign a Task to a
Mandate.

## 4. Canonical sources and reuse

The view reuses these truths rather than redefining them:

- Mandate authority: `MandateWorkspaceRecord` and current correction/status;
- Task identity and lifecycle: canonical Task event stream and aggregate;
- work contract: existing Product `Goal` and `Commitment`;
- acceptance truth: existing `ExpectedOutcome` and
  `TaskService.current_outcome()`;
- polling state: existing `mandate_active_perception_schedule`.

Unassociated situated proposals and Help are parked in this slice. The current
durable situated store has no Mandate-scoped current/list/resolution truth, so
including historical proposal rows would manufacture false attention. A later
slice may add an explicit, append-only association and acknowledgement truth;
until then these records are not part of the responsibility view.

Research objects such as `src/aac/commitment_ledger.py`, causal-variable Goals
and simulated TaskSpec/TaskResult are forbidden Product dependencies.

## 5. New contracts

### 5.1 `MandateTaskLinkCommand`

Caller fields:

- `task_id`
- optional human-readable `reason`

Server-owned fields include principal, tenant, workspace, Mandate ID, actor,
current Mandate correction epoch and timestamps. The caller cannot inject scope,
Task identity digests, activation flags or outcome state.

### 5.2 `MandateTaskLink`

An append-only, versioned record binding:

- `association_id`, deterministically derived from scoped Mandate and Task
  creation identity and stable across relinks;
- `link_id`, deterministically derived from `association_id`, current Mandate
  correction epoch, current workspace-record/operational-reference digests and
  the prior link or revocation digest;
- principal, tenant, workspace and Mandate ID;
- Task ID and Task-created-event digest;
- Mandate workspace-record digest and correction epoch at link time;
- linked-by principal and linked-at timestamp;
- command digest and record digest; and
- literal `task_activation_authorized=false`,
  `capability_grant_authorized=false`, `external_effects_authorized=false`.

Exact replay is idempotent. A same-ID/different-content replay is a conflict.
At most one unreveoked link version for an association is active. Correction
drift makes the old version `UNKNOWN`; after an explicit revocation, a Mandate
admin may append a new link version that binds the revocation digest and the
new correction epoch. The first slice never edits a link in place. A scoped
admin can append a typed
`MandateTaskLinkRevocation` that binds the prior link digest, current Mandate
correction epoch, actor, reason and time. Revocation removes the link from the
active projection but not from the audit list; it cannot mutate the Task.

### 5.3 Responsibility read model

`MandateResponsibilityView` contains:

- scoped Mandate identity and desired outcomes;
- ordered `ResponsibilityItem` rows for exact links;
- active-perception schedule summary;
- typed global gaps;
- source digests/event positions; and
- one deterministic `view_digest` over canonical JSON.

Each `ResponsibilityItem` contains source references plus the current Goal,
Commitment, ExpectedOutcome and current ObservedOutcome when valid. The view
does not persist copies of those objects. It also contains ordered typed
`attention_reasons`; `NEEDS_ATTENTION` and `UNKNOWN` require at least one reason,
while `DONE_VERIFIED` and `TRACKED` require none. Reason codes, not free-form
model text, drive ordering and the user-visible explanation.

Item state is one of, in this strict precedence order:

- `UNKNOWN`: any authority, identity, event, evaluator-support or source
  validation is missing, malformed, stale, inconsistent or cannot be replayed;
- `NEEDS_ATTENTION`: current outcome is `NOT_MET`, `UNRESOLVED` or `INVALID`;
  Task is `FAILED`, `CANCELLED`, `PAUSED` or `WAITING`; Commitment expired
  without a still-current verified completion; or a terminal Task lacks a
  current trusted outcome;
- `DONE_VERIFIED`: Task is `COMPLETED`, its current outcome is still trusted
  `VERIFIED`, the evaluator contract is supported, and the completion occurred
  before Commitment expiry;
- `TRACKED`: Task is `DRAFT`, `COMMITTED`, `RUNNING` or `VERIFYING`, all sources
  are current and no known attention condition exists; this
  is explicitly not a progress or success claim.

No other Task/status combination may default to `TRACKED`; an unhandled
combination is `UNKNOWN`.

`TRACKED` replaces the dialogue shorthand `ON_TRACK` because the current
sources cannot prove progress merely from absence of a known failure.

## 6. Public entry points

- `POST /v1/mandates/{mandate_id}/task-links`
- `GET /v1/mandates/{mandate_id}/task-links`
- `POST /v1/mandates/{mandate_id}/task-links/{link_id}:revoke`
- `GET /v1/mandates/{mandate_id}/responsibility-view`

The POST paths require the existing authenticated Mandate-admin principal and
authorize classification of a same-tenant/workspace Task under that Mandate;
they do not assert a nonexistent Task principal owner and do not grant Task
authority. `Goal.created_by` remains provenance only. Both GET paths are scoped
reads. The same typed responsibility response is rendered as a read-only
section in the existing Task Workspace / Agent Surface
`apps/api_server/index.html`; no separate dashboard application is introduced.

## 7. Link write flow

1. Resolve the request-authenticated principal and Mandate workspace scope.
2. Read both Mandate sources: immutable `MandateWorkspaceRecord` for mission,
   desired outcomes and owner scope; current `RatifiedMandateRef` for live
   operational status, correction epoch and exact workspace-record binding.
   Require matching Mandate ID, owner principal, tenant, workspace,
   `workspace_record_digest` and ratification binding. Missing or inconsistent
   sources fail closed.
3. Read the Task-created event and rehydrate the Task in the same tenant and
   workspace.
4. Reject a non-admin request principal; cross-tenant/workspace Task; missing,
   malformed, paused, revoked, expired or correction-drifted Mandate; and any
   mismatched workspace/operational authority join. Product Task has no
   principal ownership field, so no unsupported cross-principal Task claim is
   made.
5. Construct server-owned canonical link bytes.
6. Append under an immediate SQLite transaction with unique scoped identity and
   same-content idempotency.
7. Return a receipt whose three authority flags remain false.

Linking does not acquire a Task lease, append a Task event, call TaskService
mutation paths or touch active-perception counters.

Revocation follows the same scope and correction checks, requires the exact
current link digest, and appends an immutable revocation row in the same store.
An exact replay is idempotent; a different reason/digest under the same
revocation identity conflicts. It never deletes the original link row.

## 8. Read projection flow

1. Re-read the immutable workspace record, current operational Mandate ref and
   all scoped links; validate the exact join described above.
2. Rehydrate each linked Task from the canonical event stream.
3. Call the existing current-outcome validation path and also run
   `expected_outcome_contract_error`; never trust a cached old `VERIFIED` value
   or an evaluator contract unsupported by Product runtime.
4. Read the Mandate's active-perception schedule. Do not list historical
   situated proposal/Help rows in this slice.
5. Classify rows using the closed state rules above.
6. Sort deterministically by attention class, due/expiry time, link time and
   stable ID.
7. Re-read both Mandate authority sources before returning and reject a changed
   epoch/status/digest (optimistic two-read guard).
8. Bind stable source record digests, historical outcome digest, Task event
   position, deterministic outcome-validation status/reason and schedule digest
   into `view_digest`. Exclude `computed_at` and the temporary
   `TaskService.current_outcome()` timestamp from the digest: that method emits
   a fresh `observed_at` when demoting stale `VERIFIED`, so hashing the temporary
   projection would make unchanged sources produce a different digest.

The response may be cached only against that digest. A source change must
produce a new digest or a typed failure.

## 9. Failure semantics

The projection never silently omits a linked Task.

| Condition | Result |
|---|---|
| Mandate not found or request scope mismatch | typed not-found/denied response |
| Mandate revoked | no new link; existing historical links remain readable with a revoked Mandate banner |
| Mandate source missing or workspace/operational join mismatch | typed fail-closed global error; no responsibility rows claimed |
| Mandate correction epoch or workspace-record digest drift | affected link version is `UNKNOWN`; explicit revoke then versioned relink is required; no automatic rebinding |
| Task missing, malformed or Task-created identity changed | active item remains present as `UNKNOWN` |
| Task evidence expired/deleted or evaluator no longer supported | view applies explicit deterministic fail-closed validation; never `DONE_VERIFIED` |
| schedule source drift | typed global gap, never silent omission |
| duplicate exact link | idempotent replay |
| same scoped link with different bytes | conflict |
| exact revocation replay | idempotent replay; link remains in audit list and leaves active view |
| stale/different revocation bytes | conflict; original link state is unchanged |

The overall view can be `PARTIAL_UNKNOWN`; one bad item does not erase other
valid items, but the response must expose the gap and include it in the digest.

## 10. Authority and security invariants

- Request principal and Mandate-admin scope are exact. Task eligibility is
  bound by tenant, workspace and Task-created event identity;
  `Goal.created_by` is provenance and is not incorrectly treated as a principal
  authorization or Task ownership proof.
- Mission/outcomes come only from `MandateWorkspaceRecord`; operational
  status/correction comes only from `RatifiedMandateRef`; an exact digest/scope
  join and optimistic second read are mandatory.
- Task identity is bound to its creation event, not caller text.
- Only the existing trusted outcome path may yield `DONE_VERIFIED`.
- Link and view code cannot import Research Track objects.
- Link and view code cannot call Task activation, provider, capability or effect
  paths.
- Paused/revoked/expired/corrected Mandates fail closed according to the table
  above.
- No user-controlled field becomes an authority scope or record digest.
- Every link and view response is canonical-byte digest bound and restart
  replayable.

## 11. Product verification

RED tests precede implementation and must cover:

- non-admin principal plus cross-tenant and cross-workspace link attempts;
- missing, revoked and correction-drifted Mandates;
- forged or replaced Task-created identity;
- exact replay and same-ID/different-content conflict;
- revocation exact replay, stale digest, audit retention and no Task mutation;
- Task event deletion, reorder and malformed event bytes;
- expired/deleted evidence and stale `VERIFIED` outcomes;
- missing/mismatched workspace and operational Mandate sources, concurrent
  epoch drift and schedule drift;
- all TaskStatus/OutcomeStatus/evaluator-support combinations and strict state
  precedence, including terminal-without-outcome and expiry boundaries;
- stable view digest when stale `VERIFIED` is deterministically demoted across
  repeated reads and restart;
- restart-equivalent link and view digests;
- deterministic ordering and partial-unknown behavior;
- HTTP cache-bypass and server-owned field rejection; and
- literal no-change assertions for Task count, TaskActivation, capability
  grants, provider/tool calls, external effects and schedule counters.

Targeted tests, the full Product suite, Ruff, Pyright and diff checks are
required. Green tests do not replace independent exact-head review.

## 12. Founder Cognitive Load falsifier

Run a separately preregistered matched human comparison inside
`META-SHADOW-MANDATE-0`:

- baseline: existing Task/event/log surfaces plus direct model-and-tools use;
- treatment: the same surfaces plus this responsibility view;
- before any participant run, freeze hidden portfolio snapshots, the gold set
  of mandatory attention events, annotation rubric, scoring code and hashes;
- use one matched unit as the same operator on the same-complexity paired
  snapshots, with baseline/treatment order randomized or counterbalanced;
- start timing when the operator receives the responsibility question and stop
  only after they submit a final prioritized action list; exclude system load
  time but include navigation, querying and interpretation time;
- score false attention as non-gold items marked `NEEDS_ATTENTION` divided by
  all non-gold linked items; report count and denominator;
- missing or abandoned paired observations invalidate that pair; no imputation
  and no post-hoc replacement; and
- blind gold adjudication to arm where practical, with a named independent
  adjudicator and exact artifact hashes.

Primary human-cognitive-work categories are `RESTATE + LOCATE + INTERPRET +
PRIORITIZE`. The preregistered value gate is at least 30% lower median operator
minutes in treatment.

Hard non-regression gates are:

- mandatory-event recall = 100%;
- false `DONE_VERIFIED` = 0;
- false attention does not exceed baseline; and
- no additional authority or external effect.

Engineering tests verify only the capture, timer and scoring machinery; they
cannot substitute for the preregistered human comparison. Failure means the
slice remains an implemented Product feature only. It cannot
be cited as reduced Founder cognitive load, sustained responsibility or
autonomy evidence.

## 13. Smallest implementation package

1. Contracts and bypass-detecting tests.
2. SQLite link/revocation store with exact-scope/idempotency semantics.
3. Read-only projection service and typed failures.
4. Application/HTTP entry points.
5. Minimal read-only panel in existing `index.html`: scoped Mandate list/select,
   desired outcomes, responsibility rows, next observation time, and explicit
   revoked/partial-unknown banners, explicit refresh, loading/empty/error states
   and last successful source digest. It contains no link, activate, execute,
   approve, revoke or edit controls.
6. Targeted/full verification and independent review.
7. Separate preregistered cognitive-load falsifier; no value claim before it.

The package explicitly parks automatic Task association, Commitment lifecycle
management, Task activation, notification systems, a new dashboard framework,
generalized portfolio analytics and release. Revocation is API-first; a separate
link-management UI is parked, while the responsibility view may show revoked
links only in its audit section.
