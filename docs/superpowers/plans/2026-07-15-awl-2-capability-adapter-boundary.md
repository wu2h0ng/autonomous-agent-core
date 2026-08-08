# AWL-2 Capability Adapter Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make Agent Core own only generic capability authority/dispatch/receipt behavior while the Developer adapter owns repository effects, patch prompting and proposal normalization.

**Architecture:** Introduce CapabilityPort and ExecutionProfilePort as inward-facing Core protocols. CapabilityBroker validates the exact ActionPermit and C7 state, invokes a port once and creates the canonical ActionReceipt; DeveloperWorkspaceAdapter and DeveloperRepositoryPatchProfile implement the existing repository behavior outside Core. RunCoordinator keeps its public facade and current events, but receives the two ports instead of WorkspaceSandbox.

**Tech Stack:** Python 3.12, stdlib Protocol/dataclass/pathlib/subprocess, existing Pydantic contracts, pytest 9, Ruff, Pyright.

## Global Constraints

- Exact design base is e1343e3da66414c5bb944420432bf03f66ff4cfb.
- This docs branch does not authorize Runtime implementation.
- Implementation uses a new isolated worktree and one writer.
- NO_BIG_BANG_REWRITE: no SQL, browser, Data Agent, plugin registry, handler registry or AWL-3 decomposition.
- Preserve ActionContract, ActionPermit, ActionReceipt, events, digests, capability IDs/versions, grants, artifact layout and compensation semantics.
- CapabilityBroker remains the only production capability dispatch boundary.
- Developer adapters cannot create permits, policy decisions, correction epochs or ActionReceipts.
- L4 active-runtime self-modification and L5 authority-root mutation remain closed.
- No provider network call, result-bearing experiment, migration, push, merge or release.
- Known base result is 473 passed, 1 skipped, 2 failed; the two failures are fixed-NOW evaluation-grant expiry drift with HTTP 403 instead of 201.

---

## Implementation file map

Create:

- packages/os_core/src/agent_os_core/execution_profile.py — generic proposal/argument profile protocol.
- domain_packs/developer_agent/workspace_capability.py — repository capability implementation.
- domain_packs/developer_agent/repository_patch_profile.py — repository prompt and provider-proposal rules.
- tests/product/test_capability_adapter_boundary.py — authority, import and constructor boundary.
- tests/product/test_developer_repository_profile.py — prompt/proposal/argument equivalence.

Modify:

- packages/os_core/src/agent_os_core/capability.py — generic effect, port, broker and result only.
- packages/os_core/src/agent_os_core/execution.py — inject/delegate to generic ports.
- packages/os_core/src/agent_os_core/__init__.py — export generic ports; stop exporting WorkspaceSandbox.
- domain_packs/developer_agent/__init__.py — export Developer adapters and retain manifest.
- apps/api_server/app.py — compose Developer adapters and inject them.
- tests/product/test_spine0_security_and_persistence.py — import Developer adapter and route dispatch through Broker where authority is under test.
- tests/product/test_long_horizon_contracts.py — import Developer adapter.
- tests/product/test_long_horizon_compensation.py — import Developer adapter; keep compensation assertions unchanged.
- tests/product/test_long_horizon_execution.py — pass the explicit execution profile at all three direct coordinator constructors.
- tests/product/test_rebind_partial_evidence_regression.py — pass the explicit execution profile at its direct coordinator constructor.
- tests/product/test_spine0_golden_path.py — preserve provider request and patch binding behavior.
- directly affected constructor call sites found by the mandatory pre-edit search.

Separate prerequisite compatibility successor: accept its exact patch contract
before Runtime edits, then land its own independently reviewed commit before
the Core class/export is removed:

- Create: docs/research/LH-RECOVERY-1A-RUNTIME-SHAPE-SUCCESSOR-v2.yaml — maintenance-only live runtime-shape binding.
- Modify: tests/product_eval/test_lh1a_design.py — preserve frozen assertions and route only live import/instantiation/source-shape checks to the successor.

Do not modify:

- packages/contracts schemas;
- persistence schema;
- event types or event payload contracts;
- Product HTTP/CLI routes;
- ADM-P1/P2/P3/P4 services;
- Research mechanisms, environments, evaluators, preregistrations, baselines,
  assignments, results or verdicts. The only allowed Research-adjacent change is
  the separate maintenance successor above; the frozen
  docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml is byte-immutable;
- Product Blueprint, CURRENT_STATE or release records in this implementation packet.

### Task 0: Select and record the implementation base

**Files:**

- Inspect: docs/CURRENT_STATE.yaml
- Inspect: docs/AGENT-OS-PRODUCT-BLUEPRINT.md
- Inspect: docs/superpowers/specs/2026-07-15-awl-2-capability-adapter-boundary-design.md

- [ ] **Step 1: Create a fresh isolated implementation worktree**

Use superpowers:using-git-worktrees. Record the full base hash, branch, worktree path and git status.

- [ ] **Step 2: Inventory every affected reference**

Run:

~~~bash
rg -n "WorkspaceSandbox|CapabilityBroker|self\.sandbox|workspace\.apply_patch tool|_call_provider|_tool_arguments|RunCoordinator\(" \
  packages/os_core/src/agent_os_core apps domain_packs tests/product \
  tests/product_eval
~~~

Expected: every result is classified as generic dispatch, Developer behavior,
composition, direct authority test, direct constructor, historical compatibility
consumer or the explicitly deferred compensation path. The inventory must at
least name:

~~~text
tests/product/test_spine0_security_and_persistence.py:123
tests/product/test_long_horizon_compensation.py:142,160,279,316,319,328,425,439
tests/product/test_long_horizon_execution.py:535,591,647
tests/product/test_long_horizon_compensation.py:667,702,749,1004
tests/product/test_rebind_partial_evidence_regression.py:285
tests/product_eval/test_lh1a_design.py:41,7267,9381,9399
~~~

Line numbers are anchors for the exact design base; the implementation must
rerun the search and migrate every match even if later edits move the lines.

- [ ] **Step 3: Run and record the Product baseline**

Run:

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest tests/product -q
~~~

Expected on e1343e3: 473 passed, 1 skipped and only these two failures:

~~~text
tests/product/test_materialization_evaluation_api.py::test_http_records_lists_and_restarts_without_mutating_product_state
tests/product/test_materialization_evaluation_api.py::test_record_endpoint_bypasses_generic_http_idempotency_cache
~~~

Both must be HTTP 403 versus expected 201. Any other failure stops implementation.

### Task 0A: Accept the LH-RECOVERY-1A runtime-shape compatibility successor

