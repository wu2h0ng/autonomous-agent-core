"""Optional, default-off Ed25519 detached-signature verification scaffold.

This is a SCAFFOLD, not production-grade signature verification. It proves the
mechanism (generate key -> sign -> verify valid -> verify tampered fails) and
leaves an abstract interface in place. It is NOT wired into the running
self-update path, ships NO trust anchor, and the choice of cosign / minisign /
Ed25519 plus the production signing key is a founder decision. See
docs/distribution/SELF-UPDATE-SIGNATURE.md.

Only the `cryptography` package is required, and it is a TEST-time extra
(`product-test`), never a runtime dependency of the installed tool.
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class SignatureVerificationError(ValueError):
    """A signature / public key / input is malformed for this verifier."""


class ArtifactVerifier(Protocol):
    """Abstract "does this signature cover these bytes under this public key".

    Implementations must be total over (data, signature, public_key): they
    return True only when the signature is valid, and must never raise on a
    merely-invalid signature (they return False); they raise only on malformed
    inputs (wrong key length, unparseable signature) where "True/False" is not
    even meaningful.
    """

    name: str

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        """Return True iff `signature` is a valid signature over `data`."""
        ...


# Ed25519 wire lengths (RFC 8032).
_ED25519_PUBLIC_KEY_LEN = 32
_ED25519_SIGNATURE_LEN = 64


def _require_cryptography():  # type: ignore[no-untyped-def]
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: WPS433
            Ed25519PublicKey,
        )
        from cryptography.exceptions import (  # noqa: WPS433
            InvalidSignature,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - env guard
        raise SignatureVerificationError(
            "the 'cryptography' package is required for Ed25519Verifier "
            "(it is a test-time extra; install with --extra product-test)"
        ) from exc
    return Ed25519PublicKey, InvalidSignature


def ed25519_public_key_from_hex(hex_key: str) -> bytes:
    """Decode a 64-hex-char Ed25519 public key (32 raw bytes)."""
    try:
        raw = bytes.fromhex(hex_key.strip())
    except ValueError as exc:
        raise SignatureVerificationError("public key is not hex") from exc
    if len(raw) != _ED25519_PUBLIC_KEY_LEN:
        raise SignatureVerificationError(
            f"ed25519 public key must be {_ED25519_PUBLIC_KEY_LEN} bytes "
            f"(got {len(raw)})"
        )
    return raw


def ed25519_signature_from_hex(hex_sig: str) -> bytes:
    """Decode a 128-hex-char Ed25519 detached signature (64 raw bytes)."""
    try:
        raw = bytes.fromhex(hex_sig.strip())
    except ValueError as exc:
        raise SignatureVerificationError("signature is not hex") from exc
    if len(raw) != _ED25519_SIGNATURE_LEN:
        raise SignatureVerificationError(
            f"ed25519 signature must be {_ED25519_SIGNATURE_LEN} bytes "
            f"(got {len(raw)})"
        )
    return raw


def ed25519_public_key_fingerprint(public_key: bytes) -> str:
    """Short, human-stable fingerprint for a public key (sha256, first 16 hex).

    Used to log WHICH key verified a payload without logging the key itself in
    full; it is NOT a security primitive, just a stable label.
    """
    return hashlib.sha256(public_key).hexdigest()[:16]


class Ed25519Verifier:
    """Ed25519 detached-signature verifier (scaffold; default off)."""

    name = "ed25519"

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        Ed25519PublicKey, InvalidSignature = _require_cryptography()
        if len(public_key) != _ED25519_PUBLIC_KEY_LEN:
            raise SignatureVerificationError(
                f"ed25519 public key must be {_ED25519_PUBLIC_KEY_LEN} bytes "
                f"(got {len(public_key)})"
            )
        if len(signature) != _ED25519_SIGNATURE_LEN:
            raise SignatureVerificationError(
                f"ed25519 signature must be {_ED25519_SIGNATURE_LEN} bytes "
                f"(got {len(signature)})"
            )
        try:
            pub = Ed25519PublicKey.from_public_bytes(public_key)
        except Exception as exc:  # cryptography raises ValueError family
            raise SignatureVerificationError("public key is not a valid ed25519 key") from exc
        try:
            pub.verify(signature, data)
        except InvalidSignature:
            return False
        return True


def ed25519_sign(private_key_bytes: bytes, data: bytes) -> bytes:
    """Sign `data` with a raw 32-byte Ed25519 seed; returns a 64-byte signature.

    Test helper only: production signing happens off-line with the founder's
    private key and is never done on the client. Kept here so the hermetic test
    can produce a valid signature without shelling out to openssl.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: WPS433
            Ed25519PrivateKey,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - env guard
        raise SignatureVerificationError(
            "the 'cryptography' package is required for ed25519_sign"
        ) from exc
    if len(private_key_bytes) != _ED25519_PUBLIC_KEY_LEN:
        raise SignatureVerificationError(
            f"ed25519 private seed must be {_ED25519_PUBLIC_KEY_LEN} bytes "
            f"(got {len(private_key_bytes)})"
        )
    priv = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return priv.sign(data)


def ed25519_public_bytes(private_key_bytes: bytes) -> bytes:
    """Return the 32-byte public half of a raw 32-byte Ed25519 seed (test helper)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: WPS433
            Ed25519PrivateKey,
        )
        from cryptography.hazmat.primitives import serialization  # noqa: WPS433
    except ModuleNotFoundError as exc:  # pragma: no cover - env guard
        raise SignatureVerificationError(
            "the 'cryptography' package is required"
        ) from exc
    priv = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
