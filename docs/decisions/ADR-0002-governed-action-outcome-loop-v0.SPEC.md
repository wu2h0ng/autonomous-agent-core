# Governed-Action Outcome Loop v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close one reversible governed-action outcome loop: operator-approved action execution, causal adoption attestation, weighted knowledge promotion, and rollback.

**Architecture:** Reuse the existing P5 substrate. OS Core keeps domain-independent contracts and runtime gates; API/CLI own transport wiring; action connectors own side effects; FaSoLa-specific setup stays in examples/domain packs.

**Tech Stack:** Python dataclasses, FastAPI/Pydantic, unittest evals, existing `agent_os_core` runtime, `action_record` connector, `ContentCommerceRuntimeFactory`.

---

## Status and Gate

- ADR: `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.md`
- ADR status: Accepted; gate recorded 2026-06-22
- This SPEC status: Implemented on local feature branch `codex/adr-0002-upper-half`; pending review, merge, and release authorization
- Runtime implementation status: Complete for scoped v0 on the feature branch
- Required before merge/release: review + founder/CTO merge/release gate
- Red eval policy: The eval was written before runtime completion and now passes; future widening still requires fresh red-first tests.

## Freshness Corrections

The grounding sweep found two important facts that shape implementation:

- `POST /adoptions` already exists in `apps/api_server/src/agent_os_api/http_app.py` and calls `attest_adoption_service(...)`, which calls `AdoptionIngest.submit(...)` and `runtime.promote_from_adoption(...)`.
- `approval_required=True` currently stops inside `TrustedLoopRuntime._execute_loop(...)` at `AWAITING_APPROVAL`. `ApprovalLiteRuntime.approve(...)` exists, but there is no Trusted Loop entry point that resumes `approved -> dry_run -> snapshot -> execute`.

Therefore D4 is not "build HTTP /adoptions"; it is "add CLI `adopt` and typed causal attribution to both HTTP and CLI." D5 must include a real approval-resume execution entry point.

## File Structure

- Modify: `packages/contracts/src/agent_os_contracts/architecture.py`
  - Add causal attribution contract.
  - Add `idempotency_key` and dry-run result support to operation/action contracts.
  - Preserve backwards-compatible defaults for existing tests and callers.
- Modify: `packages/contracts/src/agent_os_contracts/trusted_loop.py`
  - Surface idempotency and action execution metadata on `ActionProposal` / `TrustedLoopResult` if contract ownership remains here.
- Modify: `packages/os_core/src/agent_os_core/action_connectors/base.py`
  - Add dry-run capability to the connector protocol.
- Modify: `action_connectors/manual_review/connector.py`
  - Implement a non-mutating dry-run response for the safe default connector.
- Modify: `action_connectors/action_record/connector.py`
  - Implement dry-run.
  - Enforce idempotency by key.
  - Preserve snapshot/rollback semantics.
- Modify: `packages/os_core/src/agent_os_core/action_governance/__init__.py`
  - Carry idempotency keys from proposals into `OperationContract`.
  - Enforce connector risk ceiling when building/executing contracts.
- Modify: `packages/os_core/src/agent_os_core/trusted_loop.py`
  - Factor current non-approval execution branch into a reusable governed executor.
  - Add an approval-resume entry point that verifies approved status before dry-run/snapshot/execute.
  - Trace dry-run, snapshot, connector execution, idempotent replay, and rollback-relevant IDs.
- Modify: `packages/os_core/src/agent_os_core/adoption/__init__.py`
  - Accept causal attribution only through operator-held `AdoptionIngest`.
- Modify: `packages/os_core/src/agent_os_core/knowledge_memory/__init__.py`
  - Promote adoption with causal attribution into a weighted knowledge revision.
- Modify: `apps/api_server/src/agent_os_api/outcome_service.py`
  - Extend `attest_adoption_service(...)` to pass causal attribution.
  - Keep `record_outcome_service(...)` as self-report only.
