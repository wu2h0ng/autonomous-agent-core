from __future__ import annotations

from copy import deepcopy
from typing import cast

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


def _first_case(raw: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], raw["tests"])[0]


def _first_assertion(raw: dict[str, object]) -> dict[str, object]:
    case = _first_case(raw)
    return cast(list[dict[str, object]], case["assertions"])[0]


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


def test_ir_digest_is_stable_and_binds_every_variable_ir_field() -> None:
    baseline_raw = _test_ir(0)
    baseline = EvaluatorIR.from_mapping(baseline_raw)
    equivalent = EvaluatorIR.from_mapping(deepcopy(baseline_raw))

    test_id_variant = deepcopy(baseline_raw)
    _first_case(test_id_variant)["test_id"] = "test-status-2"
    operation_variant = deepcopy(baseline_raw)
    _first_case(operation_variant)["operation_id"] = "op_7b1b"
    payload_variant = deepcopy(baseline_raw)
    _first_case(payload_variant)["payload_json"] = '{"input":1}'
    source_variant = deepcopy(baseline_raw)
    _first_assertion(source_variant)["source"] = "STDOUT"
    operator_variant = deepcopy(baseline_raw)
    _first_assertion(operator_variant)["operator"] = "NE"
    expected_variant = deepcopy(baseline_raw)
    _first_assertion(expected_variant)["expected"] = 1
    provenance_variant = deepcopy(baseline_raw)
    _first_case(provenance_variant)["provenance_refs"] = ["observation:2"]

    variants = (
        test_id_variant,
        operation_variant,
        payload_variant,
        source_variant,
        operator_variant,
        expected_variant,
        provenance_variant,
    )

    assert equivalent.ir_digest == baseline.ir_digest
    assert all(
        EvaluatorIR.from_mapping(variant).ir_digest != baseline.ir_digest
        for variant in variants
    )
