# ADR-0064: Release artifact signature — minisign format (ed25519 under the hood)

- Status: Accepted (founder ruling 1, 2026-09-19; verifier implemented on
  branch `feat/l4-audit-closure-20260919`, default-off, NO production anchor).
- Date: 2026-09-19
- Deciders: founder (rejected cosign and raw-ed25519, chose minisign).
- Preserves: terminal-first minimal dependency principle; no network on the
  verify path; fail-closed defaults.
- Numbering check: max baseline ADR is 0062. This takes 0064.

## 1. Context

Self-update must trust a downloaded release manifest + artifacts. The previous
scaffold (`distribution/signature_verify.py`) was a raw ed25519 wrapper with no
trust anchor, no envelope, no key id, and was explicitly unwired. We needed a
chosen format before wiring verification.

## 2. Options considered

- **A — cosign (OCI / keyless Fulcio / Rekor).** Rejected. It pulls in an OCI
  registry, Fulcio/Rekor transparency-log dependency and online attestation
  infrastructure. That contradicts terminal-first / minimal-dependency and makes
  an offline `curl | sh` install need network trust we do not want to carry.
- **B — Hand-rolled raw ed25519 envelope.** Rejected. We would have to invent
  key-id framing, domain separation, comment binding, and rollback handling
  ourselves. Rolling our own envelope is exactly the failure mode this ADR
  exists to avoid.
- **C — minisign (chosen).** The on-disk format is small, fully offline,
  ed25519-based, has an explicit 8-byte key id (multi-anchor / rotation), an
  untrusted + trusted comment split, and a short pin-able `.pub`. Verification
  needs no network and no new system package (pure-Python + `cryptography`).

## 3. Decision

- Signing target: a **release manifest** (version, per-artifact sha256,
  `released-at`, minimum-required version floor). Self-update downloads the
  manifest + its `.minisig`, verifies the minisign signature with the pinned
  public key, then per-artifact sha256, then monotonic/floor version checks.
  Any mismatch → fail-closed; atomic replace with a kept rollback copy.
- Wire format is the exact minisign layout: 42-byte pubkey struct
  (`"Ed" || key_id(8) || ed25519_pub(32)`); 108-byte signature struct
  (`"Ed" || key_id(8) || file_sig(64) || csum_alg(2) || blake2b256(32)`); plus
  a second 64-byte signature over `file_sig || trusted_comment`.
- Implemented in `packages/os_core/src/agent_os_core/distribution/minisign_verify.py`
  (`MinisignVerifier`), fail-closed on any parse/key-id/signature failure.
- **Trust bootstrapping:** repo/install path pins a minisign public key
  (pinned + TOFU). The key id supports multiple anchors and rotation; a rotation
  announcement is itself signed by the old key.
- **Default off / no claim:** the verifier exists and is tested, but self-update
  does not pin a production anchor yet. There is NO production long-term
  private key in this repo; tests generate a fixed DEV seed only.

## 4. Consequences and reversibility

- Reversible: swapping the format later means publishing a new signed manifest
  under a new key id and migrating the pinned `.pub`; old clients verify the
  old manifest, new clients the new one.
- The production signing-key custody ceremony (offline generation, Shamir/
  hardware, revocation procedure) is a separate founder ceremony — NOT done
  here, NOT in this repo.
- Interop: a frozen known-answer vector pins the parser; CI may additionally
  shell out to the `minisign` CLI when installed (optional, skipped if absent).

## 5. Test evidence

`tests/product/test_minisign_verify.py` (5 tests): frozen known-answer vector
from fixed DEV seed `bytes(range(32))`/key id `TESTKEY0` verifies; tampered
file, wrong key, key-id mismatch, and malformed pubkey all fail-closed.
