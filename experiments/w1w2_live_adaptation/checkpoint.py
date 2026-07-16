"""Atomic W1/W2 checkpoint and rollback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from experiments.w1w2_live_adaptation._contracts import ContractModel, NonEmptyStr, UtcDateTime, content_digest
from experiments.w1w2_live_adaptation.w1_state import W1MemoryState, W1Scope
from experiments.w1w2_live_adaptation.w2_selector import W2DecisionReceipt


class W1W2Checkpoint(ContractModel):
    checkpoint_id: NonEmptyStr
    scope: W1Scope
    w1_state_digest: NonEmptyStr
    w2_history_digest: NonEmptyStr
    w1_state: Mapping[str, Any]
    w2_history: tuple[W2DecisionReceipt, ...]
    created_at: UtcDateTime


class CheckpointStore:
    """In-memory checkpoint store. File-backed SQLite durability in Wave B."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path
        self._checkpoints: dict[str, W1W2Checkpoint] = {}

    def save(
        self,
        scope: W1Scope,
        w1_state: W1MemoryState,
        w2_history: tuple[W2DecisionReceipt, ...],
    ) -> W1W2Checkpoint:
        w1_payload = {
            "scope": scope.model_dump(mode="json", exclude_none=True),
            "epoch": w1_state.epoch,
            "updates": [u.model_dump(mode="json", exclude_none=True) for u in w1_state.updates],
        }
        w1_state_digest = content_digest(w1_payload)
        w2_payload = {"receipts": [r.model_dump(mode="json", exclude_none=True) for r in w2_history]}
        w2_history_digest = content_digest(w2_payload)
        cp = W1W2Checkpoint(
            checkpoint_id=f"cp-{uuid4().hex}",
            scope=scope,
            w1_state_digest=w1_state_digest,
            w2_history_digest=w2_history_digest,
            w1_state=w1_payload,
            w2_history=w2_history,
            created_at=datetime.now(timezone.utc),
        )
        self._checkpoints[cp.checkpoint_id] = cp
        return cp

    def load(self, checkpoint_id: str) -> W1W2Checkpoint | None:
        return self._checkpoints.get(checkpoint_id)
