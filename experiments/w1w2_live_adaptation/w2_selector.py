"""W2 strategy selector with immutable authorized option contracts."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Callable, Mapping, Protocol
from uuid import uuid4

from pydantic import Discriminator, Field

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


class BaseW2Option(ContractModel):
    option_id: NonEmptyStr
    kind: W2OptionKind


class ToolOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.TOOL
    tool_id: NonEmptyStr
    tool_version: NonEmptyStr


class ModelOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.MODEL
    model_id: NonEmptyStr
    model_version: NonEmptyStr


class WorkflowOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.WORKFLOW
    workflow_id: NonEmptyStr
    workflow_version: NonEmptyStr


class RetryOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.RETRY
    max_retries: int = Field(ge=0)
    backoff_seconds: float = Field(ge=0.0)


class ThresholdOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.THRESHOLD
    threshold_name: NonEmptyStr
    threshold_value: float


class BudgetOption(BaseW2Option):
    kind: W2OptionKind = W2OptionKind.BUDGET
    budget_unit: NonEmptyStr
    budget_limit: float = Field(ge=0.0)


W2Option = Annotated[
    ToolOption
    | ModelOption
    | WorkflowOption
    | RetryOption
    | ThresholdOption
    | BudgetOption,
    Discriminator("kind"),
]


class W2OptionRegistry(Protocol):
    """Read-only authority registry for canonical W2 option contracts."""

    def resolve(self, option_id: str) -> W2Option | None: ...


class W2DecisionReceipt(ContractModel):
    receipt_id: NonEmptyStr
    inputs_digest: NonEmptyStr
    authorized_set_digest: NonEmptyStr
    selected_option_id: NonEmptyStr
    consumed_w1_state_digest: NonEmptyStr | None = None
    outcome_feedback_ref: NonEmptyStr
    reason_code: NonEmptyStr
    created_at: UtcDateTime


SelectionFn = Callable[..., str]


class W2StrategySelector:
    """Selects only from an immutable authorized set of W2 option ids/digests.

    Cannot create a new option, expand permissions, or bypass C7/policy.
    """

    def __init__(
        self,
        registry: W2OptionRegistry,
        authorized_option_ids: tuple[str, ...],
        selection_fn: SelectionFn | None = None,
    ) -> None:
        self._registry = registry
        self._authorized_option_ids = tuple(authorized_option_ids)
        self._option_ids = frozenset(self._authorized_option_ids)
        self._selection_fn = selection_fn

    @property
    def authorized_option_ids(self) -> tuple[str, ...]:
        return self._authorized_option_ids

    def authorized_set_digest(self) -> str:
        options = []
        for option_id in sorted(self._authorized_option_ids):
            option = self._registry.resolve(option_id)
            if option is None:
                raise ValueError(
                    f"authorized option '{option_id}' is not in authority registry"
                )
            options.append(option.model_dump(mode="json", exclude_none=True))
        payload = {"options": options}
        return content_digest(payload)

    def _default_selection(self, outcome_history: tuple[Mapping[str, Any], ...]) -> str:
        """Deterministic UCB exploration without a regime or schedule channel."""
        rewards: dict[str, float] = {}
        counts: dict[str, int] = {}
        for h in outcome_history:
            action = h.get("action")
            if action is None or action not in self._option_ids:
                continue
            rewards[action] = rewards.get(action, 0.0) + float(h.get("reward", 0.0))
            counts[action] = counts.get(action, 0) + 1
        for option_id in self._authorized_option_ids:
            if counts.get(option_id, 0) == 0:
                return option_id
        total = sum(counts.values())
        best_action = max(
            (
                rewards[a] / counts[a] + math.sqrt(2.0 * math.log(total) / counts[a]),
                a,
            )
            for a in self._authorized_option_ids
        )[1]
        return best_action

    def select(
        self,
        context: Mapping[str, Any],
        outcome_history: tuple[Mapping[str, Any], ...],
        consumed_w1_state_digest: str | None = None,
        preferred_option_id: str | None = None,
    ) -> W2DecisionReceipt:
        if preferred_option_id is not None:
            if consumed_w1_state_digest is None:
                raise ValueError("W1 preference requires a consumed state digest")
            if preferred_option_id not in self._option_ids:
                raise ValueError(
                    f"preferred option '{preferred_option_id}' is not in authorized set"
                )
        if self._selection_fn is not None:
            selected = self._selection_fn(
                self._authorized_option_ids,
                dict(context),
                tuple(outcome_history),
            )
        elif preferred_option_id is not None:
            selected = preferred_option_id
        else:
            selected = self._default_selection(outcome_history)

        if selected not in self._option_ids:
            raise ValueError(f"selected option '{selected}' is not in authorized set")

        resolved = self._registry.resolve(selected)
        if resolved is None:
            raise ValueError(
                f"selected option '{selected}' is not in authority registry"
            )

        inputs = {
            "context": dict(context),
            "outcome_history": [dict(h) for h in outcome_history],
            "consumed_w1_state_digest": consumed_w1_state_digest,
            "preferred_option_id": preferred_option_id,
        }
        now = datetime.now(timezone.utc)
        return W2DecisionReceipt(
            receipt_id=f"w2r-{uuid4().hex}",
            inputs_digest=content_digest(inputs),
            authorized_set_digest=self.authorized_set_digest(),
            selected_option_id=selected,
            consumed_w1_state_digest=consumed_w1_state_digest,
            outcome_feedback_ref=f"fb-{uuid4().hex}",
            reason_code="authorized_selection",
            created_at=now,
        )
