"""Tests for MechanicalExtractor (spec §15.1, M-1 through M-8)."""

from __future__ import annotations


from agent_os_contracts import CheckType, PredicateKind
from agent_os_core.mechanical_extractor import extract_structural_predicates


def _email_tool_schema() -> dict:
    return {
        "tool_name": "send_email",
        "description": "Send an email",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "format": "email", "pattern": "^[^@]+@"},
                "body": {"type": "string", "minLength": 1, "maxLength": 10000},
                "cabin": {"type": "string", "enum": ["economy", "business"]},
                "retries": {"type": "integer", "minimum": 0, "maximum": 5},
            },
            "required": ["to", "body"],
        },
        "response": {
            "type": "object",
            "properties": {
                "status_code": {"type": "integer"},
                "body": {
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
            },
        },
        "errors": [
            {"status": 429, "description": "rate limited"},
            {"status": 500, "description": "internal error"},
        ],
        "side_effect": "NON_IDEMPOTENT_NON_QUERYABLE",
    }


class TestMechanicalExtractor:
    def test_m1_required_typed_parameter(self) -> None:
        """M-1: required typed parameter → FIELD_PRESENCE + TYPE."""
        predicates, _ = extract_structural_predicates([_email_tool_schema()])
        field_presence = [
            p
            for p in predicates
            if p.check_type == CheckType.FIELD_PRESENCE
            and "to" in p.description
            and "parameter" in p.description
        ]
        type_p = [
            p
            for p in predicates
            if p.check_type == CheckType.TYPE and "to" in p.description
        ]
        assert len(field_presence) == 1
        assert len(type_p) == 1
        assert field_presence[0].kind == PredicateKind.STRUCTURAL
        assert field_presence[0].confidence == 1.0
        assert field_presence[0].falsifiable is True
        assert field_presence[0].blocking is True
        assert type_p[0].check_params["expected_type"] == "string"

    def test_m2_enum_parameter(self) -> None:
        """M-2: enum parameter → ENUM predicate."""
        predicates, _ = extract_structural_predicates([_email_tool_schema()])
        enum_p = [p for p in predicates if p.check_type == CheckType.ENUM]
        assert len(enum_p) == 1
        assert enum_p[0].check_params["allowed_values"] == ["economy", "business"]

    def test_m3_range_parameter(self) -> None:
        """M-3: min/max parameter → RANGE predicate."""
        predicates, _ = extract_structural_predicates([_email_tool_schema()])
        range_p = [p for p in predicates if p.check_type == CheckType.RANGE]
        # body (minLength/maxLength) + retries (minimum/maximum)
        assert len(range_p) == 2
        retries_p = [p for p in range_p if "retries" in p.description][0]
        assert retries_p.check_params["min"] == 0
        assert retries_p.check_params["max"] == 5

    def test_m4_success_response_with_id(self) -> None:
        """M-4: success response with ID field → TOOL_RESPONSE + evidence binding."""
        predicates, _ = extract_structural_predicates([_email_tool_schema()])
        tool_resp = [p for p in predicates if p.check_type == CheckType.TOOL_RESPONSE]
        assert len(tool_resp) == 1
        assert tool_resp[0].check_params["tool_name"] == "send_email"
        assert len(tool_resp[0].evidence_bindings) >= 1
        # message_id evidence anchor
        id_presence = [
            p
            for p in predicates
            if p.check_type == CheckType.FIELD_PRESENCE
            and "message_id" in p.description
        ]
        assert len(id_presence) == 1

    def test_m5_documented_error_failure_path(self) -> None:
        """M-5: documented 4xx/5xx → FailurePath."""
        _, fps = extract_structural_predicates([_email_tool_schema()])
        triggers = " ".join(fp.trigger for fp in fps)
        assert "429" in triggers
        assert "500" in triggers
        fp_429 = [fp for fp in fps if "429" in fp.trigger][0]
        assert fp_429.action == "abort"
        fp_500 = [fp for fp in fps if "500" in fp.trigger][0]
        assert fp_500.action == "retry"
        assert fp_500.max_retries == 2

    def test_m6_non_idempotent_failure_path(self) -> None:
        """M-6: NON_IDEMPOTENT_NON_QUERYABLE → FailurePath action=escalate."""
        _, fps = extract_structural_predicates([_email_tool_schema()])
        escalate = [fp for fp in fps if fp.action == "escalate"]
        assert len(escalate) == 1
        assert escalate[0].escalation_target == "human"

    def test_m7_empty_schema_list(self) -> None:
        """M-7: empty tool schema list → zero structural predicates."""
        predicates, fps = extract_structural_predicates([])
        assert predicates == []
        assert fps == []

    def test_m8_pure_function(self) -> None:
        """M-8: same input → byte-identical output."""
        schema = _email_tool_schema()
        preds1, fps1 = extract_structural_predicates([schema])
        preds2, fps2 = extract_structural_predicates([schema])
        assert [p.model_dump(mode="json") for p in preds1] == [
            p.model_dump(mode="json") for p in preds2
        ]
        assert [fp.model_dump(mode="json") for fp in fps1] == [
            fp.model_dump(mode="json") for fp in fps2
        ]

    def test_regex_pattern_extracted(self) -> None:
        predicates, _ = extract_structural_predicates([_email_tool_schema()])
        regex_p = [p for p in predicates if p.check_type == CheckType.REGEX]
        assert len(regex_p) == 1
        assert regex_p[0].check_params["pattern"] == "^[^@]+@"

    def test_tool_without_response_schema(self) -> None:
        schema = {
            "tool_name": "no_response",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        }
        predicates, fps = extract_structural_predicates([schema])
        # Only parameter predicates, no TOOL_RESPONSE
        assert all(p.check_type != CheckType.TOOL_RESPONSE for p in predicates)
        assert fps == []

    def test_malformed_schema_skipped(self) -> None:
        predicates, fps = extract_structural_predicates(
            [
                "not a dict",  # type: ignore[list-item]
                {"tool_name": ""},  # empty name
                {"tool_name": 123},  # wrong type
                _email_tool_schema(),
            ]
        )
        # Only the valid email schema produces predicates
        assert all(
            p.check_params.get("tool_name") in (None, "send_email")
            or "send_email" in p.description
            or p.check_params.get("field", "").startswith("$.")
            for p in predicates
        )
