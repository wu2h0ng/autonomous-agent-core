from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDisposition,
    CapabilityGrant,
    CandidateGenerationEnvelope,
    CompensationMode,
    CompensationStatus,
    ExpectedOutcome,
    NodeKind,
    PolicyVerdict,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    ReceiptStatus,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    ObservedOutcome,
    OutcomeStatus,
    PatchCompensationRecord,
)

from .action_pipeline import ActionPipeline
from .capability import CapabilityBroker, WorkspaceSandbox
from .context_restorer import ContextRestorer
from .errors import (
    RunExecutionError,
    WorkerInterrupted,
)
from .governance import CorrectionReadPort, PolicyInput, PolicyKernel
from .graph_scheduler import GraphScheduler
from .node_handlers import NodeHandlerRegistry
from .outcome_pipeline import OutcomePipeline
from .proposal_engine import ProposalEngine
from .provider import ProviderPort
from .run_state import RunStateMachine
from .task_service import (
    TaskService,
    ValidatedTestReport,
    expected_outcome_contract_error,
)


def _strict_exit_code(output: object) -> int | None:
    if not isinstance(output, dict):
        return None
    value = output.get("exit_code")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _tool_arguments(capability_id: str, context: dict[str, Any]) -> dict[str, Any]:
    if capability_id == "workspace.read":
        path = context.get("target_path") or context.get("path")
        if not isinstance(path, str) or not path:
            raise RunExecutionError("workspace.read requires target_path")
        return {"path": path}
    if capability_id == "workspace.run_tests":
        command = (
            context.get("test_command")
            or context.get("command")
            or "python -m pytest"
        )
        return {"command": str(command)}
    explicit = context.get(capability_id)
    if isinstance(explicit, dict):
        return dict(explicit)
    raise RunExecutionError(
        f"no typed arguments available for {capability_id}"
    )


class DeterministicOutcomeEvaluator:
    """Evaluator consumes tool evidence, never provider narration."""

    def __init__(
        self,
        evidence_resolver: (
            Callable[[str, str], ValidatedTestReport | None] | None
        ) = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._evidence_resolver = evidence_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
        evidence_refs: tuple[str, ...],
        test_exit_code: int | None,
        now: datetime | None = None,
    ) -> ObservedOutcome:
        observed = now or self._clock()
        gaps: list[str] = []
        status: OutcomeStatus
        score: float | None = None

        if (
            task_id != expected.task_id
            or tenant_id != expected.tenant_id
            or workspace_id != expected.workspace_id
        ):
            status = OutcomeStatus.INVALID
            gaps.append("expected outcome scope mismatch")
        elif expected_outcome_contract_error(expected) == "unsupported evaluator":
            status = OutcomeStatus.INVALID
            gaps.append("unsupported evaluator")
        elif (
            expected_outcome_contract_error(expected)
            == "unsupported evidence requirements"
        ):
            status = OutcomeStatus.INVALID
            gaps.append("unsupported evidence requirements")
        elif expected_outcome_contract_error(expected) is not None:
            status = OutcomeStatus.INVALID
            gaps.append("unsupported failure semantics")
        elif observed < expected.frozen_at:
            status = OutcomeStatus.INVALID
            gaps.append("observation predates frozen contract")
        elif observed > expected.frozen_at + timedelta(
            seconds=expected.observation_window_seconds
        ):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("observation window expired")
        elif not any(ref.startswith("artifact:") for ref in evidence_refs):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("missing required evidence: test-report")
        elif self._evidence_resolver is None:
            status = OutcomeStatus.UNRESOLVED
            gaps.append("test-report evidence is not bound to the durable event chain")
        elif (
            report := self._evidence_resolver(task_id, run_id)
        ) is None or not set(report.artifact_ids).issubset(evidence_refs):
            status = OutcomeStatus.UNRESOLVED
            gaps.append("test-report evidence is not bound to the durable event chain")
        elif report.completed_at < expected.frozen_at:
            status = OutcomeStatus.INVALID
            gaps.append("test report predates frozen contract")
        elif test_exit_code is None:
            status = OutcomeStatus.UNRESOLVED
            gaps.append("missing pytest exit code")
        elif test_exit_code != report.exit_code:
            status = OutcomeStatus.INVALID
            gaps.append("pytest exit code does not match durable test report")
        else:
            score = 1.0 if report.exit_code == 0 else 0.0
            if report.exit_code != 0:
                status = OutcomeStatus.NOT_MET
                gaps.extend(expected.failure_semantics)
            elif score < expected.threshold:
                status = OutcomeStatus.NOT_MET
                gaps.append("frozen threshold not met")
            else:
                status = OutcomeStatus.VERIFIED

        return ObservedOutcome(
            observed_outcome_id=f"observed-{uuid4()}",
            expected_outcome_id=expected.expected_outcome_id,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluator_type=expected.evaluator_type,
            evaluator_version=expected.evaluator_version,
            status=status,
            score=score,
            confidence=1.0,
            evidence_refs=evidence_refs,
            unresolved_gaps=tuple(gaps),
            observed_at=observed,
        )


