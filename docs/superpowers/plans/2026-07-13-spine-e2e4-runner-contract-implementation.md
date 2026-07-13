# SPINE-E2E-4 Runner Contract Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new SPINE successor whose provider identity and pinned-runner event contract are both generated, executed, and digest-bound before freeze.

**Architecture:** Keep the generic JSON-Schema consumer and authority binding in focused Product-evaluation modules. Construct `spine_e2e_4` from a new identity, invoke pinned runner `3a3224a...` through subprocess in scratch, and bind the exported schema plus real emitted fixture into an exact qualification receipt. Formal anchors consume the same schema and typed authority binding; no predecessor event-field set is copied.

**Tech Stack:** Python 3.12 stdlib, pytest, existing Product eval artifacts/phase ledger, fixed workflow runner subprocess, Git SHA-256 bindings.

## Global Constraints

- Preserve SPINE-E2E-1/2/3 source directories, formal ledgers, locks, receipts, and result records byte-identically.
- New identity: `SPINE-E2E-4`; new run: `spine-e2e-4-20260713`.
- Pinned runner branch: `codex/team-event-contract-v1-20260713`; exact head: `3a3224a7af7da724d8b6ec82d34ed47d938620e4`.
- No cross-repo import. Runner interaction is subprocess-only.
- No handwritten external event field set outside explicit predecessor-rejection fixtures.
- Test first and observe each target test fail before production implementation.
- Qualification and tests use scratch ledgers that cannot alias formal ledgers.
- No formal permission, preregistration, freeze, run, D2, or parent LH transition until Tasks 1-4 are committed, independently reviewed, and clean.
- Failed formal records are terminal; no retry, rescue, repair, or identity reuse.

---

## File Structure

- `product_evals/common/json_schema_contract.py`: strict stdlib consumer for the exact runner-exported JSON-Schema subset.
- `product_evals/common/authority_binding.py`: immutable verified permission/source binding.
- `product_evals/common/runner_contract_qualification.py`: subprocess schema export, scratch event canary, normalized fixture and receipt fields.
- `product_evals/spine_e2e_4/identity.py`: only numbered identity source.
- `product_evals/spine_e2e_4/runner_team_event_schema.json`: generated snapshot from the pinned runner.
- `product_evals/spine_e2e_4/instrument_qualification_receipt.json`: provider plus runner contract closure.
- `product_evals/spine_e2e_4/cli.py`: formal phases and schema-driven anchor verification.
- `tests/product_eval/test_runner_contract_qualification.py`: common negative/compatibility tests.
- `tests/product_eval/test_spine_e2e_4_*.py`: successor assets, formal path, protocol, and scratch subprocess tests.

### Task 1: Strict external JSON-Schema consumer

**Files:**
- Create: `product_evals/common/json_schema_contract.py`
- Create: `tests/product_eval/test_json_schema_contract.py`

**Interfaces:**
- Produces: `validate_closed_record(record: Mapping[str, Any], schema: Mapping[str, Any]) -> None`
- Produces: `canonical_schema_sha256(schema: Mapping[str, Any]) -> str`
- Produces: `normalize_timestamped_record(record: Mapping[str, Any], schema: Mapping[str, Any], timestamp_field: str = "ts") -> dict[str, Any]`

- [ ] **Step 1: Write failing tests**

Tests load the live schema using:

```python
subprocess.run(
    [RUNNER_PYTHON, "-m", "agent_workflow_runner.cli", "team", "event-schema"],
    cwd=RUNNER_WORKTREE,
    env={**os.environ, "PYTHONPATH": str(RUNNER_WORKTREE / "src")},
    check=True,
    text=True,
    capture_output=True,
)
```

Require acceptance of a conformant governed event and rejection of: extra field, missing
`schema_version`, unknown event type, empty approval ID, source token containing `/`, unsupported
schema keyword, mutated schema version, and non-string evidence item. Require normalization to
remove only `ts` and retain `source_evidence_refs` plus all source bindings.

- [ ] **Step 2: Verify RED**

