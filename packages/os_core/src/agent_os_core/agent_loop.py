from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    BindingStatus,
    CandidateGenerationEnvelope,
    ExpectedOutcome,
    PrincipalIdentity,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
    SessionRef,
    TaskEventType,
    TurnId,
    WorkingSetRef,
)

from .action_pipeline import ActionPipeline
from .capability import CapabilityBroker, WorkspaceSandbox
from .governance import CorrectionReadPort, PolicyKernel
from .errors import RunExecutionError
from .provider_receipts import build_provider_execution_receipt
from .provider import ProviderPort
from .task_service import TaskService

# Tool surface exposed to the model during chat turns. The model may only ever
# propose these typed capabilities; every invocation still passes PolicyKernel.
CHAT_CAPABILITY_IDS: tuple[str, ...] = (
    "workspace.read",
    "workspace.search",
    "workspace.edit",
    "workspace.apply_patch",
    "workspace.run_tests",
    "workspace.shell",
)

# Action risk tiers per capability. Tier >= 3 escalates inside PolicyKernel and
# requires a digest-bound ApprovalDecision; tier 2 is kernel-allowed but still
# passes through the interactive confirmation gateway.
ACTION_RISK_TIERS: dict[str, int] = {
    "workspace.read": 1,
    "workspace.search": 1,
    "workspace.run_tests": 1,
    "workspace.edit": 2,
    "workspace.apply_patch": 2,
    "workspace.shell": 3,
}

# Grant risk ceilings the chat composition must provide per capability.
CHAT_GRANT_MAX_RISK_TIERS: dict[str, int] = {
    "workspace.read": 1,
    "workspace.search": 1,
    "workspace.run_tests": 1,
    "workspace.edit": 2,
    "workspace.apply_patch": 2,
    "workspace.shell": 3,
}

_SYSTEM_PROMPT = (
    "You are a governed terminal coding agent operating inside a workspace. "
    "You act only through the provided typed tools; you never claim an action "
    "succeeded before its tool result confirms it. Prefer workspace.search and "
    "workspace.read to inspect before editing. Use workspace.edit for precise "
    "string replacements and workspace.apply_patch only for full-file "
    "replacement or new files. Run tests with workspace.run_tests after "
    "edits. If a tool result reports an error, adjust and retry with "
    "corrected arguments instead of repeating the identical call."
)

_MAX_TOOL_RESULT_CHARS = 8000


class ConfirmationGateway(Protocol):
    """Interactive authority bridge. Implementations must be human-driven UI."""

    def confirm(self, action: ActionContract, preview: str) -> bool: ...


class AutoApproveGateway:
    """Non-interactive gateway for `-p` runs and hermetic tests.

    Only admits risk tier <= 2 actions; tier >= 3 still requires an explicit
    approval callback, so shell commands are never auto-approved here.
    """

    def confirm(self, action: ActionContract, preview: str) -> bool:
        return action.risk_tier < 3


class NonInteractiveDenyGateway:
    """Fail closed when a headless run reaches a confirmation-required action."""

    def confirm(self, action: ActionContract, preview: str) -> bool:
        return False


@dataclass(frozen=True)
class AgentLoopConfig:
    max_steps_per_turn: int = 25
    max_provider_retries: int = 2
    max_turn_tokens: int = 100_000
    max_context_chars: int = 60_000
    loop_detection_threshold: int = 3
    system_prompt: str = _SYSTEM_PROMPT


@dataclass(frozen=True)
class ChatSession:
    ref: SessionRef
    envelope_id: str
    expected: ExpectedOutcome

    @property
    def session_id(self) -> str:
        return self.ref.session_id

    @property
    def task_id(self) -> str:
        return self.ref.task_id

    @property
    def run_id(self) -> str:
        return self.ref.run_id


@dataclass(frozen=True)
class TurnResult:
    turn_id: TurnId
    text: str
    steps: int
    stop_reason: str
    total_tokens: int


