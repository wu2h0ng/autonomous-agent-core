# Agent OS Code-OSS IDE Design

> Status: APPROVED_DIRECTION / IMPLEMENTATION_ACTIVE
> Goal Card: `docs/product/GC-AGENT-OS-CODE-OSS-IDE-M1-2026-09-08.md`
> Architecture: `docs/architecture/A-AGENT-OS-CODE-OSS-IDE-M1-2026-09-08.md`

## Product decision

Agent OS remains one product with two native Code-OSS window kinds. Agent is the general work window; IDE is the coding window. A single destination action in the top-right host chrome focuses or creates the other window. Agent and IDE can be open simultaneously and share task/session/workspace state. Ask/Work belongs inside Agent interaction semantics and is not a second application-level switch. Internal agents, models and skills are selected by the Runtime as organs; users describe outcomes and may explicitly invoke a skill, but do not assign an “Agent identity” before work.

## Implementation decision

Use Code-OSS 1.106.3 as the editor distribution. Track the exact upstream commit and maintain Agent OS as a built-in extension plus the smallest possible Workbench and native-window patch series. Reuse `WindowsMainService` and `NativeHostMainService` for the Agent window; add an Agent OS window kind, Agent OS layout/session services and typed host IPC. Keep the existing provider-neutral Runtime, approval and trace boundaries. Do not implement the product window model in Tauri, an extension-owned `BrowserWindow`, or an IDE Webview.

## Maturity sequence

1. Reproducible Code-OSS checkout and built-in extension loading.
2. Native Agent/IDE window creation, focus, restoration and Runtime health/session/turn flow.
3. Workspace context adapters: active file, selection, diagnostics, Git and terminal.
4. Reviewable change flow: proposed edits, native diff editor, accept/reject/revert.
5. Task recovery, approvals, conflict projection and event streaming.
6. packaging, update channel, signing/notarization and migration from Tauri.

Each stage must remain a usable Code-OSS editor even when Agent Runtime is unavailable.
