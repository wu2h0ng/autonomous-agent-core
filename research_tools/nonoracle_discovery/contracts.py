from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, cast


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_VARIABLE_ID = re.compile(r"^[a-z][0-9]+$")


class DiscoveryContractError(ValueError):
    """The public discovery contract is malformed or oracle-shaped."""


def _closed(raw: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(raw) - fields
    missing = fields - set(raw)
    if unknown:
        raise DiscoveryContractError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise DiscoveryContractError(f"{label} is missing fields: {sorted(missing)}")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DiscoveryContractError(f"{field} must be a non-empty NUL-free string")
    return value


def _row(value: Sequence[object], width: int, field: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or len(value) != width:
        raise DiscoveryContractError(f"{field} row width must equal variable count")
    converted: list[float] = []
    for cell in value:
        if isinstance(cell, bool) or not isinstance(cell, (int, float)):
            raise DiscoveryContractError(f"{field} rows must be numeric")
        number = float(cell)
        if not math.isfinite(number):
            raise DiscoveryContractError(f"{field} rows must be finite")
        converted.append(number)
    return tuple(converted)


def _rows(
    value: Sequence[Sequence[object]], width: int, field: str
) -> tuple[tuple[float, ...], ...]:
    if isinstance(value, (str, bytes)) or len(value) < 4:
        raise DiscoveryContractError(f"{field} requires at least four rows")
    return tuple(_row(row, width, field) for row in value)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_digest(label: str, value: object) -> str:
    return hashlib.sha256(
        label.encode("utf-8") + b"\x00" + canonical_bytes(value)
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class InterventionCondition:
    condition_id: str
    target: str
    rows: tuple[tuple[float, ...], ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "target": self.target,
            "rows": [list(row) for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class InterventionDataset:
    variable_ids: tuple[str, ...]
    control_rows: tuple[tuple[float, ...], ...]
    conditions: tuple[InterventionCondition, ...]

    @classmethod
    def create(
        cls,
        variable_ids: Sequence[str],
        control_rows: Sequence[Sequence[object]],
        intervention_rows: Mapping[str, Sequence[Sequence[object]]],
        intervention_targets: Mapping[str, str],
    ) -> InterventionDataset:
        variables = tuple(_name(value, "variable id") for value in variable_ids)
        if any(_OPAQUE_VARIABLE_ID.fullmatch(value) is None for value in variables):
            raise DiscoveryContractError(
                "variable ids must use opaque lower-letter-plus-digits identifiers"
            )
        if len(variables) < 2 or len(variables) != len(set(variables)):
            raise DiscoveryContractError(
                "variable ids must be at least two unique names"
            )
        if set(intervention_rows) != set(intervention_targets):
            raise DiscoveryContractError(
                "intervention rows and binding identities must match"
            )
        if not intervention_rows:
            raise DiscoveryContractError(
                "at least one intervention binding is required"
            )
        target_values = tuple(intervention_targets.values())
        if len(target_values) != len(set(target_values)):
            raise DiscoveryContractError(
                "intervention binding requires one unique target per condition"
            )
        width = len(variables)
        controls = _rows(control_rows, width, "control")
        conditions: list[InterventionCondition] = []
        for condition_id in sorted(intervention_rows):
            condition = _name(condition_id, "condition id")
            target = _name(intervention_targets[condition_id], "intervention target")
            if target not in variables:
                raise DiscoveryContractError(
                    "intervention target is not a declared variable"
                )
            conditions.append(
                InterventionCondition(
                    condition,
                    target,
                    _rows(
                        intervention_rows[condition_id],
                        width,
                        f"intervention {condition}",
                    ),
                )
            )
        return cls(variables, controls, tuple(conditions))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> InterventionDataset:
        _closed(
            raw,
            frozenset({"schema_version", "variable_ids", "control_rows", "conditions"}),
            "intervention dataset",
        )
        if raw["schema_version"] != "nonoracle-intervention-dataset/v1":
            raise DiscoveryContractError("dataset schema version drift")
        conditions = raw["conditions"]
        if not isinstance(conditions, list):
            raise DiscoveryContractError("conditions must be a list")
        row_map: dict[str, Sequence[Sequence[object]]] = {}
        binding_map: dict[str, str] = {}
        for item in conditions:
            if not isinstance(item, dict):
                raise DiscoveryContractError("condition must be an object")
            _closed(item, frozenset({"condition_id", "target", "rows"}), "condition")
            condition_id = _name(item["condition_id"], "condition id")
            if condition_id in row_map:
                raise DiscoveryContractError(
                    "condition binding identities must be unique"
                )
            rows_value = item["rows"]
            if not isinstance(rows_value, list):
                raise DiscoveryContractError("condition rows must be a list")
            row_map[condition_id] = cast(Sequence[Sequence[object]], rows_value)
            binding_map[condition_id] = _name(item["target"], "intervention target")
        variable_ids_value = raw["variable_ids"]
        control_rows_value = raw["control_rows"]
        if not isinstance(variable_ids_value, list):
            raise DiscoveryContractError("variable ids must be a list")
        if not isinstance(control_rows_value, list):
            raise DiscoveryContractError("control rows must be a list")
        variable_ids = cast(Sequence[str], variable_ids_value)
        control_rows = cast(Sequence[Sequence[object]], control_rows_value)
        return cls.create(variable_ids, control_rows, row_map, binding_map)

    def condition(self, condition_id: str) -> InterventionCondition:
        for condition in self.conditions:
            if condition.condition_id == condition_id:
                return condition
        raise DiscoveryContractError("condition is absent")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "nonoracle-intervention-dataset/v1",
            "variable_ids": list(self.variable_ids),
            "control_rows": [list(row) for row in self.control_rows],
            "conditions": [condition.to_mapping() for condition in self.conditions],
        }

    @property
    def public_view_digest(self) -> str:
        value = self.to_mapping()
        value["control_rows"] = sorted(value["control_rows"])  # type: ignore[arg-type]
        for condition in value["conditions"]:  # type: ignore[union-attr]
            condition["rows"] = sorted(condition["rows"])
        return content_digest("nonoracle-public-view/v1", value)


@dataclass(frozen=True, slots=True)
class DirectedAncestryHypothesis:
    source: str
    target: str
    signed_effect_micros: int
    stability_micros: int
    evidence_digest: str

    def __post_init__(self) -> None:
        _name(self.source, "hypothesis source")
        _name(self.target, "hypothesis target")
        if self.source == self.target:
            raise DiscoveryContractError("self ancestry hypothesis is forbidden")
        for value, field in (
            (self.signed_effect_micros, "signed effect"),
            (self.stability_micros, "stability"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise DiscoveryContractError(f"{field} must be an integer")
        if self.stability_micros < 0:
            raise DiscoveryContractError("stability must be non-negative")
        if (
            not isinstance(self.evidence_digest, str)
            or _DIGEST.fullmatch(self.evidence_digest) is None
        ):
            raise DiscoveryContractError("evidence digest must be lowercase SHA-256")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DirectedAncestryHypothesis:
        fields = frozenset(
            {
                "source",
                "target",
                "signed_effect_micros",
                "stability_micros",
                "evidence_digest",
            }
        )
        _closed(raw, fields, "directed ancestry hypothesis")
        return cls(**raw)

    def to_mapping(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "signed_effect_micros": self.signed_effect_micros,
            "stability_micros": self.stability_micros,
            "evidence_digest": self.evidence_digest,
        }