def _session_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentLoop:
    """Governed multi-turn provider<->capability loop for terminal chat.

    Every model-proposed action is built as an ActionContract and executed via
    ActionPipeline, so PolicyKernel.decide -> permit -> CapabilityBroker stays
    the only execution path (C7 is never bypassed). Conversation state is held
    in memory for the live session and mirrored into the durable event store.
    """

    def __init__(
        self,
        *,
        tasks: TaskService,
        provider: ProviderPort,
        provider_profile: ProviderProfile,
        policy: PolicyKernel,
        correction: CorrectionReadPort,
        sandbox: WorkspaceSandbox,
        grants: dict[str, Any],
        principal: PrincipalIdentity,
        gateway: ConfirmationGateway,
        config: AgentLoopConfig | None = None,
    ) -> None:
        self._tasks = tasks
        self._provider = provider
        self._profile = provider_profile
        self._policy = policy
        self._correction = correction
        self._sandbox = sandbox
        self._principal = principal
        self._gateway = gateway
        self._config = config or AgentLoopConfig()
        self._broker = CapabilityBroker(sandbox, correction)
        self._actions = ActionPipeline(
            tasks, self._broker, policy, correction, grants
        )
        self._history: list[ProviderMessage] = [
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content=self._config.system_prompt,
            )
        ]

    @property
    def history(self) -> tuple[ProviderMessage, ...]:
        return tuple(self._history)

    def restore_history(self, messages: list[ProviderMessage]) -> None:
        """Replace in-memory conversation state for session resume."""
        if not messages:
            return
        self._history = list(messages)

    def run_turn(self, session: ChatSession, user_input: str) -> TurnResult:
        turn_id = TurnId(
            turn_id=f"turn-{uuid4()}",
            session_id=session.session_id,
        )
        text = user_input.strip()
        if not text:
            raise ValueError("user input must be non-empty")
        self._history.append(
            ProviderMessage(role=ProviderMessageRole.USER, content=text)
        )
        self._tasks.append_event(
            session.task_id,
            TaskEventType.SESSION_TURN_STARTED,
            {
                "turn_id": turn_id.turn_id,
                "session_id": turn_id.session_id,
                "user_text": text,
            },
            correlation_id=session.run_id,
        )
        result = self._drive(session, turn_id)
        self._tasks.append_event(
            session.task_id,
            TaskEventType.SESSION_TURN_COMPLETED,
            {
                "turn_id": turn_id.turn_id,
                "session_id": turn_id.session_id,
                "stop_reason": result.stop_reason,
                "steps": result.steps,
                "total_tokens": result.total_tokens,
            },
            correlation_id=session.run_id,
        )
        return result

    def _drive(self, session: ChatSession, turn_id: TurnId) -> TurnResult:
        steps = 0
        total_tokens = 0
        final_text = ""
        seen_action_digests: dict[str, int] = {}
        stop_reason = "max_steps"
        while steps < self._config.max_steps_per_turn:
            if self._correction.halted(session.task_id, session.run_id, "provider"):
                stop_reason = "correction_halted"
                break
            response = self._call_provider(session, turn_id, steps)
            if isinstance(response, ProviderFailure):
                stop_reason = f"provider_failure:{response.code.value}"
                final_text = response.safe_message
                break
            steps += 1
            total_tokens += response.usage.total_tokens
            if total_tokens > self._config.max_turn_tokens:
                stop_reason = "budget_exceeded"
                break
            tool_calls = tuple(
                ProviderToolCall(
                    tool_call_id=proposal.proposal_id,
                    capability_id=proposal.capability_id,
                    arguments_json=proposal.arguments_json,
                )
                for proposal in response.tool_proposals
            )
            self._history.append(
                ProviderMessage(
                    role=ProviderMessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=tool_calls,
                )
            )
            if not response.tool_proposals:
                stop_reason = "completed"
                final_text = response.text
                break
            for index, proposal in enumerate(response.tool_proposals):
                capability_id = proposal.capability_id
                if capability_id not in CHAT_CAPABILITY_IDS:
                    stop_reason = "unauthorized_proposal"
                    final_text = (
                        f"provider proposed unauthorized capability {capability_id}"
                    )
                    break
                tool_message = self._execute_proposal(
                    session,
                    turn_id.turn_id,
                    steps,
                    index,
                    proposal,
                    seen_action_digests,
                )
                self._history.append(tool_message)
                if seen_action_digests and max(seen_action_digests.values()) >= (
                    self._config.loop_detection_threshold
                ):
                    stop_reason = "loop_detected"
                    final_text = "repeated identical action proposals detected"
                    break
            if stop_reason in {
                "unauthorized_proposal",
                "loop_detected",
            }:
                break
        return TurnResult(
            turn_id=turn_id,
            text=final_text,
            steps=steps,
            stop_reason=stop_reason,
            total_tokens=total_tokens,
        )

    def _call_provider(
        self, session: ChatSession, turn_id: TurnId, step: int
    ) -> ProviderResponse | ProviderFailure:
        attempts = self._config.max_provider_retries + 1
        last_failure: ProviderFailure | None = None
        for _ in range(attempts):
            aggregate = self._tasks.get_task(session.task_id)
            run = aggregate.run
            snapshot = aggregate.configuration_snapshot
            if (
                run is None
                or snapshot is None
                or run.run_id != session.run_id
                or run.configuration_snapshot_id != snapshot.snapshot_id
                or snapshot.provider_profile != self._profile
            ):
                raise RunExecutionError(
                    "chat provider invocation requires an exact configuration snapshot"
                )
            try:
                invocation_binding = self._provider.invocation_binding
            except RuntimeError as exc:
                raise RunExecutionError(
                    "chat provider invocation binding is unavailable"
                ) from exc
            if invocation_binding.provider_profile != self._profile:
                raise RunExecutionError(
                    "chat provider invocation profile binding mismatch"
                )
            invocation_binding_digest = invocation_binding.digest()
            pre_correction_epochs = self._correction.snapshot(
                session.task_id, session.run_id, "provider"
            )
            if self._correction.halted(
                session.task_id, session.run_id, "provider"
            ):
                raise RunExecutionError("chat provider invocation is correction halted")
            request = ProviderRequest(
                request_id=f"request-{uuid4()}",
                task_id=session.task_id,
                run_id=session.run_id,
                provider_profile_id=self._profile.profile_id,
                messages=tuple(self._trimmed_history()),
                allowed_capability_ids=CHAT_CAPABILITY_IDS,
                timeout_seconds=self._profile.request_timeout_seconds,
                created_at=_session_now(),
            )
            response = self._provider.complete(request)
            if isinstance(response, ProviderFailure):
                last_failure = response
                if response.request_id != request.request_id:
                    raise RunExecutionError(
                        "chat provider failure request binding mismatch"
                    )
                if response.retryable:
                    continue
                break
            if (
                response.request_id != request.request_id
                or response.invocation_binding_digest
                != invocation_binding_digest
            ):
                raise RunExecutionError(
                    "chat provider response invocation binding mismatch"
                )
            with self._correction.guard_unchanged(
                session.task_id,
                session.run_id,
                "provider",
                pre_correction_epochs,
            ) as unchanged:
                if not unchanged:
                    raise RunExecutionError(
                        "chat provider correction epoch changed during invocation"
                    )
                post_correction_epochs = self._correction.snapshot(
                    session.task_id, session.run_id, "provider"
                )
                if post_correction_epochs != pre_correction_epochs:
                    raise RunExecutionError(
                        "chat provider correction epoch changed during invocation"
                    )
                node_id = f"{turn_id.turn_id}-step-{step + 1}"
                receipt = build_provider_execution_receipt(
                    source_event_id=f"event-{uuid4()}",
                    node_id=node_id,
                    run=run,
                    provider_profile=self._profile,
                    provider_profile_digest=snapshot.provider_profile_digest,
                    request=request,
                    response=response,
                    invocation_binding_digest=invocation_binding_digest,
                    working_set_ref=WorkingSetRef(
                        status=BindingStatus.MISSING,
                        gap_reason=(
                            "terminal chat has no TrustedWorkingSet binding"
                        ),
                    ),
                    pre_correction_epochs=pre_correction_epochs,
                    post_correction_epochs=post_correction_epochs,
                )
                self._tasks.record_provider_response(
                    session.task_id,
                    node_id=node_id,
                    provider_output=_provider_output(response),
                    receipt=receipt,
                )
            return response
        if last_failure is None:
            raise RunExecutionError("chat provider exhausted without a response")
        return last_failure

    def _execute_proposal(
        self,
        session: ChatSession,
        turn_id: str,
        step: int,
        index: int,
        proposal: Any,
        seen_action_digests: dict[str, int],
    ) -> ProviderMessage:
        capability_id = proposal.capability_id
        try:
            arguments = json.loads(proposal.arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
        except ValueError as exc:
            return self._tool_message(
                proposal, {"error": f"malformed arguments: {exc}"}
            )
        risk_tier = ACTION_RISK_TIERS.get(capability_id, 1)
        fingerprint = hashlib.sha256(
            f"{capability_id}\n{proposal.arguments_json}".encode("utf-8")
        ).hexdigest()
        seen_action_digests[fingerprint] = seen_action_digests.get(fingerprint, 0) + 1
        action = self._actions.build_action(
            task_id=session.task_id,
            run_id=session.run_id,
            node_id=f"{turn_id}-step-{step}-action-{index}",
            capability_id=capability_id,
            principal=self._principal,
            args=arguments,
            expected=session.expected,
            envelope_id=session.envelope_id,
            risk_tier=risk_tier,
        )
        self._actions.record_action_proposed(action)
        approval = None
        if risk_tier >= 2:
            if not self._gateway.confirm(action, _action_preview(action, arguments)):
                return self._tool_message(
                    proposal,
                    {"error": "user rejected the proposed action", "rejected": True},
                )
            if risk_tier >= 3:
                approval = self._build_approval(action)
        try:
            result = self._actions.execute(
                action,
                self._principal,
                capability_spec=self._sandbox.specs().get(capability_id),
                approval=approval,
                record_artifacts=False,
            )
        except Exception as exc:
            return self._tool_message(
                proposal,
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        output = result.output
        truncated = _truncate_json(output)
        return self._tool_message(proposal, truncated)

    def _build_approval(self, action: ActionContract) -> ApprovalDecision:
        now = _session_now()
        return ApprovalDecision(
            approval_id=f"approval-{uuid4()}",
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            action_digest=action.action_digest(),
            actor_id=self._principal.principal_id,
            actor_role=self._principal.role,
            disposition=ApprovalDisposition.APPROVE,
            reason="interactive terminal approval",
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
        )

    def _tool_message(
        self, proposal: Any, payload: dict[str, Any]
    ) -> ProviderMessage:
        return ProviderMessage(
            role=ProviderMessageRole.TOOL,
            content=json.dumps(payload, default=str)[:_MAX_TOOL_RESULT_CHARS],
            tool_call_id=proposal.proposal_id,
        )

    def _trimmed_history(self) -> list[ProviderMessage]:
        history = self._history
        total = sum(len(message.content) for message in history)
        if total <= self._config.max_context_chars:
            return history
        cut = 1  # never drop the system prompt
        while cut < len(history) and total > self._config.max_context_chars:
            # Only cut at USER boundaries so ASSISTANT tool_calls and their
            # TOOL replies are never split apart.
            if history[cut].role is not ProviderMessageRole.USER:
                cut += 1
                continue
            total -= len(history[cut].content)
            cut += 1
            while (
                cut < len(history)
                and history[cut].role is not ProviderMessageRole.USER
            ):
                total -= len(history[cut].content)
                cut += 1
        return [history[0], *history[cut:]]


def _action_preview(action: ActionContract, arguments: dict[str, Any]) -> str:
    if action.capability_id in {"workspace.edit", "workspace.apply_patch"}:
        path = str(arguments.get("path", ""))
        if action.capability_id == "workspace.edit":
            old = str(arguments.get("old_string", ""))
            new = str(arguments.get("new_string", ""))
            return (
                f"edit {path}\n--- old ---\n{old[:2000]}\n--- new ---\n{new[:2000]}"
            )
        content = str(arguments.get("content", ""))
        return f"replace {path} ({len(content)} chars)\n{content[:2000]}"
    if action.capability_id in {"workspace.shell", "workspace.run_tests"}:
        return f"run command: {arguments.get('command', '')}"
    return json.dumps(arguments, default=str)[:2000]


def _truncate_json(output: dict[str, Any]) -> dict[str, Any]:
    rendered = json.dumps(output, default=str)
    if len(rendered) <= _MAX_TOOL_RESULT_CHARS:
        return output
    return {
        "truncated": True,
        "preview": rendered[:_MAX_TOOL_RESULT_CHARS],
    }


def _provider_output(response: ProviderResponse) -> dict[str, object]:
    return {
        "text": response.text,
        "tool_proposals": [
            proposal.model_dump(mode="json")
            for proposal in response.tool_proposals
        ],
        "usage": response.usage.model_dump(mode="json"),
        "finish_reason": response.finish_reason,
    }


def build_chat_envelope(
    session: ChatSession,
    *,
    tenant_id: str,
    workspace_id: str,
    budget: Any,
    now: datetime | None = None,
) -> CandidateGenerationEnvelope:
    return CandidateGenerationEnvelope(
        envelope_id=session.envelope_id,
        task_id=session.task_id,
        run_id=session.run_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        generator_id="terminal-chat-loop",
        generator_version="1",
        allowed_capability_ids=tuple(sorted(CHAT_CAPABILITY_IDS)),
        resource_budget=budget,
        candidate_ids=(),
        has_abstain=True,
        has_ask=True,
        has_no_action=True,
        created_at=now or _session_now(),
    )
