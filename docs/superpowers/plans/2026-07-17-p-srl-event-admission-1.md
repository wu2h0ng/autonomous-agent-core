# P-SRL Event Admission 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated event admission and a single-spine MandateSteward facade in front of the existing situated proposal path without creating a second Runtime, assessor, store or effect path.

**Architecture:** New contracts and a narrow admission service bind external source, credential lease, payload-safety attestation, scope, binding and correction epoch to an existing `EnvironmentEvent`. A thin `MandateSteward` verifies the receipt and delegates to the existing `OperationalProposalService`, returning only its existing proposal-only result and recording a safe local trace.

**Tech Stack:** Python 3.12, Pydantic v2, stdlib protocols/in-memory stores, pytest, Ruff, Pyright.

## Global Constraints

- Base exact head is `8d5820c75a397a299bec898e783ee8113fd3d542` on isolated branch `codex/p-srl-event-admission-1-20260717`.
- Reuse `EnvironmentEvent`, `OperationalProposalService`, `ProviderRelevanceAssessor`, `SituatedAssessmentRecord`, `SQLiteSituatedAssessmentStore`, `TaskDraftProposal` and `HelpRequest`.
- Do not add a second product Runtime, provider assessor, event ledger, assessment store, proposal compiler or Task activation path.
- New receipts and traces contain ids, digests, counts, durations and reason codes only; never raw observation, prompt, response, exception text, resolver key or credential secret.
- All new behavior follows strict RED then GREEN evidence.
- No provider network call, training, multimodal, distributed Runtime, generic Domain Adaptation, merge, push, release or activation.

---

### Task 1: Admission contracts

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/srl_event_admission.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Test: `tests/product/test_srl_event_admission_contracts.py`

**Interfaces:**
- Consumes: `ContractModel`, `NonEmptyStr`, `UtcDateTime`, `Sha256Digest`.
- Produces: `EventSourceRef`, `CredentialLeaseRef`, `PayloadSafetyAttestation`, `EnvironmentEventAdmissionReceipt`, `SituatedEvaluationTrace`, deterministic digest helpers.

- [ ] Write contract RED tests for exact SHA grammar, chronology, fixed-false authority fields, source/lease/safety scope consistency and content-addressed receipt identity.
- [ ] Run the focused file and retain expected RED output proving missing contracts/validators.
- [ ] Implement only the normative contract fields and validators from the design.
- [ ] Run focused tests, Ruff and Pyright on changed scope.
- [ ] Commit as `feat(srl): add event admission contracts`.

### Task 2: Trusted admission service and idempotent store

**Files:**
- Create: `packages/os_core/src/agent_os_core/srl_event_admission.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_srl_event_admission.py`

**Interfaces:**
- Consumes: Task 1 contracts, `EnvironmentEvent`, `RatifiedMandateRef`, `SituationalTrustResolver`, active mandate/binding resolver.
- Produces: registry protocols, deterministic in-memory registries/store, `EnvironmentEventAdmissionService.admit(...)`.

- [ ] Write RED tests for trusted admission, caller-minted source/lease/safety rejection, scope/binding/epoch mismatch, expired lease, trusted artifact digest, exact replay and changed-event conflict.
- [ ] Run focused tests and retain expected RED output.
- [ ] Implement trusted registries and admission service with no provider/assessment/effect dependency.
- [ ] Run focused tests, Task 1 tests, Ruff and Pyright.
- [ ] Commit as `feat(srl): admit authenticated environment events`.

### Task 3: Single-spine MandateSteward facade and safe trace

**Files:**
- Create: `packages/os_core/src/agent_os_core/mandate_steward.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_mandate_steward.py`

**Interfaces:**
- Consumes: `EventAdmissionStorePort`, `OperationalProposalService`, existing proposal result types, `SituatedTraceStorePort`.
- Produces: `MandateSteward.observe_event(...)`, in-memory trace store.

- [ ] Write RED tests proving exact receipt requirement, one delegation, no second assessor/store, exact replay without a second provider call, revoke/epoch dominance, proposal-only result, safe trace allowlist and fail-closed trace failure.
- [ ] Run focused tests and retain expected RED output.
- [ ] Implement the thin facade without importing TaskService, CapabilityBroker, connector/effect APIs or provider implementations.
- [ ] Add AST/bypass tests that fail if forbidden imports or direct effects appear.
- [ ] Run focused tests, Tasks 1-2 tests, existing situated/provider/Data Agent/M0 regression suites, Ruff and Pyright.
- [ ] Commit as `feat(srl): add single-spine mandate steward facade`.

### Task 4: First concrete Data Agent ingress binding

**Files:**
- Modify: `apps/api_server/data_agent_report_adapter.py`
- Modify: `apps/api_server/app.py`
- Test: `tests/product/test_data_agent_provider_relevance_e2e.py`
- Test: `tests/product/test_data_agent_external_report_adapter.py`

**Interfaces:**
- Consumes: existing `TrustedObservationBundle`, Data Agent credential/source configuration, Task 1 admission contracts and Task 2 service.
- Produces: exact event source, lease and payload-safety registrations plus a public local application entry that calls the existing single steward facade.

- [ ] Write RED E2E tests for receipt binding, foreign/expired credential rejection before provider, exact replay and zero Task creation/effect.
- [ ] Run focused tests and retain expected RED output.
- [ ] Add the smallest adapter composition needed to produce trusted registry entries; do not expose secrets or add a new provider path.
- [ ] Run focused Data Agent and MandateSteward suites, Ruff and Pyright.
- [ ] Commit as `feat(product): bind data agent events to steward admission`.

### Task 5: Verification, exact-diff review and state handoff

**Files:**
- Create: `.agent_runs/p-srl-event-admission-1-20260717/verification.md`
- Create: `.agent_runs/p-srl-event-admission-1-20260717/messages.jsonl`
- Create: `.agent_runs/p-srl-event-admission-1-20260717/handoff.jsonl`
- Modify: `docs/CURRENT_STATE.yaml` only after exact implementation review is approved.

**Interfaces:**
- Consumes: Tasks 1-4 exact commits and test evidence.
- Produces: truthful `IMPLEMENTED_LOCAL_NOT_INTEGRATED` evidence and a canonical admission packet.

- [ ] Run full Product tests: `UV_CACHE_DIR=/tmp/uv-cache-p-srl-event-admission uv run --extra product-test pytest tests/product -q`.
- [ ] Run repository Ruff and full Product Pyright using the commands in `AGENTS.md`.
- [ ] Run `git diff --check 8d5820c..HEAD` and confirm clean worktree.
- [ ] Obtain an independent exact-diff review; remediate every P0/P1 and re-review.
- [ ] Update target `CURRENT_STATE` with exact head, tests, residual gaps and explicit non-claims; do not update root state until canonical integration or a separate root truth-sync action.
- [ ] Commit evidence/state only after fresh verification.

## Plan self-review

- Every new production object has a named test-first task and a real consumer.
- No task reimplements existing situated contracts, provider relevance, assessment persistence or proposal compilation.
- Positive Task activation, E2E value claims, production KMS/DLP, distributed runtime, training, multimodal and generic domain adaptation are explicitly excluded.
- No placeholder, open-ended implementation step or unbound completion claim remains.
