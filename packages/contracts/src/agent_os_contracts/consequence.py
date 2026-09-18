from __future__ import annotations

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr


class ConsequencePreview(ContractModel):
    """Evidence-bound SYMBOLIC preview of an action's OWN governed history (ADR-0016).

    Honest counts only: never a prediction, learned model or probability. ``available`` is False
    when there is no history port, no prior history for ``action_type``, or the ledger read failed;
    in that case every count is zero and ``last_outcomes`` is empty, so a surface can distinguish
    "no prior history" from a fabricated "0 of N".
    """

    action_type: NonEmptyStr
    available: bool = False
    prior_executions: int = Field(default=0, ge=0)
    resolved_intended: int = Field(default=0, ge=0)
    resolved_other: int = Field(default=0, ge=0)
    last_outcomes: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _validate_consistency(self) -> ConsequencePreview:
        if self.resolved_intended + self.resolved_other != self.prior_executions:
            raise ValueError("resolved_intended + resolved_other must equal prior_executions")
        if not self.available and (self.prior_executions != 0 or self.last_outcomes):
            raise ValueError("unavailable preview must carry zero counts and no outcomes")
        return self
