# Agent OS Native Surface Wave 2c — Native Depth and Postures

- Status: Authorized route (founder decision 2026-08-13: "全部推进"); this plan is the bounded implementation artifact for Wave 2c.
- Parent: `docs/superpowers/specs/2026-08-11-agent-os-native-surface-macos-shell-wave2-design.md` (§4, slice 2c)
- Predecessor: Wave 2b approved at `b48b4e4e` on `codex/native-surface-wave2a-macos-shell-20260812`

## Scope

1. **Tray menu depth** — a real macOS tray with a menu: Show window, daemon start/stop/status, Quit. Pure Tauri v2 tray API (no plugin).
2. **Notifications** — `tauri-plugin-notification`: notify on pending approval and on supervised daemon restart. Permission request handled by the plugin; no custom notification center code.
3. **Folder authorization flow** — `tauri-plugin-dialog` native folder picker via a new allowlisted IPC command `folder:request`; the renderer stores an authorized-folder state and a `folder:status` command returns the granted path (the daemon workspace, as in 2a). The picker returns a path; binding that grant into daemon capability policy is explicitly successor scope (2c grants folder authorization STATE, not new daemon permissions).
4. **Embedded WebView isolation** — recorded as successor: the Embedded Web panel and its isolated WebView profile remain Wave 3 (the panel is a closed shell in 2b); 2c does not add a second webview.
5. **Ask posture** — renderer composer mode: Ask = question mode with no external effect by default (read-only), with an explicit "upgrade to Work" action that opens a Task via the protocol. Pure renderer posture + protocol `open_session` (already exists).
6. **Observe posture** — renderer projection of unfinished commitments, risks, and HelpRequests from the task event stream (HelpRequest events exist in the core event vocabulary); read-only.

## Bounded semantics (binding)

- Tray menu items call the same allowlisted IPC commands (daemon start/stop/status); tray cannot bypass the allowlist.
- Notifications never carry provider keys, tokens, or message content beyond a bounded summary (capability id / event kind).
- Folder authorization grants renderer state only; no new daemon permission is added (existing workspace capability policy unchanged; C7 untouched).
- Ask posture makes no external effect; "upgrade to Work" only calls the existing `open_session` protocol command.
- Observe posture is read-only event projection.
- No new daemon-side surface; no push/merge/release/signing/notarization/daily-usability claim.

## Tasks

- [ ] T1: Tray menu (Show / daemon start/stop/status / Quit) wired to the allowlisted commands; Rust unit test for menu-command routing; build green.
- [ ] T2: `tauri-plugin-dialog` + `tauri-plugin-notification` deps; allowlisted `folder:request` and `folder:status` IPC; notification helper (approval pending, daemon restart) with bounded summary; Rust unit tests for notification payload bounds.
- [ ] T3: Ask posture renderer logic: `AskMode` composer state machine (ask → upgrade to work → open_session via protocol); Vitest: upgrade calls openSession exactly once with no other effect.
- [ ] T4: Observe posture renderer logic: `observeHelpRequests(events)` projects HelpRequest events; Vitest; wire into the Canvas as an Observe strip.
- [ ] T5: Folder authorization renderer state (requested/granted), wired to folder:request/status; Vitest for the state machine; CORS/allowlist regression.
- [ ] T6: Full verification: renderer build+tests, Python full (1803/18/1 baseline), ruff/pyright/cargo, git diff --check; CURRENT_STATE update; independent exact-head review; commit evidence.

## Exit gate (2c)

Tray controls the daemon without bypassing the allowlist; notifications fire on approval-pending and daemon restart with bounded payloads; Ask never makes an external effect and upgrades only through the protocol; Observe projects HelpRequests read-only; folder authorization is renderer state from the native picker with no daemon permission change.

## Claim ceiling

No push/merge/release/signing/notarization/daily-usability/Google/Chrome/cloud/Worker claim. Embedded WebView isolation and real Chrome/Google remain Wave 3.
