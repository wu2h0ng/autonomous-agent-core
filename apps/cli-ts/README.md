# cli-ts — TS + Ink surface-protocol client (spike)

Goal-mode charter queue A#1 spike (D1 ACCEPT 2026-09-11): prove a TypeScript +
Ink client can drive the **existing** surface protocol v1.1 end to end with
the frozen E1 semantics — subscription-first, begin-turn reservation, live
CHUNK frames (typewriter), explicit GAP honesty, digest-bound approvals,
mode switching — while the Python governance kernel stays untouched.

## Layout

- `src/contracts.ts` — zod mirrors of `agent_os_contracts/surface.py` (v1.1, frozen)
- `src/client.ts` — `SurfaceClient` port of `apps/cli/surface_client.py`
- `src/App.tsx` — Ink UI: streaming, approval card, mode cycle (shift+tab), Ctrl-C correction
- `src/cli.tsx` — entry (`--descriptor`, `--resume <session_id>`)
- `scripts/dev_daemon.py` — hermetic daemon with scripted streaming provider (no network)
- `scripts/smoke.ts` — headless end-to-end walk of the frozen order (exit 1 on violation)
- `test/client.test.ts` — contract tests against a mock wire server

## Run

```bash
npm install
npm test                                 # hermetic contract tests
npm run dev:daemon                       # terminal 1: hermetic daemon
npm run smoke                            # terminal 2: headless E2E (must print PASS)
npm run dev                              # interactive Ink TUI
```

## Boundaries

Protocol client only: never mints turn ids, never holds governance state,
treats transient frames as display state, resubscribes on 410 (dead
generation) and re-syncs from durable snapshots. No claim beyond SPIKE.
