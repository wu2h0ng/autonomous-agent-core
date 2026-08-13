from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from agent_os_contracts import (
    OutcomeStatus,
    PersistentCommitment,
    PersistentCommitmentState,
    PrincipalIdentity,
    SelfDevelopmentWorkSpec,
    SettlementCommand,
    content_digest,
)

from .responsibility_loop import (
    ResponsibilityCycleState,
    ResponsibilityLoopBinding,
    ResponsibilityLoopStaleFence,
    SQLiteResponsibilityLoopStore,
)
from .self_development_organ import SelfDevelopmentOrganBlocked


class ResponsibilityControllerError(RuntimeError):
    """Fail-closed application error for one bounded responsibility cycle."""


class ResponsibilityControllerState(str, Enum):
    SETTLED = "SETTLED"
    WAITING_EVENT = "WAITING_EVENT"
    BLOCKED = "BLOCKED"


class ResponsibilityOrganRoute(str, Enum):
    ORDINARY_TASK = "ORDINARY_TASK"
    SELFDEV = "SELFDEV"


class ResponsibilityControllerBlockReason(str, Enum):
    SELFDEV_ROUTE_NOT_BOUND = "SELFDEV_ROUTE_NOT_BOUND"
    SELFDEV_WORKTREE_NOT_ISOLATED = "SELFDEV_WORKTREE_NOT_ISOLATED"
    SELFDEV_WORKTREE_SCOPE_MISMATCH = "SELFDEV_WORKTREE_SCOPE_MISMATCH"
    SELFDEV_GIT_IDENTITY_UNAVAILABLE = "SELFDEV_GIT_IDENTITY_UNAVAILABLE"
    SELFDEV_BRANCH_MISMATCH = "SELFDEV_BRANCH_MISMATCH"
    SELFDEV_HEAD_MISMATCH = "SELFDEV_HEAD_MISMATCH"
    SELFDEV_WORKTREE_DIRTY = "SELFDEV_WORKTREE_DIRTY"
    SELFDEV_TARGET_UNSAFE = "SELFDEV_TARGET_UNSAFE"
    SELFDEV_TARGET_TOO_LARGE = "SELFDEV_TARGET_TOO_LARGE"
    SELFDEV_SCOPE_DRIFT = "SELFDEV_SCOPE_DRIFT"
    SELFDEV_WORKFLOW_NOT_ADMITTED = "SELFDEV_WORKFLOW_NOT_ADMITTED"
    SELFDEV_AGENT_LOOP_NOT_BOUND = "SELFDEV_AGENT_LOOP_NOT_BOUND"
    SELFDEV_AGENT_LOOP_STOPPED = "SELFDEV_AGENT_LOOP_STOPPED"


class ResponsibilityProjectorPort(Protocol):
    def project(self, mandate_id: str, reader: PrincipalIdentity) -> Any: ...


