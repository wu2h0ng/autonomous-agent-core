# Operator dead-end sweep — verification record

Companion to `sweep.md`. Everything here was run on 2026-09-18/19 on macOS
arm64 in `.worktrees/wt-uxe` (base `origin/main` = `03ac66b5`).

Environment discipline: every daemon used an explicit temp `--descriptor`,
`--database` and `--workspace`, bound `127.0.0.1:0` (ephemeral) and ran with
`AGENT_OS_NO_AUTOSTART=1`, `AGENT_OS_PROVIDER_CONFIG`, `AGENT_OS_DISABLE_KEYCHAIN`
and `AGENT_OS_CLI_STATE` pointed at the temp directory. `~/.agent-os` was never
written. No `git stash` was used; mutations were reverted from untracked copies
in `/tmp/uxe-sweep`.

## 1. Harness

* `/tmp/uxe-sweep/stub_daemon.py` — hermetic daemon over
  `AgentOSApplication` + a scripted `DeterministicProvider`, scenarios `plain`,
  `slow` (chunked with 1.2 s gaps so a turn stays in flight), `approval`, `loop`
  (identical capability+arguments, distinct proposal ids), `deny`, `hang`.
* `/tmp/uxe-sweep/pty_*.py` — real-pty probes (vt100 grid reconstructed with
  `apps/cli-ts/scripts/frame_reader.py`): `pty_dead_daemon_probe.py`,
  `pty_correction_probe.py`, `pty_keys_probe.py`,
  `aborted_turn_probe.py`.
* Shipped regression check: `apps/cli-ts/scripts/pty_runtime_lost_check.py`
  (`npm run check:runtime-lost`).

## 2. Reproductions (pre-fix observations)

### 2.1 F1 — Esc leaves the turn uncommitted (100%, 3/3)

pty, `slow` provider, type a message, wait ~1.2 s, press Esc
(`/tmp/uxe-sweep/pty_correction_probe.py`). Durable event log of that session
read from the daemon's SQLite store:

```
SESSION_TURN_STARTED 9  {"turn_id": "turn-67d9840b-…", "user_text": "hello slow"}
CORRECTION_WRITTEN  10  {"epoch": 1, "halted": true, "scope": "TASK", …}
(no further events — no PROVIDER_RESPONDED, no SESSION_TURN_COMPLETED)
```

Session status after Esc: `CORRECTION_HALTED; sequence 10`. The next message, in
the same pty session, produced on screen:

```
› hello again
error: a prior turn is still uncommitted for this session
```

and the status stayed `CORRECTION_HALTED` at the same sequence. `noem session
show` in the same state answers `"status": "ACTIVE"`, so the operator's only
status command disagrees with the refusal they keep getting.

### 2.2 F2 — a vanished runtime destroys the frame

`/tmp/uxe-sweep/pty_dead_daemon_probe.py /task /files`: boot the TUI against a
stub daemon, complete one turn, `SIGKILL` the daemon, type `/task`, then
`/files`. Screen (reconstructed) after the first command:

```
│                                        Console (Focused) ││                 [Copy (ctrl+shift+c)]│
│  xe/apps/cli-ts/src/client.ts:121:17)                    ││                                      │
└────────at─async─overview─(/Users/…/wt-uxe/apps/cli-ts/src/client.ts:445:33)───────────────────────┘
┌─mes/…─controller.ts:964:40)──────────────────────────────────────────────────────────────────────┐
│ Tell Noat asyncttaskCommandr(/Users/…/apps/cli-ts/src/controller.ts:964:40)                      │
│        at async submit (/Users/…/apps/cli-ts/src/controller.ts:479:20)                           │
> ASK · dateprocessTicksAndRejectionsc(native:7:39) ev 12 · [tab] panel: transcript · [pgup/pgdn]  │
```

The composer, footer and transcript are interleaved with the rejection trace;
the second command smears it further. Bun's default handling of an unhandled
rejection outside the TUI kills the process with exit 1
(`bun run /tmp/uxe-sweep/rej2.ts` → no "still alive", `EXIT=1`).

