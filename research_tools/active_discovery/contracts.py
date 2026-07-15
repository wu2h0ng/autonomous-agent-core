from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Mapping

from .canonical import canonical_json, content_digest


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractValidationError(ValueError):
    """A closed harness contract failed validation."""


def _closed_fields(raw: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown:
        raise ContractValidationError(f"unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractValidationError(f"missing fields: {sorted(missing)}")


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _canonical_object_json(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} must be canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ContractValidationError(f"{field} must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ContractValidationError(f"{field} must encode a JSON object")
    if canonical_json(decoded) != value:
        raise ContractValidationError(f"{field} must use canonical JSON encoding")
    return value


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    episode_id: str
    arm_id: str
    step_index: int
    probe_id: str
    operation_id: str
    payload_json: str
    expected_state_digest: str
    cost_units: int

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "episode_id",
            "arm_id",
            "step_index",
            "probe_id",
            "operation_id",
            "payload_json",
            "expected_state_digest",
            "cost_units",
        }
    )

    def __post_init__(self) -> None:
        _nonempty(self.episode_id, "episode_id")
        _nonempty(self.arm_id, "arm_id")
        _integer(self.step_index, "step_index")
        _nonempty(self.probe_id, "probe_id")
        _nonempty(self.operation_id, "operation_id")
        _canonical_object_json(self.payload_json, "payload_json")
        _sha256(self.expected_state_digest, "expected_state_digest")
        _integer(self.cost_units, "cost_units", minimum=1)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProbeRequest:
        _closed_fields(raw, cls.FIELDS)
        return cls(
            episode_id=_nonempty(raw["episode_id"], "episode_id"),
            arm_id=_nonempty(raw["arm_id"], "arm_id"),
            step_index=_integer(raw["step_index"], "step_index"),
            probe_id=_nonempty(raw["probe_id"], "probe_id"),
            operation_id=_nonempty(raw["operation_id"], "operation_id"),
            payload_json=_canonical_object_json(raw["payload_json"], "payload_json"),
            expected_state_digest=_sha256(
                raw["expected_state_digest"], "expected_state_digest"
            ),
            cost_units=_integer(raw["cost_units"], "cost_units", minimum=1),
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def request_digest(self) -> str:
        return content_digest("probe-request", self.to_mapping())


@dataclass(frozen=True, slots=True)
class PublicEnvironmentDescriptor:
    environment_id: str
    operation_id: str
    schema_json: str
    documentation_fragments: tuple[str, ...]
    initial_state_digest: str

    @classmethod
    def create(
        cls,
        *,
        environment_id: str,
        operation_id: str,
        schema: Mapping[str, Any],
        documentation_fragments: tuple[str, ...],
        initial_state_digest: str,
    ) -> PublicEnvironmentDescriptor:
        if not documentation_fragments or any(
            not item for item in documentation_fragments
        ):
            raise ContractValidationError("descriptor requires documentation fragments")
        return cls(
            environment_id=_nonempty(environment_id, "environment_id"),
            operation_id=_nonempty(operation_id, "operation_id"),
            schema_json=canonical_json(schema),
            documentation_fragments=tuple(documentation_fragments),
            initial_state_digest=_sha256(initial_state_digest, "initial_state_digest"),
        )

    @property
    def descriptor_digest(self) -> str:
        return content_digest("public-environment-descriptor", asdict(self))


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    episode_id: str
    step_index: int
    probe_id: str
    status_code: int
    stdout: str
    stderr: str
    output_json: str
    before_state_digest: str
    after_state_digest: str
    observation_digest: str

    @classmethod
    def create(
        cls,
        *,
        episode_id: str,
        step_index: int,
        probe_id: str,
        status_code: int,
        stdout: str,
        stderr: str,
        output: Mapping[str, Any],
        before_state_digest: str,
        after_state_digest: str,
    ) -> ProbeObservation:
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise ContractValidationError("status_code must be an integer")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ContractValidationError("stdout and stderr must be strings")
        payload = {
            "episode_id": _nonempty(episode_id, "episode_id"),
            "step_index": _integer(step_index, "step_index"),
            "probe_id": _nonempty(probe_id, "probe_id"),
            "status_code": status_code,
            "stdout": stdout,
            "stderr": stderr,
            "output_json": canonical_json(output),
            "before_state_digest": _sha256(before_state_digest, "before_state_digest"),
            "after_state_digest": _sha256(after_state_digest, "after_state_digest"),
        }
        return cls(
            **payload,
            observation_digest=content_digest("probe-observation", payload),
        )
