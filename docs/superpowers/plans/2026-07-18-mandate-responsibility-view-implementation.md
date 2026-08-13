# Mandate-Scoped Responsibility View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
> Complete tasks in order, keep one writer for this worktree, and observe every
> RED test before production code.

**Goal:** Deliver one Mandate-scoped, read-only responsibility view that joins
explicit Task associations to canonical Product truth and reduces state-location
work without creating a second portfolio ledger or any execution authority.

**Architecture:** Add a small Product contract module and one SQLite-backed
responsibility module. The store owns append-only link/revocation records and
reads the existing Mandate workspace record, live operational Mandate ref and
Task event stream under fail-closed scope/digest checks. A projection service
classifies canonical Task/Outcome state without persisting copies. The existing
API server and `index.html` expose the typed read model; mutation UI is parked.

**Tech stack:** Python 3.12, Pydantic, stdlib `sqlite3`, current HTTP server,
vanilla HTML/CSS/JS, pytest, Ruff, Pyright.

## Global constraints

- Product Track only. No import from `src/aac`, `experiments` or Research Track.
- Use the existing feature branch/worktree based on AgentOS `8982cad`; one writer.
- `TENANT_ADMIN` is the only link/revoke writer role. Owner-scoped `PRINCIPAL`
  and same-scope `TENANT_ADMIN` may read through authenticated applications.
- Never call Task mutation, activation, provider, capability, effect or schedule
  mutation paths.
- Mission/outcomes come from `MandateWorkspaceRecord`; operational
  status/correction comes from `RatifiedMandateRef`; exact join is mandatory.
- No historical situated proposal/Help enumeration in this slice.
- No release and no autonomy or reduced-cognitive-load claim from green tests.
- Commit after each task only if its targeted tests pass; do not merge until the
  full Product suite and independent exact-head review pass.

---

### Task 1: Freeze responsibility contracts and RED contract tests

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/responsibility.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Create: `tests/product/test_mandate_responsibility_contracts.py`

**Interfaces:**
- `ResponsibilityItemState`: `UNKNOWN`, `NEEDS_ATTENTION`, `DONE_VERIFIED`,
  `TRACKED`.
- Typed reason enum covering authority/source gaps, unsupported evaluator,
  outcome failure, Task failure/cancel/pause, approval wait, expired event wait,
  commitment expiry and terminal-without-outcome.
- `MandateTaskLinkCommand`, `MandateTaskLink`,
  `MandateTaskLinkRevocationCommand`, `MandateTaskLinkRevocation`.
- `ResponsibilityItem`, `MandateResponsibilityView`,
  `MandateResponsibilityViewStatus` and optional active-perception summary.

- [ ] Write tests proving caller contracts cannot contain principal, tenant,
  workspace, mandate digest, correction epoch, Task event digest, authority
  flags, outcome state or timestamps.
- [ ] Write tests proving all three authority flags accept literal `False` only;
  `UNKNOWN`/`NEEDS_ATTENTION` require typed reasons; `TRACKED`/`DONE_VERIFIED`
  forbid reasons; view rows and reasons are deterministic and unique.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_contracts.py -q`
  Expected: collection/import failure because contracts do not exist.
- [ ] Implement minimal contracts, validators and exports. Use existing
  `ContractModel`, `UtcDateTime`, `Sha256Digest`, `Goal`, `Commitment`,
  `ExpectedOutcome`, `ObservedOutcome`, `TaskStatus`, `RunStatus`.
- [ ] Re-run the contract test; run Ruff and Pyright on touched packages.
- [ ] Commit: `feat(product): add responsibility view contracts`.

### Task 2: Add atomic append-only link and revocation persistence

**Files:**
- Create: `packages/os_core/src/agent_os_core/mandate_responsibility.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Create: `tests/product/test_mandate_responsibility_store.py`

**Interfaces:**
- `SQLiteMandateResponsibilityStore(database, clock=...)`.
- `create_link(command, mandate_id, actor) -> MandateTaskLink`.
- `list_links(mandate_id, reader, *, include_revoked=True)`.
- `revoke_link(command, mandate_id, link_id, actor) -> MandateTaskLinkRevocation`.

- [ ] Add fixtures that create a real Mandate workspace record, operational
  `RatifiedMandateRef` and real Task event stream in one SQLite file.
- [ ] Write RED tests for non-`TENANT_ADMIN`, wrong tenant/workspace, missing
  operational ref, workspace-record digest mismatch, non-ACTIVE/expired
  Mandate, malformed Task creation identity, exact replay and different-command
  conflict.