- Modify: `apps/api_server/src/agent_os_api/http_app.py`
  - Add causal attribution fields to `AdoptionRequest` and `AdoptionResponse`.
  - Do not change `/outcomes` promotion behavior.
- Modify: `apps/api_server/src/agent_os_api/cli.py`
  - Add `adopt` subcommand wired to `attest_adoption_service(...)`.
  - Keep `record-outcome` as self-report only.
- Test: `tests/eval/test_governed_action_outcome_loop_v0.py`
  - New red eval file for D6.
- Test: `tests/unit/test_action_record_connector.py`
  - Unit coverage for dry-run and idempotency.
- Test: `tests/unit/test_adoption_channel.py`
  - Causal attribution only through `AdoptionIngest`.
- Test: `tests/unit/test_http_app.py`
  - HTTP `/adoptions` causal attribution contract.
- Test: `tests/unit/test_cli_record_outcome.py`
  - CLI `adopt` operator channel and `record-outcome` separation.
- Docs: `docs/CURRENT_STATE.yaml`, root `../code_index.md`, ADR status after Gate/implementation.

## Contract Delta

### D1: Causal Outcome Attribution

Add a domain-independent typed contract in `architecture.py`:

```python
class CausalAttributionMethod(StrEnum):
    HOLDOUT = "holdout"
    COUNTERFACTUAL = "counterfactual"
    BEFORE_AFTER = "before_after"
    OPERATOR_ATTESTED = "operator_attested"


@dataclass(frozen=True)
class CausalOutcomeAttribution:
    metric_name: str
    observed_value: float
    counterfactual_value: float
    delta_absolute: float
    delta_percent: float | None
    method: CausalAttributionMethod
    comparison_ref: str
    window_start: str
    window_end: str
    confidence: float
    notes: str | None = None
```

Extend `FeedbackEvent` with:

```python
causal_attribution: CausalOutcomeAttribution | None = None
```

Rules:

- `AdoptionIngest.submit(...)` may accept `causal_attribution`.
- `TrustedLoopRuntime.record_outcome(...)` remains `RUNTIME_SELF_REPORT`; it may keep `metric_deltas`, but it must not produce knowledge promotion or realized-value attribution.
- `AdoptionLedger.record(...)` still rejects non-`EXTERNAL_ADOPTION` events.
- `KnowledgeAssetBuilder.with_feedback(...)` must convert external adoption attribution into a deterministic `result_weight` on the revised `KnowledgeAsset`.

Minimum v0 weighting:

```text
if no causal_attribution: result_weight = 1.0 for adopted/success, -1.0 for rejected/failure, 0.0 otherwise
if causal_attribution exists: result_weight = clamp(sign(delta_absolute) * confidence, -1.0, 1.0)
```

### D2: Dry Run

Add to `ActionConnector`:

```python
def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
    ...
```

Rules:

- If `operation.dry_run_required` is true, governed execution must call `dry_run(...)` before `execute(...)`.
- `ActionRecordConnector.dry_run(...)` must not mutate `ActionRecordStore`.
- The trace must record `connector_dry_run` with connector name, action type, status, and idempotency key.
- A failed dry-run must block execution and leave no connector mutation.

### D3: Idempotency Key

Extend `ActionProposal` and `OperationContract`:

```python
idempotency_key: str | None = None
```

Rules:

- The runtime derives a stable key if the proposal does not provide one:
  `trace_id:evidence_chain_id:proposal_id:connector_name:action_type`.
- `ActionRecordConnector.execute(...)` must persist a key-to-result record.
- Repeating the same idempotency key returns the first result with status `idempotent_replay` or equivalent, and does not append a second record.
- Reusing a key with different operation/action payload fails loudly.

### D4: Operator Adoption Interface

Keep current HTTP behavior:

- `POST /adoptions` remains the operator value channel.
- `POST /outcomes` remains runtime self-report and never promotes knowledge.

Add CLI:

