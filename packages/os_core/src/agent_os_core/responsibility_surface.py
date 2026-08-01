from __future__ import annotations

import hmac
import os
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    MandateWorkspaceRecord,
    NodeKind,
    OutcomePortfolioHelpGap,
    OutcomePortfolioHelpRespondCommand,
    OutcomePortfolio,
    PrincipalIdentity,
    PrincipalRole,
    RunStatus,
    SelfDevelopmentWorkSpec,
    SessionRef,
    SrlHelpResponse,
    TaskEventType,
    content_digest,
)

from .agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    ChatSession,
    NonInteractiveDenyGateway,
)
from .capability import CapabilityResult
from .mandate_terminal import load_attach_session, mandate_status
from .responsibility_controller import (
    ResponsibilityControllerState,
    ResponsibilityLoopController,
    ResponsibilityOrganRoute,
)
from .responsibility_loop import (
    HcwEvaluatorRoot,
    ResponsibilityCycleState,
    OperatorWorkEventKind,
    ResponsibilityLoopBinding,
    ResponsibilityLoopEffectUnknown,
    SQLiteResponsibilityLoopStore,
)
from .self_development_organ import (
    SelfDevelopmentAgentLoopState,
    SelfDevelopmentOrgan,
    SelfDevelopmentOrganBlocked,
)
from .task_configuration import TASK_CONFIGURATION_CAPABILITY

AGENT_WORK_HCW_ROOT = HcwEvaluatorRoot(
    evaluator_root_id="hcw-evaluator:agent-work:v1",
    measurement_policy_digest=content_digest(
        {
            "policy": "agent-work-hcw",
            "version": 1,
            "idle_cutoff_seconds": 60,
            "missing_active_time": "HCW_INSUFFICIENT_DATA",
        }
    ),
    capture_surface="agent-cli",
    idle_cutoff_seconds=60,
)


class ResponsibilitySurfaceError(RuntimeError):
    """Fail-closed error for the unique terminal Work surface."""


def _effect_custody_for(execute_effect):
    def effect_custody(
        operation_slot: str,
        intent_digest: str,
        effect,
    ) -> CapabilityResult:
        captured: list[CapabilityResult] = []

        def invoke_with_receipt() -> dict[str, str]:
            result = effect()
            captured.append(result)
            receipt = result.receipt
            return {
                "receipt_id": receipt.receipt_id,
                "resource_ref": (
                    f"{receipt.connector_id}:{receipt.idempotency_key}"
                ),
                "evidence_digest": content_digest(receipt),
            }

        effect_record = execute_effect(
            operation_slot,
            intent_digest,
            invoke_with_receipt,
            reconcile_idempotent=True,
        )
        if not captured:
            raise ResponsibilityLoopEffectUnknown(
                "responsibility effect is APPLIED without a Task receipt; "
                "reconciliation is required"
            )
        del effect_record
        return captured[0]

    return effect_custody


