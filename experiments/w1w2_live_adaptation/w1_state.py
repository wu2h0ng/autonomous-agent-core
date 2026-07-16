"""W1 live adaptation state, typed payloads and durable SQLite memory store."""

from __future__ import annotations

import json
import sqlite3
from enum import Enum
from typing import Any

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
    canonical_json,
    content_digest,
)


class W1UpdateType(str, Enum):
    BELIEF = "BELIEF"
    TASK = "TASK"
    RETRIEVAL = "RETRIEVAL"
    CONFIDENCE = "CONFIDENCE"
    LOCAL_PLAN = "LOCAL_PLAN"


class W1Scope(ContractModel):
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr
    environment_id: NonEmptyStr
    episode_id: NonEmptyStr


class BeliefPayload(ContractModel):
    belief_statement: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0)


class TaskPayload(ContractModel):
    task_statement: NonEmptyStr
    priority: int = Field(ge=0, le=10)


class RetrievalPayload(ContractModel):
    retrieval_query: NonEmptyStr
    retrieved_digest: NonEmptyStr


class ConfidencePayload(ContractModel):
    confidence_target: NonEmptyStr
    confidence_value: float = Field(ge=0.0, le=1.0)


class LocalPlanPayload(ContractModel):
    plan_step: NonEmptyStr
    plan_dependency: NonEmptyStr = "none"


W1Payload = BeliefPayload | TaskPayload | RetrievalPayload | ConfidencePayload | LocalPlanPayload

_PAYLOAD_TYPES: dict[W1UpdateType, type[W1Payload]] = {
    W1UpdateType.BELIEF: BeliefPayload,
    W1UpdateType.TASK: TaskPayload,
    W1UpdateType.RETRIEVAL: RetrievalPayload,
    W1UpdateType.CONFIDENCE: ConfidencePayload,
    W1UpdateType.LOCAL_PLAN: LocalPlanPayload,
}


class W1Update(ContractModel):
    update_id: NonEmptyStr
    scope: W1Scope
    update_type: W1UpdateType
    payload: W1Payload
    provenance: NonEmptyStr
    source_event_digest: NonEmptyStr
    correction_epoch: int = Field(ge=0)
    rollback_checkpoint_id: NonEmptyStr
    version: NonEmptyStr
    valid_time: UtcDateTime
    transaction_time: UtcDateTime


class W1UpdateResult(ContractModel):
    update_id: NonEmptyStr
    applied: bool
    violations: tuple[str, ...]
    state_digest: str


class W1MemoryState:
    def __init__(self, scope: W1Scope, updates: tuple[W1Update, ...], epoch: int) -> None:
        self.scope = scope
        self.updates = updates
        self.epoch = epoch

    def digest(self) -> str:
        """Content digest over payloads/history, excluding caller ids."""
        payload = {
            "scope": self.scope.model_dump(mode="json", exclude_none=True),
            "epoch": self.epoch,
            "history": [
                {
                    "update_type": u.update_type.value,
                    "payload": u.payload.model_dump(mode="json", exclude_none=True),
                }
                for u in self.updates
            ],
        }
        return content_digest(payload)


