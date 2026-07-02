# P1-10 Internal Knowledge Context Projection Post-Merge Verification

Date: 2026-07-03
Merged branch: `codex/p1-10-internal-knowledge-context-projection-20260703`
Deployment main after merge: `4432784`
Status: local main verified; not pushed, not released

## Merge

Founder/CTO authorized cautious local merges. Deployment `main` was clean except
untracked `.agent_runs/`, and `main@6513fbe` was an ancestor of
`codex/p1-10-internal-knowledge-context-projection-20260703`.

Command:

```bash
git merge --ff-only codex/p1-10-internal-knowledge-context-projection-20260703
```

Result: fast-forward from `6513fbe` to `4432784`.

## Verification

Post-merge commands:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 556 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.

## Boundaries

This merge only projects safe recalled KnowledgeAsset asset ids into internal
`user_result.decision.knowledge_context_refs`; external audience projection
returns an empty list.

It does not push, release, expose KnowledgeAsset titles/content, publish
KnowledgeAssets, write feedback, promote adoption/value, export production
telemetry, validate autonomous-core/G10 product claims, lower governance, bypass
SQL Safety/EvidenceChain/Approval, or allow R4/R5 automatic execution.
