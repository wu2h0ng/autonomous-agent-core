from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Mapping

from ..canonical import content_digest


FAMILY_MANIFEST_SCHEMA = "active-discovery-family-manifest/v1"
_MODE = "NOT_EVIDENCE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestValidationError(ValueError):
    """A referee-owned development-family manifest is not closed."""


class FamilyCode(str, Enum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    F4 = "F4"


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ManifestValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class FamilyManifest:
    schema_version: str
    mode: str
    family_code: FamilyCode
    seed: int
    probe_budget_units: int
    descriptor_digest: str
    catalogue_digest: str
    hidden_configuration_digest: str

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "mode",
            "family_code",
            "seed",
            "probe_budget_units",
            "descriptor_digest",
            "catalogue_digest",
            "hidden_configuration_digest",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != FAMILY_MANIFEST_SCHEMA or self.mode != _MODE:
            raise ManifestValidationError(
                "family manifest must use the closed NOT_EVIDENCE schema and mode"
            )
        if not isinstance(self.family_code, FamilyCode):
            raise ManifestValidationError("family_code must be one of F1-F4")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ManifestValidationError("seed must be an integer")
        if (
            isinstance(self.probe_budget_units, bool)
            or not isinstance(self.probe_budget_units, int)
            or self.probe_budget_units < 1
        ):
            raise ManifestValidationError("probe_budget_units must be an integer >= 1")
        _digest(self.descriptor_digest, "descriptor_digest")
        _digest(self.catalogue_digest, "catalogue_digest")
        _digest(self.hidden_configuration_digest, "hidden_configuration_digest")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FamilyManifest:
        unknown = set(raw) - cls.FIELDS
        missing = cls.FIELDS - set(raw)
        if unknown:
            raise ManifestValidationError(f"unknown fields: {sorted(unknown)}")
        if missing:
            raise ManifestValidationError(f"missing fields: {sorted(missing)}")
        try:
            family_code = FamilyCode(raw["family_code"])
        except (TypeError, ValueError) as exc:
            raise ManifestValidationError("family_code must be one of F1-F4") from exc
        return cls(
            schema_version=raw["schema_version"],
            mode=raw["mode"],
            family_code=family_code,
            seed=raw["seed"],
            probe_budget_units=raw["probe_budget_units"],
            descriptor_digest=_digest(raw["descriptor_digest"], "descriptor_digest"),
            catalogue_digest=_digest(raw["catalogue_digest"], "catalogue_digest"),
            hidden_configuration_digest=_digest(
                raw["hidden_configuration_digest"], "hidden_configuration_digest"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "family_code": self.family_code.value,
            "seed": self.seed,
            "probe_budget_units": self.probe_budget_units,
            "descriptor_digest": self.descriptor_digest,
            "catalogue_digest": self.catalogue_digest,
            "hidden_configuration_digest": self.hidden_configuration_digest,
        }

    @property
    def manifest_digest(self) -> str:
        return content_digest("development-family-manifest", self.to_mapping())
