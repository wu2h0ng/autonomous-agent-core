"""Distribution scaffolding: install / upgrade / verification helpers.

This subpackage is SCAFFOLDING. It does not publish, release, or run the
self-update path. See docs/distribution/.
"""

from .signature_verify import (
    ArtifactVerifier,
    Ed25519Verifier,
    SignatureVerificationError,
    ed25519_public_bytes,
    ed25519_public_key_fingerprint,
    ed25519_public_key_from_hex,
    ed25519_sign,
    ed25519_signature_from_hex,
)

__all__ = [
    "ArtifactVerifier",
    "Ed25519Verifier",
    "SignatureVerificationError",
    "ed25519_public_bytes",
    "ed25519_public_key_fingerprint",
    "ed25519_public_key_from_hex",
    "ed25519_sign",
    "ed25519_signature_from_hex",
]