This is a separate `TEST_MAINTENANCE_ONLY / NO_RESULT_CHANGE /
NO_CLAIM_UPGRADE` prerequisite packet. Freeze and independently accept its
exact patch contract before Runtime work. Materialize its live-test change only
after `DeveloperWorkspaceAdapter` exists, then review and integrate that
separate commit before deleting the Core class/export. It does not authorize a
result-bearing run or alter the historical verdict.

**Files:**

- Create: docs/research/LH-RECOVERY-1A-RUNTIME-SHAPE-SUCCESSOR-v2.yaml
- Modify: tests/product_eval/test_lh1a_design.py
- Verify byte-only: docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml

- [ ] **Step 1: Freeze the historical bytes and semantic ceiling**

Record and assert:

~~~bash
test "$(shasum -a 256 docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml | cut -d ' ' -f 1)" = \
  "21db5ab15ffa84a7db07ded2f4a9fee1b8683a8212084993b695101845acfa21"
~~~

The generator, regimes, templates, evaluator, statistics, preregistration,
baselines, assignments, result artifacts and verdict references are out of
scope and must remain byte-identical.

- [ ] **Step 2: Add a versioned maintenance-only successor**

The successor records:

~~~text
status: TEST_MAINTENANCE_ONLY
claim_effect: NO_RESULT_CHANGE / NO_CLAIM_UPGRADE
supersedes_runtime_shape_only: docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml
frozen_parent_sha256: 21db5ab15ffa84a7db07ded2f4a9fee1b8683a8212084993b695101845acfa21
tool_capability_registry: DeveloperWorkspaceAdapter.specs
capability_source: domain_packs/developer_agent/workspace_capability.py
~~~

It may describe only the live code-shape binding. It must not redefine seeds,
population, gates, statistics, baselines, result identity or verdict.

- [ ] **Step 3: Split historical and live-shape assertions**

In `tests/product_eval/test_lh1a_design.py`:

- replace the live Core import and instantiation with
  `DeveloperWorkspaceAdapter` from `domain_packs.developer_agent`;
- retain an assertion that the frozen parent still literally records
  `WorkspaceSandbox.specs` and its original source paths;
- move only the current-code registry/source assertions to the successor and
  require `DeveloperWorkspaceAdapter.specs` plus
  `domain_packs/developer_agent/workspace_capability.py`;
- replace source introspection for `class WorkspaceSandbox` in Core with
  introspection for `class DeveloperWorkspaceAdapter` in the Developer module;
- do not edit the frozen parent manifest in place.

- [ ] **Step 4: Verify and independently review the successor**

Run the exact affected tests plus the frozen-byte assertion. Require an
independent exact-head verdict that the change is test maintenance only and
does not alter any research input, result or claim. If it is not accepted,
stop: AWL-2 remains `DESIGN_ONLY`, and Core must not add a reverse import,
re-export or lazy alias to bypass this prerequisite.

### Task 1: Freeze the generic authority boundary in RED tests

**Files:**

- Create: tests/product/test_capability_adapter_boundary.py
- Inspect: packages/os_core/src/agent_os_core/capability.py
- Inspect: packages/os_core/src/agent_os_core/execution.py

**Interfaces:**

- Consumes: existing ActionContract, ActionPermit, CapabilitySpec and CorrectionAuthority.
- Produces: executable expectations for CapabilityEffect, CapabilityPort and the new RunCoordinator constructor.

- [ ] **Step 1: Add a spy port and action/permit factory**

Add concrete helpers equivalent to:

~~~python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilitySpec,
    ReceiptStatus,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    CorrectionAuthority,
)


class SpyCapabilityPort:
    def __init__(self) -> None:
        self.execute_count = 0

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> dict[str, CapabilitySpec]:
        return {}

    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={"artifact_ids": ("artifact:" + "a" * 64,)},
            error_code="error:none",
            detail_ref="detail:spy",
        )


def action_and_permit(
    correction: CorrectionAuthority,
) -> tuple[ActionContract, ActionPermit]:
    now = datetime.now(timezone.utc)
    epochs = correction.snapshot("task:boundary", "run:boundary", "capability:spy")
    action = ActionContract(
        action_id="action:boundary",
        task_id="task:boundary",
        run_id="run:boundary",
        node_id="node:boundary",
        principal_id="principal:boundary",
        tenant_id="tenant:boundary",
        workspace_id="workspace:boundary",
        capability_id="capability:spy",
        capability_version="1",
        arguments_json="{}",
        risk_tier=0,
        idempotency_key="idempotency:boundary",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected:boundary",
        candidate_envelope_id="envelope:boundary",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:boundary",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:boundary",
        grant_id="grant:boundary",
        correction_epochs=epochs,
        lease_fence=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return action, permit
~~~

- [ ] **Step 2: Add guard and receipt tests**

Add:

~~~python
def test_broker_creates_receipt_after_one_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)

    result = CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 1
    assert result.receipt.action_digest == action.action_digest()
    assert result.receipt.permit_id == permit.permit_id
    assert result.receipt.connector_id == action.capability_id
    assert result.receipt.idempotency_key == action.idempotency_key
    assert result.receipt.status is ReceiptStatus.SUCCEEDED
    assert result.receipt.output_artifact_ids == ("artifact:" + "a" * 64,)
    assert result.receipt.detail_ref == "detail:spy"


def test_broker_rejects_expired_permit_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    expired = permit.model_copy(
        update={
            "issued_at": permit.issued_at - timedelta(minutes=10),
            "expires_at": permit.issued_at - timedelta(minutes=5),
        }
    )

    with pytest.raises(CapabilityDenied, match="expired"):
        CapabilityBroker(port, correction).invoke(action, expired)

    assert port.execute_count == 0


def test_broker_rejects_c7_halt_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    correction.correct("task", action.task_id, "operator halt")

    with pytest.raises(CapabilityDenied, match="halted"):
        CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 0


def test_broker_rejects_stale_epoch_before_port_execution() -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort()
    action, permit = action_and_permit(correction)
    correction.correct("run", action.run_id, "epoch advance")
    correction.resume("run", action.run_id)

    with pytest.raises(CapabilityDenied, match="stale correction epoch"):
        CapabilityBroker(port, correction).invoke(action, permit)

    assert port.execute_count == 0
~~~

Also retain a mismatch test by copying the permit with action_digest set to 64 zeros and asserting execute_count remains zero.

Add a second spy that returns a `FAILED` `CapabilityEffect` and assert the
Broker creates exactly one `FAILED` receipt with the same `error_code` and
`detail_ref`. Adapter-phase tests in Task 3 separately prove that exceptions in
the existing dispatch/write capture block produce that effect, while cached
integrity failures before the block still raise without a receipt.

- [ ] **Step 3: Run RED**

Run:

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py -q
~~~

Expected: collection fails because CapabilityEffect is absent.

- [ ] **Step 4: Commit the RED test**

