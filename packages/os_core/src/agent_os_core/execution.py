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
    BindingStatus,
    CapabilityGrant,
    CandidateGenerationEnvelope,
    CompensationMode,
    CompensationStatus,
    ExpectedOutcome,
    NodeKind,
    PolicyVerdict,
    PrincipalIdentity,
    PrincipalRole,
    ProviderExecutionReceipt,
    ProviderProfile,
    ProviderFailure,
    ReceiptStatus,
    ResourceBudget,
    RunPlanRebound,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
    ObservedOutcome,
    OutcomeStatus,
    PatchCompensationRecord,
    WorkingSetRef,
    content_digest,
    provider_execution_receipt_digest,
)

from .capability import (
    CapabilityBroker,
    CapabilityEffectUnknown,
    CapabilityPort,
    CapabilityResult,
    CollaborationPreflightPort,
)
from ._action_outcome import ExecutionLease
from .action_pipeline import ActionPipeline
from .errors import (
    ConcurrentWriteError,
    RunExecutionError,
    UnsupportedNodeError,
    WorkerInterrupted,
)
from .execution_profile import ExecutionProfileError, ExecutionProfilePort
from .governance import CorrectionReadPort, PolicyInput, PolicyKernel
from .outcome_evaluators import (
    OutcomeEvaluatorRegistry,
    PytestOutcomeEvaluator,
    default_registry,
)
from .provider import ProviderPort
from .task_service import (
    TaskService,
    ValidatedTestReport,
)

EffectCustodyPort = Callable[
    [str, str, Callable[[], CapabilityResult]],
    CapabilityResult,
]


def _strict_exit_code(output: object) -> int | None:
    if not isinstance(output, dict):
        return None
    value = output.get("exit_code")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value

