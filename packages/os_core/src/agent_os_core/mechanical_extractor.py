"""Mechanical extractor: deterministic derivation of structural predicates from
tool JSON Schemas (spec §6, Stage 1).

No LLM. No I/O beyond schema parsing. Pure functions.

Tool schema format (dict):
    {
        "tool_name": str,
        "description": str,
        "parameters": {<JSON Schema for input>},
        "response": {<JSON Schema for success response>},
        "errors": [{"status": int, "description": str}, ...],
        "side_effect": "NON_IDEMPOTENT_NON_QUERYABLE" | ...,  # optional
    }
"""

from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    CheckType,
    EvidenceBinding,
    EvidenceSourceType,
    FailurePath,
    PredicateKind,
    SuccessPredicate,
    derive_predicate_id,
)

_EXTRACTOR_SOURCE = "mechanical:tool_response_schema"

# JSON Schema type → our expected_type vocabulary
_JSON_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def _binding(
    tool_name: str,
    extract_path: str | None,
    relation: str,
    binding_id: str,
    source_type: EvidenceSourceType = EvidenceSourceType.TOOL_RESPONSE,
    source_selector: str | None = None,
) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id=binding_id,
        source_type=source_type,
        source_selector=source_selector or f"{tool_name}:last",
        extract_path=extract_path,
        relation=relation,
    )


def _make_predicate(
    *,
    description: str,
    check_type: CheckType,
    check_params: dict[str, Any],
    bindings: tuple[EvidenceBinding, ...],
    kind: PredicateKind = PredicateKind.STRUCTURAL,
    blocking: bool = True,
    confidence: float = 1.0,
    source: str = _EXTRACTOR_SOURCE,
    falsifiable: bool = True,
    meta_template: str | None = None,
) -> SuccessPredicate:
    pid = derive_predicate_id(kind, check_type, check_params, bindings)
    return SuccessPredicate(
        predicate_id=pid,
        kind=kind,
        description=description,
        check_type=check_type,
        check_params=check_params,
        evidence_bindings=bindings,
        blocking=blocking,
        confidence=confidence,
        source=source,
        falsifiable=falsifiable,
        meta_template=meta_template,
    )


def _binding_counter(start: int = 0) -> Any:
    """Generate binding IDs: bind:1, bind:2, ..."""
    n = start

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"bind:{n}"

    return next_id