class RunCoordinator:
    """Single durable execution path shared by API, CLI and workspace adapters."""

    def __init__(
        self,
        task_service: TaskService,
        sandbox: WorkspaceSandbox,
        provider: ProviderPort,
        provider_profile: ProviderProfile,
        policy: PolicyKernel,
        correction: CorrectionReadPort,
        grant: CapabilityGrant | dict[str, CapabilityGrant],
        *,
        evaluator: DeterministicOutcomeEvaluator | None = None,
        compensation_grant: CapabilityGrant | None = None,
    ) -> None:
        self.tasks = task_service
        self.sandbox = sandbox
        self.tasks.bind_artifact_reader(sandbox.read_artifact_bytes)
        self.tasks.bind_correction_reader(correction)
        self.broker = CapabilityBroker(sandbox, correction)
        self.provider = provider
        self.provider_profile = provider_profile
        self.policy = policy
        self.correction = correction
        self.grant = grant
        self.compensation_grant = compensation_grant
        self.evaluator = evaluator or DeterministicOutcomeEvaluator(
            task_service.validated_test_report,
            clock=task_service.now,
        )
        self._actions = ActionPipeline(task_service, self.broker, policy, correction, grant)
        self._context = ContextRestorer(task_service._event_store.read)
        self._proposal = ProposalEngine(provider, provider_profile, correction, task_service)
        self._outcome = OutcomePipeline(self.evaluator, task_service)
        self._state = RunStateMachine(task_service)
        self._nodes = NodeHandlerRegistry()
        self._scheduler = GraphScheduler()

    def run(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        inputs: dict[str, Any] | None = None,
        *,
        stop_after_node: str | None = None,
        recover_stale_lease: bool = False,
    ):
        inputs = inputs or {}
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.workflow is None or aggregate.commitment is None or aggregate.expected_outcome is None:
            raise RunExecutionError("task is not committed and started")
        run = aggregate.run
        lease_fence, owner = self._state.acquire_lease(run.run_id, recover_stale_lease)
        aggregate = self.tasks.get_task(task_id)
        if (
            aggregate.run is None
            or aggregate.workflow is None
            or aggregate.commitment is None
            or aggregate.expected_outcome is None
        ):
            self._state.release_lease(run.run_id, owner)
            raise RunExecutionError("task bindings changed while acquiring the lease")
        run = aggregate.run
        if run.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            self._state.release_lease(run.run_id, owner)
            return aggregate
        waiting_result = self._state.check_waiting_event(task_id, run, aggregate)
        if waiting_result is not None:
            self._state.release_lease(run.run_id, owner)
            return waiting_result
        expiry_result = self._state.check_commitment_expiry(task_id, aggregate)
        if expiry_result is not None:
            self._state.release_lease(run.run_id, owner)
            return expiry_result
        try:
            aggregate = self._state.transition_to_running(task_id, run, lease_fence)
        except Exception:
            self._state.release_lease(run.run_id, owner)
            raise
        if (
            aggregate.run is None
            or aggregate.workflow is None
            or aggregate.commitment is None
            or aggregate.expected_outcome is None
        ):
            self._state.release_lease(run.run_id, owner)
            raise RunExecutionError("task bindings disappeared after lease binding")
        run = aggregate.run
        try:
            context = self._context.restore(task_id, inputs)
            for workflow_node in aggregate.workflow.nodes:
                restored_output = context.get(workflow_node.node_id)
                if workflow_node.capability and isinstance(restored_output, dict):
                    context[workflow_node.capability] = restored_output
            if aggregate.goal is not None:
                context.setdefault("goal", aggregate.goal.statement)
            completed_nodes = self._context.completed_nodes(task_id)
            restored_evidence = context.get("evidence_refs", ())
            evidence: list[str] = (
                [str(item) for item in restored_evidence]
                if isinstance(restored_evidence, (tuple, list))
                else []
            )
            test_exit_codes = {
                node.node_id: exit_code
                for node in aggregate.workflow.nodes
                if node.capability == "workspace.run_tests"
                and (exit_code := _strict_exit_code(context.get(node.node_id)))
                is not None
            }
            observed_outcome = aggregate.observed_outcome
            envelope = CandidateGenerationEnvelope(
                envelope_id=f"envelope-{uuid4()}", task_id=task_id, run_id=run.run_id,
                tenant_id=run.tenant_id, workspace_id=run.workspace_id,
                generator_id="developer-golden-path", generator_version="1",
                allowed_capability_ids=tuple(sorted(self.sandbox.specs())),
                resource_budget=aggregate.commitment.budget,
                candidate_ids=tuple(node.node_id for node in aggregate.workflow.nodes),
                has_abstain=True, has_ask=True, has_no_action=True, created_at=datetime.now(timezone.utc),
            )
            self.tasks.append_event(task_id, TaskEventType.CANDIDATES_GENERATED, {"envelope": envelope.model_dump(mode="json")}, correlation_id=run.run_id)
        except Exception:
            self._state.release_lease(run.run_id, owner)
            raise
        for node in self._scheduler.ordered_nodes(aggregate.workflow):
            if node.node_id in completed_nodes:
                continue
            try:
                self.tasks.append_event(task_id, TaskEventType.NODE_STARTED, {"node_id": node.node_id}, correlation_id=run.run_id)
            except Exception:
                self._state.release_lease(run.run_id, owner)
                raise
            try:
                if node.kind is NodeKind.PROVIDER:
                    provider_event_id = f"event:provider-response:{uuid4()}"
                    provider_output, provider_receipt = self._proposal.call(
                        run.run_id,
                        task_id,
                        node.capability or "provider",
                        node.node_id,
                        provider_event_id,
                        context,
                    )
                    context[node.node_id] = provider_output
                    if provider_receipt is None:
                        self.tasks.append_event(
                            task_id,
                            TaskEventType.PROVIDER_RESPONDED,
                            {
                                "node_id": node.node_id,
                                "provider_output": provider_output,
                            },
                            correlation_id=run.run_id,
                        )
                    for proposal in provider_output["tool_proposals"]:
                        capability_id = str(proposal["capability_id"])
                        arguments = json.loads(str(proposal["arguments_json"]))
                        context[capability_id] = arguments
                        target = next(
                            (
                                candidate
                                for candidate in aggregate.workflow.nodes
                                if candidate.kind is NodeKind.TOOL
                                and candidate.capability == capability_id
                            ),
                            None,
                        )
                        if target is not None:
                            action = self._actions.build_action(
                                task_id=task_id,
                                run_id=run.run_id,
                                node_id=target.node_id,
                                capability_id=capability_id,
                                principal=principal,
                                args=arguments,
                                expected=aggregate.expected_outcome,
                                envelope_id=envelope.envelope_id,
                                risk_tier=target.risk_tier,
                            )
                            context[f"action:{capability_id}"] = action
                            self.tasks.append_event(
                                task_id,
                                TaskEventType.ACTION_PROPOSED,
                                {"action": action.model_dump(mode="json")},
                                correlation_id=run.run_id,
                            )
                elif node.kind is NodeKind.TOOL:
                    capability_id = node.capability or ""
                    arguments = _tool_arguments(capability_id, context)
                    proposed = context.get(f"action:{capability_id}")
                    if capability_id == "workspace.apply_patch" and not isinstance(proposed, ActionContract):
                        raise RunExecutionError("workspace.apply_patch requires a provider-bound ActionContract")
                    action_was_proposed = isinstance(proposed, ActionContract)
                    action = proposed if action_was_proposed else self._actions.build_action(
                        task_id=task_id, run_id=run.run_id, node_id=node.node_id,
                        capability_id=capability_id, principal=principal, args=arguments,
                        expected=aggregate.expected_outcome, envelope_id=envelope.envelope_id,
                        risk_tier=node.risk_tier,
                    )
                    if action.node_id != node.node_id or action.capability_id != capability_id or json.loads(action.arguments_json) != arguments:
                        raise RunExecutionError("proposed action does not match the executable node")
                    if not action_was_proposed:
                        self._actions.record_action_proposed(action)
                    result = self._actions.execute(
                        action, principal,
                        capability_spec=self.sandbox.specs().get(capability_id),
                        approval=aggregate.approval,
                    )
                    context[node.node_id] = result.output
                    context[capability_id or node.node_id] = result.output
                    evidence.extend(str(item) for item in result.receipt.output_artifact_ids)
                    context["evidence_refs"] = tuple(evidence)
                    if node.capability == "workspace.run_tests":
                        exit_code = _strict_exit_code(result.output)
                        if exit_code is not None:
                            test_exit_codes[node.node_id] = exit_code
                elif node.kind is NodeKind.EVALUATION:
                    test_exit_code = next(
                        (code for code in test_exit_codes.values() if code != 0),
                        0 if test_exit_codes else None,
                    )
                    outcome = self._outcome.evaluate(
                        aggregate.expected_outcome, task_id=task_id, run_id=run.run_id,
                        tenant_id=run.tenant_id, workspace_id=run.workspace_id,
                        evidence=tuple(evidence), test_exit_code=test_exit_code,
                    )
                    self.tasks.record_outcome(task_id, outcome)
                    observed_outcome = outcome
                    context[node.node_id] = {
                        "status": outcome.status.value,
                        "score": outcome.score,
                    }
                elif node.kind in {NodeKind.TRANSFORM, NodeKind.DECISION}:
                    self._nodes.handle_simple(node, context=context)
                elif node.kind is NodeKind.APPROVAL:
                    proposed_actions = [
                        value
                        for key, value in context.items()
                        if key.startswith("action:")
                        and isinstance(value, ActionContract)
                    ]
                    action = next(
                        (
                            candidate
                            for candidate in proposed_actions
                            if aggregate.approval is not None
                            and aggregate.approval.action_digest
                            == candidate.action_digest()
                        ),
                        proposed_actions[-1] if proposed_actions else None,
                    )
                    approved = (
                        action is not None
                        and aggregate.approval is not None
                        and aggregate.approval.disposition is ApprovalDisposition.APPROVE
                        and aggregate.approval.action_digest == action.action_digest()
                    )
                    if approved and action is not None:
                        context["approved_action"] = action.action_digest()
                    else:
                        self.tasks.append_event(
                            task_id,
                            TaskEventType.APPROVAL_REQUESTED,
                            {
                                "node_id": node.node_id,
                                "action_digest": action.action_digest() if action else None,
                            },
                            correlation_id=run.run_id,
                        )
                        self.tasks.update_run_status(task_id, RunStatus.WAITING_APPROVAL, event_type=TaskEventType.APPROVAL_REQUESTED, active_node_id=node.node_id)
                        self._state.release_lease(run.run_id, owner)
                        return self.tasks.get_task(task_id)
                elif node.kind is NodeKind.WAIT_EVENT:
                    waiting = self.tasks.register_wait(task_id, node)
                    self._state.release_lease(run.run_id, owner)
                    return waiting
                elif node.kind in {NodeKind.LOOP, NodeKind.PARALLEL_MAP, NodeKind.SUBWORKFLOW}:
                    self._nodes.handle_simple(node, context=context)  # raises UnsupportedNodeError
                elif node.kind is NodeKind.TERMINAL:
                    self._nodes.handle_simple(node, context=context)
                output = context.get(node.node_id)
                payload: dict[str, Any] = {"node_id": node.node_id}
                if isinstance(output, dict):
                    payload["output"] = output
                self.tasks.append_event(task_id, TaskEventType.NODE_COMPLETED, payload, correlation_id=run.run_id)
                if stop_after_node == node.node_id:
                    raise WorkerInterrupted(f"worker interrupted after node {node.node_id}")
            except WorkerInterrupted:
                raise
            except Exception as exc:
                try:
                    self.tasks.append_event(task_id, TaskEventType.NODE_FAILED, {"node_id": node.node_id, "error": type(exc).__name__}, correlation_id=run.run_id)
                    self.tasks.update_run_status(task_id, RunStatus.FAILED, event_type=TaskEventType.RUN_FAILED, active_node_id=node.node_id)
                    self._attempt_automatic_compensation(
                        task_id,
                        principal,
                        held_lease_fence=lease_fence,
                    )
                finally:
                    self._state.release_lease(run.run_id, owner)
                raise RunExecutionError(
                    f"node {node.node_id} failed: {type(exc).__name__}: {exc}"
                ) from exc
        if observed_outcome is None:
            self._state.release_lease(run.run_id, owner)
            raise RunExecutionError("workflow completed without an evaluation node")
        try:
            observed_outcome = self._outcome.revalidate_before_finalization(
                task_id,
                observed_outcome,
            )
            self.tasks.update_run_status(
                task_id,
                RunStatus.SUCCEEDED
                if observed_outcome.status is OutcomeStatus.VERIFIED
                else RunStatus.FAILED,
                event_type=TaskEventType.RUN_SUCCEEDED
                if observed_outcome.status is OutcomeStatus.VERIFIED
                else TaskEventType.RUN_FAILED,
            )
            if observed_outcome.status is not OutcomeStatus.VERIFIED:
                self._attempt_automatic_compensation(
                    task_id,
                    principal,
                    held_lease_fence=lease_fence,
                )
        finally:
            self._state.release_lease(run.run_id, owner)
        return self.tasks.get_task(task_id)

    def compensate_task(
        self,
        task_id: str,
        principal: PrincipalIdentity,
    ):
        return self._compensate_with_mode(
            task_id,
            principal,
            mode=CompensationMode.MANUAL,
            held_lease_fence=None,
        )

    def _auto_compensate_task(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        held_lease_fence: int,
    ):
        return self._compensate_with_mode(
            task_id,
            principal,
            mode=CompensationMode.AUTOMATIC,
            held_lease_fence=held_lease_fence,
        )

    def _attempt_automatic_compensation(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        held_lease_fence: int,
    ) -> None:
        """Keep an already-persisted failure authoritative if rollback infrastructure fails."""

        try:
            self._auto_compensate_task(
                task_id,
                principal,
                held_lease_fence=held_lease_fence,
            )
        except Exception:
            # The original RUN_FAILED/NOT_MET is already durable. A broken event store
            # cannot reliably accept a second failure record, so never mask that truth.
            return

    def _compensate_with_mode(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        mode: CompensationMode,
        held_lease_fence: int | None,
    ):
        if mode is CompensationMode.MANUAL and principal.role not in {
            PrincipalRole.PRINCIPAL,
            PrincipalRole.TENANT_ADMIN,
        }:
            raise PermissionError(
                "manual compensation requires principal authority"
            )
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None:
            raise RunExecutionError("compensation requires an active run")
        current_outcome = self.tasks.current_outcome(task_id)
        currently_verified = (
            current_outcome is not None
            and current_outcome.status is OutcomeStatus.VERIFIED
        )
        stale_verified = (
            aggregate.observed_outcome is not None
            and aggregate.observed_outcome.status is OutcomeStatus.VERIFIED
            and not currently_verified
        )
        if aggregate.run.status is RunStatus.CANCELLED or (
            aggregate.run.status is RunStatus.SUCCEEDED and not stale_verified
        ) or currently_verified:
            raise RunExecutionError(
                "compensation cannot roll back a succeeded, cancelled, or verified run"
            )
        failure_context = (
            aggregate.run.status is RunStatus.FAILED
            or stale_verified
            or (
                current_outcome is not None
                and current_outcome.status
                in {OutcomeStatus.NOT_MET, OutcomeStatus.UNRESOLVED}
            )
            or any(
                record.status
                in {CompensationStatus.FAILED, CompensationStatus.BLOCKED}
                for record in aggregate.compensations
            )
        )
        if not failure_context:
            raise RunExecutionError(
                "compensation requires FAILED/NOT_MET or prior intervention context"
            )

        owner: str | None = None
        acquired_fence = held_lease_fence
        if mode is CompensationMode.MANUAL:
            acquire_lease = getattr(self.tasks._event_store, "acquire_lease", None)
            if acquire_lease is not None:
                owner = f"compensator:{uuid4()}"
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat()
                acquired_fence = acquire_lease(
                    aggregate.run.run_id,
                    owner,
                    expires_at,
                )
        elif acquired_fence is None:
            raise RunExecutionError(
                "automatic compensation requires the worker's held lease fence"
            )
        try:
            return self._compensate_task_locked(
                task_id,
                principal,
                mode=mode,
                lease_fence=acquired_fence,
            )
        finally:
            self._state.release_lease(aggregate.run.run_id, owner)

    def _compensate_task_locked(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        mode: CompensationMode,
        lease_fence: int | None,
    ):
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.workflow is None:
            raise RunExecutionError("compensation requires an active workflow run")
        run = aggregate.run
        events = self.tasks._event_store.read(task_id)
        actions_by_node: dict[str, ActionContract] = {}
        outputs_by_node: dict[str, dict[str, Any]] = {}
        completed_node_ids: set[str] = set()
        compensated_nodes: set[str] = set()
        for event in events:
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.ACTION_PROPOSED:
                value = payload.get("action")
                if isinstance(value, dict):
                    action = ActionContract.model_validate(value)
                    actions_by_node[action.node_id] = action
            elif event.event_type is TaskEventType.NODE_COMPLETED:
                node_id = payload.get("node_id")
                output = payload.get("output")
                if isinstance(node_id, str):
                    completed_node_ids.add(node_id)
                    if isinstance(output, dict):
                        outputs_by_node[node_id] = output
            elif event.event_type is TaskEventType.ACTION_COMPENSATED:
                value = payload.get("compensation")
                if isinstance(value, dict):
                    record = PatchCompensationRecord.model_validate(value)
                    compensated_nodes.add(record.node_id)

        candidates = [
            node
            for node in reversed(self._scheduler.ordered_nodes(aggregate.workflow))
            if node.capability == "workspace.apply_patch"
            and node.idempotency.value == "compensatable"
            and node.node_id in completed_node_ids
            and node.node_id not in compensated_nodes
        ]
        for node in candidates:
            original = actions_by_node.get(node.node_id)
            output = outputs_by_node.get(node.node_id, {})
            compensation_ref = output.get("compensation_ref")
            manifest_sha256 = output.get("manifest_sha256")
            path = output.get("path")
            attempt_id = f"compensation-{uuid4()}"
            if (
                original is None
                or not isinstance(compensation_ref, str)
                or not isinstance(manifest_sha256, str)
                or not isinstance(path, str)
            ):
                missing = PatchCompensationRecord(
                    compensation_id=attempt_id,
                    task_id=task_id,
                    run_id=run.run_id,
                    node_id=node.node_id,
                    original_action_id=(
                        original.action_id
                        if original is not None
                        else f"action:missing:{node.node_id}"
                    ),
                    mode=mode,
                    status=CompensationStatus.FAILED,
                    reason="durable compensation binding is missing",
                    manual_intervention_required=True,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    TaskEventType.COMPENSATION_FAILED,
                    missing,
                )
                break

            arguments = {
                "path": path,
                "original_action_key": original.idempotency_key,
                "compensation_ref": compensation_ref,
                "manifest_sha256": manifest_sha256,
            }
            compensation_action = ActionContract(
                action_id=f"action-{uuid4()}",
                task_id=task_id,
                run_id=run.run_id,
                node_id=node.node_id,
                principal_id=principal.principal_id,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                capability_id="workspace.compensate_patch",
                capability_version="1",
                arguments_json=json.dumps(arguments),
                risk_tier=1,
                idempotency_key=f"{run.run_id}:compensate:{node.node_id}",
                estimated_budget=ResourceBudget(
                    max_cost_usd=Decimal("0"),
                    max_duration_seconds=120,
                    max_provider_tokens=0,
                    max_tool_calls=1,
                ),
                policy_version=self.policy.policy_version,
                observed_correction_epochs=self.correction.snapshot(
                    task_id,
                    run.run_id,
                    "workspace.compensate_patch",
                ),
                expected_outcome_id=original.expected_outcome_id,
                candidate_envelope_id=original.candidate_envelope_id,
                created_at=self.tasks.now(),
            )
            record_kwargs = {
                "compensation_id": attempt_id,
                "task_id": task_id,
                "run_id": run.run_id,
                "node_id": node.node_id,
                "original_action_id": original.action_id,
                "compensation_action_id": compensation_action.action_id,
                "compensation_ref": compensation_ref,
                "manifest_sha256": manifest_sha256,
                "mode": mode,
            }
            if self.correction.halted(
                task_id,
                run.run_id,
                "workspace.compensate_patch",
            ) or self.correction.halted(
                task_id,
                run.run_id,
                original.capability_id,
            ):
                blocked = PatchCompensationRecord(
                    **record_kwargs,
                    status=CompensationStatus.BLOCKED,
                    reason="correction authority halted compensation",
                    manual_intervention_required=True,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    TaskEventType.COMPENSATION_BLOCKED,
                    blocked,
                )
                continue
            if self.compensation_grant is None:
                failed = PatchCompensationRecord(
                    **record_kwargs,
                    status=CompensationStatus.FAILED,
                    reason="internal compensation grant is unavailable",
                    manual_intervention_required=True,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    TaskEventType.COMPENSATION_FAILED,
                    failed,
                )
                continue

            started = PatchCompensationRecord(
                **record_kwargs,
                status=CompensationStatus.STARTED,
                reason="governed patch compensation started",
                manual_intervention_required=False,
                created_at=self.tasks.now(),
            )
            self._append_compensation_record(
                task_id,
                run.run_id,
                TaskEventType.COMPENSATION_STARTED,
                started,
            )
            try:
                capability = self.sandbox.specs(include_internal=True).get(
                    "workspace.compensate_patch"
                )
                self.tasks.append_event(
                    task_id,
                    TaskEventType.ACTION_PROPOSED,
                    {"action": compensation_action.model_dump(mode="json")},
                    correlation_id=run.run_id,
                )
                decision = self.policy.decide(
                    compensation_action,
                    PolicyInput(
                        principal=principal,
                        grant=self.compensation_grant,
                        capability=capability,
                    ),
                )
                self.tasks.append_event(
                    task_id,
                    TaskEventType.POLICY_DECIDED,
                    {"decision": decision.model_dump(mode="json")},
                    correlation_id=run.run_id,
                )
                if decision.verdict is not PolicyVerdict.ALLOW:
                    raise PermissionError(
                        f"policy denied compensation: {decision.reason_codes}"
                    )
                current = self.tasks.get_task(task_id)
                permit_fence = (
                    lease_fence
                    if lease_fence is not None
                    else (current.run.lease_fence if current.run is not None else 0)
                )
                permit = self.policy.permit(
                    compensation_action,
                    decision,
                    self.compensation_grant,
                    lease_fence=permit_fence,
                )
                current_fence = getattr(
                    self.tasks._event_store,
                    "lease_fence",
                    lambda _run_id: permit_fence,
                )(run.run_id)
                if current_fence != permit.lease_fence:
                    raise PermissionError("stale worker lease for compensation")
                if self.correction.halted(
                    task_id,
                    run.run_id,
                    original.capability_id,
                ):
                    raise PermissionError(
                        "original capability correction halted compensation"
                    )
                result = self.broker.invoke(compensation_action, permit)
                self.tasks._record_action_receipt(
                    task_id,
                    action=compensation_action,
                    decision=decision,
                    permit=permit,
                    receipt=result.receipt,
                    writer_token=self.tasks._runtime_writer_token,
                )
                if result.receipt.status is not ReceiptStatus.COMPENSATED:
                    raise RunExecutionError(
                        f"compensation failed: {result.receipt.error_code}"
                    )
                compensated = PatchCompensationRecord(
                    **record_kwargs,
                    status=CompensationStatus.COMPENSATED,
                    reason="governed patch compensation completed",
                    manual_intervention_required=False,
                    receipt_id=result.receipt.receipt_id,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    TaskEventType.ACTION_COMPENSATED,
                    compensated,
                )
            except Exception as exc:
                blocked_by_correction = self.correction.halted(
                    task_id,
                    run.run_id,
                    "workspace.compensate_patch",
                ) or self.correction.halted(
                    task_id,
                    run.run_id,
                    original.capability_id,
                )
                failed = PatchCompensationRecord(
                    **record_kwargs,
                    status=(
                        CompensationStatus.BLOCKED
                        if blocked_by_correction
                        else CompensationStatus.FAILED
                    ),
                    reason=f"compensation stopped: {type(exc).__name__}",
                    manual_intervention_required=True,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    (
                        TaskEventType.COMPENSATION_BLOCKED
                        if blocked_by_correction
                        else TaskEventType.COMPENSATION_FAILED
                    ),
                    failed,
                )
                break
        return self.tasks.get_task(task_id)

    def _append_compensation_record(
        self,
        task_id: str,
        run_id: str,
        event_type: TaskEventType,
        record: PatchCompensationRecord,
    ) -> None:
        self.tasks.append_event(
            task_id,
            event_type,
            {"compensation": record.model_dump(mode="json")},
            correlation_id=run_id,
        )
