# PR-11: Deployment push authorization (M7 refresh)

- Date: 2026-07-07
- Status: **HOLD for further origin/main promotion**
- Authorization: founder/CTO (ADR-0013 PKG push completed 2026-07-07; subsequent pushes gated)

## Decision

DEPLOYMENT_PUSH: HOLD

## Context

Founder authorized scoped ADR-0013 commits (PKG-01..13) and a one-time push to `origin/main`, completed at:

- candidate_head: 89c2e9b5d7526afadabd66c5d8efccb2eaf3104e

This record **does not** authorize additional `origin/main` pushes, release tags, or external product claims until a new explicit `DEPLOYMENT_PUSH: AUTHORIZED` line binds a fresh 40-character `candidate_head` after M7 internal-pilot verification.

## Boundaries (unchanged)

- No release tags or RC promotion tags for the ADR-0013 candidate without a separate release gate.
- No default-on staged-out feature flags in deployed environments.
- R4/R5 automatic execution remains proposal-only unless tenant policy + flag + ADR-0012 review explicitly authorize a pilot profile.

## Next gate to lift HOLD

1. `make ci-local-full` green at intended candidate head (PostgreSQL parity).
2. M7 internal pilot smoke (`scripts/smoke-test.sh`) green against compose stack.
3. New PR record with `DEPLOYMENT_PUSH: AUTHORIZED` and matching `candidate_head:` line.
