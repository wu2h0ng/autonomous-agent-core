from __future__ import annotations

from enum import Enum
from typing import Protocol

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    NodeKind,
    PrincipalIdentity,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_contracts.common import ContractModel, NonEmptyStr

from .task_aggregate import TaskAggregate
from .task_configuration import TASK_CONFIGURATION_CAPABILITY

from .c7_receipt import (
    C7ReceiptError,
    C7ReceiptIssuer,
    C7ReceiptVerifier,
    C7VerificationScope,
)
from .governance import CorrectionGuardConflict, CorrectionReadPort
from .errors import AgentOSCoreError
from .task_service import TaskService


class ExecutionDenialReason(str, Enum):
    """Enumerable fail-closed reasons for refusing a commit/start."""

    TASK_UNAVAILABLE = "TASK_UNAVAILABLE"
    TASK_NOT_DRAFT = "TASK_NOT_DRAFT"
    PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
    PLAN_BINDING_MISMATCH = "PLAN_BINDING_MISMATCH"
    COMMIT_REJECTED = "COMMIT_REJECTED"
    SNAPSHOT_REJECTED = "SNAPSHOT_REJECTED"
    C7_REJECTED = "C7_REJECTED"
    START_REJECTED = "START_REJECTED"


class SrlExecutionPlan(ContractModel):
    """Trusted execution contracts for one activated SRL task.

    Supplied only by an injected trusted port; an SRL organ must never author it.
    """

    task_id: NonEmptyStr
    commitment: Commitment
    workflow: WorkflowGraph
    expected_outcome: ExpectedOutcome
    capability_id: NonEmptyStr


class SrlExecutionResult(ContractModel):
    committed: bool
    started: bool = False
    task_id: NonEmptyStr
    run_id: NonEmptyStr | None = None
    denial_reason: ExecutionDenialReason | None = None
    detail: NonEmptyStr | None = None


class TrustedSrlExecutionPlanPort(Protocol):
    """Resolves the trusted execution contracts for an activated task."""

    def resolve(self, task_id: str) -> SrlExecutionPlan | None: ...


class TaskSnapshotServicePort(Protocol):
    """Trusted task-configuration service.

    ``seal`` reserves the run identity; ``start_run`` is the C7-guarded start
    (it re-checks the snapshot's original correction epochs and wraps the run-start
    append in ``guard_unchanged``), which closes the verify->start race.
    """

    def seal(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        command: TaskConfigurationSnapshotCommand,
    ) -> TaskConfigurationSnapshot: ...

    def start_run(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        snapshot_id: str,
    ) -> TaskAggregate: ...


