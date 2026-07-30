from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .common import ContractModel, NonEmptyStr, UtcDateTime


class BeliefRecord(ContractModel):
    """Revisable proposition with confidence, provenance, conflict and validity interval."""

    belief_id: str = ""
    task_id: str
    proposition: NonEmptyStr
    confidence: float
    provenance_refs: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    valid_from: UtcDateTime = datetime.now(timezone.utc)
    valid_until: UtcDateTime | None = None
    status: Literal["ACTIVE", "RETRACTED", "SUPERSEDED"] = "ACTIVE"

    def model_post_init(self, __context: Any) -> None:
        if not self.belief_id:
            object.__setattr__(self, "belief_id", f"belief-{uuid4()}")


class BeliefPatch(ContractModel):
    """Typed add/revise/invalidate proposal against a base snapshot."""

    patch_id: str = ""
    task_id: str
    base_snapshot_digest: NonEmptyStr
    operation: Literal["ADD", "REVISE", "INVALIDATE"]
    target_belief_id: str | None = None
    new_proposition: NonEmptyStr | None = None
    new_confidence: float | None = None
    reason: NonEmptyStr | None = None
    created_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.patch_id:
            object.__setattr__(self, "patch_id", f"belief-patch-{uuid4()}")
