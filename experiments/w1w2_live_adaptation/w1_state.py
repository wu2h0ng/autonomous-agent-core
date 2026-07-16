"""W1 live adaptation state and memory store."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping
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


class W1Update(ContractModel):
    update_id: NonEmptyStr
    scope: W1Scope
    update_type: W1UpdateType
    payload: Mapping[str, Any]
    provenance: NonEmptyStr
    source_event_digest: NonEmptyStr
    version: NonEmptyStr
    valid_time: UtcDateTime
    transaction_time: UtcDateTime
    confidence: float = Field(ge=0.0, le=1.0)
    rollback_checkpoint_id: NonEmptyStr


class W1UpdateApplicationResult(ContractModel):
    update_id: NonEmptyStr
    applied: bool
    checkpoint_id: str | None
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
            "update_ids": [u.update_id for u in self.updates],
        }
        return content_digest(payload)


class W1MemoryStore:
    """In-memory, auditable W1 update store scoped by mandate/task/environment/episode."""

    def __init__(
        self,
        authorized_schema: Mapping[W1UpdateType, tuple[str, ...]],
        initial_state: Mapping[str, Any] | None = None,
    ) -> None:
        self._authorized_schema = dict(authorized_schema)
        self._state: dict[str, dict[str, Any]] = {}
        self._updates: dict[str, list[W1Update]] = {}
        self._epoch: dict[str, int] = {}
        self._checkpoints: dict[str, tuple[str, dict[str, Any], tuple[W1Update, ...], int]] = {}
        self._initial = dict(initial_state) if initial_state else {}
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

    def apply(self, update: W1Update) -> W1UpdateApplicationResult:
        violations: list[str] = []
        key = self._key(update.scope)

        if self._active_scope is not None and self._key(update.scope) != self._key(self._active_scope):
            violations.append("cross-scope write rejected")

        allowed_keys = self._authorized_schema.get(update.update_type)
        if allowed_keys is None:
            violations.append(f"unauthorized update type: {update.update_type.value}")
        else:
            allowed_set = set(allowed_keys)
            for payload_key in update.payload:
                if payload_key not in allowed_set:
                    violations.append(f"unauthorized payload key: {payload_key}")

        if violations:
            return W1UpdateApplicationResult(
                update_id=update.update_id,
                applied=False,
                checkpoint_id=None,
                violations=tuple(violations),
                state_digest=self.get_state(update.scope).digest(),
            )

        if self._active_scope is None:
            self._active_scope = update.scope

        if key not in self._state:
            self._state[key] = dict(self._initial)
            self._updates[key] = []
            self._epoch[key] = 0

        merged = dict(self._state[key])
        merged.update(update.payload)
        self._state[key] = merged
        self._updates[key].append(update)
        self._epoch[key] += 1

        return W1UpdateApplicationResult(
            update_id=update.update_id,
            applied=True,
            checkpoint_id=None,
            violations=(),
            state_digest=self.get_state(update.scope).digest(),
        )

    def checkpoint(self) -> str:
        if self._active_scope is None:
            cp_id = f"cp-{uuid4().hex}"
            self._checkpoints[cp_id] = (cp_id, {}, (), 0)
            return cp_id
        key = self._key(self._active_scope)
        cp_id = f"cp-{uuid4().hex}"
        self._checkpoints[cp_id] = (
            cp_id,
            dict(self._state.get(key, {})),
            tuple(self._updates.get(key, ())),
            self._epoch.get(key, 0),
        )
        return cp_id

    def rollback_to(self, checkpoint_id: str) -> W1MemoryState:
        cp_id, state, updates, epoch = self._checkpoints[checkpoint_id]
        if self._active_scope is None:
            raise ValueError("no active scope to rollback")
        key = self._key(self._active_scope)
        self._state[key] = dict(state)
        self._updates[key] = list(updates)
        self._epoch[key] = epoch
        return self.get_state(self._active_scope)
