from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDisposition,
    CapabilityGrant,
    CandidateGenerationEnvelope,
    ExpectedOutcome,
    NodeKind,
    PolicyVerdict,
    PrincipalIdentity,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderFailure,
    ProviderToolProposal,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
    ObservedOutcome,
    OutcomeStatus,
)

from .capability import CapabilityBroker, CapabilityResult, WorkspaceSandbox
from .governance import CorrectionAuthority, PolicyInput, PolicyKernel
from .provider import ProviderPort
from .task_service import TaskService


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
        observed = now or datetime.now(timezone.utc)
        passed = test_exit_code == 0 and bool(evidence_refs)
        return ObservedOutcome(
            observed_outcome_id=f"observed-{uuid4()}",
            expected_outcome_id=expected.expected_outcome_id,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluator_type=expected.evaluator_type,
            evaluator_version=expected.evaluator_version,
            status=OutcomeStatus.VERIFIED if passed else OutcomeStatus.NOT_MET,
            score=1.0 if passed else 0.0,
            confidence=1.0,
            evidence_refs=evidence_refs,
            unresolved_gaps=() if passed else ("allowlisted verification did not pass",),
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
    ) -> None:
        self.tasks = task_service
        self.sandbox = sandbox
        self.broker = CapabilityBroker(sandbox, correction)
        self.provider = provider
        self.provider_profile = provider_profile
        self.policy = policy
        self.correction = correction
        self.grant = grant
        self.evaluator = evaluator or DeterministicOutcomeEvaluator()

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
            except Exception:
                if not recover_stale_lease:
                    raise
                recover = getattr(self.tasks._event_store, "recover_lease", None)
                if recover is None:
                    raise
                lease_fence = recover(run.run_id, owner, expiry)
        resume_states = {
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_EVENT,
            RunStatus.PAUSED,
            RunStatus.FAILED,
        }
        self.tasks.update_run_status(
            task_id,
            RunStatus.RUNNING,
            event_type=(
                TaskEventType.RUN_RESUMED
                if run.status in resume_states
                else TaskEventType.RUN_QUEUED
            ),
            lease_fence=lease_fence,
        )
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
        test_output = context.get("workspace.run_tests")
        test_exit_code = (
            int(str(test_output.get("exit_code", 1)))
            if isinstance(test_output, dict)
            else None
        )
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
        for node in self._ordered_nodes(aggregate.workflow):
            if node.node_id in completed_nodes:
                continue
            self.tasks.append_event(task_id, TaskEventType.NODE_STARTED, {"node_id": node.node_id}, correlation_id=run.run_id)
            try:
                if node.kind is NodeKind.PROVIDER:
                    provider_output = self._call_provider(run.run_id, task_id, node.capability or "provider", context)
                    context[node.node_id] = provider_output
                    self.tasks.append_event(
                        task_id,
                        TaskEventType.PROVIDER_RESPONDED,
                        {"node_id": node.node_id, "provider_output": provider_output},
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
                        test_exit_code = int(str(result.output.get("exit_code", 1)))
                elif node.kind is NodeKind.EVALUATION:
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
                    context[node.node_id] = context.get(node.node_id, context)
                elif node.kind is NodeKind.APPROVAL:
                    action = next(
                        (
                            value
                            for key, value in context.items()
                            if key.startswith("action:") and isinstance(value, ActionContract)
                        ),
                        None,
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
                    self.tasks.update_run_status(task_id, RunStatus.WAITING_EVENT, event_type=TaskEventType.NODE_STARTED, active_node_id=node.node_id)
                    self._release_lease(run.run_id, owner)
                    return self.tasks.get_task(task_id)
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
                self.tasks.append_event(task_id, TaskEventType.NODE_FAILED, {"node_id": node.node_id, "error": type(exc).__name__}, correlation_id=run.run_id)
                self.tasks.update_run_status(task_id, RunStatus.FAILED, event_type=TaskEventType.RUN_FAILED, active_node_id=node.node_id)
                self._release_lease(run.run_id, owner)
                raise RunExecutionError(f"node {node.node_id} failed: {type(exc).__name__}") from exc
        if observed_outcome is None:
            self._release_lease(run.run_id, owner)
            raise RunExecutionError("workflow completed without an evaluation node")
        self.tasks.update_run_status(
            task_id,
            RunStatus.SUCCEEDED
            if observed_outcome.status is OutcomeStatus.VERIFIED
            else RunStatus.FAILED,
            event_type=TaskEventType.RUN_SUCCEEDED
            if observed_outcome.status is OutcomeStatus.VERIFIED
            else TaskEventType.RUN_FAILED,
        )
        self._release_lease(run.run_id, owner)
        return self.tasks.get_task(task_id)

    def _call_provider(self, run_id: str, task_id: str, capability: str, context: dict[str, Any]) -> dict[str, Any]:
        target_path = str(context.get("target_path") or context.get("path") or "")
        read_output = context.get("workspace.read") or context.get("read")
        if not target_path or not isinstance(read_output, dict):
            raise RunExecutionError("provider requires a target path and completed workspace.read")
        current_content = str(read_output.get("content", ""))
        goal = str(context.get("goal") or context.get("prompt") or "Produce the requested repository patch.")
        prompt = (
            f"Repository task: {goal}\n"
            f"Target path: {target_path}\n"
            f"Current SHA-256: {read_output.get('sha256', '')}\n"
            "Current file content follows:\n"
            f"---BEGIN FILE---\n{current_content[:20000]}\n---END FILE---\n"
            "Propose the complete replacement content by calling only the "
            "workspace.apply_patch tool. Include path and content. Do not call any "
            "other capability and do not claim that the patch was applied."
        )
        request = ProviderRequest(
            request_id=f"request-{uuid4()}", task_id=task_id, run_id=run_id,
            provider_profile_id=self.provider_profile.profile_id,
            messages=(ProviderMessage(role=ProviderMessageRole.USER, content=prompt),),
            allowed_capability_ids=("workspace.apply_patch",),
            timeout_seconds=self.provider_profile.request_timeout_seconds,
            created_at=datetime.now(timezone.utc),
        )
        response = self.provider.complete(request)
        if isinstance(response, ProviderFailure):
            raise RunExecutionError(f"provider {response.code.value}: {response.safe_message}")
        proposals = list(response.tool_proposals)
        if proposals and (
            len(proposals) != 1
            or proposals[0].capability_id != "workspace.apply_patch"
        ):
            raise RunExecutionError(
                "provider returned an ambiguous or unauthorized tool proposal"
            )
        if not proposals:
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
        if set(raw_arguments) != {"path", "content"}:
            raise RunExecutionError(
                "provider patch arguments must contain only path and content"
            )
        proposed_path = str(raw_arguments.get("path", ""))
        proposed_content = raw_arguments.get("content")
        if proposed_path != target_path:
            raise RunExecutionError("provider proposal path does not match the reviewed target")
        if not isinstance(proposed_content, str):
            raise RunExecutionError("provider proposal requires complete string content")
        raw_arguments["expected_sha256"] = str(read_output.get("sha256", ""))
        bound_proposal = ProviderToolProposal(
            proposal_id=proposals[0].proposal_id,
            capability_id="workspace.apply_patch",
            arguments_json=json.dumps(raw_arguments),
        )
        return {
            "text": response.text,
            "tool_proposals": [bound_proposal.model_dump(mode="json")],
            "usage": response.usage.model_dump(mode="json"),
            "finish_reason": response.finish_reason,
        }

    def _call_tool(self, task_id: str, run_id: str, node_id: str, capability_id: str, principal: PrincipalIdentity, args: Any, expected: ExpectedOutcome, envelope_id: str, approval: Any = None, risk_tier: int = 0, proposed_action: Any = None) -> CapabilityResult:
        if not isinstance(args, dict):
            args = {"value": args}
        if capability_id == "workspace.apply_patch" and not isinstance(proposed_action, ActionContract):
            raise RunExecutionError("workspace.apply_patch requires a provider-bound ActionContract")
        action = proposed_action if isinstance(proposed_action, ActionContract) else self._build_action(
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
        self.tasks.append_event(task_id, TaskEventType.ACTION_RECEIPT_RECORDED, {"receipt": result.receipt.model_dump(mode="json")}, correlation_id=run_id)
        if result.receipt.status.value != "SUCCEEDED":
            raise RunExecutionError(f"tool failed: {result.receipt.error_code}")
        for artifact_id in result.receipt.output_artifact_ids:
            self.tasks.record_artifact(task_id, artifact_id)
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
        explicit = context.get(capability_id)
        if isinstance(explicit, dict):
            return dict(explicit)
        if capability_id == "workspace.read":
            path = context.get("target_path") or context.get("path")
            if not isinstance(path, str) or not path:
                raise RunExecutionError("workspace.read requires target_path")
            return {"path": path}
        if capability_id == "workspace.run_tests":
            command = context.get("test_command") or context.get("command") or "python -m pytest"
            return {"command": str(command)}
        raise RunExecutionError(f"no typed arguments available for {capability_id}")

    def _restore_context(self, task_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        context = dict(inputs)
        evidence: list[str] = []
        for event in self.tasks._event_store.read(task_id):
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.NODE_COMPLETED:
                output = payload.get("output")
                node_id = payload.get("node_id")
                if isinstance(node_id, str) and isinstance(output, dict):
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
            elif event.event_type is TaskEventType.ACTION_PROPOSED:
                action_payload = payload.get("action")
                if isinstance(action_payload, dict):
                    action = ActionContract.model_validate(action_payload)
                    context[f"action:{action.capability_id}"] = action
            elif event.event_type is TaskEventType.ARTIFACT_RECORDED:
                artifact_id = payload.get("artifact_id")
                if isinstance(artifact_id, str):
                    evidence.append(artifact_id)
        if evidence:
            context["evidence_refs"] = tuple(evidence)
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
