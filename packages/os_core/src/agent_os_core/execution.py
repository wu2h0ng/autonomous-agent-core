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
    BenchmarkTaskValidationError,
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
    ProviderMessage,
    ProviderMessageRole,
    ProviderExecutionReceipt,
    ProviderProfile,
    ProviderRequest,
    ProviderFailure,
    ProviderToolProposal,
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

from .capability import CapabilityBroker, CapabilityResult, WorkspaceSandbox
from .benchmark_baseline import extract_unified_diff, validate_unified_diff
from .errors import ConcurrentWriteError
from .governance import CorrectionAuthority, PolicyInput, PolicyKernel
from .provider import ProviderPort
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


def _diff_header_path(diff_text: str) -> str | None:
    """Extract the stripped single-file path from +++ headers of a validated diff."""
    for line in diff_text.splitlines():
        if line.startswith("+++"):
            candidate = line[3:].strip()
            if candidate.startswith("b/"):
                candidate = candidate[2:]
            return candidate or None
    return None


class RunExecutionError(RuntimeError):
    pass


class WorkerInterrupted(RunExecutionError):
    """Test/worker crash boundary; durable event state remains resumable."""
    pass


class WaitingForApproval(RunExecutionError):
    pass


class UnsupportedNodeError(RunExecutionError):
    pass


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
        correction: CorrectionAuthority,
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
        lease_fence = 0
        owner: str | None = None
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
            completed_nodes = self._completed_nodes(task_id)
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
            self._release_lease(run.run_id, owner)
            raise
        for node in self._ordered_nodes(aggregate.workflow):
            if node.node_id in completed_nodes:
                continue
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
                    arguments = self._tool_arguments(node.capability or "", context)
                    result = self._call_tool(
                        task_id, run.run_id, node.node_id, node.capability or "", principal,
                        arguments,
                        aggregate.expected_outcome,
                        envelope.envelope_id,
                        aggregate.approval,
                        node.risk_tier,
                        context.get(f"action:{node.capability}"),
                    )
                    context[node.node_id] = result.output
                    context[node.capability or node.node_id] = result.output
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
                    self._release_lease(run.run_id, owner)
                raise RunExecutionError(
                    f"node {node.node_id} failed: {type(exc).__name__}: {exc}"
                ) from exc
        if observed_outcome is None:
            self._release_lease(run.run_id, owner)
            raise RunExecutionError("workflow completed without an evaluation node")
        try:
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
                )
        finally:
            self._release_lease(run.run_id, owner)
        return self.tasks.get_task(task_id)

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
            self._release_lease(aggregate.run.run_id, owner)

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
            for node in reversed(self._ordered_nodes(aggregate.workflow))
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

    def _call_provider(
        self,
        run_id: str,
        task_id: str,
        capability: str,
        node_id: str,
        source_event_id: str,
        context: dict[str, Any],
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
        target_path = str(context.get("target_path") or context.get("path") or "")
        read_output = context.get("workspace.read") or context.get("read")
        if not target_path or not isinstance(read_output, dict):
            raise RunExecutionError("provider requires a target path and completed workspace.read")
        current_content = str(read_output.get("content", ""))
        goal = str(context.get("goal") or context.get("prompt") or "Produce the requested repository patch.")
        patch_format = str(context.get("patch_format") or "complete_file")
        if patch_format not in {"complete_file", "unified_diff"}:
            raise RunExecutionError(f"unsupported patch_format: {patch_format}")
        if patch_format == "unified_diff":
            proposal_instruction = (
                "Propose a single-file unified diff for the target path only. "
                "Output ONLY the diff as plain text: it must start with "
                "'--- a/<path>' and '+++ b/<path>' headers for the target path "
                "and contain only well-formed @@ hunks. Do not output the "
                "complete file, do not wrap the diff in prose or code fences "
                "beyond a single markdown fence, and do not claim that the "
                "patch was applied."
            )
        else:
            proposal_instruction = (
                "Propose the complete replacement content by calling only the "
                "workspace.apply_patch tool. Include path and content. Do not call any "
                "other capability and do not claim that the patch was applied."
            )
        prompt = (
            f"Repository task: {goal}\n"
            f"Target path: {target_path}\n"
            f"Current SHA-256: {read_output.get('sha256', '')}\n"
            "Current file content follows:\n"
            f"---BEGIN FILE---\n{current_content[:20000]}\n---END FILE---\n"
            f"{proposal_instruction}"
        )
        request = ProviderRequest(
            request_id=f"request-{uuid4()}", task_id=task_id, run_id=run_id,
            provider_profile_id=self.provider_profile.profile_id,
            messages=(ProviderMessage(role=ProviderMessageRole.USER, content=prompt),),
            allowed_capability_ids=("workspace.apply_patch",),
            timeout_seconds=self.provider_profile.request_timeout_seconds,
            created_at=datetime.now(timezone.utc),
        )
        pre_correction_epochs = None
        if snapshot is not None:
            pre_correction_epochs = self.correction.snapshot(
                task_id, run_id, capability
            )
            if self.correction.halted(task_id, run_id, capability):
                raise RunExecutionError("provider invocation is correction halted")
        response = self.provider.complete(request)
        if isinstance(response, ProviderFailure):
            raise RunExecutionError(f"provider {response.code.value}: {response.safe_message}")
        if response.request_id != request.request_id:
            raise RunExecutionError("provider response request binding mismatch")
        if snapshot is not None and (
            response.invocation_binding_digest != invocation_binding_digest
        ):
            raise RunExecutionError("provider response invocation binding mismatch")
        proposals = list(response.tool_proposals)
        if proposals and (
            len(proposals) != 1
            or proposals[0].capability_id != "workspace.apply_patch"
        ):
            raise RunExecutionError(
                "provider returned an ambiguous or unauthorized tool proposal"
            )
        if not proposals:
            if patch_format == "unified_diff":
                extracted = extract_unified_diff(response.text)
                fallback = (
                    {"path": target_path, "diff": extracted}
                    if extracted is not None
                    else None
                )
            else:
                fallback = self._parse_patch_json(response.text)
            if fallback is not None:
                proposals = [
                    ProviderToolProposal(
                        proposal_id=f"proposal-{uuid4()}",
                        capability_id="workspace.apply_patch",
                        arguments_json=json.dumps(fallback),
                    )
                ]
        if len(proposals) != 1:
            raise RunExecutionError("provider must return exactly one workspace.apply_patch proposal")
        raw_arguments = json.loads(proposals[0].arguments_json)
        if not isinstance(raw_arguments, dict):
            raise RunExecutionError("provider patch arguments must be an object")
        if patch_format == "unified_diff":
            if set(raw_arguments) != {"path", "diff"}:
                raise RunExecutionError(
                    "provider diff arguments must contain only path and diff"
                )
            proposed_diff = raw_arguments.get("diff")
            if not isinstance(proposed_diff, str) or not proposed_diff.strip():
                raise RunExecutionError(
                    "provider proposal requires string diff content"
                )
            try:
                validate_unified_diff(proposed_diff)
            except BenchmarkTaskValidationError as exc:
                raise RunExecutionError(
                    f"provider diff failed validation: {exc.detail}"
                ) from exc
        else:
            if set(raw_arguments) != {"path", "content"}:
                raise RunExecutionError(
                    "provider patch arguments must contain only path and content"
                )
            proposed_content = raw_arguments.get("content")
            if not isinstance(proposed_content, str):
                raise RunExecutionError(
                    "provider proposal requires complete string content"
                )
        proposed_path = str(raw_arguments.get("path", ""))
        if patch_format == "unified_diff":
            header_path = _diff_header_path(str(raw_arguments.get("diff", "")))
            if header_path is None or header_path != proposed_path:
                raise RunExecutionError(
                    "provider diff path does not match the proposal path"
                )
        if proposed_path != target_path:
            raise RunExecutionError("provider proposal path does not match the reviewed target")
        raw_arguments["expected_sha256"] = str(read_output.get("sha256", ""))
        bound_proposal = ProviderToolProposal(
            proposal_id=proposals[0].proposal_id,
            capability_id="workspace.apply_patch",
            arguments_json=json.dumps(raw_arguments),
        )
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

    def _call_tool(self, task_id: str, run_id: str, node_id: str, capability_id: str, principal: PrincipalIdentity, args: Any, expected: ExpectedOutcome, envelope_id: str, approval: Any = None, risk_tier: int = 0, proposed_action: Any = None) -> CapabilityResult:
        if capability_id == "workspace.compensate_patch":
            raise RunExecutionError(
                "workspace.compensate_patch is coordinator-only"
            )
        if not isinstance(args, dict):
            args = {"value": args}
        if capability_id == "workspace.apply_patch" and not isinstance(proposed_action, ActionContract):
            raise RunExecutionError("workspace.apply_patch requires a provider-bound ActionContract")
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
        grant = self.grant[capability_id] if isinstance(self.grant, dict) else self.grant
        bound_approval = (
            approval
            if approval is not None and approval.action_digest == action.action_digest()
            else None
        )
        decision = self.policy.decide(
            action,
            PolicyInput(
                principal=principal,
                grant=grant,
                capability=self.sandbox.specs().get(capability_id),
                approval=bound_approval,
            ),
        )
        self.tasks.append_event(task_id, TaskEventType.POLICY_DECIDED, {"decision": decision.model_dump(mode="json")}, correlation_id=run_id)
        if decision.verdict is not PolicyVerdict.ALLOW:
            raise PermissionError(f"policy denied {capability_id}: {decision.reason_codes}")
        aggregate = self.tasks.get_task(task_id)
        lease_fence = aggregate.run.lease_fence if aggregate.run is not None else 0
        permit = self.policy.permit(action, decision, grant, lease_fence=lease_fence)
        current_fence = getattr(self.tasks._event_store, "lease_fence", lambda _run_id: lease_fence)(run_id)
        if current_fence != permit.lease_fence:
            raise PermissionError("stale worker lease")
        result = self.broker.invoke(action, permit)
        self.tasks._record_action_receipt(
            task_id,
            action=action,
            decision=decision,
            permit=permit,
            receipt=result.receipt,
            writer_token=self.tasks._runtime_writer_token,
        )
        if result.receipt.status.value != "SUCCEEDED":
            raise RunExecutionError(f"tool failed: {result.receipt.error_code}")
        for artifact_id in result.receipt.output_artifact_ids:
            self.tasks.record_artifact(
                task_id,
                artifact_id,
                node_id=node_id,
                action_id=action.action_id,
            )
        return result

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
        return ActionContract(
            action_id=f"action-{uuid4()}", task_id=task_id, run_id=run_id, node_id=node_id,
            principal_id=principal.principal_id, tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id, capability_id=capability_id,
            capability_version="1", arguments_json=json.dumps(args), risk_tier=risk_tier,
            idempotency_key=f"{run_id}:{node_id}",
            estimated_budget=ResourceBudget(max_cost_usd=Decimal("0"), max_duration_seconds=120, max_provider_tokens=0, max_tool_calls=1),
            policy_version=self.policy.policy_version,
            observed_correction_epochs=self.correction.snapshot(task_id, run_id, capability_id),
            expected_outcome_id=expected.expected_outcome_id, candidate_envelope_id=envelope_id,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _parse_patch_json(text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                value = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _tool_arguments(capability_id: str, context: dict[str, Any]) -> dict[str, Any]:
        if capability_id == "workspace.read":
            path = context.get("target_path") or context.get("path")
            if not isinstance(path, str) or not path:
                raise RunExecutionError("workspace.read requires target_path")
            return {"path": path}
        if capability_id == "workspace.run_tests":
            command = context.get("test_command") or context.get("command") or "python -m pytest"
            return {"command": str(command)}
        explicit = context.get(capability_id)
        if isinstance(explicit, dict):
            return dict(explicit)
        raise RunExecutionError(f"no typed arguments available for {capability_id}")

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
