"""Baseline pins for the ADR-0061 Form B probes that need no child agents.

Source of truth: ``docs/reviews/ADR-0061-C6-C7-PRESERVATION-REVIEW-2026-09-19.md``
(PR #95) -- an adversarial review of the frozen ``agent.spawn`` design that listed
probes P1-P14 and recorded, honestly, that not one of them had ever been run.

This module is the "before" side of that probe list: the review's claims that are
facts about the EXISTING system, independent of whether Form B lands. The Form B
implementation commit is the "after" side, and the C7 cascade pins below are the
ones that commit is REQUIRED to change -- a green cascade pin after the kernel
lands means the hierarchy axis was never added, which is the review's C2 finding.

Pinned here (review claim -> test):

* ``governance.py:129-138`` -- ``halted()`` consults only the action's own
  ``(task, run, capability)`` keys, and ``app.py:2963`` writes only the corrected
  session's own task key, so an operator halt does not cascade to any other
  task/run. ``app.py:2912-2915`` (pause) writes no C7 correction at all.
* ``capability.py:193`` -- ``connector.execute`` has exactly one call site in the
  tree, inside ``CapabilityBroker.invoke``, which is the only dispatch entry point.
* ``agent_loop.py:525-534`` + ``governance.py:378-381`` -- an approved action is
  bound to its own action digest, so cross-session approval reuse (probe P8) is
  correctly refused.
* Lease expiry / reclaim semantics -- the review recorded probe P13 as
  ``undetermined`` because it did not read ``persistence.py``'s lease internals.
  The last two tests pin the answer from the code that is in the tree.

Claim classes (root ``AGENTS.md`` §4 / repo ``AGENTS.md`` §4): every assertion
here is ``tested`` against the implementation on this base commit. Nothing in
this module claims that Form B exists, works, or is safe.
"""

from __future__ import annotations

import ast
import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    ActionContract,
    ActionPermit,
    ApprovalDecision,
    ApprovalDisposition,
    CapabilityGrant,
    CapabilityGrantStatus,
    CapabilitySpec,
    CorrectionEpochVector,
    PrincipalIdentity,
    PrincipalRole,
    ReceiptStatus,
    ResourceBudget,
    SideEffectGuarantee,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    TaskEventType,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    CorrectionAuthority,
    DeferredApprovalGateway,
    DeterministicProvider,
    DurableActionOutcomeRepository,
    ExecutionLease,
    InvalidTransitionError,
    PolicyInput,
    PolicyKernel,
    SQLiteTaskEventStore,
)
from agent_os_core.errors import ConcurrentWriteError
from agent_os_core.provider import ProviderToolProposal

from apps.api_server.app import AgentOSApplication

REPO_ROOT = Path(__file__).resolve().parents[2]

# Where the single capability dispatch path must stay single. `tests/` is
# excluded on purpose: fixtures may implement their own connector, and the claim
# under test is about the production path (ADR-0059:69 lists app/loop/pipeline).
PRODUCTION_ROOTS = ("packages", "apps", "domain_packs", "src")


def _production_sources() -> list[Path]:
    paths: list[Path] = []
    for root in PRODUCTION_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# helpers: a hermetic chat app (no daemon, no port, temp database + workspace)
# ---------------------------------------------------------------------------