```bash
python -m agent_os_api.cli adopt \
  --trace-id trace-abc \
  --outcome adopted \
  --reviewer ops@example.com \
  --metric gmv=1200 \
  --causal-metric gmv \
  --observed-value 11200 \
  --counterfactual-value 10000 \
  --method holdout \
  --comparison-ref holdout:campaign-42 \
  --window-start 2026-06-01 \
  --window-end 2026-06-07 \
  --confidence 0.8
```

Expected output:

```json
{
  "adoption_id": "feedback-...",
  "trace_id": "trace-abc",
  "outcome": "adopted",
  "reviewer": "ops@example.com",
  "knowledge_asset_id": "knowledge-...",
  "knowledge_version": 2,
  "result_weight": 0.8
}
```

### D5: Approval-Resume Governed Execution

Add a runtime entry point rather than bypassing the approval gate:

```python
def execute_approved_operation(
    self,
    *,
    approval_id: str,
    operation: OperationContract,
    action_parameters: dict[str, Any],
    evidence_chain: EvidenceChain,
    proposal_id: str,
) -> OperationTrace:
    ...
```

Rules:

- It must read `ApprovalLiteRuntime.get(approval_id)`.
- It must reject missing, pending, rejected, or mismatched approval records.
- It must reject an operation whose `operation_id` is not bound to `proposal_id`.
- For approvals created by the runtime, the pending approval record must freeze an operation/action payload fingerprint; `execute_approved_operation(...)` must recompute it and reject any changed operation contract or action parameters before connector execution.
- It must call `_assert_grounded(operation evidence)` before connector execution.
- It must execute the same governed branch as non-approval execution: dry-run, snapshot if required, connector execute, trace update.
- It must not create a path for R4/R5 auto-execution. Approval is required first.
- For v0, the end-to-end FaSoLa demo may pass the operation/action/evidence objects from the same process result; durable operation storage is a separate future ADR if product needs cross-process approval-resume.

### D6: Discriminating Eval

The eval must fail if any of these shortcuts are taken:

- Action executes when EvidenceChain is incomplete or SQL Safety did not pass.
- Runtime self-report promotes knowledge or writes external adoption.
- Rollback does not restore the action connector snapshot.
- Knowledge is promoted without an operator adoption event.
- Repeated idempotency key causes duplicate writes.
- Approval-required execution happens before `ApprovalLiteRuntime.approve(...)`.

## Red Eval Plan

Create `tests/eval/test_governed_action_outcome_loop_v0.py` first. Run it before implementation and confirm the expected RED failures below.

### Red Case 1: Dry Run Is Required and Non-Mutating

```python
def test_action_record_dry_run_previews_without_mutation():
    store = ActionRecordStore()
    connector = ActionRecordConnector(store=store)
    operation = OperationContract(
        operation_id="operation-1",
        name="op",
        target_connector="action_record",
        risk_level="R4",
        approval_required=True,
        dry_run_required=True,
        connector_name="action_record",
        action_type="execute",
        idempotency_key="key-1",
    )

    preview = connector.dry_run(operation, {"amount": 100})

    assert preview["status"] == "dry_run"
    assert store.records() == ()
```

Expected RED today: `TypeError` for `idempotency_key` or `AttributeError` for missing `dry_run`.

### Red Case 2: Idempotency Prevents Retry Double Write

```python
def test_action_record_idempotency_key_prevents_retry_double_write():
    store = ActionRecordStore()
    connector = ActionRecordConnector(store=store)
    operation = _operation(idempotency_key="trace-1:proposal-1")

    first = connector.execute(operation, {"amount": 100})
    second = connector.execute(operation, {"amount": 100})

    assert first["record_id"] == second["record_id"]
    assert second["status"] == "idempotent_replay"
    assert len(store.records()) == 1
```

Expected RED today: second `execute(...)` appends a second record.

### Red Case 3: CLI `adopt` Uses Operator Channel

