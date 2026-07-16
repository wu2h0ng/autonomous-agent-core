# Data Agent Situated Bootstrap Implementation Plan

> **For agentic workers:** use TDD and a single writer per AllowedPaths scope. Kimi/OpenCode sessions are valid writers only in their assigned isolated worktree; they may not merge, push, release or change acceptance criteria.

**Goal:** replace the test-only self-minted receipt path with executable payload validation, durable admission material, current authority checks and a real local Data Agent ingress -> receipt -> MandateSteward entry.

**Base:** `46405a31fd71d95d9cd19440fda59a810f13d32d` plus this revised design commit.

## Global constraints

- Reuse `EnvironmentEventAdmissionService`, `MandateSteward`, `OperationalProposalService` and existing scoped persistence.
- No caller-supplied origin, attestation, lease, credential snapshot, receipt, writer, store or raw authority object.
- No adapter-owned attestation; no caller-supplied schema/policy digest.
- No mutable lease registry, no Task activation/effect, no provider result-bearing run, no training, merge, push or release.
- Public start path may load locators/configuration but cannot mint Mandate/binding/credential authority.
- Every production behavior begins with a failing or bypass-detecting test.

---

### Task 1: Independent executable validator and atomic material

**AllowedPaths:**
- Create `apps/api_server/data_agent_report_admission.py`
- Create `tests/product/test_data_agent_report_admission.py`

- [ ] RED: adapter has no `PayloadAdmissionAttestation` construction/import; validator accepts no caller schema/policy digest.
- [ ] RED: duplicate keys, NaN/Infinity, invalid UTF-8, oversize, hash-only-invalid payload, audience/redaction/trace/event/artifact/scope/type/id drift all produce zero material rows.
- [ ] RED: credential reflection and dependency exception use fixed safe errors; no secret, resolver key, body or exception text enters material DB/log/error.
- [ ] RED: first truthful validation time is used; restart with later clock returns byte-identical origin/attestation; policy/version drift and DB corruption fail closed.
- [ ] RED: origin/attestation write is atomic and concurrent identical prepare converges while conflicting content denies.
- [ ] Implement frozen executable descriptors, validator, registrar, dual read-only views and insert-only SQLite material store.
- [ ] Run focused tests, Ruff, Pyright and `git diff --check`; commit only if the task packet authorizes it.

### Task 2: Current-authority admission facade and runtime

**AllowedPaths:**
- Create `apps/api_server/data_agent_situated_bootstrap.py`
- Create `tests/product/test_data_agent_situated_bootstrap.py`

- [ ] RED: facade signature only accepts `event_id`; public objects expose no writer/store/registry/authority mutation.
- [ ] RED: deterministic lease bytes across calls/restart; every lease field mutation, clock-based issuance, expiry overflow, unknown/accumulated lease and cross-event lease fail closed.
- [ ] RED: after bootstrap, credential ACTIVE->REVOKED, scope removal, expiry shortening, digest/content rotation and owner/tenant/workspace drift deny the next not-yet-admitted event without restart.
- [ ] RED: correction epoch changes before admission, after receipt/before proposal and after restart follow current semantics; old-event conflicts do not create a second receipt.
- [ ] RED: same durable adapter/admission/situated databases replay exact material/receipt/trace without network or second provider call; wrong/corrupt DB or scope fails closed.
- [ ] Implement `DataAgentAdmissionFacade`, pure deterministic lease derivation, one-event immutable lease registry and scope-bound `DataAgentSituatedRuntime`.
- [ ] Compose existing admission/proposal/steward services; do not modify core contracts, authority, admission, steward or stores.
- [ ] Run Task 1-2 and focused admission/steward/security suites.

### Task 3: Bind the Application surface

**AllowedPaths:**
- Modify `apps/api_server/app.py`
- Modify `tests/product/test_data_agent_provider_relevance_e2e.py`
- Modify `tests/product/test_api_surface.py`
- Stop using `tests/product/_steward_app.py` for this path; do not migrate its receipt construction.

- [ ] RED AST/runtime: public constructor accepts no situated runtime/steward/writer/lease/origin/attestation/credential; Application cannot construct receipts or call raw `OperationalProposalService.propose`.
- [ ] RED: uncomposed admission, fake/wrong-scope runtime and legacy two-argument proposal fail before assessment/provider/trace/Task/effect.
- [ ] Add private scope-checking runtime binder and safe `observe_data_agent_report`, `admit_data_agent_event`, receipt-required proposal, plus one combined proposal-only operation accepting only `trace_id`.
- [ ] Replace the real Product E2E helper path with Task 2 composition; retain zero Task/effect assertions.
- [ ] Run focused API/Data Agent/provider/situated/security suites.

### Task 4: Real local CLI/API startup

**AllowedPaths:**
- Create `apps/api_server/_data_agent_situated_startup.py`
- Create `tests/product/test_data_agent_situated_startup.py`
- Modify `apps/api_server/__main__.py`
- Modify `apps/api_server/server.py`
- Modify only the directly related API tests if needed.

- [ ] RED: `--data-agent-situated-config` selects the private composed factory and `serve` receives the configured Application; without it, legacy startup remains unchanged.
- [ ] RED: strict bounded regular-file JSON rejects symlink, extra/import/factory/raw authority fields and contains no secret; resolver env key never appears in errors/logs.
- [ ] RED: startup resolves an already-persisted active Mandate/binding and exact digest/version/epoch/scope/policy/context/provider bindings; missing/paused/revoked/expired/mismatched authority fails before serve.
- [ ] RED: local endpoint accepts only `trace_id`; raw event/origin/attestation/lease/receipt/Mandate fields have no route.
- [ ] Implement private startup builder, CLI flag and one proposal-only local POST route. Configuration cannot bootstrap authority.
- [ ] E2E: one call pulls, validates, admits and proposes; restart reuses durable material; Task/effect counts remain zero.

### Task 5: Verification and handoff

**AllowedPaths:**
- Create `.superpowers/sdd/task6-report.md`
- Do not modify `docs/CURRENT_STATE.yaml` before independent exact-head approval.

- [ ] Run all focused suites, all `tests/product`, repository Ruff, Product Pyright and `git diff --check 46405a3..HEAD`.
- [ ] Scan production adapter/Application/bootstrap/startup AST for attestation self-signing, receipt construction, mutable authority/lease APIs and raw proposal bypasses.
- [ ] Record public entry, contracts, failures, durable evidence, credential-revocation semantics, local-deployment boundary and deferred claims.
- [ ] Obtain independent Kimi/OpenCode/Codex spec, code and security review; fix all P0/P1 and repeat exact-head review.
- [ ] Leave `IMPLEMENTED_LOCAL_NOT_CANONICALLY_INTEGRATED`; do not merge, push or release.

## Writer allocation

- Task 1 and Task 2 have disjoint files and may run in parallel after this plan is committed.
- Task 3 starts only after Task 2 interface is accepted.
- Task 4 may start its config/CLI RED in parallel, but its final composition wiring waits for Tasks 2-3.
- Codex owns integration and contested authority surfaces. Kimi/OpenCode may own an isolated task module and its tests with exact AllowedPaths; a different model performs read-only review.
