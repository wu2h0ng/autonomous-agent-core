from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..canonical import content_digest
from ..contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from ..referee import HiddenScore


class OpaqueExpiryError(ValueError):
    """The F2 development family received an invalid hidden configuration."""


@dataclass(frozen=True, slots=True)
class OpaqueExpirySemantics:
    lifetime_steps: int
    refresh_on_write: bool
    expires_at_boundary: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.lifetime_steps, bool)
            or not isinstance(self.lifetime_steps, int)
            or self.lifetime_steps < 1
        ):
            raise OpaqueExpiryError("lifetime_steps must be an integer >= 1")
        if not isinstance(self.refresh_on_write, bool) or not isinstance(
            self.expires_at_boundary, bool
        ):
            raise OpaqueExpiryError("expiry switches must be booleans")


@dataclass(frozen=True, slots=True)
class OpaqueExpirySnapshot:
    clock: int
    entries: tuple[tuple[str, str, int], ...]
    state_digest: str


def _opaque(seed: int, role: str, prefix: str) -> str:
    return f"{prefix}_{content_digest('opaque-f2-label', {'seed': seed, 'role': role})[:12]}"


class OpaqueExpiryFamily:
    """F2: deterministic logical-lifetime state machine behind opaque labels."""

    def __init__(self, *, seed: int, semantics: OpaqueExpirySemantics) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise OpaqueExpiryError("seed must be an integer")
        self._seed = seed
        self._semantics = semantics
        self._environment_id = _opaque(seed, "environment", "env")
        self._operation_id = _opaque(seed, "operation", "op")
        self._action_field = _opaque(seed, "action-field", "f")
        self._slot_field = _opaque(seed, "slot-field", "f")
        self._value_field = _opaque(seed, "value-field", "f")
        self._steps_field = _opaque(seed, "steps-field", "f")
        self._put_token = _opaque(seed, "put-token", "k")
        self._get_token = _opaque(seed, "get-token", "k")
        self._advance_token = _opaque(seed, "advance-token", "k")
        self._present_field = _opaque(seed, "present-field", "o")
        self._output_value_field = _opaque(seed, "output-value-field", "o")
        self._clock_field = _opaque(seed, "clock-field", "o")
        self._present_token = _opaque(seed, "present-token", "v")
        self._absent_token = _opaque(seed, "absent-token", "v")
        self._error_token = _opaque(seed, "error-token", "e")
        self._clock = 0
        self._entries: dict[str, tuple[str, int]] = {}
        self._initial_state_digest = self.state_digest()

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return PublicEnvironmentDescriptor.create(
            environment_id=self._environment_id,
            operation_id=self._operation_id,
            schema={
                "inputs": [
                    {"field_id": self._action_field, "shape": "token"},
                    {"field_id": self._slot_field, "shape": "string"},
                    {"field_id": self._value_field, "shape": "string"},
                    {"field_id": self._steps_field, "shape": "integer"},
                ],
                "command_tokens": [
                    self._put_token,
                    self._get_token,
                    self._advance_token,
                ],
                "outputs": [
                    {"field_id": self._present_field, "shape": "boolean"},
                    {"field_id": self._output_value_field, "shape": "string"},
                    {"field_id": self._clock_field, "shape": "integer"},
                ],
                "status_domain": [0, 4],
            },
            documentation_fragments=(
                "One opaque token changes or inspects a retained record under logical progress.",
                "Boundary and replacement behavior are intentionally unspecified.",
            ),
            initial_state_digest=self._initial_state_digest,
        )

    def state_digest(self) -> str:
        return content_digest(
            "opaque-f2-state",
            {
                "environment_id": self._environment_id,
                "clock": self._clock,
                "entries": [
                    {"slot": slot, "value": value, "written_at": written_at}
                    for slot, (value, written_at) in sorted(self._entries.items())
                ],
            },
        )

    def snapshot(self) -> OpaqueExpirySnapshot:
        return OpaqueExpirySnapshot(
            clock=self._clock,
            entries=tuple(
                (slot, value, written_at)
                for slot, (value, written_at) in sorted(self._entries.items())
            ),
            state_digest=self.state_digest(),
        )

    def restore(self, snapshot: OpaqueExpirySnapshot) -> None:
        payload = {
            "environment_id": self._environment_id,
            "clock": snapshot.clock,
            "entries": [
                {"slot": slot, "value": value, "written_at": written_at}
                for slot, value, written_at in snapshot.entries
            ],
        }
        if content_digest("opaque-f2-state", payload) != snapshot.state_digest:
            raise OpaqueExpiryError("snapshot digest mismatch")
        self._clock = snapshot.clock
        self._entries = {
            slot: (value, written_at) for slot, value, written_at in snapshot.entries
        }

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        if request.operation_id != self._operation_id:
            raise OpaqueExpiryError("operation id is outside the public descriptor")
        before = self.state_digest()
        if request.expected_state_digest != before:
            raise OpaqueExpiryError("request expected state is stale")
        payload = json.loads(request.payload_json)
        parsed = self._parse(payload)
        if parsed is None:
            return self._observation(
                request=request,
                before=before,
                status_code=4,
                present=False,
                value="",
                stderr=self._error_token,
            )

        action, slot, value, steps = parsed
        self._purge_expired()
        present = False
        output_value = ""
        if action == self._put_token:
            prior = self._entries.get(slot)
            written_at = (
                self._clock
                if prior is None or self._semantics.refresh_on_write
                else prior[1]
            )
            self._entries[slot] = (value, written_at)
            present = True
            output_value = value
        elif action == self._get_token:
            entry = self._entries.get(slot)
            if entry is not None:
                present = True
                output_value = entry[0]
        else:
            self._clock += steps
            self._purge_expired()

        return self._observation(
            request=request,
            before=before,
            status_code=0,
            present=present,
            value=output_value,
            stderr="",
        )

    def _parse(self, payload: dict[str, Any]) -> tuple[str, str, str, int] | None:
        if set(payload) != {
            self._action_field,
            self._slot_field,
            self._value_field,
            self._steps_field,
        }:
            return None
        action = payload[self._action_field]
        slot = payload[self._slot_field]
        value = payload[self._value_field]
        steps = payload[self._steps_field]
        if (
            not isinstance(action, str)
            or not isinstance(slot, str)
            or not isinstance(value, str)
            or isinstance(steps, bool)
            or not isinstance(steps, int)
            or steps < 0
        ):
            return None
        if action == self._put_token:
            return (action, slot, value, steps) if slot and steps == 0 else None
        if action == self._get_token:
            return (
                (action, slot, value, steps)
                if slot and not value and steps == 0
                else None
            )
        if action == self._advance_token:
            return (
                (action, slot, value, steps)
                if not slot and not value and steps >= 1
                else None
            )
        return None

    def _purge_expired(self) -> None:
        def expired(written_at: int) -> bool:
            age = self._clock - written_at
            if self._semantics.expires_at_boundary:
                return age >= self._semantics.lifetime_steps
            return age > self._semantics.lifetime_steps

        self._entries = {
            slot: entry
            for slot, entry in self._entries.items()
            if not expired(entry[1])
        }

    def _observation(
        self,
        *,
        request: ProbeRequest,
        before: str,
        status_code: int,
        present: bool,
        value: str,
        stderr: str,
    ) -> ProbeObservation:
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=status_code,
            stdout=self._present_token if present else self._absent_token,
            stderr=stderr,
            output={
                self._present_field: present,
                self._output_value_field: value,
                self._clock_field: self._clock,
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
                "opaque-f2-development-score",
                {
                    "mode": "NOT_EVIDENCE",
                    "bundle_digest": bundle_digest,
                    "transcript": [item.observation_digest for item in transcript],
                },
            ),
        )