class W1MemoryStore:
    """File-backed SQLite W1 update ledger and state store."""

    def __init__(
        self,
        db_path: str,
        linter: Any | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        if not db_path:
            raise ValueError("W1MemoryStore requires a non-empty db_path")
        self._db_path = db_path
        self._linter = linter
        self._initial = dict(initial_state) if initial_state else {}
        self._active_scope: W1Scope | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS w1_updates (
                    update_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    update_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    source_event_digest TEXT NOT NULL,
                    correction_epoch INTEGER NOT NULL,
                    rollback_checkpoint_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    valid_time TEXT NOT NULL,
                    transaction_time TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS w1_state (
                    scope_key TEXT PRIMARY KEY,
                    scope_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    epoch INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_w1_updates_scope ON w1_updates(scope_key)"
            )

    def _key(self, scope: W1Scope) -> str:
        return canonical_json(scope)

    def _parse_update(self, row: sqlite3.Row) -> W1Update:
        payload_type = _PAYLOAD_TYPES[W1UpdateType(row["update_type"])]
        return W1Update(
            update_id=row["update_id"],
            scope=W1Scope(**json.loads(row["scope_json"])),
            update_type=W1UpdateType(row["update_type"]),
            payload=payload_type(**json.loads(row["payload_json"])),
            provenance=row["provenance"],
            source_event_digest=row["source_event_digest"],
            correction_epoch=row["correction_epoch"],
            rollback_checkpoint_id=row["rollback_checkpoint_id"],
            version=row["version"],
            valid_time=row["valid_time"],
            transaction_time=row["transaction_time"],
        )

    def get_state(self, scope: W1Scope) -> W1MemoryState:
        key = self._key(scope)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM w1_updates WHERE scope_key = ? ORDER BY transaction_time",
                (key,),
            )
            updates = tuple(self._parse_update(row) for row in cur.fetchall())
            row = conn.execute(
                "SELECT epoch FROM w1_state WHERE scope_key = ?",
                (key,),
            ).fetchone()
            epoch = row["epoch"] if row else 0
        return W1MemoryState(scope=scope, updates=updates, epoch=epoch)

    def apply(self, update: W1Update) -> W1UpdateResult:
        violations: list[str] = []
        if self._linter is not None:
            violations = self._linter.lint(update)
        if violations:
            return W1UpdateResult(
                update_id=update.update_id,
                applied=False,
                violations=tuple(violations),
                state_digest=self.get_state(update.scope).digest(),
            )

        key = self._key(update.scope)
        if self._active_scope is None:
            self._active_scope = update.scope
        elif key != self._key(self._active_scope):
            return W1UpdateResult(
                update_id=update.update_id,
                applied=False,
                violations=("cross-scope write rejected",),
                state_digest=self.get_state(update.scope).digest(),
            )

        state = self.get_state(update.scope)
        merged = dict(self._initial)
        for u in state.updates:
            merged[u.update_type.value] = u.payload.model_dump(mode="json", exclude_none=True)
        merged[update.update_type.value] = update.payload.model_dump(mode="json", exclude_none=True)
        epoch = state.epoch + 1

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO w1_updates (
                    update_id, scope_key, scope_json, update_type, payload_json,
                    provenance, source_event_digest, correction_epoch, rollback_checkpoint_id,
                    version, valid_time, transaction_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.update_id,
                    key,
                    update.scope.model_dump_json(),
                    update.update_type.value,
                    update.payload.model_dump_json(),
                    update.provenance,
                    update.source_event_digest,
                    update.correction_epoch,
                    update.rollback_checkpoint_id,
                    update.version,
                    update.valid_time.isoformat(),
                    update.transaction_time.isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO w1_state (scope_key, scope_json, state_json, epoch)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    state_json = excluded.state_json,
                    epoch = excluded.epoch
                """,
                (
                    key,
                    update.scope.model_dump_json(),
                    json.dumps(merged, sort_keys=True),
                    epoch,
                ),
            )

        return W1UpdateResult(
            update_id=update.update_id,
            applied=True,
            violations=(),
            state_digest=self.get_state(update.scope).digest(),
        )

    def activate_scope(self, scope: W1Scope) -> None:
        if self._active_scope is None:
            self._active_scope = scope

    def checkpoint(self) -> str:
        if self._active_scope is None:
            raise ValueError("no active scope to checkpoint")
        state = self.get_state(self._active_scope)
        return state.digest()

    def rollback_to(self, checkpoint_id: str) -> W1MemoryState:
        if self._active_scope is None:
            raise ValueError("no active scope to rollback")
        # Wave B: rollback by replaying history up to the checkpoint digest.
        state = self.get_state(self._active_scope)
        target_updates: list[W1Update] = []
        current_digest = W1MemoryState(
            scope=self._active_scope,
            updates=(),
            epoch=0,
        ).digest()
        for update in state.updates:
            if current_digest == checkpoint_id:
                break
            target_updates.append(update)
            current_digest = W1MemoryState(
                scope=self._active_scope,
                updates=tuple(target_updates),
                epoch=len(target_updates),
            ).digest()

        key = self._key(self._active_scope)
        merged = dict(self._initial)
        for u in target_updates:
            merged[u.update_type.value] = u.payload.model_dump(mode="json", exclude_none=True)
        epoch = len(target_updates)
        with self._connect() as conn:
            conn.execute("DELETE FROM w1_updates WHERE scope_key = ? AND update_id NOT IN ({})".format(
                ",".join("?" * len(target_updates))
            ), (key, *(u.update_id for u in target_updates)))
            conn.execute(
                """
                INSERT INTO w1_state (scope_key, scope_json, state_json, epoch)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    state_json = excluded.state_json,
                    epoch = excluded.epoch
                """,
                (
                    key,
                    self._active_scope.model_dump_json(),
                    json.dumps(merged, sort_keys=True),
                    epoch,
                ),
            )
        return self.get_state(self._active_scope)

    def close(self) -> None:
        pass
