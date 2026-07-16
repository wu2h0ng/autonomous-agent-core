# Data Agent Situated Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the test-only self-minted receipt path with a real, durable Data Agent ingress -> admission receipt -> MandateSteward Product composition.

**Architecture:** A production-owned bootstrap composes the existing durable Data Agent adapter, deterministic read-only admission material, composition-owned credential lease, scoped admission/assessment stores and receipt-required steward. `AgentOSApplication` exposes only observe, admit and receipt-required propose methods; Task activation and effects remain absent.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, sqlite3, stdlib protocols, pytest, Ruff and Pyright.

## Global Constraints

- Exact base is `46405a31fd71d95d9cd19440fda59a810f13d32d`.
- Reuse `EnvironmentEventAdmissionService`, `MandateSteward`, `OperationalProposalService` and existing scoped persistence.
- No caller-supplied origin, attestation, lease, credential snapshot, receipt, writer or raw assessment store.
- No compatibility shim for the two-argument proposal path.
- No Task activation, connector/capability invocation, provider result run, training, merge, push or release.
- Every production behavior begins with a failing or bypass-detecting test.

---

### Task 1: Deterministic adapter-owned admission material

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Test: `tests/product/test_data_agent_external_report_adapter.py`

**Interfaces:**
- Consumes: durable `DataAgentReportAdapter.resolve_event/resolve_artifact` and frozen `DataAgentReportSourceConfig`.
- Produces: `DataAgentAdmissionMaterialReader.resolve_event(event_id)` for both `EventOriginRegistration` and `PayloadAdmissionAttestation`, plus safe source/credential snapshots used by composition.

- [ ] Add RED tests proving origin/attestation APIs are absent and that test-only fixed digest receipts cannot satisfy production composition.
- [ ] Add mutation RED for source config, event, observation, credential and frozen schema/policy fields; add restart byte-equality and secret-sentinel assertions.
- [ ] Run the exact RED tests and record failures caused by the missing reader.
- [ ] Implement the minimal deterministic reader using canonical dict payloads and existing digest helpers.
- [ ] Run focused tests, Ruff and Pyright; commit `feat(product): derive data agent admission material`.

### Task 2: Composition-owned admission facade

**Files:**
- Create: `apps/api_server/data_agent_situated_bootstrap.py`
- Test: `tests/product/test_data_agent_situated_bootstrap.py`

**Interfaces:**
- Consumes: adapter/material reader, principal, situated control/assessor, database, clock and private transport/credential dependencies.
- Produces: `DataAgentAdmissionFacade.admit_event(event_id) -> EnvironmentEventAdmissionReceipt` and `DataAgentSituatedBootstrap.build(...) -> AgentOSApplication`.

- [ ] Write RED tests for no caller lease/authority arguments, deterministic lease bytes, correction-epoch binding, inactive/expired/revoked/drifted credential, foreign scope and dependency exception redaction.
- [ ] Write a real RED E2E: durable adapter pull -> admission -> receipt -> steward result -> restart replay; assert zero Task/effect and exact receipt/trace reuse.
- [ ] Run RED and verify failures are missing composition rather than fixtures.
- [ ] Implement a private dynamic lease registry and facade, then compose the existing admission service, proposal service and steward without new Runtime/store/assessor implementations.
- [ ] Run Task 1-2 tests plus event admission, steward and security suites; commit `feat(product): compose data agent situated runtime`.

### Task 3: Bind the production Application surface

**Files:**
- Modify: `apps/api_server/app.py`
- Modify: `tests/product/test_data_agent_provider_relevance_e2e.py`
- Modify: `tests/product/test_data_agent_external_report_adapter.py`
- Remove or stop using: `tests/product/_steward_app.py`

**Interfaces:**
- Consumes: one scope-bound `DataAgentSituatedRuntime` produced by Task 2.
- Produces: `AgentOSApplication.admit_data_agent_event(event_id)` and the existing receipt-required `propose_situated_work(event_id, projection_id, admission_receipt_id)`.

- [ ] Add RED AST and runtime tests proving Application cannot directly call `OperationalProposalService.propose`, construct a receipt, access a private writer or accept admission authority through its public constructor.
- [ ] Add RED that uncomposed admission and legacy two-argument proposal fail before assessment/provider/trace/Task/effect.
- [ ] Replace test helper composition with the Task 2 bootstrap and bind the runtime through one private scope-checking classmethod.
- [ ] Run the focused Data Agent/provider/situated/security suites; commit `feat(product): require real admission for data agent proposals`.

### Task 4: Verification and handoff

**Files:**
- Create: `.superpowers/sdd/task6-report.md`
- Do not modify: `docs/CURRENT_STATE.yaml` before independent exact-head approval.

**Interfaces:**
- Consumes: Tasks 1-3 exact commits.
- Produces: exact-head Product integration candidate and non-claim report.

- [ ] Run focused suites, all `tests/product`, repository Ruff, Product Pyright and `git diff --check 46405a3..HEAD`.
- [ ] Scan production Application and bootstrap AST for direct proposal/admission-writer/receipt-constructor bypasses.
- [ ] Record entry points, contracts, failures, trace/receipt evidence, security scope, database compatibility and deferred claims.
- [ ] Obtain independent spec/code/security review; fix every P0/P1 and repeat exact-head review.
- [ ] Leave state `IMPLEMENTED_LOCAL_NOT_CANONICALLY_INTEGRATED`; do not merge, push or release.

## Plan self-review

- Every design requirement maps to Tasks 1-4.
- The adapter owns derivation; the bootstrap owns authority composition; Application owns only safe user entry points.
- No new Runtime, assessor, general registry or Task activation path is introduced.
- The plan explicitly replaces, rather than legitimizes, the test-only self-minted receipt path.
- Compatibility breaks remain fail-closed and are not hidden by shims.

