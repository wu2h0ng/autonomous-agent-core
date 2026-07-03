# P1-52 Knowledge Detail Usage Summary Post-Merge Verification

Date: 2026-07-03
Merged branch: `codex/p1-52-knowledge-detail-usage-summary-20260703`
Deployment local main after ff-only merge: `e6d1e49`
Status: locally merged and post-merge verified; not pushed or released

## Merge

The branch was fast-forward merged into deployment local `main`:

```text
git switch main
git merge --ff-only codex/p1-52-knowledge-detail-usage-summary-20260703
```

Result: `main` advanced from `88b8128` to `e6d1e49`.

## Post-Merge Verification

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 599 tests OK / 4 skipped
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

- Ruff check passed
- Ruff format check passed
- Primary unittest discovery: 599 tests OK
- Eval tests: 12 OK
- Threshold report: 5 golden cases across 8 dimensions passed at 1.0 thresholds
- OpenAPI contract up to date
- Full local CI parity checks passed

## Boundary

This remains a local-main implementation only. It is not pushed, not released,
and not an external product claim.

The merged slice is internal-only and read-only. It exposes only safe latest
usage summaries on KnowledgeAsset detail. It does not expose usage event bodies,
raw trace payloads, raw run parameters, source asset content, related knowledge
content, tool names on detail summaries, correction payloads, metric deltas, or
secret-like fields. It does not mutate lifecycle/version/retrieval/feedback/
adoption state, lower governance, bypass SQL Safety/EvidenceChain/Approval,
promote adoption/value, write feedback, change connector routing, or allow R4/R5
automatic execution.