def _extract_parameter_predicates(
    tool_name: str, parameters: dict[str, Any], next_binding_id: Any
) -> list[SuccessPredicate]:
    """Derive FIELD_PRESENCE / TYPE / ENUM / RANGE / REGEX from input schema."""
    predicates: list[SuccessPredicate] = []
    if not isinstance(parameters, dict):
        return predicates

    properties: dict[str, Any] = parameters.get("properties", {})
    required: list[str] = parameters.get("required", [])

    if not isinstance(properties, dict):
        return predicates

    for param_name, param_schema in properties.items():
        if not isinstance(param_schema, dict):
            continue
        is_required = param_name in required
        json_type = param_schema.get("type")

        # FIELD_PRESENCE + TYPE for required typed parameters
        if is_required and json_type in _JSON_TYPE_MAP:
            bindings = (
                _binding(
                    tool_name,
                    f"$.{param_name}",
                    f"parameter {param_name} is present and typed",
                    next_binding_id(),
                    source_selector=f"{tool_name}:last",
                ),
            )
            predicates.append(
                _make_predicate(
                    description=f"{tool_name} parameter '{param_name}' is present",
                    check_type=CheckType.FIELD_PRESENCE,
                    check_params={"field": f"$.{param_name}"},
                    bindings=bindings,
                    meta_template="schema",
                )
            )
            bindings_type = (
                _binding(
                    tool_name,
                    f"$.{param_name}",
                    f"parameter {param_name} is of type {json_type}",
                    next_binding_id(),
                    source_selector=f"{tool_name}:last",
                ),
            )
            predicates.append(
                _make_predicate(
                    description=(
                        f"{tool_name} parameter '{param_name}' is type {json_type}"
                    ),
                    check_type=CheckType.TYPE,
                    check_params={
                        "field": f"$.{param_name}",
                        "expected_type": _JSON_TYPE_MAP[json_type],
                    },
                    bindings=bindings_type,
                    meta_template="schema",
                )
            )

        # ENUM
        if "enum" in param_schema and isinstance(param_schema["enum"], list):
            bindings_enum = (
                _binding(
                    tool_name,
                    f"$.{param_name}",
                    f"parameter {param_name} is in allowed set",
                    next_binding_id(),
                    source_selector=f"{tool_name}:last",
                ),
            )
            predicates.append(
                _make_predicate(
                    description=(
                        f"{tool_name} parameter '{param_name}' is in allowed values"
                    ),
                    check_type=CheckType.ENUM,
                    check_params={
                        "field": f"$.{param_name}",
                        "allowed_values": list(param_schema["enum"]),
                    },
                    bindings=bindings_enum,
                    meta_template="schema",
                )
            )

        # RANGE (minimum/maximum for numbers, minLength/maxLength for strings)
        range_bounds: dict[str, Any] = {}
        if "minimum" in param_schema:
            range_bounds["min"] = param_schema["minimum"]
        if "maximum" in param_schema:
            range_bounds["max"] = param_schema["maximum"]
        if "minLength" in param_schema:
            range_bounds["min"] = param_schema["minLength"]
        if "maxLength" in param_schema:
            range_bounds["max"] = param_schema["maxLength"]
        if range_bounds:
            bindings_range = (
                _binding(
                    tool_name,
                    f"$.{param_name}",
                    f"parameter {param_name} within bounds",
                    next_binding_id(),
                    source_selector=f"{tool_name}:last",
                ),
            )
            predicates.append(
                _make_predicate(
                    description=(
                        f"{tool_name} parameter '{param_name}' is within bounds"
                    ),
                    check_type=CheckType.RANGE,
                    check_params={"field": f"$.{param_name}", **range_bounds},
                    bindings=bindings_range,
                    meta_template="schema",
                )
            )

        # REGEX (pattern)
        if "pattern" in param_schema and isinstance(param_schema["pattern"], str):
            bindings_regex = (
                _binding(
                    tool_name,
                    f"$.{param_name}",
                    f"parameter {param_name} matches pattern",
                    next_binding_id(),
                    source_selector=f"{tool_name}:last",
                ),
            )
            predicates.append(
                _make_predicate(
                    description=(
                        f"{tool_name} parameter '{param_name}' matches pattern"
                    ),
                    check_type=CheckType.REGEX,
                    check_params={
                        "field": f"$.{param_name}",
                        "pattern": param_schema["pattern"],
                    },
                    bindings=bindings_regex,
                    meta_template="schema",
                )
            )

    return predicates


def _extract_response_predicates(
    tool_name: str, response: dict[str, Any], next_binding_id: Any
) -> list[SuccessPredicate]:
    """Derive TOOL_RESPONSE predicates from success response schema."""
    predicates: list[SuccessPredicate] = []
    if not isinstance(response, dict):
        return predicates

    properties: dict[str, Any] = response.get("properties", {})
    if not isinstance(properties, dict):
        return predicates

    # If response has a status_code field, derive success check
    if "status_code" in properties:
        status_schema = properties["status_code"]
        success_range: dict[str, Any] = {"tool_name": tool_name}
        if isinstance(status_schema, dict) and "enum" in status_schema:
            success_codes = [
                c for c in status_schema["enum"] if isinstance(c, int) and 200 <= c < 300
            ]
            if success_range.get("condition") is None:
                success_range["condition"] = {"$.status_code": success_codes[0]}
        else:
            success_range["condition"] = {"$.status_code": {"$gte": 200, "$lt": 300}}

        bindings = (
            _binding(
                tool_name,
                "$.status_code",
                f"{tool_name} returns a 2xx success status",
                next_binding_id(),
            ),
        )
        predicates.append(
            _make_predicate(
                description=f"{tool_name} returns a 2xx success status",
                check_type=CheckType.TOOL_RESPONSE,
                check_params=success_range,
                bindings=bindings,
                meta_template="evidence_anchor",
            )
        )

    # Recursively find ID/confirmation fields (evidence anchors), including nested
    _collect_id_field_predicates(tool_name, properties, "$", next_binding_id, predicates)

    return predicates


