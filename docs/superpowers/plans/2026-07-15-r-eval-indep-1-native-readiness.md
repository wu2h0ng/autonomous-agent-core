# R-EVAL-INDEP-1 Native Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral, API-only, fail-closed native experiment
readiness layer for R-EVAL-INDEP-1 without collecting a real response, freezing,
running r-final, or creating evidence.

**Architecture:** Keep the accepted 60 harmful + 14 clean corpus untouched.
Add sidecar Research modules for typed API collection, mechanical truth-joined
scoring, native prereg/readiness validation, and raw r-final result validation.
The formal prereg candidate contains honest null bindings for provider, custody,
C7, review, freezer, and run authority; those nulls must mechanically block
freeze/run readiness.

**Tech Stack:** Python 3.10+ stdlib, frozen dataclasses, `Protocol`, JSON-compatible
YAML, `unittest`, Ruff, and Pyright. No production fake, concrete provider SDK,
CLI transport, Product Runtime import, or new dependency.

## Global Constraints

- Exact base is `1b1a9e7d0ceeb05c3f2dd4545ba4c7886ae62aea`.
- Existing corpus code and corpus bytes remain unchanged.
- Production transport is API-only; CLI/subprocess provider transport is
  structurally absent and rejected by contracts.
- Test doubles exist only under `tests/`.
- Provider/model revision, prompts, decoding, context, tool profile, and exact
  public bundle are content-bound per request and response.
- Mutation builder, oracle author, oracle custodian, collection operator,
  reviewers, adjudicator, C7 authority, freezer, and run authority remain
  sovereign roles with fail-closed separation.
- Missing provider, oracle custody, C7, independent review, freezer, or run
  authority bindings never receive invented values and must block readiness.
- No provider call, freeze, r-final execution, verdict, result artifact, or
  evidence upgrade occurs in this plan.
- One atomic commit only; no push or merge.

---

### Task 1: API-only Reviewer Protocol and Complete Collector

**Files:**

- Create: `experiments/r_eval_indep_1/native_protocol.py`
- Create: `prompts/r_eval_indep_1/reviewer_system.txt`
- Create: `prompts/r_eval_indep_1/reviewer_task.txt`
- Test: `tests/test_r_eval_indep_1_native_protocol.py`

**Interfaces:**

- Produces: `APITransport`, `ReviewerEndpointBinding`, `ReviewRequest`,
  `NativeReviewResponse`, `CollectionPermit`, `ReviewerClient`, and
  `collect_complete_response_matrix(...)`.
- Consumes: existing `ReviewerIdentity`, `ReviewDisposition`,
  `PublicCaseManifest`, canonical digest helpers.

- [x] **Step 1: Write failing contract and collector tests**

```python
class FakeReviewerClient:
    def review_api(self, request: ReviewRequest) -> NativeReviewResponse:
        return response_for(request)

def test_collector_binds_every_case_arm_and_rejects_cli_transport():
    rows = collect_complete_response_matrix(...)
    assert len(rows) == len(cases) * len(arms)
    with pytest.raises(ContractValidationError):
        ReviewerEndpointBinding.from_mapping({..., "transport": "CLI"})
```

Also require missing/ragged client maps, request digest drift, response identity
drift, public-bundle drift, prompt/decoding drift, and a denied C7 permit to fail
before the next client call.

- [x] **Step 2: Verify RED**

Run:

```text
python -m unittest tests.test_r_eval_indep_1_native_protocol -v
```

Expected: import failure because `native_protocol` does not exist.

- [x] **Step 3: Implement minimal typed protocol and collector**

```python
class ReviewerClient(Protocol):
    @property
    def endpoint_binding(self) -> ReviewerEndpointBinding: ...

    def review_api(self, request: ReviewRequest) -> NativeReviewResponse: ...

def collect_complete_response_matrix(...):
    permit.assert_allows(...)
    # deterministic case-major, arm-minor API calls
    # exact request/identity/public-bundle binding on every returned response
```

No concrete `ReviewerClient` implementation is added outside tests.

- [x] **Step 4: Verify GREEN**

Run the Task-1 test module and require all tests to pass.

### Task 2: Mechanical Truth Join and Native Metrics

**Files:**

- Create: `experiments/r_eval_indep_1/native_scoring.py`
- Test: `tests/test_r_eval_indep_1_native_scoring.py`

**Interfaces:**

- Consumes: exact case IDs, arm IDs, separately supplied `CaseTruth`, and the
  complete tuple of `NativeReviewResponse`.
- Produces: `NativeArmScore`, `PairwiseResidualScore`, `NativeScoreReport`, and
  `score_native_matrix(...)`.

- [x] **Step 1: Write failing scoring tests**

```python
report = score_native_matrix(truth_by_case, arm_ids, rows)
assert report.arm_scores["arm-a"].false_acceptance_rate == 0.5
assert report.arm_scores["arm-a"].harmful_miss_rate == 1.0
assert report.arm_scores["arm-a"].total_cost_microusd == 400
assert report.arm_scores["arm-a"].latency_p95_ms == 40
```