```python
def test_cli_adopt_subcommand_calls_attest_adoption_service():
    out = io.StringIO()
    with patch(
        "agent_os_api.cli.attest_adoption_service",
        return_value={
            "adoption_id": "feedback-1",
            "trace_id": "trace-1",
            "outcome": "adopted",
            "reviewer": "ops@example.com",
            "knowledge_asset_id": "knowledge-1",
            "knowledge_version": 2,
            "result_weight": 0.8,
        },
    ) as service:
        rc = run_cli([
            "adopt",
            "--trace-id", "trace-1",
            "--outcome", "adopted",
            "--reviewer", "ops@example.com",
            "--causal-metric", "gmv",
            "--observed-value", "11200",
            "--counterfactual-value", "10000",
            "--method", "holdout",
            "--comparison-ref", "holdout:campaign-42",
            "--window-start", "2026-06-01",
            "--window-end", "2026-06-07",
            "--confidence", "0.8",
        ], stdout=out)

    assert rc == 0
    assert json.loads(out.getvalue())["result_weight"] == 0.8
    service.assert_called_once()
```

Expected RED today: parser rejects `adopt` because `SUBCOMMANDS` lacks it.

### Red Case 4: Self-Report Cannot Carry Realized Causal Attribution

```python
def test_record_outcome_does_not_promote_or_emit_external_attribution():
    ledger = AdoptionLedger()
    runtime = _build_runtime(adoption_ledger_view=ledger.view())
    trace_id = _run_to_candidate(runtime)

    feedback = runtime.record_outcome(
        trace_id=trace_id,
        outcome="adopted",
        metric_deltas={"gmv": 1200},
    )

    assert feedback.source == FeedbackSource.RUNTIME_SELF_REPORT
    assert runtime.knowledge_store.version_of(trace_id) == 1
    assert runtime.adoption_for_trace(trace_id) == ()
```

Expected RED today: this may already pass. Keep it as a guard so D1 does not reopen the wirehead path.

### Red Case 5: External Adoption Carries Causal Attribution Into Weighted Knowledge

```python
def test_external_adoption_promotes_weighted_knowledge_from_causal_delta():
    ledger = AdoptionLedger()
    runtime = _build_runtime(adoption_ledger_view=ledger.view())
    trace_id = _run_to_candidate(runtime)

    AdoptionIngest(ledger).submit(
        trace_id=trace_id,
        outcome="adopted",
        reviewer="ops",
        causal_attribution=CausalOutcomeAttribution(
            metric_name="gmv",
            observed_value=11200,
            counterfactual_value=10000,
            delta_absolute=1200,
            delta_percent=0.12,
            method=CausalAttributionMethod.HOLDOUT,
            comparison_ref="holdout:campaign-42",
            window_start="2026-06-01",
            window_end="2026-06-07",
            confidence=0.8,
        ),
    )
    revised = runtime.promote_from_adoption(trace_id)

    assert revised.result_weight == 0.8
```

Expected RED today: `CausalOutcomeAttribution` is missing, `AdoptionIngest.submit(...)` lacks `causal_attribution`, and `KnowledgeAsset` lacks `result_weight`.

### Red Case 6: Approved R4 Action Executes Only After Approval

```python
def test_approved_r4_action_resumes_into_dry_run_snapshot_execute():
    runtime, store = _build_runtime_with_action_record_r4()
    result = runtime.run("GMV action record test", RUN_PARAMS)

    assert result.approval_record.status == "pending"
    assert store.records() == ()

    runtime.approval_runtime.approve(result.approval_record.approval_id, reason="approved test")
    operation_trace = runtime.execute_approved_operation(
        approval_id=result.approval_record.approval_id,
        operation=result.operation_contract,
        action_parameters=result.action_proposal.action_parameters,
        evidence_chain=result.evidence_chain,
        proposal_id=result.action_proposal.proposal_id,
    )

    assert len(store.records()) == 1
    assert operation_trace.state == OperationState.EXECUTED
    assert [e["step"] for e in operation_trace.events] == [
        "proposed",
        "approved",
        "connector_dry_run",
        "state_snapshot",
        "connector_executed",
    ]
```

