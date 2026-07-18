"""Strict canonical JSON for public ABA qualification commitments only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


class CanonicalizationError(ValueError):
    """Raised without echoing a rejected value into logs or transcripts."""


def _normalize(value: object) -> object:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("UNSUPPORTED_CANONICAL_TYPE")
        return {key: _normalize(value[key]) for key in sorted(value)}
    raise CanonicalizationError("UNSUPPORTED_CANONICAL_TYPE")


def canonical_json_bytes(value: object) -> bytes:
    """Serialize the closed JSON subset used by public commitments."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: object) -> str:
    """Return one lowercase, bare SHA-256 form for canonical public data."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = ["CanonicalizationError", "canonical_json_bytes", "sha256_hex"]
