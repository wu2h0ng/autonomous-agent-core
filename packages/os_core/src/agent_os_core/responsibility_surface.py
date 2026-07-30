from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    MandateWorkspaceRecord,
    content_digest,
)

from .mandate_terminal import load_attach_session, mandate_status
from .responsibility_controller import (
    ResponsibilityControllerState,
    ResponsibilityLoopController,
)
from .responsibility_loop import (
    ResponsibilityCycleState,
    OperatorWorkEventKind,
    ResponsibilityLoopBinding,
    SQLiteResponsibilityLoopStore,
)


class ResponsibilitySurfaceError(RuntimeError):
    """Fail-closed error for the unique terminal Work surface."""


@dataclass(frozen=True)
class ResponsibilitySurfaceContext:
    mandate_id: str
    binding: ResponsibilityLoopBinding
    loop_store: SQLiteResponsibilityLoopStore


def _repository_head(workspace: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or len(head) != 40:
        raise ResponsibilitySurfaceError(
            "agent Work requires a Git repository with an exact HEAD"
        )
    return head


def build_responsibility_surface_context(
    *,
    app: Any,
    execution_app: Any | None = None,
    workspace: Path,
    database: Path,
    lease_ttl_seconds: int = 30,
) -> ResponsibilitySurfaceContext:
    workspace = Path(workspace).resolve()
    database = Path(database).resolve()
    session = load_attach_session(workspace)
    if Path(session.database).resolve() != database:
        raise ResponsibilitySurfaceError(
            "attached Mandate database does not match --database"
        )
    mandate_status(workspace=workspace, session=session)
    workspace_record = MandateWorkspaceRecord.model_validate(
        app.get_mandate_workspace_record(session.mandate_id)
    )
    owner_principal_id = workspace_record.mandate.principal_id
    execution = execution_app or app
    if (
        session.principal_id != owner_principal_id
        or app.principal.principal_id != owner_principal_id
        or execution.principal.principal_id != owner_principal_id
        or app.principal.tenant_id != session.tenant_id
        or app.principal.workspace_id != session.workspace_id
        or execution.principal.tenant_id != session.tenant_id
        or execution.principal.workspace_id != session.workspace_id
    ):
        raise ResponsibilitySurfaceError(
            "terminal attach, canonical Mandate owner and application principal differ"
        )
    portfolio = app.mandate_outcome_portfolio_store.get_view(
        session.mandate_id,
        app.principal,
    )
    configuration_digest = content_digest(
        {
            "provider_profile": execution.provider_profile,
            "policy_version": execution.policy.policy_version,
            "grants": {
                capability_id: content_digest(
                    grant.model_dump(
                        mode="python",
                        exclude={"granted_at", "expires_at"},
                    )
                )
                for capability_id, grant in sorted(execution.grants.items())
            },
        }
    )
    binding = ResponsibilityLoopBinding(
        mandate_id=session.mandate_id,
        principal_id=owner_principal_id,
        tenant_id=session.tenant_id,
        workspace_id=session.workspace_id,
        repository_root=str(workspace),
        repository_head=_repository_head(workspace),
        correction_epoch=portfolio.portfolio.correction_epoch,
        configuration_digest=configuration_digest,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    return ResponsibilitySurfaceContext(
        mandate_id=session.mandate_id,
        binding=binding,
        loop_store=SQLiteResponsibilityLoopStore(
            database,
            clock=lambda: datetime.now(timezone.utc),
        ),
    )


def _result_payload(result: Any) -> dict[str, Any]:
    payload = asdict(result)
    payload["state"] = result.state.value
    return payload


def run_responsibility_work(
    *,
    app: Any,
    execution_app: Any,
    workspace: Path,
    database: Path,
    inputs: dict[str, Any],
    resume: bool,
    max_cycles: int = 16,
) -> dict[str, Any]:
    if max_cycles < 1:
        raise ResponsibilitySurfaceError("max_cycles must be positive")
    context = build_responsibility_surface_context(
        app=app,
        execution_app=execution_app,
        workspace=workspace,
        database=database,
    )
    prior = context.loop_store.latest_checkpoint(context.binding)
    if resume and prior is None:
        raise ResponsibilitySurfaceError(
            "agent resume requires an existing responsibility checkpoint"
        )

    def execute_task(task_id: str, assert_current) -> None:
        assert_current("before_existing_task")
        execution_app.run_task(
            task_id,
            inputs,
            execution_fence=assert_current,
        )
        assert_current("after_existing_task")

    controller = ResponsibilityLoopController(
        responsibility_projector=app.mandate_responsibility,
        portfolio_store=app.mandate_outcome_portfolio_store,
        task_reader=app.tasks,
        loop_store=context.loop_store,
        actor=app.principal,
        execute_task=execute_task,
        clock=lambda: datetime.now(timezone.utc),
    )
    results: list[dict[str, Any]] = []
    process_prefix = f"agent-work:{os.getpid()}:{uuid4().hex}"
    for index in range(max_cycles):
        result = controller.run_once(
            context.binding,
            process_instance_id=f"{process_prefix}:{index}",
        )
        results.append(_result_payload(result))
        if result.state is not ResponsibilityControllerState.SETTLED:
            break
    else:
        raise ResponsibilitySurfaceError(
            "responsibility cycle budget exhausted before a wait state"
        )
    return {
        "entry": "agent resume" if resume else "agent run",
        "mandate_id": context.mandate_id,
        "cycles": results,
        "terminal_state": results[-1]["state"],
        "claim_ceiling": (
            "BOUNDED_LOCAL_RESPONSIBILITY_LOOP / NOT_RELEASED / "
            "NO_AUTONOMY_OR_HCW_REDUCTION_CLAIM"
        ),
    }


def responsibility_status_payload(
    *,
    app: Any,
    workspace: Path,
    database: Path,
) -> dict[str, Any]:
    context = build_responsibility_surface_context(
        app=app,
        workspace=workspace,
        database=database,
    )
    checkpoint = context.loop_store.latest_checkpoint(context.binding)
    responsibility = app.mandate_responsibility.project(
        context.mandate_id,
        app.principal,
    )
    portfolio = app.mandate_outcome_portfolio_store.get_view(
        context.mandate_id,
        app.principal,
        include_resolved_help=True,
    )
    return {
        "entry": "agent status",
        "mandate_id": context.mandate_id,
        "responsibility": responsibility.model_dump(mode="json"),
        "portfolio": portfolio.model_dump(mode="json"),
        "checkpoint": asdict(checkpoint) if checkpoint is not None else None,
        "claim_ceiling": "MANDATE_SCOPED_READ_ONLY_STATUS / NOT_RELEASED",
    }


def answer_responsibility_help(
    *,
    app: Any,
    workspace: Path,
    database: Path,
    help_request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    context = build_responsibility_surface_context(
        app=app,
        workspace=workspace,
        database=database,
    )
    checkpoint = context.loop_store.latest_checkpoint(context.binding)
    if (
        checkpoint is None
        or checkpoint.active_cycle_id is None
        or checkpoint.active_help_request_id != help_request_id
    ):
        raise ResponsibilitySurfaceError(
            "Help response does not match the active responsibility checkpoint"
        )
    response = app.respond_outcome_portfolio_help_request(
        context.mandate_id,
        help_request_id,
        payload,
    )
    event_id = "operator-help-response:" + content_digest(response)
    context.loop_store.append_operator_work_event(
        context.binding,
        event_id=event_id,
        kind=OperatorWorkEventKind.HELP_RESPONSE,
        cycle_id=checkpoint.active_cycle_id,
        task_id=checkpoint.active_task_id,
        run_id=checkpoint.active_run_id,
        occurred_at=datetime.now(timezone.utc),
    )
    return {
        "entry": "agent answer",
        "mandate_id": context.mandate_id,
        "help_request": response,
        "operator_event_id": event_id,
        "authority_granted": False,
    }


def correct_responsibility_work(
    *,
    app: Any,
    execution_app: Any,
    workspace: Path,
    database: Path,
    reason: str,
) -> dict[str, Any]:
    context = build_responsibility_surface_context(
        app=app,
        execution_app=execution_app,
        workspace=workspace,
        database=database,
    )
    prior = context.loop_store.latest_checkpoint(context.binding)
    if (
        prior is None
        or prior.active_cycle_id is None
        or prior.active_task_id is None
        or prior.active_run_id is None
    ):
        raise ResponsibilitySurfaceError(
            "agent correct requires an active checkpointed Task/Run"
        )
    lease = context.loop_store.acquire_lease(
        context.binding,
        process_instance_id=f"agent-correct:{os.getpid()}:{uuid4().hex}",
        now=datetime.now(timezone.utc),
    )
    try:
        aggregate = execution_app.correct_task(prior.active_task_id, reason)
        stopped = context.loop_store.write_checkpoint(
            context.binding,
            lease,
            state=ResponsibilityCycleState.STOPPED,
            active_cycle_id=prior.active_cycle_id,
            active_link_id=prior.active_link_id,
            active_commitment_record_id=prior.active_commitment_record_id,
            responsibility_projection_digest=(
                prior.responsibility_projection_digest
            ),
            active_help_request_id=prior.active_help_request_id,
            active_task_id=prior.active_task_id,
            active_run_id=prior.active_run_id,
            last_event_sequence=max(
                prior.last_event_sequence,
                aggregate.sequence,
            ),
            next_transition="EXTERNAL_CORRECTION",
            recorded_at=datetime.now(timezone.utc),
            expected_prior_digest=prior.checkpoint_digest,
        )
        event_id = "operator-correction:" + content_digest(
            {
                "checkpoint_digest": stopped.checkpoint_digest,
                "reason": reason,
            }
        )
        context.loop_store.append_operator_work_event(
            context.binding,
            event_id=event_id,
            kind=OperatorWorkEventKind.CORRECTION,
            cycle_id=prior.active_cycle_id,
            task_id=prior.active_task_id,
            run_id=prior.active_run_id,
            occurred_at=datetime.now(timezone.utc),
        )
        return {
            "entry": "agent correct",
            "mandate_id": context.mandate_id,
            "task_id": prior.active_task_id,
            "run_id": prior.active_run_id,
            "checkpoint_digest": stopped.checkpoint_digest,
            "operator_event_id": event_id,
            "state": ResponsibilityCycleState.STOPPED.value,
        }
    finally:
        context.loop_store.release_lease(
            context.binding,
            lease,
            released_at=datetime.now(timezone.utc),
        )
