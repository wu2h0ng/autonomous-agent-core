from __future__ import annotations

from pydantic import model_validator

from .common import ContractModel, NonEmptyStr


class ApprovalChoice(ContractModel):
    """One surfaced alternative in a human-facing approval choice set (ADR-0014)."""

    action: NonEmptyStr
    rationale: NonEmptyStr | None = None


class ApprovalChoiceSet(ContractModel):
    """ADR-0014 human-facing choice-set contract for an approval-required proposal.

    A proposal requiring human approval must surface EITHER a real choice set (>=2 distinct
    alternatives with exactly one ``recommended_action``) OR a single alternative plus a non-empty
    ``single_option_rationale`` explaining why only one option was surfaced. This is fail-closed
    data discipline, not a UI concern: a choice set that cannot answer "what was the approver
    choosing between, and why only one option" is refused at construction.
    """

    alternatives: tuple[ApprovalChoice, ...] = ()
    recommended_action: NonEmptyStr | None = None
    single_option_rationale: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_choice_set(self) -> ApprovalChoiceSet:
        actions = tuple(alternative.action for alternative in self.alternatives)
        if len(set(actions)) != len(actions):
            raise ValueError("choice-set alternatives must be distinct")
        if self.recommended_action is not None and self.recommended_action not in actions:
            raise ValueError("recommended_action must be one of the surfaced alternatives")
        if len(actions) == 1:
            if not self.single_option_rationale:
                raise ValueError(
                    "a single-option choice set requires a non-empty single_option_rationale"
                )
            if self.recommended_action is None:
                raise ValueError("a single-option choice set must name its recommended action")
            return self
        if len(actions) < 2:
            raise ValueError(
                "a choice set requires at least two alternatives or a single-option rationale"
            )
        if self.recommended_action is None:
            raise ValueError(
                "a multi-alternative choice set requires exactly one recommended_action"
            )
        return self

    def action_labels(self) -> tuple[NonEmptyStr, ...]:
        return tuple(alternative.action for alternative in self.alternatives)
