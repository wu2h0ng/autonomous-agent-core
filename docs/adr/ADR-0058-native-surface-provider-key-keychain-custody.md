# ADR-0058: Native Surface Provider-Key Custody in macOS Keychain

- Status: Accepted (founder decision 2026-08-12)
- Date: 2026-08-12
- Deciders: founder (explicit answer to Wave 2 scope question: "授权 Keychain（推荐）")

## Context

Wave 1 (ADR-covered program `2026-08-11-agent-os-native-surface-runtime-program-design`, plan `2026-08-11-agent-os-native-surface-wave1`) resolves provider keys from environment variables only; the runtime descriptor, protocol payloads, SQLite, logs, and tests never contain them.

Wave 2 introduces a Tauri macOS shell whose process model (program design §5.1) gives the shell responsibility for "Keychain access". The exit gate for a clean arm64 Mac installation requires the app to configure a provider and start the supervised Runtime without manually setting environment variables. That requires a custody location the desktop process can write and the daemon can read without the user exporting variables by hand. Moving provider keys into macOS Keychain is therefore a change to the Wave 1 secret-handling boundary and requires this ADR.

## Options Considered

1. **Environment variables only (status quo).**
   - Cost: every launch requires the user to export keys by hand or store them in a shell profile; the arm64 `.app` exit gate ("launch, configure, restart, recover without manually starting Python") cannot be met for a double-clicked app launched by LaunchServices, which does not inherit a terminal profile.
   - Benefit: zero new secret-storage dependency; identical to Wave 1.
   - C1–C7: compatible; no authority change.

2. **macOS Keychain via `keyring` (Rust crate, Security framework) with env fallback.**
   - Cost: new OS-level secret store dependency; Keychain unlock prompts on some configurations; requires careful ACL/access-group handling in an unsigned dev artifact (no entitlement binding until signing).
   - Benefit: keys persist across launches for the packaged app; Keychain is the platform-standard OS secret store; per-item access control; survives app restart without shell profile.
   - C1–C7: compatible. C7 is untouched; keys remain credentials, not authority. Strongest counter-argument recorded: an unsigned `.app` cannot bind Keychain access groups by entitlements, so items are protected only by the default login-keychain ACL; Wave 2 explicitly keeps this as a dev-artifact boundary and does not claim release-grade isolation.

3. **Encrypted local config file (e.g., 0600 file with derived-key encryption).**
   - Cost: reimplements key management (wrapping key custody problem), worse audit story, no OS keychain UI/ACL.
   - Benefit: no new dependency.
   - Rejected: inferior to the platform keychain for the same threat model; wrapping-key custody is unsolved and adds risk.

## Decision

Wave 2 adopts **option 2**: provider keys are written to and read from macOS Keychain by the Tauri shell (Rust, `keyring` crate over the Security framework), with the existing environment variables as an explicit fallback for the CLI and for daemons started outside the shell.

Concrete rules:

- The shell is the only process that reads Keychain items. The renderer never receives the key value except through one write-only path for initial configuration: a single allowlisted IPC command (`custody:set_provider_key`) that writes the item and returns only a boolean. The key value is never read back through IPC, never logged, never stored in webview-local storage, and never serialized into the runtime descriptor, protocol payloads, SQLite, logs, or tests.
- The daemon receives the provider key only at startup via an environment variable injected by the shell (or by the user's own environment when started from the CLI); the key never appears in the runtime descriptor, protocol payloads, SQLite, logs, or tests. A daemon started from the CLI continues to resolve the environment as in Wave 1; app-side Keychain custody is shell-managed in Wave 2a (recorded as a known boundary: the CLI cannot parse app-Keychain items until a later slice).
- Fallback precedence: environment variable (if set) wins; otherwise the shell reads the Keychain item for the configured provider model/base URL.
- Keychain item naming is namespaced under `com.agent-os.runtime` with `service` + `account` = provider profile identity; no provider secret is stored in the repo, docs, or run artifacts.
- This ADR authorizes Keychain as the custody location for **provider credentials only** (API keys/tokens for model providers). It does not authorize storing customer data, cookies, or other secrets; does not move any authority semantics; and does not change C1–C7.
- The unsigned arm64 `.app` dev artifact has no entitlement-bound access groups; this is recorded as a known dev-boundary limitation, not a release claim.

## Consequences

- Wave 2 (Tauri shell + daemon supervision) can meet its clean-install exit gate without manual env export.
- New dependency surface: `keyring` crate; macOS-only for Wave 2.
- Secret-handling boundary in the program spec §8.2 and the Wave 1 verification report is aligned: "environment-resolved by the daemon" becomes "environment-resolved or Keychain-custodied by the shell, environment-injected at daemon start". Program spec §8.2 already mandates "macOS provider keys, OAuth tokens, and device private keys live in Keychain"; this ADR scopes the Wave 2a implementation of that rule to provider credentials with env fallback.
- ADR-0058 does not authorize release, signing, notarization, daily usability, or any autonomy claim.
