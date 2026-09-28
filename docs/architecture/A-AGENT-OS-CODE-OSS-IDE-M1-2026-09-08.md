# Architecture Brief — Agent OS on Code-OSS

> Goal Card: `docs/product/GC-AGENT-OS-CODE-OSS-IDE-M1-2026-09-08.md`
> Context Pack: `docs/product/CP-AGENT-OS-CODE-OSS-IDE-M1-2026-09-08.md`

## 1. Product topology

```text
Agent OS.app (Code-OSS distribution)
├── Code-OSS Workbench
│   ├── editor / files / search / SCM / terminal / debug / extensions
│   └── Command Center: one contextual Agent ↗ or IDE ↗ action
├── Built-in extension: agent-os
│   ├── Agent Surface webview editor
│   ├── workspace/editor/diagnostic/Git context adapter
│   └── Surface Runtime client
└── Local Agent OS Runtime daemon
    ├── Task / Session / Approval / Evidence / Trace
    ├── typed capability broker and C7 boundaries
    └── private 0600 runtime descriptor
```

Agent Surface and IDE Surface are views of the same product and task state. “Agent” is not a selectable worker identity. The Runtime selects skills, tools and internal organs according to the work.

## 1.1 Window-host decision (Cursor/Qoder local implementation study)

The Agent surface is not an IDE Webview and is not a second Tauri application. It is a first-class window type in the Code-OSS host window system.

Local inspection performed on 2026-09-08:

- Qoder IDE 1.29.0 (`/Applications/Qoder IDE.app/Contents/Resources/app/out/main.js`) uses `isAgentsWindow`, `openAgentsWindow`, `foregroundAgentsWindow`, `AgentsWindowSession`, and `environmentMainService.agentsWindowWorkspace`. Its native host opens an Agents workspace through `windowsMainService.open({ forceNewWindow: true })`, then restores/focuses it through the same Code-OSS window lifecycle.
- Cursor 3.19.13 (`/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js`) uses a Glass/Agents window layer with `openGlassWindow`, `cursor.toggleAgentWindowIDEUnification`, `workbench.action.toggleAgents`, `agentLayoutService`, and persisted `default` / `agentWindow` / `lastUsedWindows` restoration choices. It routes window creation and focus through `nativeHostService` and `hostService`, rather than an extension-owned standalone window.

These observations establish the product and host boundary, not a claim that the proprietary implementations are source-identical. Agent OS must reuse Code-OSS `WindowsMainService`/`NativeHostMainService` and add an Agent OS window kind, session restoration and layout service. A direct `new BrowserWindow(...)` in an extension, a Tauri Agent OS Shell, or an IDE Webview is out of scope for the product path.

## 2. Upstream strategy

Track upstream by an exact lock file containing repository, tag and commit. `bootstrap.mjs` creates a disposable fork work directory, verifies exact HEAD, copies the built-in extension, and applies an ordered patch series when patches exist. Product code and patches are tracked; generated upstream files are ignored.

## 3. Window and layout switching

The Code-OSS host owns `openAgentOSWindow`, `focusAgentOSWindow`, `openEditorWindow` and `toggleAgentOSIDEUnification`. The top-right action is one contextual destination action: it reads the current native window kind and changes between `Agent` and `IDE`; it does not render two competing buttons or a segmented control. Agent and IDE windows may remain open simultaneously. The host persists the last-used window policy and restores each window's geometry, workspace and active task.

The Agent window has an Agent-first layout service; the IDE window retains the Code-OSS editor layout. Both consume the same typed task/session store and Runtime connection. The built-in extension is responsible for commands, context projection and Runtime calls, but it must not own native window creation.

## 4. Runtime boundary

The extension reads the local descriptor only in the extension host. The Webview never receives the bearer token. Webview messages are typed intents; the extension performs authenticated requests and returns redacted projections. Descriptor validation rejects symlinks, non-files, group/world-readable modes, non-loopback hosts, invalid ports and protocol versions other than `1.0`.

## 5. Failure behavior

- Missing Runtime: show “启动 Agent OS Runtime” with a retry action; IDE remains usable.
- Invalid descriptor: refuse connection and show a bounded diagnostic without secret content.
- 401: mark descriptor stale and require Runtime restart.
- protocol mismatch: disable Agent execution while preserving IDE use.
- Webview reload: restore current session id from workspace state, then fetch a fresh snapshot.
- workspace absent: Agent remains enterable; Coding work can request a workspace, then the host opens/focuses an IDE window through the native window service.

## 6. Verification and claim boundary

Tests must fail if both Surface buttons can be visible, if the Webview receives a token, if an unsafe descriptor is accepted, or if Runtime errors are rendered with secrets. M1 establishes a branch-contained developer build, not a signed or released application.