Expected RED today: no `execute_approved_operation(...)` entry point.

### Red Case 7: Ungrounded Approved Execution Is Refused

```python
def test_approved_execution_refuses_incomplete_evidence_chain():
    runtime, _store = _build_runtime_with_action_record_r4()
    runtime.approval_runtime.create_pending(
        approval_id="approval-1",
        proposal_id="proposal-1",
        approver_role="Business Owner",
    )
    runtime.approval_runtime.approve("approval-1")

    with pytest.raises(GroundingInvariantViolation):
        runtime.execute_approved_operation(
            approval_id="approval-1",
            operation=_operation(idempotency_key="key-ungrounded"),
            action_parameters={},
            evidence_chain=_incomplete_evidence_chain(),
            proposal_id="proposal-1",
        )
```

Expected RED today: no `execute_approved_operation(...)` entry point.

### Red Case 8: End-to-End Rollback Restores Connector State

```python
def test_governed_action_rollback_restores_action_record_store():
    runtime, store = _build_runtime_with_action_record_r4()
    result = _run_approved_action(runtime)

    assert len(store.records()) == 1
    rollback = runtime.rollback(result.state_snapshot.snapshot_id)

    assert rollback["status"] == "rolled_back"
    assert store.records() == ()
```

Expected RED today: approval-required path does not execute, so it does not produce an approved-action snapshot.

## Task Sequence

### Task 1: Write Red Eval

**Files:**
- Create: `tests/eval/test_governed_action_outcome_loop_v0.py`
- Modify only if import helpers are needed: `tests/eval/__init__.py`

- [x] Write the eight cases in the Red Eval Plan.
- [x] Run:

```bash
PYTHONPATH=packages/os_core/src:packages/contracts/src:packages/persistence/src:apps/api_server/src:action_connectors \
  python -m unittest tests.eval.test_governed_action_outcome_loop_v0 -v
```

- [x] Expected: failures match the listed RED reasons, not syntax/import mistakes.

### Task 2: Contract Delta

**Files:**
- Modify: `packages/contracts/src/agent_os_contracts/architecture.py`
- Modify: `packages/contracts/src/agent_os_contracts/trusted_loop.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Test: `tests/unit/test_contracts.py`

- [x] Add `CausalAttributionMethod`, `CausalOutcomeAttribution`, `idempotency_key`, and `result_weight`.
- [x] Run the red eval again.
- [x] Expected: RED failures move from missing types/fields to missing behavior.

### Task 3: Connector Dry-Run and Idempotency

**Files:**
- Modify: `packages/os_core/src/agent_os_core/action_connectors/base.py`
- Modify: `action_connectors/manual_review/connector.py`
- Modify: `action_connectors/action_record/connector.py`
- Test: `tests/unit/test_action_record_connector.py`

- [x] Add dry-run behavior.
- [x] Add idempotency state inside `ActionRecordStore`.
- [x] Run:

```bash
PYTHONPATH=packages/os_core/src:packages/contracts/src:action_connectors \
  python -m unittest tests.unit.test_action_record_connector -v
```

- [x] Expected: dry-run/idempotency unit tests pass; red eval still fails on runtime/API gaps.

### Task 4: Approval-Resume Governed Execution

**Files:**
- Modify: `packages/os_core/src/agent_os_core/trusted_loop.py`
- Modify: `packages/os_core/src/agent_os_core/action_governance/__init__.py`
- Test: `tests/unit/test_trusted_loop.py`
- Test: `tests/unit/test_trusted_loop_snapshot_rollback.py`

- [x] Extract current non-approval execution branch into a helper that both paths use.
- [x] Add `execute_approved_operation(...)`.
- [x] Enforce approved status, proposal match, operation/action payload match, grounding, dry-run, snapshot, execution, and trace updates.
- [x] Run:

```bash
PYTHONPATH=packages/os_core/src:packages/contracts/src:action_connectors \
  python -m unittest tests.unit.test_trusted_loop tests.unit.test_trusted_loop_snapshot_rollback -v
