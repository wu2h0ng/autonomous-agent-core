"""Deterministically generate a SPINE provider bank from a model-free template."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Mapping

from product_evals.common.provider_bank import request_body_digest
from product_evals.common.spine_identity import SpineEvaluationIdentity


_STALE_IDENTITY = re.compile(r"spine[-_]e2e[-_]\d+", re.IGNORECASE)


def canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def _reject_stale_identity(value: object) -> None:
    if isinstance(value, str) and _STALE_IDENTITY.search(value):
        raise ValueError("template contains stale successor identity")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_stale_identity(str(key))
            _reject_stale_identity(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_stale_identity(item)


def build_provider_bank(
    identity: SpineEvaluationIdentity, template: Mapping[str, object]
) -> dict[str, object]:
    if not isinstance(identity, SpineEvaluationIdentity):
        raise ValueError("invalid evaluation identity")
    if not isinstance(template, Mapping) or set(template) != {"entries"}:
        raise ValueError("invalid provider bank template")
    _reject_stale_identity(template)
    sources = template["entries"]
    if not isinstance(sources, list) or len(sources) != 12:
        raise ValueError("invalid provider bank template entries")
    generated: list[dict[str, object]] = []
    case_ids: set[str] = set()
    digests: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != {
            "case_id",
            "request",
            "expected_calls",
            "response",
        }:
            raise ValueError("invalid provider bank template entry")
        case_id = source["case_id"]
        request_source = source["request"]
        response_source = source["response"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in case_ids
            or not isinstance(request_source, Mapping)
            or "model" in request_source
            or "digest" in request_source
            or not isinstance(response_source, Mapping)
            or "model" in response_source
            or "digest" in response_source
            or type(source["expected_calls"]) is not int
            or source["expected_calls"] != 2
        ):
            raise ValueError("invalid provider bank template entry")
        request = {"model": identity.provider_model, **deepcopy(dict(request_source))}
        response = {**deepcopy(dict(response_source)), "model": identity.provider_model}
        digest = request_body_digest(request)
        if digest in digests:
            raise ValueError("duplicate generated request digest")
        case_ids.add(case_id)
        digests.add(digest)
        generated.append(
            {
                "case_id": case_id,
                "request": request,
                "digest": digest,
                "expected_calls": 2,
                "response": response,
            }
        )
    return {"entries": generated}


def write_provider_bank(
    path: Path,
    identity: SpineEvaluationIdentity,
    template: Mapping[str, object],
) -> bytes:
    data = canonical_json_bytes(build_provider_bank(identity, template))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data
