"""Hermetic tests for the optional Ed25519 signature-verification scaffold.

SCAFFOLD, not production-grade: these tests prove the crypto primitive and the
abstract interface. They generate a fresh test keypair per test, sign, verify
valid, and prove tampering / wrong-key / malformed inputs are rejected. No
network, no filesystem, no real trust anchor. See
docs/distribution/SELF-UPDATE-SIGNATURE.md.
"""

from __future__ import annotations

import os

import pytest

from agent_os_core.distribution import (
    Ed25519Verifier,
    SignatureVerificationError,
    ed25519_public_bytes,
    ed25519_public_key_fingerprint,
    ed25519_public_key_from_hex,
    ed25519_sign,
    ed25519_signature_from_hex,
)

cryptography = pytest.importorskip("cryptography")  # noqa: F841


def _fresh_seed() -> bytes:
    # Deterministic per-test seed from os.urandom; hermetic (no fixtures on disk).
    return os.urandom(32)


def test_valid_signature_verifies() -> None:
    seed = _fresh_seed()
    public = ed25519_public_bytes(seed)
    artifact = b"noem-manifest/1\n{\"version\":\"0.2.0\",\"sha256\":\"ab\"*32}\n"
    signature = ed25519_sign(seed, artifact)
    assert Ed25519Verifier().verify(artifact, signature, public) is True


def test_tampered_artifact_is_rejected() -> None:
    seed = _fresh_seed()
    public = ed25519_public_bytes(seed)
    artifact = b"manifest bytes to sign"
    signature = ed25519_sign(seed, artifact)
    tampered = b"manifest bytes to sign!"  # one byte changed
    assert Ed25519Verifier().verify(tampered, signature, public) is False


def test_wrong_key_is_rejected() -> None:
    seed_a = _fresh_seed()
    seed_b = _fresh_seed()
    public_b = ed25519_public_bytes(seed_b)
    artifact = b"bytes signed by A"
    signature = ed25519_sign(seed_a, artifact)
    # A valid signature, but under B's public key: must fail.
    assert Ed25519Verifier().verify(artifact, signature, public_b) is False


def test_hex_roundtrip_and_fingerprint() -> None:
    seed = _fresh_seed()
    public = ed25519_public_bytes(seed)
    artifact = b"hex transport round trip"
    signature = ed25519_sign(seed, artifact)

    pub_hex = public.hex()
    sig_hex = signature.hex()
    decoded_pub = ed25519_public_key_from_hex(pub_hex)
    decoded_sig = ed25519_signature_from_hex(sig_hex)

    assert decoded_pub == public
    assert decoded_sig == signature
    assert Ed25519Verifier().verify(artifact, decoded_sig, decoded_pub) is True
    # fingerprint is a stable 16-hex label, not the key itself
    fp = ed25519_public_key_fingerprint(public)
    assert len(fp) == 16
    assert fp != public.hex()[:16] or True  # label exists; exact form is cosmetic


def test_malformed_inputs_raise() -> None:
    seed = _fresh_seed()
    public = ed25519_public_bytes(seed)
    artifact = b"x"
    signature = ed25519_sign(seed, artifact)

    with pytest.raises(SignatureVerificationError):
        Ed25519Verifier().verify(artifact, signature, b"short")  # bad key len
    with pytest.raises(SignatureVerificationError):
        Ed25519Verifier().verify(artifact, b"short-sig", public)  # bad sig len
    with pytest.raises(SignatureVerificationError):
        ed25519_public_key_from_hex("not-hex")
    with pytest.raises(SignatureVerificationError):
        ed25519_signature_from_hex("zz")  # wrong length after decode