Run:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. .venv/bin/python -m pytest tests/product_eval/test_json_schema_contract.py -q
```

Expected: collection or assertion failure because `json_schema_contract` does not exist.

- [ ] **Step 3: Implement the minimal validator**

Support only the pinned schema keywords: `$schema`, `title`, `type`, `properties`, `required`,
`additionalProperties`, `const`, `enum`, `minLength`, `pattern`, and `items`. Reject any other
keyword before validating a record. Use `canonical_json_bytes` and `hashlib.sha256`; do not add a
JSON-Schema dependency.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused tests plus Ruff, then commit:

```text
git add product_evals/common/json_schema_contract.py tests/product_eval/test_json_schema_contract.py
git commit -m "feat(eval): consume pinned runner event schema"
```

### Task 2: Typed authority binding

**Files:**
- Create: `product_evals/common/authority_binding.py`
- Create: `tests/product_eval/test_authority_binding.py`
- Modify: `product_evals/spine_e2e_4/cli.py` only after its Task 3 scaffold exists

**Interfaces:**
- Produces immutable `AuthorityBinding` with request/approval hashes, IDs, source fields, action,
  affected path, decision, decider, and parsed timestamps.
- Produces `verify_authority_binding(run_root: Path, *, run_id: str, action: str, affected_path: str) -> AuthorityBinding`.

- [ ] **Step 1: Write failing permission-ledger tests**

Fixtures must cover exactly one valid request/approval and reject duplicate request, duplicate
approval, orphan/later conflict, self-approval, wrong affected path/action/run, missing or blank
source field, source value mismatch, naive timestamp, and approval timestamp not after request.

- [ ] **Step 2: Verify RED**

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. .venv/bin/python -m pytest tests/product_eval/test_authority_binding.py -q
```

Expected: missing module/API failure.

- [ ] **Step 3: Implement exact full-ledger verification**

Parse every JSONL row, canonical-hash the selected rows, enforce exact counts/order, and return a
frozen dataclass. Never return untyped dictionaries to the formal anchor path.

- [ ] **Step 4: Verify GREEN and commit**

```text
git add product_evals/common/authority_binding.py tests/product_eval/test_authority_binding.py
git commit -m "feat(eval): type formal authority bindings"
```

### Task 3: E2E-4 identity, assets, and real runner qualification

**Files:**
- Create: `product_evals/spine_e2e_4/` from new identity-owned assets, not by mutating E2E-3
- Create: `product_evals/common/runner_contract_qualification.py`
- Create: `tests/product_eval/test_runner_contract_qualification.py`
- Create: `tests/product_eval/test_spine_e2e_4_assets.py`
- Modify: `product_evals/common/instrument_qualification.py`

**Interfaces:**
- Produces `qualify_runner_contract(...) -> dict[str, Any]` and
  `verify_runner_contract_receipt(...) -> dict[str, Any]`.
- Receipt includes runner head/branch/common-dir, raw/canonical schema hashes, normalized emitted
  fixture hash, consumer/authority source hashes, and scratch alias proof.

- [ ] **Step 1: Add E2E-4 identity/assets tests and runner-canary tests**

Require the successor identity to generate model, bearer, schemas, run paths and provider bank.
The canary creates a temporary workspace, initializes a scratch run with the pinned runner,
creates/approves a synthetic `team.event.record` permission, writes evidence, invokes the real
`team event` CLI, validates the emitted event through Task 1, and checks exact Task 2 source
binding. Monkeypatching subprocess or hand-writing the event row is forbidden by the test.