~~~bash
git add tests/product/test_capability_adapter_boundary.py
git commit -m "test(product): freeze capability adapter boundary"
~~~

### Task 2: Make CapabilityBroker own guard and receipt semantics

**Files:**

- Modify: packages/os_core/src/agent_os_core/capability.py
- Modify: packages/os_core/src/agent_os_core/__init__.py
- Test: tests/product/test_capability_adapter_boundary.py

**Interfaces:**

- Consumes: ActionContract, ActionPermit, ActionReceipt, CapabilitySpec, ReceiptStatus and CorrectionAuthority.
- Produces: CapabilityEffect, CapabilityPort, CapabilityResult and CapabilityBroker.invoke.

- [ ] **Step 1: Add the generic effect and port**

At the top of capability.py, use:

~~~python
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class CapabilityEffect:
    status: ReceiptStatus
    output: dict[str, object]
    error_code: str = "error:none"
    detail_ref: str = "detail:none"


class CapabilityPort(Protocol):
    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> Mapping[str, CapabilitySpec]:
        raise NotImplementedError

    def execute(self, action: ActionContract) -> CapabilityEffect:
        raise NotImplementedError
~~~

- [ ] **Step 2: Replace Broker invocation with the exact authority order**

Implement:

~~~python
class CapabilityBroker:
    """The only production execution boundary for typed capability actions."""

    def __init__(
        self,
        connector: CapabilityPort,
        correction: CorrectionAuthority,
    ) -> None:
        self.connector = connector
        self.correction = correction

    def invoke(
        self,
        action: ActionContract,
        permit: ActionPermit,
        attempt: int = 1,
    ) -> CapabilityResult:
        if not permit.matches(action):
            raise CapabilityDenied("broker rejected a permit/action digest mismatch")
        if permit.expires_at <= datetime.now(timezone.utc):
            raise CapabilityDenied("permit expired before capability dispatch")
        if self.correction.halted(
            action.task_id,
            action.run_id,
            action.capability_id,
        ):
            raise CapabilityDenied("correction authority is halted")
        current_epochs = self.correction.snapshot(
            action.task_id,
            action.run_id,
            action.capability_id,
        )
        if (
            current_epochs != permit.correction_epochs
            or current_epochs != action.observed_correction_epochs
        ):
            raise CapabilityDenied("stale correction epoch")

        effect = self.connector.execute(action)
        receipt = ActionReceipt(
            receipt_id=f"receipt-{uuid4()}",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            permit_id=permit.permit_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            connector_id=action.capability_id,
            status=effect.status,
            idempotency_key=action.idempotency_key,
            attempt=attempt,
            output_artifact_ids=tuple(
                str(value)
                for value in _as_sequence(effect.output.get("artifact_ids", ()))
            ),
            error_code=effect.error_code,
            detail_ref=effect.detail_ref,
            occurred_at=datetime.now(timezone.utc),
        )
        return CapabilityResult(receipt=receipt, output=effect.output)
~~~

Keep `_as_sequence` in `agent_os_core.capability`: Broker receipt construction
uses it, so it is generic Core behavior and is not in the repository-helper move
list.

Freeze the exact failure/receipt equivalence in tests:

- permit mismatch, expiry, C7 halt and stale epochs raise before execute and
  create no receipt;
- argument decoding/type, idempotency lookup and cached-effect validation keep
  their current pre-effect fail-closed exception/no-receipt behavior;
- exceptions inside the current `_dispatch` plus `_put_idempotency` `try` block,
  including `CapabilityDenied`, become `FAILED` `CapabilityEffect` and therefore
  one `FAILED` `ActionReceipt`;
- success and compensation create one effect and one receipt.

Do not replace this phase-specific contract with a broad "catch" or "do not
catch CapabilityDenied" rule.

- [ ] **Step 3: Refactor the existing WorkspaceSandbox through the new Broker without changing behavior**

Before moving the class, split its current invoke body:

- execute contains argument parsing, idempotency, dispatch and CapabilityEffect construction;
- invoke remains a temporary compatibility wrapper that calls CapabilityBroker.

Use:

~~~python
def execute(self, action: ActionContract) -> CapabilityEffect:
    args = json.loads(action.arguments_json)
    if not isinstance(args, dict):
        raise CapabilityDenied("capability arguments must be an object")
    intent_fingerprint = _intent_fingerprint(action)
    stored = self._get_idempotency(
        action.idempotency_key,
        intent_fingerprint,
    )
    if stored is not None:
        if action.capability_id == "workspace.apply_patch":
            self._validate_cached_patch_effect(args, stored)
        elif action.capability_id == "workspace.compensate_patch":
            self._validate_cached_compensation_effect(args, stored)
        output = stored
        status = (
            ReceiptStatus.COMPENSATED
            if action.capability_id == "workspace.compensate_patch"
            else ReceiptStatus.SUCCEEDED
        )
        error_code = "error:none"
    else:
        try:
            output = self._dispatch(
                action.capability_id,
                args,
                action.idempotency_key,
            )
            self._put_idempotency(
                action.idempotency_key,
                intent_fingerprint,
                output,
            )
            status = (
                ReceiptStatus.COMPENSATED
                if action.capability_id == "workspace.compensate_patch"
                else ReceiptStatus.SUCCEEDED
            )
            error_code = "error:none"
        except Exception as exc:
            output = {"error": type(exc).__name__}
            status = ReceiptStatus.FAILED
            error_code = type(exc).__name__
    return CapabilityEffect(
        status=status,
        output=output,
        error_code=error_code,
        detail_ref=str(output.get("compensation_ref", "detail:none")),
    )


def invoke(
    self,
    action: ActionContract,
    permit: ActionPermit,
    correction: CorrectionAuthority,
    attempt: int = 1,
) -> CapabilityResult:
    return CapabilityBroker(self, correction).invoke(
        action,
        permit,
        attempt=attempt,
    )
~~~

This wrapper exists only between Task 2 and Task 3 to keep the intermediate
commit executable. Every direct caller is migrated to `CapabilityBroker` in
Task 3, and neither `DeveloperWorkspaceAdapter.invoke` nor any Core compatibility
wrapper may exist at final AWL-2 HEAD.

- [ ] **Step 4: Export the generic types**

Update agent_os_core/__init__.py to export:

~~~python
from .capability import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    CapabilityPort,
    CapabilityResult,
)
~~~

Keep WorkspaceSandbox temporarily until Task 3 moves all repository imports.

- [ ] **Step 5: Run broker and existing dispatch tests**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py \
  tests/product/test_authority_contracts.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_long_horizon_contracts.py -q
~~~

Expected: all targeted tests pass.

- [ ] **Step 6: Commit**

