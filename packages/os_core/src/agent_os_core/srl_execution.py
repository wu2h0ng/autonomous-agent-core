from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
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


class PlanRegistrationDenialReason(str, Enum):
    """Enumerable fail-closed reasons for refusing a plan registration."""

    MISSING_REGISTRANT = "MISSING_REGISTRANT"
    TASK_UNAVAILABLE = "TASK_UNAVAILABLE"
    TASK_NOT_DRAFT = "TASK_NOT_DRAFT"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    DUPLICATE_PLAN = "DUPLICATE_PLAN"


class SrlExecutionPlanRegistrationError(AgentOSCoreError):
    """Raised when a registration would violate the trusted-plan boundary."""

    def __init__(self, reason: PlanRegistrationDenialReason, detail: str = "") -> None:
        self.reason = reason
        message = f"plan registration denied: {reason.value}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


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


class RegisteredSrlExecutionPlan(ContractModel):
    """A durable (plan, registrant) record read back from the plan store."""

    plan: SrlExecutionPlan
    registered_by: NonEmptyStr
    registered_at: datetime


class SrlExecutionPlanStore(Protocol):
    """Durable backing for the trusted plan registry (optional)."""

    def save(
        self,
        plan: SrlExecutionPlan,
        *,
        registered_by: str,
        registered_at: datetime,
    ) -> None: ...

    def exists(self, task_id: str) -> bool: ...

    def load_all(self) -> Iterable[RegisteredSrlExecutionPlan]: ...


class SQLiteSrlExecutionPlanStore:
    """SQLite-backed, restart-durable store for registered SRL execution plans."""

    def __init__(self, path: str | Path = ":memory:", *, uri: bool = False) -> None:
        self.path = str(path)
        self._uri = uri
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, uri=self._uri)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS srl_execution_plans (
              task_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              registered_by TEXT NOT NULL,
              registered_at TEXT NOT NULL,
              payload_json TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def exists(self, task_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM srl_execution_plans WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row is not None

    def save(
        self,
        plan: SrlExecutionPlan,
        *,
        registered_by: str,
        registered_at: datetime,
    ) -> None:
        payload = plan.model_dump(mode="json")
        with self._lock:
            self._db.execute(
                """
                INSERT INTO srl_execution_plans
                  (task_id, tenant_id, workspace_id, registered_by,
                   registered_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.task_id,
                    plan.commitment.tenant_id,
                    plan.commitment.workspace_id,
                    registered_by,
                    registered_at.isoformat(),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._db.commit()

    def load_all(self) -> list[RegisteredSrlExecutionPlan]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT payload_json, registered_by, registered_at
                FROM srl_execution_plans ORDER BY registered_at
                """
            ).fetchall()
        return [
            RegisteredSrlExecutionPlan(
                plan=SrlExecutionPlan.model_validate(json.loads(row["payload_json"])),
                registered_by=row["registered_by"],
                registered_at=datetime.fromisoformat(row["registered_at"]),
            )
            for row in rows
        ]


class SrlExecutionPlanRegistry:
    """Composition-root-owned, trusted plan source (never caller-injected).

    A trusted organ registers a plan for an already-activated SRL task; the bridge
    resolves it. There is no HTTP/CLI path that accepts a plan from a caller.

    Hardening (subagent N6/N7): registration binds an explicit registrant, refuses
    a second plan for the same task (no silent overwrite), and, when a durable
    store is supplied, survives a process restart by reloading registered plans.
    """

    def __init__(self, store: SrlExecutionPlanStore | None = None) -> None:
        self._store = store
        self._plans: dict[str, SrlExecutionPlan] = {}
        self._registrants: dict[str, str] = {}
        if store is not None:
            for record in store.load_all():
                self._plans[record.plan.task_id] = record.plan
                self._registrants[record.plan.task_id] = record.registered_by

    def register(
        self,
        plan: SrlExecutionPlan,
        *,
        registered_by: str,
        registered_at: datetime | None = None,
    ) -> None:
        if not registered_by:
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.MISSING_REGISTRANT
            )
        if plan.task_id in self._plans:
            raise SrlExecutionPlanRegistrationError(
                PlanRegistrationDenialReason.DUPLICATE_PLAN, plan.task_id
            )
        if self._store is not None:
            self._store.save(
                plan,
                registered_by=registered_by,
                registered_at=registered_at or datetime.now(timezone.utc),
            )
        self._plans[plan.task_id] = plan
        self._registrants[plan.task_id] = registered_by

    def resolve(self, task_id: str) -> SrlExecutionPlan | None:
        return self._plans.get(task_id)

    def registered_by(self, task_id: str) -> str | None:
        return self._registrants.get(task_id)


def plan_binds(aggregate: TaskAggregate, plan: SrlExecutionPlan, principal: PrincipalIdentity) -> bool:
    """True iff the trusted plan is coherently bound to the task and principal."""

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
        goal.tenant_id == principal.tenant_id
        and goal.workspace_id == principal.workspace_id
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
        *,
        additional_capability_ids: tuple[str, ...] = (),
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
        if not plan_binds(aggregate, plan, self._principal):
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

        # C7-guarded start via the configuration service. The service holds its
        # config->authority lock region and now guards the plan's tool capability
        # in the SAME region (additional_capability_ids), so a tool-capability
        # correction in the verify->start window still forbids the start - without
        # inverting the lock order (subagent F1 closed at the service level).
        try:
            started = self._snapshots.start_run(
                self._principal,
                task_id,
                snapshot.snapshot_id,
                additional_capability_ids=(plan.capability_id,),
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
