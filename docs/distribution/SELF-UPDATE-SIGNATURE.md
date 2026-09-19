# Self-update: current status and the optional signature-verification scaffold

Status: SCAFFOLDING. The self-update mechanism itself lives in the TypeScript
client and is already implemented (see below). This file (a) records its current
state honestly and (b) introduces an OPTIONAL, DEFAULT-OFF Ed25519 signature
verification scaffold in Python. The scaffold is NOT wired into the running
self-update path and does NOT claim to be production-grade.

## 1. Self-update as it exists today

Location: `apps/cli-ts/src/self-update.ts` + `self-update-command.ts`
(shell surface `noem self-update ...`), dispatched in `cli.tsx` BEFORE daemon
resolution so an update cannot wake a kernel.

Verified properties (measured, not aspirational — see
`docs/CURRENT_STATE.yaml` self_update_2026_09_18):

- **Default off by construction.** No default channel, no background check, no
  telemetry. With no `--source` it returns typed `no_source_configured` (exit 2)
  having touched neither network nor disk. The source gate is checked before the
  install path is even resolved.
- **No source today.** Publishing a release channel is founder-reserved; there
  is no host, manifest, or artifact that anything can be updated FROM. So
  `noem self-update` refuses rather than falling back to anything.
- **Integrity, NOT authenticity.** The chain is: scheme → manifest shape
  (`noem-self-update-manifest/1`, per-platform `{file,sha256,bytes}`, bare
  basename only) → a 64-hex `sha256` MUST be present (`checksum_missing`) →
  strictly newer version (`up_to_date` / `downgrade_refused`) → executable-image
  shape/magic check → SHA-256 of the staged bytes READ BACK FROM DISK compared
  to the manifest → copy backup → atomic same-directory rename → post-install
  `--version` probe in a fresh process → restore-and-reverify on failure.
- **The honest gap this slice addresses.** A source that can serve `manifest.json`
  can serve ANY artifact together with a matching checksum. The checksum proves
  "these are the bytes the manifest described"; it does NOT prove WHO signed the
  manifest. A forged higher version cannot be detected today. The manifest
  schema is versioned (`.../1`) precisely so a signature can be added without
  reinterpreting existing manifests.

## 2. The optional signature-verification scaffold (this slice)

New Python module: `packages/os_core/src/agent_os_core/distribution/signature_verify.py`.

- An abstract `ArtifactVerifier` interface (`verify(data, signature,
  public_key) -> bool` plus a key fingerprint helper).
- One concrete implementation: `Ed25519Verifier` (Ed25519 detached signature
  over the bytes to verify), backed by the `cryptography` package.
- **Default off.** Nothing in the running self-update path calls this. It is a
  release/verification-side scaffold: given a public key and a detached
  signature, it answers "does this signature cover these bytes".
- Hermetic test: `tests/product/test_signature_verify_scaffold.py` generates a
  fresh test keypair, signs, verifies valid, then verifies that (a) a tampered
  artifact fails, (b) a signature by the WRONG key fails, (c) a truncated /
  wrong-length signature fails.

### Why Ed25519 and not cosign/minisign here

The brief offered cosign / minisign / Ed25519. Ed25519 is the lightest: it has
no external binary (cosign/minisign would shell out to a tool the operator must
have installed), it is a well-understood signature primitive, and
`cryptography` already bundles it. cosign/minisign remain valid options the
founder may choose later; the abstract interface above does not preclude them.

### Explicit limits (do not overclaim)

- This is a SCAFFOLD, not production-grade signature verification. It proves
  the crypto primitive and the interface shape. It does NOT yet:
  - pin a real public key or trust anchor (no production key exists),
  - wire verification into `apps/cli-ts/src/self-update.ts` (that is the
    TypeScript runtime and a separate change),
  - define a signature envelope / canonicalization for the manifest (what bytes
    exactly are signed is a product decision),
  - verify a chain of trust, revocation, or key rotation.
- `cryptography` is added as an OPTIONAL test-time dependency (the
  `product-test` extra) so the hermetic test actually runs; it is NOT a runtime
  dependency of the installed tool.
- Choosing cosign vs minisign vs Ed25519, and generating the production signing
  key, is a FOUNDER decision. This slice only proves the mechanism works and
  leaves the interface in place.

## 3. Security model (proposed, not yet enforced)

If and when the founder enables signature verification, the model is:

1. The release process signs the manifest (and/or the artifact bytes) with a
   private Ed25519 key whose PUBLIC half ships inside the binary (the trust
   anchor).
2. `self-update` fetches `manifest.json` AND its detached signature, verifies the
   signature against the embedded public key BEFORE trusting the checksum in the
   manifest.
3. Only after the signature verifies does the existing SHA-256 integrity chain
   run. Integrity alone is then upgraded to authenticity: a source that cannot
   sign cannot inject a forged higher version.
4. Until then, the documented invariant stands: self-update is integrity-only,
   default-off, sourceless, and must not be represented as authenticated.