- [ ] Write RED tests for stable `association_id`, versioned `link_id`, active
  uniqueness, exact revocation replay, stale digest conflict, audit retention,
  same-epoch relink after explicit revocation, and correction-drifted link
  remaining audit-only/non-relinkable.
- [ ] Assert Task event count, Task aggregate, schedule counters and authority
  tables are byte/count unchanged by link/revoke operations.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_store.py -q`
  Expected: import/attribute failures.
- [ ] Implement tables with exact schema validation and `BEGIN IMMEDIATE`.
  Inside the same transaction validate canonical `mandate_workspace_records`,
  `situated_mandates` and Task sequence-1 `TASK_CREATED` bytes. Derive IDs and
  digests server-side. Never update/delete link rows.
- [ ] Re-run store tests and contract tests.
- [ ] Commit: `feat(product): persist mandate task associations`.

### Task 3: Build deterministic fail-closed projection

**Files:**
- Modify: `packages/os_core/src/agent_os_core/mandate_responsibility.py`
- Create: `tests/product/test_mandate_responsibility_projection.py`

**Interfaces:**
- `MandateResponsibilityProjector(store, task_service, clock=...)`.
- `project(mandate_id, reader) -> MandateResponsibilityView`.

- [ ] Write table-driven RED tests for every `TaskStatus`, relevant `RunStatus`
  and every `OutcomeStatus`; include unsupported evaluator, terminal without
  current outcome, Commitment expiry and completed-before-expiry.
- [ ] Add WAITING tests: `WAITING_APPROVAL -> NEEDS_ATTENTION`, pre-deadline
  `WAITING_EVENT -> TRACKED`, deadline-arrived wait -> `NEEDS_ATTENTION`, and
  missing/malformed wait condition -> `UNKNOWN`.
- [ ] Add tampering RED tests for deleted/reordered/malformed Task events,
  replaced creation event, missing/mismatched dual Mandate sources, concurrent
  epoch/status change and malformed schedule state. A bad linked Task must
  remain visible as `UNKNOWN`; a broken Mandate join fails the whole view.
- [ ] Add deterministic digest RED tests proving repeated reads and restart
  produce the same digest within one time-classification interval, including
  stale `VERIFIED` demotion. Prove a source/event/deadline-boundary change
  changes the digest. Exclude computed/projection timestamps.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_projection.py -q`
- [ ] Implement strict precedence, typed reasons, `expected_outcome_contract_error`,
  canonical sorting, stable validation summary, schedule read, and optimistic
  two-read Mandate authority guard.
- [ ] Re-run Tasks 1-3 tests.
- [ ] Commit: `feat(product): project mandate responsibility truth`.

### Task 4: Wire Application and HTTP entry points

**Files:**
- Modify: `apps/api_server/app.py`
- Modify: `apps/api_server/server.py`
- Create: `tests/product/test_mandate_responsibility_api.py`

**Endpoints:**
- `POST /v1/mandates/{mandate_id}/task-links`
- `GET /v1/mandates/{mandate_id}/task-links`
- `POST /v1/mandates/{mandate_id}/task-links/{link_id}:revoke`
- `GET /v1/mandates/{mandate_id}/responsibility-view`

- [ ] Write RED HTTP tests for admin authentication, owner/admin scoped reads,
  400/403/404/409 mapping, exact idempotent replay, server-owned field
  rejection, partial-unknown response, revoked banner and no-cache response.
- [ ] Add a bypass test proving generic HTTP idempotency storage cannot replace
  domain-level canonical replay for link/revoke endpoints.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_api.py -q`
- [ ] Compose the store/projector in `AgentOSApplication`. Keep typed application
  methods thin; do not expose raw SQL or Task mutation handles.
- [ ] Add exact route matchers and error types/status mapping. Set
  `Cache-Control: no-store` for responsibility reads; optionally emit ETag from
  `view_digest`, but never return a stale cached body after source drift.
- [ ] Re-run API plus existing Mandate workspace/observation API tests.
- [ ] Commit: `feat(product): expose mandate responsibility api`.

### Task 5: Add the minimal read-only Agent Surface panel

**Files:**
- Modify: `apps/api_server/index.html`
- Create: `tests/product/test_mandate_responsibility_surface.py`

- [ ] Write RED static/surface tests requiring Mandate select/list, desired
  outcomes, responsibility rows, next observation, typed reason display,
  revoked/partial-unknown banners, refresh/loading/empty/error states and last
  successful digest.
- [ ] Assert absence of link, revoke, activate, execute, approve and edit
  controls in the responsibility panel.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_surface.py -q`
