# Agent OS Code-OSS IDE Implementation Plan

> **For agentic workers:** execute task-by-task with TDD and exact upstream verification.

**Goal:** Deliver a mature Agent OS coding Surface on a reproducible Code-OSS fork while preserving the existing governed Runtime.

**Architecture:** Code-OSS owns IDE primitives. A built-in Agent OS extension owns Surface switching and protocol adaptation. The local Runtime remains the only task/approval/evidence authority.

**Tech Stack:** Code-OSS 1.106.3, Electron, TypeScript, VS Code Extension API, Agent OS Surface Protocol 1.0, Python Runtime daemon.

**Spec:** `docs/superpowers/specs/2026-09-08-agent-os-code-oss-ide-design.md`

## Global constraints

- Exact upstream: tag `1.106.3`, commit `bf9252a2fb45be6893dd8870c0bf37e2e1766d61`.
- Never send the Runtime bearer token into a Webview.
- Exactly one of `Agent ↗` and `IDE ↗` is visible.
- IDE remains usable without Runtime.
- No Cursor/Qoder proprietary code.
- No push, merge or release under this plan.

### Task 1: Reproducible upstream workspace

- [x] Add exact upstream lock.
- [x] Add bootstrap and verification scripts.
- [x] Ignore generated checkout.
- [ ] Run bootstrap and mechanically verify the installed built-in extension.

### Task 2: Surface switching and Runtime boundary

- [x] Write manifest test for mutually exclusive Command Center actions.
- [x] Implement Agent and IDE commands with one context key.
- [x] Write descriptor validation and secret-redaction tests.
- [x] Implement local Runtime client and Agent Webview without token exposure.
- [ ] Type-check, test and bundle extension.
- [ ] Launch Code-OSS Extension Host and verify actual placement and switching.

### Task 3: Real workspace context

- [ ] Add typed projection for active editor URI, language, selection and visible diagnostics.
- [ ] Add Git repository and diff summary adapters through public Extension APIs.
- [ ] Attach explicit context only when the user references it or the Runtime requests the capability.
- [ ] Verify workspace-trust and excluded-file failure paths.

### Task 4: Reviewable edits

- [ ] Map Runtime patch proposals to `WorkspaceEdit` without bypassing approval.
- [ ] Open native Code-OSS diff editors for proposed changes.
- [ ] Implement accept, reject and rollback receipts bound to exact digests.
- [ ] Run repository tests through typed terminal/task capabilities and stream output.

### Task 5: Durable work and collaboration

- [ ] Resume current Task/Session after Webview and application restart.
- [ ] Render pending approvals and collaboration conflicts from Runtime events.
- [ ] Add resumable SSE with sequence-gap recovery.
- [ ] Verify two-window conflict and interruption recovery.

### Task 6: Product distribution

- [ ] Apply Agent OS branding without Microsoft trademarks or Marketplace dependencies.
- [ ] Add Open VSX-compatible extension registry policy.
- [ ] Build unsigned arm64 developer `.app`.
- [ ] Run IDE smoke suite, Runtime E2E and restart recovery.
- [ ] Prepare independent review and separate signing/release gate.

