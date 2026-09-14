"""Deterministic predicate checkers (spec §11.2).

Each checker evaluates a SuccessPredicate against evidence accessed through
EvidenceAccessor. Returns:
    (passed, evidence_refs, detail)
    passed: True | False | None  (None = UNRESOLVED, evidence missing)
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_os_contracts import CheckType, SuccessPredicate

from .evidence_accessor import EvidenceAccessor

# JSON types accepted by TYPE check
_JSON_TYPE_NAMES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class PredicateCheckError(Exception):
    """Checker received malformed check_params."""


def _extract_path(value: Any, path: str) -> Any:
    """Minimal JSONPath ($.a.b.c or $.a[0]) extraction."""
    if not path.startswith("$."):
        return value
    current = value
    for part in path[2:].split("."):
        # handle array index like items[0]
        key = part
        index: int | None = None
        m = re.match(r"^([^\[]+)\[(\d+)\]$", part)
        if m:
            key = m.group(1)
            index = int(m.group(2))
        if isinstance(current, dict):
            if key not in current:
                return None
            current = current[key]
        else:
            return None
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def _resolve_value(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[Any, tuple[str, ...]]:
    """Resolve the value under test from the first evidence binding.

    Returns (value, evidence_refs_used). value=None means evidence missing.
    """
    if not predicate.evidence_bindings:
        return None, ()
    binding = predicate.evidence_bindings[0]
    refs: list[str] = []

    if binding.source_type.value == "TOOL_RESPONSE":
        selector = binding.source_selector
        tool_name = selector.split(":")[0] if ":" in selector else selector
        result = accessor.tool_result(tool_name)
        if result is None:
            return None, ()
        refs.append(f"tool:{tool_name}")
        value = result
        if binding.extract_path:
            value = _extract_path(result, binding.extract_path)
        return value, tuple(refs)

    if binding.source_type.value == "ARTIFACT":
        artifact_id = binding.source_selector
        content = accessor.artifact_json(artifact_id)
        if content is None:
            raw = accessor.artifact_content(artifact_id)
            if raw is None:
                return None, ()
            try:
                content = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None, ()
        refs.append(artifact_id)
        value = content
        if binding.extract_path:
            value = _extract_path(content, binding.extract_path)
        return value, tuple(refs)

    if binding.source_type.value == "ENVIRONMENT_QUERY":
        snapshot = accessor.state_snapshot(binding.source_selector)
        if snapshot is None:
            return None, ()
        refs.append(f"env:{binding.source_selector}")
        value = snapshot
        if binding.extract_path:
            value = _extract_path(snapshot, binding.extract_path)
        return value, tuple(refs)

    return None, ()


def _check_type(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    expected = predicate.check_params.get("expected_type")
    if expected not in _JSON_TYPE_NAMES:
        raise PredicateCheckError(f"invalid expected_type: {expected!r}")
    value, refs = _resolve_value(predicate, accessor)
    if value is None and refs == ():
        return None, refs, "evidence missing"
    if value is None:
        return False, refs, f"value is null, expected {expected}"
    py_type = _JSON_TYPE_NAMES[expected]
    # bool is subclass of int in Python; exclude bool for "integer"
    if expected == "integer" and isinstance(value, bool):
        return False, refs, "value is boolean, expected integer"
    if expected == "number" and isinstance(value, bool):
        return False, refs, "value is boolean, expected number"
    passed = isinstance(value, py_type)
    return passed, refs, f"value type: {type(value).__name__}"


def _check_range(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    value, refs = _resolve_value(predicate, accessor)
    if value is None and refs == ():
        return None, refs, "evidence missing"
    if value is None:
        return False, refs, "value is null"
    mn = predicate.check_params.get("min")
    mx = predicate.check_params.get("max")
    # For strings, min/max constrain length (from minLength/maxLength in schema)
    if isinstance(value, str):
        length = len(value)
        if mn is not None and length < mn:
            return False, refs, f"string length {length} < min {mn}"
        if mx is not None and length > mx:
            return False, refs, f"string length {length} > max {mx}"
        return True, refs, f"string length {length} in bounds"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False, refs, f"value is not numeric: {type(value).__name__}"
    if mn is not None and value < mn:
        return False, refs, f"value {value} < min {mn}"
    if mx is not None and value > mx:
        return False, refs, f"value {value} > max {mx}"
    return True, refs, f"value {value} in bounds"


def _check_enum(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    allowed = predicate.check_params.get("allowed_values")
    if not isinstance(allowed, list):
        raise PredicateCheckError("enum requires allowed_values list")
    value, refs = _resolve_value(predicate, accessor)
    if value is None and refs == ():
        return None, refs, "evidence missing"
    return value in allowed, refs, f"value {value!r} in {allowed}"


def _check_regex(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    pattern = predicate.check_params.get("pattern")
    if not isinstance(pattern, str):
        raise PredicateCheckError("regex requires pattern string")
    value, refs = _resolve_value(predicate, accessor)
    if value is None and refs == ():
        return None, refs, "evidence missing"
    if not isinstance(value, str):
        return False, refs, f"value is not a string: {type(value).__name__}"
    passed = re.search(pattern, value) is not None
    return passed, refs, f"value {value!r} matches /{pattern}/"


def _check_cardinality(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    target = predicate.check_params.get("target")
    if not isinstance(target, str):
        raise PredicateCheckError("cardinality requires target path")
    # Resolve the parent object/array, then count items at target
    binding = predicate.evidence_bindings[0]
    if binding.source_type.value == "ARTIFACT":
        content = accessor.artifact_json(binding.source_selector)
        if content is None:
            return None, (), "evidence missing"
        items = _extract_path(content, target)
        refs = (binding.source_selector,)
    elif binding.source_type.value == "TOOL_RESPONSE":
        tool_name = binding.source_selector.split(":")[0]
        result = accessor.tool_result(tool_name)
        if result is None:
            return None, (), "evidence missing"
        items = _extract_path(result, target)
        refs = (f"tool:{tool_name}",)
    else:
        return None, (), "unsupported source for cardinality"
    if items is None:
        return False, refs, f"target {target} not found"
    if not isinstance(items, (list, tuple, dict)):
        return False, refs, f"target is not countable: {type(items).__name__}"
    count = len(items)
    mn = predicate.check_params.get("min_count")
    mx = predicate.check_params.get("max_count")
    if mn is not None and count < mn:
        return False, refs, f"count {count} < min {mn}"
    if mx is not None and count > mx:
        return False, refs, f"count {count} > max {mx}"
    return True, refs, f"count {count} in bounds"


def _check_field_presence(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    value, refs = _resolve_value(predicate, accessor)
    if value is None and refs == ():
        return None, refs, "evidence missing"
    passed = value is not None
    return passed, refs, f"field present: {passed}"


def _check_artifact_exists(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    path = predicate.check_params.get("path")
    if not isinstance(path, str):
        raise PredicateCheckError("artifact_exists requires path")
    content = accessor.artifact_content(path)
    if content is None:
        return False, (path,), f"artifact {path} not found"
    return True, (path,), f"artifact {path} exists ({len(content)} bytes)"


def _check_artifact_content(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    path = predicate.check_params.get("path")
    if not isinstance(path, str):
        raise PredicateCheckError("artifact_content requires path")
    content = accessor.artifact_json(path)
    if content is None:
        raw = accessor.artifact_content(path)
        if raw is None:
            return None, (path,), "evidence missing"
        try:
            content = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, (path,), "artifact is not valid JSON"
    assertions = predicate.check_params.get("content_assertions", [])
    if not isinstance(assertions, list):
        raise PredicateCheckError("content_assertions must be a list")
    refs = (path,)
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        kind = assertion.get("kind", "").upper()
        field = assertion.get("field", "$")
        value = _extract_path(content, field) if field != "$" else content
        if kind == "CARDINALITY":
            if not isinstance(value, (list, tuple, dict)):
                return False, refs, f"{field}: not countable"
            count = len(value)
            mn = assertion.get("min_count")
            mx = assertion.get("max_count")
            if mn is not None and count < mn:
                return False, refs, f"{field}: count {count} < {mn}"
            if mx is not None and count > mx:
                return False, refs, f"{field}: count {count} > {mx}"
        elif kind == "TYPE":
            expected = assertion.get("expected_type")
            if not isinstance(expected, str):
                return False, refs, f"{field}: missing expected_type"
            py_type = _JSON_TYPE_NAMES.get(expected)
            if py_type is None:
                return False, refs, f"{field}: unknown type {expected}"
            if not isinstance(value, py_type):
                return False, refs, f"{field}: expected {expected}, got {type(value).__name__}"
        elif kind == "FIELD_PRESENCE":
            if value is None:
                return False, refs, f"{field}: missing"
    return True, refs, "all content assertions passed"


def _check_tool_response(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    tool_name = predicate.check_params.get("tool_name")
    condition = predicate.check_params.get("condition", {})
    if not isinstance(tool_name, str) or not isinstance(condition, dict):
        raise PredicateCheckError("tool_response requires tool_name and condition")
    result = accessor.tool_result(tool_name)
    if result is None:
        return None, (f"tool:{tool_name}",), "evidence missing"
    refs = (f"tool:{tool_name}",)
    for field_path, expected in condition.items():
        actual = _extract_path(result, field_path)
        if isinstance(expected, dict):
            # Operator dict: {$gte: val, $lt: val, $exists: bool, ...}
            for op, val in expected.items():
                if op == "$gte":
                    if not (isinstance(actual, (int, float)) and actual >= val):
                        return False, refs, f"{field_path}: {actual} < {val}"
                elif op == "$gt":
                    if not (isinstance(actual, (int, float)) and actual > val):
                        return False, refs, f"{field_path}: {actual} <= {val}"
                elif op == "$lte":
                    if not (isinstance(actual, (int, float)) and actual <= val):
                        return False, refs, f"{field_path}: {actual} > {val}"
                elif op == "$lt":
                    if not (isinstance(actual, (int, float)) and actual < val):
                        return False, refs, f"{field_path}: {actual} >= {val}"
                elif op == "$eq":
                    if actual != val:
                        return False, refs, f"{field_path}: {actual} != {val}"
                elif op == "$ne":
                    if actual == val:
                        return False, refs, f"{field_path}: {actual} == {val}"
                elif op == "$exists":
                    if val is True and actual is None:
                        return False, refs, f"{field_path}: does not exist"
                    if val is False and actual is not None:
                        return False, refs, f"{field_path}: exists but should not"
                else:
                    return False, refs, f"{field_path}: unknown operator {op}"
        elif actual != expected:
            return False, refs, f"{field_path}: expected {expected!r}, got {actual!r}"
    return True, refs, "tool response condition met"


def _check_state_delta(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    # MVP: no baseline snapshot infrastructure → UNRESOLVED (spec §16 open q2)
    return None, (), "state delta baseline not available in MVP"


def _check_cross_consistency(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    refs_paths = predicate.check_params.get("refs", [])
    relation = predicate.check_params.get("relation")
    if not isinstance(refs_paths, list) or not isinstance(relation, str):
        raise PredicateCheckError("cross_consistency requires refs and relation")
    values: list[Any] = []
    refs: list[str] = []
    specs: list[str] = []
    for ref in refs_paths:
        if not isinstance(ref, str):
            continue
        # ref format: "artifact:<id>:$.path" or "tool:<name>:$.path"
        parts = ref.split(":", 2)
        if len(parts) < 3:
            continue
        source_type, source_id, path = parts
        if not path.startswith("$."):
            # A non-JSONPath path aliases to the whole document, which would
            # make 'equal' self-comparisons vacuous; treat as malformed.
            continue
        if source_type == "artifact":
            content = accessor.artifact_json(source_id)
            if content is None:
                return None, tuple(refs), f"evidence missing: {source_id}"
            value = _extract_path(content, path)
            refs.append(source_id)
        elif source_type == "tool":
            result = accessor.tool_result(source_id)
            if result is None:
                return None, tuple(refs), f"evidence missing: tool {source_id}"
            value = _extract_path(result, path)
            refs.append(f"tool:{source_id}")
        else:
            continue
        if value is None:
            # A missing path is unresolved evidence, not a value to compare.
            return None, tuple(refs), f"path not resolved: {ref}"
        values.append(value)
        specs.append(ref)
    # Cross-consistency compares at least two DISTINCT resolved refs. Fewer or
    # duplicate refs would compare a value with itself (vacuously true) and let
    # a "blocking" predicate never fail; require >= 2 distinct specs.
    if len(values) < 2 or len(set(specs)) < 2:
        return None, tuple(refs), (
            "cross_consistency requires at least two distinct resolved refs"
        )
    if relation == "equal":
        passed = all(v == values[0] for v in values)
        return passed, tuple(refs), f"values: {values}"
    if relation == "subset":
        if isinstance(values[0], set) and isinstance(values[1], set):
            return values[0].issubset(values[1]), tuple(refs), "subset check"
    if relation == "superset":
        if isinstance(values[0], set) and isinstance(values[1], set):
            return values[0].issuperset(values[1]), tuple(refs), "superset check"
    return None, tuple(refs), f"relation {relation} not fully supported in MVP"


def _check_llm_judge(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    # Advisory only — never blocks. Returns None (recorded as advisory, no verdict impact).
    return None, (), "LLM_JUDGE is advisory only"


CHECKER_REGISTRY: dict[CheckType, Any] = {
    CheckType.TYPE: _check_type,
    CheckType.RANGE: _check_range,
    CheckType.ENUM: _check_enum,
    CheckType.REGEX: _check_regex,
    CheckType.CARDINALITY: _check_cardinality,
    CheckType.FIELD_PRESENCE: _check_field_presence,
    CheckType.STATE_DELTA: _check_state_delta,
    CheckType.TOOL_RESPONSE: _check_tool_response,
    CheckType.ARTIFACT_EXISTS: _check_artifact_exists,
    CheckType.ARTIFACT_CONTENT: _check_artifact_content,
    CheckType.CROSS_CONSISTENCY: _check_cross_consistency,
    CheckType.LLM_JUDGE: _check_llm_judge,
}


def run_checker(
    predicate: SuccessPredicate, accessor: EvidenceAccessor
) -> tuple[bool | None, tuple[str, ...], str]:
    """Execute the checker for a predicate's check_type."""
    checker = CHECKER_REGISTRY.get(predicate.check_type)
    if checker is None:
        return None, (), f"unsupported check_type: {predicate.check_type}"
    return checker(predicate, accessor)
