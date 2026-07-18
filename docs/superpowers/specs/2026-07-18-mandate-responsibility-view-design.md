# Mandate-Scoped Responsibility View Design

> Status: `WRITTEN_SPEC_AWAITING_USER_REVIEW`
> Track: Product
> Requirement classes: `U` operator responsibility visibility; `P` responsibility projection; `A` scoped linking and fail-closed truth; `E` implementation and falsifier gates
> Base: Agent OS `946d428` (Product runtime through `4ba2612`)
> Release: not authorized

## 1. User result

An operator can open one Mandate-scoped, read-only responsibility view and see:

- the Mandate's desired outcomes;
- which existing Tasks are explicitly linked to it;
- each linked Task's canonical Commitment, ExpectedOutcome and current trusted ObservedOutcome;
- unresolved Help, known blockers and proposal-only observations;
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
from existing Mandate, Task event stream, current outcome, situated assessment
and active-perception sources. This adds the missing cross-layer join without
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
- proposal-only observation: existing `SituatedAssessmentRecord`;
- Help: the currently durable situated Help projection only; the richer
  in-memory `SrlHelpRequest` is not silently merged into it;
- polling state: existing `mandate_active_perception_schedule`.

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

An append-only record binding:

- `link_id`, deterministically derived from scoped Mandate and Task identity;
- principal, tenant, workspace and Mandate ID;
- Task ID and Task-created-event digest;
- Mandate workspace-record digest and correction epoch at link time;
- linked-by principal and linked-at timestamp;
- command digest and record digest; and
- literal `task_activation_authorized=false`,
  `capability_grant_authorized=false`, `external_effects_authorized=false`.

Exact replay is idempotent. A same-ID/different-content replay is a conflict.
The first slice never edits a link in place. A scoped admin can append a typed
`MandateTaskLinkRevocation` that binds the prior link digest, current Mandate
correction epoch, actor, reason and time. Revocation removes the link from the
active projection but not from the audit list; it cannot mutate the Task.

### 5.3 Responsibility read model

`MandateResponsibilityView` contains:

- scoped Mandate identity and desired outcomes;
- ordered `ResponsibilityItem` rows for exact links;
- unassociated current proposal/Help attention rows;
- active-perception schedule summary;
- typed global gaps;
- source digests/event positions; and
- one deterministic `view_digest` over canonical JSON.

Each `ResponsibilityItem` contains source references plus the current Goal,
Commitment, ExpectedOutcome and current ObservedOutcome when valid. The view
does not persist copies of those objects.

Item state is one of:

- `DONE_VERIFIED`: current outcome is still trusted `VERIFIED`;
- `NEEDS_ATTENTION`: expired Commitment, current `UNRESOLVED`/`INVALID`,
  unresolved Help, or a critical unassociated proposal;
- `TRACKED`: sources are current and no known attention condition exists; this
  is explicitly not a progress or success claim; or
- `UNKNOWN`: a required source is missing, malformed, stale or cannot be
  replayed.

`TRACKED` replaces the dialogue shorthand `ON_TRACK` because the current
sources cannot prove progress merely from absence of a known failure.

## 6. Public entry points

- `POST /v1/mandates/{mandate_id}/task-links`
- `GET /v1/mandates/{mandate_id}/task-links`
- `POST /v1/mandates/{mandate_id}/task-links/{link_id}:revoke`
- `GET /v1/mandates/{mandate_id}/responsibility-view`

The POST paths are authenticated Mandate administration, not Task authority.
Both GET paths are scoped reads. The same typed responsibility response is
rendered as a read-only section in the existing Task Workspace / Agent Surface
`apps/api_server/index.html`; no separate dashboard application is introduced.

## 7. Link write flow

1. Resolve the request-authenticated principal and Mandate workspace scope.
2. Read the current Mandate record, status, correction epoch and digest.
3. Read the Task-created event and rehydrate the Task in the same tenant and
   workspace.
4. Reject cross-principal, cross-tenant, cross-workspace, missing, malformed,
   revoked or correction-drifted inputs.
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

1. Re-read current Mandate authority and all scoped links.
2. Rehydrate each linked Task from the canonical event stream.
3. Call the existing current-outcome validation path; never trust a cached old
   `VERIFIED` value.
4. Read the Mandate's durable situated assessments and active-perception
   schedule.
