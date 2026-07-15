from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..canonical import content_digest
from ..contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from ..referee import HiddenScore


class OpaqueCliError(ValueError):
    """The development family received a protocol-invalid operation."""


class RepeatMode(str, Enum):
    FIRST = "FIRST"
    LAST = "LAST"
    ERROR = "ERROR"


class UnknownMode(str, Enum):
    IGNORE = "IGNORE"
    ERROR = "ERROR"


_SOURCES = frozenset({"sequence", "map_one", "map_two"})


@dataclass(frozen=True, slots=True)
class OpaqueCliSemantics:
    source_precedence: tuple[str, str, str]
    repeat_mode: RepeatMode
    unknown_mode: UnknownMode
    empty_is_missing: bool
    atomic_on_error: bool

    def __post_init__(self) -> None:
        if set(self.source_precedence) != _SOURCES:
            raise OpaqueCliError(
                "source_precedence must be a permutation of all sources"
            )


@dataclass(frozen=True, slots=True)
class OpaqueCliSnapshot:
    retained_value: str
    state_digest: str


def _opaque(seed: int, role: str, prefix: str) -> str:
    return f"{prefix}_{content_digest('opaque-cli-label', {'seed': seed, 'role': role})[:12]}"


class OpaqueCliFamily:
    """Stateful, deterministic F1 fixture exposed only through opaque contracts."""

    def __init__(self, *, seed: int, semantics: OpaqueCliSemantics) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise OpaqueCliError("seed must be an integer")
        self._seed = seed
        self._semantics = semantics
        self._environment_id = _opaque(seed, "environment", "env")
        self._operation_id = _opaque(seed, "operation", "op")
        self._sequence_field = _opaque(seed, "sequence-field", "f")
        self._map_one_field = _opaque(seed, "map-one-field", "f")
        self._map_two_field = _opaque(seed, "map-two-field", "f")
        self._setting_token = _opaque(seed, "setting-token", "k")
        self._output_field = _opaque(seed, "output-field", "o")
        self._error_token = _opaque(seed, "error-token", "e")
        self._initial_value = _opaque(seed, "initial-value", "v")
        self._retained_value = self._initial_value
        self._initial_state_digest = self.state_digest()

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        schema = {
            "input_fields": [
                {"field_id": self._sequence_field, "shape": "sequence<string>"},
                {"field_id": self._map_one_field, "shape": "map<string,string>"},
                {"field_id": self._map_two_field, "shape": "map<string,string>"},
            ],
            "tokens": {"setting": self._setting_token},
            "output_field": self._output_field,
            "status_domain": [0, 2],
        }
        return PublicEnvironmentDescriptor.create(
            environment_id=self._environment_id,
            operation_id=self._operation_id,
            schema=schema,
            documentation_fragments=(
                "One ordered text collection and two text maps may supply a retained scalar.",
                "Input conflict, empty-value, and failure behavior are intentionally unspecified.",
            ),
            initial_state_digest=self._initial_state_digest,
        )

    def state_digest(self) -> str:
        return content_digest(
            "opaque-cli-state",
            {"environment_id": self._environment_id, "value": self._retained_value},
        )

    def snapshot(self) -> OpaqueCliSnapshot:
        return OpaqueCliSnapshot(self._retained_value, self.state_digest())

    def restore(self, snapshot: OpaqueCliSnapshot) -> None:
        expected = content_digest(
            "opaque-cli-state",
            {"environment_id": self._environment_id, "value": snapshot.retained_value},
        )
        if snapshot.state_digest != expected:
            raise OpaqueCliError("snapshot digest mismatch")
        self._retained_value = snapshot.retained_value

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        if request.operation_id != self._operation_id:
            raise OpaqueCliError("operation id is outside the public descriptor")
        before = self.state_digest()
        if request.expected_state_digest != before:
            raise OpaqueCliError("request expected state is stale")
        payload = json.loads(request.payload_json)
        candidates, parse_error = self._parse_candidates(payload)
        selected = next(
            (
                candidates[source]
                for source in self._semantics.source_precedence
                if candidates.get(source) is not None
            ),
            None,
        )

        if parse_error:
            if not self._semantics.atomic_on_error and selected is not None:
                self._retained_value = selected
            status_code = 2
            stdout = ""
            stderr = self._error_token
        else:
            if selected is not None:
                self._retained_value = selected
            status_code = 0
            stdout = self._retained_value
            stderr = ""

        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=status_code,
            stdout=stdout,
            stderr=stderr,
            output={self._output_field: self._retained_value},
            before_state_digest=before,
            after_state_digest=self.state_digest(),
        )

    def _parse_candidates(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, str | None], bool]:
        expected_fields = {
            self._sequence_field,
            self._map_one_field,
            self._map_two_field,
        }
        parse_error = set(payload) != expected_fields
        sequence = payload.get(self._sequence_field, [])
        map_one = payload.get(self._map_one_field, {})
        map_two = payload.get(self._map_two_field, {})
        if not isinstance(sequence, list) or any(
            not isinstance(item, str) for item in sequence
        ):
            sequence = []
            parse_error = True
        if not isinstance(map_one, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in getattr(map_one, "items", lambda: ())()
        ):
            map_one = {}
            parse_error = True
        if not isinstance(map_two, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in getattr(map_two, "items", lambda: ())()
        ):
            map_two = {}
            parse_error = True

        sequence_values: list[str] = []
        unknown_seen = False
        for token in sequence:
            if "=" not in token:
                unknown_seen = True
                continue
            key, value = token.split("=", 1)
            if key == self._setting_token:
                sequence_values.append(value)
            else:
                unknown_seen = True
        for mapping in (map_one, map_two):
            if any(key != self._setting_token for key in mapping):
                unknown_seen = True

        repeated = len(sequence_values) > 1
        if repeated and self._semantics.repeat_mode is RepeatMode.ERROR:
            parse_error = True
        if unknown_seen and self._semantics.unknown_mode is UnknownMode.ERROR:
            parse_error = True

        sequence_value: str | None = None
        if sequence_values:
            if self._semantics.repeat_mode is RepeatMode.FIRST:
                sequence_value = sequence_values[0]
            else:
                sequence_value = sequence_values[-1]
        candidates: dict[str, str | None] = {
            "sequence": sequence_value,
            "map_one": map_one.get(self._setting_token),
            "map_two": map_two.get(self._setting_token),
        }
        if self._semantics.empty_is_missing:
            candidates = {
                source: None if value == "" else value
                for source, value in candidates.items()
            }
        return candidates, parse_error

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        return HiddenScore(
            score_micros=0,
            details_digest=content_digest(
                "opaque-cli-development-score",
                {
                    "mode": "NOT_EVIDENCE",
                    "bundle_digest": bundle_digest,
                    "transcript": [item.observation_digest for item in transcript],
                },
            ),
        )
