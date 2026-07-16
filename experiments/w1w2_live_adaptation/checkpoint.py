"""Atomic W1+W2 durable checkpoint store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

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
    """File-backed SQLite store for atomic W1+W2 checkpoints."""

    def __init__(self, db_path: str) -> None:
        if not db_path:
            raise ValueError("CheckpointStore requires a non-empty db_path")
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    scope_json TEXT NOT NULL,
                    w1_state_digest TEXT NOT NULL,
                    w2_history_digest TEXT NOT NULL,
                    w1_state_json TEXT NOT NULL,
                    w2_history_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save(
        self,
        scope: W1Scope,
        w1_state: W1MemoryState,
        w2_history: tuple[W2DecisionReceipt, ...],
    ) -> W1W2Checkpoint:
        w1_payload = {
            "scope": scope.model_dump(mode="json", exclude_none=True),
            "epoch": w1_state.epoch,
            "history": [
                {
                    "update_type": u.update_type.value,
                    "payload": u.payload.model_dump(mode="json", exclude_none=True),
                }
                for u in w1_state.updates
            ],
        }
        w1_state_digest = content_digest(w1_payload)
        w2_payload = {"receipts": [r.model_dump(mode="json", exclude_none=True) for r in w2_history]}
        w2_history_digest = content_digest(w2_payload)
        created_at = datetime.now(timezone.utc)

        # Deterministic checkpoint id from content (without timestamp).
        id_payload = {
            "scope": scope.model_dump(mode="json", exclude_none=True),
            "w1_state_digest": w1_state_digest,
            "w2_history_digest": w2_history_digest,
            "w1_state": w1_payload,
            "w2_history": w2_payload,
        }
        checkpoint_id = content_digest(id_payload)

        cp = W1W2Checkpoint(
            checkpoint_id=checkpoint_id,
            scope=scope,
            w1_state_digest=w1_state_digest,
            w2_history_digest=w2_history_digest,
            w1_state=w1_payload,
            w2_history=w2_history,
            created_at=created_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints (
                    checkpoint_id, scope_json, w1_state_digest, w2_history_digest,
                    w1_state_json, w2_history_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cp.checkpoint_id,
                    scope.model_dump_json(),
                    w1_state_digest,
                    w2_history_digest,
                    json.dumps(w1_payload, sort_keys=True),
                    json.dumps(w2_payload, sort_keys=True),
                    created_at.isoformat(),
                ),
            )
        return cp

    def load(self, checkpoint_id: str) -> W1W2Checkpoint | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            return None
        scope = W1Scope(**json.loads(row["scope_json"]))
        w1_state = json.loads(row["w1_state_json"])
        w2_history = tuple(
            W2DecisionReceipt(**r) for r in json.loads(row["w2_history_json"])["receipts"]
        )
        return W1W2Checkpoint(
            checkpoint_id=row["checkpoint_id"],
            scope=scope,
            w1_state_digest=row["w1_state_digest"],
            w2_history_digest=row["w2_history_digest"],
            w1_state=w1_state,
            w2_history=w2_history,
            created_at=row["created_at"],
        )
