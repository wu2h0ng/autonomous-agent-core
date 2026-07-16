# P-SRL Event Admission 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add canonical authenticated event admission and an admission-required single-spine MandateSteward entry without creating another Runtime, assessor, store or effect path.

**Architecture:** Adapter-owned origin, canonical lease/credential and policy-attestation registries feed a durable admission service. A SQLite PENDING/COMPLETED outbox surrounds the existing `OperationalProposalService`; the application removes the public bypass and exposes only the receipt-required steward path.

**Tech Stack:** Python 3.12, Pydantic v2, sqlite3, stdlib protocols/locks, pytest, Ruff, Pyright.

## Global Constraints

- Exact implementation base: `8d5820c75a397a299bec898e783ee8113fd3d542`.
- Reuse all existing situated/provider/proposal/assessment contracts and services.
- No caller-supplied source, lease, attestation or receipt object becomes authority.
- No second product Runtime, provider assessor, assessment store, event ledger or proposal compiler.
- No raw payload/provider/secret/exception text in new durable records.
- RED before production code for every behavior.
- No live provider, training, multimodal, distributed Runtime, domain-generalization, merge, push, release or activation.

---

### Task 1: Content-addressed admission and outbox contracts

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/srl_event_admission.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Test: `tests/product/test_srl_event_admission_contracts.py`

**Produces:** `EventOriginRegistration`, `CredentialLeaseRef`, `PayloadAdmissionAttestation`, `EnvironmentEventAdmissionReceipt`, trace status/reason enums and `SituatedEvaluationTrace`.

- [ ] Write RED tests for exact ids/digests, every-field mutation sensitivity, chronology, numeric bounds, fixed-false fields and closed trace reasons.
- [ ] Run focused RED and record the expected missing/validation failures.
- [ ] Implement the minimal contracts and digest helpers.
- [ ] Run focused tests, Ruff and Pyright.
- [ ] Commit `feat(srl): add event admission contracts`.

### Task 2: Canonical origin, lease, credential and policy registries

**Files:**
- Create: `packages/os_core/src/agent_os_core/srl_event_authority.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_srl_event_authority.py`

**Produces:** read-only registry protocols, canonical lease/credential readers and composition-owned implementations; no public mutable origin/attestation surface.

- [ ] Write RED tests for caller-minted object rejection, event-to-origin lookup, canonical lease lookup, current CredentialRef digest/status/scope/expiry, issuer identity and policy-attestation lookup.
- [ ] Prove a boolean verifier, caller/Application-supplied origin/attestation or an unregistered same-content object cannot authorize admission.
- [ ] Implement minimal registries/readers.
- [ ] Run Tasks 1-2 tests, Ruff and Pyright.
- [ ] Commit `feat(srl): add canonical event authority registries`.

### Task 3: Durable admission and trace outbox store

**Files:**
- Create: `packages/os_core/src/agent_os_core/srl_event_store.py`
- Test: `tests/product/test_srl_event_store.py`

**Produces:** `SQLiteEventAdmissionStore` with separate reader/service-bound writer views, identity-checked object capability, receipt lookup by id/event and trace PENDING/COMPLETED/DENIED transitions.

- [ ] Write RED tests for durable restart, exact replay, changed-event conflict, trace transition legality, content conflict and no raw forbidden fields.
- [ ] Write RED tests proving direct receipt, fake proof, same-field object and serialized/deserialized token cannot write; only the service-bound writer can.
- [ ] Run focused RED.
- [ ] Implement SQLite schema/transactions and the service-bound identity-capability write path; do not rely on naming privacy.
- [ ] Run Tasks 1-3 tests, Ruff and Pyright.
- [ ] Commit `feat(srl): persist admission and steward outbox`.

### Task 4: Trusted event admission service

**Files:**
- Create: `packages/os_core/src/agent_os_core/srl_event_admission.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_srl_event_admission.py`

**Produces:** `EnvironmentEventAdmissionService.admit(event_id, lease_id, admitted_at=...)`.

- [ ] Write RED mutation tests for every origin/credential/lease/attestation/event/binding/epoch field and exact artifact bytes.
- [ ] Verify all failures occur before provider/assessment calls.
- [ ] Implement service resolution and receipt construction using current authority and trusted artifact ports.
- [ ] Run Tasks 1-4 tests plus existing situated scope/revoke tests, Ruff and Pyright.
- [ ] Commit `feat(srl): admit canonical environment events`.

### Task 5: Admission-required MandateSteward facade

**Files:**
- Create: `packages/os_core/src/agent_os_core/mandate_steward.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_mandate_steward.py`

**Produces:** receipt-required facade, process-local single flight and durable trace reconciliation around one existing `OperationalProposalService`.

- [ ] Write RED tests for current epoch/binding recheck, TaskDraft/Help/None/ABSTAIN matrix, one delegation/store, constant-return rejection, same-process concurrency and restart reconciliation after trace completion failure.
- [ ] Write a crash-window RED showing durable `delegation_attempt_count` increments while no exact provider-total claim is emitted before a committed assessment.
- [ ] Add forbidden-import AST and Task/connector/capability zero-effect tests.
- [ ] Implement thin facade; do not import provider implementations or effect paths.
- [ ] Run Tasks 1-5 and existing provider/situated/M0 suites, Ruff and Pyright.
- [ ] Commit `feat(srl): add admission-required mandate steward`.

### Task 6: Remove public bypass and bind Data Agent ingress

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/app.py`
- Test: `tests/product/test_data_agent_external_report_adapter.py`
- Test: `tests/product/test_data_agent_provider_relevance_e2e.py`

**Produces:** adapter-owned read-only origin/attestation resolution, canonical lease composition and receipt-required application proposal entry.

- [ ] Write RED tests that the legacy application entry without receipt fails before provider/persistence.
- [ ] Write RED E2E tests for exact derived registration, restart-stable derivation, caller/Application same-content object rejection, credential drift, foreign scope, replay and zero Task/effect.
- [ ] Make the adapter itself (or a tightly owning read-only wrapper) implement origin/attestation readers from durable state; Application must not copy/register these objects.
- [ ] Add only derived read methods/composition; do not rewrite fetching, redaction, cursor, trust or provider logic.
- [ ] Run Data Agent, steward, situated/provider and M0 regression suites, Ruff and Pyright.
- [ ] Commit `feat(product): require admission for situated proposals`.

### Task 7: Verification, independent review and truthful handoff

**Files:**
- Create: `.agent_runs/p-srl-event-admission-1-20260717/verification.md`
- Create: `.agent_runs/p-srl-event-admission-1-20260717/messages.jsonl`
- Create: `.agent_runs/p-srl-event-admission-1-20260717/handoff.jsonl`
- Modify: `docs/CURRENT_STATE.yaml` only after exact-diff approval.

- [ ] Run full Product tests, repository Ruff, full Product Pyright and `git diff --check 8d5820c..HEAD`.
- [ ] Generate exact review package and obtain independent spec/quality review.
- [ ] Fix every P0/P1, rerun covering tests and re-review.
- [ ] Record exact head, gates, persistence envelope and non-claims as `IMPLEMENTED_LOCAL_NOT_INTEGRATED`.
- [ ] Do not update root state, merge canonical, push or release.

## Plan self-review

- Revision 2 closes the public bypass, self-minted authority, stale receipt and false atomicity defects.
- Restart durability is assigned to SQLite; in-memory stores cannot close persistence gates.
- Provider exactly-once is not claimed beyond committed sequential/restart replay and same-process single flight.
- Positive activation, value falsifier results, production identity/KMS/DLP, distributed execution and learning remain out of scope.
