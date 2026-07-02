# P1-13 KnowledgeAsset Deprecate Lifecycle Post-Merge Verification

Date: 2026-07-03
Merged branch: `codex/p1-13-knowledge-deprecate-lifecycle-20260703`
Local main: `cd9b9dc`
Status: local ff-only merge verified; not pushed, not released

## Merge

`main@84f1d21` was verified as an ancestor of
`codex/p1-13-knowledge-deprecate-lifecycle-20260703@cd9b9dc`, then deployment
`main` was fast-forward merged to `cd9b9dc`.

No remote push or release was performed.

## Post-Merge Verification

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
ruff clean
format check clean
563 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed: 5 golden cases across 8 dimensions at 1.0 thresholds
OpenAPI contract up to date
```

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Result:

```text
563 primary unittest tests OK / 4 skipped
12 eval tests OK
threshold-report gate passed
OpenAPI contract up to date
Full local CI parity checks passed
```

## Boundary Confirmation

P1-13 remains an internal correction lifecycle surface:

- `POST /knowledge/assets/{asset_id}/deprecate` requires internal
  `knowledge:review` scope.
- `external_report` principals are denied.
- Only `active` or `published` KnowledgeAssets can become `deprecated`.
- Draft assets must still use the review queue reject path.
- Trace audit uses `knowledge_deprecate_decision` and records
  `reason_present`, not raw reason text.
- The transition does not infer value, write feedback/adoption, publish
  external content, bypass SQL Safety/EvidenceChain/Approval, or alter R4/R5
  behavior.

Push and release remain separate founder/CTO gates.