- [ ] Implement one section in the existing visual system and fetch only the
  existing Mandate list plus selected responsibility endpoint. Preserve current
  Task Workspace behavior; no framework or new page.
- [ ] Run surface/API tests and manually inspect the local page at desktop and
  narrow viewport. Record screenshots only as review evidence, not Product
  truth.
- [ ] Commit: `feat(product): render read-only responsibility view`.

### Task 6: Freeze cognitive-load measurement machinery, do not run the claim

**Files:**
- Create: `product_evals/mandate_responsibility_view/README.md`
- Create: `product_evals/mandate_responsibility_view/preregistration.json`
- Create: `product_evals/mandate_responsibility_view/score.py`
- Create: `tests/product_eval/test_mandate_responsibility_view_eval.py`

- [ ] Write RED tests for canonical artifact hashes, randomized/counterbalanced
  paired order, timing boundary validation, no imputation, frozen gold reasons,
  the unified `operator_attention_set`, mandatory recall and false-attention
  denominator.
- [ ] Ensure `UNKNOWN` receives mandatory-event credit only for a matching
  frozen source-gap gold reason.
- [ ] Run RED:
  `.venv/bin/python -m pytest tests/product_eval/test_mandate_responsibility_view_eval.py -q`
- [ ] Implement deterministic scorer and schema. Mark preregistration
  `DESIGN_ONLY / NOT_FROZEN / NOT_RUN` until hidden snapshots, independent
  adjudicator identity and founder participant timing are separately frozen.
- [ ] Commit: `test(product): define responsibility view value falsifier`.

### Task 7: Full verification and independent exact-head review

**Files:** all touched files; no new scope.

- [ ] Run targeted suite:
  `.venv/bin/python -m pytest tests/product/test_mandate_responsibility_contracts.py tests/product/test_mandate_responsibility_store.py tests/product/test_mandate_responsibility_projection.py tests/product/test_mandate_responsibility_api.py tests/product/test_mandate_responsibility_surface.py tests/product_eval/test_mandate_responsibility_view_eval.py -q`.
- [ ] Run full Product suite:
  `.venv/bin/python -m pytest tests/product tests/product_eval -q`.
- [ ] Run `.venv/bin/python -m ruff check packages/contracts/src packages/os_core/src apps/api_server tests/product tests/product_eval`.
- [ ] Run `.venv/bin/python -m pyright packages/contracts/src packages/os_core/src apps/api_server`.
- [ ] Run `git diff --check`, inspect `git status --short`, and verify the branch
  diff contains no Research/runtime/provider/effect changes.
- [ ] Request one independent exact-head diff review. Required verdict:
  `APPROVE_MANDATE_RESPONSIBILITY_VIEW_INTEGRATION`.
- [ ] If review finds P0/P1 defects, add new RED tests before fixes and repeat
  full verification; do not narrative-close defects.

### Task 8: Truth sync, merge and push without release

**Files:**
- Modify: `docs/CURRENT_STATE.yaml`
- Modify parent root `docs/CURRENT_STATE.yaml` only after AgentOS main advances.
- Append durable handoff/messages under the existing founder-control run.

- [ ] Record exact branch head, test counts, review verdict and claim ceiling:
  implemented/tested/integrated, cognitive-load falsifier `NOT_FROZEN / NOT_RUN`,
  no autonomy claim, no release.
- [ ] Commit and push feature branch.
- [ ] Fast-forward merge to AgentOS `main` only if exact-head review passes and
  remote main still equals the validated base/expected successor.
- [ ] Push AgentOS main; then update/push parent root state with the exact AgentOS
  head. Do not release, tag or publish artifacts.

## Exit conditions

- One scoped view is reachable from the existing Agent Surface and API.
- Every visible item is derived from canonical Mandate/Task/Outcome/schedule
  sources; no copied responsibility truth exists.
- Bad linked items remain visible; broken authority joins fail closed.
- Link/revoke changes no Task, schedule, capability, provider or effect state.
- Full Product suite, Ruff, Pyright, diff-check and independent exact-head review
  pass.
- Cognitive-load claim remains `NOT_RUN` until the separately frozen human
  comparison is actually executed and adjudicated.
- No release.
