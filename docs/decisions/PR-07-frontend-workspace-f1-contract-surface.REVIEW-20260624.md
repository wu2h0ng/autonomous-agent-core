# PR-07 Frontend Workspace F1 Contract Surface Review

- Date: 2026-06-24
- Branch: `codex/workspace-f1-contract-surface`
- Reviewed commit: `16fdc62`
- Base: `codex/enterprise-integration-reconcile` at `14556e0`
- Scope: review the static Frontend Workspace F1 contract surface for DataProduct candidate and KnowledgeAsset candidate visibility
- Status: reviewed locally; approved for explicit merge-order decision only; not merged, pushed, released, or deployed

## Findings

No code-level merge blocker found for the F1 static contract surface.

Initial read-only review found three concerns, all remediated in this review pass:

- SQL-blocked and insufficient-evidence states now override the full DataProduct candidate field set (`id`, `contract`, `freshness`, `reuse`, `source`, `status`) instead of mixing stale scenario fields with blocked/draft language.
- The static test now guards the full visible candidate field set, candidate-state override markers, and the workspace-wide no-OS-Core-import boundary for `.html`, `.md`, `.js`, `.css`, `.ts`, and `.tsx` files under `apps/workspace`.
- The candidate header layout now allows wrapping and `min-width: 0` to reduce small-viewport squeeze risk.

## Review Notes

- The F1 delta is narrow relative to `codex/enterprise-integration-reconcile`: 8 files, 281 insertions, 23 deletions. It adds the static prototype surface, a focused static test file, implementation log, and status-doc updates.
- The branch is not a standalone UI-only branch relative to local `main`. A direct merge to `main` would also bring the whole unmerged reconcile stack: report-read projection, postgres report snapshots, connector execution semantics cleanup, CI preflight, and related docs. That is acceptable only if the founder/CTO chooses to merge the reconcile stack first or merge this branch as the combined successor to reconcile.
- The prototype exposes real DOM surfaces for `DataProduct candidate` and `KnowledgeAsset candidate` rather than only narrative text: candidate id/status/contract/freshness/reuse/source fields plus KnowledgeAsset state/review path.
- The state model includes loaded, SQL-blocked, and insufficient-evidence mock states. Blocked state keeps DataProduct unpromoted and avoids creating a KnowledgeAsset from a blocked formal answer; insufficient-evidence state keeps both surfaces review/draft-only without leaking stale candidate id/contract/freshness/reuse fields from the active scenario.
- The test guards visible F1 markers, full candidate field presence, candidate-state override markers, contract-shaped mock states, workspace-wide no-OS-Core-import markers, and candidate-header wrap CSS. This is appropriate for a static prototype, but it is not a substitute for live API or React/Next.js integration tests.
- The implementation log and status docs keep the non-claims explicit: no live API integration, no new public API contract, no React/Next.js scaffold, no production release, no external release, and no automatic R4/R5 execution.

## Merge-Order Constraint

`codex/workspace-f1-contract-surface` has merge-base `f35f4e8` with local `main` and includes the unmerged reconcile commits before the F1 commit. Therefore:

- **Allowed next step:** explicit founder/CTO merge-order decision: merge `codex/enterprise-integration-reconcile` first, or merge `codex/workspace-f1-contract-surface` as the combined successor branch.
- **Not allowed:** describe this branch as an independently mergeable UI-only patch against `main`.
- **Not allowed:** push, release, deploy, claim production UI, or claim live data-agent workspace integration from this review.

## Verification

```bash
git diff --name-status codex/enterprise-integration-reconcile...HEAD
git diff --stat codex/enterprise-integration-reconcile...HEAD
git merge-tree --write-tree main HEAD
git merge-tree --write-tree codex/enterprise-integration-reconcile HEAD
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_workspace_prototype -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed results:

- Relative-to-reconcile delta: 8 files, 281 insertions, 23 deletions.
- `git merge-tree --write-tree main HEAD`: exit 0, wrote tree `7caacd7ed2bb7f4ac087f23a19a9146958929f08`.
- `git merge-tree --write-tree codex/enterprise-integration-reconcile HEAD`: exit 0, wrote tree `7caacd7ed2bb7f4ac087f23a19a9146958929f08`.
- Targeted workspace prototype tests: 5 tests OK.
- Full CI: 445 primary unittest/eval-discover tests OK, 4 skipped; 12 eval subset tests OK; ruff clean; format clean; OpenAPI contract up to date.
- Browser QA was run against a local static server before this review: desktop, blocked-state interaction, Need-evidence interaction, and mobile viewport had the F1 candidate surfaces present, no console warnings/errors, no stale candidate field leakage, and no mobile horizontal overflow at 390px.

## Approval Status

Approved for an explicit founder/CTO merge-order decision. This review does not approve push, production release, external release, live API-backed frontend integration, React/Next.js scaffold, full RBAC/DLP, tenant isolation, field/row-level authorization, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, workflow replacement, autonomous-core adoption, or automatic R4/R5 execution.
