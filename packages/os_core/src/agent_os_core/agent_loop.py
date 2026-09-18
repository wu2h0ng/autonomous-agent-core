from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ApprovalDecision,
    ApprovalDisposition,
    BindingStatus,
    CandidateGenerationEnvelope,
    ExpectedOutcome,
    PermissionMode,
    PrincipalIdentity,
    PrincipalRole,
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

from .action_pipeline import ActionPipeline, EffectCustodyPort
from ._action_outcome import ExecutionLeaseConflict
from .capability import (
    CapabilityBroker,
    CapabilityCorrectionBlocked,
    CapabilityEffectUnknown,
    CapabilityPort,
    CapabilityResult,
    CollaborationPreflightPort,
)
from .errors import ConcurrentWriteError, InvalidTransitionError, RunExecutionError
from .governance import CorrectionReadPort, PolicyKernel
from .permission_gate import (
    ACTION_RISK_TIERS,
    PermissionGateOutcome,
    apply_deny_rules,
    evaluate_permission_gate,
)
from .permission_rules import PermissionDenyRule, active_deny_rule
from .proposal_engine import build_provider_execution_receipt
from .provider import ProviderPort
from .responsibility_loop import ResponsibilityLoopStaleFence
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
    "session.todo_write",
)

# Action risk tiers live in permission_gate (frozen allowlist, E2); tier >= 3
# escalates inside PolicyKernel and requires a digest-bound ApprovalDecision;
# tier 2 is kernel-allowed but still passes through the interactive
# confirmation gateway unless the session permission mode policy auto-allows
# it.

