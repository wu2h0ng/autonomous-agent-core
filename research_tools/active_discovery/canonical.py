from __future__ import annotations

import hashlib
import json
from typing import Any


DOMAIN_PREFIX = "active-discovery/v1"


def canonical_json(value: Any) -> str:
    """Return the one UTF-8 JSON representation used by harness digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(domain: str, value: Any) -> str:
    """Hash canonical content under an explicit record-type domain."""

    if not domain or "\x00" in domain:
        raise ValueError("digest domain must be a non-empty NUL-free string")
    preimage = f"{DOMAIN_PREFIX}:{domain}\x00{canonical_json(value)}".encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()