def _validate_selfdev_task(
    aggregate: Any,
    spec: SelfDevelopmentWorkSpec,
) -> None:
    workflow = aggregate.workflow
    if workflow is None:
        raise SelfDevelopmentOrganBlocked(
            "SELFDEV_WORKFLOW_NOT_ADMITTED",
            "SELFDEV requires a committed canonical workflow",
        )
    nodes = {node.node_id: node for node in workflow.nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in workflow.edges:
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1
    roots = [node_id for node_id, count in incoming.items() if count == 0]
    ordered = []
    current = roots[0] if len(roots) == 1 else None
    while current is not None:
        ordered.append(nodes[current])
        targets = outgoing[current]
        current = targets[0] if len(targets) == 1 else None
    signature = tuple((node.kind, node.capability) for node in ordered)
    if spec.edit_mode == "agent_loop_precise":
        if (
            aggregate.commitment is None
            or TASK_CONFIGURATION_CAPABILITY
            not in aggregate.commitment.authority_scopes
        ):
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKFLOW_NOT_ADMITTED",
                "precise SELFDEV requires authority to freeze its runtime binding",
            )
        expected = (
            (NodeKind.TRANSFORM, None),
            (NodeKind.TOOL, "workspace.run_tests"),
            (NodeKind.EVALUATION, None),
            (NodeKind.TERMINAL, None),
        )
        test_node = ordered[1] if len(ordered) == len(expected) else None
        if (
            signature != expected
            or len(workflow.edges) != len(expected) - 1
            or test_node is None
            or test_node.risk_tier != 0
            or test_node.idempotency.value != "idempotent"
        ):
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_WORKFLOW_NOT_ADMITTED",
                "precise SELFDEV workflow must be agent-loop-handoff-test-evaluate",
            )
        return
    expected = (
        (NodeKind.TOOL, "workspace.read"),
        (NodeKind.PROVIDER, "provider.chat"),
        (NodeKind.APPROVAL, None),
        (NodeKind.TOOL, "workspace.apply_patch"),
        (NodeKind.TOOL, "workspace.run_tests"),
        (NodeKind.EVALUATION, None),
        (NodeKind.TERMINAL, None),
    )
    patch_node = ordered[3] if len(ordered) == len(expected) else None
    if (
        signature != expected
        or len(workflow.edges) != len(expected) - 1
        or patch_node is None
        or patch_node.risk_tier != 2
        or patch_node.idempotency.value != "compensatable"
    ):
        raise SelfDevelopmentOrganBlocked(
            "SELFDEV_WORKFLOW_NOT_ADMITTED",
            "SELFDEV workflow must be read-provider-approval-single-patch-test-evaluate",
        )


@dataclass(frozen=True)
class ResponsibilitySurfaceContext:
    mandate_id: str
    binding: ResponsibilityLoopBinding
    loop_store: SQLiteResponsibilityLoopStore


@dataclass(frozen=True)
class ResponsibilityAuthorityContext:
    mandate_id: str
    binding: ResponsibilityLoopBinding
    portfolio: OutcomePortfolio


def resolve_agent_work_authority(
    *,
    database: Path,
    session: Any,
    bearer: str,
) -> PrincipalIdentity:
    """Resolve a credential-bound local authority from canonical portfolio truth."""
    if not bearer:
        raise ResponsibilitySurfaceError(
            "AGENT_OS_AUTHORITY_BEARER is required for Agent Work"
        )
    connection = sqlite3.connect(str(Path(database).resolve()))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM mandate_outcome_portfolios "
            "WHERE mandate_id=? AND tenant_id=? AND workspace_id=?",
            (
                session.mandate_id,
                session.tenant_id,
                session.workspace_id,
            ),
        ).fetchall()
    except sqlite3.Error:
        raise ResponsibilitySurfaceError(
            "canonical Outcome Portfolio is unavailable for authority resolution"
        ) from None
    finally:
        connection.close()
    if len(rows) != 1:
        raise ResponsibilitySurfaceError(
            "Agent Work requires one canonical Outcome Portfolio authority"
        )
    row = rows[0]
    try:
        portfolio = OutcomePortfolio.model_validate_json(str(row["payload"]))
    except Exception:
        raise ResponsibilitySurfaceError(
            "canonical Outcome Portfolio authority is malformed"
        ) from None
    payload = portfolio.model_dump(mode="json", exclude={"record_digest"})
    if (
        content_digest(payload) != portfolio.record_digest
        or portfolio.record_digest != str(row["record_digest"])
        or portfolio.portfolio_id != str(row["portfolio_id"])
        or portfolio.mandate_id != session.mandate_id
        or portfolio.tenant_id != session.tenant_id
        or portfolio.workspace_id != session.workspace_id
        or portfolio.principal_id != session.principal_id
        or portfolio.created_by == session.principal_id
        or portfolio.authority_credential_digest is None
    ):
        raise ResponsibilitySurfaceError(
            "canonical Outcome Portfolio authority binding is invalid"
        )
    presented_digest = content_digest(
        {"agent_work_authority_bearer": bearer}
    )
    if not hmac.compare_digest(
        presented_digest,
        portfolio.authority_credential_digest,
    ):
        raise ResponsibilitySurfaceError(
            "Agent Work authority bearer is invalid"
        )
    return PrincipalIdentity(
        principal_id=portfolio.created_by,
        tenant_id=portfolio.tenant_id,
        workspace_id=portfolio.workspace_id,
        role=PrincipalRole.TENANT_ADMIN,
        authenticated_at=datetime.now(timezone.utc),
    )


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