def _collect_id_field_predicates(
    tool_name: str,
    properties: dict[str, Any],
    path_prefix: str,
    next_binding_id: Any,
    predicates: list[SuccessPredicate],
) -> None:
    """Recursively walk response properties for ID/confirmation fields."""
    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            continue
        field_path = f"{path_prefix}.{field_name}" if path_prefix != "$" else f"$.{field_name}"

        if field_name in ("id", "message_id", "confirmation_id", "receipt_id") or (
            isinstance(field_name, str) and field_name.endswith("_id")
        ):
            bindings = (
                _binding(
                    tool_name,
                    field_path,
                    f"{tool_name} response contains {field_name}",
                    next_binding_id(),
                ),
            )
            predicates.append(
                _make_predicate(
                    description=(
                        f"{tool_name} response contains '{field_name}' confirmation"
                    ),
                    check_type=CheckType.FIELD_PRESENCE,
                    check_params={"field": field_path},
                    bindings=bindings,
                    meta_template="evidence_anchor",
                )
            )

        # Recurse into nested object properties
        nested_props = field_schema.get("properties")
        if isinstance(nested_props, dict):
            _collect_id_field_predicates(
                tool_name, nested_props, field_path, next_binding_id, predicates
            )


def _extract_failure_paths(
    tool_name: str,
    errors: list[dict[str, Any]],
    side_effect: str | None,
    next_fp_id: Any,
) -> list[FailurePath]:
    """Derive FailurePaths from documented errors and side-effect guarantees."""
    paths: list[FailurePath] = []

    for error in errors:
        if not isinstance(error, dict):
            continue
        status = error.get("status")
        description = error.get("description", "error response")
        if isinstance(status, int):
            if 400 <= status < 500:
                action = "abort"
            elif 500 <= status < 600:
                action = "retry"
            else:
                action = "escalate"
            paths.append(
                FailurePath(
                    failure_path_id=next_fp_id(),
                    trigger=f"{tool_name} response status {status}: {description}",
                    action=action,
                    max_retries=2 if action == "retry" else 0,
                )
            )

    if side_effect == "NON_IDEMPOTENT_NON_QUERYABLE":
        paths.append(
            FailurePath(
                failure_path_id=next_fp_id(),
                trigger=f"{tool_name} is non-idempotent and non-queryable",
                action="escalate",
                escalation_target="human",
            )
        )

    return paths


def extract_structural_predicates(
    tool_schemas: list[dict[str, Any]],
) -> tuple[list[SuccessPredicate], list[FailurePath]]:
    """Extract structural predicates and failure paths from tool schemas.

    Pure function. Same input → byte-identical output (spec M-8).
    """
    predicates: list[SuccessPredicate] = []
    failure_paths: list[FailurePath] = []
    next_binding_id = _binding_counter()
    fp_counter = 0

    def next_fp_id() -> str:
        nonlocal fp_counter
        fp_counter += 1
        return f"fp:{fp_counter}"

    for schema in tool_schemas:
        if not isinstance(schema, dict):
            continue
        tool_name = schema.get("tool_name")
        if not tool_name or not isinstance(tool_name, str):
            continue

        parameters = schema.get("parameters", {})
        response = schema.get("response", {})
        errors = schema.get("errors", [])
        side_effect = schema.get("side_effect")

        if isinstance(parameters, dict):
            predicates.extend(
                _extract_parameter_predicates(tool_name, parameters, next_binding_id)
            )
        if isinstance(response, dict):
            predicates.extend(
                _extract_response_predicates(tool_name, response, next_binding_id)
            )
        if isinstance(errors, list):
            failure_paths.extend(
                _extract_failure_paths(tool_name, errors, side_effect, next_fp_id)
            )
        elif side_effect == "NON_IDEMPOTENT_NON_QUERYABLE":
            failure_paths.extend(
                _extract_failure_paths(tool_name, [], side_effect, next_fp_id)
            )

    return predicates, failure_paths
