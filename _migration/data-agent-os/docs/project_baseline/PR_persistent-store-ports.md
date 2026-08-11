## Summary

Phase 1 of the in-memory → PostgreSQL persistence migration, plus the design AR that scopes the
whole migration. **Design doc + a decision-free refactor — no DB, no backend choice yet.**

Builds on #2 (merged).

## Commits

1. **`docs(ar): persistent store design (in-memory -> PostgreSQL)`** — `AR-20260606-persistent-store-design.md`.
   Scopes durable persistence for the loop's four stateful stores (feedback, knowledge, snapshot,
   approval): Ports in OS Core, Postgres adapters *outside* OS Core, JSONB schema, phased rollout,
   transactional `record_outcome`, and the open decisions to ratify (psycopg vs SQLAlchemy, migrations
   tool, adapter location, sync vs async).

2. **`refactor(os-core): introduce store Ports (Phase 1)`** — add `FeedbackStorePort` and
   `KnowledgeStorePort` ABCs (`SnapshotStore` is already a port). The in-memory `FeedbackStore` /
   `KnowledgeStore` now implement the ports, and `TrustedLoopRuntime` programs to the port types.
   This is the seam future Postgres adapters plug into. No behavior change; in-memory remains the
   default. `ApprovalLiteRuntime` storage split (`ApprovalStorePort`) is deferred to a later phase.

## Verification (CI parity)

- `pip install -e ".[dev]"` succeeds; `ruff check .` clean; `ruff format --check .` clean (whole repo);
  `unittest` with the Makefile PYTHONPATH → **223 tests pass**; eval suite passes.

## Scope / non-goals

No PostgreSQL adapter, no schema, no backend selection in this PR — those are Phase 2+, gated on the
open decisions in the AR. This PR only establishes the abstraction seam and records the plan.

## Review focus

- `packages/os_core/.../feedback/__init__.py`, `.../knowledge_memory/__init__.py` — the new Port ABCs.
- `packages/os_core/.../trusted_loop.py` — type hints now reference the ports.
- `docs/architecture_reviews/AR-20260606-persistent-store-design.md` — the migration plan + open decisions.
- OS Core still imports no infra drivers / `domain_packs` / `providers` / `action_connectors`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
