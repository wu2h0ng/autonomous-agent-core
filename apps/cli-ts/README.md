# cli-ts — TS + Ink surface-protocol client (spike)

Goal-mode charter queue A#1 spike (D1 ACCEPT 2026-09-11): prove a TypeScript +
Ink client can drive the **existing** surface protocol v1.1 end to end with
the frozen E1 semantics — subscription-first, begin-turn reservation, live
CHUNK frames (typewriter), explicit GAP honesty, digest-bound approvals,
mode switching — while the Python governance kernel stays untouched.

## Quick start (fresh checkout)

Prerequisites: Node ≥ 20, [uv](https://docs.astral.sh/uv/) (the daemon is the
Python governance kernel; `uv run` resolves its environment from the repo
root `pyproject.toml`).

```bash
cd apps/cli-ts
npm install

# terminal 1 — hermetic daemon (scripted provider, no network/credentials).
# Writes a private descriptor (0600) to ~/.agent-os/runtime.json by default.
npm run dev:daemon

# terminal 2 — interactive Ink TUI (loads the default descriptor)
npm run dev
```

Inside the TUI: type a message and press Enter to stream a turn; `/help`
lists commands (`/mode`, `/files`, `/task`, `/clear`, `/resume`); `y`/`n`
answer approval cards; Esc/Ctrl-C issue a correction; Ctrl-L clears the view.

## Verify (one command, fully hermetic)

```bash
npm run e2e        # doctor → smoke full → headless -p json → daemon restart
                   # resume → doctor-must-fail → pty smoke (3 phases)
```

`npm test` runs the 40 unit tests; `npm run build` type-checks.

## Other entry points

```bash
npm run doctor                      # read-only probes: descriptor/auth/protocol
npm run dev -- -p "hello"           # headless one-shot (exit codes 0/1/2/3)
npm run dev -- -p "hello" --output-format json
npm run smoke:pty                   # real-pty TUI regression (3 phases)
npm run live                        # real provider evidence (needs KIMI_*)
npm run live:pty                    # real provider multi-turn in a real pty
```

## Layout

- `src/contracts.ts` — zod mirrors of `agent_os_contracts/surface.py` (v1.1, frozen)
- `src/client.ts` — `SurfaceClient` port of `apps/cli/surface_client.py`
- `src/controller.ts` — Ink-free state machine; frozen-semantics mapping table in the header comment
- `src/App.tsx` — Ink UI: streaming, approval card, todo panel projection, diff preview
- `src/cli.tsx` — entry (`--descriptor`, `--resume`, `doctor`, `-p`)
- `scripts/dev_daemon.py` — hermetic daemon with scripted streaming provider (no network)
- `scripts/smoke.ts` — headless end-to-end walk of the frozen order (exit 1 on violation)
- `scripts/pty_smoke.py` — real-pty TUI smoke: render/typing/Enter/narrow+resize/approval
- `scripts/live_evidence.py`, `scripts/live_multiturn_pty.py` — opt-in real-provider evidence
- `scripts/e2e.sh` — one-command full-chain regression (hermetic)
- `test/` — unit tests incl. bypass-detection (a controller skipping the
  frozen semantics fails here)

## Boundaries

Protocol client only: never mints turn ids, never holds governance state,
treats transient frames as display state, resubscribes on 410 (dead
generation) and re-syncs from durable snapshots. Approvals are human-only
(`y`/`n` in the TUI); permission modes are operator-only (`/mode`). No claim
beyond SPIKE.