class DeterministicOutcomeEvaluator:
    """Facade over an OutcomeEvaluatorRegistry.

    Preserves the legacy constructor signature (evidence_resolver + clock)
    and delegates to registered evaluators by expected.evaluator_type.
    The pytest evaluator is registered by default.
    """

    def __init__(
        self,
        evidence_resolver: (
            Callable[[str, str], ValidatedTestReport | None] | None
        ) = None,
        *,
        clock: Callable[[], datetime] | None = None,
        registry: OutcomeEvaluatorRegistry | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if registry is not None:
            self._registry = registry
            existing = registry.get(PytestOutcomeEvaluator.evaluator_type)
            if existing is None or (
                isinstance(existing, PytestOutcomeEvaluator)
                and existing.evidence_resolver is None
            ):
                registry.register(
                    PytestOutcomeEvaluator(evidence_resolver=evidence_resolver)
                )
        else:
            self._registry = default_registry(evidence_resolver=evidence_resolver)

    @property
    def registry(self) -> OutcomeEvaluatorRegistry:
        return self._registry

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
        return self._registry.evaluate(
            expected,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evidence_refs=evidence_refs,
            test_exit_code=test_exit_code,
            now=observed,
        )


class RunCoordinator:
    """Single durable execution path shared by API, CLI and workspace adapters."""

    def __init__(
        self,
        task_service: TaskService,
        capabilities: CapabilityPort,
        execution_profile: ExecutionProfilePort,
        provider: ProviderPort,
        provider_profile: ProviderProfile,
        policy: PolicyKernel,
        correction: CorrectionReadPort,
        grant: CapabilityGrant | dict[str, CapabilityGrant],
        *,
        evaluator: DeterministicOutcomeEvaluator | None = None,
        compensation_grant: CapabilityGrant | None = None,
        collaboration_preflight: CollaborationPreflightPort | None = None,
    ) -> None:
        self.tasks = task_service
        self.capabilities = capabilities
        self.execution_profile = execution_profile
        self.tasks.bind_correction_reader(correction)
        self.broker = CapabilityBroker(
            capabilities, correction, collaboration_preflight=collaboration_preflight
        )
        self.actions = ActionPipeline(
            task_service,
            self.broker,
            policy,
            correction,
            grant,
        )
        self.provider = provider
        self.provider_profile = provider_profile
        self.policy = policy
        self.correction = correction
        self.grant = grant
        self.compensation_grant = compensation_grant
        self.evaluator = evaluator or DeterministicOutcomeEvaluator(
            task_service.validated_test_report,
            clock=task_service.now,
            registry=task_service.evaluator_registry,
        )

    def run(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        inputs: dict[str, Any] | None = None,
        *,
        stop_after_node: str | None = None,
        recover_stale_lease: bool = False,
        execution_fence: Callable[[str], None] | None = None,
        effect_custody: EffectCustodyPort | None = None,
    ):
        def assert_execution_fence(phase: str) -> None:
            if execution_fence is not None:
                execution_fence(phase)

        inputs = inputs or {}
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.workflow is None or aggregate.commitment is None or aggregate.expected_outcome is None:
            raise RunExecutionError("task is not committed and started")
        run = aggregate.run
        assert_execution_fence("before_run_execution")
        lease_fence = 0
        owner: str | None = None
        expiry: str | None = None
        acquire_lease = getattr(self.tasks._event_store, "acquire_lease", None)
        if acquire_lease is not None:
            owner = f"worker:{uuid4()}"
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            try:
                lease_fence = acquire_lease(run.run_id, owner, expiry)
            except ConcurrentWriteError:
                if not recover_stale_lease:
                    raise
                recover = getattr(self.tasks._event_store, "recover_lease", None)
                if recover is None:
                    raise
                lease_fence = recover(run.run_id, owner, expiry)
        aggregate = self.tasks.get_task(task_id)
        if (
            aggregate.run is None
            or aggregate.workflow is None
            or aggregate.commitment is None
            or aggregate.expected_outcome is None
        ):
            self._release_lease(run.run_id, owner)
            raise RunExecutionError("task bindings changed while acquiring the lease")
        run = aggregate.run
        if run.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
            self._release_lease(run.run_id, owner)
            return aggregate
        if run.status is RunStatus.WAITING_EVENT:
            condition = run.wait_condition
            if condition is None:
                self._release_lease(run.run_id, owner)
                raise RunExecutionError(
                    "WAITING_EVENT run is missing its durable wait condition"
                )
            try:
                now = self.tasks.now()
                if now >= aggregate.commitment.expires_at:
                    return self.tasks.expire_commitment(task_id)
                if now >= condition.deadline:
                    return self.tasks.expire_wait(task_id)
                return self.tasks.get_task(task_id)
            except ConcurrentWriteError:
                return self.tasks.get_task(task_id)
            finally:
                self._release_lease(run.run_id, owner)
        if self.tasks.now() >= aggregate.commitment.expires_at:
            try:
                return self.tasks.expire_commitment(task_id)
            finally:
                self._release_lease(run.run_id, owner)
        resume_states = {
            RunStatus.WAITING_APPROVAL,
            RunStatus.PAUSED,
            RunStatus.FAILED,
        }
        try:
            aggregate = self.tasks.update_run_status(
                task_id,
                RunStatus.RUNNING,
                event_type=(
                    TaskEventType.RUN_RESUMED
                    if run.status in resume_states
                    else TaskEventType.RUN_QUEUED
                ),
                lease_fence=lease_fence,
            )
        except Exception:
            self._release_lease(run.run_id, owner)
            raise
        if (
            aggregate.run is None
            or aggregate.workflow is None
            or aggregate.commitment is None
            or aggregate.expected_outcome is None
        ):
            self._release_lease(run.run_id, owner)
            raise RunExecutionError("task bindings disappeared after lease binding")
        run = aggregate.run
        try:
            context = self._restore_context(task_id, inputs)
            for workflow_node in aggregate.workflow.nodes:
                restored_output = context.get(workflow_node.node_id)
                if workflow_node.capability and isinstance(restored_output, dict):
                    context[workflow_node.capability] = restored_output
            if aggregate.goal is not None:
                context.setdefault("goal", aggregate.goal.statement)
            if aggregate.commitment is not None:
                context.setdefault(
                    "acceptance_criteria",
                    "\n".join(
                        f"- {criterion}"
                        for criterion in aggregate.commitment.acceptance_criteria
                    ),
                )
            completed_nodes = self._completed_nodes(task_id)
            restored_evidence = context.get("evidence_refs", ())
            evidence: list[str] = (
                [str(item) for item in restored_evidence]
                if isinstance(restored_evidence, (tuple, list))
                else []
            )
            test_exit_codes: dict[str, int] = {}
            for test_node in aggregate.workflow.nodes:
                if test_node.capability != "workspace.run_tests":
                    continue
                try:
                    restored_exit_code = self.execution_profile.verification_exit_code(
                        {"workspace.run_tests": context.get(test_node.node_id)}
                    )
                except ExecutionProfileError as exc:
                    raise RunExecutionError(str(exc)) from exc
                if restored_exit_code is not None:
                    test_exit_codes[test_node.node_id] = restored_exit_code
            observed_outcome = aggregate.observed_outcome
            envelope = CandidateGenerationEnvelope(
                envelope_id=f"envelope-{uuid4()}", task_id=task_id, run_id=run.run_id,
                tenant_id=run.tenant_id, workspace_id=run.workspace_id,
                generator_id=self.execution_profile.generator_id,
                generator_version=self.execution_profile.generator_version,
                allowed_capability_ids=tuple(sorted(self.capabilities.specs())),
                resource_budget=aggregate.commitment.budget,
                candidate_ids=tuple(node.node_id for node in aggregate.workflow.nodes),
                has_abstain=True, has_ask=True, has_no_action=True, created_at=datetime.now(timezone.utc),
            )
            self.tasks.append_event(task_id, TaskEventType.CANDIDATES_GENERATED, {"envelope": envelope.model_dump(mode="json")}, correlation_id=run.run_id)
        except Exception:
            self._release_lease(run.run_id, owner)
            raise
        for node in self._ordered_nodes(aggregate.workflow):
            if node.node_id in completed_nodes:
                continue
            assert_execution_fence(f"before_node:{node.node_id}")
            try:
                self.tasks.append_event(task_id, TaskEventType.NODE_STARTED, {"node_id": node.node_id}, correlation_id=run.run_id)
            except Exception:
                self._release_lease(run.run_id, owner)
                raise
            try:
                if node.kind is NodeKind.PROVIDER:
                    provider_event_id = f"event:provider-response:{uuid4()}"
                    provider_output, provider_receipt = self._call_provider(
                        run.run_id,
                        task_id,
                        node.capability or "provider",
                        node.node_id,
                        provider_event_id,
                        context,
                        execution_fence=execution_fence,
                    )
                    assert_execution_fence("before_provider_projection")
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
                            action = self._build_action(
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
                    try:
                        arguments = self.execution_profile.tool_arguments(
                            node.capability or "",
                            context,
                        )
                    except ExecutionProfileError as exc:
                        raise RunExecutionError(str(exc)) from exc
                    result = self._call_tool(
                        task_id, run.run_id, node.node_id, node.capability or "", principal,
                        arguments,
                        aggregate.expected_outcome,
                        envelope.envelope_id,
                        aggregate.approval,
                        node.risk_tier,
                        context.get(f"action:{node.capability}"),
                        execution_fence=execution_fence,
                        effect_custody=effect_custody,
                        execution_claim=ExecutionLease(
                            run_id=run.run_id,
                            owner=owner or f"worker:{uuid4()}",
                            fence=lease_fence,
                            expires_at=(
                                datetime.fromisoformat(expiry)
                                if expiry
                                else datetime.now(timezone.utc)
                                + timedelta(minutes=5)
                            ),
                        ),
                    )
                    context[node.node_id] = result.output
                    context[node.capability or node.node_id] = result.output
                    evidence.extend(str(item) for item in result.receipt.output_artifact_ids)
                    context["evidence_refs"] = tuple(evidence)
                    if node.capability == "workspace.run_tests":
                        try:
                            exit_code = self.execution_profile.verification_exit_code(
                                {"workspace.run_tests": result.output}
                            )
                        except ExecutionProfileError as exc:
                            raise RunExecutionError(str(exc)) from exc
                        if exit_code is not None:
                            test_exit_codes[node.node_id] = exit_code
                elif node.kind is NodeKind.EVALUATION:
                    assert_execution_fence("before_outcome_evaluation")
                    test_exit_code = next(
                        (code for code in test_exit_codes.values() if code != 0),
                        0 if test_exit_codes else None,
                    )
                    outcome = self.evaluator.evaluate(
                        aggregate.expected_outcome, task_id=task_id, run_id=run.run_id,
                        tenant_id=run.tenant_id, workspace_id=run.workspace_id,
                        evidence_refs=tuple(evidence), test_exit_code=test_exit_code,
                    )
                    self.tasks.record_outcome(task_id, outcome)
                    observed_outcome = outcome
                    context[node.node_id] = {
                        "status": outcome.status.value,
                        "score": outcome.score,
                    }
                elif node.kind in {NodeKind.TRANSFORM, NodeKind.DECISION}:
                    existing = context.get(node.node_id)
                    context[node.node_id] = (
                        existing
                        if isinstance(existing, dict)
                        else {
                            "available_context_keys": tuple(
                                sorted(
                                    key
                                    for key in context
                                    if key != node.node_id
                                    and not key.startswith("action:")
                                )
                            )
                        }
                    )
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
                        self._release_lease(run.run_id, owner)
                        return self.tasks.get_task(task_id)
                elif node.kind is NodeKind.WAIT_EVENT:
                    assert_execution_fence("before_wait_registration")
                    waiting = self.tasks.register_wait(task_id, node)
                    self._release_lease(run.run_id, owner)
                    return waiting
                elif node.kind in {NodeKind.LOOP, NodeKind.PARALLEL_MAP, NodeKind.SUBWORKFLOW}:
                    raise UnsupportedNodeError(f"node kind {node.kind.value} requires an explicit runtime extension")
                elif node.kind is NodeKind.TERMINAL:
                    context[node.node_id] = {"status": "complete"}
                output = context.get(node.node_id)
                payload: dict[str, Any] = {"node_id": node.node_id}
                if isinstance(output, dict):
                    payload["output"] = output
                assert_execution_fence(f"before_node_commit:{node.node_id}")
                self.tasks.append_event(task_id, TaskEventType.NODE_COMPLETED, payload, correlation_id=run.run_id)
                if stop_after_node == node.node_id:
                    raise WorkerInterrupted(f"worker interrupted after node {node.node_id}")
            except WorkerInterrupted:
                raise
            except KeyboardInterrupt:
                try:
                    self._handle_keyboard_interrupt(
                        task_id,
                        principal,
                        run_id=run.run_id,
                        node_id=node.node_id,
                        lease_fence=lease_fence,
                        effect_custody=effect_custody,
                        held_lease_expiry=expiry,
                        held_lease_owner=owner,
                    )
                finally:
                    self._release_lease(run.run_id, owner)
                raise
            except CapabilityEffectUnknown as unknown:
                # UNKNOWN: the action may have taken effect. Mark the run
                # unresolved (paused) with an unknown_action marker so the
                # resume gate requires explicit reconciliation; release the
                # execution claim; NEVER auto-compensate or auto-resend
                # (founder P1).
                paused_run = run.model_copy(
                    update={
                        "status": RunStatus.PAUSED,
                        "active_node_id": node.node_id,
                    }
                )
                try:
                    self.tasks.append_event(
                        task_id,
                        TaskEventType.RUN_PAUSED,
                        {
                            "run": paused_run.model_dump(mode="json"),
                            "unknown_action": {
                                "action_id": unknown.action.action_id,
                                "action_digest": unknown.action.action_digest(),
                                "capability_id": unknown.action.capability_id,
                                "run_id": run.run_id,
                            },
                        },
                        correlation_id=run.run_id,
                    )
                finally:
                    self._release_lease(run.run_id, owner)
                raise RunExecutionError(
                    f"node {node.node_id} effect is UNKNOWN; "
                    "external reconciliation required"
                ) from unknown
            except Exception as exc:
                failure_commit_allowed = True
                if execution_fence is not None:
                    try:
                        execution_fence("before_failure_commit")
                    except Exception:
                        failure_commit_allowed = False
                try:
                    if failure_commit_allowed:
                        self.tasks.append_event(task_id, TaskEventType.NODE_FAILED, {"node_id": node.node_id, "error": type(exc).__name__}, correlation_id=run.run_id)
                        self.tasks.update_run_status(task_id, RunStatus.FAILED, event_type=TaskEventType.RUN_FAILED, active_node_id=node.node_id)
                        self._attempt_automatic_compensation(
                            task_id,
                            principal,
                            held_lease_fence=lease_fence,
                            effect_custody=effect_custody,
                            held_lease_expiry=expiry,
                            held_lease_owner=owner,
                        )
                finally:
                    self._release_lease(run.run_id, owner)
                raise RunExecutionError(
                    f"node {node.node_id} failed: {type(exc).__name__}: {exc}"
                ) from exc
        if observed_outcome is None:
            self._release_lease(run.run_id, owner)
            raise RunExecutionError("workflow completed without an evaluation node")
        try:
            assert_execution_fence("before_run_finalization")
            observed_outcome = self._revalidate_outcome_before_finalization(
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
                    effect_custody=effect_custody,
                    held_lease_expiry=expiry,
                    held_lease_owner=owner,
                )
        except KeyboardInterrupt:
            self._handle_keyboard_interrupt(
                task_id,
                principal,
                run_id=run.run_id,
                node_id="run-finalization",
                lease_fence=lease_fence,
                effect_custody=effect_custody,
                held_lease_expiry=expiry,
                held_lease_owner=owner,
            )
            raise
        finally:
            self._release_lease(run.run_id, owner)
        return self.tasks.get_task(task_id)

    def _handle_keyboard_interrupt(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        run_id: str,
        node_id: str,
        lease_fence: int,
        effect_custody: EffectCustodyPort | None = None,
        held_lease_expiry: str | None = None,
        held_lease_owner: str | None = None,
    ) -> None:
        current = self.tasks.current_outcome(task_id)
        if current is not None and current.status is OutcomeStatus.VERIFIED:
            self.tasks.record_outcome(
                task_id,
                ObservedOutcome(
                    observed_outcome_id=f"observed-{uuid4()}",
                    expected_outcome_id=current.expected_outcome_id,
                    task_id=current.task_id,
                    run_id=current.run_id,
                    tenant_id=current.tenant_id,
                    workspace_id=current.workspace_id,
                    evaluator_type=current.evaluator_type,
                    evaluator_version=current.evaluator_version,
                    status=OutcomeStatus.UNRESOLVED,
                    score=None,
                    confidence=1.0,
                    evidence_refs=current.evidence_refs,
                    unresolved_gaps=("execution interrupted before finalization",),
                    observed_at=self.tasks.now(),
                ),
            )
        self.tasks.append_event(
            task_id,
            TaskEventType.NODE_FAILED,
            {"node_id": node_id, "error": "KeyboardInterrupt"},
            correlation_id=run_id,
        )
        self.tasks.update_run_status(
            task_id,
            RunStatus.FAILED,
            event_type=TaskEventType.RUN_FAILED,
            active_node_id=node_id,
        )
        self._attempt_automatic_compensation(
            task_id,
            principal,
            held_lease_fence=lease_fence,
            effect_custody=effect_custody,
            held_lease_expiry=held_lease_expiry,
            held_lease_owner=held_lease_owner,
        )

    def _revalidate_outcome_before_finalization(
        self,
        task_id: str,
        outcome: ObservedOutcome,
    ) -> ObservedOutcome:
        if outcome.status is not OutcomeStatus.VERIFIED:
            return outcome
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.expected_outcome is None:
            raise RunExecutionError("outcome finalization lost its committed bindings")
        current = self.tasks.current_outcome(task_id)
        if current is not None and current.status is OutcomeStatus.VERIFIED:
            return outcome
        replacement = ObservedOutcome(
            observed_outcome_id=f"observed-{uuid4()}",
            expected_outcome_id=outcome.expected_outcome_id,
            task_id=outcome.task_id,
            run_id=outcome.run_id,
            tenant_id=outcome.tenant_id,
            workspace_id=outcome.workspace_id,
            evaluator_type=outcome.evaluator_type,
            evaluator_version=outcome.evaluator_version,
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=1.0,
            evidence_refs=outcome.evidence_refs,
            unresolved_gaps=("verified evidence became stale before run finalization",),
            observed_at=self.tasks.now(),
        )
        self.tasks.record_outcome(task_id, replacement)
        return replacement

    def compensate_task(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        effect_custody: EffectCustodyPort | None = None,
    ):
        if effect_custody is None and self._requires_effect_custody(task_id):
            raise RunExecutionError(
                "durable external-exact Task compensation requires effect custody"
            )
        return self._compensate_with_mode(
            task_id,
            principal,
            mode=CompensationMode.MANUAL,
            held_lease_fence=None,
            effect_custody=effect_custody,
        )

    def _requires_effect_custody(self, task_id: str) -> bool:
        return any(
            ActionContract.model_validate(event.decoded_payload()["action"])
            .approval_requirement
            == "external_exact"
            for event in self.tasks._event_store.read(task_id)
            if event.event_type is TaskEventType.ACTION_PROPOSED
            and isinstance(event.decoded_payload().get("action"), dict)
        )

    def _auto_compensate_task(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        held_lease_fence: int,
        effect_custody: EffectCustodyPort | None = None,
        held_lease_expiry: str | None = None,
        held_lease_owner: str | None = None,
    ):
        return self._compensate_with_mode(
            task_id,
            principal,
            mode=CompensationMode.AUTOMATIC,
            held_lease_fence=held_lease_fence,
            effect_custody=effect_custody,
            held_lease_expiry=held_lease_expiry,
            held_lease_owner=held_lease_owner,
        )

    def _attempt_automatic_compensation(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        held_lease_fence: int,
        effect_custody: EffectCustodyPort | None = None,
        held_lease_expiry: str | None = None,
        held_lease_owner: str | None = None,
    ) -> None:
        """Keep an already-persisted failure authoritative if rollback infrastructure fails."""

        try:
            self._auto_compensate_task(
                task_id,
                principal,
                held_lease_fence=held_lease_fence,
                effect_custody=effect_custody,
                held_lease_expiry=held_lease_expiry,
                held_lease_owner=held_lease_owner,
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
        effect_custody: EffectCustodyPort | None,
        held_lease_expiry: str | None = None,
        held_lease_owner: str | None = None,
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

        owner: str | None = held_lease_owner
        acquired_fence = held_lease_fence
        acquired_expiry = held_lease_expiry
        if mode is CompensationMode.MANUAL:
            acquire_lease = getattr(self.tasks._event_store, "acquire_lease", None)
            if acquire_lease is not None:
                owner = f"compensator:{uuid4()}"
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat()
                acquired_expiry = expires_at
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
                effect_custody=effect_custody,
                owner=owner,
                lease_expiry=acquired_expiry,
            )
        finally:
            self._release_lease(aggregate.run.run_id, owner)

    def _compensate_task_locked(
        self,
        task_id: str,
        principal: PrincipalIdentity,
        *,
        mode: CompensationMode,
        lease_fence: int | None,
        effect_custody: EffectCustodyPort | None,
        owner: str | None = None,
        lease_expiry: str | None = None,
    ):
        aggregate = self.tasks.get_task(task_id)
        if aggregate.run is None or aggregate.workflow is None:
            raise RunExecutionError("compensation requires an active workflow run")
        run = aggregate.run
        events = self.tasks._event_store.read(task_id)
        actions_by_node: dict[str, ActionContract] = {}
        actions_by_id: dict[str, ActionContract] = {}
        outputs_by_node: dict[str, dict[str, Any]] = {}
        completed_node_ids: set[str] = set()
        compensated_nodes: set[str] = set()
        effect_candidates: list[tuple[int, ActionContract, dict[str, Any]]] = []
        for event in events:
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.ACTION_PROPOSED:
                value = payload.get("action")
                if isinstance(value, dict):
                    action = ActionContract.model_validate(value)
                    actions_by_node[action.node_id] = action
                    actions_by_id[action.action_id] = action
            elif event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED:
                effect = payload.get("effect")
                decision = payload.get("decision")
                if isinstance(effect, dict) and isinstance(decision, dict):
                    action_id = decision.get("action_id")
                    action = (
                        actions_by_id.get(action_id)
                        if isinstance(action_id, str)
                        else None
                    )
                    if (
                        action is not None
                        and action.capability_id
                        in {"workspace.apply_patch", "workspace.edit"}
                    ):
                        effect_candidates.append(
                            (event.sequence, action, dict(effect))
                        )
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

        durable_effect_nodes = {
            action.node_id for _, action, _ in effect_candidates
        }
        candidates: list[tuple[ActionContract | None, dict[str, Any]]] = [
            (action, output)
            for _, action, output in sorted(
                effect_candidates,
                key=lambda candidate: candidate[0],
                reverse=True,
            )
            if action.node_id not in compensated_nodes
        ]
        candidates.extend(
            (
                actions_by_node.get(node.node_id),
                outputs_by_node.get(node.node_id, {}),
            )
            for node in reversed(self._ordered_nodes(aggregate.workflow))
            if node.capability == "workspace.apply_patch"
            and node.idempotency.value == "compensatable"
            and node.node_id in completed_node_ids
            and node.node_id not in compensated_nodes
            and node.node_id not in durable_effect_nodes
        )
        for original, output in candidates:
            node_id = (
                original.node_id
                if original is not None
                else "unknown-compensatable-action"
            )
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
                    node_id=node_id,
                    original_action_id=(
                        original.action_id
                        if original is not None
                        else f"action:missing:{node_id}"
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
            compensation_identity = content_digest(
                {
                    "task_id": task_id,
                    "run_id": run.run_id,
                    "node_id": node_id,
                    "original_action_id": original.action_id,
                    "compensation_ref": compensation_ref,
                    "manifest_sha256": manifest_sha256,
                }
            )
            compensation_action = ActionContract(
                action_id=f"action:compensate:{compensation_identity}",
                task_id=task_id,
                run_id=run.run_id,
                node_id=node_id,
                principal_id=principal.principal_id,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                capability_id="workspace.compensate_patch",
                capability_version="1",
                arguments_json=json.dumps(arguments),
                risk_tier=1,
                idempotency_key=f"{run.run_id}:compensate:{node_id}",
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
                created_at=original.created_at,
            )
            record_kwargs = {
                "compensation_id": attempt_id,
                "task_id": task_id,
                "run_id": run.run_id,
                "node_id": node_id,
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
            # A previously sealed compensation (e.g. an effect-before-receipt
            # crash) replays the original durable receipt; minting a fresh
            # decision/permit pair against the replayed receipt would violate
            # the receipt identity binding (founder P1 UNKNOWN contract).
            pre_replayed = self.broker.replay(compensation_action)
            if pre_replayed is not None:
                self.tasks.append_event(
                    task_id,
                    TaskEventType.ACTION_PROPOSED,
                    {"action": compensation_action.model_dump(mode="json")},
                    correlation_id=run.run_id,
                )
                self.tasks._recover_action_receipt(
                    task_id,
                    action=compensation_action,
                    permit=pre_replayed.permit,
                    receipt=pre_replayed.receipt,
                    writer_token=self.tasks._runtime_writer_token,
                )
                compensated = PatchCompensationRecord(
                    **record_kwargs,
                    status=CompensationStatus.COMPENSATED,
                    reason="governed patch compensation completed (sealed replay)",
                    manual_intervention_required=False,
                    receipt_id=pre_replayed.receipt.receipt_id,
                    created_at=self.tasks.now(),
                )
                self._append_compensation_record(
                    task_id,
                    run.run_id,
                    TaskEventType.ACTION_COMPENSATED,
                    compensated,
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
                capability = self.capabilities.specs(include_internal=True).get(
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
                def invoke_compensation() -> CapabilityResult:
                    # ADR-0059: every production dispatch carries an execution
                    # claim bound to the held/acquired run lease (founder P1).
                    claim = ExecutionLease(
                        run_id=run.run_id,
                        owner=owner or f"compensator:{uuid4()}",
                        fence=int(lease_fence or 1),
                        expires_at=(
                            datetime.fromisoformat(lease_expiry)
                            if lease_expiry
                            else datetime.now(timezone.utc)
                            + timedelta(minutes=5)
                        ),
                    )
                    return self.broker.invoke(
                        compensation_action,
                        permit,
                        execution_claim=claim,
                    )
                result = (
                    effect_custody(
                        f"compensate:{original.node_id}",
                        compensation_action.action_digest(),
                        invoke_compensation,
                    )
                    if effect_custody is not None
                    else invoke_compensation()
                )
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

    def _call_provider(
        self,
        run_id: str,
        task_id: str,
        capability: str,
        node_id: str,
        source_event_id: str,
        context: dict[str, Any],
        *,
        execution_fence: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], ProviderExecutionReceipt | None]:
        aggregate = self.tasks.get_task(task_id)
        snapshot = aggregate.configuration_snapshot
        run = aggregate.run
        if run is None:
            raise RunExecutionError("provider invocation requires an active Run")
        try:
            invocation_binding = self.provider.invocation_binding
        except RuntimeError as exc:
            if snapshot is not None:
                raise RunExecutionError(
                    "provider invocation binding is unavailable"
                ) from exc
            invocation_binding = None
        if snapshot is None:
            if invocation_binding is not None:
                raise RunExecutionError(
                    "bound provider invocation requires an exact configuration snapshot"
                )
            invocation_binding_digest = None
        else:
            if (
                run.run_id != run_id
                or run.configuration_snapshot_id != snapshot.snapshot_id
                or run.configuration_snapshot_digest != snapshot.snapshot_digest
                or run.provider_profile_id != snapshot.provider_profile.profile_id
            ):
                raise RunExecutionError("provider Run snapshot binding drift")
            if (
                self.provider_profile != snapshot.provider_profile
                or content_digest(self.provider_profile)
                != snapshot.provider_profile_digest
            ):
                raise RunExecutionError("provider profile snapshot binding drift")
            assert invocation_binding is not None
            if (
                invocation_binding.provider_profile != self.provider_profile
                or invocation_binding.provider_id != self.provider_profile.provider_id
                or invocation_binding.model_id != self.provider_profile.model_id
            ):
                raise RunExecutionError("provider profile invocation binding mismatch")
            invocation_binding_digest = invocation_binding.digest()
        if aggregate.commitment is None:
            raise RunExecutionError("provider requires a canonical Commitment")
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
        pre_correction_epochs = None
        if snapshot is not None:
            pre_correction_epochs = self.correction.snapshot(
                task_id, run_id, capability
            )
            if self.correction.halted(task_id, run_id, capability):
                raise RunExecutionError("provider invocation is correction halted")
        if execution_fence is not None:
            execution_fence("before_provider")
        response = self.provider.complete(request)
        if isinstance(response, ProviderFailure):
            raise RunExecutionError(f"provider {response.code.value}: {response.safe_message}")
        if response.request_id != request.request_id:
            raise RunExecutionError("provider response request binding mismatch")
        if snapshot is not None and (
            response.invocation_binding_digest != invocation_binding_digest
        ):
            raise RunExecutionError("provider response invocation binding mismatch")
        try:
            proposals = self.execution_profile.bind_provider_response(
                response,
                context=context,
            )
        except ExecutionProfileError as exc:
            raise RunExecutionError(str(exc)) from exc
        bound_proposal = proposals[0]
        provider_output = {
            "text": response.text,
            "tool_proposals": [bound_proposal.model_dump(mode="json")],
            "usage": response.usage.model_dump(mode="json"),
            "finish_reason": response.finish_reason,
        }
        if snapshot is None:
            return provider_output, None
        assert invocation_binding_digest is not None
        assert pre_correction_epochs is not None
        working_set_ref = WorkingSetRef(
            status=BindingStatus.MISSING,
            gap_reason="developer provider path has no TrustedWorkingSet binding",
        )
        missing_fields: list[str] = ["working_set_digest"]
        if self.provider_profile.model_revision_digest is None:
            missing_fields.append("model_revision_digest")
        receipt_payload = {
            "schema_version": "1.0",
            "source_event_id": source_event_id,
            "node_id": node_id,
            "task_id": task_id,
            "run_id": run_id,
            "tenant_id": run.tenant_id,
            "workspace_id": run.workspace_id,
            "provider_profile_id": self.provider_profile.profile_id,
            "provider_profile_digest": snapshot.provider_profile_digest,
            "provider_id": self.provider_profile.provider_id,
            "model_id": self.provider_profile.model_id,
            "model_revision_digest": self.provider_profile.model_revision_digest,
            "request_id": request.request_id,
            "request_digest": content_digest(request),
            "response_id": response.response_id,
            "response_digest": content_digest(response),
            "invocation_binding_digest": invocation_binding_digest,
            "working_set_ref": working_set_ref.model_dump(mode="json"),
            "pre_correction_epochs": pre_correction_epochs.model_dump(mode="json"),
            "post_correction_epochs": pre_correction_epochs.model_dump(mode="json"),
            "correction_epoch": max(
                pre_correction_epochs.task_epoch,
                pre_correction_epochs.run_epoch,
                pre_correction_epochs.capability_epoch,
            ),
            "missing_fields": tuple(sorted(missing_fields)),
        }
        with self.correction.guard_unchanged(
            task_id,
            run_id,
            capability,
            pre_correction_epochs,
        ) as unchanged:
            if not unchanged:
                raise RunExecutionError(
                    "provider correction epoch changed or became halted during invocation"
                )
            post_correction_epochs = self.correction.snapshot(
                task_id, run_id, capability
            )
            if post_correction_epochs != pre_correction_epochs:
                raise RunExecutionError(
                    "provider correction epoch changed during invocation"
                )
            if execution_fence is not None:
                execution_fence("before_provider_commit")
            receipt_payload["post_correction_epochs"] = (
                post_correction_epochs.model_dump(mode="json")
            )
            receipt = ProviderExecutionReceipt(
                **receipt_payload,
                receipt_digest=provider_execution_receipt_digest(receipt_payload),
            )
            self.tasks.record_provider_response(
                task_id,
                node_id=node_id,
                provider_output=provider_output,
                receipt=receipt,
            )
        return provider_output, receipt

    def _call_tool(
        self,
        task_id: str,
        run_id: str,
        node_id: str,
        capability_id: str,
        principal: PrincipalIdentity,
        args: Any,
        expected: ExpectedOutcome,
        envelope_id: str,
        approval: Any = None,
        risk_tier: int = 0,
        proposed_action: Any = None,
        *,
        execution_fence: Callable[[str], None] | None = None,
        effect_custody: EffectCustodyPort | None = None,
        execution_claim: ExecutionLease,
    ) -> CapabilityResult:
        if capability_id == "workspace.compensate_patch":
            raise RunExecutionError(
                "workspace.compensate_patch is coordinator-only"
            )
        if not isinstance(args, dict):
            args = {"value": args}
        if (
            self.execution_profile.requires_provider_bound_action(capability_id)
            and not isinstance(proposed_action, ActionContract)
        ):
            raise RunExecutionError(f"{capability_id} requires a provider-bound ActionContract")
        action_was_proposed = isinstance(proposed_action, ActionContract)
        action = proposed_action if action_was_proposed else self._build_action(
            task_id=task_id,
            run_id=run_id,
            node_id=node_id,
            capability_id=capability_id,
            principal=principal,
            args=args,
            expected=expected,
            envelope_id=envelope_id,
            risk_tier=risk_tier,
        )
        if (
            action.node_id != node_id
            or action.capability_id != capability_id
            or json.loads(action.arguments_json) != args
        ):
            raise RunExecutionError("proposed action does not match the executable node")
        if not action_was_proposed:
            self.tasks.append_event(
                task_id,
                TaskEventType.ACTION_PROPOSED,
                {"action": action.model_dump(mode="json")},
                correlation_id=run_id,
            )
        return self.actions.execute(
            action,
            principal,
            capability_spec=self.capabilities.specs().get(capability_id),
            approval=approval,
            record_artifacts=True,
            execution_fence=execution_fence,
            effect_custody=effect_custody,
            execution_claim=execution_claim,
        )

    def _build_action(
        self,
        *,
        task_id: str,
        run_id: str,
        node_id: str,
        capability_id: str,
        principal: PrincipalIdentity,
        args: dict[str, Any],
        expected: ExpectedOutcome,
        envelope_id: str,
        risk_tier: int,
    ) -> ActionContract:
        return self.actions.build_action(
            task_id=task_id,
            run_id=run_id,
            node_id=node_id,
            capability_id=capability_id,
            principal=principal,
            args=args,
            expected=expected,
            envelope_id=envelope_id,
            risk_tier=risk_tier,
        )

    def _restore_context(self, task_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        context = dict(inputs)
        completed: set[str] = set()
        proposal_capabilities: set[str] = set()
        evidence: list[tuple[str, str | None]] = []
        for event in self.tasks._event_store.read(task_id):
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.NODE_COMPLETED:
                output = payload.get("output")
                node_id = payload.get("node_id")
                if isinstance(node_id, str):
                    completed.add(node_id)
                    if isinstance(output, dict):
                        context[node_id] = output
            elif event.event_type is TaskEventType.PROVIDER_RESPONDED:
                provider_output = payload.get("provider_output")
                node_id = payload.get("node_id")
                if isinstance(node_id, str) and isinstance(provider_output, dict):
                    context[node_id] = provider_output
                    proposals = provider_output.get("tool_proposals", ())
                    if isinstance(proposals, list):
                        for proposal in proposals:
                            if isinstance(proposal, dict):
                                capability_id = proposal.get("capability_id")
                                arguments_json = proposal.get("arguments_json")
                                if isinstance(capability_id, str) and isinstance(arguments_json, str):
                                    arguments = json.loads(arguments_json)
                                    if isinstance(arguments, dict):
                                        context[capability_id] = arguments
                                        proposal_capabilities.add(capability_id)
            elif event.event_type is TaskEventType.ACTION_PROPOSED:
                action_payload = payload.get("action")
                if isinstance(action_payload, dict):
                    action = ActionContract.model_validate(action_payload)
                    context[f"action:{action.capability_id}"] = action
            elif event.event_type is TaskEventType.RUN_PLAN_REBOUND:
                rebound_payload = payload.get("rebound")
                if not isinstance(rebound_payload, dict):
                    raise RunExecutionError("run plan rebound payload is missing")
                rebound = RunPlanRebound.model_validate(rebound_payload)
                invalidated = set(rebound.invalidated_node_ids)
                for node_id in invalidated:
                    context.pop(node_id, None)
                for key, value in tuple(context.items()):
                    if not key.startswith("action:") or not isinstance(
                        value, ActionContract
                    ):
                        continue
                    context.pop(key, None)
                    context.pop(value.capability_id, None)
                for capability_id in proposal_capabilities:
                    context.pop(capability_id, None)
                proposal_capabilities.clear()
                evidence = [
                    (artifact_id, node_id)
                    for artifact_id, node_id in evidence
                    if node_id is not None and node_id in completed
                ]
            elif event.event_type is TaskEventType.ARTIFACT_RECORDED:
                artifact_id = payload.get("artifact_id")
                if isinstance(artifact_id, str):
                    node_id = payload.get("node_id")
                    evidence.append(
                        (artifact_id, node_id if isinstance(node_id, str) else None)
                    )
        if evidence:
            context["evidence_refs"] = tuple(
                artifact_id for artifact_id, _ in evidence
            )
        return context

    def _completed_nodes(self, task_id: str) -> set[str]:
        completed: set[str] = set()
        for event in self.tasks._event_store.read(task_id):
            if event.event_type is TaskEventType.NODE_COMPLETED:
                node_id = event.decoded_payload().get("node_id")
                if isinstance(node_id, str):
                    completed.add(node_id)
        return completed

    def _release_lease(self, run_id: str, owner: str | None) -> None:
        if owner is None:
            return
        release = getattr(self.tasks._event_store, "release_lease", None)
        if release is not None:
            release(run_id, owner)

    @staticmethod
    def _ordered_nodes(workflow: WorkflowGraph):
        incoming = {node.node_id: 0 for node in workflow.nodes}
        outgoing = {node.node_id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge.target)
        ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
        by_id = {node.node_id: node for node in workflow.nodes}
        result = []
        while ready:
            node_id = ready.pop(0)
            result.append(by_id[node_id])
            for target in sorted(outgoing[node_id]):
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
                    ready.sort()
        return result