5. Classify rows using the closed state rules above.
6. Sort deterministically by attention class, due/expiry time, link time and
   stable ID.
7. Bind source record digests and event positions into `view_digest`.

The response may be cached only against that digest. A source change must
produce a new digest or a typed failure.

## 9. Failure semantics

The projection never silently omits a linked Task.

| Condition | Result |
|---|---|
| Mandate not found or request scope mismatch | typed not-found/denied response |
| Mandate revoked | no new link; existing historical links remain readable with a revoked Mandate banner |
| Mandate correction epoch or workspace-record digest drift | affected link is `UNKNOWN` until explicitly relinked; no automatic rebinding |
| Task missing, malformed or Task-created identity changed | active item remains present as `UNKNOWN` |
| Task evidence expired/deleted or evaluator no longer valid | current outcome follows existing fail-closed path; never `DONE_VERIFIED` |
| assessment/schedule source drift | typed global gap or affected attention row, never silent omission |
| duplicate exact link | idempotent replay |
| same scoped link with different bytes | conflict |
| exact revocation replay | idempotent replay; link remains in audit list and leaves active view |
| stale/different revocation bytes | conflict; original link state is unchanged |

The overall view can be `PARTIAL_UNKNOWN`; one bad item does not erase other
valid items, but the response must expose the gap and include it in the digest.

## 10. Authority and security invariants

- Request principal and Mandate admin scope are exact. Task ownership is bound
  by tenant, workspace and Task-created event identity; `Goal.created_by` is
  provenance and is not incorrectly treated as a principal authorization.
- Task identity is bound to its creation event, not caller text.
- Only the existing trusted outcome path may yield `DONE_VERIFIED`.
- Link and view code cannot import Research Track objects.
- Link and view code cannot call Task activation, provider, capability or effect
  paths.
- Paused/revoked/corrected Mandates fail closed according to the table above.
- No user-controlled field becomes an authority scope or record digest.
- Every link and view response is canonical-byte digest bound and restart
  replayable.

## 11. Product verification

RED tests precede implementation and must cover:

- cross-principal, tenant and workspace link attempts;
- missing, revoked and correction-drifted Mandates;
- forged or replaced Task-created identity;
- exact replay and same-ID/different-content conflict;
- revocation exact replay, stale digest, audit retention and no Task mutation;
- Task event deletion, reorder and malformed event bytes;
- expired/deleted evidence and stale `VERIFIED` outcomes;
- assessment and schedule drift;
- restart-equivalent link and view digests;
- deterministic ordering and partial-unknown behavior;
- HTTP cache-bypass and server-owned field rejection; and
- literal no-change assertions for Task count, TaskActivation, capability
  grants, provider/tool calls, external effects and schedule counters.

Targeted tests, the full Product suite, Ruff, Pyright and diff checks are
required. Green tests do not replace independent exact-head review.

## 12. Founder Cognitive Load falsifier

Run a matched comparison inside `META-SHADOW-MANDATE-0`:

- baseline: existing Task/event/log surfaces plus direct model-and-tools use;
- treatment: the same surfaces plus this responsibility view;
- matched hidden portfolio snapshots and mandatory attention events;
- blinded timing/annotation where practical.

Primary human-cognitive-work categories are `RESTATE + LOCATE + INTERPRET +
PRIORITIZE`. The preregistered value gate is at least 30% lower median operator
minutes in treatment.

Hard non-regression gates are:

- mandatory-event recall = 100%;
- false `DONE_VERIFIED` = 0;
- false attention does not exceed baseline; and
- no additional authority or external effect.

Failure means the slice remains an implemented Product feature only. It cannot
be cited as reduced Founder cognitive load, sustained responsibility or
autonomy evidence.

## 13. Smallest implementation package

1. Contracts and bypass-detecting tests.
2. SQLite link/revocation store with exact-scope/idempotency semantics.
3. Read-only projection service and typed failures.
4. Application/HTTP entry points.
5. Minimal read-only panel in existing `index.html`.
6. Targeted/full verification and independent review.
7. Separate preregistered cognitive-load falsifier; no value claim before it.

The package explicitly parks automatic Task association, Commitment lifecycle
management, Task activation, notification systems, a new dashboard framework,
generalized portfolio analytics and release. Revocation is API-first; a separate
link-management UI is parked, while the responsibility view may show revoked
links only in its audit section.
