# Agent OS Native Surface Wave 2a — macOS Shell, Daemon Supervision, Keychain Custody, Minimal Canvas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first bounded Wave 2 slice: a Tauri v2 macOS shell that supervises the Wave 1 Python daemon, custodians provider keys in Keychain (ADR-0058, env fallback), and renders a minimal Workspace Canvas (Agent Thread, Evidence and Approval, Files read-only) that consumes the SAME local Runtime through the versioned Surface protocol. Produces an unsigned arm64 `.app` development artifact.

**Architecture:** Tauri shell (Rust) owns window/tray/lifecycle/Keychain; narrow IPC bridge for daemon lifecycle + custody status only; React/TypeScript renderer owns Canvas and panels as typed Surface consumers over HTTP+SSE via the private descriptor; the Wave 1 daemon owns all canonical state. No new authority semantics.

**Tech Stack:** Rust (Tauri v2), React 18 + TypeScript + Vite, stdlib HTTP/SSE client in TS (or minimal fetch/EventSource), Python daemon unchanged, `keyring` crate, arm64-apple-darwin target.

## Global Constraints

- Implement in a NEW isolated worktree created from reconciled exact head `ed75c28a`; suggested branch `codex/native-surface-wave2a-macos-shell-20260812`.
- The renderer must never open the daemon SQLite database or construct `AgentOSApplication`; all state flows through the Surface protocol.
- The Tauri IPC bridge is allowlisted: daemon start/stop/status/restart; custody status; and write-only `custody:set_provider_key`/`custody:clear_provider_key` (key value crosses inbound only, never read back).
- Provider keys: Keychain (ADR-0058) or shell-injected environment; never in renderer, descriptor, SQLite, logs, tests, or repo.
- The daemon Python executable is resolved explicitly by the shell (configured `agent-os-runtime` console-script venv path or the shell's own runtime executable), never bare `python` from PATH — GUI-launched processes have no terminal PATH. Record PATH-independent resolution as a packaging prerequisite of the dev artifact.
- No live-provider requests, Google/Chrome APIs, cloud sync, Workers, signing, notarization, or release in this plan.
- Every state-changing command keeps protocol version, token, `SurfaceClientRef`, idempotency key, and exact event sequence (Wave 1 rules).
- Tests first, observed failing, before implementation for every behavior slice — including Rust unit tests and renderer Vitest tests.
- Do not weaken Wave 1 E2E assertions; `agent-os chat` and the protocol client keep working unchanged.
- Toolchain prerequisite (recorded, not installed by this plan): Rust 1.96, Node 22, npm present; `tauri-cli` installable via npm; macOS Command Line Tools present (full Xcode not required for an unsigned dev `.app` in this slice — verified on this machine).

## File Structure (new, under `apps/macos/`)

- `apps/macos/shell/Cargo.toml` — Tauri v2 project manifest.
- `apps/macos/shell/src/main.rs` — shell entry; window/tray; daemon supervisor; keychain custody.
- `apps/macos/shell/src/daemon_supervisor.rs` — spawn/health/restart of `agent-os-runtime` via descriptor; boot-id-matched descriptor handling.
- `apps/macos/shell/src/keychain_custody.rs` — Keychain provider-key read/write (keyring) with env fallback.
- `apps/macos/shell/src/ipc.rs` — narrow allowlisted IPC commands.
- `apps/macos/shell/tauri.conf.json` — app identifier, window config, dev artifact settings.
- `apps/macos/renderer/package.json` — Vite + React + TypeScript.
- `apps/macos/renderer/src/` — Canvas routes, panels, Surface client (fetch + EventSource), state.
- `apps/macos/renderer/src/surface_client.ts` — typed Surface HTTP/SSE client (mirrors `apps/cli/surface_client.py` semantics).
- `apps/macos/renderer/src/panels/agent_thread.tsx`, `evidence_approval.tsx`, `files.tsx` — first three panels.
- `tests/product/test_wave2_surface_client_ts.md` — review-led check contract for the TS client (unit tests run under `npm test` with Vitest).
- `tests/product/test_daemon_supervisor_contract.md` — contract checklist the Rust supervisor must satisfy (validated by Rust unit tests + a Python-side descriptor helper).
- `docs/CURRENT_STATE.yaml` — Wave 2a status fields after verification.

## Task 1: Freeze the Wave 2a authority contract

- [ ] Write a failing Python-side test that a spawned daemon can be supervised: `tests/product/test_wave2_supervision_contract.py` asserting `start_runtime`/`stop_runtime`/`daemon_status` semantics the Rust supervisor will rely on (descriptor privacy, boot-id match, health endpoint auth) — mostly re-verification of Wave 1, kept RED-first as the contract.
- [ ] Confirm the Wave 1 daemon CLI (`agent-os-runtime serve`) and descriptor helpers are importable and behave at the exact head.
- [ ] Commit `docs(adr): authorize keychain custody (ADR-0058)` + this plan + child spec + supervision contract test.

## Task 2: Rust shell scaffold and narrow IPC

- [ ] `apps/macos/shell` — Tauri v2 app with one window and a tray stub; `tauri.conf.json` with `com.agent-os.runtime` identifier.
- [ ] IPC allowlist (test-first): `daemon:start`, `daemon:stop`, `daemon:status`, `custody:status`, `custody:set_provider_key`, `custody:clear_provider_key`. Every other command is rejected.
- [ ] Unit tests (test-first): IPC allowlist rejects unknown commands; custody status does not expose the key value; `custody:set_provider_key` is write-only (returns boolean, no read-back).
- [ ] Verify `cargo build` for `aarch64-apple-darwin`.

## Task 3: Daemon supervision in Rust

- [ ] `daemon_supervisor.rs`: resolve the daemon Python executable explicitly (configured `agent-os-runtime` venv path, PATH-independent); spawn `apps.runtime_daemon` with the configured database/workspace/descriptor, wait for the authenticated health route (10s), restart on unexpected exit (bounded backoff, max N restarts/hour), stop via SIGTERM + boot-id-matched descriptor removal.
- [ ] Unit tests (Rust, test-first): descriptor parsing; health wait timeout; boot-id mismatch refuses descriptor removal; restart budget exhaustion stops.
- [ ] Python-side integration test: start supervisor-managed daemon, kill it, assert supervision restarts it and the same session is recoverable.

## Task 4: Keychain custody (ADR-0058)

- [ ] `keychain_custody.rs` (test-first): `set/read/clear` provider key in Keychain (keyring) namespaced `com.agent-os.runtime`; env fallback precedence env > keychain; daemon startup injects the resolved key into the daemon environment.
- [ ] Unit tests: env wins; key value never returned through IPC (set returns boolean only; no read command exists); clear removes item.
- [ ] Renderer cannot request the key value (no IPC command carries it outbound).

## Task 5: Renderer scaffold and Surface client

- [ ] `apps/macos/renderer` — Vite + React + TypeScript; Vitest configured.
- [ ] `surface_client.ts` mirrors the Wave 1 client: open/get/run_turn/decide_approval/pause/resume/correct/events; protocol-version check; closed typed errors; sequence tracking; token injected by the Rust layer, never in webview storage.
- [ ] **Conformance (I5):** a shared JSON fixture corpus (`apps/macos/renderer/tests/fixtures/surface_contract/*.json` — commands, snapshots, SSE bodies) is consumed by BOTH the Python `test_surface_client.py` (as `--fixture` table tests or a fixture-reading test) and the Vitest suite; both clients must parse the same fixtures to identical semantics. The Vitest suite fails on any mapping the Python client rejects and vice versa.
- [ ] Vitest unit tests against a stubbed HTTP server: protocol mismatch, 401 mapping, SSE cursor resume, sequence tracking.

## Task 6: Minimal Canvas panels

- [ ] Canvas frame: left rail (Workspace/Task nav), active Task header (status, pause/correction controls, outstanding approval), composer sending typed commands into the protocol.
- [ ] Agent Thread panel: render session transcript from `events` (resumable SSE cursor).
- [ ] Evidence and Approval panel: render pending approval (capability + preview + exact digest) and Approve/Reject actions via `decide_approval`.
- [ ] Files panel: read-only listing via the Wave 2a protocol addition `GET /v1/surface/tasks/{task_id}/files` (bound in the child spec §4: path, size, mtime; no content without a task capability). Implement the route server-side (Python) with auth + scope + task-ownership checks, test-first.
- [ ] Vitest + a renderer-level test: approve flow calls `decide_approval` with the exact digest; SSE resume after reconnect.

## Task 7: arm64 `.app` dev artifact and exit gate

- [ ] `tauri build` producing an unsigned `aarch64-apple-darwin` `.app` dev artifact.
- [ ] Exit-gate verification on this Mac (program spec §10 Wave 2 gate, "launches, configures, exits, restarts, and recovers without manually starting Python"): launch the `.app` (no manual Python start) -> configure a provider through the shell (Keychain custody, write-only IPC set) -> assert the supervised daemon resolves the provider key from the shell-injected environment (a bounded probe checks the daemon's configured provider is usable without env vars in the launch context) -> a Task created in the renderer is visible in Agent Thread and Evidence/Approval -> quit and relaunch recovers the same Task -> kill the daemon process and assert the supervisor restarts it.
- [ ] Record the exit-gate transcript in `.agent_runs/native-surface-wave2a-20260812/verification.md`.
- [ ] `git diff --check`; no push/merge.

## Task 8: Full verification and claim ceiling

- [ ] Re-run the entire Wave 1 focused suite + Wave 2a tests; confirm no Wave 1 regression (1792 passed / 18 pre-existing failed baseline unchanged).
- [ ] `ruff`, `pyright` clean; `cargo test` clean; `npm test` clean.
- [ ] Update `docs/CURRENT_STATE.yaml` with `IMPLEMENTED/TESTED/INTEGRATED/REVIEWED` and explicit `PUSHED:false/RELEASED:false/DAILY_USABLE:false`; record Keychain as dev-boundary (unsigned, no entitlement-bound access groups).
- [ ] Request independent exact-head review; commit evidence only after approval.

## Plan Self-Review Checklist

- The renderer cannot open SQLite, construct an application, or receive key values.
- The IPC bridge is allowlisted and rejects everything else.
- Panels are typed Surface consumers; no native/Google/Chrome/shell/Worker calls.
- Daemon supervision is bounded (backoff, restart budget) and boot-id-matched.
- Keychain custody is namespaced, env-fallback, ADR-0058-bound.
- The `.app` artifact is unsigned and dev-only; no signing/notarization/release/daily-usability claim.
- Wave 1 CLI, protocol client, daemon, and E2E remain green.