# Grant risk ceilings the chat composition must provide per capability.
CHAT_GRANT_MAX_RISK_TIERS: dict[str, int] = {
    "workspace.read": 1,
    "workspace.search": 1,
    "workspace.run_tests": 1,
    "session.todo_write": 1,
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
    "edits. For multi-step work, maintain a structured task list with "
    "session.todo_write (full-replace semantics: submit the complete list "
    "every call). If a tool result reports an error, adjust and retry with "
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
    auto-approved here. It is currently also wired for the non-interactive
    one-shot `-p` path (tier <= 2 auto-approve; tier >= 3 fails closed), and
    must not be wired into interactive production paths.
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
    stream: bool = True


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
        connector: CapabilityPort,
        grants: dict[str, Any],
        principal: PrincipalIdentity,
        gateway: ConfirmationGateway,
        session: ChatSession,
        config: AgentLoopConfig | None = None,
        initial_history: tuple[ProviderMessage, ...] | None = None,
        message_sink: Callable[[ChatSession, int, ProviderMessage, str | None], None],
        resumable_turn_ids: tuple[str, ...] = (),
        execution_fence: Callable[[str], None] | None = None,
        effect_custody: EffectCustodyPort | None = None,
        independent_approval: bool = False,
        external_exact_approval: bool = False,
        collaboration_preflight: CollaborationPreflightPort | None = None,
        text_delta_sink: Callable[[str], None] | None = None,
        reasoning_delta_sink: Callable[[str], None] | None = None,
        permission_mode: PermissionMode = "ASK",
        permission_mode_event_id: str | None = None,
        deny_rules: Sequence[PermissionDenyRule] = (),
    ) -> None:
        self._tasks = tasks
        self._provider = provider
        self._profile = provider_profile
        self._policy = policy
        self._correction = correction
        self._sandbox = connector
        self._principal = principal
        self._gateway = gateway
        self._session = session
        self._config = config or AgentLoopConfig()
        self._broker = CapabilityBroker(
            connector, correction, collaboration_preflight=collaboration_preflight
        )
        self._actions = ActionPipeline(tasks, self._broker, policy, correction, grants)
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
        if system_indexes != (0,) or history[0].content != self._config.system_prompt:
            raise ValueError(
                "agent loop history requires exactly one leading frozen system prompt"
            )
        self._history = list(history)
        self._message_sink = message_sink
        self._resumable_turn_ids = set(resumable_turn_ids)
        self._execution_owner = f"surface-runtime:{uuid4()}"
        self._execution_fence = execution_fence
        self._effect_custody = effect_custody
        self._independent_approval = independent_approval
        self._external_exact_approval = external_exact_approval
        self._text_delta_sink = text_delta_sink
        self._reasoning_delta_sink = reasoning_delta_sink
        self._permission_mode: PermissionMode = permission_mode
        self._permission_mode_event_id = permission_mode_event_id
        self._deny_rules = tuple(deny_rules)
        self._last_compaction: tuple[object, ...] | None = None

    @property
    def history(self) -> tuple[ProviderMessage, ...]:
        return tuple(self._history)

    def _assert_execution_fence(self, phase: str) -> None:
        if self._execution_fence is not None:
            self._execution_fence(phase)

    def _operator_stopped(self, session: ChatSession) -> bool:
        """Whether the operator durably stopped this session's Run.

        The stop is the durable Run transition (`RUN_PAUSED` -> PAUSED), not an
        in-memory flag, so a pause issued by any client or process stops the
        in-flight turn at its next safe point. A Run that is already PAUSED
        before the turn starts never reaches the loop: `run_turn` refuses it.
        """
        run = self._tasks.get_task(session.task_id).run
        return (
            run is not None
            and run.run_id == session.run_id
            and run.status is RunStatus.PAUSED
        )

    def _durable_write(self, write: Callable[[], _WriteT]) -> _WriteT:
        """Run one durable write of this turn, absorbing a bounded append race.

        The operator's stop appends `RUN_PAUSED` to the same optimistic event
        stream the in-flight turn writes to, so a turn record can lose the
        sequence race against the very command that is stopping it (measured:
        the TOOL reply append lost and the turn ended uncommitted). A losing
        attempt wrote nothing, and each attempt re-reads durable truth, so a
        retry cannot duplicate an effect. Every other rejection propagates.
        """
        attempts = 5
        for attempt in range(attempts):
            try:
                return write()
            except ConcurrentWriteError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.02)
        raise AssertionError("unreachable")  # pragma: no cover - loop returns or raises

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
        self._durable_write(
            lambda: self._tasks.append_event(
                session.task_id,
                TaskEventType.SESSION_TURN_STARTED,
                {
                    "turn_id": turn_id.turn_id,
                    "session_id": turn_id.session_id,
                    "user_text": text,
                },
                correlation_id=session.run_id,
            )
        )
        self._resumable_turn_ids.add(turn_id.turn_id)
        return self.resume_turn(session, turn_id, started_here=True)

    def resume_turn(
        self,
        session: ChatSession,
        turn_id: TurnId,
        *,
        started_here: bool = False,
    ) -> TurnResult:
        """Drive one durable open turn.

        `started_here` marks a turn whose durable `SESSION_TURN_STARTED` was
        written by *this* call (`run_turn`): only then may a Run that turned
        PAUSED in between be treated as the end of that same turn. A restored
        turn (`started_here=False`) belongs to an earlier process and stays
        fail-closed.
        """

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
            run = self._tasks.get_task(session.task_id).run
            if (
                run is None
                or run.run_id != session.run_id
                or run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}
            ):
                if (
                    started_here
                    and run is not None
                    and run.run_id == session.run_id
                    and run.status is RunStatus.PAUSED
                ):
                    # The operator's stop won the race for this turn's own first
                    # writes: `run_turn` had already read a runnable Run, and the
                    # pause became durable before this call committed the turn
                    # start. The turn is durable and the provider was never
                    # called, so it must end durably here as
                    # `stopped_by_operator`. Raising instead would leave this
                    # SESSION_TURN_STARTED without its SESSION_TURN_COMPLETED, and
                    # "uncommitted turn" is exactly that difference - every later
                    # begin-turn on the session would fail SurfaceTurnInProgress,
                    # so the stop would brick the session it stopped. The refusal
                    # that follows is for a *restored* turn (another process's
                    # durable turn, `started_here=False`): it must not be consumed
                    # by a resume while the Run is PAUSED.
                    stopped = TurnResult(
                        turn_id=turn_id,
                        text=_STOPPED_BY_OPERATOR_TEXT,
                        steps=0,
                        stop_reason="stopped_by_operator",
                        total_tokens=0,
                    )
                    self._complete_turn(session, turn_id, stopped)
                    return stopped
                # Fail closed before any provider call, and before the durable
                # turn can be consumed by a resume: a Run that is already PAUSED
                # (or terminal) must be resumed explicitly first. The mid-turn
                # stop is the other direction - the pause arrives *after* this
                # check, and `_drive` winds the turn down at its next safe point.
                raise InvalidTransitionError(
                    "resume requires a runnable Run; "
                    "a PAUSED or terminal Run must be resumed first"
                )
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
        if result.stop_reason == "approval_required":
            return
        projected = self._tasks.project_session(
            session.task_id,
            session.session_id,
        )
        if result.stop_reason == "unknown_requires_review" and (
            projected.pending_continuation is not None
            or _has_unanswered_tool_calls(projected.history)
        ):
            # S2: an unknown effect ends the turn truthfully - it is never a
            # success, the Run stays PAUSED, and the durable pause blocks every
            # automatic resume until an external reconciliation. The turn is
            # only left open when a parked approval owns an unanswered tool
            # call: only a human APPROVE/REJECT may resolve that one, and the
            # session projection forbids completing a turn with an unanswered
            # tool call or an unresolved approval.
            return
        if projected.resumable_turn_id is None:
            self._resumable_turn_ids.discard(turn_id.turn_id)
            return
        self._assert_execution_fence("before_turn_commit")
        self._durable_write(
            lambda: self._tasks.append_event(
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
            or approval.disposition
            not in {ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT}
        ):
            raise InvalidTransitionError(
                "approval decision does not bind the exact pending action"
            )
        if self._independent_approval:
            # SELFDEV mode: the deciding actor must be an external operator,
            # never the principal that proposed the action (main lineage).
            if (
                approval.actor_id == pending.action.principal_id
                or approval.actor_role is not PrincipalRole.TENANT_ADMIN
            ):
                raise InvalidTransitionError(
                    "approval decision is not independently authorized"
                )
        elif (
            approval.actor_id != self._principal.principal_id
            or approval.actor_role is not self._principal.role
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
        # Fail closed: a durable operator DENY rule forbids *executing* a previously
        # escalated pending action. Only APPROVE executes, so only APPROVE is
        # blocked — a REJECT is always safe and must stay resolvable (no wedging).
        if approval.disposition is ApprovalDisposition.APPROVE:
            deny_rule = active_deny_rule(
                self._deny_rules,
                pending.action.capability_id,
                self._principal.tenant_id,
                self._principal.workspace_id,
            )
            if deny_rule is not None:
                self._record_policy_verdict(
                    session,
                    pending.action,
                    verdict="DENY",
                    basis="rule",
                    reason="denied by an operator permission rule",
                    rule_id=deny_rule.rule_id,
                    rule_reason=deny_rule.reason,
                )
                raise RunExecutionError(
                    "denied by an operator permission rule: pending action is blocked"
                )
        self._validate_pending_runtime(
            session,
            pending,
            require_current_c7=(approval.disposition is ApprovalDisposition.APPROVE),
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
            authority = self._durable_write(
                lambda: self._tasks.record_or_reuse_session_approval(
                    session.task_id,
                    session.session_id,
                    pending.action,
                    approval,
                )
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

            def resume_dispatch() -> CapabilityResult:
                return self._actions.execute(
                    pending.action,
                    self._principal,
                    capability_spec=self._sandbox.specs().get(
                        pending.action.capability_id
                    ),
                    approval=bound_approval,
                    record_artifacts=False,
                    execution_claim=execution_lease,
                    execution_fence=self._assert_execution_fence,
                )

            try:
                result = (
                    self._effect_custody(
                        pending.action.node_id,
                        pending.action.action_digest(),
                        resume_dispatch,
                    )
                    if self._effect_custody is not None
                    else resume_dispatch()
                )
            except ResponsibilityLoopStaleFence:
                raise
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
                # Same durable signal as the unapproved path: an approved call
                # that the capability layer still refuses (the file turned
                # read-only, the digest changed between approval and dispatch)
                # sealed nothing, so the card it created must not stay pending.
                self._record_tool_failure(
                    pending.action, pending.proposal.proposal_id, exc
                )
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
        self._durable_write(
            lambda: self._tasks.resolve_session_approval(
                session.task_id,
                session.session_id,
                pending=pending,
                approval=bound_approval,
                tool_message=tool_message,
            )
        )
        self._history.append(tool_message)
        turn_id = TurnId(
            turn_id=pending.turn_id,
            session_id=session.session_id,
        )
        if run_was_paused and bound_approval.disposition is ApprovalDisposition.REJECT:
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
            or (require_current_c7 and run.status.value != "WAITING_APPROVAL")
            or (
                not require_current_c7
                and run.status.value not in {"WAITING_APPROVAL", "PAUSED"}
            )
            or run.run_id != session.run_id
            or run.configuration_snapshot_id != pending.configuration_snapshot_id
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
                if self._correction.halted(session.task_id, session.run_id, "provider"):
                    stop_reason = "correction_halted"
                    break
                run = self._tasks.get_task(session.task_id).run
                if run is None or run.run_id != session.run_id:
                    raise InvalidTransitionError(
                        "provider invocation requires the session's exact Run"
                    )
                if run.status is RunStatus.PAUSED:
                    # The operator durably stopped this session mid-turn. Wind
                    # the turn down truthfully instead of raising: the provider
                    # is not called again and the turn ends as stopped_by_operator.
                    stop_reason = "stopped_by_operator"
                    final_text = _STOPPED_BY_OPERATOR_TEXT
                    break
                if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                    raise InvalidTransitionError(
                        "provider invocation requires a runnable Run; "
                        "a terminal Run cannot continue a turn"
                    )
                self._assert_execution_fence("before_provider")
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
                self._assert_execution_fence("before_provider_commit")
                assistant_message_index = len(self._history)
                assistant_message = ProviderMessage(
                    role=ProviderMessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=tool_calls,
                )
                if not response.tool_proposals:
                    stop_reason = "completed"
                    final_text = response.text
                    self._durable_write(
                        lambda: self._tasks.record_session_final_message_and_complete(
                            session.task_id,
                            session.session_id,
                            turn_id=turn_id.turn_id,
                            message=assistant_message,
                            stop_reason=stop_reason,
                            steps=steps,
                            total_tokens=total_tokens,
                        )
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
                if self._operator_stopped(session):
                    # A durable operator pause arrived while this message's
                    # proposals were being executed: dispatch nothing further.
                    # The replies below answer every unanswered tool call, so
                    # the transcript stays valid for the next turn.
                    stop_reason = "stopped_by_operator"
                    final_text = _STOPPED_BY_OPERATOR_TEXT
                    break
                proposal = proposals[index]
                capability_id = proposal.capability_id
                if capability_id not in CHAT_CAPABILITY_IDS:
                    # Fail closed in every mode: never executable, not
                    # approvable. The denial is recorded durably (E2) with
                    # reason and digest before the turn stops.
                    self._record_out_of_allowlist_denial(session, proposal)
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
                    # S2 fail-closed, but honest and terminal: a post-dispatch
                    # unknown is never a success and is never auto-retried, yet
                    # the turn must still conclude visibly. Answer the
                    # outstanding tool call with the reason, answer the
                    # proposals of this message that will not run (a provider
                    # rejects unanswered tool_calls), then stop on the durable
                    # unknown pause.
                    continuation_checkpoint = self._append_turn_progress(
                        session,
                        turn_id=turn_id.turn_id,
                        message=self._unknown_tool_message(proposal, unknown),
                        continuation=continuation_checkpoint,
                        assistant_message_index=assistant_message_index,
                        next_proposal_index=index + 1,
                        steps=steps,
                        total_tokens=total_tokens,
                        seen_action_digests=seen_action_digests,
                    )
                    replied_proposal_ids.add(proposal.proposal_id)
                    for remaining_index in range(index + 1, len(proposals)):
                        remaining = proposals[remaining_index]
                        continuation_checkpoint = self._append_turn_progress(
                            session,
                            turn_id=turn_id.turn_id,
                            message=self._tool_message(
                                remaining,
                                {
                                    "error": _NOT_EXECUTED_AFTER_UNKNOWN,
                                    "not_executed": True,
                                },
                            ),
                            continuation=continuation_checkpoint,
                            assistant_message_index=assistant_message_index,
                            next_proposal_index=remaining_index + 1,
                            steps=steps,
                            total_tokens=total_tokens,
                            seen_action_digests=seen_action_digests,
                        )
                        replied_proposal_ids.add(remaining.proposal_id)
                    return self._pause_for_unknown(
                        session,
                        turn_id,
                        proposal.proposal_id,
                        unknown,
                        steps=steps,
                        total_tokens=total_tokens,
                    )
                except ApprovalRequired as required:
                    approval_action = required.action
                    approval_preview = required.preview
                    self._durable_write(
                        lambda: self._tasks.record_session_approval_pending(
                            session.task_id,
                            session.session_id,
                            turn_id=turn_id.turn_id,
                            action=approval_action,
                            proposal=proposal,
                            preview=approval_preview,
                            assistant_message_index=assistant_message_index,
                            proposal_index=index,
                            steps=steps,
                            total_tokens=total_tokens,
                            seen_action_digests=seen_action_digests,
                        )
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
                "stopped_by_operator",
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

    def _unknown_tool_message(
        self,
        proposal: Any,
        unknown: CapabilityEffectUnknown,
    ) -> ProviderMessage:
        """The model-visible result of a dispatched action whose effect is
        unknown: the reason, the review requirement, and the explicit statement
        that the action was not retried.

        Host absolute paths are dropped from the model-visible detail; the
        operator-facing text keeps them.
        """
        return self._tool_message(
            proposal,
            {
                "error": _unknown_review_text(
                    unknown,
                    _model_visible_unknown_detail(unknown),
                ),
                "effect_unknown": True,
                "dispatched": True,
                "auto_retry": False,
                "requires_human_review": True,
                "reason_code": unknown.reason_code,
                "action_digest": unknown.action_digest,
                "reservation_id": unknown.reservation_id,
                "stop_reason": "unknown_requires_review",
            },
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
        self._durable_write(
            lambda: self._tasks.pause_session_for_unknown_action(
                session.task_id,
                session.session_id,
                turn_id=turn_id.turn_id,
                proposal_id=proposal_id,
                action=unknown.action,
                steps=steps,
                total_tokens=total_tokens,
            )
        )
        return TurnResult(
            turn_id=turn_id,
            text=_unknown_review_text(unknown, unknown.detail),
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
        self._durable_write(
            lambda: self._message_sink(session, index, message, turn_id)
        )
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
        self._durable_write(
            lambda: self._tasks.record_session_continuation_message(
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

    def _emit_text_delta(self, delta: str) -> None:
        """Forward one transient provider chunk to the display sink.

        Frozen (E1): chunks are transient display events, never durable
        truth; a display-path failure must never fail the durable turn."""
        sink = self._text_delta_sink
        if sink is None or not delta:
            return
        try:
            sink(delta)
        except Exception:  # noqa: BLE001 - transient display path only
            return

    def _emit_reasoning_delta(self, delta: str) -> None:
        """Forward one transient provider reasoning chunk (display-only).

        Frozen (E1): reasoning is transient, never durable and never part of
        the assistant message or evidence; a display failure is swallowed."""
        sink = self._reasoning_delta_sink
        if sink is None or not delta:
            return
        try:
            sink(delta)
        except Exception:  # noqa: BLE001 - transient display path only
            return

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
            if self._correction.halted(session.task_id, session.run_id, "provider"):
                raise RunExecutionError("chat provider invocation is correction halted")
            messages, compaction = self._compact_history()
            self._maybe_record_compaction(session, compaction)
            request = ProviderRequest(
                request_id=f"request-{uuid4()}",
                task_id=session.task_id,
                run_id=session.run_id,
                provider_profile_id=self._profile.profile_id,
                messages=tuple(messages),
                allowed_capability_ids=CHAT_CAPABILITY_IDS,
                timeout_seconds=self._profile.request_timeout_seconds,
                created_at=_session_now(),
            )
            response = self._provider.complete_streaming(
                request,
                on_text_delta=self._emit_text_delta,
                on_reasoning_delta=self._emit_reasoning_delta,
            )
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
                or response.invocation_binding_digest != invocation_binding_digest
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
                        gap_reason=("terminal chat has no TrustedWorkingSet binding"),
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

    def _record_tool_failure(
        self,
        action: ActionContract,
        provider_tool_call_id: str,
        exc: BaseException,
    ) -> None:
        """Durable node-level failure for a tool call that sealed no result.

        A refusal taken before dispatch produces no receipt (a receipt attests
        that a dispatch executed, and none did) and no `NODE_COMPLETED`
        (nothing completed), so the durable stream held nothing at all for it:
        the model was told through the tool result, but every operator surface
        that projects the stream - the TUI tool card, `/export` - showed a call
        that stayed pending forever with no reason. The reason is recorded here
        as a node-level failure instead. This is not a receipt and it does not
        change receipt semantics: no reservation, no seal, no
        `ACTION_RECEIPT_RECORDED`, and the Run is untouched.

        Only failures the broker did not convert into a typed UNKNOWN reach
        this path (ADR-0059 turns every post-dispatch failure into one), so the
        event claims exactly what the loop knows: this proposal produced no
        sealed result, and this is why.
        """

        self._durable_write(
            lambda: self._tasks.append_event(
                action.task_id,
                TaskEventType.NODE_FAILED,
                {
                    "node_id": action.node_id,
                    "action_id": action.action_id,
                    "provider_tool_call_id": provider_tool_call_id,
                    "agent_loop_dynamic_action": True,
                    "capability_id": action.capability_id,
                    "action_digest": action.action_digest(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "exception": type(exc).__name__,
                    "error_code": f"error:{type(exc).__name__}",
                },
                correlation_id=action.run_id,
            )
        )

    def _record_tool_completion(
        self,
        action: ActionContract,
        provider_tool_call_id: str,
        output: dict[str, Any],
    ) -> None:
        self._durable_write(
            lambda: self._tasks.append_event(
                action.task_id,
                TaskEventType.NODE_COMPLETED,
                {
                    "node_id": action.node_id,
                    "action_id": action.action_id,
                    "provider_tool_call_id": provider_tool_call_id,
                    "agent_loop_dynamic_action": True,
                    "output": output,
                },
                correlation_id=action.run_id,
            )
        )

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
            approval_requirement=(
                "external_exact" if self._external_exact_approval else "policy"
            ),
        )
        approval = None
        gate = evaluate_permission_gate(
            capability_id=capability_id,
            mode=self._permission_mode,
            mode_event_id=self._permission_mode_event_id,
        )
        # Purely-restrictive operator DENY rules (S2): they can only downgrade the
        # frozen matrix to DENY_BY_RULE; they can never allow or pre-empt C7.
        gate = apply_deny_rules(
            gate,
            capability_id=capability_id,
            rules=self._deny_rules,
            tenant_id=self._principal.tenant_id,
            workspace_id=self._principal.workspace_id,
        )
        if gate.outcome in (
            PermissionGateOutcome.DENY_OUT_OF_ALLOWLIST,
            PermissionGateOutcome.DENY_BY_RULE,
        ):
            # Fail closed in every mode: never executable, not approvable.
            # No ApprovalDecision, human or otherwise, can authorize it; the
            # denial is recorded durably with reason and the action digest.
            denied_by_rule = gate.outcome is PermissionGateOutcome.DENY_BY_RULE
            self._record_policy_verdict(
                session,
                action,
                verdict="DENY",
                basis="rule" if denied_by_rule else "out_of_allowlist",
                reason=(
                    "denied by an operator permission rule"
                    if denied_by_rule
                    else "capability is outside the frozen session allowlist"
                ),
                rule_id=gate.rule_id if denied_by_rule else None,
                rule_reason=gate.rule_reason if denied_by_rule else None,
            )
            # The model-visible result names the refusal and, for a rule denial,
            # the rule it came from: an unnamed "a rule forbids this" left the
            # model free to report success for work that never happened.
            return self._tool_message(
                proposal,
                {
                    "error": (
                        f"denied: operator permission rule {gate.rule_id} "
                        f"forbids {capability_id}"
                        if denied_by_rule
                        else "denied: capability is outside the allowlist"
                    ),
                    "denied": True,
                    "executed": False,
                    "basis": "rule" if denied_by_rule else "out_of_allowlist",
                    "rule_id": gate.rule_id if denied_by_rule else None,
                    "capability_id": capability_id,
                },
            )
        if gate.outcome is PermissionGateOutcome.REQUIRE_CONFIRM:
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
            if gate.risk_tier >= 3:
                approval = self._build_approval(action)
        else:
            self._actions.record_action_proposed(action)
            if gate.outcome is PermissionGateOutcome.MODE_AUTO_ALLOW:
                # Durable policy allowance with provenance — NEVER an
                # ApprovalDecision(APPROVE): a permission mode is prior
                # session policy, not per-action human approval.
                self._record_policy_verdict(
                    session,
                    action,
                    verdict="ALLOW",
                    basis="permission_mode",
                    reason=None,
                    mode_event_id=gate.mode_event_id,
                )
        # Replay-before-dispatch: a sealed or reserved action is resolved
        # through the durable outcome repository and never re-dispatched.
        reconciled = self._actions.reconcile_before_policy(
            action,
            record_artifacts=False,
        )
        if reconciled is not None:
            self._record_tool_completion(
                action,
                proposal.proposal_id,
                reconciled.output,
            )
            return self._tool_message(
                proposal,
                _truncate_json(reconciled.output),
            )
        # ADR-0059: every production dispatch carries an execution claim
        # bound to the durable run lease (founder P1).
        execution_lease = self._sandbox.acquire_execution_lease(
            action, self._execution_owner
        )

        def dispatch() -> CapabilityResult:
            return self._actions.execute(
                action,
                self._principal,
                capability_spec=self._sandbox.specs().get(capability_id),
                approval=approval,
                record_artifacts=False,
                execution_claim=execution_lease,
                execution_fence=self._assert_execution_fence,
            )

        try:
            self._assert_execution_fence("before_tool_effect")
            result = (
                self._effect_custody(
                    action.node_id,
                    action.action_digest(),
                    dispatch,
                )
                if self._effect_custody is not None
                else dispatch()
            )
            self._assert_execution_fence("before_tool_effect_commit")
        except CapabilityEffectUnknown:
            raise
        except ResponsibilityLoopStaleFence:
            raise
        except Exception as exc:
            self._record_tool_failure(action, proposal.proposal_id, exc)
            return self._tool_message(
                proposal,
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            self._sandbox.release_execution_lease(execution_lease)
        output = result.output
        self._record_tool_completion(
            action,
            proposal.proposal_id,
            output,
        )
        truncated = _truncate_json(output)
        return self._tool_message(proposal, truncated)

    def _record_out_of_allowlist_denial(
        self, session: ChatSession, proposal: Any
    ) -> None:
        """E2: durably record a fail-closed denial for a provider proposal
        whose capability is outside the frozen session allowlist. No Action is
        built and no ApprovalDecision can ever authorize it.

        No Action exists on this path, so the identity of the refused attempt is
        the proposal itself (id + arguments): the denial is the only record of
        it, and a surface has to be able to say what was refused.
        """
        self._durable_write(
            lambda: self._tasks.append_event(
                session.task_id,
                TaskEventType.POLICY_VERDICT_RECORDED,
                {
                    "verdict": "DENY",
                    "basis": "out_of_allowlist",
                    "mode_event_id": None,
                    "capability_id": proposal.capability_id,
                    "risk_tier": None,
                    "action_digest": hashlib.sha256(
                        f"{proposal.capability_id}\n{proposal.arguments_json}".encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                    "proposal_id": proposal.proposal_id,
                    "arguments_json": proposal.arguments_json,
                    "reason": "capability is outside the frozen session allowlist",
                },
            )
        )

    def _record_policy_verdict(
        self,
        session: ChatSession,
        action: ActionContract,
        *,
        verdict: str,
        basis: str | None,
        reason: str | None,
        mode_event_id: str | None = None,
        rule_id: str | None = None,
        rule_reason: str | None = None,
    ) -> None:
        """E2 durable policy verdict: an auto-allowance is recorded with
        provenance (basis=permission_mode + mode_event_id), never as an
        ApprovalDecision; an out-of-allowlist denial is recorded with reason; a
        DENY-by-rule records the exact rule_id.

        A DENY verdict is the only durable trace a refused action leaves (it is
        never proposed, dispatched or receipted), so it carries the full identity
        of the refused action — action_id, node_id and the arguments — plus the
        rule name and the operator's reason. Without them a surface cannot say
        *what* was refused, and the defect was exactly that: the denial reached
        nobody.
        """
        self._durable_write(
            lambda: self._tasks.append_event(
                session.task_id,
                TaskEventType.POLICY_VERDICT_RECORDED,
                {
                    "verdict": verdict,
                    "basis": basis,
                    "mode_event_id": mode_event_id,
                    "rule_id": rule_id,
                    "rule_reason": rule_reason,
                    "capability_id": action.capability_id,
                    "risk_tier": action.risk_tier,
                    "action_digest": action.action_digest(),
                    "action_id": action.action_id,
                    "node_id": action.node_id,
                    "arguments_json": action.arguments_json,
                    "reason": reason,
                },
            )
        )

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

    def _tool_message(self, proposal: Any, payload: dict[str, Any]) -> ProviderMessage:
        return ProviderMessage(
            role=ProviderMessageRole.TOOL,
            content=json.dumps(payload, default=str)[:_MAX_TOOL_RESULT_CHARS],
            tool_call_id=proposal.proposal_id,
        )

    def _maybe_record_compaction(
        self, session: ChatSession, compaction: dict[str, object] | None
    ) -> None:
        """Record a compaction durably (M1 S4), once per distinct result."""

        if compaction is None:
            return
        # Key on the drop BOUNDARY (dropped_messages, kept_from_index), which does not
        # move back as the retained content grows step to step, so a compaction is not
        # re-recorded on every provider step. If the boundary advances mid-turn (a very
        # large tool result pushes the cut further), an additional event is recorded;
        # cardinality is therefore per distinct boundary, not strictly per turn.
        key = (compaction["dropped_messages"], compaction["kept_from_index"])
        if key == self._last_compaction:
            return
        self._last_compaction = key
        self._durable_write(
            lambda: self._tasks.append_event(
                session.task_id,
                TaskEventType.SESSION_CONTEXT_COMPACTED,
                compaction,
                correlation_id=session.run_id,
            )
        )

    def _compact_history(
        self,
    ) -> tuple[list[ProviderMessage], dict[str, object] | None]:
        """Deterministically compact history to ``max_context_chars`` (M1 S4).

        Returns the messages to send and, when a compaction actually happened, a
        deterministic payload describing it (so the caller can record it durably as a
        ``SESSION_CONTEXT_COMPACTED`` event). Cutting happens only at USER boundaries
        so an ASSISTANT tool_calls message and its TOOL replies are never split apart.
        The system prompt (index 0) is never dropped.
        """

        history = self._history
        if not history or self._config.max_context_chars <= 0:
            return history, None
        chars_before = sum(len(message.content) for message in history)
        if chars_before <= self._config.max_context_chars:
            return history, None
        # The active request must survive compaction: never drop messages from the
        # most recent USER turn onward.
        last_user = 0
        for index in range(1, len(history)):
            if history[index].role is ProviderMessageRole.USER:
                last_user = index
        if last_user == 0:
            # No user turn to anchor on: do not attempt a cut (avoid dropping the tail).
            return history, None
        cut = 1  # never drop the system prompt
        limit = last_user if last_user > 0 else len(history)
        total = chars_before
        while cut < limit and total > self._config.max_context_chars:
            # Only cut at USER boundaries so ASSISTANT tool_calls and their
            # TOOL replies are never split apart.
            if history[cut].role is not ProviderMessageRole.USER:
                cut += 1
                continue
            total -= len(history[cut].content)
            cut += 1
            while cut < limit and history[cut].role is not ProviderMessageRole.USER:
                total -= len(history[cut].content)
                cut += 1
        if cut <= 1:
            # Nothing actually dropped (the active turn is preserved): this is NOT a
            # compaction and must not be recorded as one.
            return history, None
        kept = [history[0], *history[cut:]]
        payload: dict[str, object] = {
            "chars_before": chars_before,
            "chars_after": sum(len(message.content) for message in kept),
            "dropped_messages": cut - 1,
            "kept_from_index": cut,
            "retained_digest": _history_digest(kept),
        }
        return kept, payload


_WriteT = TypeVar("_WriteT")

_NOT_EXECUTED_AFTER_UNKNOWN = (
    "not executed: an earlier action of this message was dispatched and its "
    "effect is unknown; a human must reconcile it first"
)

# Final text of a turn that the operator stopped mid-flight (the session's Run
# is durably PAUSED); the durable turn completion carries the same stop_reason.
_STOPPED_BY_OPERATOR_TEXT = (
    "turn stopped by the operator; the session is paused and must be resumed "
    "before another turn"
)

_UNKNOWN_MODEL_DETAIL_CHARS = 400

_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w./~-])(?:/[A-Za-z0-9._+@%=-]+){2,}")


def _unknown_review_text(
    unknown: CapabilityEffectUnknown,
    detail: str,
) -> str:
    """Operator/model-facing wording for a dispatched action of unknown effect.

    The `UNKNOWN_REQUIRES_REVIEW [reason_code]` prefix is the frozen marker; the
    sentence after it says what is true (not a success), what did not happen (no
    retry), and what is required (a human review).
    """

    return (
        f"UNKNOWN_REQUIRES_REVIEW [{unknown.reason_code}]: {detail} - the effect "
        "may already have happened, so this action is not a success and was not "
        "retried; a human must review and reconcile it before the Run can "
        "continue"
    )


def _model_visible_unknown_detail(unknown: CapabilityEffectUnknown) -> str:
    """The reason detail with host absolute paths removed.

    The operator-facing text keeps the raw detail; the model-visible text must
    not carry the host's absolute paths (they add nothing the model can act on
    and the workspace-relative form already identifies the target).
    """

    redacted = _ABSOLUTE_PATH_RE.sub(
        lambda match: "[host-path]/" + match.group(0).rsplit("/", 1)[-1],
        unknown.detail,
    )
    if len(redacted) > _UNKNOWN_MODEL_DETAIL_CHARS:
        redacted = redacted[: _UNKNOWN_MODEL_DETAIL_CHARS - 3] + "..."
    return redacted


def _has_unanswered_tool_calls(
    history: Sequence[ProviderMessage],
) -> bool:
    """Whether any ASSISTANT tool_call still lacks its TOOL reply.

    Mirrors the session projection's own invariant, so a turn is only ever
    completed when the projection will accept its completion event. A dispatched
    action whose effect is unknown still receives a TOOL reply (see
    `_unknown_tool_message`), so it never counts as unanswered here.
    """

    answered = {
        message.tool_call_id
        for message in history
        if message.role is ProviderMessageRole.TOOL
    }
    return any(
        call.tool_call_id not in answered
        for message in history
        if message.role is ProviderMessageRole.ASSISTANT
        for call in message.tool_calls
    )


def _history_digest(messages: "list[ProviderMessage]") -> str:
    """Deterministic digest of the retained history (roles, ids, tool calls, content)."""

    hasher = hashlib.sha256()
    for message in messages:
        hasher.update(message.role.value.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update((message.tool_call_id or "").encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(
            json.dumps(
                [call.model_dump(mode="json") for call in message.tool_calls],
                sort_keys=True,
            ).encode("utf-8")
        )
        hasher.update(b"\x00")
        hasher.update(message.content.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _action_preview(action: ActionContract, arguments: dict[str, Any]) -> str:
    if action.capability_id in {"workspace.edit", "workspace.apply_patch"}:
        path = str(arguments.get("path", ""))
        if action.capability_id == "workspace.edit":
            old = str(arguments.get("old_string", ""))
            new = str(arguments.get("new_string", ""))
            return f"edit {path}\n--- old ---\n{old[:2000]}\n--- new ---\n{new[:2000]}"
        content = str(arguments.get("content", ""))
        return f"replace {path} ({len(content)} chars)\n{content[:2000]}"
    if action.capability_id in {"workspace.shell", "workspace.run_tests"}:
        return f"run command: {arguments.get('command', '')}"
    return json.dumps(arguments, default=str)[:2000]


_SUMMARY_VALUE_CHARS = 120


def _scalar_summary(output: dict[str, Any]) -> dict[str, Any]:
    """The small top-level scalars, which are the decision-relevant part.

    Keys arrive key-sorted (canonical_output), so a payload whose bulk lives in
    `matches` loses every field that sorts after it once the preview is cut -
    `truncated_reason`, `scanned_files`, `unexamined_files`, `exit_code`, `mode`.
    Those are exactly the fields that say WHY a result is incomplete, so they are
    carried explicitly. Long strings are replaced by their length so the summary
    itself stays bounded (a 5 MB read would otherwise re-inflate it).
    """

    summary: dict[str, Any] = {}
    for key, value in output.items():
        if value is None or isinstance(value, (bool, int, float)):
            summary[key] = value
        elif isinstance(value, str):
            summary[key] = (
                value
                if len(value) <= _SUMMARY_VALUE_CHARS
                else f"<omitted: {len(value)} chars>"
            )
    return summary


def _truncate_json(output: dict[str, Any]) -> dict[str, Any]:
    rendered = json.dumps(output, default=str)
    if len(rendered) <= _MAX_TOOL_RESULT_CHARS:
        return output
    return {
        "truncated": True,
        "summary": _scalar_summary(output),
        "preview": rendered[:_MAX_TOOL_RESULT_CHARS],
    }


def _provider_output(response: ProviderResponse) -> dict[str, object]:
    return {
        "text": response.text,
        "tool_proposals": [
            proposal.model_dump(mode="json") for proposal in response.tool_proposals
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
