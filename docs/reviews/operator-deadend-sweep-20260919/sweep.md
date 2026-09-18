# Operator dead-end sweep — 2026-09-18/19

Worktree `autonomous-agent-core/.worktrees/wt-uxe`, branch
`codex/operator-deadend-sweep-20260918`, base `origin/main` = `03ac66b5`.

Three operator dead ends (a DENY with no feedback, an ineffective
`session pause`, a resume that never un-paused) had been found *by accident*.
This is the sweep of that whole class: enumerate the operator surface, ask the
four questions for every item, verify against a real daemon and a real pty, fix
what is found, and record what came back clean.

Method, evidence identifiers, mutations and gate numbers: `verification.md` in
this directory.

Track: Product Track (terminal surface usability of Agent OS), plus one
fail-closed-preserving kernel record fix. Claim class: **product runtime** —
nothing here is research evidence, an autonomy claim or a release.

## 1. Surface inventory (enumerated from the code)

### TUI slash commands — `apps/cli-ts/src/commands.ts:19` (single registry; the
help transcript, the palette and the dispatch all read it)
`/exit` `/status` `/cost` `/provider [set|clear]` `/mode [MODE]` `/resume
<id|n>` `/files [PREFIX]` `/task` `/goal [obj|clear]` `/theme [name|next]`
`/export [path]` `/keys` `/find <q>` `/vim` `/doctor` `/retry` `/edit` `/clear`
`/queue [clear]` `/help` — plus the unknown-command fallback
(`controller.ts:565`).

### Key bindings, by mode — `src/keys.ts`, `src/opentui/viewkeys.ts`,
`src/opentui/vim.ts`, `src/composer.ts`

| mode | keys |
| --- | --- |
| global | Esc (correction while streaming/stalled, consumed otherwise), Ctrl-C (interrupt/exit), Ctrl-L (clear view) |
| approval | `y` approve, `n` reject, every other key ignored |
| reverse search | Ctrl-R open; ↑/↓, Enter (pick), Esc (cancel); Tab/PgUp/PgDn and Ctrl-R/Ctrl-G swallowed; printable text edits the query |
| command palette | ↑/↓, Tab (complete), Enter (run); printable keys fall through to the composer |
| `@` mention | Tab (complete path) |
| external editor | Ctrl-G |
| panel chrome | Tab (next panel), PgUp/PgDn (scroll) |
| agents panel | ctrl+↑/↓ and ctrl+p/ctrl+n, ↑/↓ (move), Enter (switch session) |
| composer history | ↑/↓ only (see finding F5) |
| vim normal | Esc→normal, `i/a/A/I`, `h j k l 0 $`, `w b e`, `x`, `dd/dw/d$`, `c`+motion, Enter |
| selector (resume/theme/mode) | ↑/↓, 1-9, Enter, Esc, printable filter, Backspace |
| composer (textarea) | Enter/kpenter submit, Ctrl-J/linefeed newline, Backspace/Delete, Ctrl-D, Ctrl-A/Ctrl-E |

### Session/Run lifecycle an operator can drive

States: `SurfaceSessionStatus` ACTIVE / WAITING_APPROVAL / PAUSED /
CORRECTION_HALTED / CLOSED (`packages/contracts/.../surface.py:37`), projected
from `RunStatus` + the correction authority (`apps/api_server/app.py:2630`).

Operator-drivable transitions and their entry points: open session
(`POST /v1/surface/sessions`, driven by `ensureSession`), attach (`/resume`,
`noem -p --resume`), turn (`POST …/begin-turn` subscription-first), approve/reject
(`POST …/approvals`), permission mode (`POST …/mode`), pause / resume /
correction (`POST …/{pause,resume,correction}` — TUI Esc, `noem session …`),
plus read projections (`GET …/sessions`, `/tasks/{id}/{overview,files,events}`).
CLOSED and PAUSED are not reachable from this base's terminal (see §6).

### Headless flags and exit codes — `apps/cli-ts/src/cli.tsx`,
`src/headless.ts:22`, `src/opentui/panels.ts`

Flags: `-p/--print <prompt>`, `--output-format text|json|stream-json`,
`--descriptor <path>`, `--resume <session-id>`, `--no-daemon` /
`AGENT_OS_NO_AUTOSTART=1`, view flags (`--no-animation`, `--no-panels`,
`--no-agents`), subcommands `doctor` / `daemon` / `provider` / `session`,
`--version|-v`, `--help|-h`.

Exit codes (frozen): `0` turn completed, `1` transport/contract/general error,
`2` awaiting approval, `3` turn ended without `stop_reason: completed`. All four
were re-measured against a real daemon (see §5).

