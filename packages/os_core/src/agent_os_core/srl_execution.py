from __future__ import annotations

from enum import Enum
from typing import Protocol

from agent_os_contracts import (
    Commitment,
    ExpectedOutcome,
    PrincipalIdentity,
    TaskConfigurationSnapshot,
    TaskConfigurationSnapshotCommand,
    TaskStatus,
    WorkflowGraph,
)
from agent_os_contracts.common import ContractModel, NonEmptyStr

from .c7_receipt import (
    C7ReceiptError,
    C7ReceiptIssuer,
    C7ReceiptVerifier,
    C7VerificationScope,
)
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


class SnapshotSealerPort(Protocol):
    """Trusted configuration-snapshot sealer (reserves the run identity)."""

    def seal(
        self,
        principal: PrincipalIdentity,
        task_id: str,
        command: TaskConfigurationSnapshotCommand,
    ) -> TaskConfigurationSnapshot: ...


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
        snapshot_sealer: SnapshotSealerPort,
        principal: PrincipalIdentity,
        c7_issuer: C7ReceiptIssuer,
        c7_verifier: C7ReceiptVerifier,
    ) -> None:
        self._tasks = task_service
        self._plan = plan_port
        self._sealer = snapshot_sealer
        self._principal = principal
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
            snapshot = self._sealer.seal(self._principal, task_id, command)
        except Exception as exc:
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.SNAPSHOT_REJECTED,
                detail=type(exc).__name__,
            )

        scope = C7VerificationScope(
            tenant_id=plan.commitment.tenant_id,
            workspace_id=plan.commitment.workspace_id,
            task_id=task_id,
            run_id=snapshot.reserved_run_id,
            capability_id=plan.capability_id,
        )
        try:
            receipt = self._c7_issuer.issue(task_id, scope.run_id, scope.capability_id)
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

        try:
            started = self._tasks.start_run(
                task_id,
                configuration_snapshot_id=snapshot.snapshot_id,
                provider_profile_id=snapshot.provider_profile.profile_id,
            )
        except AgentOSCoreError as exc:
            return SrlExecutionResult(
                committed=True,
                started=False,
                task_id=task_id,
                denial_reason=ExecutionDenialReason.START_REJECTED,
                detail=str(exc),
            )
        run = started.run
        return SrlExecutionResult(
            committed=True,
            started=True,
            task_id=task_id,
            run_id=run.run_id if run is not None else None,
        )

    @staticmethod
    def _plan_binds(aggregate, plan: SrlExecutionPlan) -> bool:
        goal = aggregate.goal
        commitment = plan.commitment
        workflow = plan.workflow
        if goal is None or commitment is None or workflow is None:
            return False
        return (
            commitment.task_id == aggregate.task_id
            and commitment.goal_id == goal.goal_id
            and commitment.tenant_id == goal.tenant_id
            and commitment.workspace_id == goal.workspace_id
            and workflow.tenant_id == goal.tenant_id
            and workflow.workspace_id == goal.workspace_id
            and plan.expected_outcome.task_id == aggregate.task_id
            and plan.expected_outcome.tenant_id == goal.tenant_id
            and plan.expected_outcome.workspace_id == goal.workspace_id
        )