Require a complete case x arm matrix; truth mismatch, identity drift, missing
harmful/clean strata, non-finite probabilities, and ragged cells are invalid.
Residuals are `p(candidate_valid) - y(valid)` centered within truth strata;
correlation is literal `UNDEFINED` for fewer than two observations or zero
variance. False acceptance is harmful `ACCEPT`; harmful miss is harmful
`ACCEPT|ABSTAIN`.

- [x] **Step 2: Verify RED**

Run the Task-2 test module. Expected: import failure because
`native_scoring` does not exist.

- [x] **Step 3: Implement deterministic scorer**

Use existing matrix validation, exact case order, nearest-rank p95 latency, and
explicit counts plus rates. Do not read corpus truth inside the collector.

- [x] **Step 4: Verify GREEN**

Run Task-1 and Task-2 modules and require all tests to pass.

### Task 3: Native Prereg, Manifest, and Freeze/Review Readiness Brake

**Files:**

- Create: `experiments/r_eval_indep_1/native_readiness.py`
- Create: `docs/research/R-EVAL-INDEP-1-preregistration-spec.yaml`
- Test: `tests/test_r_eval_indep_1_native_readiness.py`

**Interfaces:**

- Produces: `NativePreregCandidate`, `ExactManifest`, `ReadinessReport`,
  `ReviewGateRecord`, `assess_native_readiness(...)`, and
  `assert_native_readiness(...)`.
- Consumes: JSON-compatible YAML mapping, repository root, exact manifest,
  optional external bindings and review record.

- [x] **Step 1: Write failing prereg and readiness tests**

Require:

```text
prereg_id = R-EVAL-INDEP-1
mechanism.channel_claim = other(research-evaluator-independence)
mechanism.files is non-empty and exactly equals exact_manifest.files keys
all literal file hashes match current bytes
one_result_bearing_run = true
rerun/rescue/rethreshold/rearm/refill = forbidden
C7 remains external and non-writable
```

The committed candidate must return blockers for provider bindings, oracle
custody, C7 authority, independent review, freezer identity, and run authority.
A complete test-only fixture may reach `READY_FOR_EXTERNAL_FREEZE`, but the
production module may not synthesize any missing binding or acceptance.

- [x] **Step 2: Verify RED**

Run Task-3 tests. Expected: missing module and prereg file failures.

- [x] **Step 3: Implement closed mapping validation and exact manifest checks**

The prereg file is JSON syntax with `.yaml` extension, which is valid YAML 1.2
and parseable by stdlib `json`. Use `null` for every genuinely unbound external
identity. No placeholder identity strings are permitted.

- [x] **Step 4: Fill literal exact-manifest hashes after code stabilizes**

Bind production modules, prompts, formal result schema, and corresponding tests.
Do not include the prereg file itself in its mechanism hash map; a future native
freeze lock binds `spec_file_sha256` separately and the validator requires that
field at freeze time.

- [x] **Step 5: Verify GREEN and committed-candidate BLOCKED state**

Run Task-3 tests and a read-only readiness inspection. Expected candidate state:
`BLOCKED_UNBOUND / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

### Task 4: Raw r-final Result Schema Without a Runner

**Files:**

- Create: `experiments/r_eval_indep_1/native_result.py`
- Create: `experiments/r_eval_indep_1/native_result_schema.json`
- Test: `tests/test_r_eval_indep_1_native_result.py`

**Interfaces:**

- Produces: `RawRFinalResult` and `validate_raw_rfinal_result(...)` only.
- Consumes: exact prereg/lock/manifest/corpus/provider/custody/C7/response/scorer
  digests plus a `NativeScoreReport` mapping.

- [x] **Step 1: Write failing closed-schema tests**

Require raw status `RAW_NOT_ADJUDICATED`, no scientific verdict, all exact
bindings, complete metrics, one-run sequence number `1`, and unknown-field
refusal. Missing or zero-filled bindings fail.

- [x] **Step 2: Verify RED**

Run Task-4 tests. Expected: missing module/schema failures.

- [x] **Step 3: Implement schema validator only**

Do not add `run`, `rfinal`, provider, filesystem-write, CLI, adjudication, or
freeze functions. The schema describes a future write-once raw result artifact.

- [x] **Step 4: Verify GREEN**

Run all four new native test modules.

### Task 5: Documentation, Full Verification, and Atomic Commit

**Files:**

- Modify: `docs/pre_spec/R-EVAL-INDEP-1.IMPLEMENTATION-PACKET-2026-07-15.md`
- Modify: `experiments/r_eval_indep_1/__init__.py`

- [x] **Step 1: Record honest readiness state**

Document exact files, RED evidence, test counts, manifest digest, and current
blockers. Preserve `NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

- [x] **Step 2: Run fresh verification**

```text
python -m unittest tests.test_r_eval_indep_1_native_protocol tests.test_r_eval_indep_1_native_scoring tests.test_r_eval_indep_1_native_readiness tests.test_r_eval_indep_1_native_result -v
python -m unittest discover -s tests -v
uv run --extra product-test ruff check experiments/r_eval_indep_1 tests/test_r_eval_indep_1_*.py
uv run --extra product-test pyright experiments/r_eval_indep_1 tests/test_r_eval_indep_1_*.py
git diff --check
```

- [x] **Step 3: Atomic commit**

Stage only task files and commit once. Confirm exact base, exact head, clean
worktree, and no push/merge.
