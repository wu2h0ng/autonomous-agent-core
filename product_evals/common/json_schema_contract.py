"""Strict, fail-closed consumer for the pinned runner TeamEvent JSON-Schema.

The pinned workflow runner exports a small Draft-07 subset for its
``team.event`` contract.  This module consumes exactly that subset with the
Python standard library only; it is not a general JSON-Schema engine.  Any
schema keyword outside the pinned subset is rejected before a record is
validated, so an unreviewed schema extension can never widen acceptance
silently.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Callable, Mapping

from product_evals.common.bank_generator import canonical_json_bytes

# Only the keywords the pinned runner actually emits are honoured.  Every other
# keyword is treated as an unreviewed schema extension and rejected fail-closed.
_SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "title",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "const",
        "enum",
        "minLength",
        "pattern",
        "items",
    }
)

_JSON_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "null": lambda value: value is None,
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
}


def canonical_schema_sha256(schema: Mapping[str, Any]) -> str:
    """Digest a schema independent of key order and sensitive to any mutation."""

    return hashlib.sha256(canonical_json_bytes(schema)).hexdigest()


def validate_closed_record(
    record: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    """Validate ``record`` against the pinned schema subset, failing closed.

    Raises ``ValueError`` when the schema uses an unsupported keyword or when the
    record violates any pinned constraint.
    """

    _assert_supported_schema(schema, "$")
    _validate_value(record, schema, "$")


def normalize_timestamped_record(
    record: Mapping[str, Any],
    schema: Mapping[str, Any],
    timestamp_field: str = "ts",
) -> dict[str, Any]:
    """Validate ``record`` then drop only ``timestamp_field``.

    All authority-lineage bindings (source ids and evidence refs) are retained.
    The input record is not mutated.
    """

    validate_closed_record(record, schema)
    return {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key != timestamp_field
    }


def _assert_supported_schema(node: Any, path: str) -> None:
    if not isinstance(node, Mapping):
        raise ValueError(f"schema node at {path} is not an object")
    for keyword in node:
        if keyword not in _SUPPORTED_KEYWORDS:
            raise ValueError(f"unsupported schema keyword {keyword!r} at {path}")
    properties = node.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise ValueError(f"'properties' at {path} is not an object")
        for name, subschema in properties.items():
            _assert_supported_schema(subschema, f"{path}.properties.{name}")
    items = node.get("items")
    if items is not None:
        _assert_supported_schema(items, f"{path}.items")


def _validate_value(value: Any, schema: Mapping[str, Any], path: str) -> None:
    if "type" in schema:
        _validate_type(value, schema["type"], path)
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of the permitted values")
    if "minLength" in schema and isinstance(value, str):
        if len(value) < schema["minLength"]:
            raise ValueError(f"{path} is shorter than minLength")
    if "pattern" in schema and isinstance(value, str):
        if re.search(schema["pattern"], value) is None:
            raise ValueError(f"{path} does not match required pattern")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, dict):
        _validate_object(value, schema, path)


def _validate_type(value: Any, declared: Any, path: str) -> None:
    names = declared if isinstance(declared, list) else [declared]
    for name in names:
        check = _JSON_TYPE_CHECKS.get(name)
        if check is None:
            raise ValueError(f"unsupported type {name!r} at {path}")
        if check(value):
            return
    raise ValueError(f"{path} does not match type {declared!r}")


def _validate_object(
    value: dict[str, Any], schema: Mapping[str, Any], path: str
) -> None:
    properties = schema.get("properties", {})
    for required in schema.get("required", []):
        if required not in value:
            raise ValueError(f"{path} is missing required field {required!r}")
    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        subschema = properties.get(key)
        if subschema is None:
            if additional is False:
                raise ValueError(f"{path} has unexpected field {key!r}")
            continue
        _validate_value(item, subschema, f"{path}.{key}")
