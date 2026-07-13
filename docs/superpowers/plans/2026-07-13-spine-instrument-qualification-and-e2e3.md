# SPINE Instrument Qualification and E2E-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a machine-enforced constructability gate that makes stale successor constants and request digests fail before freeze, then construct a fresh qualified SPINE-E2E-3 candidate.

**Architecture:** A derived typed identity is the only source for correlated successor values. A deterministic builder produces the provider bank from a model-free, digest-free template; a no-formal-ledger canary verifies bank semantics and authentication and emits a hash-bound receipt consumed by E2E-3 preflight.

**Tech Stack:** Python 3.12 standard library, pytest, existing Product packages, existing frozen replay protocol.

## Global Constraints

- Product-evaluation infrastructure only; no Product runtime or Research Track mechanism changes.
- `product_evals/spine_e2e_1`, `product_evals/spine_e2e_2`, and prior result artifacts are immutable.
- No formal evaluation phase may run until a fresh candidate commit, independent reviews, manifest, preregistration freeze, and founder permission exist.
- No rescue or rerun of E2E-1/E2E-2.

---

### Task 1: Freeze immutable baseline and RED contracts

**Files:**
- Create: `tests/product_eval/test_instrument_qualification.py`
- Modify: `tests/product_eval/test_spine_e2e_2_cli.py`

**Interfaces:**
- Consumes: base commit `7d62270536f51c2ec99c242f84583c3cb2c8acbd` and current provider-bank behavior.
- Produces: failing tests for derived identity, bank generation, stale-literal rejection, auth canary, receipt binding, and explicit ledger-path isolation.

- [ ] Write tests that import the wished-for `SpineEvaluationIdentity`, `build_provider_bank`, `qualify_instrument`, and `verify_qualification_receipt` APIs.
- [ ] Add separate mutations for request model, response model, digest, bearer, duplicate case ID, and generated-bank byte drift.
- [ ] Change the E2E-2 dependency preflight test to pass a temporary run object instead of consulting the preserved formal ledger.
- [ ] Run `python3 -m pytest tests/product_eval/test_instrument_qualification.py tests/product_eval/test_spine_e2e_2_cli.py -q` and confirm failures are caused by missing common qualification APIs, while the isolation regression fails for the known real-ledger coupling.

### Task 2: Implement common identity, generator, and qualifier

**Files:**
- Create: `product_evals/common/instrument_qualification.py`
- Modify: `product_evals/common/provider_bank.py`
- Test: `tests/product_eval/test_instrument_qualification.py`

**Interfaces:**
- Consumes: `SpineEvaluationIdentity.create(sequence: int, run_date: str)` and a provider-bank template mapping.
- Produces: `build_provider_bank(identity, template) -> dict`, `write_provider_bank(...)`, `qualify_instrument(...) -> dict`, `verify_qualification_receipt(...) -> dict`, and an identity-bound replay-server constructor.

- [ ] Implement strict identity validation and derived properties without caller-supplied correlated strings.
- [ ] Implement deterministic canonical JSON generation and exact request-body digest calculation.
- [ ] Add an explicit bearer parameter to the replay server while preserving the historical default only for frozen legacy callers; require the identity-bound wrapper for new successors.
- [ ] Implement scratch-ledger wrong-bearer and correct-bearer canaries, formal-ledger absence checks, and deterministic receipt hashing.
- [ ] Run the focused RED tests until green, then run `python3 -m pytest tests/product_eval/test_provider_bank.py tests/product_eval/test_instrument_qualification.py -q`.

### Task 3: Construct E2E-3 from identity-bound sources

**Files:**
- Create: `product_evals/spine_e2e_3/__init__.py`
- Create: `product_evals/spine_e2e_3/identity.py`
- Create: `product_evals/spine_e2e_3/provider_bank_template.json`
- Create: `product_evals/spine_e2e_3/provider_responses.json`
- Create: `product_evals/spine_e2e_3/instrument_qualification_receipt.json`
- Create: `product_evals/spine_e2e_3/cli.py`
- Create: `product_evals/spine_e2e_3/coordinator.py`
- Create: `product_evals/spine_e2e_3/frozen_cases.json`
- Create: `product_evals/spine_e2e_3/protocol.py`
- Create: `product_evals/spine_e2e_3/public_surface.py`
- Create: `tests/product_eval/test_spine_e2e_3_cli.py`
- Create: `tests/product_eval/test_spine_e2e_3_protocol.py`

**Interfaces:**
- Consumes: common identity/generator/qualifier APIs and the preserved semantic E2E-2 case/protocol design.
- Produces: a new, unfrozen, unrun successor candidate whose correlated values are identity-derived and whose bank/receipt regenerate exactly.

- [ ] Copy semantic protocol/case behavior into the new namespace without importing an old successor at runtime.
- [ ] Replace module-level experiment/model/key/bearer/schema literals with `IDENTITY` properties.
- [ ] Generate the bank from the model-free/digest-free template; do not hand-edit generated digests.
- [ ] Make prepare genesis verify the committed qualification receipt before any phase/provider ledger access.
- [ ] Scan the entire E2E-3 scope for `spine-e2e-1`, `spine-e2e-2`, `SPINE_E2E_1`, and `SPINE_E2E_2`; the result must be empty.
- [ ] Run focused E2E-3 tests and the qualifier twice; the second generated bank and receipt must be byte-identical.

### Task 4: Verify candidate and preserve historical evidence

**Files:**
- Modify after verification: `docs/CURRENT_STATE.yaml`
- Modify after verification: `codebase_index.md`
- Create: `docs/research/SPINE-INSTRUMENT-QUAL-1-result.md`

**Interfaces:**
- Consumes: completed diff and fresh test output.
- Produces: bounded local-slice status and candidate readiness record; no experimental verdict.

- [ ] Run Product-eval, Product-only, Ruff, format check, and full relevant suite.
- [ ] Compare `product_evals/spine_e2e_1`, `product_evals/spine_e2e_2`, `docs/research/SPINE-E2E-1-result.md`, and `docs/research/SPINE-E2E-2-result.md` against base commit; require zero diff.
- [ ] Record exact test counts and qualification receipt hashes without claiming SPINE PASS.
- [ ] Request Claude diff review; fix every accepted finding with a new RED-GREEN cycle.
- [ ] Commit the qualified candidate. Stop before preregistration freeze or formal run unless a separate exact-content review/freeze chain is complete.

### Task 5: Fresh freeze/run chain only after candidate acceptance

**Files:**
- Create only after independent acceptance: `docs/research/SPINE-E2E-3-preregistration-spec.yaml`
- Create only through runner: `.agent_runs/spine-e2e-3-20260713/prereg.json`, reviews, manifest, `prereg.lock`, phase ledgers, and result.

**Interfaces:**
- Consumes: clean qualified candidate commit and independent review artifacts.
- Produces: at most one fresh frozen E2E-3 run and mechanical adjudication.

- [ ] Obtain independent content and architecture reviews that execute the public qualifier.
- [ ] Bind identity source, template, generated bank, verifier, receipt, protocol, cases, and CLI in the exact-content manifest and lock.
- [ ] Freeze under a distinct identity, verify zero drift, and execute one formal run.
- [ ] Mechanically adjudicate the result; construct D2 only if the frozen SPINE result is PASS.
- [ ] Preserve any INVALID/NOT_PASS result without rescue, rerun, or gate movement.
