"""Pluggable signature backend for R-STATE-CREDIT-1 authority artifacts.

The production harness is expected to supply a real Ed25519 implementation.
This module provides only the protocol and test-only deterministic substitutes.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Protocol, runtime_checkable


@runtime_checkable
class SignatureBackend(Protocol):
    """Sign and verify detached signatures bound to a textual identity key."""

    def sign(self, identity_key: str, message: bytes) -> bytes: ...

    def verify(
        self,
        identity_key: str,
        message: bytes,
        signature: bytes,
    ) -> bool: ...


class SignatureBackendError(RuntimeError):
    """Raised when a signature backend cannot complete an operation."""


class TestHmacBackend:
    """Deterministic HMAC-SHA256 backend for unit tests.

    Each ``identity_key`` produces a distinct secret, so swapping or reusing
    identities changes the signature.  This is **not** a secure signature
    scheme and must never be used outside tests.
    """

    __test__ = False

    __slots__ = ("_master_secret",)

    def __init__(self, master_secret: bytes | None = None) -> None:
        if master_secret is None:
            # Fixed test-only secret; determinism is required for reproducible
            # tests, not for security.
            master_secret = b"test-only-hmac-master-secret"
        if not isinstance(master_secret, bytes):
            raise SignatureBackendError("master_secret must be bytes")
        self._master_secret = master_secret

    def _derive_key(self, identity_key: str) -> bytes:
        if not isinstance(identity_key, str):
            raise SignatureBackendError("identity_key must be str")
        return hmac.new(
            self._master_secret,
            identity_key.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def sign(self, identity_key: str, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise SignatureBackendError("message must be bytes")
        key = self._derive_key(identity_key)
        return hmac.new(key, message, hashlib.sha256).digest()

    def verify(
        self,
        identity_key: str,
        message: bytes,
        signature: bytes,
    ) -> bool:
        if not isinstance(signature, bytes):
            return False
        expected = self.sign(identity_key, message)
        return hmac.compare_digest(expected, signature)


class Ed25519BackendStub:
    """Placeholder for a future real Ed25519 signature backend."""

    def sign(self, identity_key: str, message: bytes) -> bytes:
        raise NotImplementedError(
            "Ed25519BackendStub.sign is not implemented; "
            "replace with a real Ed25519 backend before production use"
        )

    def verify(
        self,
        identity_key: str,
        message: bytes,
        signature: bytes,
    ) -> bool:
        raise NotImplementedError(
            "Ed25519BackendStub.verify is not implemented; "
            "replace with a real Ed25519 backend before production use"
        )