class OutcomePortfolioPort(Protocol):
    def get_view(self, mandate_id: str, actor: PrincipalIdentity) -> Any: ...

    def settle(
        self,
        command: SettlementCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> Any: ...

    def request_missing_outcome_help(
        self,
        commitment_record_id: str,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> Any: ...

    def list_help_requests(
        self,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        include_resolved: bool = False,
    ) -> tuple[Any, ...]: ...


class TaskReaderPort(Protocol):
    def get_task(self, task_id: str) -> Any: ...

    def current_outcome(self, task_id: str) -> Any: ...


EffectExecutionPort = Callable[
    [str, str, Callable[[], Mapping[str, str]]],
    Any,
]
TaskExecutionPort = Callable[
    [str, Callable[[str], None], EffectExecutionPort],
    None,
]
SelfDevelopmentExecutionPort = Callable[
    [str, SelfDevelopmentWorkSpec, Callable[[str], None], EffectExecutionPort],
    None,
]
ResponsibilityRouteSelectorPort = Callable[
    [Any, PersistentCommitment],
    ResponsibilityOrganRoute,
]


@dataclass(frozen=True)
class ResponsibilityControllerResult:
    state: ResponsibilityControllerState
    mandate_id: str
    cycle_id: str | None
    link_id: str | None
    commitment_record_id: str | None
    task_id: str | None
    run_id: str | None
    settlement_id: str | None
    help_request_id: str | None
    cycle_receipt_digest: str | None
    hcw_receipt_digest: str | None
    checkpoint_digest: str
    organ_route: ResponsibilityOrganRoute | None = None
    block_reason: ResponsibilityControllerBlockReason | None = None


class ResponsibilityLoopController:
    """Coordinate canonical responsibility, execution, outcome and loop truth."""

    def __init__(
        self,
        *,
        responsibility_projector: ResponsibilityProjectorPort,
        portfolio_store: OutcomePortfolioPort,
        task_reader: TaskReaderPort,
        loop_store: SQLiteResponsibilityLoopStore,
        actor: PrincipalIdentity,
        execute_task: TaskExecutionPort,
        select_route: ResponsibilityRouteSelectorPort,
        hcw_evaluator_root_id: str,
        clock: Callable[[], datetime],
        execute_selfdev: SelfDevelopmentExecutionPort | None = None,
    ) -> None:
        self._responsibility_projector = responsibility_projector
        self._portfolio_store = portfolio_store
        self._tasks = task_reader
        self._loop = loop_store
        self._actor = actor
        self._execute_task = execute_task
        self._execute_selfdev = execute_selfdev
        self._select_route = select_route
        self._hcw_evaluator_root_id = hcw_evaluator_root_id
        self._clock = clock

    def _project_responsibility(
        self,
        binding: ResponsibilityLoopBinding,
        prior_checkpoint: Any | None,
    ) -> tuple[Any, PersistentCommitment, Any, Any | None] | None:
        responsibility = self._responsibility_projector.project(
            binding.mandate_id,
            self._actor,
        )
        portfolio = self._portfolio_store.get_view(
            binding.mandate_id,
            self._actor,
        )
        if (
            prior_checkpoint is not None
            and prior_checkpoint.active_commitment_record_id is not None
        ):
            matching_commitments = [
                commitment
                for commitment in portfolio.commitments
                if commitment.commitment_record_id
                == prior_checkpoint.active_commitment_record_id
            ]
            if len(matching_commitments) != 1:
                raise ResponsibilityControllerError(
                    "checkpoint commitment is missing or ambiguous"
                )
            commitment = matching_commitments[0]
            item = next(
                (
                    candidate
                    for candidate in responsibility.items
                    if candidate.link.task_id == commitment.task_id
                ),
                None,
            )
            if item is None:
                raise ResponsibilityControllerError(
                    "checkpoint responsibility link is no longer active"
                )
            matching_settlements = [
                settlement
                for settlement in portfolio.settlements
                if settlement.commitment_record_id
                == commitment.commitment_record_id
            ]
            if len(matching_settlements) > 1:
                raise ResponsibilityControllerError(
                    "checkpoint commitment has ambiguous settlements"
                )
            if (
                commitment.state is not PersistentCommitmentState.OPEN
                and len(matching_settlements) != 1
            ):
                raise ResponsibilityControllerError(
                    "closed checkpoint commitment lacks canonical settlement"
                )
            return (
                responsibility,
                commitment,
                item,
                matching_settlements[0] if matching_settlements else None,
            )
        open_commitments = sorted(
            (
                commitment
                for commitment in portfolio.commitments
                if commitment.state is PersistentCommitmentState.OPEN
            ),
            key=lambda item: (
                item.attached_at,
                item.commitment_record_id,
            ),
        )
        for commitment in open_commitments:
            item = next(
                (
                    candidate
                    for candidate in responsibility.items
                    if candidate.link.task_id == commitment.task_id
                ),
                None,
            )
            if item is not None:
                return responsibility, commitment, item, None
        return None

    def run_once(
        self,
        binding: ResponsibilityLoopBinding,
        *,
        process_instance_id: str,
    ) -> ResponsibilityControllerResult:
        if (
            self._actor.tenant_id != binding.tenant_id
            or self._actor.workspace_id != binding.workspace_id
        ):
            raise ResponsibilityControllerError(
                "controller actor is outside responsibility binding scope"
            )
        lease = self._loop.acquire_lease(
            binding,
            process_instance_id=process_instance_id,
            now=self._clock(),
        )
        checkpoint_digest: str | None = None
        try:
            prior_checkpoint = self._loop.latest_checkpoint(binding)
            projected = self._project_responsibility(
                binding,
                prior_checkpoint,
            )
            if projected is None:
                checkpoint = self._loop.write_checkpoint(
                    binding,
                    lease,
                    state=ResponsibilityCycleState.WAITING_EVENT,
                    active_task_id=None,
                    active_run_id=None,
                    last_event_sequence=(
                        prior_checkpoint.last_event_sequence
                        if prior_checkpoint is not None
                        else 0
                    ),
                    next_transition="PROJECT_RESPONSIBILITIES",
                    recorded_at=self._clock(),
                    expected_prior_digest=(
                        prior_checkpoint.checkpoint_digest
                        if prior_checkpoint is not None
                        else None
                    ),
                )
                return ResponsibilityControllerResult(
                    state=ResponsibilityControllerState.WAITING_EVENT,
                    mandate_id=binding.mandate_id,
                    cycle_id=None,
                    link_id=None,
                    commitment_record_id=None,
                    task_id=None,
                    run_id=None,
                    settlement_id=None,
                    help_request_id=None,
                    cycle_receipt_digest=None,
                    hcw_receipt_digest=None,
                    checkpoint_digest=checkpoint.checkpoint_digest,
                )
            responsibility, commitment, item, recovered_settlement = projected
            if item.commitment is None or item.expected_outcome is None:
                raise ResponsibilityControllerError(
                    "selected responsibility lacks commitment or expected outcome"
                )
            if (
                content_digest(item.commitment) != commitment.commitment_digest
                or content_digest(item.expected_outcome)
                != commitment.expected_outcome_digest
            ):
                raise ResponsibilityControllerError(
                    "selected responsibility digest does not match portfolio"
                )
            cycle_id = "responsibility-cycle:" + content_digest(
                {
                    "schema_version": "1.0",
                    "lease_scope_id": binding.lease_scope_id,
                    "mandate_id": binding.mandate_id,
                    "link_id": item.link.link_id,
                    "commitment_record_id": commitment.commitment_record_id,
                    "task_id": commitment.task_id,
                    "expected_outcome_digest": commitment.expected_outcome_digest,
                }
            )
            aggregate = self._tasks.get_task(commitment.task_id)
            organ_route = self._select_route(item, commitment)
            if organ_route is ResponsibilityOrganRoute.SELFDEV and (
                self._execute_selfdev is None or item.link.selfdev_spec is None
            ):
                blocked_checkpoint = self._loop.write_checkpoint(
                    binding,
                    lease,
                    state=ResponsibilityCycleState.BLOCKED,
                    active_cycle_id=cycle_id,
                    active_link_id=item.link.link_id,
                    active_commitment_record_id=commitment.commitment_record_id,
                    responsibility_projection_digest=responsibility.view_digest,
                    active_task_id=commitment.task_id,
                    active_run_id=(
                        aggregate.run.run_id
                        if aggregate.run is not None
                        else None
                    ),
                    last_event_sequence=max(
                        aggregate.sequence,
                        (
                            prior_checkpoint.last_event_sequence
                            if prior_checkpoint is not None
                            else 0
                        ),
                    ),
                    next_transition="BIND_SELFDEV_ORGAN",
                    recorded_at=self._clock(),
                    expected_prior_digest=(
                        prior_checkpoint.checkpoint_digest
                        if prior_checkpoint is not None
                        else None
                    ),
                )
                return ResponsibilityControllerResult(
                    state=ResponsibilityControllerState.BLOCKED,
                    mandate_id=binding.mandate_id,
                    cycle_id=cycle_id,
                    link_id=item.link.link_id,
                    commitment_record_id=commitment.commitment_record_id,
                    task_id=commitment.task_id,
                    run_id=(
                        aggregate.run.run_id
                        if aggregate.run is not None
                        else None
                    ),
                    settlement_id=None,
                    help_request_id=None,
                    cycle_receipt_digest=None,
                    hcw_receipt_digest=None,
                    checkpoint_digest=blocked_checkpoint.checkpoint_digest,
                    organ_route=organ_route,
                    block_reason=(
                        ResponsibilityControllerBlockReason.SELFDEV_ROUTE_NOT_BOUND
                    ),
                )
            active_run_id = (
                aggregate.run.run_id if aggregate.run is not None else None
            )
            if (
                prior_checkpoint is not None
                and prior_checkpoint.active_commitment_record_id
                == commitment.commitment_record_id
            ):
                if (
                    prior_checkpoint.active_cycle_id != cycle_id
                    or prior_checkpoint.active_link_id != item.link.link_id
                ):
                    raise ResponsibilityControllerError(
                        "restored responsibility identity drift"
                    )
                if prior_checkpoint.active_help_request_id is not None:
                    help_request = next(
                        (
                            candidate
                            for candidate in self._portfolio_store.list_help_requests(
                                binding.mandate_id,
                                self._actor,
                                include_resolved=True,
                            )
                            if candidate.help_request_id
                            == prior_checkpoint.active_help_request_id
                        ),
                        None,
                    )
                    if help_request is None:
                        raise ResponsibilityControllerError(
                            "checkpoint Help request is missing"
                        )
                    if help_request.response is None:
                        waiting_checkpoint = self._loop.write_checkpoint(
                            binding,
                            lease,
                            state=ResponsibilityCycleState.WAITING_EVENT,
                            active_cycle_id=cycle_id,
                            active_link_id=item.link.link_id,
                            active_commitment_record_id=(
                                commitment.commitment_record_id
                            ),
                            responsibility_projection_digest=(
                                responsibility.view_digest
                            ),
                            active_help_request_id=(
                                help_request.help_request_id
                            ),
                            active_task_id=commitment.task_id,
                            active_run_id=active_run_id,
                            last_event_sequence=max(
                                aggregate.sequence,
                                prior_checkpoint.last_event_sequence,
                            ),
                            next_transition="HELP_RESPONSE",
                            recorded_at=self._clock(),
                            expected_prior_digest=(
                                prior_checkpoint.checkpoint_digest
                            ),
                        )
                        return ResponsibilityControllerResult(
                            state=ResponsibilityControllerState.WAITING_EVENT,
                            mandate_id=binding.mandate_id,
                            cycle_id=cycle_id,
                            link_id=item.link.link_id,
                            commitment_record_id=(
                                commitment.commitment_record_id
                            ),
                            task_id=commitment.task_id,
                            run_id=active_run_id,
                            settlement_id=None,
                            help_request_id=help_request.help_request_id,
                            cycle_receipt_digest=None,
                            hcw_receipt_digest=None,
                            checkpoint_digest=(
                                waiting_checkpoint.checkpoint_digest
                            ),
                            organ_route=organ_route,
                        )
            checkpoint = self._loop.write_checkpoint(
                binding,
                lease,
                state=ResponsibilityCycleState.RUNNING,
                active_cycle_id=cycle_id,
                active_link_id=item.link.link_id,
                active_commitment_record_id=commitment.commitment_record_id,
                responsibility_projection_digest=responsibility.view_digest,
                active_task_id=commitment.task_id,
                active_run_id=active_run_id,
                last_event_sequence=max(
                    aggregate.sequence,
                    (
                        prior_checkpoint.last_event_sequence
                        if prior_checkpoint is not None
                        else 0
                    ),
                ),
                next_transition="EXECUTE_OR_SETTLE",
                recorded_at=self._clock(),
                expected_prior_digest=(
                    prior_checkpoint.checkpoint_digest
                    if prior_checkpoint is not None
                    else None
                ),
            )
            checkpoint_digest = checkpoint.checkpoint_digest

            def assert_current(_phase: str) -> None:
                self._loop.heartbeat_lease(
                    binding,
                    lease,
                    heartbeat_at=self._clock(),
                )

            def execute_effect(
                operation_slot: str,
                intent_digest: str,
                effect: Callable[[], Mapping[str, str]],
                *,
                reconcile_idempotent: bool = False,
            ) -> Any:
                return self._loop.execute_effect(
                    binding,
                    lease,
                    cycle_id=cycle_id,
                    task_id=commitment.task_id,
                    operation_slot=operation_slot,
                    intent_digest=intent_digest,
                    effect=effect,
                    executed_at=self._clock(),
                    reconcile_idempotent=reconcile_idempotent,
                )

            outcome = self._tasks.current_outcome(commitment.task_id)
            if outcome is None:
                if organ_route is ResponsibilityOrganRoute.SELFDEV:
                    assert self._execute_selfdev is not None
                    assert item.link.selfdev_spec is not None
                    try:
                        self._execute_selfdev(
                            commitment.task_id,
                            item.link.selfdev_spec,
                            assert_current,
                            execute_effect,
                        )
                    except SelfDevelopmentOrganBlocked as exc:
                        blocked_checkpoint = self._loop.write_checkpoint(
                            binding,
                            lease,
                            state=ResponsibilityCycleState.BLOCKED,
                            active_cycle_id=cycle_id,
                            active_link_id=item.link.link_id,
                            active_commitment_record_id=(
                                commitment.commitment_record_id
                            ),
                            responsibility_projection_digest=(
                                responsibility.view_digest
                            ),
                            active_task_id=commitment.task_id,
                            active_run_id=(
                                aggregate.run.run_id
                                if aggregate.run is not None
                                else None
                            ),
                            last_event_sequence=max(
                                aggregate.sequence,
                                checkpoint.last_event_sequence,
                            ),
                            next_transition=exc.code,
                            recorded_at=self._clock(),
                            expected_prior_digest=checkpoint_digest,
                        )
                        return ResponsibilityControllerResult(
                            state=ResponsibilityControllerState.BLOCKED,
                            mandate_id=binding.mandate_id,
                            cycle_id=cycle_id,
                            link_id=item.link.link_id,
                            commitment_record_id=(
                                commitment.commitment_record_id
                            ),
                            task_id=commitment.task_id,
                            run_id=(
                                aggregate.run.run_id
                                if aggregate.run is not None
                                else None
                            ),
                            settlement_id=None,
                            help_request_id=None,
                            cycle_receipt_digest=None,
                            hcw_receipt_digest=None,
                            checkpoint_digest=(
                                blocked_checkpoint.checkpoint_digest
                            ),
                            organ_route=organ_route,
                            block_reason=ResponsibilityControllerBlockReason(
                                exc.code
                            ),
                        )
                else:
                    self._execute_task(
                        commitment.task_id,
                        assert_current,
                        execute_effect,
                    )
                assert_current("after_task_execution")
                outcome = self._tasks.current_outcome(commitment.task_id)
            if outcome is None:
                help_request = self._portfolio_store.request_missing_outcome_help(
                    commitment.commitment_record_id,
                    binding.mandate_id,
                    self._actor,
                )
                aggregate = self._tasks.get_task(commitment.task_id)
                waiting_checkpoint = self._loop.write_checkpoint(
                    binding,
                    lease,
                    state=ResponsibilityCycleState.WAITING_EVENT,
                    active_cycle_id=cycle_id,
                    active_link_id=item.link.link_id,
                    active_commitment_record_id=commitment.commitment_record_id,
                    responsibility_projection_digest=responsibility.view_digest,
                    active_help_request_id=help_request.help_request_id,
                    active_task_id=commitment.task_id,
                    active_run_id=(
                        aggregate.run.run_id
                        if aggregate.run is not None
                        else None
                    ),
                    last_event_sequence=max(
                        aggregate.sequence,
                        checkpoint.last_event_sequence,
                    ),
                    next_transition="HELP_RESPONSE",
                    recorded_at=self._clock(),
                    expected_prior_digest=checkpoint_digest,
                )
                checkpoint_digest = waiting_checkpoint.checkpoint_digest
                return ResponsibilityControllerResult(
                    state=ResponsibilityControllerState.WAITING_EVENT,
                    mandate_id=binding.mandate_id,
                    cycle_id=cycle_id,
                    link_id=item.link.link_id,
                    commitment_record_id=commitment.commitment_record_id,
                    task_id=commitment.task_id,
                    run_id=(
                        aggregate.run.run_id
                        if aggregate.run is not None
                        else None
                    ),
                    settlement_id=None,
                    help_request_id=help_request.help_request_id,
                    cycle_receipt_digest=None,
                    hcw_receipt_digest=None,
                    checkpoint_digest=checkpoint_digest,
                    organ_route=organ_route,
                )
            settlement = recovered_settlement
            if settlement is None:
                settlement = self._portfolio_store.settle(
                    SettlementCommand(
                        commitment_record_id=commitment.commitment_record_id,
                        expected_outcome_digest=commitment.expected_outcome_digest,
                        observed_outcome_digest=content_digest(outcome),
                        observed_status=OutcomeStatus(outcome.status),
                    ),
                    binding.mandate_id,
                    self._actor,
                )
            elif (
                settlement.task_id != commitment.task_id
                or settlement.expected_outcome_digest
                != commitment.expected_outcome_digest
                or settlement.observed_outcome_digest != content_digest(outcome)
                or settlement.observed_status is not OutcomeStatus(outcome.status)
            ):
                raise ResponsibilityControllerError(
                    "recovered settlement does not match canonical Task outcome"
                )
            aggregate = self._tasks.get_task(commitment.task_id)
            if aggregate.run is None:
                raise ResponsibilityControllerError(
                    "settled responsibility has no canonical Run"
                )
            existing_cycle_receipt = self._loop.get_cycle_receipt(
                binding,
                cycle_id,
            )
            if existing_cycle_receipt is not None:
                if (
                    existing_cycle_receipt.task_id != commitment.task_id
                    or existing_cycle_receipt.run_id != aggregate.run.run_id
                ):
                    raise ResponsibilityControllerError(
                        "recovered cycle receipt does not match canonical Task/Run"
                    )
                self._loop.bind_cycle_settlement(
                    binding,
                    cycle_id=cycle_id,
                    task_id=commitment.task_id,
                    settlement_id=settlement.settlement_id,
                    expected_settlement_digest=settlement.record_digest,
                    cycle_receipt_digest=(
                        existing_cycle_receipt.receipt_digest
                    ),
                )
                hcw_receipt = self._loop.measure_hcw(
                    binding,
                    cycle_id=cycle_id,
                    evaluator_root_id=self._hcw_evaluator_root_id,
                    measured_at=self._clock(),
                )
                neutral_checkpoint = self._loop.write_checkpoint(
                    binding,
                    lease,
                    state=ResponsibilityCycleState.WAITING_EVENT,
                    active_task_id=None,
                    active_run_id=None,
                    last_event_sequence=aggregate.sequence,
                    next_transition="PROJECT_RESPONSIBILITIES",
                    recorded_at=self._clock(),
                    expected_prior_digest=checkpoint_digest,
                )
                return ResponsibilityControllerResult(
                    state=ResponsibilityControllerState.WAITING_EVENT,
                    mandate_id=binding.mandate_id,
                    cycle_id=None,
                    link_id=None,
                    commitment_record_id=None,
                    task_id=None,
                    run_id=None,
                    settlement_id=None,
                    help_request_id=None,
                    cycle_receipt_digest=None,
                    hcw_receipt_digest=hcw_receipt.receipt_digest,
                    checkpoint_digest=(
                        neutral_checkpoint.checkpoint_digest
                    ),
                    organ_route=organ_route,
                )
            final_checkpoint = self._loop.write_checkpoint(
                binding,
                lease,
                state=ResponsibilityCycleState.WAITING_EVENT,
                active_cycle_id=cycle_id,
                active_link_id=item.link.link_id,
                active_commitment_record_id=commitment.commitment_record_id,
                responsibility_projection_digest=responsibility.view_digest,
                active_task_id=commitment.task_id,
                active_run_id=aggregate.run.run_id,
                last_event_sequence=aggregate.sequence,
                next_transition="PROJECT_RESPONSIBILITIES",
                recorded_at=self._clock(),
                expected_prior_digest=checkpoint_digest,
            )
            checkpoint_digest = final_checkpoint.checkpoint_digest
            cycle_receipt = self._loop.seal_cycle_receipt(
                binding,
                lease,
                cycle_id=cycle_id,
                task_id=commitment.task_id,
                run_id=aggregate.run.run_id,
                checkpoint_digest=checkpoint_digest,
            )
            self._loop.bind_cycle_settlement(
                binding,
                cycle_id=cycle_id,
                task_id=commitment.task_id,
                settlement_id=settlement.settlement_id,
                expected_settlement_digest=settlement.record_digest,
                cycle_receipt_digest=cycle_receipt.receipt_digest,
            )
            hcw_receipt = self._loop.measure_hcw(
                binding,
                cycle_id=cycle_id,
                evaluator_root_id=self._hcw_evaluator_root_id,
                measured_at=self._clock(),
            )
            return ResponsibilityControllerResult(
                state=ResponsibilityControllerState.SETTLED,
                mandate_id=binding.mandate_id,
                cycle_id=cycle_id,
                link_id=item.link.link_id,
                commitment_record_id=commitment.commitment_record_id,
                task_id=commitment.task_id,
                run_id=aggregate.run.run_id,
                settlement_id=settlement.settlement_id,
                help_request_id=None,
                cycle_receipt_digest=cycle_receipt.receipt_digest,
                hcw_receipt_digest=hcw_receipt.receipt_digest,
                checkpoint_digest=checkpoint_digest,
                organ_route=organ_route,
            )
        finally:
            try:
                self._loop.release_lease(
                    binding,
                    lease,
                    released_at=self._clock(),
                )
            except ResponsibilityLoopStaleFence:
                # Cleanup cannot overwrite the original stale/UNKNOWN failure.
                # A later owner already controls the durable lease row.
                pass
