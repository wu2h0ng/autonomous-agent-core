"""Authority contracts and read-only registries for freeze/run and C7."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import Field

from experiments.w1w2_live_adaptation._contracts import (
    ContractModel,
    NonEmptyStr,
    UtcDateTime,
    content_digest,
)
from experiments.w1w2_live_adaptation.w1_state import W1Scope


class FreezeAuthorization(ContractModel):
    """Externally issued, content-bound freeze/run authorization.

    This package cannot mint one; it must be resolved from an injected registry.
    """

    receipt_id: NonEmptyStr
    authorized_scope: W1Scope
    authorized_sets_digest: NonEmptyStr
    run_digest: NonEmptyStr
    issued_by: NonEmptyStr
    issued_at: UtcDateTime
    expires_at: UtcDateTime

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


class FreezeAuthorizationRegistry(Protocol):
    """Read-only registry for canonical freeze/run authorizations."""

    def resolve(self, receipt_id: str) -> FreezeAuthorization | None:
        ...


class C7Snapshot(ContractModel):
    """Immutable correction snapshot visible to candidates."""

    correction_id: NonEmptyStr
    scope_id: NonEmptyStr
    halted: bool
    epoch: int = Field(ge=0)


class C7Controller:
    """Private external correction capability. Candidates never receive this."""

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

    def reset(self) -> None:
        """Reset internal state for a fresh characterization/run. External only."""
        self._halted = False
        self._halt_reason = None


def make_run_digest(
    arm_name: str,
    seed: int,
    n_steps: int,
    authorized_sets_digest: str,
) -> str:
    payload = {
        "arm_name": arm_name,
        "seed": seed,
        "n_steps": n_steps,
        "authorized_sets_digest": authorized_sets_digest,
    }
    return content_digest(payload)


def make_freeze_authorization(
    scope: W1Scope,
    authorized_sets_digest: str,
    arm_name: str,
    seed: int,
    n_steps: int,
    issued_by: str = "external-test-authority",
    lifetime_seconds: int = 60,
) -> FreezeAuthorization:
    now = datetime.now(timezone.utc)
    run_digest = make_run_digest(arm_name, seed, n_steps, authorized_sets_digest)
    return FreezeAuthorization(
        receipt_id=f"fa-{uuid4().hex}",
        authorized_scope=scope,
        authorized_sets_digest=authorized_sets_digest,
        run_digest=run_digest,
        issued_by=issued_by,
        issued_at=now,
        expires_at=datetime.fromtimestamp(now.timestamp() + lifetime_seconds, tz=timezone.utc),
    )
