from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from agent_os_contracts import (
    OutcomeStatus,
    PersistentCommitment,
    PersistentCommitmentState,
    PrincipalIdentity,
    SettlementCommand,
    content_digest,
)

from .responsibility_loop import (
    ResponsibilityCycleState,
    ResponsibilityLoopBinding,
    SQLiteResponsibilityLoopStore,
)


class ResponsibilityControllerError(RuntimeError):
    """Fail-closed application error for one bounded responsibility cycle."""


class ResponsibilityControllerState(str, Enum):
    SETTLED = "SETTLED"
    WAITING_EVENT = "WAITING_EVENT"
    BLOCKED = "BLOCKED"


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


TaskExecutionPort = Callable[[str, Callable[[str], None]], None]


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
    checkpoint_digest: str


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
        clock: Callable[[], datetime],
    ) -> None:
        self._responsibility_projector = responsibility_projector
        self._portfolio_store = portfolio_store
        self._tasks = task_reader
        self._loop = loop_store
        self._actor = actor
        self._execute_task = execute_task
        self._clock = clock

    def _project_open_responsibility(
        self,
        binding: ResponsibilityLoopBinding,
    ) -> tuple[Any, PersistentCommitment, Any] | None:
        responsibility = self._responsibility_projector.project(
            binding.mandate_id,
            self._actor,
        )
        portfolio = self._portfolio_store.get_view(
            binding.mandate_id,
            self._actor,
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
                return responsibility, commitment, item
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
            projected = self._project_open_responsibility(binding)
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
                    checkpoint_digest=checkpoint.checkpoint_digest,
                )
            responsibility, commitment, item = projected
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
                    or prior_checkpoint.responsibility_projection_digest
                    != responsibility.view_digest
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
                            checkpoint_digest=(
                                waiting_checkpoint.checkpoint_digest
                            ),
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
                self._loop.assert_active_lease(binding, lease)

            outcome = self._tasks.current_outcome(commitment.task_id)
            if outcome is None:
                self._execute_task(commitment.task_id, assert_current)
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
                    checkpoint_digest=checkpoint_digest,
                )
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
            aggregate = self._tasks.get_task(commitment.task_id)
            if aggregate.run is None:
                raise ResponsibilityControllerError(
                    "settled responsibility has no canonical Run"
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
                checkpoint_digest=checkpoint_digest,
            )
        finally:
            self._loop.release_lease(
                binding,
                lease,
                released_at=self._clock(),
            )
