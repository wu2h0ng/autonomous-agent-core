"""Hermetic tests for the minisign-compatible verifier (ADR-0064).

These pin:
* the wire-format parse (42-byte pubkey, 108-byte signature struct, trusted
  comment second signature);
* a FROZEN known-answer vector generated from a fixed 32-byte DEV seed
  (seed = bytes(range(32)), key id "TESTKEY0") -- the bytes below are the exact
  minisign-format output and are pinned so any drift in the parser redens;
* fail-closed on: tampered file, wrong key, key-id mismatch, malformed input.

No production key is created here. The seed is a fixed test value.
"""

from __future__ import annotations

import base64

import pytest

from agent_os_core.distribution.minisign_verify import (
    MinisignVerifier,
    SignatureVerificationError,
)

# cryptography is an optional test-time extra (product-test). The verifier
# imports it lazily inside methods, so the import above always succeeds. Probe
# it directly and skip the whole module via pytestmark when absent. NOT
# pytest.importorskip (which would hide the module from --collect-only and
# trip the governed file-set gate). Same pattern as
# tests/product/test_signature_verify_scaffold.py.
try:
    import cryptography  # noqa: F401
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False

pytestmark = pytest.mark.skipif(
    not _HAS_CRYPTOGRAPHY,
    reason="cryptography not installed (optional test-time extra; minisign verifier only)",
)


# Frozen known-answer vector (DEVELOPMENT ONLY; seed = bytes(range(32))).
_FROZEN_PUB_B64 = "RWRURVNUS0VZMAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4"
_FROZEN_SIG_STRUCT_B64 = (
    "RWRURVNUS0VZMGZNZtbn3MGLjgLN3TKosh59ovwsPC9UKnh4RA8oryAS450m4/MiWsHFuq+UHD/"
    "US5ehRoH8GN57fpqZRDynTwFCQpmZeueVtyFzjueJOobWUtRnPupZlG1mYZjrQWll9Ze3"
)
_FROZEN_TRUSTED_SIG_B64 = (
    "rwrirydXJbqcsA4Ni8PaSm0OQNwAGpTS+miy5s4hJBybJlMtlWsD8kj1f+v3ty5KGvub1SPuld4Ue5X40p9tCg=="
)
_FROZEN_FILE = b"minisign known-answer test vector\n"
_FROZEN_TRUSTED_COMMENT = "minisign test signature, DEV ONLY"


def _frozen_signature_block() -> str:
    return (
        "untrusted comment: minisign test signature\n"
        f"{_FROZEN_SIG_STRUCT_B64}\n"
        f"trusted comment: {_FROZEN_TRUSTED_COMMENT}\n"
        f"{_FROZEN_TRUSTED_SIG_B64}\n"
    )


def test_known_answer_vector_verifies() -> None:
    v = MinisignVerifier()
    assert v.verify_file(
        file_bytes=_FROZEN_FILE,
        public_key_b64=_FROZEN_PUB_B64,
        signature_b64_block=_frozen_signature_block(),
    )


def test_tampered_file_fails_closed() -> None:
    v = MinisignVerifier()
    with pytest.raises(SignatureVerificationError):
        v.verify_file(
            file_bytes=_FROZEN_FILE + b"tampered\n",
            public_key_b64=_FROZEN_PUB_B64,
            signature_b64_block=_frozen_signature_block(),
        )


def test_wrong_public_key_fails_closed() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    other_priv = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
    other_pub = other_priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    other_pub_b64 = base64.b64encode(b"Ed" + b"TESTKEY0" + other_pub).decode()
    v = MinisignVerifier()
    with pytest.raises(SignatureVerificationError):
        v.verify_file(
            file_bytes=_FROZEN_FILE,
            public_key_b64=other_pub_b64,
            signature_b64_block=_frozen_signature_block(),
        )


def test_key_id_mismatch_fails_closed() -> None:
    # Re-encode the pubkey under a DIFFERENT key id; the signature carries
    # TESTKEY0, so the id check must reject it.
    raw = base64.b64decode(_FROZEN_PUB_B64)
    other = b"Ed" + b"OTHERKEY" + raw[10:]
    v = MinisignVerifier()
    with pytest.raises(SignatureVerificationError):
        v.verify_file(
            file_bytes=_FROZEN_FILE,
            public_key_b64=base64.b64encode(other).decode(),
            signature_b64_block=_frozen_signature_block(),
        )


def test_malformed_public_key_is_rejected() -> None:
    v = MinisignVerifier()
    with pytest.raises(SignatureVerificationError):
        v.verify_file(
            file_bytes=_FROZEN_FILE,
            public_key_b64="not-base64!!!",
            signature_b64_block=_frozen_signature_block(),
        )
