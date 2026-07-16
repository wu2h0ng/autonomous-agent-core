"""W1 live adaptation state, typed payloads and memory store."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

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
        payload = {
            "scope": self.scope.model_dump(mode="json", exclude_none=True),
            "epoch": self.epoch,
            "updates": [u.model_dump(mode="json", exclude_none=True) for u in self.updates],
        }
        return content_digest(payload)


class W1MemoryStore:
    """In-memory W1 update store. Durable SQLite ledger added in Wave B."""

    def __init__(
        self,
        db_path: str | None,
        linter: Any | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        self._db_path = db_path
        self._linter = linter
        self._initial = dict(initial_state) if initial_state else {}
        self._state: dict[str, dict[str, Any]] = {}
        self._updates: dict[str, list[W1Update]] = {}
        self._epoch: dict[str, int] = {}
        self._active_scope: W1Scope | None = None

    def _key(self, scope: W1Scope) -> str:
        return canonical_json(scope)

    def get_state(self, scope: W1Scope) -> W1MemoryState:
        key = self._key(scope)
        return W1MemoryState(
            scope=scope,
            updates=tuple(self._updates.get(key, [])),
            epoch=self._epoch.get(key, 0),
        )

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

        if key not in self._state:
            self._state[key] = dict(self._initial)
            self._updates[key] = []
            self._epoch[key] = 0

        # Merge typed payload fields into state ( Wave B: ledger writes )
        merged = dict(self._state[key])
        merged[update.update_type.value] = update.payload.model_dump(mode="json", exclude_none=True)
        self._state[key] = merged
        self._updates[key].append(update)
        self._epoch[key] += 1

        return W1UpdateResult(
            update_id=update.update_id,
            applied=True,
            violations=(),
            state_digest=self.get_state(update.scope).digest(),
        )

    def checkpoint(self) -> str:
        if self._active_scope is None:
            return f"cp-{uuid4().hex}"
        return f"cp-{uuid4().hex}"

    def rollback_to(self, checkpoint_id: str) -> W1MemoryState:
        raise NotImplementedError
