# P1-14 KnowledgeAsset Detail Post-Merge Verification

Date: 2026-07-03
Merged branch: `codex/p1-14-knowledge-asset-detail-20260703`
Local main: `ec46dc0`
Status: local ff-only merge verified; not pushed, not released

## Merge

`main@c1ff0ea` was verified as an ancestor of
`codex/p1-14-knowledge-asset-detail-20260703@ec46dc0`, then deployment `main`
was fast-forward merged to `ec46dc0`.

No remote push or release was performed.

## Post-Merge Verification

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
ruff clean
format check clean
566 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed: 5 golden cases across 8 dimensions at 1.0 thresholds
OpenAPI contract up to date
```

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
566 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed
OpenAPI contract up to date
Full local CI parity checks passed
```

## Boundary Confirmation

P1-14 remains an internal read-only drill-down surface:

- `GET /knowledge/assets/{asset_id}` requires internal `knowledge:review` scope.
- `external_report` principals are denied.
- Unknown asset ids return typed 404 `KNOWLEDGE_ASSET_NOT_FOUND`.
- The response returns safe metadata plus `has_source_trace`; it does not embed
  trace events.
- The route does not mutate lifecycle, version, feedback, adoption, retrieval
  ranking, SQL Safety, EvidenceChain, Approval, connector, or R4/R5 behavior.

Push and release remain separate founder/CTO gates.
