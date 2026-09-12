"""Frozen manifest load/verify — fail-closed on any digest mismatch.

The manifest is the freeze boundary: task inputs, acceptance commands and
expected outcomes are SHA-256 bound before any run. A tampered manifest must
refuse to load rather than silently run different tasks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from .models import EvalManifest


class ManifestIntegrityError(Exception):
    """Raised when a frozen manifest's digest does not match its contents."""


def canonical_manifest_payload(manifest: EvalManifest) -> str:
    data = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def manifest_digest(manifest: EvalManifest) -> str:
    return hashlib.sha256(canonical_manifest_payload(manifest).encode("utf-8")).hexdigest()


def freeze_manifest(manifest: EvalManifest) -> EvalManifest:
    """Return a copy with `manifest_sha256` bound to the current contents."""
    return manifest.model_copy(update={"manifest_sha256": manifest_digest(manifest)})


def verify_manifest(manifest: EvalManifest) -> EvalManifest:
    """Fail closed unless the manifest is frozen and its digest matches."""
    if manifest.manifest_sha256 is None:
        raise ManifestIntegrityError("manifest is not frozen (missing manifest_sha256)")
    actual = manifest_digest(manifest)
    if actual != manifest.manifest_sha256:
        raise ManifestIntegrityError(
            f"manifest digest mismatch: declared {manifest.manifest_sha256}, computed {actual}"
        )
    return manifest


def load_manifest(path: str | Path) -> EvalManifest:
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestIntegrityError(f"manifest unreadable or malformed: {exc}") from exc
    try:
        manifest = EvalManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestIntegrityError(f"manifest schema invalid: {exc}") from exc
    return verify_manifest(manifest)
