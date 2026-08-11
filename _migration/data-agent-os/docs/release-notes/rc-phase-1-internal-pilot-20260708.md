# Release Candidate Notes — Phase 1 Internal Pilot

- **Tag:** `rc/phase-1-internal-pilot-20260708` (prepared locally, not yet pushed)
- **Candidate head:** `e11ebadaf955bc51c1911acb1dc7b0236787af91`
- **Local main head:** `4a8922b22b5c7bc92d93384cc230eeeab94bbbf5`
- **Date:** 2026-07-08
- **Status:** Internal pilot release candidate — external GA gate remains closed

## What this RC represents

This candidate captures the phase-1 governed data-agent OS product vertical at the end of M9. It is intended for internal/Customer-0 pilot pinning and operator rehearsal, not for external general availability.

## M9 verification summary

| Gate | Result | Evidence |
|------|--------|----------|
| Default operator walkthrough | PASS | `trace-4a5db21ec92c`, approval executed, outcome recorded, `/workflows` 503 with default flags |
| Staging C/D/E walkthrough | PASS | `trace-4adf8da2d7d4`, `workflow.started` in RunTrace |
| `make ci-local-full` | PASS | Green at candidate head `e11ebad…`; format-check drift resolved |
| M8 compose E2E | PASS | Prior M8 commit family |
| Internal pilot loop demonstrable | YES | End-to-end health → run → approval → outcome chain |

## Authorization

- **PR-32 Option B:** `DEPLOYMENT_PUSH: AUTHORIZED` for candidate head `e11ebadaf955bc51c1911acb1dc7b0236787af91`.
- **PR-32 Option C:** `rc/phase-1-internal-pilot-20260708` tag prepared locally at the same candidate head; tag push is a separate release gate.
- Prior record PR-11 `DEPLOYMENT_PUSH: HOLD` is superseded by PR-32 for this candidate only.

## Remaining external-GA gate

No external GA claim is made. Before any external/general-availability release:

1. Founder/CTO must explicitly authorize tag push / release publish.
2. A separate release review must confirm R4/R5 remain proposal-only by default under `ADR-0012`.
3. Customer-0 operator rehearsal must complete against the pinned RC.

## Commits included since origin/main

```text
4a8922b docs(PR-32): update candidate head to green e11ebad and retag rc pointer
e11ebad test: update readiness gate fixture to copy CURRENT_STATE verification sources and current R4/R5 phrase
2cc86af fix(ruff): resolve format drift in alembic/tests and authorize PR-32 Option B/C
52321de docs: align IGI objective, reposition historical blueprints, and update layer role map
```

`origin/main` is an ancestor of local `main`; a fast-forward push is possible.

## Known caveats

- The staging walkthrough exercises C/D/E surfaces; production profile keeps staged-out flags default-off.
- Operator UI surfaces require manual browser confirmation after `docker compose up -d`.
- External promotion remains gated; do not push `origin/main` or the RC tag without explicit approval.