def resolve_responsibility_authority_context(
    *,
    app: Any,
    execution_app: Any | None = None,
    workspace: Path,
    database: Path,
    lease_ttl_seconds: int = 30,
) -> ResponsibilityAuthorityContext:
    workspace = Path(workspace).resolve()
    database = Path(database).resolve()
    session = load_attach_session(workspace)
    if Path(session.database).resolve() != database:
        raise ResponsibilitySurfaceError(
            "attached Mandate database does not match --database"
        )
    mandate_status(workspace=workspace, session=session)
    workspace_record = MandateWorkspaceRecord.model_validate(
        (
            execution_app.get_mandate_workspace_record(session.mandate_id)
            if execution_app is not None
            else app.mandate_workspace.get_for_authorization(
                session.mandate_id,
                app.principal,
            )
        )
    )
    owner_principal_id = workspace_record.mandate.principal_id
    execution = execution_app or app
    if (
        session.principal_id != owner_principal_id
        or app.principal.role is not PrincipalRole.TENANT_ADMIN
        or app.principal.principal_id == owner_principal_id
        or app.principal.tenant_id != session.tenant_id
        or app.principal.workspace_id != session.workspace_id
    ):
        raise ResponsibilitySurfaceError(
            "Agent Work requires an independent same-scope authority principal"
        )
    if execution_app is not None and (
        execution.principal.role is not PrincipalRole.PRINCIPAL
        or execution.principal.principal_id != owner_principal_id
        or execution.principal.tenant_id != session.tenant_id
        or execution.principal.workspace_id != session.workspace_id
    ):
        raise ResponsibilitySurfaceError(
            "execution principal does not match the canonical Mandate owner"
        )
    portfolio = app.mandate_outcome_portfolio_store.get_view(
        session.mandate_id,
        app.principal,
    )
    if portfolio.portfolio.created_by != app.principal.principal_id:
        raise ResponsibilitySurfaceError(
            "Agent Work authority does not match the canonical portfolio creator"
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
    return ResponsibilityAuthorityContext(
        mandate_id=session.mandate_id,
        binding=binding,
        portfolio=portfolio.portfolio,
    )


def build_responsibility_surface_context(
    *,
    app: Any,
    execution_app: Any | None = None,
    workspace: Path,
    database: Path,
    lease_ttl_seconds: int = 30,
) -> ResponsibilitySurfaceContext:
    authority = resolve_responsibility_authority_context(
        app=app,
        execution_app=execution_app,
        workspace=workspace,
        database=database,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    loop_store = SQLiteResponsibilityLoopStore(
        database,
        clock=lambda: datetime.now(timezone.utc),
    )
    loop_store.ensure_hcw_evaluator_root(AGENT_WORK_HCW_ROOT)
    return ResponsibilitySurfaceContext(
        mandate_id=authority.mandate_id,
        binding=authority.binding,
        loop_store=loop_store,
    )


def _result_payload(result: Any) -> dict[str, Any]:
    payload = asdict(result)
    payload["state"] = result.state.value
    payload["organ_route"] = (
        result.organ_route.value if result.organ_route is not None else None
    )
    payload["block_reason"] = (
        result.block_reason.value if result.block_reason is not None else None
    )
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

    def execute_task_with_inputs(
        task_id: str,
        task_inputs: dict[str, Any],
        assert_current,
        execute_effect,
    ) -> None:
        assert_current("before_existing_task")
        aggregate = execution_app.tasks.get_task(task_id)
        snapshot = aggregate.configuration_snapshot
        execution_app.run_task(
            task_id,
            task_inputs,
            configuration_snapshot_id=(
                snapshot.snapshot_id if snapshot is not None else None
            ),
            execution_fence=assert_current,
            effect_custody=_effect_custody_for(execute_effect),
        )
        assert_current("after_existing_task")

    def execute_task(task_id: str, assert_current, execute_effect) -> None:
        execute_task_with_inputs(
            task_id,
            inputs,
            assert_current,
            execute_effect,
        )

    def execute_agent_loop(
        task_id: str,
        spec: SelfDevelopmentWorkSpec,
        assert_current,
        execute_effect,
    ) -> SelfDevelopmentAgentLoopState:
        aggregate = execution_app.tasks.get_task(task_id)
        if aggregate.expected_outcome is None or aggregate.commitment is None:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_AGENT_LOOP_NOT_BOUND",
                "precise SELFDEV requires the existing committed Task contracts",
            )
        snapshot = aggregate.configuration_snapshot
        if snapshot is None or aggregate.run is None:
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_AGENT_LOOP_NOT_BOUND",
                "precise SELFDEV requires an existing snapshot-bound Run",
            )
        run = aggregate.run
        if (
            run.configuration_snapshot_id != snapshot.snapshot_id
            or run.configuration_snapshot_digest != snapshot.snapshot_digest
            or run.provider_profile_id != snapshot.provider_profile.profile_id
        ):
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_AGENT_LOOP_NOT_BOUND",
                "precise SELFDEV Run does not bind the exact Task configuration snapshot",
            )
        session = ChatSession(
            ref=SessionRef(
                session_id=f"session:selfdev:{task_id}",
                task_id=task_id,
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                workspace_id=run.workspace_id,
            ),
            envelope_id=f"envelope:selfdev:{run.run_id}",
            expected=aggregate.expected_outcome,
        )
        capabilities = (
            "workspace.read",
            "workspace.search",
            "workspace.edit",
        )
        grants = {
            capability_id: execution_app.grants[capability_id]
            for capability_id in capabilities
        }
        write_paths = "\n".join(
            f"- {path}" for path in spec.allowed_write_paths
        )
        acceptance = "\n".join(
            f"- {criterion}"
            for criterion in aggregate.commitment.acceptance_criteria
        )
        system_prompt = (
            "You are the internal Agent OS SELFDEV inspect/propose organ for one "
            "existing governed Task. Inspect with workspace.search/read, then make "
            "one exact workspace.edit tool call per provider response. Never use "
            "complete-file replacement, shell, commit, push, merge, main, release, "
            "approval, policy, evaluator or promotion operations. Each edit waits "
            "for an external exact-action decision. When the repository change is "
            "ready for the detached verifier, return a final response with no tools."
        )
        prompt = (
            f"Task: {aggregate.goal.statement if aggregate.goal else task_id}\n"
            f"Acceptance criteria:\n{acceptance}\n"
            f"Persisted allowed write paths:\n{write_paths}\n"
            f"Exact base HEAD: {spec.repository_head}\n"
            f"Verifier after handoff: {spec.verifier_command}"
        )
        loop = AgentLoop(
            tasks=execution_app.tasks,
            provider=execution_app.provider,
            provider_profile=execution_app.provider_profile,
            policy=execution_app.policy,
            correction=execution_app.correction,
            sandbox=execution_app.sandbox,
            grants=grants,
            principal=execution_app.principal,
            gateway=NonInteractiveDenyGateway(),
            config=AgentLoopConfig(
                stream=False,
                system_prompt=system_prompt,
            ),
            execution_fence=assert_current,
            effect_custody=_effect_custody_for(execute_effect),
            allowed_capability_ids=capabilities,
            durable_write_approval=True,
            allowed_write_paths=spec.allowed_write_paths,
        )
        events = execution_app.tasks._event_store.read(task_id)
        has_turn = any(
            event.event_type is TaskEventType.SESSION_TURN_STARTED
            and event.correlation_id == run.run_id
            for event in events
        )
        current = execution_app.tasks.get_task(task_id)
        if (
            current.run is not None
            and current.run.status is RunStatus.WAITING_APPROVAL
        ):
            if current.approval is None:
                return SelfDevelopmentAgentLoopState.WAITING_APPROVAL
            result = loop.resume_after_approval(session)
        elif has_turn:
            result = loop.continue_existing_turn(session)
        else:
            result = loop.run_turn(session, prompt)
        if result.stop_reason == "waiting_approval":
            return SelfDevelopmentAgentLoopState.WAITING_APPROVAL
        if result.stop_reason != "completed":
            raise SelfDevelopmentOrganBlocked(
                "SELFDEV_AGENT_LOOP_STOPPED",
                f"precise AgentLoop stopped with {result.stop_reason}",
            )
        return SelfDevelopmentAgentLoopState.COMPLETED

    def has_persisted_effects(task_id: str) -> bool:
        return context.loop_store.has_effects_for_task(
            context.binding,
            task_id,
        ) or any(
            event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
            and isinstance(event.decoded_payload().get("effect"), dict)
            for event in execution_app.tasks._event_store.read(task_id)
        )

    def fail_agent_loop(task_id: str, exc: BaseException, execute_effect) -> None:
        aggregate = execution_app.tasks.get_task(task_id)
        if aggregate.run is None:
            return
        if aggregate.run.status not in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.SUCCEEDED,
        }:
            execution_app.tasks.append_event(
                task_id,
                TaskEventType.NODE_FAILED,
                {
                    "node_id": aggregate.run.active_node_id or "selfdev-agent-loop",
                    "error": type(exc).__name__,
                },
                correlation_id=aggregate.run.run_id,
            )
            execution_app.tasks.update_run_status(
                task_id,
                RunStatus.FAILED,
                event_type=TaskEventType.RUN_FAILED,
                active_node_id=aggregate.run.active_node_id or "selfdev-agent-loop",
            )
        if has_persisted_effects(task_id):
            execution_app.compensate_task(
                task_id,
                effect_custody=_effect_custody_for(execute_effect),
            )

    selfdev_organ = SelfDevelopmentOrgan(
        workspace=workspace,
        execute_task=execute_task_with_inputs,
        validate_task=lambda task_id, spec: _validate_selfdev_task(
            execution_app.tasks.get_task(task_id), spec
        ),
        execute_agent_loop=execute_agent_loop,
        has_persisted_effects=has_persisted_effects,
        fail_agent_loop=fail_agent_loop,
    )

    controller = ResponsibilityLoopController(
        responsibility_projector=app.mandate_responsibility,
        portfolio_store=app.mandate_outcome_portfolio_store,
        task_reader=app.tasks,
        loop_store=context.loop_store,
        actor=app.principal,
        execute_task=execute_task,
        execute_selfdev=selfdev_organ,
        select_route=lambda item, _commitment: ResponsibilityOrganRoute(
            item.link.work_route.value
        ),
        hcw_evaluator_root_id=AGENT_WORK_HCW_ROOT.evaluator_root_id,
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
    execution_app: Any,
    workspace: Path,
    database: Path,
) -> dict[str, Any]:
    context = build_responsibility_surface_context(
        app=app,
        execution_app=execution_app,
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
        "runtime": context.loop_store.runtime_status(context.binding),
        "wake_capability": {
            "resident_watcher_active": False,
            "automatic_sources": [],
            "manual_resume_triggers": [
                "HELP_RESPONSE",
                "EXTERNAL_SIGNAL",
                "TYPED_OPERATOR_COMMAND",
            ],
        },
        "claim_ceiling": "MANDATE_SCOPED_READ_ONLY_STATUS / NOT_RELEASED",
    }


