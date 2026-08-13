# Agent OS Native Surface Wave 2b — Remaining Panels and Layout Templates

- Status: Authorized route (founder decision 2026-08-13: "全部推进"); this plan is the bounded implementation artifact for Wave 2b.
- Parent: `docs/superpowers/specs/2026-08-11-agent-os-native-surface-macos-shell-wave2-design.md` (§4, slice 2b)
- Predecessor: Wave 2a approved at `dbf5ab11` on `codex/native-surface-wave2a-macos-shell-20260812`

## Scope

Wave 2b adds the remaining Canvas surface on top of the Wave 2a shell:

1. **Plan and Tasks panel** — render the Task/plan state for the active task from Surface queries (task status, run status, outcome, receipts count) via a bounded read projection; no writes beyond typed commands.
2. **Diff panel** — render persisted action/effect diffs for the active task from the Task event stream (ACTION_PROPOSED / receipts); read-only.
3. **Terminal panel** — render governed shell-action events for the active task from the event stream (read-only; the panel cannot invoke shell commands itself — only typed commands may, per spec §4.2).
4. **Panel layout templates** — named templates (move/resize/focus/close/persist) as renderer state; a layout is a pure data structure with a bounded schema; templates persist in webview memory only in 2b (durable layout sync is cloud/Worker scope).
5. **Closed shells** for Chrome Live, Embedded Web, Gmail, Calendar — panels that render Surface state (session/status) with NO external connectivity; their real integrations remain Wave 3.

## Bounded semantics (binding)

- Panels are typed Surface consumers; none can call native capabilities, Google APIs, Chrome automation, shell commands, or Worker endpoints directly.
- All writes go through the versioned Surface protocol (token, protocol version, idempotency, sequence) — no new authority.
- Layout templates are renderer-local data; no durable layout store is added in 2b.
- The Terminal panel renders events only; the Wave 1 `workspace.shell` typed command remains the only shell path (via approval).
- No new native plugin dependencies for 2b.

## Tasks

- [ ] T1: Layout template engine (pure TS): `LayoutTemplate { id, name, panels: PanelPlacement[] }`, `PanelPlacement { panel_id (closed enum of 10), x, y, w, h, focused }`; validation rejects unknown panel ids/overlaps/negative sizes; Vitest tests (RED first).
- [ ] T2: Plan and Tasks panel logic: `taskOverview(taskId)` reads a bounded Surface projection (task status, run status, outcome state, receipt count) — add `GET /v1/surface/tasks/{id}/overview` (Python route, auth+scope+ownership, test-first) returning a closed schema.
- [ ] T3: Diff panel logic: `recentDiffs(taskId)` reads ACTION_PROPOSED/RECEIPT events from the resumable SSE cursor and renders bounded diff summaries (path + old/new excerpt, truncated); Vitest + conformance with the Python client fixtures.
- [ ] T4: Terminal panel logic: `terminalEvents(taskId)` filters shell action events from the event stream; read-only; Vitest.
- [ ] T5: Closed shells (Chrome Live, Embedded Web, Gmail, Calendar): one shared `ClosedShellPanel` rendering "integration pending (Wave 3)" + Surface session status; no external calls (test asserts zero fetch/invoke).
- [ ] T6: Wire all panels into the Canvas (App.tsx) with a layout template selector; Vitest for the wiring logic; build green.
- [ ] T7: Full verification: Python (no regression, 1802/18/1 baseline), ruff, pyright, cargo, npm, git diff --check; CURRENT_STATE update; independent exact-head review; commit evidence.

## Exit gate (2b)

The Canvas renders all ten panel types (6 functional in 2a/2b + 4 closed shells), layout templates apply/validate, and every panel remains a typed Surface consumer with zero direct native/Google/Chrome/shell/Worker calls.

## Claim ceiling

No push/merge/release/signing/notarization/daily-usability/Google/Chrome/cloud/Worker claim. Durable layout sync and real Chrome/Google integrations remain Wave 3/4.
