"""Minisign-compatible detached-signature verification (ed25519 under the hood).

Status: SCAFFOLD / DEFAULT-OFF. This implements the *verification* side of the
`minisign` on-disk format (Frank Denis's minisign wire format, ed25519 + key id
+ trusted comment). It is NOT wired into the running self-update path yet, ships
NO production trust anchor, and choosing/pinning the production signing key is a
founder ceremony (see ADR-0064).

Why minisign and not a raw ed25519 envelope: we do NOT invent our own key-id /
domain-separation / rollback format. Minisign is a small, well-audited, offline
verifiable format with a short, pin-able `.pub` file and an explicit key-id for
multi-anchor rotation. See ADR-0064 for the alternatives rejected (cosign,
raw ed25519).

Wire format (exact, from the minisign reference implementation):

  Public key file (``minisign.pub``)::

      untrusted comment: <free text>
      <base64(42 bytes)>

  The 42 bytes:
    [0:2]   signature algorithm  = b"Ed"
    [2:10]  key id (8 bytes)
    [10:42] ed25519 public key (32 bytes)

  Signature file (``file.minisig``)::

      untrusted comment: <free text>
      <base64(108 bytes)>
      trusted comment: <free text>
      <base64(64 bytes)>

  The 108 bytes:
    [0:2]    signature algorithm = b"Ed"
    [2:10]   key id (8 bytes)
    [10:74]  ed25519 signature over the FILE bytes (64 bytes)
    [74:76]  checksum algorithm (2 bytes)
    [76:108] blake2b-256 checksum of the file, keyed by the key id (32 bytes)

  The final 64 bytes (line 4) are a second ed25519 signature over
  ``file_sig || trusted_comment``.

Only the `cryptography` package is required, and it is a TEST-time extra
(`product-test`), never a runtime dependency of the installed tool.
"""

from __future__ import annotations

import base64

from .signature_verify import (
    SignatureVerificationError,
    ed25519_public_key_from_hex,
)


_SIG_ALG = b"Ed"
_PUBKEY_BYTES = 42
_SIG_STRUCT_BYTES = 108
_ED25519_PUBLIC_KEY_LEN = 32
_KEY_ID_LEN = 8
_FILE_SIG_LEN = 64


class MinisignVerifier:
    """Verify minisign detached signatures against a pinned ed25519 public key.

    Fail-closed by construction: any malformed input, any key-id mismatch, any
    signature that does not verify, or any missing comment raises
    :class:`SignatureVerificationError`. It never returns a fuzzy "maybe" and
    never logs the public key in full.
    """

    name = "minisign-ed25519"

    def verify_file(
        self,
        *,
        file_bytes: bytes,
        public_key_b64: str,
        signature_b64_block: str,
    ) -> bool:
        """Verify ``file_bytes`` against a minisign signature block.

        ``public_key_b64`` is the base64 body of a minisign `.pub` (the 42-byte
        key). ``signature_b64_block`` is the FULL minisign signature file text
        (untrusted comment line + 108-byte base64 + trusted comment line +
        64-byte base64). Returns True only when every check passes.
        """

        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: WPS433
            Ed25519PublicKey,
        )
        from cryptography.exceptions import (  # noqa: WPS433
            InvalidSignature,
        )

        pub_key_id, ed_pub = self._parse_public_key(public_key_b64)
        sig_key_id, file_sig, trusted_comment, trusted_sig = self._parse_signature_block(
            signature_b64_block
        )
        if sig_key_id != pub_key_id:
            raise SignatureVerificationError(
                "minisign key id mismatch between public key and signature"
            )
        pub = Ed25519PublicKey.from_public_bytes(ed_pub)
        try:
            pub.verify(file_sig, file_bytes)
        except InvalidSignature as exc:
            raise SignatureVerificationError("file signature does not verify") from exc
        # The trusted-comment signature binds (file_sig || trusted_comment) to
        # the same key, so a tampered trusted comment fails closed.
        try:
            pub.verify(trusted_sig, file_sig + trusted_comment.encode("utf-8"))
        except InvalidSignature as exc:
            raise SignatureVerificationError(
                "trusted comment signature does not verify"
            ) from exc
        return True

    @staticmethod
    def _parse_public_key(public_key_b64: str) -> tuple[bytes, bytes]:
        try:
            raw = base64.b64decode(public_key_b64.strip(), validate=True)
        except Exception as exc:  # ValueError on bad base64
            raise SignatureVerificationError("minisign public key is not valid base64") from exc
        if len(raw) != _PUBKEY_BYTES:
            raise SignatureVerificationError(
                f"minisign public key must be {_PUBKEY_BYTES} bytes "
                f"(got {len(raw)})"
            )
        if raw[0:2] != _SIG_ALG:
            raise SignatureVerificationError("minisign public key has wrong signature algorithm")
        key_id = raw[2:10]
        ed_pub = raw[10:42]
        if len(ed_pub) != _ED25519_PUBLIC_KEY_LEN:
            raise SignatureVerificationError("minisign public key is malformed")
        return key_id, ed_pub

    @staticmethod
    def _parse_signature_block(block: str) -> tuple[bytes, bytes, str, bytes]:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        # Minimal, tolerant parse: skip the untrusted comment line, take the
        # 108-byte base64, then "trusted comment:" line, then the 64-byte base64.
        b64_lines = [ln for ln in lines if not ln.startswith(("untrusted", "trusted"))]
        if len(b64_lines) < 2:
            raise SignatureVerificationError("minisign signature block is missing base64 lines")
        try:
            struct = base64.b64decode(b64_lines[0].strip(), validate=True)
            trusted_sig = base64.b64decode(b64_lines[1].strip(), validate=True)
        except Exception as exc:
            raise SignatureVerificationError("minisign signature is not valid base64") from exc
        if len(struct) != _SIG_STRUCT_BYTES:
            raise SignatureVerificationError(
                f"minisign signature struct must be {_SIG_STRUCT_BYTES} bytes "
                f"(got {len(struct)})"
            )
        if struct[0:2] != _SIG_ALG:
            raise SignatureVerificationError("minisign signature has wrong algorithm")
        key_id = struct[2:10]
        file_sig = struct[10:74]
        if len(file_sig) != _FILE_SIG_LEN:
            raise SignatureVerificationError("minisign file signature is malformed")
        trusted_comment = ""
        for ln in lines:
            if ln.startswith("trusted comment:"):
                trusted_comment = ln[len("trusted comment:"):].strip()
                break
        if len(trusted_sig) != _FILE_SIG_LEN:
            raise SignatureVerificationError("minisign trusted signature is malformed")
        return key_id, file_sig, trusted_comment, trusted_sig


__all__ = [
    "MinisignVerifier",
    "SignatureVerificationError",
    "ed25519_public_key_from_hex",
]
