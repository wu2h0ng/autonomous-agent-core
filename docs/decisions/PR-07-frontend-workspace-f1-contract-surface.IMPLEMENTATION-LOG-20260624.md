# PR-07 Frontend Workspace F1 Contract Surface Implementation Log

- Date: 2026-06-24
- Branch: `codex/workspace-f1-contract-surface`
- Base: `codex/enterprise-integration-reconcile` at `14556e0`
- Status: implemented locally; not merged, pushed, released, or deployed

## Scope

This slice upgrades the static Intent Workspace prototype from F0-only visibility to a
static F1 contract surface. It keeps the existing static-prototype boundary and adds
first-class visibility for:

- DataProduct candidate id/status/contract/freshness/reuse/source context;
- KnowledgeAsset candidate state and review note;
- loaded, SQL-blocked, and insufficient-evidence mock states that update those candidate surfaces.

## Entry Point

```text
apps/workspace/prototype/index.html
```

The page is still a static prototype. It does not call the API, does not execute business
actions, and does not import OS Core.

## Contract Boundary

- Uses contract-shaped mock fields derived from the existing public product/API vocabulary:
  `MetricContract`, `ProviderContract`, `EvidenceChain`, report snapshot, trace link,
  `DataProduct candidate`, and `KnowledgeAsset candidate`.
- Does not add or change OpenAPI, backend schemas, runtime contracts, SQL Safety, EvidenceChain,
  approval, action connectors, auth, persistence, or trace behavior.
- Does not claim live API integration, React/Next.js scaffold, production UI, or release readiness.

## Negative Paths

- `blocked` state: DataProduct candidate is not promoted and KnowledgeAsset candidate is not
  created from a SQL Safety-blocked formal answer. The full visible candidate field set is
  replaced with blocked/not-applicable values to avoid stale scenario leakage.
- `insufficient` state: DataProduct remains draft and KnowledgeAsset remains review-only until
  missing owner/dimension evidence is resolved. The full visible candidate field set is replaced
  with draft/pending-evidence values.

## Verification

- Red/green static UI contract test:
  `tests/unit/test_workspace_prototype.py`
- Browser QA target flow:
  `http://127.0.0.1:8765/ -> ROI 诊断 -> Need evidence`
- Checks covered:
  DataProduct candidate visible, KnowledgeAsset candidate visible, loaded/blocked/insufficient
  states present, blocked/insufficient states override the full candidate field set, no OS Core
  import marker under `apps/workspace`, candidate header wrapping, no console warnings/errors,
  desktop interaction updates candidate state, and mobile viewport has no horizontal overflow.

## Non-Claims

- No live API integration.
- No new public API contract.
- No React/Next.js scaffold.
- No production release.
- No external release.
- No automatic R4/R5 execution.
