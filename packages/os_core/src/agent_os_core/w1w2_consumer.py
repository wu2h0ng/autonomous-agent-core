"""W1/W2 outcome consumer — the last hop of the SRL closed loop (P0-3 Inc3).

Consumes an admitted outcome from the existing, unchanged `OutcomeLearningGate` and
applies a **bounded, deterministic, in-envelope** update to the agent's typed working
state (W1). It is fail-closed and structurally confined: `W1State` carries only
attention/confidence weights and has no Mandate / MandateEnvelope / StandingMission /
grant / policy field, so a W1/W2 update cannot widen authority (A-SRL-1 I-22 / AC-14).

It never executes an effect, never dispatches a capability, never writes C7 and never
mutates the Task. Every applied update is recorded as a durable, digest-bound
`W1W2_UPDATED` event (audit: outcome -> update with before/after digests).
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from agent_os_contracts import ObservedOutcome, TaskEventType
from agent_os_contracts.common import ContractModel, NonEmptyStr

from .outcome_learning_gate import OutcomeAdmissionReason, OutcomeLearningGate
from .task_service import TaskService

# Fixed, bounded update rule (no model, no learning rate search): move the weight for
# the producing candidate a fixed fraction toward the verified outcome's score.
_STEP = 0.5
_INITIAL_WEIGHT = 0.5


class W1W2UpdateReason(str, Enum):
    """Enumerable outcome of a consume attempt."""

    UPDATED = "UPDATED"
    REFUSED = "REFUSED"
    DUPLICATE = "DUPLICATE"


class W1State(ContractModel):
    """In-envelope W1 working state: attention/confidence weights only.

    Deliberately contains NO Mandate/Envelope/StandingMission/grant/policy field, so a
    W1/W2 update is structurally incapable of widening authority (I-22).
    """

    weights: dict[NonEmptyStr, float] = {}

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.weights, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class W1W2UpdateDecision(ContractModel):
    """Typed receipt for one consume attempt (no side effect on refusal)."""

    applied: bool
    reason_code: W1W2UpdateReason
    task_id: NonEmptyStr
    outcome_id: NonEmptyStr | None = None
    candidate_key: NonEmptyStr | None = None
    w1_before_digest: NonEmptyStr | None = None
    w1_after_digest: NonEmptyStr | None = None
    detail: NonEmptyStr | None = None


def _candidate_key(task) -> str:
    """Deterministic key of the candidate that produced the task (its goal)."""

    goal = task.goal
    return goal.goal_id if goal is not None else task.task_id


class W1W2OutcomeConsumer:
    """Applies admitted outcomes to W1; default-off, opt-in at the composition root."""

    def __init__(
        self,
        task_service: TaskService,
        *,
        step: float = _STEP,
    ) -> None:
        self._tasks = task_service
        self._gate = OutcomeLearningGate(task_service)
        self._step = step
        self._w1 = W1State()

    def _already_applied(self, task_id: str, outcome_id: str) -> bool:
        """Durable idempotency: has this outcome already produced an update?"""

        for event in self._tasks._event_store.read(task_id):
            if event.event_type is not TaskEventType.W1W2_UPDATED:
                continue
            if json.loads(event.payload_json).get("outcome_id") == outcome_id:
                return True
        return False

    def w1_state(self) -> W1State:
        return self._w1.model_copy(deep=True)

    def consume(self, task_id: str, outcome: ObservedOutcome) -> W1W2UpdateDecision:
        """Consume an outcome into W1 iff the learning gate ADMITS it; else no-op."""

        decision = self._gate.admit(task_id, outcome)
        if not decision.admitted:
            return W1W2UpdateDecision(
                applied=False,
                reason_code=W1W2UpdateReason.REFUSED,
                task_id=task_id,
                outcome_id=outcome.observed_outcome_id,
                detail=decision.reason_code.value,
            )
        if self._already_applied(task_id, outcome.observed_outcome_id):
            return W1W2UpdateDecision(
                applied=False,
                reason_code=W1W2UpdateReason.DUPLICATE,
                task_id=task_id,
                outcome_id=outcome.observed_outcome_id,
            )

        task = self._tasks.get_task(task_id)
        candidate_key = _candidate_key(task)
        before_digest = self._w1.digest()
        before = self._w1.weights.get(candidate_key, _INITIAL_WEIGHT)
        score = outcome.score if outcome.score is not None else 1.0
        after = min(1.0, max(0.0, before + self._step * (score - before)))
        self._w1.weights[candidate_key] = after
        after_digest = self._w1.digest()

        self._tasks.append_event(
            task_id,
            TaskEventType.W1W2_UPDATED,
            {
                "outcome_id": outcome.observed_outcome_id,
                "expected_outcome_id": outcome.expected_outcome_id,
                "run_id": outcome.run_id,
                "candidate_key": candidate_key,
                "weight_before": before,
                "weight_after": after,
                "w1_before_digest": before_digest,
                "w1_after_digest": after_digest,
            },
            correlation_id=outcome.run_id,
        )
        return W1W2UpdateDecision(
            applied=True,
            reason_code=W1W2UpdateReason.UPDATED,
            task_id=task_id,
            outcome_id=outcome.observed_outcome_id,
            candidate_key=candidate_key,
            w1_before_digest=before_digest,
            w1_after_digest=after_digest,
        )


__all__ = [
    "W1State",
    "W1W2OutcomeConsumer",
    "W1W2UpdateDecision",
    "W1W2UpdateReason",
    "OutcomeAdmissionReason",
]
