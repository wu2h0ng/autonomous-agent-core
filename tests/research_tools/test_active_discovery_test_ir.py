from __future__ import annotations

import pytest

from research_tools.active_discovery.test_ir import (
    TestIR as EvaluatorIR,
    TestIRValidationError as IRValidationError,
)


def _test_ir(expected: object) -> dict[str, object]:
    return {
        "schema_version": "active-discovery-test-ir/v1",
        "tests": [
            {
                "test_id": "test-status",
                "operation_id": "op_7b1a",
                "payload_json": "{}",
                "assertions": [
                    {
                        "source": "STATUS_CODE",
                        "operator": "EQ",
                        "expected": expected,
                    }
                ],
                "provenance_refs": ["observation:1"],
            }
        ],
    }


def test_test_ir_rejects_dynamic_expected_values() -> None:
    with pytest.raises(IRValidationError, match="fixed literal"):
        EvaluatorIR.from_mapping(_test_ir({"from_actual": "STATUS_CODE"}))


def test_test_ir_rejects_tautological_actual_reference() -> None:
    with pytest.raises(IRValidationError, match="fixed literal"):
        EvaluatorIR.from_mapping(_test_ir("$actual.status_code"))


def test_test_ir_rejects_arbitrary_code_fields() -> None:
    raw = _test_ir(0)
    test_case = raw["tests"][0]  # type: ignore[index]
    test_case["python"] = "import os"  # type: ignore[index]

    with pytest.raises(IRValidationError, match="unknown fields"):
        EvaluatorIR.from_mapping(raw)