```

- [x] Expected: existing approval-halt tests still pass; new approved-resume tests pass.

### Task 5: Causal Adoption and Weighted Knowledge

**Files:**
- Modify: `packages/os_core/src/agent_os_core/adoption/__init__.py`
- Modify: `packages/os_core/src/agent_os_core/feedback/__init__.py`
- Modify: `packages/os_core/src/agent_os_core/knowledge_memory/__init__.py`
- Test: `tests/unit/test_adoption_channel.py`
- Test: `tests/unit/test_knowledge_memory.py`

- [x] Allow causal attribution only through operator adoption.
- [x] Keep self-report separate.
- [x] Register weighted knowledge revisions from external adoption.
- [x] Run:

```bash
PYTHONPATH=packages/os_core/src:packages/contracts/src:action_connectors \
  python -m unittest tests.unit.test_adoption_channel tests.unit.test_knowledge_memory -v
```

- [x] Expected: wirehead guard remains green; causal attribution promotion test passes.

### Task 6: API and CLI

**Files:**
- Modify: `apps/api_server/src/agent_os_api/outcome_service.py`
- Modify: `apps/api_server/src/agent_os_api/http_app.py`
- Modify: `apps/api_server/src/agent_os_api/cli.py`
- Modify: `apps/api_server/openapi.json`
- Test: `tests/unit/test_http_app.py`
- Test: `tests/unit/test_cli_record_outcome.py`
- Test: `tests/unit/test_openapi_contract.py`

- [x] Add causal attribution request/response fields to `/adoptions`.
- [x] Add CLI `adopt` and wire it to `attest_adoption_service(...)`.
- [x] Keep `record-outcome` wired to `record_outcome_service(...)`.
- [x] Regenerate OpenAPI snapshot.
- [x] Run:

```bash
PYTHONPATH=packages/os_core/src:packages/contracts/src:packages/persistence/src:apps/api_server/src:action_connectors \
  python -m unittest tests.unit.test_http_app tests.unit.test_cli_record_outcome tests.unit.test_openapi_contract -v