~~~bash
git add packages/os_core/src/agent_os_core/capability.py \
  packages/os_core/src/agent_os_core/__init__.py \
  tests/product/test_capability_adapter_boundary.py
git commit -m "refactor(product): centralize capability guard and receipt"
~~~

### Task 3: Move repository effects into DeveloperWorkspaceAdapter

**Files:**

- Create: domain_packs/developer_agent/workspace_capability.py
- Modify: domain_packs/developer_agent/__init__.py
- Modify: packages/os_core/src/agent_os_core/capability.py
- Modify: packages/os_core/src/agent_os_core/__init__.py
- Modify: tests/product/test_spine0_security_and_persistence.py
- Modify: tests/product/test_long_horizon_contracts.py
- Modify: tests/product/test_long_horizon_compensation.py
- Test: tests/product/test_capability_adapter_boundary.py

**Interfaces:**

- Consumes: CapabilityEffect, CapabilityPort protocol and existing contracts.
- Produces: DeveloperWorkspaceAdapter.specs and DeveloperWorkspaceAdapter.execute.

- [ ] **Step 1: Add the concrete-type and dependency assertions, then run RED**

Add:

~~~python
from pathlib import Path


def test_agent_core_does_not_import_developer_adapter() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    offenders = [
        path
        for path in root.glob("*.py")
        if "domain_packs.developer_agent" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_capability_core_has_no_workspace_concrete_type() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    capability_source = (root / "capability.py").read_text(encoding="utf-8")
    exports_source = (root / "__init__.py").read_text(encoding="utf-8")

    assert "class WorkspaceSandbox" not in capability_source
    assert '"WorkspaceSandbox"' not in exports_source


def test_only_broker_dispatches_the_capability_port() -> None:
    repo = Path(__file__).parents[2]
    capability_source = (
        repo / "packages/os_core/src/agent_os_core/capability.py"
    ).read_text(encoding="utf-8")
    execution_source = (
        repo / "packages/os_core/src/agent_os_core/execution.py"
    ).read_text(encoding="utf-8")
    app_source = (repo / "apps/api_server/app.py").read_text(encoding="utf-8")

    assert capability_source.count("self.connector.execute(action)") == 1
    assert "self.sandbox.execute" not in execution_source
    assert "self.capabilities.execute" not in execution_source
    assert "self.sandbox.execute" not in app_source
    assert "self.capabilities.execute" not in app_source
~~~

Place the Path import with the file's top-level imports before running Ruff.

Run:

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py -q
~~~

Expected: the WorkspaceSandbox assertion fails.

- [ ] **Step 2: Create the Developer module with exact moved behavior**

Use apply_patch to move these existing members from capability.py without changing their algorithms:

~~~text
WorkspaceSandbox.__init__
WorkspaceSandbox.specs
WorkspaceSandbox._get_idempotency
WorkspaceSandbox._put_idempotency
WorkspaceSandbox._dispatch
WorkspaceSandbox._safe_path
WorkspaceSandbox._apply_patch
WorkspaceSandbox._validate_cached_patch_effect
WorkspaceSandbox._validate_cached_compensation_effect
WorkspaceSandbox.compensate
WorkspaceSandbox._compensate_patch
WorkspaceSandbox._persist_snapshot
WorkspaceSandbox._load_snapshot
WorkspaceSandbox._write_snapshot_state
WorkspaceSandbox._write_new_file
WorkspaceSandbox._atomic_write
WorkspaceSandbox._run_tests
_sha256
_canonical_json_bytes
_intent_fingerprint
_fsync_directory
~~~

Do not move `_as_sequence`; it remains in Core because
`CapabilityBroker.invoke` uses it to create the canonical receipt.

Rename the class to DeveloperWorkspaceAdapter. Move the execute method introduced in Task 2 with the following exact body:

~~~python
def execute(self, action: ActionContract) -> CapabilityEffect:
    args = json.loads(action.arguments_json)
    if not isinstance(args, dict):
        raise CapabilityDenied("capability arguments must be an object")
    intent_fingerprint = _intent_fingerprint(action)
    stored = self._get_idempotency(
        action.idempotency_key,
        intent_fingerprint,
    )
    if stored is not None:
        if action.capability_id == "workspace.apply_patch":
            self._validate_cached_patch_effect(args, stored)
        elif action.capability_id == "workspace.compensate_patch":
            self._validate_cached_compensation_effect(args, stored)
        output = stored
        status = (
            ReceiptStatus.COMPENSATED
            if action.capability_id == "workspace.compensate_patch"
            else ReceiptStatus.SUCCEEDED
        )
        error_code = "error:none"
    else:
        try:
            output = self._dispatch(
                action.capability_id,
                args,
                action.idempotency_key,
            )
            self._put_idempotency(
                action.idempotency_key,
                intent_fingerprint,
                output,
            )
            status = (
                ReceiptStatus.COMPENSATED
                if action.capability_id == "workspace.compensate_patch"
                else ReceiptStatus.SUCCEEDED
            )
            error_code = "error:none"
        except Exception as exc:
            output = {"error": type(exc).__name__}
            status = ReceiptStatus.FAILED
            error_code = type(exc).__name__
    return CapabilityEffect(
        status=status,
        output=output,
        error_code=error_code,
        detail_ref=str(output.get("compensation_ref", "detail:none")),
    )
~~~

The adapter must not import CorrectionAuthority, ActionPermit or ActionReceipt.

It must not define `invoke`. `execute` is the port implementation, and the
Broker is the only authority-bearing public dispatch path.

- [ ] **Step 3: Export and commit the adapter precursor while Core compatibility still exists**

Export `DeveloperWorkspaceAdapter` and the package-local temporary alias without
any Core back-import:

~~~python
from .workspace_capability import DeveloperWorkspaceAdapter

WorkspaceSandbox = DeveloperWorkspaceAdapter
~~~

Add direct adapter tests, run them through a real `CapabilityBroker`, and commit
the new Developer implementation before deleting the old Core class. This
transient commit may contain both concrete implementations, but production
composition still uses the Core class and there is no new dispatch path.

~~~bash
git add domain_packs/developer_agent tests/product/test_capability_adapter_boundary.py
git commit -m "refactor(product): stage developer workspace adapter"
~~~

- [ ] **Step 4: Materialize and independently accept the compatibility successor**

Execute Task 0A now that `DeveloperWorkspaceAdapter` exists:

- create the maintenance-only successor manifest;
- migrate the live import, instantiation, registry and source-shape checks in
  `tests/product_eval/test_lh1a_design.py`;
- keep the frozen parent at SHA-256
  `21db5ab15ffa84a7db07ded2f4a9fee1b8683a8212084993b695101845acfa21`;
- run the affected Product-eval tests;
- commit only the successor and live test change;
- obtain an independent exact-head review with literal status
  `TEST_MAINTENANCE_ONLY / NO_RESULT_CHANGE / NO_CLAIM_UPGRADE`.

Do not proceed to Core removal unless this separate commit is accepted. The
alias is Developer-package-local compatibility only; never export it from
`agent_os_core`.

- [ ] **Step 5: Remove repository implementation from Core**

Delete WorkspaceSandbox and all filesystem/subprocess/patch helpers from capability.py. Remove its os, shutil, subprocess, tempfile, Path and repository-only imports.

Remove WorkspaceSandbox from agent_os_core/__init__.py. Retain `_as_sequence`
and its imports in Core.

- [ ] **Step 6: Update every Developer behavior and authority test**

Change direct imports to:

~~~python
from domain_packs.developer_agent import DeveloperWorkspaceAdapter
~~~

Replace WorkspaceSandbox(root) with DeveloperWorkspaceAdapter(root), using each test's existing root expression.

For permit/C7 tests, call:

~~~python
broker = CapabilityBroker(adapter, correction)
result = broker.invoke(action, permit)
~~~

Apply this migration to every direct authority/idempotency dispatch, including:

~~~text
tests/product/test_spine0_security_and_persistence.py:123
tests/product/test_long_horizon_compensation.py:142,160,279,316,319,328,425,439
~~~

At lines 319 and 328, construct a new adapter with the existing idempotency
store and then construct a new Broker around that adapter; do not retain a
class-level or adapter-level `invoke` shortcut. Tests at 316, 319 and 328 must
continue to prove compensation replay and cached-effect integrity with the same
exception/no-receipt behavior.

For pure filesystem snapshot tests, retain direct calls to private _dispatch exactly as today; those tests validate the adapter implementation rather than authority.

- [ ] **Step 7: Run adapter, compatibility and security tests**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_long_horizon_contracts.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product_eval/test_lh1a_design.py -q
~~~

Expected: all targeted tests pass.

- [ ] **Step 8: Run dependency and broker-only dispatch checks**

~~~bash
rg -n "WorkspaceSandbox|import os|import shutil|import subprocess|import tempfile|from pathlib import Path" \
  packages/os_core/src/agent_os_core/capability.py \
  packages/os_core/src/agent_os_core/__init__.py
~~~

Expected: no match.

Run:

~~~bash
test "$(rg -o 'self\.connector\.execute\(action\)' \
  packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "1"
test "$(rg -l 'self\.(sandbox|capabilities)\.execute' \
  apps/api_server/app.py packages/os_core/src/agent_os_core/execution.py \
  | wc -l | tr -d ' ')" = "0"
test "$(rg -l 'def invoke\(' domain_packs/developer_agent/workspace_capability.py \
  | wc -l | tr -d ' ')" = "0"
~~~

Expected: all three commands exit 0.

- [ ] **Step 9: Commit the remaining move atomically**

~~~bash
git add domain_packs/developer_agent \
  packages/os_core/src/agent_os_core/capability.py \
  packages/os_core/src/agent_os_core/__init__.py \
  tests/product/test_capability_adapter_boundary.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_long_horizon_contracts.py \
  tests/product/test_long_horizon_compensation.py
git commit -m "refactor(product): move workspace effects to developer adapter"
~~~

### Task 4: Move repository prompting behind ExecutionProfilePort

**Files:**

- Create: packages/os_core/src/agent_os_core/execution_profile.py
- Create: domain_packs/developer_agent/repository_patch_profile.py
- Create: tests/product/test_developer_repository_profile.py
- Modify: packages/os_core/src/agent_os_core/__init__.py
- Modify: domain_packs/developer_agent/__init__.py

**Interfaces:**

- Consumes: ProviderProfile, ProviderRequest, ProviderResponse, ProviderToolProposal and immutable execution context.
- Produces: ExecutionProfilePort and DeveloperRepositoryPatchProfile.

- [ ] **Step 1: Freeze Developer profile behavior in RED tests**

Add tests that construct the profile directly. The core positive case is:

~~~python
def provider_profile(now: datetime) -> ProviderProfile:
    return ProviderProfile(
        profile_id="provider-profile:test",
        provider_id="deterministic",
        model_id="deterministic-v1",
        endpoint_class="test",
        credential_ref_id="credential:test",
        capabilities=("chat",),
        max_context_tokens=16000,
        request_timeout_seconds=60,
        created_at=now,
    )


def test_profile_binds_reviewed_path_sha_and_only_patch_capability() -> None:
    now = datetime.now(timezone.utc)
    profile = DeveloperRepositoryPatchProfile()
    request = profile.build_provider_request(
        task_id="task:profile",
        run_id="run:profile",
        provider_profile=provider_profile(now),
        provider_capability="provider.chat",
        context={
            "goal": "replace the fixture",
            "target_path": "fixture.txt",
            "workspace.read": {
                "content": "before\n",
                "sha256": "b" * 64,
            },
        },
        now=now,
    )

    assert request.allowed_capability_ids == ("workspace.apply_patch",)
    assert "Target path: fixture.txt" in request.messages[0].content
    assert "Current SHA-256: " + "b" * 64 in request.messages[0].content
~~~

Add fail-closed cases for:

- missing target path or read output;
- two tool proposals;
- a capability other than workspace.apply_patch;
- argument keys other than path and content;
- proposal path mismatch;
- non-string content;
- malformed text fallback;
- no proposal after fallback.

Each fail-closed profile case must assert `ExecutionProfileError` and the exact
message currently surfaced as `RunExecutionError`; the Developer profile must
not import `RunExecutionError`.

Add tool argument cases for workspace.read and workspace.run_tests, and assert requires_provider_bound_action returns true only for workspace.apply_patch.

- [ ] **Step 2: Run RED**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_developer_repository_profile.py -q
~~~

Expected: import failure because both profile types are absent.

- [ ] **Step 3: Define ExecutionProfilePort**

Create execution_profile.py with:

~~~python
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from agent_os_contracts import (
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
)


class ExecutionProfileError(ValueError):
    """Fail-closed profile validation without execution authority."""


class ExecutionProfilePort(Protocol):
    @property
    def generator_id(self) -> str:
        raise NotImplementedError

    @property
    def generator_version(self) -> str:
        raise NotImplementedError

    def build_provider_request(
        self,
        *,
        task_id: str,
        run_id: str,
        provider_profile: ProviderProfile,
        provider_capability: str,
        context: Mapping[str, Any],
        now: datetime,
    ) -> ProviderRequest:
        raise NotImplementedError

    def bind_provider_response(
        self,
        response: ProviderResponse,
        *,
        context: Mapping[str, Any],
    ) -> tuple[ProviderToolProposal, ...]:
        raise NotImplementedError

    def tool_arguments(
        self,
        capability_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        raise NotImplementedError

    def verification_exit_code(
        self,
        context: Mapping[str, Any],
    ) -> int | None:
        raise NotImplementedError
~~~

- [ ] **Step 4: Implement DeveloperRepositoryPatchProfile**

Move the exact current prompt, _parse_patch_json logic, proposal cardinality/capability checks, argument shape checks, target-path binding and expected_sha256 injection from RunCoordinator.

Raise `ExecutionProfileError` with the exact existing failure text for every
missing, ambiguous, malformed or mismatched profile input. Do not import or
raise `RunExecutionError` from the domain module.

Set:

~~~python
class DeveloperRepositoryPatchProfile:
    generator_id = "developer-golden-path"
    generator_version = "1"

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        return capability_id == "workspace.apply_patch"

    def verification_exit_code(
        self,
        context: Mapping[str, Any],
    ) -> int | None:
        output = context.get("workspace.run_tests")
        if not isinstance(output, dict):
            return None
        try:
            return int(str(output.get("exit_code", 1)))
        except (TypeError, ValueError) as exc:
            raise ExecutionProfileError(str(exc)) from exc
~~~

The prompt content and 20,000-character truncation must be byte-equivalent to the current implementation. ProviderFailure handling remains in RunCoordinator and is not duplicated here.

- [ ] **Step 5: Export the generic seam and Developer profile**

Update `agent_os_core/__init__.py` to export
`ExecutionProfileError` and `ExecutionProfilePort` without importing any domain
module.

Update domain_packs/developer_agent/__init__.py:

~~~python
from .repository_patch_profile import DeveloperRepositoryPatchProfile
from .workspace_capability import DeveloperWorkspaceAdapter
~~~

- [ ] **Step 6: Run profile tests**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_developer_repository_profile.py -q
~~~

Expected: all tests pass without a provider network call.

- [ ] **Step 7: Commit**

~~~bash
git add packages/os_core/src/agent_os_core/execution_profile.py \
  packages/os_core/src/agent_os_core/__init__.py \
  domain_packs/developer_agent/repository_patch_profile.py \
  domain_packs/developer_agent/__init__.py \
  tests/product/test_developer_repository_profile.py
git commit -m "feat(product): add developer execution profile seam"
~~~

### Task 5: Inject the two ports into RunCoordinator

**Files:**

- Modify: packages/os_core/src/agent_os_core/execution.py
- Modify: packages/os_core/src/agent_os_core/__init__.py
- Modify: apps/api_server/app.py
- Modify: tests/product/test_capability_adapter_boundary.py
- Modify: tests/product/test_long_horizon_execution.py
- Modify: tests/product/test_long_horizon_compensation.py
- Modify: tests/product/test_rebind_partial_evidence_regression.py

**Interfaces:**

- Consumes: CapabilityPort, CapabilityBroker and ExecutionProfilePort.
- Produces: RunCoordinator with no WorkspaceSandbox or repository-prompt dependency.

- [ ] **Step 1: Freeze removal of the concrete type and patch prompt, then run RED**

Add:

~~~python
def test_execution_core_has_no_workspace_concrete_type_or_patch_prompt() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    execution_source = (root / "execution.py").read_text(encoding="utf-8")

    assert "WorkspaceSandbox" not in execution_source
    assert "Repository task:" not in execution_source
    assert "workspace.apply_patch tool" not in execution_source
    assert "def _parse_patch_json" not in execution_source
    assert "def _tool_arguments" not in execution_source
~~~

Run:

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py -q
~~~

Expected: the execution boundary assertion fails on the exact current constructor and prompt.

- [ ] **Step 2: Narrow the constructor**

Replace the concrete parameter with:

~~~python
def __init__(
    self,
    task_service: TaskService,
    capabilities: CapabilityPort,
    execution_profile: ExecutionProfilePort,
    provider: ProviderPort,
    provider_profile: ProviderProfile,
    policy: PolicyKernel,
    correction: CorrectionAuthority,
    grant: CapabilityGrant | dict[str, CapabilityGrant],
    *,
    evaluator: DeterministicOutcomeEvaluator | None = None,
    compensation_grant: CapabilityGrant | None = None,
) -> None:
    self.tasks = task_service
    self.capabilities = capabilities
    self.execution_profile = execution_profile
    self.broker = CapabilityBroker(capabilities, correction)
    self.provider = provider
    self.provider_profile = provider_profile
    self.policy = policy
    self.correction = correction
    self.grant = grant
    self.compensation_grant = compensation_grant
    self.evaluator = evaluator or DeterministicOutcomeEvaluator()
~~~

Update self.sandbox.specs calls to self.capabilities.specs. Do not change compensation capability IDs, event order or policy calls.

- [ ] **Step 3: Delegate candidate envelope metadata**

Use:

~~~python
envelope = CandidateGenerationEnvelope(
    envelope_id=f"envelope-{uuid4()}",
    task_id=task_id,
    run_id=run.run_id,
    tenant_id=run.tenant_id,
    workspace_id=run.workspace_id,
    generator_id=self.execution_profile.generator_id,
    generator_version=self.execution_profile.generator_version,
    allowed_capability_ids=tuple(sorted(self.capabilities.specs())),
    resource_budget=aggregate.commitment.budget,
    candidate_ids=tuple(node.node_id for node in aggregate.workflow.nodes),
    has_abstain=True,
    has_ask=True,
    has_no_action=True,
    created_at=datetime.now(timezone.utc),
)
~~~

- [ ] **Step 4: Delegate provider request and response binding**

Replace the repository-specific _call_provider body with:

~~~python
try:
    request = self.execution_profile.build_provider_request(
        task_id=task_id,
        run_id=run_id,
        provider_profile=self.provider_profile,
        provider_capability=capability,
        context=context,
        now=datetime.now(timezone.utc),
    )
except ExecutionProfileError as exc:
    raise RunExecutionError(str(exc)) from exc
response = self.provider.complete(request)
if isinstance(response, ProviderFailure):
    raise RunExecutionError(
        f"provider {response.code.value}: {response.safe_message}"
    )
try:
    proposals = self.execution_profile.bind_provider_response(
        response,
        context=context,
    )
except ExecutionProfileError as exc:
    raise RunExecutionError(str(exc)) from exc
return {
    "text": response.text,
    "tool_proposals": [
        proposal.model_dump(mode="json") for proposal in proposals
    ],
    "usage": response.usage.model_dump(mode="json"),
    "finish_reason": response.finish_reason,
}
~~~

Delete _parse_patch_json from execution.py.

- [ ] **Step 5: Delegate tool arguments and provider binding**

Replace _tool_arguments calls with:

~~~python
try:
    arguments = self.execution_profile.tool_arguments(
        node.capability or "",
        context,
    )
except ExecutionProfileError as exc:
    raise RunExecutionError(str(exc)) from exc
~~~

Replace the workspace.apply_patch check in _call_tool with:

~~~python
if (
    self.execution_profile.requires_provider_bound_action(capability_id)
    and not isinstance(proposed_action, ActionContract)
):
    raise RunExecutionError(
        f"{capability_id} requires a provider-bound ActionContract"
    )
~~~

Delete _tool_arguments from execution.py.

- [ ] **Step 6: Delegate verification extraction**

After context restoration and after each tool result, set:

~~~python
try:
    test_exit_code = self.execution_profile.verification_exit_code(context)
except ExecutionProfileError as exc:
    raise RunExecutionError(str(exc)) from exc
~~~

Specifically replace the initial direct `context.get("workspace.run_tests")`
calculation at the exact base's `execution.py:232-237`; do not leave it beside
the profile call. Then replace every post-tool recalculation. Wrap only
`ExecutionProfileError` as `RunExecutionError(str(exc)) from exc`. Do not change
DeterministicOutcomeEvaluator or outcome event semantics.

- [ ] **Step 7: Update composition and every direct constructor explicitly**

Create `self.execution_profile = DeveloperRepositoryPatchProfile()` in
`AgentOSApplication`, pass it at all three exact-base constructors in
`apps/api_server/app.py:715,731,871`, and preserve snapshot-bound provider
profiles and grants.

Pass the corresponding application profile at every direct test constructor:

~~~text
tests/product/test_long_horizon_execution.py:535,591,647
tests/product/test_long_horizon_compensation.py:667,702,749,1004
tests/product/test_rebind_partial_evidence_regression.py:285
~~~

For `app` use `app.execution_profile`; for `restarted` use
`restarted.execution_profile`. Line numbers are exact-base anchors and do not
replace a final `rg -n "RunCoordinator\(" apps tests/product` inventory.

Add a boundary test with a minimal fake profile and SpyCapabilityPort proving RunCoordinator construction needs no root Path or Developer class.

- [ ] **Step 8: Run coordinator and golden-path tests**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py \
  tests/product/test_developer_repository_profile.py \
  tests/product/test_spine0_golden_path.py \
  tests/product/test_long_horizon_execution.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_rebind_partial_evidence_regression.py -q
~~~

Expected: all targeted tests pass.

- [ ] **Step 9: Run static prompt/type checks**

~~~bash
rg -n "WorkspaceSandbox|Repository task:|workspace\.apply_patch tool|def _parse_patch_json|def _tool_arguments" \
  packages/os_core/src/agent_os_core
~~~

Expected: no match.

Also run the broker-only gate:

~~~bash
test "$(rg -o 'self\.connector\.execute\(action\)' \
  packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "1"
test "$(rg -l 'self\.(sandbox|capabilities)\.execute' \
  apps/api_server/app.py packages/os_core/src/agent_os_core/execution.py \
  | wc -l | tr -d ' ')" = "0"
~~~

The following deferred compensation identifiers may still appear in execution.py and must be listed in the review receipt:

~~~text
workspace.apply_patch
workspace.compensate_patch
PatchCompensationRecord
~~~

- [ ] **Step 10: Commit**

~~~bash
git add packages/os_core/src/agent_os_core/execution.py \
  packages/os_core/src/agent_os_core/execution_profile.py \
  packages/os_core/src/agent_os_core/__init__.py \
  apps/api_server/app.py \
  tests/product
git commit -m "refactor(product): inject capability and execution profile ports"
~~~

### Task 6: Rewire the Developer composition root

**Files:**

- Modify: apps/api_server/app.py
- Modify: tests/product/test_api_surface.py
- Modify: tests/product/test_task_configuration_application.py
- Modify: directly affected application tests.

**Interfaces:**

- Consumes: DeveloperWorkspaceAdapter, DeveloperRepositoryPatchProfile and the narrowed RunCoordinator constructor.
- Produces: unchanged HTTP/UI/CLI behavior and immutable configuration capability bindings.

- [ ] **Step 1: Construct both Developer adapters**

Replace the Core WorkspaceSandbox import with:

~~~python
from domain_packs.developer_agent import (
    DeveloperRepositoryPatchProfile,
    DeveloperWorkspaceAdapter,
    manifest as developer_agent_manifest,
)
~~~

In AgentOSApplication.__init__, use:

~~~python
self.sandbox = DeveloperWorkspaceAdapter(
    workspace,
    idempotency_store=self.store,
)
self.execution_profile = DeveloperRepositoryPatchProfile()
~~~

The self.sandbox name may remain temporarily because application tests and workspace-status methods use it. Its concrete type is now outside Core.

- [ ] **Step 2: Preserve attach_workspace atomicity**

Inside the existing configuration lock, replace only the constructor:

~~~python
self.sandbox = DeveloperWorkspaceAdapter(
    root,
    idempotency_store=self.store,
)
rebuilt_grants = self._build_grants()
self.grants.clear()
self.grants.update(rebuilt_grants)
~~~

Do not alter path validation, allowlisted roots, lock scope or snapshot semantics.

- [ ] **Step 3: Pass the execution profile to every coordinator**

Each constructor becomes:

~~~python
runner = RunCoordinator(
    self.tasks,
    self.sandbox,
    self.execution_profile,
    self.provider,
    selected_provider_profile,
    self.policy,
    self.correction,
    selected_grants,
    compensation_grant=self.compensation_grant,
)
~~~

Use the existing provider-profile and grants variables at each call site; do not replace snapshot-bound values with live values.

- [ ] **Step 4: Add composition assertions**

In application tests assert:

~~~python
assert isinstance(app.sandbox, DeveloperWorkspaceAdapter)
assert isinstance(app.execution_profile, DeveloperRepositoryPatchProfile)
assert tuple(sorted(app.sandbox.specs())) == (
    "artifact.write",
    "workspace.apply_patch",
    "workspace.read",
    "workspace.run_tests",
)
~~~

Retain existing domain_pack and workspace status assertions.

- [ ] **Step 5: Run composition, API and configuration tests**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_api_surface.py \
  tests/product/test_spine0_golden_path.py \
  tests/product/test_task_configuration_application.py \
  tests/product/test_task_configuration_service.py \
  tests/product/test_long_horizon_execution.py \
  tests/product/test_long_horizon_compensation.py -q
~~~

Expected: all targeted tests pass. No external provider is called.

- [ ] **Step 6: Run import-direction guard**

~~~bash
rg -n "domain_packs|DeveloperWorkspaceAdapter|DeveloperRepositoryPatchProfile" \
  packages/os_core/src/agent_os_core
~~~

Expected: no match.

~~~bash
rg -n "from agent_os_core import .*WorkspaceSandbox|WorkspaceSandbox" \
  apps domain_packs tests/product packages/os_core/src
~~~

Expected: only the optional alias declaration inside domain_packs/developer_agent; no Core import or generic constructor.

- [ ] **Step 7: Commit**

~~~bash
git add apps/api_server/app.py tests/product
git commit -m "refactor(product): compose developer capability adapters"
~~~

### Task 7: Prove behavior equivalence and no regression

**Files:**

- Verify only: all modified implementation and test files.
- Do not update CURRENT_STATE or release documents in this implementation packet.

- [ ] **Step 1: Run focused boundary and security suites**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest \
  tests/product/test_capability_adapter_boundary.py \
  tests/product/test_developer_repository_profile.py \
  tests/product/test_spine0_security_and_persistence.py \
  tests/product/test_spine0_golden_path.py \
  tests/product/test_long_horizon_contracts.py \
  tests/product/test_long_horizon_execution.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_api_surface.py \
  tests/product/test_task_configuration_application.py \
  tests/product/test_rebind_partial_evidence_regression.py \
  tests/product_eval/test_lh1a_design.py -q
~~~

Expected: all focused tests pass.

- [ ] **Step 2: Run the full Product suite**

~~~bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  uv run --extra product-test pytest tests/product -q
~~~

Expected on unchanged e1343e3 baseline ancestry: all newly added tests pass, the pass count equals the 473-test baseline plus the net committed test additions, 1 test remains skipped, and only the two documented fixed-NOW evaluation-grant tests fail. Any new failing test is a regression and blocks acceptance.

If the implementation base includes an independently reviewed fix for those failures, expected is full green and the review receipt must name that upstream commit.

- [ ] **Step 3: Run quality and syntax checks**

~~~bash
uv run --extra product-test ruff check \
  apps domain_packs/developer_agent packages/os_core/src \
  packages/contracts/src tests/product tests/product_eval/test_lh1a_design.py
uv run --extra product-test ruff format --check \
  apps domain_packs/developer_agent packages/os_core/src \
  packages/contracts/src tests/product tests/product_eval/test_lh1a_design.py
uv run --extra product-test pyright \
  apps domain_packs/developer_agent packages/os_core/src \
  packages/contracts/src tests/product tests/product_eval/test_lh1a_design.py
python -m compileall -q apps domain_packs/developer_agent \
  packages/os_core/src packages/contracts/src tests/product_eval/test_lh1a_design.py
git diff --check
~~~

Expected: all commands exit 0.

- [ ] **Step 4: Run final structural assertions**

~~~bash
test "$(rg -l 'class WorkspaceSandbox' packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "0"
test "$(rg -l 'Repository task:|workspace\.apply_patch tool' packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "0"
test "$(rg -l 'domain_packs\.developer_agent' packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "0"
test "$(rg -l 'class DeveloperWorkspaceAdapter' domain_packs/developer_agent | wc -l | tr -d ' ')" = "1"
test "$(rg -o 'self\.connector\.execute\(action\)' packages/os_core/src/agent_os_core | wc -l | tr -d ' ')" = "1"
test "$(rg -l 'self\.(sandbox|capabilities)\.execute' apps/api_server/app.py packages/os_core/src/agent_os_core/execution.py | wc -l | tr -d ' ')" = "0"
test "$(rg -l 'def invoke\(' domain_packs/developer_agent/workspace_capability.py | wc -l | tr -d ' ')" = "0"
test "$(rg -l '^def _as_sequence' packages/os_core/src/agent_os_core/capability.py | wc -l | tr -d ' ')" = "1"
test "$(shasum -a 256 docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml | cut -d ' ' -f 1)" = "21db5ab15ffa84a7db07ded2f4a9fee1b8683a8212084993b695101845acfa21"
rg -n "TEST_MAINTENANCE_ONLY|NO_RESULT_CHANGE|NO_CLAIM_UPGRADE|DeveloperWorkspaceAdapter\.specs" \
  docs/research/LH-RECOVERY-1A-RUNTIME-SHAPE-SUCCESSOR-v2.yaml
git status --short
~~~

Expected: every structural and frozen-byte command succeeds; git status contains
only the planned AWL-2 files before the final commit.

- [ ] **Step 5: Commit any final test-only corrections atomically**

~~~bash
git add apps domain_packs/developer_agent packages/os_core/src \
  packages/contracts/src tests/product tests/product_eval/test_lh1a_design.py \
  docs/research/LH-RECOVERY-1A-RUNTIME-SHAPE-SUCCESSOR-v2.yaml
git commit -m "test(product): verify capability adapter equivalence"
~~~

Skip this commit if there are no final changes.

### Task 8: Obtain exact-head independent technical review

**Files:**

- Read-only review of the exact implementation HEAD and parent design.

- [ ] **Step 1: Freeze exact review inputs**

Record:

~~~bash
git rev-parse HEAD
git status --short
git diff --check HEAD^ HEAD
git show --stat --oneline HEAD
~~~

The worktree must be clean.

- [ ] **Step 2: Ask the independent reviewer the precise questions**

The review request must ask:

1. Does any production path call DeveloperWorkspaceAdapter.execute outside CapabilityBroker?
2. Can the adapter create or alter permit, C7, policy or ActionReceipt authority?
3. Are capability IDs, versions, events, digests, idempotency and compensation semantics equivalent?
4. Is any repository prompt or WorkspaceSandbox concrete type still required by generic Core constructors?
5. Does the remaining patch compensation debt stay within the AWL-3 boundary?
6. Are the two known Product failures pre-existing and are there any new regressions?
7. Are Broker pre-dispatch exceptions, adapter pre-effect exceptions and
   dispatch/write `FAILED` effects receipt-equivalent to the exact base?
8. Does the LH-RECOVERY-1A successor preserve the frozen parent hash and every
   research result/claim while changing only live runtime-shape maintenance?

Require one literal verdict:

~~~text
TECHNICAL_APPROVE
SPEC_REVISE
TECHNICAL_REJECT
~~~

- [ ] **Step 3: Gate integration**

TECHNICAL_APPROVE permits only an integration proposal. SPEC_REVISE or TECHNICAL_REJECT keeps the branch NOT_ACCEPTED. No verdict authorizes push, merge or release.

## Completion receipt

The implementer reports:

- exact base and final HEAD;
- branch and worktree;
- changed-file list;
- RED and GREEN targeted commands;
- full Product result, including the exact two known failures if still present;
- Ruff, format, Pyright, compileall and diff-check results;
- structural boundary scan;
- frozen LH-RECOVERY-1A parent hash, successor commit and its independent
  maintenance-only verdict;
- independent reviewer identity/session/verdict;
- remaining AWL-3 compensation debt;
- explicit NO_PUSH / NO_MERGE / NO_RELEASE.
