"""Minimal self-contained contract primitives for the W1/W2 falsifier."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Mapping, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, TypeAdapter


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


NonEmptyStr: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
UtcDateTime: TypeAlias = Annotated[datetime, AfterValidator(_require_aware_utc)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"


_JSON_ADAPTER = TypeAdapter(Any)


def canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude_none=True)
    else:
        payload = _JSON_ADAPTER.dump_python(value, mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(value: BaseModel | Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class CandidateObservation(ContractModel):
    """Arm-visible observation with no regime, schedule or turn oracle."""

    observation_id: NonEmptyStr


class CandidateFeedback(ContractModel):
    """Delayed outcome visible to candidate adaptation organs."""

    action: NonEmptyStr
    reward: float
    source_event_digest: NonEmptyStr