## 2. What was found

Severity is about the operator: **P0** = a state they cannot leave or a
consequence with no visible trace; **P1** = misled or a session they cannot
recover; **P2** = a wrong statement on the surface.

### F1 — P0, FIXED. Esc (the advertised correction key) left the turn uncommitted
in the durable store, and every later turn in that session was then refused for
the rest of its life.

* **The operator sees**: Esc during a turn → `correction issued (operator
  interrupt)`; the next message is refused with `error: a prior turn is still
  uncommitted for this session`. `noem session show` keeps answering
  `"status": "ACTIVE"`.
* **The kernel reports**: `SESSION_TURN_STARTED` for the turn, `CORRECTION_WRITTEN`,
  and **nothing else** — no `PROVIDER_RESPONDED`, no `SESSION_TURN_COMPLETED`,
  no failure event. `surface_has_uncommitted_turn()` stays true, so
  `begin_turn` raises `SurfaceTurnInProgress` before the provider is ever
  started (`packages/os_core/src/agent_os_core/surface_runtime.py:417`). The
  turn thread died on `RunExecutionError("chat provider correction epoch changed
  during invocation")` raised by `_call_provider` (`agent_loop.py:1330`), which
  the worker swallows (`apps/api_server/app.py:2380`).
* **Reproduction**: real pty, `slow` stub provider, one Esc mid-turn — the
  durable event log ends at `SESSION_TURN_STARTED`, and the next message is
  refused forever (`verification.md` §2.1). 100% reproducible (3/3 runs).
* **Root fix** (§3, K1): a correction landing during a provider invocation now
  ends the turn as `correction_halted` — the same frozen stop reason the
  pre-invocation halt path already used. The discarded answer is still discarded
  (asserted: no `PROVIDER_RESPONDED`, no assistant message, no dispatch).

### F2 — P0, FIXED. A vanished runtime + `/task` or `/files` tore the TUI's screen
apart.

* **The operator sees**: the daemon dies (crash/restart/kill); they type `/task`
  to find out what is going on; Bun prints an unhandled-rejection stack **into
  the alternate screen**, over the frame (`Console (Focused)`, `at async …`
  smeared through the layout), and the process may exit 1 (measured separately
  with the same rejection shape outside the TUI).
* **The kernel reports**: nothing to do with the UI — the local runtime is
  simply unreachable.
* **Reproduction**: real pty, kill the daemon under a live session, type `/task`
  then `/files` (`verification.md` §2.2). Regression check:
  `apps/cli-ts/scripts/pty_runtime_lost_check.py`.
* **Cost of the defect**: `/files`, `/task` (and, measured with the fake client,
  a resume-selector pick and `y`/`n` with nothing pending) were all
  fire-and-forget call sites; one client error anywhere on them destroyed the
  operator's screen.

### F3 — P0, FIXED. `y`/`n` with nothing left to decide was an unhandled rejection.

* **The operator sees**: nothing — or a smeared stack, as in F2. The y/n layer
  is chosen from render state, so a second press, or a press that lands while the
  first decision is still in flight, reaches `decide()` with `status !==
  "awaiting_approval"` (or a kernel snapshot with no pending approval), and it
  used to `throw` — into a `void controller.approve()` in `app.tsx:456`.
* **Reproduction**: `verification.md` §2.3 (scripted client; pre-fix the call
  rejects).

### F4 — P0 (kernel hole), reported NOT fixed. **Any** interrupted turn — not just
a correction — leaves a session that reports ACTIVE and refuses everything.

* **The operator sees**: the runtime restarts while a turn is in flight; after
  the restart `noem session show` says `"status": "ACTIVE"`, and every turn is
  refused with `a prior turn is still uncommitted for this session` (exit 1).
* **The kernel reports**: `SESSION_TURN_STARTED` with no completion; the
  designed recovery (`AgentLoop.resume_turn`, fed by
  `projected.resumable_turn_id`) is wired into the loop but has **no caller in
  the app layer** (`apps/api_server/app.py:2149` populates `resumable_turn_ids`
  and nothing ever resumes), and the surface refuses `begin_turn` first, so the
  operator has no route to it.
* **Reproduction**: `verification.md` §2.4 — kill the daemon mid-turn, restart
  it on the same database, `noem -p … --resume <session-id>`.
* **Why it is not fixed here**: recovering or discarding an open durable turn is
  a surface-protocol capability plus an authority question (resume the turn vs
  abandon it, and who may). The sibling slice
  `codex/tui-stop-key-20260918` is already extending the surface control
  commands (`surface.py`, `app.py`); this belongs there, not in a
  half-implementation here. F1 removes the *one* producer of this state that a
  single advertised key could create.

