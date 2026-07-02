# P1-18 KnowledgeAsset Usage Events Post-Merge Verification

Date: 2026-07-03
Layer: deployment
Branch: `main`
Merge: local fast-forward from `codex/p1-18-knowledge-usage-events-20260703`
Merged head: `d0ca465`
Status: local main verified; not pushed, not released

## Merge Gate

Pre-merge checks:

- `git status --short --branch` on deployment `main` showed no tracked changes; only untracked `.agent_runs/` remained.
- `git merge-base --is-ancestor main codex/p1-18-knowledge-usage-events-20260703` returned `0`.
- `git merge --ff-only codex/p1-18-knowledge-usage-events-20260703` succeeded.

## Post-Merge Verification

Commands:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- `576` primary unittest tests passed, `4` skipped.
- `12` eval tests passed.
- threshold report passed for `5` golden cases across `8` dimensions at `1.0` thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` ended with `Full local CI parity checks passed`.

## Boundary

This local merge does not authorize push or release.

The merged P1-18 surface remains internal read-only audit:

- `GET /knowledge/assets/{asset_id}/usage-events`
- requires internal `knowledge:review` scope;
- denies `external_report`;
- returns allowlisted proposal/correction usage metadata only.

It does not expose KnowledgeAsset title/content/full related knowledge, raw correction payloads, metric deltas, reasons, or secret-like values. It does not mutate lifecycle/version/retrieval/feedback/adoption state, lower governance, bypass SQL Safety/EvidenceChain/Approval, promote adoption/value, reuse `/runs` ordering for correction-channel events, or enable R4/R5 automatic execution.