### 2.3 F3 — `y`/`n` with nothing pending rejects

Scripted client (`apps/cli-ts/.sweep/rejection-probe.ts`, untracked, since
removed; copy in `/tmp/uxe-sweep/rejection-probe-copy`):

```
REJECTS? selector pick → resume: (void) unhandled — stack printed by the runtime
REJECTS? /files (files endpoint down): YES — HTTP 500: files projection failed
REJECTS? /task (overview endpoint down): YES — HTTP 500: overview projection failed
REJECTS? approve() with no pending approval: YES — no pending approval
REJECTS? reject() with no pending approval: YES — no pending approval
```

### 2.4 F4 — an aborted turn bricks the session permanently

`/tmp/uxe-sweep/aborted_turn_probe.py`: start a turn against the `slow` provider,
kill the daemon 0.8 s in, restart it on the same database, then run a turn with
`--resume`:

```
turn 1 exit: 1  {"subtype":"error","text":"slow rep","stop_reason":"cannot reach the local runtime: Unable to connect…"}
session show: {"status": "ACTIVE", "event_sequence": 9, "message_count": 2}
turn 2 exit: 1  {"subtype":"error","stop_reason":"a prior turn is still uncommitted for this session"}
```

`event_sequence 9` is the `SESSION_TURN_STARTED` of the killed turn: nothing can
complete it, `surface_has_uncommitted_turn()` is true forever, and
`begin_turn` refuses before the provider is reached.

### 2.5 F6 — a correction is terminal for the session

Real daemon, headless only:

```
session show            → {"status": "ACTIVE", "event_sequence": 12}
session correct <id>    → {"status": "CORRECTION_HALTED"}  (exit 0)
turn (--resume)         → exit 1, stop_reason "configuration correction epochs changed after seal"
session resume <id>     → {"status": "CORRECTION_HALTED"}  (exit 0, pre-fix)
turn (--resume)         → exit 1, same refusal
POST /v1/tasks/{id}/correction/resume  → 200, snapshot back to ACTIVE
turn (--resume)         → exit 1, still "configuration correction epochs changed after seal"
```

Only a *new* session runs again (verified: `noem -p "hello after un-halt"` with
no `--resume` → `sweep reply 1`, exit 0).

### 2.6 F7 — flags in the durable audit reason

`noem session correct <id> "operator interrupt (escape)" --descriptor
/tmp/uxe-sweep/run1/descriptor.json` recorded:

```
CORRECTION_WRITTEN {"epoch":1,"halted":true,
  "reason":"operator interrupt (escape) --descriptor /tmp/uxe-sweep/run1/descriptor.json", …}
```

### 2.7 C3 backstop, `/keys` claims, Ctrl-C (real pty)

`/tmp/uxe-sweep/pty_keys_probe.py`:

* `/resume s:does-not-exist` → transcript shows
  `internal error (unhandled rejection): session s:does-not-exist not found`,
  `tui alive: True`. The frame is still disturbed by the runtime's own stack
  print (that is why C1/C2 catch at the command, and C3 is only a backstop).
* Ctrl-P on a one-line draft after a completed turn: the composer is still empty
  (no recall); Ctrl-A then `Z` produced `Zabcdef` (caret moved to line start).
* Ctrl-C while idle: exit code `0`.

## 3. Post-fix confirmations

* Real pty, Esc mid-turn (same probe as 2.1), after the fixes:

  ```
  › hello slow
  slow reply 1
  ⏵ correction issued (operator interrupt)
  ⏵ this session is CORRECTION_HALTED — a correction halts the task and voids its
    sealed configuration, so the kernel refuses every further turn in this
    session. No command in this terminal restores it: start a new session
    (restart noem) and use /resume only to look at this one.
  ⏵ turn ended: correction_halted (0 steps, tokens counted) — not a successful completion
  …
  › (the next message is refused locally; no kernel round trip, no jargon error)
  ⏵ this session is CORRECTION_HALTED — …
  ```

  The durable log for that turn now contains
  `SESSION_TURN_COMPLETED {"stop_reason": "correction_halted", "steps": 0}` (the
  sequence advanced 10 → 11), so nothing is left uncommitted; and the bare
  `error: configuration correction epochs changed after seal` from 2.5 no longer
  appears — the refusal is named before the request is sent.
