from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..canonical import content_digest
from ..contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from ..referee import HiddenScore


class OpaqueQuotaError(ValueError):
    """The F3 development family received an invalid hidden configuration."""


@dataclass(frozen=True, slots=True)
class OpaqueQuotaSemantics:
    capacity_units: int
    refill_per_step: int
    refill_before_request: bool
    deny_consumes: bool

    def __post_init__(self) -> None:
        for value, field, minimum in (
            (self.capacity_units, "capacity_units", 1),
            (self.refill_per_step, "refill_per_step", 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise OpaqueQuotaError(f"{field} must be an integer >= {minimum}")
        if not isinstance(self.refill_before_request, bool) or not isinstance(
            self.deny_consumes, bool
        ):
            raise OpaqueQuotaError("quota switches must be booleans")


@dataclass(frozen=True, slots=True)
class OpaqueQuotaSnapshot:
    clock: int
    available_units: int
    state_digest: str


def _opaque(seed: int, role: str, prefix: str) -> str:
    return f"{prefix}_{content_digest('opaque-f3-label', {'seed': seed, 'role': role})[:12]}"


class OpaqueQuotaFamily:
    """F3: deterministic refill/consumption dynamics behind opaque labels."""

    def __init__(self, *, seed: int, semantics: OpaqueQuotaSemantics) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise OpaqueQuotaError("seed must be an integer")
        self._seed = seed
        self._semantics = semantics
        self._environment_id = _opaque(seed, "environment", "env")
        self._operation_id = _opaque(seed, "operation", "op")
        self._amount_field = _opaque(seed, "amount-field", "f")
        self._progress_field = _opaque(seed, "progress-field", "f")
        self._accepted_field = _opaque(seed, "accepted-field", "o")
        self._remaining_field = _opaque(seed, "remaining-field", "o")
        self._accepted_token = _opaque(seed, "accepted-token", "v")
        self._denied_token = _opaque(seed, "denied-token", "v")
        self._error_token = _opaque(seed, "error-token", "e")
        self._clock = 0
        self._available_units = semantics.capacity_units
        self._initial_state_digest = self.state_digest()

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return PublicEnvironmentDescriptor.create(
            environment_id=self._environment_id,
            operation_id=self._operation_id,
            schema={
                "inputs": [
                    {"field_id": self._amount_field, "shape": "integer"},
                    {"field_id": self._progress_field, "shape": "integer"},
                ],
                "outputs": [
                    {"field_id": self._accepted_field, "shape": "boolean"},
                    {"field_id": self._remaining_field, "shape": "integer"},
                ],
                "status_domain": [0, 3, 4],
            },
            documentation_fragments=(
                "Two non-negative integers request a state transition under optional logical progress.",
                "Acceptance and progress ordering are intentionally unspecified.",
            ),
            initial_state_digest=self._initial_state_digest,
        )

    def state_digest(self) -> str:
        return content_digest(
            "opaque-f3-state",
            {
                "environment_id": self._environment_id,
                "clock": self._clock,
                "available_units": self._available_units,
            },
        )

    def snapshot(self) -> OpaqueQuotaSnapshot:
        return OpaqueQuotaSnapshot(
            clock=self._clock,
            available_units=self._available_units,
            state_digest=self.state_digest(),
        )

    def restore(self, snapshot: OpaqueQuotaSnapshot) -> None:
        expected = content_digest(
            "opaque-f3-state",
            {
                "environment_id": self._environment_id,
                "clock": snapshot.clock,
                "available_units": snapshot.available_units,
            },
        )
        if snapshot.state_digest != expected:
            raise OpaqueQuotaError("snapshot digest mismatch")
        self._clock = snapshot.clock
        self._available_units = snapshot.available_units

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        if request.operation_id != self._operation_id:
            raise OpaqueQuotaError("operation id is outside the public descriptor")
        before = self.state_digest()
        if request.expected_state_digest != before:
            raise OpaqueQuotaError("request expected state is stale")
        parsed = self._parse(json.loads(request.payload_json))
        if parsed is None:
            return self._observation(
                request=request,
                before=before,
                status_code=4,
                accepted=False,
                stderr=self._error_token,
            )
        amount, progress = parsed
        if self._semantics.refill_before_request:
            self._progress(progress)
        accepted = amount <= self._available_units
        if accepted:
            self._available_units -= amount
        elif self._semantics.deny_consumes:
            self._available_units = max(0, self._available_units - amount)
        if not self._semantics.refill_before_request:
            self._progress(progress)
        return self._observation(
            request=request,
            before=before,
            status_code=0 if accepted else 3,
            accepted=accepted,
            stderr="",
        )

    def _parse(self, payload: dict[str, Any]) -> tuple[int, int] | None:
        if set(payload) != {self._amount_field, self._progress_field}:
            return None
        amount = payload[self._amount_field]
        progress = payload[self._progress_field]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (amount, progress)
        ):
            return None
        return amount, progress

    def _progress(self, steps: int) -> None:
        self._clock += steps
        self._available_units = min(
            self._semantics.capacity_units,
            self._available_units + steps * self._semantics.refill_per_step,
        )

    def _observation(
        self,
        *,
        request: ProbeRequest,
        before: str,
        status_code: int,
        accepted: bool,
        stderr: str,
    ) -> ProbeObservation:
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=status_code,
            stdout=self._accepted_token if accepted else self._denied_token,
            stderr=stderr,
            output={
                self._accepted_field: accepted,
                self._remaining_field: self._available_units,
            },
            before_state_digest=before,
            after_state_digest=self.state_digest(),
        )

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        return HiddenScore(
            score_micros=0,
            details_digest=content_digest(
                "opaque-f3-development-score",
                {
                    "mode": "NOT_EVIDENCE",
                    "bundle_digest": bundle_digest,
                    "transcript": [item.observation_digest for item in transcript],
                },
            ),
        )