def _app(tmp_path: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=tmp_path,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="probe-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _wait_for(predicate: Any, description: str, timeout: float = 10.0) -> Any:
    """Poll until ``predicate`` is truthy; ``begin_turn`` returns before the turn runs.

    ``surface_begin_turn`` records the durable turn-start and then executes the
    turn on a worker thread, so a test that reads durable state straight after it
    returns is racing the turn. Every place this module drives a turn waits here
    first, exactly as ``tests/product/test_permission_mode_matrix.py`` does.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"{description} did not occur within {timeout}s")


def _begin_turn(app: AgentOSApplication, session_id: str) -> Any:
    stream_id = app.subscribe_stream(session_id)
    task_id = app.surface_task_for_session(session_id)
    return app.surface.begin_turn(
        SurfaceBeginTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=session_id,
            text="do the turn",
            stream=SurfaceStreamBinding(
                runtime_boot_id=app.runtime_boot_id,
                stream_id=stream_id,
            ),
            expected_event_sequence=app.surface_current_sequence(task_id),
            idempotency_key=f"turn:{session_id}:{time.monotonic_ns()}",
            requested_at=datetime.now(timezone.utc),
        )
    )


def _await_turn_completed(app: AgentOSApplication, session_id: str) -> None:
    _wait_for(
        lambda: app.surface_has_uncommitted_turn(session_id) is False,
        f"turn in {session_id} to commit",
    )


def _await_pending_approval(
    app: AgentOSApplication, task_id: str, session_id: str
) -> Any:
    return _wait_for(
        lambda: app.tasks.project_session(task_id, session_id).pending_continuation,
        f"session {session_id} to park on a pending approval",
    )


def _edit_script() -> tuple:
    return (
        (
            "",
            (
                _proposal(
                    "call-edit",
                    "workspace.edit",
                    {
                        "path": "fixture.txt",
                        "old_string": "stable\n",
                        "new_string": "fixed\n",
                    },
                ),
            ),
        ),
        ("edit applied", ()),
    )


def _two_session_edit_script() -> tuple:
    """One edit proposal per session: the scripted provider is a shared FIFO."""

    entry = _edit_script()[0]
    return (entry, entry, "edit applied", "edit applied")


# ---------------------------------------------------------------------------
# C7 reach: the halt key space has no hierarchy axis (review C2 / G1)
# ---------------------------------------------------------------------------


def test_correction_halt_keyspace_has_no_hierarchy_axis() -> None:
    """``halted()`` answers from the three keys it is handed, nothing else.

    This is the root of the review's C2 finding: ``halted(task, run, capability)``
    is an ``any`` over exactly those three scopes. A correction on one task
    therefore cannot reach an action dispatched under a different task, and there
    is no fourth scope a parent/child axis could be expressed in.
    """

    authority = CorrectionAuthority()

    # A "parent" session's task is halted by the operator.
    assert authority.correct("task", "task:parent", "operator halt") == 1
    assert authority.halted("task:parent", "run:parent", "workspace.read") is True
    # The task axis alone is enough: the run and capability are not consulted to
    # decide the parent's own fate.
    assert authority.halted("task:parent", "run:other", "workspace.shell") is True

    # A "child" session -- its own task and run, the same capability -- is NOT.
    # This is what a Form B child would look like: its own task/run keys.
    assert authority.halted("task:child", "run:child", "workspace.read") is False
    # ... and it stays false no matter how many other tasks are halted. Epochs are
    # per (scope, scope_id), so a second halted task starts its own counter at 1.
    assert authority.correct("task", "task:parent-2", "operator halt") == 1
    assert authority.halted("task:parent-2", "run:parent-2", "workspace.read") is True
    assert authority.halted("task:child", "run:child", "workspace.read") is False

    # The one axis that IS global: a capability id names one capability for the
    # whole authority, so halting it reaches every task and run. The review calls
    # this the operator's only existing "reach the children" lever.
    assert authority.correct("capability", "workspace.shell", "global halt") == 1
    assert authority.halted("task:child", "run:child", "workspace.shell") is True
    assert authority.halted("task:unrelated", "run:unrelated", "workspace.shell") is True

    # And a run-scoped correction reaches only that run.
    assert authority.correct("run", "run:child", "stop this run") == 1
    assert authority.halted("task:other", "run:child", "workspace.read") is True
    assert authority.halted("task:other", "run:unrelated", "workspace.read") is False


def test_operator_correction_writes_only_the_corrected_sessions_own_task_key(
    tmp_path: Path,
) -> None:
    """The operator's halt lever targets the session's own task, and nothing else.

    ``surface_correct_session`` -> ``correct_task`` -> ``correct("task", task_id)``
    (``app.py:2501-2506``, ``app.py:2963``). Two independent sessions in one
    application are the closest thing this base commit has to a parent/child pair,
    so they stand in for the pair until Form B exists.
    """

    app = _app(tmp_path, scripted=(("session a done", ()), ("session b done", ())))
    session_a, _ = app.open_chat_session("session a", DeferredApprovalGateway())
    session_b, _ = app.open_chat_session("session b", DeferredApprovalGateway())
    assert session_a.task_id != session_b.task_id
    _begin_turn(app, session_a.session_id)
    _await_turn_completed(app, session_a.session_id)
    _begin_turn(app, session_b.session_id)
    _await_turn_completed(app, session_b.session_id)

    def _corrections(task_id: str) -> list[Any]:
        return [
            event
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.CORRECTION_WRITTEN
        ]

    # Pause is the operator's other "stop this session" lever, and it writes no C7
    # correction at all -- it only moves the run's status (``app.py:2912-2915``),
    # so it cannot halt an action even on its own task. (The run is put back into
    # RUNNING first, exactly as the existing control test at
    # tests/product/test_surface_runtime.py does.)
    app.resume_task(session_b.task_id)
    before = app.correction.snapshot(
        session_b.task_id, session_b.run_id, "workspace.read"
    )
    app.pause_task(session_b.task_id)
    assert (
        app.correction.snapshot(
            session_b.task_id, session_b.run_id, "workspace.read"
        )
        == before
    )
    assert (
        app.correction.halted(session_b.task_id, session_b.run_id, "workspace.read")
        is False
    )
    assert _corrections(session_b.task_id) == []

    # Now the operator halts session A.
    app.correct_task(session_a.task_id, "operator halted session a")

    # Session A is halted on its own keys.
    assert (
        app.correction.halted(session_a.task_id, session_a.run_id, "workspace.read")
        is True
    )
    # Session B is untouched: the same call did not cascade.
    assert (
        app.correction.halted(session_b.task_id, session_b.run_id, "workspace.read")
        is False
    )

    # The durable record lands on the corrected task's stream only.
    assert len(_corrections(session_a.task_id)) == 1
    assert _corrections(session_b.task_id) == []


def _policy_material(
    task_id: str = "task:parent", run_id: str = "run:parent"
) -> tuple[ActionContract, CapabilityGrant, CapabilitySpec, PrincipalIdentity]:
    now = datetime.now(timezone.utc)
    principal = PrincipalIdentity(
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=now,
    )
    capability = CapabilitySpec(
        capability_id="workspace.read",
        version="1",
        display_name="read",
        input_contract="json:object:1",
        output_contract="json:object:1",
        side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
        idempotency_supported=True,
        credential_class="none",
        data_boundary="workspace-local",
        risk_tier=1,
        timeout_seconds=30,
        cancellation_supported=True,
        compensation_supported=False,
        audit_policy="event-and-artifact",
        created_by="system",
        created_at=now,
    )
    budget = ResourceBudget(
        max_cost_usd=Decimal("0"),
        max_duration_seconds=30,
        max_provider_tokens=0,
        max_tool_calls=1,
    )
    grant = CapabilityGrant(
        grant_id="grant:read",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=budget,
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="system",
        granted_at=now,
        expires_at=now + timedelta(hours=1),
    )
    action = ActionContract(
        action_id=f"action:{task_id}",
        task_id=task_id,
        run_id=run_id,
        node_id="node:read",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        capability_id="workspace.read",
        capability_version="1",
        arguments_json="{}",
        risk_tier=1,
        idempotency_key=f"idempotency:{task_id}",
        estimated_budget=budget,
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id=f"expected:{task_id}",
        candidate_envelope_id=f"envelope:{task_id}",
        created_at=now,
    )
    return action, grant, capability, principal


def test_policy_kernel_admits_a_foreign_task_action_while_another_task_is_halted() -> (
    None
):
    """``PolicyKernel.decide`` checks the action's own keys, so halt is not abstract.

    The kernel's only correction lookup is
    ``self.correction.halted(action.task_id, action.run_id, action.capability_id)``
    (``governance.py:372``). An action on a task the operator never halted is
    ADMITTED, which is precisely the C2 hole once the second task belongs to a
    spawned child.
    """

    correction = CorrectionAuthority()
    now = datetime.now(timezone.utc)
    parent_action, grant, capability, principal = _policy_material()
    child_action, _, _, _ = _policy_material("task:child", "run:child")

    # The operator halts the parent session's task.
    correction.correct("task", "task:parent", "operator halted the parent")

    kernel = PolicyKernel(correction, clock=lambda: now)

    parent_decision = kernel.decide(
        parent_action,
        PolicyInput(principal=principal, grant=grant, capability=capability, now=now),
    )
    assert parent_decision.verdict.value == "DENY"
    assert parent_decision.reason_codes == ("CORRECTION_HALTED",)

    # One grant, and it has no axis that could narrow a child: the grant is
    # scoped to (principal, tenant, workspace, capability, version) only, so
    # "this task's grants" is not a concept the authority spine can express.
    assert "task_id" not in CapabilityGrant.model_fields
    assert "run_id" not in CapabilityGrant.model_fields
    child_decision = kernel.decide(
        child_action,
        PolicyInput(principal=principal, grant=grant, capability=capability, now=now),
    )
    assert child_decision.verdict.value == "ALLOW"
    assert child_decision.reason_codes == ("ADMITTED",)


class _RecordingConnector:
    """Minimal ADR-0059 connector: specs / outcomes / replay / preflight / execute."""

    def __init__(self, tmp_path: Path) -> None:
        self.execute_count = 0
        self.store = SQLiteTaskEventStore(tmp_path / "dispatch.sqlite3")
        self._outcomes = DurableActionOutcomeRepository(self.store)

    def specs(
        self, now: datetime | None = None, *, include_internal: bool = False
    ) -> dict[str, CapabilitySpec]:
        now = now or datetime.now(timezone.utc)
        return {
            "workspace.read": CapabilitySpec(
                capability_id="workspace.read",
                version="1",
                display_name="read",
                input_contract="json:object:1",
                output_contract="json:object:1",
                side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                credential_class="none",
                data_boundary="workspace-local",
                risk_tier=1,
                timeout_seconds=30,
                audit_policy="event-and-artifact",
                created_by="system",
                created_at=now,
                collaboration_required=False,
            )
        }

    def outcomes(self) -> Any:
        return self._outcomes

    def replay(self, action: ActionContract) -> Any:
        return self._outcomes.replay(action)

    def preflight(
        self, capability_id: str, args: dict[str, object], action_key: str
    ) -> None:
        return None

    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={
                "artifact_ids": ("artifact:" + "a" * 64,),
                "compensation_ref": "detail:probe",
            },
            error_code="error:none",
            detail_ref="detail:probe",
        )


def _permit(
    action: ActionContract,
    correction: CorrectionAuthority,
    *,
    lease_fence: int,
) -> ActionPermit:
    now = datetime.now(timezone.utc)
    epochs = correction.snapshot(action.task_id, action.run_id, action.capability_id)
    return ActionPermit(
        permit_id=f"permit:{action.action_id}",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id=f"decision:{action.action_id}",
        grant_id="grant:read",
        correction_epochs=epochs,
        lease_fence=lease_fence,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def test_capability_broker_dispatches_a_foreign_task_action_after_a_halt(
    tmp_path: Path,
) -> None:
    """The broker's halt check is also per-action, so the C2 hole reaches execution.

    ``CapabilityBroker.invoke`` checks
    ``self.correction.halted(action.task_id, action.run_id, action.capability_id)``
    (``capability.py:154-163``) before the guarded dispatch. With the parent's task
    halted, a foreign task's action reaches ``connector.execute``; the parent's own
    action does not.
    """

    correction = CorrectionAuthority()
    connector = _RecordingConnector(tmp_path)
    broker = CapabilityBroker(connector, correction)

    parent_action, _, _, _ = _policy_material()
    child_action, _, _, _ = _policy_material("task:child", "run:child")

    def _claim(run_id: str) -> ExecutionLease:
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        fence = connector.store.acquire_lease(run_id, "probe:worker", expiry.isoformat())
        return ExecutionLease(
            run_id=run_id, owner="probe:worker", fence=fence, expires_at=expiry
        )

    # Baseline: with no correction written, the foreign action dispatches. Its
    # permit is issued against its own (unhalted) epoch vector.
    child_claim = _claim(child_action.run_id)
    result = broker.invoke(
        child_action,
        _permit(child_action, correction, lease_fence=child_claim.fence),
        execution_claim=child_claim,
    )
    assert connector.execute_count == 1
    assert result.receipt.status is ReceiptStatus.SUCCEEDED

    # Operator halts the parent's task, then a fresh parent action is prepared.
    correction.correct("task", "task:parent", "operator halted the parent")
    parent_action = parent_action.model_copy(
        update={
            "action_id": "action:parent:after-halt",
            "idempotency_key": "idempotency:parent:after-halt",
            "observed_correction_epochs": correction.snapshot(
                "task:parent", "run:parent", "workspace.read"
            ),
        }
    )
    parent_claim = _claim(parent_action.run_id)
    with pytest.raises(CapabilityDenied, match="correction authority is halted"):
        broker.invoke(
            parent_action,
            _permit(parent_action, correction, lease_fence=parent_claim.fence),
            execution_claim=parent_claim,
        )
    assert connector.execute_count == 1, (
        "the halted parent action must never reach the connector"
    )

    # The foreign ("child") action still dispatches: the halt did not cascade. It
    # is a second action on the child's run, so it takes a fresh claim and permit.
    child_action_2, _, _, _ = _policy_material("task:child", "run:child")
    child_action_2 = child_action_2.model_copy(
        update={
            "action_id": "action:child:second",
            "idempotency_key": "idempotency:task:child:second",
        }
    )
    child_claim_2 = _claim(child_action_2.run_id)
    result_2 = broker.invoke(
        child_action_2,
        _permit(child_action_2, correction, lease_fence=child_claim_2.fence),
        execution_claim=child_claim_2,
    )
    assert connector.execute_count == 2
    assert result_2.receipt.status is ReceiptStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Dispatch linearity: one call site, one entry point (review D1)
# ---------------------------------------------------------------------------


def _enclosing_function(source: str, lineno: int) -> tuple[str | None, str | None]:
    """Return (class name, function name) innermost enclosing ``lineno``."""

    tree = ast.parse(source)
    found: tuple[str | None, str | None] = (None, None)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (node.lineno <= lineno <= (node.end_lineno or node.lineno)):
            continue
        if isinstance(node, ast.FunctionDef):
            if found[1] is None:
                found = (found[0], node.name)
        else:
            found = (node.name, found[1])
    return found


def test_connector_execute_has_exactly_one_call_site_in_the_tree() -> None:
    """``connector.execute`` is the physical effect boundary and has one caller.

    ADR-0059:19 makes ``CapabilityBroker.invoke`` the ONLY dispatch path and
    :17 rejects a second one as a bypass risk. This asserts that on the tree, not
    on a single file: a new dispatch path -- including a spawn manager that calls
    the connector directly from ``AgentLoop`` -- shows up here as a second call
    site and fails this test.
    """

    call_site = re.compile(r"\bconnector\.execute\s*\(")
    hits: list[tuple[str, int]] = []
    for path in _production_sources():
        for match in call_site.finditer(path.read_text(encoding="utf-8")):
            lineno = path.read_text(encoding="utf-8")[: match.start()].count("\n") + 1
            hits.append((str(path.relative_to(REPO_ROOT)), lineno))

    assert len(hits) == 1, (
        "the capability connector's physical execute() must have exactly one call "
        f"site in the production tree, found {len(hits)}: {hits}"
    )
    relative, lineno = hits[0]
    assert relative == "packages/os_core/src/agent_os_core/capability.py", (
        f"the single connector.execute call site moved to {relative}; ADR-0059 "
        "requires it to stay inside CapabilityBroker.invoke"
    )

    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    class_name, function_name = _enclosing_function(source, lineno)
    assert (class_name, function_name) == ("CapabilityBroker", "invoke"), (
        "connector.execute must be called from CapabilityBroker.invoke, found "
        f"{class_name}.{function_name}"
    )


def test_capability_broker_invoke_is_the_only_dispatch_entry_point() -> None:
    """Every production dispatch goes through one broker entry point.

    The three production ``.invoke(`` call sites (``execution.py:1236``,
    ``action_pipeline.py:343``, ``action_pipeline.py:479``) all enter the same
    ``CapabilityBroker`` class, so a Form B child -- as an ordinary session -- would
    inherit the same path. A spawn path that dispatches any other way fails here.
    """

    invoke_call = re.compile(r"\b(?P<receiver>[A-Za-z_]\w*)\.invoke\s*\(")
    receivers: dict[str, set[str]] = {}
    for path in _production_sources():
        text = path.read_text(encoding="utf-8")
        for match in invoke_call.finditer(text):
            receivers.setdefault(match.group("receiver"), set()).add(
                str(path.relative_to(REPO_ROOT))
            )

    assert set(receivers) == {"broker", "_broker"}, (
        "capability dispatch must be invoked on a broker attribute only; found "
        f"receivers {sorted(receivers)}"
    )
    assert receivers["broker"] == {"packages/os_core/src/agent_os_core/execution.py"}
    assert receivers["_broker"] == {
        "packages/os_core/src/agent_os_core/action_pipeline.py"
    }

    # Both holders must be the one broker class rather than a duck-typed stand-in:
    # that is what keeps the dispatch path single as files change.
    execution = (
        REPO_ROOT / "packages/os_core/src/agent_os_core/execution.py"
    ).read_text(encoding="utf-8")
    pipeline = (
        REPO_ROOT / "packages/os_core/src/agent_os_core/action_pipeline.py"
    ).read_text(encoding="utf-8")
    # execution.py constructs its broker in place, so the construction itself is
    # the annotation.
    assert "self.broker = CapabilityBroker(" in execution
    assert re.search(r"\bbroker\s*:\s*CapabilityBroker\b", pipeline), (
        "the action pipeline's broker must be annotated CapabilityBroker"
    )
    assert re.search(r"self\._broker\s*=\s*broker", pipeline)


# ---------------------------------------------------------------------------
# Approval binding (review B1 / probe P8)
# ---------------------------------------------------------------------------


def test_policy_kernel_denies_an_approval_bound_to_a_foreign_action_digest() -> None:
    """A decision approved for one action cannot admit another (``governance.py:378``).

    This is one leg of the review's B1 ``defended`` verdict: the second lookup site
    compares the approval's digest with the exact action digest.
    """

    correction = CorrectionAuthority()
    now = datetime.now(timezone.utc)
    action, grant, capability, principal = _policy_material()
    other_action, _, _, _ = _policy_material("task:child", "run:child")

    approval = ApprovalDecision(
        approval_id="approval:parent",
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        action_digest=action.action_digest(),
        actor_id=principal.principal_id,
        actor_role=principal.role,
        disposition=ApprovalDisposition.APPROVE,
        reason="approved the parent action",
        decided_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    kernel = PolicyKernel(correction, clock=lambda: now)
    context = PolicyInput(
        principal=principal,
        grant=grant,
        capability=capability,
        approval=approval,
        now=now,
    )

    own = kernel.decide(action, context)
    assert own.verdict.value == "ALLOW"

    foreign = kernel.decide(other_action, context)
    assert foreign.verdict.value == "DENY"
    assert foreign.reason_codes == ("APPROVAL_DIGEST_MISMATCH",)


def test_cross_session_approval_reuse_is_refused_by_resume_pending_approval(
    tmp_path: Path,
) -> None:
    """Probe P8: a parent session's approval cannot resume another session.

    Two independent sessions stand in for the parent/child pair. Both park on a
    tier-2 ``workspace.edit`` confirmation; resuming session B with session A's
    ``ApprovalDecision`` is refused by the digest check at ``agent_loop.py:525-534``
    even though B *does* have a pending approval of its own -- so the refusal is
    about digest binding, not about the absence of a pending action.
    """

    app = _app(tmp_path, scripted=_two_session_edit_script())
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")

    session_a, _ = app.open_chat_session("session a", DeferredApprovalGateway())
    session_b, _ = app.open_chat_session("session b", DeferredApprovalGateway())
    _begin_turn(app, session_a.session_id)
    pending_a = _await_pending_approval(app, session_a.task_id, session_a.session_id)
    _begin_turn(app, session_b.session_id)
    pending_b = _await_pending_approval(app, session_b.task_id, session_b.session_id)

    assert pending_a is not None and pending_b is not None, (
        "both sessions must park on their own pending approval for this probe to "
        "mean anything"
    )
    assert pending_a.action.action_digest() != pending_b.action.action_digest(), (
        "the two pending actions must be distinguishable by digest"
    )

    _, loop_b = app.restore_chat_session(
        session_b.session_id, DeferredApprovalGateway()
    )
    now = datetime.now(timezone.utc)
    stolen = ApprovalDecision(
        approval_id="approval:borrowed-from-a",
        tenant_id=pending_a.action.tenant_id,
        workspace_id=pending_a.action.workspace_id,
        action_digest=pending_a.action.action_digest(),
        actor_id=app.principal.principal_id,
        actor_role=app.principal.role,
        disposition=ApprovalDisposition.APPROVE,
        reason="reusing session a's approval for session b",
        decided_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    with pytest.raises(
        InvalidTransitionError, match="does not bind the exact pending action"
    ):
        loop_b.resume_pending_approval(session_b, stolen)

    # The borrowed approval did not consume or resolve session B's own pending
    # action, and the file is untouched.
    still_pending = app.tasks.project_session(
        session_b.task_id, session_b.session_id
    ).pending_continuation
    assert still_pending is not None
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"


# ---------------------------------------------------------------------------
# Lease expiry / reclaim: probe P13's "undetermined" answer
# ---------------------------------------------------------------------------
# The review recorded P13 as undetermined because it read only the entry point of
# persistence.py:286-323 and not ``_acquire_lease_in_transaction``. The two tests
# below pin what that method and the reservation guard actually do, so the next
# reviewer starts from behaviour instead of re-reading.


def test_expired_execution_lease_allows_a_higher_fence_to_take_over(
    tmp_path: Path,
) -> None:
    """An expired lease is reclaimable, but a live one is not wrested away.

    ``_acquire_lease_in_transaction`` (``persistence.py:370-394``) refuses only
    when the stored lease is still ACTIVE *and* held by a different owner; it then
    writes ``fence + 1``. So a second owner cannot take a larger fence while the
    first lease is alive, and can take one as soon as it has expired.
    """

    store = SQLiteTaskEventStore(tmp_path / "leases.sqlite3")
    now = datetime.now(timezone.utc)
    expired = (now - timedelta(minutes=1)).isoformat()
    live = (now + timedelta(minutes=5)).isoformat()

    first = store.acquire_lease("run:parent", "worker:first", expired)
    assert first == 1
    # An expired lease is not reported as an active fence.
    assert store.lease_fence("run:parent") == 0

    # A second owner reclaims it with a strictly larger fence.
    second = store.acquire_lease("run:parent", "worker:second", live)
    assert second == first + 1

    # While that lease is live, a third owner is refused outright.
    with pytest.raises(ConcurrentWriteError):
        store.acquire_lease("run:parent", "worker:third", live)
    # ... and so is a re-acquire by the current owner? No: the same owner may
    # extend, which is what a long in-flight turn does today.
    assert store.acquire_lease("run:parent", "worker:second", live) == second + 1


def test_a_stale_lease_cannot_reserve_and_a_reservation_forbids_automatic_resend(
    tmp_path: Path,
) -> None:
    """The interlock against a double effect is the RESERVATION, not the lease.

    ``put_idempotency_guarded_by_lease`` (``persistence.py:325-363``) requires the
    stored lease row to match fence, owner and ``expires_at`` exactly and still be
    active, so a reclaiming owner cannot reserve the same action with a stale
    lease. And once a reservation exists without an outcome,
    ``DurableActionOutcomeRepository.replay`` raises a typed UNKNOWN
    (``_action_outcome.py:142-152``, ADR-0059:36-42) instead of re-dispatching.
    """

    store = SQLiteTaskEventStore(tmp_path / "reserve.sqlite3")
    connector = _RecordingConnector(tmp_path)
    repo = connector.outcomes()
    action, _, _, _ = _policy_material()

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=1)).isoformat()

    # A stale (expired) lease cannot reserve capability dispatch.
    with pytest.raises(ConcurrentWriteError):
        store.put_idempotency_guarded_by_lease(
            action.run_id,
            "probe:worker",
            1,
            past,
            DurableActionOutcomeRepository.RESERVATION_SCOPE,
            action.idempotency_key,
            {"state": "RESERVED"},
            now.isoformat(),
        )

    # A live lease reserves the action once.
    live_claim = repo.acquire_execution_lease(
        action, "probe:worker", ttl=timedelta(minutes=5)
    )
    reservation = repo.reserve(action, execution_lease=live_claim)
    assert isinstance(reservation, dict)
    assert reservation["state"] == "RESERVED"

    # Re-reserving the same action on that lease does not dispatch again: it
    # replays the reservation, which is a reservable outcome with no terminal
    # record, so it is a typed UNKNOWN.
    with pytest.raises(Exception) as conflict:
        repo.reserve(action, execution_lease=live_claim)
    assert "RESERVATION_WITHOUT_OUTCOME" in str(conflict.value), (
        "a second reservation attempt on an unreserved-outcome action must not "
        f"re-dispatch; expected RESERVATION_WITHOUT_OUTCOME, got {conflict.value!r}"
    )

    # And a plain replay of the same action is that same typed UNKNOWN.
    with pytest.raises(Exception) as unknown:
        repo.replay(action)
    assert "RESERVATION_WITHOUT_OUTCOME" in str(unknown.value)
    assert connector.execute_count == 0
