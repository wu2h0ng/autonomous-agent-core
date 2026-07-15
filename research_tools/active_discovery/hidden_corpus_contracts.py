from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Mapping

from .canonical import content_digest


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_TERMS = ("tbd", "todo", "unknown", "fake", "test")


class CustodyBlockedError(RuntimeError):
    """A role-bearing hidden action was attempted before real identity binding."""


class CustodyAction(str, Enum):
    HIDDEN_GENERATION = "HIDDEN_GENERATION"
    COMMITMENT = "COMMITMENT"
    PROVIDER_CALL = "PROVIDER_CALL"
    MODEL_CALL = "MODEL_CALL"
    HUMAN_CALL = "HUMAN_CALL"
    PILOT = "PILOT"
    FREEZE = "FREEZE"
    SCIENTIFIC_RUN = "SCIENTIFIC_RUN"


@dataclass(frozen=True, slots=True)
class CustodyBindingManifest:
    binding_status: str
    q_score_custodian_id: str | None
    p_power_custodian_id: str | None
    e_score_custodian_id: str | None
    runner_operator_id: str | None
    c7_authority_id: str | None
    independent_adjudicator_id: str | None
    human_protocol_operator_id: str | None

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "binding_status",
            "q_score_custodian_id",
            "p_power_custodian_id",
            "e_score_custodian_id",
            "runner_operator_id",
            "c7_authority_id",
            "independent_adjudicator_id",
            "human_protocol_operator_id",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.binding_status, str) or not self.binding_status:
            raise CustodyBlockedError("BLOCKED_UNBOUND: binding_status is missing")
        for field_name in self.FIELDS - {"binding_status"}:
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise CustodyBlockedError(
                    f"BLOCKED_UNBOUND: {field_name} is not a real non-empty identity"
                )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> CustodyBindingManifest:
        unknown = set(raw) - cls.FIELDS
        missing = cls.FIELDS - set(raw)
        if unknown or missing:
            raise CustodyBlockedError("BLOCKED_UNBOUND: custody binding fields drifted")
        return cls(**{field_name: raw[field_name] for field_name in cls.FIELDS})

    def to_mapping(self) -> dict[str, object]:
        return {
            "binding_status": self.binding_status,
            "q_score_custodian_id": self.q_score_custodian_id,
            "p_power_custodian_id": self.p_power_custodian_id,
            "e_score_custodian_id": self.e_score_custodian_id,
            "runner_operator_id": self.runner_operator_id,
            "c7_authority_id": self.c7_authority_id,
            "independent_adjudicator_id": self.independent_adjudicator_id,
            "human_protocol_operator_id": self.human_protocol_operator_id,
        }


@dataclass(frozen=True, slots=True)
class BindingValidationReceipt:
    action: CustodyAction
    disposition: str
    validation_digest: str


def _real_identity(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise CustodyBlockedError(f"BLOCKED_UNBOUND: {field} is null")
    lowered = value.lower()
    if any(term in lowered for term in _PLACEHOLDER_TERMS):
        raise CustodyBlockedError(
            f"BLOCKED_UNBOUND: {field} is a placeholder or test fake"
        )
    return value


def assert_action_ready(
    *,
    manifest: CustodyBindingManifest,
    action: CustodyAction,
    independent_review_receipt: str | None,
    scorer_implementer_id: str,
    actor_principal_ids: tuple[str, ...],
) -> BindingValidationReceipt:
    """Validate future bindings without creating execution or freeze authority."""

    if not isinstance(action, CustodyAction):
        raise CustodyBlockedError("BLOCKED_UNBOUND: action is outside the closed enum")
    if manifest.binding_status == "UNBOUND_DESIGN_ONLY":
        raise CustodyBlockedError("BLOCKED_UNBOUND: design manifest has no principals")
    fields = {
        field_name: _real_identity(getattr(manifest, field_name), field_name)
        for field_name in CustodyBindingManifest.FIELDS - {"binding_status"}
    }
    if (
        independent_review_receipt is None
        or _SHA256_RE.fullmatch(independent_review_receipt) is None
    ):
        raise CustodyBlockedError("BLOCKED_UNBOUND: independent review receipt is absent")
    scorer = _real_identity(scorer_implementer_id, "scorer_implementer_id")
    if not actor_principal_ids:
        raise CustodyBlockedError("BLOCKED_UNBOUND: actor principal set is empty")
    actors = tuple(
        _real_identity(value, "actor_principal_id") for value in actor_principal_ids
    )
    if len(actors) != len(set(actors)):
        raise CustodyBlockedError("BLOCKED_UNBOUND: actor principal identities repeat")

    q_id = fields["q_score_custodian_id"]
    p_id = fields["p_power_custodian_id"]
    e_id = fields["e_score_custodian_id"]
    if len({q_id, p_id, e_id}) != 3:
        raise CustodyBlockedError("BLOCKED_UNBOUND: Q/P/E custodian roles collapse")
    forbidden_e_identities = {
        fields["runner_operator_id"],
        fields["c7_authority_id"],
        fields["independent_adjudicator_id"],
        fields["human_protocol_operator_id"],
        scorer,
        *actors,
    }
    if e_id in forbidden_e_identities:
        raise CustodyBlockedError(
            "BLOCKED_UNBOUND: E-SCORE custodian collapses with a protected role"
        )
    payload = {
        "manifest": manifest.to_mapping(),
        "action": action.value,
        "independent_review_receipt": independent_review_receipt,
        "scorer_implementer_id": scorer,
        "actor_principal_ids": list(actors),
        "disposition": "BINDINGS_VALIDATED_NOT_RUN_AUTHORITY",
    }
    return BindingValidationReceipt(
        action=action,
        disposition="BINDINGS_VALIDATED_NOT_RUN_AUTHORITY",
        validation_digest=content_digest("custody-binding-validation/v1", payload),
    )


def load_custody_design_manifest(path: Path) -> CustodyBindingManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustodyBlockedError("BLOCKED_UNBOUND: design manifest could not be read") from exc
    if not isinstance(raw, dict):
        raise CustodyBlockedError("BLOCKED_UNBOUND: design manifest is not an object")
    manifest = CustodyBindingManifest.from_mapping(raw)
    if manifest.binding_status != "UNBOUND_DESIGN_ONLY" or any(
        getattr(manifest, field_name) is not None
        for field_name in manifest.FIELDS - {"binding_status"}
    ):
        raise CustodyBlockedError(
            "BLOCKED_UNBOUND: tracked design manifest must retain literal nulls"
        )
    return manifest