* `apps/cli-ts/scripts/pty_runtime_lost_check.py`:

  ```
  ⏵ task overview unavailable: cannot reach the local runtime: … (no status is being guessed)
  ⏵ files unavailable: cannot reach the local runtime: … (nothing was read)
  PASS: a vanished runtime is reported, never fatal, and the surface keeps working
  ```

* Headless exit-code table re-measured against real daemons:
  `0` completed; `1` bad `--output-format` / unknown session / refused turn;
  `2` `approval_required` naming `workspace.edit`; `3` `loop_detected` with
  `total_tokens: 318`.

## 4. Gates (final tree)

```
cd apps/cli-ts && npm test
  # tests 247  # pass 247  # fail 0
cd apps/cli-ts && npm run test:ci
  === ran 34 test files in 38 s (budget 720000 ms, per file 180000 ms)
  === all test files passed
cd apps/cli-ts && npm run typecheck          → clean (tsc --noEmit)
uv run --extra product-test pytest tests/product -q
  2756 passed, 1 skipped in 229.64s
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
  All checks passed!
uv run --extra product-test pyright packages/os_core/src tests/product/test_surface_correction_during_invocation.py
  0 errors, 0 warnings
uv run --extra product-test python apps/cli-ts/scripts/pty_runtime_lost_check.py
  PASS
```

`scripts.test` in `apps/cli-ts/package.json` is untouched and still lists exactly
the on-disk test files (`test/test-list-guard.test.ts` passes, and it is part of
`test:ci`).

## 5. Mutations actually performed

Each mutation was applied to an untracked copy (`/tmp/uxe-sweep/*.fixed*`),
run, and reverted; the tree was green again afterwards.

| mutant | result |
| --- | --- |
| `agent_loop.py`: remove the `ProviderCorrectionHalt` catch in `_drive` | 3/3 new product cases fail (`ProviderCorrectionHalt` raised out of the turn) |
| `controller.ts`: remove the `/files` + `/task` try/catch | `not ok 46 - a failing read command is reported, never thrown into a void`; the real-pty check fails with `an unhandled-rejection stack was smeared over the frame` |
| `controller.ts`: `decide()` throws again when nothing is pending | `not ok 47 - answering an approval with nothing pending reports instead of rejecting` |
| `controller.ts`: drop the halt notice after a correction | `not ok 50 - a correction reports the halt it caused (CORRECTION_HALTED)` |
| `controller.ts`: drop the halted-session turn guard | `not ok 51 - a turn on a halted session is named and not sent` |
| `controller.ts`: restore `(try /retry or /status)` | `not ok 53 - the stall notice names a way out that works…` |
| `controller.ts`: restore the old `/keys` lines | `not ok 54 - the /keys card describes the keymap that exists` |

All seven mutants redden exactly one test each; no other test moves.

## 6. Process hygiene

* No `python -m apps.runtime_daemon` process was ever started by this sweep; each
  stub daemon ran as `/tmp/uxe-sweep/stub_daemon.py` or
  `apps/cli-ts/scripts/dev_daemon.py`.
* After the run: `pgrep -f 'python -m apps\.runtime_daemon'`,
  `pgrep -fl stub_daemon`, `pgrep -fl uxe-sweep` all print nothing. One
  `dev_daemon.py` from **another** workstream is still running
  (`…/T/editor-keys-m7_25bce/r.json`, pids 2995/3043, older than this session) —
  not started by this sweep and deliberately left alone.
* Temp state lives under `/tmp/uxe-sweep/` and `$TMPDIR/noem-runtime-lost-*`;
  the repository contains only the files listed in the PR diff.
