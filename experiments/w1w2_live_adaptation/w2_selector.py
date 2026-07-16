"""W2 strategy selector with immutable authorized option set."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping
from uuid import uuid4


from experiments.w1w2_live_adaptation._contracts import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
    content_digest,
)


class W2OptionKind(str, Enum):
    MODEL = "MODEL"
    TOOL = "TOOL"
    WORKFLOW = "WORKFLOW"
    RETRY = "RETRY"
    THRESHOLD = "THRESHOLD"
    BUDGET = "BUDGET"


class W2Option(ContractModel):
    option_id: NonEmptyStr
    kind: W2OptionKind
    params: Mapping[str, Any]


class W2DecisionReceipt(ContractModel):
    receipt_id: NonEmptyStr
    task_id: NonEmptyStr
    inputs_digest: NonEmptyStr
    authorized_set_digest: NonEmptyStr
    selected_option_id: NonEmptyStr
    outcome_feedback_ref: NonEmptyStr
    reason_code: NonEmptyStr
    created_at: UtcDateTime


SelectionFn = Callable[..., str]


class W2StrategySelector:
    """Selects only from an immutable authorized set of W2 options.

    Cannot create a new option, expand permissions, or bypass C7/policy.
    """

    def __init__(
        self,
        authorized_options: tuple[W2Option, ...],
        selection_fn: SelectionFn | None = None,
    ) -> None:
        self._authorized_options = tuple(authorized_options)
        self._option_ids = frozenset(o.option_id for o in self._authorized_options)
        self._selection_fn = selection_fn

    @property
    def authorized_options(self) -> tuple[W2Option, ...]:
        return self._authorized_options

    def _default_selection(self, outcome_history: tuple[Mapping[str, Any], ...]) -> str:
        if not outcome_history:
            return self._authorized_options[0].option_id
        rewards: dict[str, float] = {}
        counts: dict[str, int] = {}
        for h in outcome_history:
            action = h.get("action")
            if action is None:
                continue
            rewards[action] = rewards.get(action, 0.0) + float(h.get("reward", 0.0))
            counts[action] = counts.get(action, 0) + 1
        if not counts:
            return self._authorized_options[0].option_id
        best_action = max(
            ((rewards[a] / counts[a], a) for a in counts),
            key=lambda x: x[0],
        )[1]
        if best_action not in self._option_ids:
            return self._authorized_options[0].option_id
        return best_action

    def authorized_set_digest(self) -> str:
        payload = {"options": [o.model_dump(mode="json", exclude_none=True) for o in self._authorized_options]}
        return content_digest(payload)

    def select(
        self,
        task_id: str,
        context: Mapping[str, Any],
        outcome_history: tuple[Mapping[str, Any], ...],
    ) -> W2DecisionReceipt:
        if self._selection_fn is not None:
            selected = self._selection_fn(
                self._authorized_options,
                dict(context),
                tuple(outcome_history),
            )
        else:
            selected = self._default_selection(outcome_history)

        if selected not in self._option_ids:
            raise ValueError(f"selected option '{selected}' is not in authorized set")

        inputs = {
            "task_id": task_id,
            "context": dict(context),
            "outcome_history": [dict(h) for h in outcome_history],
        }
        now = datetime.now(timezone.utc)
        return W2DecisionReceipt(
            receipt_id=f"w2r-{uuid4().hex}",
            task_id=task_id,
            inputs_digest=content_digest(inputs),
            authorized_set_digest=self.authorized_set_digest(),
            selected_option_id=selected,
            outcome_feedback_ref=f"fb-{uuid4().hex}",
            reason_code="authorized_selection",
            created_at=now,
        )
