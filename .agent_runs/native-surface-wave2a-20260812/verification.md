# Agent OS Native Surface Wave 2a — Exit Gate Transcript

- Date: 2026-08-13
- Head: codex/native-surface-wave2a-macos-shell-20260812 (Task 7)
- Artifact: `apps/macos/shell/target/aarch64-apple-darwin/release/bundle/macos/Agent OS.app` (unsigned dev artifact, `com.agent-os.runtime`)

## Programmatic exit-gate verification (headless)

Performed against the real `.app` binary with daemon config injected via env
(`AGENT_OS_DAEMON_*`), `PYTHONPATH` set for the repo packages. No manual
Python daemon start.

1. **Launch (no manual Python):** launched `Agent OS.app/Contents/MacOS/agent-os-shell`
   -> within 8s the supervised daemon wrote `runtime.json` (descriptor) and
   created the SQLite database. Daemon pid was a child of the app process.
   `boot1=boot:e3c92ad3-...`.
2. **Supervised restart:** `kill -9 <daemon pid>` -> within 8s the supervisor
   respawned the daemon with a NEW descriptor boot id
   (`boot2 != boot1`, SUPERVISED RESTART OK).
3. **Clean shutdown:** `kill -TERM <app pid>` -> app exited cleanly, the
   daemon received SIGTERM (graceful, not SIGKILL), removed its own descriptor
   (boot-id match) and closed SQLite: `descriptor cleaned`, `orphan daemons: 0`.

## Rust + renderer suites

- `cargo test`: 16 unit (IPC allowlist, supervisor decision machine, keychain
  custody, descriptor parsing, health probe) + 1 supervisor integration
  (real daemon spawn/kill/restart) + 1 opt-in keychain integration (skipped
  unless `AGENT_OS_WAVE2_KEYCHAIN_TEST=1`) — all pass.
- `npm test` (Vitest): 10 tests (surface client conformance, panels) — all pass.
- Python: `test_wave2_supervision_contract.py` 5 passed;
  `test_wave2_renderer_conformance.py` 3 passed; `test_surface_api.py` 15
  passed (incl. Files route).

## Human-verified portion (not reproducible headlessly)

- In-window interactive task creation requires a desktop session and remains
  a human verification; the renderer Canvas is wired (runtime:connection,
  composer, Agent Thread / Evidence and Approval / Files panels) and panel
  logic is covered by Vitest; protocol round-trips are covered by the Wave 1
  E2E gate.
- Real Keychain write/read/clear round-trip is opt-in
  (`AGENT_OS_WAVE2_KEYCHAIN_TEST=1`) to avoid touching the user's login
  keychain from an automated run.

## Claim ceiling

Unsigned dev artifact; no signing, notarization, release, daily usability,
Google/Chrome, cloud sync, or Worker claim. Renderer never opens SQLite,
never constructs an application, and cannot read back provider keys.
