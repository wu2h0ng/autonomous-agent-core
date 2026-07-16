"""External run-custody and correction-boundary contracts.

This package deliberately has no receipt minting or registry mutation API.  A
result-bearing run can consume only an opaque receipt id through an injected,
read-only custody resolver.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
)
from experiments.w1w2_live_adaptation.w1_state import W1Scope


class RunAuthorizationBinding(ContractModel):
    """Exact content that an independent freezer authorizes."""

    scope: W1Scope
    arm_name: NonEmptyStr
    seed: int
    n_steps: int = Field(gt=0)
    option_content_digest: NonEmptyStr
    evaluator_gate_digest: NonEmptyStr
    experiment_content_digest: NonEmptyStr


class CanonicalRunAuthorization(ContractModel):
    """Canonical resolver output, never constructed by the falsifier package."""

    receipt_id: NonEmptyStr
    binding: RunAuthorizationBinding
    issuer_id: NonEmptyStr
    issued_at: UtcDateTime
    expires_at: UtcDateTime

    def is_current(self, now: datetime) -> bool:
        now = now.astimezone(timezone.utc)
        return self.issued_at <= now < self.expires_at


class RunAuthorizationResolver(Protocol):
    """External, atomic one-time custody resolver."""

    def consume(
        self,
        receipt_id: str,
        expected: RunAuthorizationBinding,
    ) -> CanonicalRunAuthorization | None:
        """Atomically authenticate, bind and consume a canonical receipt."""


class C7Snapshot(ContractModel):
    """Immutable correction snapshot visible to candidate code."""

    correction_id: NonEmptyStr
    scope_id: NonEmptyStr
    halted: bool
    epoch: int = Field(ge=0)


class C7Controller:
    """External evaluator/controller capability; candidate arms receive snapshots only."""

    def __init__(self, correction_id: str, scope_id: str) -> None:
        self._correction_id = correction_id
        self._scope_id = scope_id
        self._halted = False
        self._epoch = 0
        self._halt_reason: str | None = None

    @property
    def snapshot(self) -> C7Snapshot:
        return C7Snapshot(
            correction_id=self._correction_id,
            scope_id=self._scope_id,
            halted=self._halted,
            epoch=self._epoch,
        )

    def halt(self, reason: str) -> C7Snapshot:
        self._halted = True
        self._epoch += 1
        self._halt_reason = reason
        return self.snapshot

    def is_halted(self) -> bool:
        return self._halted