### F5 — P1, PARTLY FIXED. `/keys` advertised keys the composer does not have.

* The card said `↑/↓ or ctrl-p/ctrl-n history`. Measured in a real pty: Ctrl-P on
  a one-line draft recalls nothing (the composer keeps `↑/↓`; ctrl+p/ctrl+n are
  the **agents panel** movement keys, `viewkeys.ts:166`), while Ctrl-A/Ctrl-E do
  work (the textarea handles them). The card now says so.

### F6 — P1, FIXED (reporting half). A correction ends the session, and the
surface did not say so.

* **The operator sees** (before): `correction FAILED`/`correction issued`, then
  on the next message the bare kernel jargon
  `configuration correction epochs changed after seal`, with nothing about what
  happened or what to do. `noem session resume <id>` answered
  `{"status": "CORRECTION_HALTED"}` with **exit 0**.
* **The kernel reports**: session status `CORRECTION_HALTED`
  (`app.py:2638`), and every later pre-turn preflight denies because the sealed
  configuration binds the *original* correction epochs
  (`task_configuration.py:616`).
* **Reproduction**: `verification.md` §2.5/2.6 (real daemon): a correction while
  idle, then a turn → refused; `session resume` → still halted; an out-of-band
  `POST /v1/tasks/{id}/correction/resume` → status back to ACTIVE, **turn still
  refused**; only a new session works.
* **Fixed here**: the TUI now renders the kernel's own status (a halt notice the
  moment the correction's response says `CORRECTION_HALTED`), refuses a turn on
  a halted session *after re-reading durable truth* (so an out-of-band lift is
  honoured, not remembered as a client flag), and `noem session resume` exits
  non-zero with the real status.
* **Not fixed** (see §6): the halt itself. Lifting it needs `resume_correction`
  — an existing, principal-authorised, durable operation reachable today only
  over the admin HTTP route — exposed on the operator surface, or a `/new`
  command. Both are product/authority decisions (and the terminal has no way to
  start a new session in-process), so they are reported, not improvised.

### F7 — P2, FIXED. CLI flags became part of a durable audit reason.

`noem session correct <id> "why" --descriptor /tmp/x.json` recorded
`CORRECTION_WRITTEN.reason = "why --descriptor /tmp/x.json"`, and
`noem session pause <id> --descriptor /tmp/x.json` lost the default reason to the
flag text entirely. The reason is durable evidence; it now excludes the
transport flags.

### F8 — P2, FIXED. The stall notice advised a command that cannot work there.

The typed `stalled` state says the turn's outcome is unknown and used to add
`(try /retry or /status)`. While stalled, `canStartTurn()` is false, so `/retry`
is *queued*, and the queue is only drained by `runTurn`'s finally / `decide` /
`interrupt` — so the operator got `queued (#1) — will send when the current turn
ends` for a turn that was never going to end. The notice now names Esc (which
does clear the stall) and says `/retry` only queues.

### Confirmed by reading, NOT fixed (owned elsewhere or needing a gate)

