# Agent OS Native Surface — Wave 2 Child Spec: macOS Shell and Workspace Canvas

- Status: Proposed (requires CTO/founder gate before implementation)
- Date: 2026-08-12
- Parent: `docs/superpowers/specs/2026-08-11-agent-os-native-surface-runtime-program-design.md` (§10 Wave 2)
- Predecessor: Wave 1 verified at `ed75c28a` on `codex/native-surface-wave1-20260811`
- Boundary: this spec authorizes design only. Implementation proceeds only through bounded plans and the CTO gate, per program spec §10 ("Waves 2 through 4 require their own bounded child spec and plan before implementation").

## 1. Scope

Wave 2 delivers the macOS application shell and Workspace Canvas over the already-verified local Runtime:

1. Tauri v2 macOS shell (Rust) that owns windows, tray, notifications, Keychain access, folder authorization, and supervised child-process lifecycle;
2. React/TypeScript renderer that owns Canvas routes, panels, interaction state, and event rendering;
3. supervised Python Agent Core daemon (the Wave 1 `agent-os-runtime` process) spawned and monitored by the shell;
4. an arm64 `.app` development artifact (unsigned; packaging ≠ signing/notarization/release/daily usability).

Out of scope (explicitly): Google/Chrome integrations (Wave 3), cloud sync and Workers (Wave 4), signing/notarization, release, daily usability, autonomy.

## 2. Process and authority model (from program design §5.1, made binding)

- The packaged app has exactly three layers: Tauri shell (Rust), React/TS renderer, supervised Python daemon.
- The daemon owns ALL canonical product behavior and durable state. The renderer NEVER opens the SQLite database and NEVER constructs an `AgentOSApplication`.
- The renderer consumes the daemon exclusively through the versioned Surface protocol (HTTP commands + resumable SSE events), the same contract the CLI uses; it uses the private 0600 runtime descriptor for base URL and bearer token.
- The Tauri IPC bridge is narrow and allowlisted: daemon lifecycle (start/stop/status/restart) and Keychain custody — status plus a write-only `set`/`clear` for provider keys, where the key value may cross the bridge only inbound (renderer → shell) and is never read back to the renderer. Renderer input cannot become a raw shell command, arbitrary filesystem path, Keychain query, or process invocation.
- Every state-changing command still enters the Runtime protocol with protocol version, authenticated token, `SurfaceClientRef`, idempotency key, and exact expected event sequence (Wave 1 rules unchanged).

## 3. Closed panel types (ten, from program design §4.2)

1. Agent Thread
2. Plan and Tasks
3. Files
4. Diff
5. Terminal
6. Chrome Live
7. Embedded Web
8. Gmail
9. Calendar
10. Evidence and Approval

Panels can move, resize, focus, close, and persist in named layout templates. A panel is a typed Surface consumer; it cannot call native capabilities, Google APIs, Chrome automation, shell commands, or Worker endpoints directly. Panels whose real integration is Wave 3 (Chrome Live, Embedded Web, Gmail, Calendar) ship in Wave 2 only as closed panel shells rendering Surface state, with no external connectivity.

## 4. Wave 2 sub-slicing

Wave 2 is too large for one plan. It is split into independently testable slices, each with its own bounded plan:

- **Wave 2a — Shell, supervision, custody, minimal Canvas (first plan):** Tauri shell scaffold; daemon supervision (spawn/health/restart); Keychain provider-key custody per ADR-0058 with env fallback; renderer with Workspace Canvas frame + Agent Thread, Evidence and Approval, and Files (read-only) panels; one bounded protocol read addition — `GET /v1/surface/tasks/{task_id}/files` returning a bounded workspace file listing (path, size, mtime; no content without a task capability); narrow IPC bridge; arm64 `.app` dev artifact.
  - Exit gate: clean arm64 Mac launch (no manual Python start) -> configure a provider through the shell (Keychain custody) -> daemon health ok and the daemon resolves the provider key from the shell-injected environment -> a Task created in the renderer (or continued from the CLI) is visible in Agent Thread and Evidence/Approval with the same identity/sequence the CLI sees -> quit and relaunch recovers the same Task and history -> restart of a killed daemon is supervised automatically.
- **Wave 2b — remaining panels and layouts:** Plan and Tasks, Diff, Terminal, panel layout templates, pane management; remaining panels as closed shells (Chrome Live, Embedded Web, Gmail, Calendar) rendering Surface state.
- **Wave 2c — native integration depth:** folder authorization flow, tray menu depth, notifications, embedded WebView isolation profile, `Ask` posture projection, `Observe` posture projection.

Slices 2b/2c are NOT authorized by this spec's first plan; they get their own plans after 2a passes its gate.

## 5. Security and privacy invariants (binding)

1. Provider keys live in macOS Keychain (ADR-0058) or the shell-injected environment; never stored or read back to the renderer (except the write-only inbound configuration path), never in the descriptor, SQLite, logs, tests, or repo.
2. The renderer webview never stores the bearer token in webview-local storage; the token is held by the Rust layer and injected into Surface client requests. The provider key value may cross IPC only inbound for one-time configuration and is never read back, logged, or stored in webview storage.
3. The IPC bridge rejects any request that is not an allowlisted daemon-lifecycle or custody call (status plus write-only set/clear).
4. External content (pages, emails, docs) is untrusted data and cannot alter Mandate, permission ceiling, policy, or approval requirements.
5. No live provider requests, Google APIs, Chrome automation, shell commands, or Worker endpoints are invoked by panels.
6. C7 remains non-writable and non-bypassable; uncertain effects fail closed; proposer/outcome acceptor separation unchanged.

## 6. Deliverable identity and branch

- New worktree from Wave 1 head `ed75c28a` (reconciled exact head), suggested branch `codex/native-surface-wave2a-macos-shell-20260812`.
- No push, merge, release, signing, notarization, or current-state completion claim without explicit authorization.

## 7. Claims ceiling

Wave 2 establishes only the bounded local macOS shell + Canvas capability claims above. It does NOT establish: release, daily usability, signing/notarization, enterprise deployment, Google/Chrome integrations, cloud sync, Workers, autonomy, or general intelligence.
