from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
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
    ProviderToolProposal,
    RunStatus,
    SessionRef,
    TaskEventType,
    TurnId,
    WorkingSetRef,
)

from .action_pipeline import ActionPipeline
from ._action_outcome import ExecutionLeaseConflict
from .capability import (
    CapabilityBroker,
    CapabilityCorrectionBlocked,
    CapabilityEffectUnknown,
    WorkspaceSandbox,
)
from .errors import ConcurrentWriteError, InvalidTransitionError, RunExecutionError
from .governance import CorrectionReadPort, PolicyKernel
from .proposal_engine import build_provider_execution_receipt
from .provider import ProviderPort
from .session_projection import (
    ProjectedApprovalContinuation,
    ProjectedResolvedContinuation,
)
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


@dataclass(frozen=True)
class ApprovalRequired(Exception):
    action: ActionContract
    preview: str


class DeferredApprovalGateway:
    """Persist the exact proposal and return control to the Surface caller."""

    def confirm(self, action: ActionContract, preview: str) -> bool:
        raise ApprovalRequired(action=action, preview=preview)


class AutoApproveGateway:
    """Test-support gateway for hermetic suites and pre-authorized batch runs.

    Auto-admits risk tier <= 2 actions with no human in the loop; tier >= 3
    still requires an explicit approval callback, so shell commands are never
    auto-approved here. This gateway is NOT used by `chat -p` (which fails
    closed via NonInteractiveDenyGateway) and must not be wired into
    interactive production paths.
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
        session: ChatSession,
        config: AgentLoopConfig | None = None,
        initial_history: tuple[ProviderMessage, ...] | None = None,
        message_sink: Callable[
            [ChatSession, int, ProviderMessage, str | None], None
        ],
        resumable_turn_ids: tuple[str, ...] = (),
    ) -> None:
        self._tasks = tasks
        self._provider = provider
        self._profile = provider_profile
        self._policy = policy
        self._correction = correction
        self._sandbox = sandbox
        self._principal = principal
        self._gateway = gateway
        self._session = session
        self._config = config or AgentLoopConfig()
        self._broker = CapabilityBroker(sandbox, correction)
        self._actions = ActionPipeline(
            tasks, self._broker, policy, correction, grants
        )
        history = (
            initial_history
            if initial_history is not None
            else (
                ProviderMessage(
                    role=ProviderMessageRole.SYSTEM,
                    content=self._config.system_prompt,
                ),
            )
        )
        system_indexes = tuple(
            index
            for index, message in enumerate(history)
            if message.role is ProviderMessageRole.SYSTEM
        )
        if (
            system_indexes != (0,)
            or history[0].content != self._config.system_prompt
        ):
            raise ValueError(
                "agent loop history requires exactly one leading frozen system prompt"
            )
        self._history = list(history)
        self._message_sink = message_sink
        self._resumable_turn_ids = set(resumable_turn_ids)
        self._execution_owner = f"surface-runtime:{uuid4()}"

    @property
    def history(self) -> tuple[ProviderMessage, ...]:
        return tuple(self._history)

    def run_turn(self, session: ChatSession, user_input: str) -> TurnResult:
        self._require_session_binding(session)
        if self._resumable_turn_ids:
            raise ValueError("session already has an open durable turn")
        run = self._tasks.get_task(session.task_id).run
        if (
            run is None
            or run.run_id != session.run_id
            or run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}
        ):
            raise InvalidTransitionError(
                "run_turn requires a runnable Run; "
                "a PAUSED or terminal Run must be resumed first"
            )
        turn_id = TurnId(
            turn_id=f"turn-{uuid4()}",
            session_id=session.session_id,
        )
        text = user_input.strip()
        if not text:
            raise ValueError("user input must be non-empty")
        self._append_message(
            session,
            ProviderMessage(role=ProviderMessageRole.USER, content=text),
            turn_id=turn_id.turn_id,
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
        self._resumable_turn_ids.add(turn_id.turn_id)
        return self.resume_turn(session, turn_id)

    def resume_turn(self, session: ChatSession, turn_id: TurnId) -> TurnResult:
        self._require_session_binding(session)
        if (
            turn_id.session_id != session.session_id
            or turn_id.turn_id not in self._resumable_turn_ids
        ):
            raise ValueError("resume requires an exact durable started turn")
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        if projected.history != tuple(self._history):
            raise InvalidTransitionError(
                "resumed turn does not bind the restored session history"
            )
        if projected.pending_continuation is not None:
            raise ValueError(
                "pending approval must resume through resume_pending_approval"
            )
        unknown = self._tasks._unknown_session_action(
            session.task_id,
            session.session_id,
        )
        if unknown is not None:
            if unknown["turn_id"] != turn_id.turn_id:
                raise InvalidTransitionError(
                    "unknown action does not bind the resumed turn"
                )
            unknown_steps = unknown["steps"]
            unknown_tokens = unknown["total_tokens"]
            if (
                isinstance(unknown_steps, bool)
                or not isinstance(unknown_steps, int)
                or isinstance(unknown_tokens, bool)
                or not isinstance(unknown_tokens, int)
            ):
                raise InvalidTransitionError(
                    "unknown action has invalid durable counters"
                )
            return TurnResult(
                turn_id=turn_id,
                text="capability effect requires external reconciliation",
                steps=unknown_steps,
                stop_reason="unknown_requires_review",
                total_tokens=unknown_tokens,
            )
        resolved = projected.resolved_continuation
        if resolved is None:
            result = self._drive(session, turn_id)
        else:
            run = self._tasks.get_task(session.task_id).run
            if (
                run is None
                or run.run_id != session.run_id
                or run.status is not RunStatus.RUNNING
            ):
                raise InvalidTransitionError(
                    "resolved continuation requires an exact RUNNING Run; "
                    "write RUN_RESUMED first"
                )
            result = self._drive_resolved_continuation(
                session,
                turn_id,
                resolved,
            )
        self._complete_turn(session, turn_id, result)
        return result

    def resume_resolved_continuation(
        self,
        session: ChatSession,
        *,
        action_digest: str,
        disposition: ApprovalDisposition,
    ) -> TurnResult:
        """Idempotently continue an already committed approval resolution."""

        self._require_session_binding(session)
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        resolved = projected.resolved_continuation
        if (
            resolved is None
            or resolved.source_action_digest != action_digest
            or resolved.disposition is not disposition
        ):
            raise InvalidTransitionError(
                "approval retry does not bind the resolved continuation"
            )
        return self.resume_turn(
            session,
            TurnId(
                turn_id=resolved.turn_id,
                session_id=session.session_id,
            ),
        )

    def _drive_resolved_continuation(
        self,
        session: ChatSession,
        turn_id: TurnId,
        resolved: ProjectedResolvedContinuation,
    ) -> TurnResult:
        if (
            resolved.turn_id != turn_id.turn_id
            or resolved.assistant_message_index >= len(self._history)
        ):
            raise InvalidTransitionError(
                "resolved continuation does not bind the resumed turn"
            )
        assistant = self._history[resolved.assistant_message_index]
        proposals = tuple(
            ProviderToolProposal(
                proposal_id=call.tool_call_id,
                capability_id=call.capability_id,
                arguments_json=call.arguments_json,
            )
            for call in assistant.tool_calls
        )
        if resolved.next_proposal_index > len(proposals):
            raise InvalidTransitionError("resolved continuation cursor is invalid")
        return self._drive(
            session,
            turn_id,
            steps=resolved.steps,
            total_tokens=resolved.total_tokens,
            seen_action_digests=dict(resolved.seen_action_digests),
            continuation=(
                proposals,
                resolved.next_proposal_index,
                resolved.assistant_message_index,
            ),
            continuation_checkpoint=resolved,
        )

    def _complete_turn(
        self,
        session: ChatSession,
        turn_id: TurnId,
        result: TurnResult,
    ) -> None:
        if result.stop_reason in {
            "approval_required",
            "unknown_requires_review",
        }:
            return
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        if projected.resumable_turn_id is None:
            self._resumable_turn_ids.discard(turn_id.turn_id)
            return
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
        self._resumable_turn_ids.remove(turn_id.turn_id)

    def resume_pending_approval(
        self,
        session: ChatSession,
        approval: ApprovalDecision,
    ) -> TurnResult:
        self._require_session_binding(session)
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        pending = projected.pending_continuation
        if pending is None:
            raise InvalidTransitionError("session has no pending approval")
        if (
            projected.history != tuple(self._history)
            or projected.resumable_turn_id != pending.turn_id
            or pending.turn_id not in self._resumable_turn_ids
        ):
            raise InvalidTransitionError(
                "pending approval does not bind the restored session history"
            )
        if (
            approval.action_digest != pending.action.action_digest()
            or approval.tenant_id != pending.action.tenant_id
            or approval.workspace_id != pending.action.workspace_id
            or approval.actor_id != self._principal.principal_id
            or approval.actor_role is not self._principal.role
            or approval.disposition
            not in {ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT}
        ):
            raise InvalidTransitionError(
                "approval decision does not bind the exact pending action"
            )
        unknown = self._tasks._unknown_session_action(
            session.task_id,
            session.session_id,
        )
        if unknown is not None:
            if (
                unknown.get("turn_id") != pending.turn_id
                or unknown.get("action_digest") != pending.action.action_digest()
            ):
                raise InvalidTransitionError(
                    "unknown action does not bind the pending approval"
                )
            unknown_steps = unknown["steps"]
            unknown_tokens = unknown["total_tokens"]
            if (
                isinstance(unknown_steps, bool)
                or not isinstance(unknown_steps, int)
                or isinstance(unknown_tokens, bool)
                or not isinstance(unknown_tokens, int)
            ):
                raise InvalidTransitionError(
                    "unknown action has invalid durable counters"
                )
            return TurnResult(
                turn_id=TurnId(
                    turn_id=pending.turn_id,
                    session_id=session.session_id,
                ),
                text="capability effect requires external reconciliation",
                steps=unknown_steps,
                stop_reason="unknown_requires_review",
                total_tokens=unknown_tokens,
            )
        self._validate_pending_runtime(
            session,
            pending,
            require_current_c7=(
                approval.disposition is ApprovalDisposition.APPROVE
            ),
        )
        current_run = self._tasks.get_task(session.task_id).run
        if current_run is None:
            raise InvalidTransitionError("pending approval requires an active Run")
        run_was_paused = current_run.status.value == "PAUSED"
        execution_lease = None
        reconciled = None
        if approval.disposition is ApprovalDisposition.APPROVE:
            try:
                reconciled = self._actions.reconcile_before_policy(
                    pending.action,
                    record_artifacts=False,
                )
            except CapabilityEffectUnknown as unknown:
                raise InvalidTransitionError(
                    "APPROVE execution claim is in progress or requires review"
                ) from unknown
            if reconciled is None:
                try:
                    execution_lease = self._sandbox.acquire_execution_lease(
                        pending.action,
                        self._execution_owner,
                    )
                except (ConcurrentWriteError, ExecutionLeaseConflict) as conflict:
                    raise InvalidTransitionError(
                        "APPROVE execution claim is still in progress"
                    ) from conflict
        try:
            authority = self._tasks.record_or_reuse_session_approval(
                session.task_id,
                session.session_id,
                pending.action,
                approval,
            )
        except Exception:
            if execution_lease is not None:
                self._sandbox.release_execution_lease(execution_lease)
            raise
        bound_approval = authority.approval
        if (
            bound_approval.disposition is ApprovalDisposition.APPROVE
            and reconciled is None
            and execution_lease is None
        ):
            try:
                reconciled = self._actions.reconcile_before_policy(
                    pending.action,
                    record_artifacts=False,
                )
            except CapabilityEffectUnknown as unknown:
                raise InvalidTransitionError(
                    "APPROVE execution claim is in progress or requires review"
                ) from unknown
            if reconciled is None:
                raise InvalidTransitionError(
                    "APPROVE execution claim is still in progress"
                )
        if bound_approval.disposition is ApprovalDisposition.REJECT:
            tool_message = self._tool_message(
                pending.proposal,
                {
                    "error": f"user rejected the proposed action: {bound_approval.reason}",
                    "rejected": True,
                },
            )
        elif reconciled is not None:
            result = reconciled
            tool_message = self._tool_message(
                pending.proposal,
                _truncate_json(result.output),
            )
        else:
            if execution_lease is None:
                raise InvalidTransitionError(
                    "APPROVE execution requires current execution ownership"
                )
            try:
                result = self._actions.execute(
                    pending.action,
                    self._principal,
                    capability_spec=self._sandbox.specs().get(
                        pending.action.capability_id
                    ),
                    approval=bound_approval,
                    record_artifacts=False,
                    execution_lease=execution_lease,
                )
            except CapabilityCorrectionBlocked as blocked:
                self._sandbox.release_execution_lease(execution_lease)
                self._tasks.pause_session_for_claim_correction(
                    session.task_id,
                    session.session_id,
                    pending=pending,
                    approval=bound_approval,
                )
                return TurnResult(
                    turn_id=TurnId(
                        turn_id=pending.turn_id,
                        session_id=session.session_id,
                    ),
                    text=str(blocked),
                    steps=pending.steps,
                    stop_reason="correction_blocked",
                    total_tokens=pending.total_tokens,
                )
            except ExecutionLeaseConflict as conflict:
                self._sandbox.release_execution_lease(execution_lease)
                raise InvalidTransitionError(
                    "APPROVE execution ownership changed before reservation"
                ) from conflict
            except CapabilityEffectUnknown as unknown:
                self._sandbox.release_execution_lease(execution_lease)
                return self._pause_for_unknown(
                    session,
                    TurnId(
                        turn_id=pending.turn_id,
                        session_id=session.session_id,
                    ),
                    pending.proposal.proposal_id,
                    unknown,
                    steps=pending.steps,
                    total_tokens=pending.total_tokens,
                )
            except Exception as exc:
                self._sandbox.release_execution_lease(execution_lease)
                tool_message = self._tool_message(
                    pending.proposal,
                    {"error": f"{type(exc).__name__}: {exc}"},
                )
            else:
                self._sandbox.release_execution_lease(execution_lease)
                tool_message = self._tool_message(
                    pending.proposal,
                    _truncate_json(result.output),
                )
        self._tasks.resolve_session_approval(
            session.task_id,
            session.session_id,
            pending=pending,
            approval=bound_approval,
            tool_message=tool_message,
        )
        self._history.append(tool_message)
        turn_id = TurnId(
            turn_id=pending.turn_id,
            session_id=session.session_id,
        )
        if (
            run_was_paused
            and bound_approval.disposition is ApprovalDisposition.REJECT
        ):
            return TurnResult(
                turn_id=turn_id,
                text="action rejected; Run remains paused",
                steps=pending.steps,
                stop_reason="paused",
                total_tokens=pending.total_tokens,
            )
        return self.resume_turn(session, turn_id)

    def _validate_pending_runtime(
        self,
        session: ChatSession,
        pending: ProjectedApprovalContinuation,
        *,
        require_current_c7: bool,
    ) -> None:
        aggregate = self._tasks.get_task(session.task_id)
        run = aggregate.run
        snapshot = aggregate.configuration_snapshot
        if (
            run is None
            or snapshot is None
            or (
                require_current_c7
                and run.status.value != "WAITING_APPROVAL"
            )
            or (
                not require_current_c7
                and run.status.value not in {"WAITING_APPROVAL", "PAUSED"}
            )
            or run.run_id != session.run_id
            or run.configuration_snapshot_id
            != pending.configuration_snapshot_id
            or run.configuration_snapshot_digest
            != pending.configuration_snapshot_digest
            or snapshot.snapshot_id != pending.configuration_snapshot_id
            or snapshot.snapshot_digest != pending.configuration_snapshot_digest
            or snapshot.provider_profile.profile_id != pending.provider_profile_id
            or snapshot.provider_profile_digest != pending.provider_profile_digest
            or self._profile.profile_id != pending.provider_profile_id
            or self._profile != snapshot.provider_profile
        ):
            raise InvalidTransitionError(
                "pending approval configuration/provider binding mismatch"
            )
        if not require_current_c7:
            return
        current_epochs = self._correction.snapshot(
            session.task_id,
            session.run_id,
            pending.action.capability_id,
        )
        if (
            current_epochs != pending.action.observed_correction_epochs
            or self._correction.halted(
                session.task_id,
                session.run_id,
                pending.action.capability_id,
            )
        ):
            raise InvalidTransitionError(
                "pending approval C7 correction epochs are stale"
            )

    def _require_session_binding(self, session: ChatSession) -> None:
        if session != self._session:
            raise ValueError("chat session binding mismatch")

    def _drive(
        self,
        session: ChatSession,
        turn_id: TurnId,
        *,
        steps: int = 0,
        total_tokens: int = 0,
        seen_action_digests: dict[str, int] | None = None,
        continuation: tuple[
            tuple[ProviderToolProposal, ...],
            int,
            int,
        ]
        | None = None,
        continuation_checkpoint: ProjectedResolvedContinuation | None = None,
    ) -> TurnResult:
        final_text = ""
        seen_action_digests = dict(seen_action_digests or {})
        stop_reason = "max_steps"
        while steps < self._config.max_steps_per_turn:
            if continuation is None:
                if self._correction.halted(
                    session.task_id, session.run_id, "provider"
                ):
                    stop_reason = "correction_halted"
                    break
                run = self._tasks.get_task(session.task_id).run
                if (
                    run is None
                    or run.run_id != session.run_id
                    or run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}
                ):
                    raise InvalidTransitionError(
                        "provider invocation requires a runnable Run; "
                        "a PAUSED or terminal Run must be resumed first"
                    )
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
                assistant_message_index = len(self._history)
                assistant_message = ProviderMessage(
                    role=ProviderMessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=tool_calls,
                )
                if not response.tool_proposals:
                    stop_reason = "completed"
                    final_text = response.text
                    self._tasks.record_session_final_message_and_complete(
                        session.task_id,
                        session.session_id,
                        turn_id=turn_id.turn_id,
                        message=assistant_message,
                        stop_reason=stop_reason,
                        steps=steps,
                        total_tokens=total_tokens,
                    )
                    self._history.append(assistant_message)
                    break
                continuation_checkpoint = self._append_turn_progress(
                    session,
                    turn_id=turn_id.turn_id,
                    message=assistant_message,
                    continuation=continuation_checkpoint,
                    assistant_message_index=assistant_message_index,
                    next_proposal_index=0,
                    steps=steps,
                    total_tokens=total_tokens,
                    seen_action_digests=seen_action_digests,
                )
                proposals = response.tool_proposals
                start_index = 0
            else:
                proposals, start_index, assistant_message_index = continuation
                continuation = None
            replied_proposal_ids: set[str] = {
                proposal.proposal_id for proposal in proposals[:start_index]
            }
            for index in range(start_index, len(proposals)):
                proposal = proposals[index]
                capability_id = proposal.capability_id
                if capability_id not in CHAT_CAPABILITY_IDS:
                    stop_reason = "unauthorized_proposal"
                    final_text = (
                        f"provider proposed unauthorized capability {capability_id}"
                    )
                    break
                try:
                    tool_message = self._execute_proposal(
                        session,
                        turn_id.turn_id,
                        steps,
                        index,
                        proposal,
                        seen_action_digests,
                    )
                except CapabilityEffectUnknown as unknown:
                    return self._pause_for_unknown(
                        session,
                        turn_id,
                        proposal.proposal_id,
                        unknown,
                        steps=steps,
                        total_tokens=total_tokens,
                    )
                except ApprovalRequired as required:
                    self._tasks.record_session_approval_pending(
                        session.task_id,
                        session.session_id,
                        turn_id=turn_id.turn_id,
                        action=required.action,
                        proposal=proposal,
                        preview=required.preview,
                        assistant_message_index=assistant_message_index,
                        proposal_index=index,
                        steps=steps,
                        total_tokens=total_tokens,
                        seen_action_digests=seen_action_digests,
                    )
                    return TurnResult(
                        turn_id=turn_id,
                        text="approval required",
                        steps=steps,
                        stop_reason="approval_required",
                        total_tokens=total_tokens,
                    )
                continuation_checkpoint = self._append_turn_progress(
                    session,
                    turn_id=turn_id.turn_id,
                    message=tool_message,
                    continuation=continuation_checkpoint,
                    assistant_message_index=assistant_message_index,
                    next_proposal_index=index + 1,
                    steps=steps,
                    total_tokens=total_tokens,
                    seen_action_digests=seen_action_digests,
                )
                replied_proposal_ids.add(proposal.proposal_id)
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
                # Never leave dangling ASSISTANT tool_calls in history: a real
                # provider rejects tool_calls without matching TOOL replies
                # (HTTP 400), which would make the session unrecoverable.
                for proposal_index, proposal in enumerate(proposals):
                    if proposal.proposal_id not in replied_proposal_ids:
                        denial_message = self._tool_message(
                            proposal,
                            {"error": f"not executed: {stop_reason}"},
                        )
                        continuation_checkpoint = self._append_turn_progress(
                            session,
                            turn_id=turn_id.turn_id,
                            message=denial_message,
                            continuation=continuation_checkpoint,
                            assistant_message_index=assistant_message_index,
                            next_proposal_index=proposal_index + 1,
                            steps=steps,
                            total_tokens=total_tokens,
                            seen_action_digests=seen_action_digests,
                        )
                break
        return TurnResult(
            turn_id=turn_id,
            text=final_text,
            steps=steps,
            stop_reason=stop_reason,
            total_tokens=total_tokens,
        )

    def _pause_for_unknown(
        self,
        session: ChatSession,
        turn_id: TurnId,
        proposal_id: str,
        unknown: CapabilityEffectUnknown,
        *,
        steps: int,
        total_tokens: int,
    ) -> TurnResult:
        self._tasks.pause_session_for_unknown_action(
            session.task_id,
            session.session_id,
            turn_id=turn_id.turn_id,
            proposal_id=proposal_id,
            action=unknown.action,
            steps=steps,
            total_tokens=total_tokens,
        )
        return TurnResult(
            turn_id=turn_id,
            text=str(unknown),
            steps=steps,
            stop_reason="unknown_requires_review",
            total_tokens=total_tokens,
        )

    def _append_message(
        self,
        session: ChatSession,
        message: ProviderMessage,
        *,
        turn_id: str | None,
    ) -> None:
        index = len(self._history)
        self._message_sink(session, index, message, turn_id)
        self._history.append(message)

    def _append_continuation_message(
        self,
        session: ChatSession,
        *,
        turn_id: str,
        message: ProviderMessage,
        continuation: ProjectedResolvedContinuation,
        assistant_message_index: int,
        next_proposal_index: int,
        steps: int,
        total_tokens: int,
        seen_action_digests: dict[str, int],
    ) -> ProjectedResolvedContinuation:
        self._tasks.record_session_continuation_message(
            session.task_id,
            session.session_id,
            turn_id=turn_id,
            message=message,
            continuation=continuation,
            assistant_message_index=assistant_message_index,
            next_proposal_index=next_proposal_index,
            steps=steps,
            total_tokens=total_tokens,
            seen_action_digests=seen_action_digests,
        )
        self._history.append(message)
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        advanced = projected.resolved_continuation
        if advanced is None:
            raise InvalidTransitionError(
                "continuation checkpoint disappeared after durable append"
            )
        return advanced

    def _append_turn_progress(
        self,
        session: ChatSession,
        *,
        turn_id: str,
        message: ProviderMessage,
        continuation: ProjectedResolvedContinuation | None,
        assistant_message_index: int,
        next_proposal_index: int,
        steps: int,
        total_tokens: int,
        seen_action_digests: dict[str, int],
    ) -> ProjectedResolvedContinuation | None:
        if continuation is None:
            self._append_message(session, message, turn_id=turn_id)
            return None
        return self._append_continuation_message(
            session,
            turn_id=turn_id,
            message=message,
            continuation=continuation,
            assistant_message_index=assistant_message_index,
            next_proposal_index=next_proposal_index,
            steps=steps,
            total_tokens=total_tokens,
            seen_action_digests=seen_action_digests,
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
        approval = None
        if risk_tier >= 2:
            confirmed = self._gateway.confirm(
                action,
                _action_preview(action, arguments),
            )
            self._actions.record_action_proposed(action)
            if not confirmed:
                self._record_denial(session, action)
                return self._tool_message(
                    proposal,
                    {"error": "user rejected the proposed action", "rejected": True},
                )
            if risk_tier >= 3:
                approval = self._build_approval(action)
        else:
            self._actions.record_action_proposed(action)
        try:
            result = self._actions.execute(
                action,
                self._principal,
                capability_spec=self._sandbox.specs().get(capability_id),
                approval=approval,
                record_artifacts=False,
            )
        except CapabilityEffectUnknown:
            raise
        except Exception as exc:
            return self._tool_message(
                proposal,
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        output = result.output
        truncated = _truncate_json(output)
        return self._tool_message(proposal, truncated)

    def _record_denial(self, session: ChatSession, action: ActionContract) -> None:
        """Durably record that the principal declined this exact proposed action."""
        now = _session_now()
        denial = ApprovalDecision(
            approval_id=f"approval-{uuid4()}",
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            action_digest=action.action_digest(),
            actor_id=self._principal.principal_id,
            actor_role=self._principal.role,
            disposition=ApprovalDisposition.REJECT,
            reason="interactive terminal denial",
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        self._tasks.record_approval(session.task_id, denial)

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