* `--output-format json` reports `success`/`is_error:false` for a turn whose tool
  run failed (`headless.ts` summarises the turn, not the tools). Known
  (parity map, PR #88); a Python/TS cooperation change, out of this sweep.
* `formatToolDetail` (`controller.ts:231`) still has no view caller.
* Delta replay after a mid-stream retry, and a truncated stream counted as a
  successful turn: reported by PR #89, being fixed by
  `codex/delta-replay-and-truncation-20260918`.
* Unknown flags/subcommands are accepted silently (`noem sessio show` mounts the
  TUI; an unknown flag is ignored): validating argv needs to cover the view's own
  flags (`--no-panels`, `--no-animation`, `--no-agents`) — a small design change,
  not a one-liner, so it is reported rather than half-done.
* A restarted daemon is not re-attached by a running TUI (the descriptor carries
  a new port and bearer token). Rebinding a live session to a new endpoint is a
  trust decision; the surface now at least says the runtime is unreachable.
* `noem session pause` cannot take effect on this base (kernel 409 `cannot move
  run from QUEUED to PAUSED`), reported truthfully with exit 1. Fixed by
  `codex/tui-stop-key-20260918` (not in this base).

## 3. Fixes (file:line → test → mutation)

| # | fix | location | test | mutation that reddens it |
| --- | --- | --- | --- | --- |
| K1 | a correction landing during the provider invocation ends the turn as `correction_halted` instead of leaving it open | `packages/os_core/src/agent_os_core/errors.py:169` (`ProviderCorrectionHalt`), `agent_loop.py:887` (catch), `agent_loop.py:1330,1337` (typed raise) | `tests/product/test_surface_correction_during_invocation.py` (3 cases) | remove the catch → `ProviderCorrectionHalt` propagates → 3/3 fail |
| C1 | `/files` and `/task` report a failed read instead of rejecting | `apps/cli-ts/src/controller.ts:987`, `:1014` | `controller.test.ts` "a failing read command is reported…" | delete both try/catch → test fails; real pty check also fails with the stack smeared on the frame |
| C2 | `approve()`/`reject()` report instead of rejecting, and follow the kernel when the approval is gone | `controller.ts:1552-1650` (`decide`) | 3 cases in `controller.test.ts` | restore `throw new Error("no pending approval")` → 1 fail |
| C3 | process-level `unhandledRejection` backstop (report + survive) + `TuiController.notify` | `apps/cli-ts/src/cli.tsx:40-46,194`, `controller.ts:412` | measured in a real pty (`/resume s:does-not-exist` → notice on the transcript, app alive) | — (measured, not unit-testable; see verification §2.7) |
| C4 | a correction renders the kernel's `CORRECTION_HALTED` consequence; a turn on a halted session is named (after a fresh read) and not sent | `controller.ts:72` (`HALT_NOTICE`), `:1713` (correction), `:1187` (turn guard) | 3 cases in `controller.test.ts` | drop the notice → 1 fail; drop the guard → 1 fail |
| C5 | the stall notice names the exit that exists | `controller.ts:73` (`STALL_ADVICE`), `:1299` | "the stall notice names a way out that works…" | restore `(try /retry or /status)` → 1 fail |
| C6 | `/keys` describes the keymap that exists | `controller.ts:766` (`keysPanel`) | "the /keys card describes the keymap that exists" | restore the old line → 1 fail |
| D1 | `noem session resume` exits non-zero when the session is still not ACTIVE | `apps/cli-ts/src/session-command.ts:150-161` | 2 cases in `session-command.test.ts` | (covered by the case that asserts exit 1 + the reason) |
| D2 | CLI flags never enter the durable correction reason | `session-command.ts:88` (`reasonFrom`) | "CLI flags never become part of the durable correction reason" | restore `args.slice(2).join(" ")` → fail |

Regression checks added: `apps/cli-ts/scripts/pty_runtime_lost_check.py`
(real pty; `npm run check:runtime-lost`), `tests/product/test_surface_correction_during_invocation.py`.

## 4. Checked and CLEAN (per surface item)

| item | what was tested | outcome |
| --- | --- | --- |
| `/help`, `/status`, `/cost` | unit tests; read against the snapshot/projection they render; real daemon | clean: cost is stated UNKNOWN (never invented), tokens exact |
| `/provider` (TUI + `noem provider status/set/clear`) | real daemon: `provider status` JSON, redacted; `set` without the env key refuses; failures caught | clean |
| `/mode` | invalid mode refused; failure path caught and reports "still <old>" (previous fix re-verified) | clean |
| `/resume` (no arg) selector + `/resume <id>` | real daemon (`/resume s:nope`), plus fake-client probe | **not clean on this base**: the attach failure is still an unhandled rejection; the C3 backstop keeps the app alive and shows it. The sibling slice `codex/tui-resume-20260918` (f51a9639) rewrites this path — not duplicated here |
| `/goal` | unit tests; the goal is prefixed onto the outgoing text (`client.beginTexts`) and shown in the footer | clean (never silent) |
| `/theme`, `/vim` | unit tests; state persisted (0600) | clean |
| `/export` | 0600 enforced and verified before promising it; failure reported | clean |
| `/find`, `/clear`, `/queue`, `/edit`, `/retry` | unit tests; `/clear` refused while a turn is live | clean (the *stall* advice around `/retry` was F8) |
| `/doctor` | real daemon: descriptor/reach/auth/protocol all reported; `/doctor <bad descriptor>` → exit 1 | clean |
| `/files`, `/task` | real daemon (happy path) + daemon-killed path | clean after C1 |
| Esc while idle | `keys.ts` consumes it deliberately (no stray durable REJECT); unit test | clean |
| Ctrl-C | real pty: exits with code 0 | clean, as documented |
| Ctrl-L | unit test (`clearView` only) | clean: local view only, never durable context |
| approval y/n | unit tests + real daemon approval turn (headless exit 2) | clean after C2 |
| Ctrl-G editor | pty check exists (`pty_fullscreen_editor_keys.py`); read-code: reads the textarea, not the stale React mirror | clean by reading (not re-run here, see §6) |
| Tab / PgUp / PgDn / panel switch | `opentui-viewkeys.test.ts` + `opentui-panels.test.ts` | clean |
| agents panel movement + Enter (switch session) | unit tests; real pty showed the read-only projection including the session's durable `CORRECTION_HALTED` | clean |
| vim modal layer | `opentui-vim.test.ts` + `composer.test.ts` (motions, operators, caret) | clean by test |
| selector (resume/theme/mode) | `selector.test.ts` + read-code | clean, except that a *resume pick* inherits the `/resume` rejection above |
| `/exit` | status → closed → the view exits; documented in the key card | clean |
| headless exit 0 | real daemon: completed turn | clean |
| headless exit 1 | bad `--output-format`, unknown session, refused turn | clean: message on stderr, no stack |
| headless exit 2 | real daemon (edit proposal in ASK mode) | clean: `approval_required`, names the capability |
| headless exit 3 | real daemon (loop detector) | clean: `loop_detected`, tokens still counted |
| stream-json | unit tests (`headless.test.ts`) | clean by test |
| `--resume <bad>` in headless | real daemon | clean: exit 1, `noem: session … not found` |
| correction → session halted | real daemon + pty | **by design** the session is dead afterwards; now named (F6). Reported, not "fixed" |

## 5. Gates

See `verification.md` §4 for the exact commands and outputs (npm test 247 pass,
`npm run test:ci` 34 files pass, `npm run typecheck` clean, `pytest tests/product`
2756 passed / 1 skipped, ruff clean, pyright 0 for the touched files, real-pty
`check:runtime-lost` PASS).

## 6. Honest limits

* **Three sibling fixes are not in this base.** The DENY-visibility fix, the
  real stop key and the `/resume` un-pause fix live on
  `codex/deny-visibility-20260918`, `codex/tui-stop-key-20260918`,
  `codex/tui-resume-20260918` (stacked), not in `03ac66b5`. So on this base:
  `session pause` still cannot take effect (it reports truthfully), a permission
  DENY still shows no card, and `/resume <bad>` still rejects. I did not
  duplicate or pre-empt them; F1's fix touches `agent_loop.py`, which those
  branches also modify, and will need a merge decision.
* **PAUSED and CLOSED sessions were not exercised end to end**: this base cannot
  reach PAUSED (the pause transition fails) and nothing on the terminal closes a
  session.
* **The Daemon-restart re-attach question is open** (new port + token); the
  running-TUI behaviour was measured, but whether the client *should* rebind is a
  decision, not a measurement.
* **`~/.agent-os` was read, once, by accident**: the first stub daemon reported
  its provider status from the operator's persisted `provider.json`
  (read-only; the turn ran on the in-process deterministic provider; nothing was
  written, and no real provider call was made). Every later run set
  `AGENT_OS_PROVIDER_CONFIG`, `AGENT_OS_DISABLE_KEYCHAIN` and
  `AGENT_OS_CLI_STATE` to temp paths, and all descriptors/databases/workspaces
  were explicit temp paths with the server bound to port 0.
* **Not re-run here**: the pre-existing pty checks
  (`pty_smoke.py`, `pty_entry_check.py`, `pty_home_frame_check.py`,
  `pty_search_check.py`). Four of them hardcode
  `HERE = Path("/Users/.../worktrees/os-sandbox/apps/cli-ts/scripts")`, so they
  import `frame_reader` from another worktree; running them from this worktree
  would test a different tree's helper. That is test-infrastructure drift, out of
  this sweep's scope — reported, not fixed. `pty_theme_check.py` and my new
  `pty_runtime_lost_check.py` are portable.
* **One rejection class was not measured end to end**: the `/resume` failure in
  the *real* TUI was measured only through the backstop, not with the command's
  own catch (which the sibling slice adds).
* **`formatToolDetail`, json-reporting of failed tools, delta replay and
  truncation** are read-code confirmations (or another slice's findings), not
  measurements of mine.
* **The same "correction during invocation" condition in the workflow-node paths**
  (`execution.py:1475`, `proposal_engine.py:243`) still raises
  `RunExecutionError` and aborts the node. That is deliberately unchanged: the
  chat-turn path needed the terminal record (F1), while a workflow node has no
  turn to complete. If a future slice unifies them, K1 is the shape to copy.
* **The `decide()` fail-open direction was not fuzzed**: a decision that reaches
  the kernel but whose response is lost leaves the operator on the approval card
  with the true reason on screen (press again). The idempotency key is minted per
  call in `decideApproval`'s default, so a retry is a fresh decision, not a
  replay — measured by reading, not by an interrupted-response test.
