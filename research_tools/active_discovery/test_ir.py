from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .canonical import canonical_json, content_digest


SCHEMA_VERSION = "active-discovery-test-ir/v1"


class TestIRValidationError(ValueError):
    """An evaluator candidate escaped the inert closed TestIR grammar."""


class AssertionSource(str, Enum):
    STATUS_CODE = "STATUS_CODE"
    STDOUT = "STDOUT"
    STDERR = "STDERR"
    OUTPUT_JSON = "OUTPUT_JSON"
    STATE_DIGEST = "STATE_DIGEST"


class AssertionOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    CONTAINS = "CONTAINS"


def _closed(raw: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    unknown = set(raw) - expected
    missing = expected - set(raw)
    if unknown:
        raise TestIRValidationError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise TestIRValidationError(f"{label} is missing fields: {sorted(missing)}")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestIRValidationError(f"{field} must be a non-empty string")
    return value


def _canonical_payload(value: Any) -> str:
    if not isinstance(value, str):
        raise TestIRValidationError("payload_json must be canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TestIRValidationError("payload_json must be valid JSON") from exc
    if not isinstance(decoded, dict) or canonical_json(decoded) != value:
        raise TestIRValidationError("payload_json must be a canonical JSON object")
    return value


def _fixed_literal(value: Any) -> None | bool | int | str | tuple[Any, ...]:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith(("$actual", "actual.", "${")):
            raise TestIRValidationError("expected must be a fixed literal")
        return value
    if isinstance(value, list):
        return tuple(_fixed_literal(item) for item in value)
    raise TestIRValidationError("expected must be a fixed literal")


@dataclass(frozen=True, slots=True)
class TestAssertion:
    source: AssertionSource
    operator: AssertionOperator
    expected: None | bool | int | str | tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class TestCase:
    test_id: str
    operation_id: str
    payload_json: str
    assertions: tuple[TestAssertion, ...]
    provenance_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestIR:
    schema_version: str
    tests: tuple[TestCase, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> TestIR:
        _closed(raw, frozenset({"schema_version", "tests"}), "TestIR")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise TestIRValidationError("unsupported TestIR schema_version")
        tests_raw = raw["tests"]
        if not isinstance(tests_raw, list) or not tests_raw:
            raise TestIRValidationError("TestIR requires a non-empty tests list")
        tests: list[TestCase] = []
        for test_raw in tests_raw:
            if not isinstance(test_raw, Mapping):
                raise TestIRValidationError("each test must be an object")
            _closed(
                test_raw,
                frozenset(
                    {
                        "test_id",
                        "operation_id",
                        "payload_json",
                        "assertions",
                        "provenance_refs",
                    }
                ),
                "test case",
            )
            assertions_raw = test_raw["assertions"]
            if not isinstance(assertions_raw, list) or not assertions_raw:
                raise TestIRValidationError("test case requires assertions")
            assertions: list[TestAssertion] = []
            for assertion_raw in assertions_raw:
                if not isinstance(assertion_raw, Mapping):
                    raise TestIRValidationError("assertion must be an object")
                _closed(
                    assertion_raw,
                    frozenset({"source", "operator", "expected"}),
                    "assertion",
                )
                try:
                    source = AssertionSource(assertion_raw["source"])
                    operator = AssertionOperator(assertion_raw["operator"])
                except (TypeError, ValueError) as exc:
                    raise TestIRValidationError(
                        "assertion enum is not allowed"
                    ) from exc
                expected = _fixed_literal(assertion_raw["expected"])
                if operator is AssertionOperator.CONTAINS and not isinstance(
                    expected, str
                ):
                    raise TestIRValidationError(
                        "CONTAINS requires a fixed string literal"
                    )
                assertions.append(TestAssertion(source, operator, expected))

            refs_raw = test_raw["provenance_refs"]
            if (
                not isinstance(refs_raw, list)
                or not refs_raw
                or any(not isinstance(ref, str) or not ref for ref in refs_raw)
            ):
                raise TestIRValidationError("test case requires provenance refs")
            refs = tuple(sorted(set(refs_raw)))
            tests.append(
                TestCase(
                    test_id=_name(test_raw["test_id"], "test_id"),
                    operation_id=_name(test_raw["operation_id"], "operation_id"),
                    payload_json=_canonical_payload(test_raw["payload_json"]),
                    assertions=tuple(assertions),
                    provenance_refs=refs,
                )
            )
        ids = tuple(item.test_id for item in tests)
        if len(ids) != len(set(ids)):
            raise TestIRValidationError("test_id values must be unique")
        return cls(schema_version=SCHEMA_VERSION, tests=tuple(tests))

    @property
    def ir_digest(self) -> str:
        return content_digest("test-ir", asdict(self))