- [ ] **Step 2: Verify RED**

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. .venv/bin/python -m pytest tests/product_eval/test_runner_contract_qualification.py tests/product_eval/test_spine_e2e_4_assets.py -q
```

Expected: missing E2E-4 and runner qualification APIs.

- [ ] **Step 3: Implement and generate assets**

Generate, never hand-edit:

```text
runner_team_event_schema.json
provider_responses.json
instrument_qualification_receipt.json
```

Reverification must rerun both provider and runner canaries and compare the exact canonical
receipt. Bind the pinned runner interpreter path and verify its imports before creating formal
ledgers.

- [ ] **Step 4: Mutation/alias verification and commit**

Mutate runner head, schema, fixture, consumer source, authority source, bearer, bank, template,
and formal-ledger alias one at a time; every mutation must fail. Commit only after focused tests
and Ruff are green.

### Task 4: Formal E2E-4 CLI and schema-driven anchors

**Files:**
- Create: `product_evals/spine_e2e_4/cli.py`, `coordinator.py`, `protocol.py`, `public_surface.py`
- Create: `tests/product_eval/test_spine_e2e_4_cli.py`
- Create: `tests/product_eval/test_spine_e2e_4_scratch_cli.py`
- Create: `tests/product_eval/test_spine_e2e_4_protocol.py`
- Create: `docs/research/SPINE-E2E-4-preregistration-spec.yaml`

**Interfaces:**
- Formal commands: `prepare`, `interrupt-batch`, `probe-active-lease`, `resume`, `adjudicate`,
  `record-runner-anchor`, `finalize-result`.
- `_phase_anchor` validates with Task 1 and exact Task 2 source values; it contains no external
  field-set literal.

- [ ] **Step 1: Write scratch-only formal-path tests**

Use a temporary run root and scratch ledgers. Cover phase order, write-once payloads, prior anchor,
real pinned-runner event, exact source binding, timing, adjudication, finalization, unknown/extra
event fields, partial phase, duplicate anchor, and CLI dispatch. Assert no E2E-1/2/3 helper is
called or modified.

- [ ] **Step 2: Verify RED**

Run the three E2E-4 test files; expected missing module/API failures.

- [ ] **Step 3: Implement minimal formal path**

Port only Product recovery mechanics from E2E-3. Replace permission dicts with
`AuthorityBinding`; replace event-field literals with the bound schema consumer; pass all source
fields explicitly to runner CLI; require qualification receipt reverification before genesis.

- [ ] **Step 4: Verify focused and full Product-eval suites**

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. .venv/bin/python -m pytest tests/product_eval -q
uv run --extra product-test ruff check product_evals tests/product_eval
uv run --extra product-test ruff format --check product_evals tests/product_eval
git diff --check
```

- [ ] **Step 5: Verify historical immutability and commit**

Compare E2E-1/2/3 directories and result docs to the pre-task base. Commit E2E-4 code/spec only.

### Task 5: Review, freeze, one run, and parent decision

**Files:**
- Run-local only until result: `.agent_runs/spine-e2e-4-20260713/`
- Result only after terminal outcome: `docs/research/SPINE-E2E-4-result.md`
- Authority updates after adjudication: `docs/CURRENT_STATE.yaml`, `docs/PROJECT_PLAN.md`, `codebase_index.md`

- [ ] **Step 1: Independent content and architecture reviews**

Require exact-head RR-0031 blind calibration, complete mechanism manifest, builder/reviewer
separation, content review, RR-0029 architecture review, Claude diff review, and exact runner
contract qualification receipt.

- [ ] **Step 2: Fresh founder-bound permission**

Create exactly one formal `team.event.record` request with all five anchor evidence refs and all
three source fields. Founder decision must be later, unique, and bound by canonical hashes.

- [ ] **Step 3: Freeze and verify**

Freeze exact clean Product and runner heads. Verify source spec bytes, mechanism bytes, schema,
qualification receipt, permission rows, and runner identity before genesis.

- [ ] **Step 4: Execute exactly once**

Run phases in frozen order, record one anchor after each completed phase, never retry a failed
record, and run external result verification only if `evaluation/result.json` exists.

- [ ] **Step 5: Independent mechanical adjudication**

Record `PASS`, `NOT_PASS`, or `INVALID` with exact hashes and absences. Construct D2 only on
verified PASS; otherwise preserve parent `LH-RECOVERY-1` as blocked.

## Plan Self-Review

- Spec coverage: Tasks 1-5 cover schema consumption, authority typing, real producer canary,
  qualification closure, formal anchors, review/freeze/run, and result disposition.
- Placeholder scan: no unresolved placeholders or open implementation decisions.
- Type consistency: Task 1 validator and Task 2 binding are consumed unchanged by Tasks 3-4.
- Scope: workflow contract is already separately committed; this plan changes Product-evaluation
  infrastructure only until the formal result updates authority docs.