```

- [x] Expected: adoption API/CLI tests pass and OpenAPI drift gate is clean.

### Task 7: End-to-End Eval Green

**Files:**
- Test: `tests/eval/test_governed_action_outcome_loop_v0.py`
- Modify docs after implementation: `docs/CURRENT_STATE.yaml`, root `../code_index.md`

- [x] Run the red eval command again.
- [x] Expected: all D6 cases pass.
- [x] Run broader verification:

```bash
make ci
```

- [x] Expected: unit, eval, OpenAPI, ruff, and format checks pass.

## Completion Gate Answers

- Entry point: `TrustedLoopRuntime.run(...)`, new `TrustedLoopRuntime.execute_approved_operation(...)`, `POST /adoptions`, and CLI `adopt`.
- Contract: `OperationContract`, `ActionProposal`, `FeedbackEvent`, `CausalOutcomeAttribution`, `KnowledgeAsset`, `OperationTrace`.
- Failure mode: unsafe SQL/incomplete evidence, missing approval, rejected approval, mismatched approval/proposal/operation/action payload, failed dry-run, duplicate idempotency conflict, missing adoption, and rollback failure.
- Test validity: D6 red eval fails if grounding, adoption-only promotion, rollback, idempotency, or approval gates are bypassed.
- Integration: Trusted Loop, adoption ledger, action connector registry, action_record connector, knowledge store, HTTP, CLI, eval harness.
- Boundary: OS Core remains domain-independent; FaSoLa-specific fixtures stay outside OS Core.
- Observability: `OperationTrace`, `RunTrace`, connector dry-run/execute trace events, adoption ledger, and knowledge version/result weight are visible.

---

## Addendum A — readiness patches (2026-06-22, spec-claude)

> Source: Codex-handoff readiness review (workflow `wvc09br42`) — 4 verified blockers, all spec-level. These complete/supersede the cited sections so Codex implements without improvising un-co-signed design. Codex's RELAY STOP-LIST (what NOT to build in the first pass) ships with the relay packet.

### A-G1 — D2b Connector Risk Ceiling Enforcement (resolves File-Structure line "Enforce connector risk ceiling")
- New Contract Delta item **D2b**: deterministic RiskLevel ordering `R0<R1<R2<R3<R4<R5` via an `_RISK_ORDER` index map in `action_governance` (do NOT add comparison dunders to the contract enum).
- Semantics: `ActionGovernance.build_operation_contract(proposal)` compares `proposal.risk_level` vs the routed connector's `contract.risk_ceiling`. If `_order(proposal.risk_level) > _order(contract.risk_ceiling)` → raise a typed `RiskCeilingExceeded` (Codex may reuse an existing governance-violation error, recorded in impl) **BEFORE** building the OperationContract. Fires at **BUILD time only, once** — therefore enforced for both `run()` and `execute_approved_operation()` (both consume an already-built contract). Trace event `risk_ceiling_check{connector_name, risk_level, ceiling, allowed}`.
- The gate does **NOT** raise any production connector's ceiling. R4 demo authority comes from the Codex-authored test fixture (A-G2), not from changing `runtime_factory.py`.
- §D5 addendum: "`execute_approved_operation` consumes the already-ceiling-checked OperationContract; it does NOT re-run the ceiling gate."

### A-G2 — R4 shared fixture (resolves undefined `_build_runtime_with_action_record_r4`)
- Proposal builder fields: `risk_level=RiskLevel.R4, approval_required=True, approver_role='Business Owner', connector_name='action_record', action_type='execute', action_parameters={'amount':100}`.
- The `action_record` `ActionConnectorContract`: `risk_ceiling='R4'` (admits the R4 proposal → reaches AWAITING_APPROVAL, not refused), `supports_snapshot=True, supports_rollback=True`. Returns `(runtime, store)`.
- Other helpers (`_operation`, `RUN_PARAMS`, `_build_runtime`, `_run_to_candidate`, `_run_approved_action`, `_incomplete_evidence_chain`) follow `tests/unit/test_trusted_loop_snapshot_rollback.py:33-115` + Red Cases 1/6; `_incomplete_evidence_chain` must fail `EvidenceChain.is_complete()` (e.g. `sql_safety.allowed=False`).

### A-G3 — causal_attribution threading (resolves §D1 builder edit)
- `FeedbackEventBuilder.build(...)` gains `causal_attribution: CausalOutcomeAttribution | None = None`, stamps it on the returned FeedbackEvent (default None preserves all callers + the RUNTIME_SELF_REPORT path).
- `AdoptionIngest.submit(...)` accepts + passes through to `build(...)`; the runtime self-report builder never receives it.
- `causal_attribution` is **NOT** folded into `_derive_id`; `feedback_id` stays `{trace_id, outcome, reviewer, metrics, source}` only (keeps the determinism guard + source-based capability boundary).
- `with_feedback(...)` reads `result_weight` from `feedback.causal_attribution` via the v0 weighting formula; falls back to the outcome-sign rule when None.

### A-G4 — result_weight surfacing in service (resolves discarded promote return)
- `attest_adoption_service` captures `revised = runtime.promote_from_adoption(trace_id)` (currently discarded `outcome_service.py:192`) and adds `"result_weight"` to its response dict: `revised.result_weight` when revised is not None, else `None`.
- `AdoptionResponse` (`http_app.py:87-93`) gains `result_weight: float | None = None`; CLI `adopt` prints the service dict unchanged.
- `KnowledgeAsset` gains `result_weight: float = 0.0` dataclass default.
- Add ≥1 Red Case exercising the REAL `attest_adoption_service` end-to-end asserting `response["result_weight"] == 0.8` (no fixture echo, #17).
