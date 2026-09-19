# cli-ts — TS + OpenTUI full-screen surface-protocol client (spike)

Goal-mode charter queue A#1 spike (D1 ACCEPT 2026-09-11): prove a TypeScript
client can drive the **existing** surface protocol v1.1 end to end with
the frozen E1 semantics — subscription-first, begin-turn reservation, live
CHUNK frames (typewriter), explicit GAP honesty, digest-bound approvals,
mode switching — while the Python governance kernel stays untouched.

The view is the full-screen OpenTUI client (`src/opentui/`). The earlier Ink
client was retired on 2026-09-17 once the full-screen view reached parity; see
`docs/product/TUI-INK-RETIREMENT-PREP-2026-09-17.md` for the record.

## Quick start (fresh checkout)

Prerequisites: [Bun](https://bun.sh/) ≥ 1.4 (the CLI's runtime) and
[uv](https://docs.astral.sh/uv/) (the daemon is the Python governance kernel;
`uv run` resolves its environment from the repo root `pyproject.toml`).

The interactive view needs a runtime with native FFI: **Bun**, or Node ≥ 26 with
`--experimental-ffi` (`@opentui/core` declares `engines: { bun: ">=1.3.0",
node: ">=26.4.0" }`). View-free commands (`--version`, `doctor`, `daemon`,
`provider`, `session`, headless `-p`) work on any runtime, because the view is
imported lazily.

```bash
cd apps/cli-ts
npm install

# terminal 1 — hermetic daemon (scripted provider, no network/credentials).
# Writes a private descriptor (0600) to ~/.agent-os/runtime.json by default.
npm run dev:daemon

# terminal 2 — interactive full-screen TUI (loads the default descriptor)
npm run dev
```

Inside the TUI: type a message and press Enter to stream a turn; `/help`
lists commands (`/mode`, `/files`, `/task`, `/trace`, `/goal`, `/theme`, `/vim`,
`/keys`, `/find`, `/export`, `/queue`, `/doctor`, `/retry`, `/edit`, `/clear`,
`/resume`).
`/trace [turn-id]` projects the durable event log of the last turn (or of the
turn named) as spans: the turn, each recorded model call, each policy verdict and
decision, each approval and each capability dispatch, with the record kind that
opened and closed it and the id that links it to the turn. It carries no prompt,
completion or tool argument text, and a turn the log never closed — or any other
hole in the evidence — is printed as a `gap` line instead of being closed up. The
same projection is served as JSON by
`GET /v1/surface/sessions/{session_id}/trace`.
Messages sent while a turn is in flight are queued (shown in the footer) and
run automatically when the turn ends; `/queue clear` discards them.
`/goal <objective>` sets a persistent session objective (shown in the footer
and prefixed onto every subsequent turn); `/goal clear` unsets it. `/theme`,
`/mode` and `/resume` with no argument open an interactive picker
(↑/↓ move, Enter select, 1-9 quick pick, Esc cancel); `/doctor` runs the
read-only self-check in the transcript; `/retry` re-sends the last message
and `/edit` loads it into the composer. `@` completes workspace file paths
(Tab inserts). **`/resume <session-id>|<n>` attaches to a session and, when the
kernel reports that session's Run `PAUSED`, resumes it** — it sends the real
`POST /v1/surface/sessions/{id}/resume` (the same command as
`noem session resume <session-id>`), then renders the status the kernel reads
back; a rejected resume is reported as `resume FAILED` and is never shown as
applied. It cannot approve, deny, widen a policy ceiling or write C7 state: a
resume only re-permits work the operator had already authorised.
Typing `/`
opens a filterable command palette (↑/↓ select, Tab complete, Enter run,
Esc dismiss); ↑/↓ recall input history, Ctrl-R reverse-searches it.
`y`/`n` answer approval cards; Esc issues a correction during a turn
(Ctrl-C exits); **Ctrl-X stops the running turn** — it sends the real session
pause (`POST /v1/surface/sessions/{id}/pause`, the same command as
`noem session pause <session-id>`), reports "stop requested", shows its own
`stopping…` state until the durable turn record ends the turn, and leaves the
session PAUSED — while the Run is PAUSED the kernel refuses every new turn, so
the stop is not a dead end: resume it in this terminal with
`/resume <session-id>` (or `noem session resume <session-id>` from a shell),
and the durable turn record names both;
Ctrl-L clears the view. `/vim`

enables a vim keymap (Esc → normal; `i`/`a` insert; `h j k l 0 $ w b e x`,
and `dd`/`dw`/`cw` operators). Tab switches the focused panel and PgUp/PgDn
scroll it. Ctrl-X outranks every layer (vim normal mode, an open picker,
Ctrl-R, an open palette, a pending approval), so a stop never depends on what
is on screen.

If the local runtime goes away mid-session, the read commands (`/task`,
`/files`, `/doctor`) report the failure on the transcript and the app keeps
running; a restarted runtime is not re-attached automatically (the descriptor
carries a new port and token), so restart `noem` to talk to it.

The key/command surface above is asserted where it can be: unit tests for the
key resolver (`test/opentui-viewkeys.test.ts`, `test/opentui-vim.test.ts`) and
real-pty checks for the integration (`scripts/pty_*.py`, see Verify).

### Local state & notifications

Input history, theme and `/goal` persist to `~/.agent-os/cli-ts-state.json`
(0600; it stores whatever you typed verbatim, so treat it as sensitive and
don't paste secrets you don't want retained). Override the path with
`AGENT_OS_CLI_STATE`. A terminal
bell rings on approval-needed and turn completion/failure (`AGENT_OS_BELL=0`
disables it); set `AGENT_OS_NOTIFY=osc` for an OSC-9 desktop notification
where the terminal supports it.

## Verify (one command, fully hermetic)

```bash
npm run e2e        # doctor → smoke full → headless -p json → daemon restart
                   # resume → doctor-must-fail → pty smoke (3 phases)
```

`npm test` runs the 273 unit tests (a count that goes stale every time one is
added — re-measure with `npm test` rather than trusting this line);
`npm run build` type-checks and emits `dist` (it is the release build — a
release also wants `npm run compile`).

Targeted real-pty checks (each boots its own hermetic daemon):

```bash
npm run check:entry      # the unified entry: node subcommands, node FFI advice, bun TUI
npm run check:home       # the home panel owns the first frame
npm run check:search     # Ctrl-R reverse search + multiline composer
npm run check:highlight  # fenced-code colouring (headless + pty)
npm run check:stop       # Ctrl-X stops a mid-turn run (real pause; honest stopping state)
npm run check:resume     # the stop is not a dead end: /resume un-pauses it in-session
npm run check:deny       # a rule DENY renders as its own card in a real frame
npm run check:runtime-lost  # the runtime dying mid-session is reported, not fatal
```

## Upgrade path (`noem self-update`)

An installed single-file binary can replace itself, but only when an operator
explicitly names where to get the bytes and only after it verifies them:

```bash
noem self-update --status                                   # read-only: version, path, pending journal
noem self-update --source file:///srv/noem --check          # manifest + version only; downloads nothing
noem self-update --source https://example.invalid/noem      # verify, then replace, with rollback
```

The source is a directory holding `manifest.json` and the artifact:

```json
{"schema":"noem-self-update-manifest/1","version":"0.2.0",
 "artifacts":{"darwin-arm64":{"file":"noem-0.2.0-darwin-arm64","sha256":"<64 hex>","bytes":76691442}}}
```

There is **no default channel**: publishing is a founder-reserved decision, so
nothing is contacted unless `--source` (or `AGENT_OS_SELF_UPDATE_SOURCE`) names
a source, and there is no background check or telemetry. Refusals are typed and
exit non-zero: `no_source_configured`, `source_invalid`, `source_unreachable`,
`manifest_invalid`, `checksum_missing`, `checksum_mismatch`,
`artifact_not_executable`, `downgrade_refused`, `target_unresolved`,
`replace_failed`, `rolled_back`, `rollback_failed`,
`interrupted_update_pending`.

Verification chain, in order: scheme → manifest shape + a checksum for this
platform → strictly-newer version → program-image shape → SHA-256 of the
**staged bytes read back from disk** → copy the old bytes aside → atomic
`rename` over the program file → run the **installed path** in a fresh process
and require the published `--version`. Any failure after the rename restores
the previous bytes, which are verified again before the command reports.

Honest limits: the checksum proves integrity, not authenticity — a source that
serves the manifest can serve any artifact with a matching checksum, so a
forged newer version string is not detectable until a signature exists (no
signing utility exists in this repository, and no signature is claimed). A
source publishing a genuinely older version IS refused. When a replacement is
rejected because it did not run, the `rejection` field says which way, and its
`spawn_error` / `exit_nonzero` split is **platform-dependent**, not a product
promise: a file the kernel will not execute fails the spawn on macOS (its
spawn path performs no shell fallback), while Linux's `execvp` retries it as
`/bin/sh <file>`, so it does start, as a shell, and exits non-zero. Both roll
back; treat `rolled_back` as the contract and `rejection` as the host's wording.

This replaces a program file and nothing else: C7, permission modes, approval,
policy, evidence and `ActionReceipt`/`ReceiptStatus` are untouched, and the
command is a shell entry point with no session, slash-command or turn input.

## Other entry points

```bash
npm run doctor                      # read-only probes: descriptor/auth/protocol
npm run dev -- -p "hello"           # headless one-shot (exit codes 0/1/2/3/4; 4 = an action was refused in THIS turn)
npm run dev -- -p "hello" --output-format json
npm run smoke:pty                   # real-pty TUI regression (3 phases)
npm run compile                     # single-file binary (bun build --compile)
npm run live                        # real provider evidence (needs KIMI_*)
npm run live:pty                    # real provider multi-turn in a real pty
```

## Layout

- `src/contracts.ts` — zod mirrors of `agent_os_contracts/surface.py` (v1.1, frozen)
- `src/client.ts` — `SurfaceClient` port of `apps/cli/surface_client.py`
- `src/controller.ts` — renderer-neutral state machine; frozen-semantics mapping table in the header comment
- `src/cli.tsx` — the unified entry: every subcommand plus the interactive TUI
  (the view is a **lazy** import so view-free paths stay runtime-independent)
- `src/self-update.ts` — the upgrade mechanism (typed statuses, SHA-256
  verification, atomic replace, rollback, interruption journal); the header
  comment is the contract, including what it deliberately does NOT touch
- `src/self-update-command.ts` — the `noem self-update` shell surface (exit
  codes 0/1/2); dispatched before daemon resolution so it cannot wake a kernel
- `src/opentui/` — the full-screen view (`app.tsx`), its entry (`mount.tsx`),
  panels, overlays, key routing (`viewkeys.ts`), theme colours and code
  highlighting (`code-highlight.ts`)
- `src/home.ts` — renderer-neutral home-panel content model (survives view changes)
- `src/highlight.ts` — language/extension map + cli-highlight wrapper. Named after
  the retired Ink path but NOT Ink-only: `src/opentui/code-highlight.ts` depends
  on `EXTENSION_LANGUAGE`, so do not delete it with other legacy files.
- `scripts/dev_daemon.py` — hermetic daemon with scripted streaming provider (no network)
- `scripts/stop_daemon.py` — the same, with the first provider call held open so a
  mid-turn stop is reachable from a terminal (no default descriptor path: it can
  never write the operator's `~/.agent-os`)
- `scripts/resume_daemon.py` — the same hold-open daemon with a second scripted
  turn, so `pty_resume_check.py` can prove a REAL turn runs after the resume
  (not merely that a status string changed)
- `scripts/deny_daemon.py` — the same, with a durable operator DENY rule seeded
  before the session opens, so one scripted turn produces a rule refusal and an
  ordinary tool failure in the same transcript
- `scripts/smoke.ts` — headless end-to-end walk of the frozen order (exit 1 on violation)
- `scripts/pty_*.py` — real-pty checks: render/typing/Enter/narrow+resize/approval,
  theme, highlighting, home frame, search, unified entry, Ctrl-X stop, Ctrl-X
  stop → in-session `/resume`, DENY card
- `scripts/frame_reader.py` — terminal emulator used by every pty check to
  reconstruct the screen (assert what a human sees, not stripped bytes)
- `scripts/compile.ts` — `bun build --compile` wrapper (bakes the version in)
- `scripts/live_evidence.py`, `scripts/live_multiturn_pty.py` — opt-in real-provider evidence
- `scripts/e2e.sh` — one-command full-chain regression (hermetic)
- `test/` — unit tests incl. bypass-detection (a controller skipping the
  frozen semantics fails here). `test/fixtures/ink-home-baseline.ts` is a frozen
  record of the retired Ink home panel; the drift guard still compares against it.

## Boundaries

Protocol client only: never mints turn ids, never holds governance state,
treats transient frames as display state, resubscribes on 410 (dead
generation) and re-syncs from durable snapshots. Approvals are human-only
(`y`/`n` in the TUI); permission modes are operator-only (`/mode`). No claim
beyond SPIKE.