def answer_responsibility_help(
    *,
    app: Any,
    execution_app: Any,
    workspace: Path,
    database: Path,
    help_request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    context = build_responsibility_surface_context(
        app=app,
        execution_app=execution_app,
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
    matching_help = [
        candidate
        for candidate in app.mandate_outcome_portfolio_store.list_help_requests(
            context.mandate_id,
            app.principal,
        )
        if candidate.help_request_id == help_request_id
    ]
    if len(matching_help) != 1:
        raise ResponsibilitySurfaceError(
            "active Help request is missing or ambiguous"
        )
    help_request = matching_help[0]
    response_command = OutcomePortfolioHelpRespondCommand.model_validate(payload)
    SrlHelpResponse(
        help_request_id=help_request_id,
        responded_at=datetime.now(timezone.utc),
        responder_principal_id=app.principal.principal_id,
        response_kind=response_command.response_kind,
        decision=response_command.decision,
        notes=response_command.notes,
    )
    task_approval_recorded = False
    pending_task_decision: str | None = None
    if help_request.gap_kind is OutcomePortfolioHelpGap.PENDING_ACTION_APPROVAL:
        if help_request.task_id != checkpoint.active_task_id:
            raise ResponsibilitySurfaceError(
                "action approval Help does not match the active Task"
            )
        decision = payload.get("decision")
        aggregate = app.tasks.get_task(checkpoint.active_task_id)
        pending_action = app.tasks.pending_action(checkpoint.active_task_id)
        if (
            pending_action is None
            or help_request.pending_action_digest is None
            or pending_action.action_digest()
            != help_request.pending_action_digest
        ):
            raise ResponsibilitySurfaceError(
                "SELFDEV_APPROVAL_ACTION_DRIFT: Help no longer binds the pending action"
            )
        if decision in {"APPROVE", "REJECT"}:
            if aggregate.approval is not None and (
                aggregate.approval.actor_id != app.principal.principal_id
                or aggregate.approval.actor_role is not app.principal.role
                or app.principal.role is not PrincipalRole.TENANT_ADMIN
            ):
                raise ResponsibilitySurfaceError(
                    "SELFDEV_APPROVAL_AUTHORITY_INVALID: pending action has a "
                    "non-independent approval"
                )
            if (
                aggregate.approval is not None
                and aggregate.approval.disposition.value != decision
            ):
                raise ResponsibilitySurfaceError(
                    "SELFDEV_APPROVAL_DECISION_CONFLICT: Help decision contradicts "
                    "the durable Task approval"
                )
            if aggregate.approval is None:
                pending_task_decision = decision
            else:
                task_approval_recorded = True
        elif decision == "MORE_INFO" and aggregate.approval is not None:
            raise ResponsibilitySurfaceError(
                "SELFDEV_APPROVAL_DECISION_CONFLICT: MORE_INFO contradicts the "
                "durable Task approval"
            )
        elif decision != "MORE_INFO":
            raise ResponsibilitySurfaceError(
                "action approval Help requires APPROVE, REJECT or MORE_INFO"
            )
    if pending_task_decision is not None:
        app.record_approval(
            checkpoint.active_task_id,
            {
                "disposition": pending_task_decision,
                "action_digest": help_request.pending_action_digest,
                "reason": payload.get("notes")
                or "External Agent Work action decision",
            },
        )
        task_approval_recorded = True
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
        "task_approval_recorded": task_approval_recorded,
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
    ):
        raise ResponsibilitySurfaceError(
            "agent correct requires an active checkpointed Task"
        )
    current = execution_app.tasks.get_task(prior.active_task_id)
    active_run_id = (
        prior.active_run_id
        or (current.run.run_id if current.run is not None else None)
    )
    if active_run_id is None:
        raise ResponsibilitySurfaceError(
            "agent correct requires a canonical active Run"
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
            active_run_id=active_run_id,
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
            run_id=active_run_id,
            occurred_at=datetime.now(timezone.utc),
        )
        return {
            "entry": "agent correct",
            "mandate_id": context.mandate_id,
            "task_id": prior.active_task_id,
            "run_id": active_run_id,
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
