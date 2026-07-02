# P1-08 Reviewed Knowledge Consumption Post-Merge Verification

Date: 2026-07-03
Merged branch: `codex/p1-08-active-knowledge-consumption-20260703`
Deployment main after merge: `6471924`
Status: local main verified; not pushed, not released

## Merge

Founder/CTO authorized a cautious local merge. Deployment `main` was clean
except untracked `.agent_runs/`, and `main` was an ancestor of
`codex/p1-08-active-knowledge-consumption-20260703`.

Command:

```bash
git merge --ff-only codex/p1-08-active-knowledge-consumption-20260703
```

Result: fast-forward from `02f4f26` to `6471924`.

## Verification

Post-merge commands:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 555 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.

## Boundaries

This merge only adds a read-side KnowledgeAsset consumption guard: default
retrieval/search/recall consumes reviewed `ACTIVE` assets or external adopted
value-backed assets, while unreviewed `DRAFT` and `DEPRECATED` assets remain
stored/auditable and available through explicit lifecycle queries.

It does not push, release, publish KnowledgeAssets, change adoption ingestion,
write feedback, export production telemetry, validate autonomous-core/G10
product claims, or allow R4/R5 automatic execution.