class SrlTaskExecutionBridge:
    """Fail-closed commit + start bridge for an activated SRL task.

    Order (CTO condition 2): commit -> seal (reserves the run id) -> verify C7
    with the reserved run id -> start. A C7 change/failure after commit leaves an
    auditable COMMITTED state without starting. It never executes an effect and
    never authors execution contracts; the plan is trusted-only.
    """

    def __init__(
        self,
        *,
        task_service: TaskService,
        plan_port: TrustedSrlExecutionPlanPort,
        task_snapshots: TaskSnapshotServicePort,
        principal: PrincipalIdentity,
        correction: CorrectionReadPort,
        c7_issuer: C7ReceiptIssuer,
        c7_verifier: C7ReceiptVerifier,
    ) -> None:
        self._tasks = task_service
        self._plan = plan_port
        self._snapshots = task_snapshots
        self._principal = principal
        self._correction = correction
        self._c7_issuer = c7_issuer
        self._c7_verifier = c7_verifier

    def commit_and_start(
        self,
        task_id: str,
        *,
        snapshot_command: TaskConfigurationSnapshotCommand | None = None,
    ) -> SrlExecutionResult:
        def _deny(reason: ExecutionDenialReason, detail: str = "") -> SrlExecutionResult:
            return SrlExecutionResult(
                committed=False,
                started=False,
                task_id=task_id,
                denial_reason=reason,
                detail=detail or None,
            )

        try:
            aggregate = self._tasks.get_task(task_id)
        except Exception as exc:
            return _deny(ExecutionDenialReason.TASK_UNAVAILABLE, type(exc).__name__)
        if aggregate.status is not TaskStatus.DRAFT:
            return _deny(ExecutionDenialReason.TASK_NOT_DRAFT)

        plan = self._plan.resolve(task_id)
        if plan is None:
            return _deny(ExecutionDenialReason.PLAN_UNAVAILABLE)
        if not self._plan_binds(aggregate, plan):
            return _deny(ExecutionDenialReason.PLAN_BINDING_MISMATCH)

        try:
            self._tasks.commit_task(
                task_id, plan.commitment, plan.workflow, plan.expected_outcome
            )
        except AgentOSCoreError as exc:
            return _deny(ExecutionDenialReason.COMMIT_REJECTED, str(exc))

        command = snapshot_command or TaskConfigurationSnapshotCommand()
        try:
            snapshot = self._snapshots.seal(self._principal, task_id, command)
        except Exception as exc:
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.SNAPSHOT_REJECTED,
                detail=type(exc).__name__,
            )

        base_scope = {
            "tenant_id": plan.commitment.tenant_id,
            "workspace_id": plan.commitment.workspace_id,
            "task_id": task_id,
            "run_id": snapshot.reserved_run_id,
        }
        # Verify the start-authorizing scope (the configuration capability, which
        # the guarded start also holds atomically across the append) AND the plan's
        # tool capability as defense-in-depth. A per-capability halt landing after
        # this point still blocks the effect at dispatch, not the start; that
        # boundary is documented in the cast.
        for capability_id in (TASK_CONFIGURATION_CAPABILITY, plan.capability_id):
            scope = C7VerificationScope(capability_id=capability_id, **base_scope)
            try:
                receipt = self._c7_issuer.issue(task_id, scope.run_id, capability_id)
                self._c7_verifier.verify(receipt, scope=scope)
            except C7ReceiptError as exc:
                # Committed but deliberately NOT started: auditable COMMITTED state.
                return SrlExecutionResult(
                    committed=True,
                    started=False,
                    task_id=task_id,
                    denial_reason=ExecutionDenialReason.C7_REJECTED,
                    detail=type(exc).__name__,
                )

        # C7-guarded start via the configuration service, which re-checks the
        # snapshot's original correction epochs and holds guard_unchanged
        # (config capability + task + run) across the run-start append.
        # NOTE (subagent N1, OPEN): the service locks config->authority; taking an
        # ADDITIONAL authority guard here would invert that order and deadlock, so
        # the tool-capability scope is only verified pre-start (see the cast's F1).
        try:
            started = self._snapshots.start_run(
                self._principal, task_id, snapshot.snapshot_id
            )
        except C7ReceiptError as exc:
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.C7_REJECTED,
                detail=type(exc).__name__,
            )
        except CorrectionGuardConflict as exc:
            # A correction landed reentrantly while the guard was held: the
            # authority refuses it and the start is forbidden.
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.C7_REJECTED,
                detail=type(exc).__name__,
            )
        except AgentOSCoreError as exc:
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.START_REJECTED,
                detail=type(exc).__name__,
            )
        run = started.run
        return SrlExecutionResult(
            committed=True,
            started=True,
            task_id=task_id,
            run_id=run.run_id if run is not None else None,
        )

    def _plan_binds(self, aggregate, plan: SrlExecutionPlan) -> bool:
        goal = aggregate.goal
        commitment = plan.commitment
        workflow = plan.workflow
        if goal is None or commitment is None or workflow is None:
            return False
        workflow_capabilities = {
            node.capability
            for node in workflow.nodes
            if node.kind is NodeKind.TOOL and node.capability
        }
        return (
            # The task must belong to the bridge principal's tenant/workspace, so
            # a caller cannot bind a plan to a foreign-scope goal before mutation.
            goal.tenant_id == self._principal.tenant_id
            and goal.workspace_id == self._principal.workspace_id
            and plan.task_id == aggregate.task_id
            and plan.capability_id in workflow_capabilities
            and commitment.task_id == aggregate.task_id
            and commitment.goal_id == goal.goal_id
            and commitment.tenant_id == goal.tenant_id
            and commitment.workspace_id == goal.workspace_id
            and workflow.tenant_id == goal.tenant_id
            and workflow.workspace_id == goal.workspace_id
            and plan.expected_outcome.task_id == aggregate.task_id
            and plan.expected_outcome.tenant_id == goal.tenant_id
            and plan.expected_outcome.workspace_id == goal.workspace_id
        )
