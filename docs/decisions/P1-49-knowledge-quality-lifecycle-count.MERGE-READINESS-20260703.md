# P1-49 Knowledge Quality Summary Lifecycle Count Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-49-knowledge-quality-lifecycle-count-20260703`
Head: `4ae8465`
Target: local `main@7dc1624`
Status: ready for authorized local ff-only merge; not merged, pushed, or released

## Scope

P1-49 exposes `lifecycle_event_count` on internal
`GET /knowledge/assets/quality-summary` items. The field is a safe count of
review/publish/deprecate lifecycle audit events for the asset. It does not
return event bodies, raw reasons, raw trace payloads, related knowledge content,
correction payloads, metric deltas, or secret-like fields.

## Readiness Checks

```text
git merge-base --is-ancestor main HEAD; echo merge_base_exit:$?
```

Result: `merge_base_exit:0`

```text
git rev-list --left-right --count main...HEAD
```

Result: `0 1`

```text
git status --short --branch
```

Result: branch `codex/p1-49-knowledge-quality-lifecycle-count-20260703`;
only `.agent_runs/` remains untracked and is not part of the merge.

## Verification Evidence

Recorded in:

- `docs/decisions/P1-49-knowledge-quality-lifecycle-count.IMPLEMENTATION-20260703.md`

Branch-local verification passed:

- targeted RED/GREEN: 3 tests OK;
- related KnowledgeAsset/API/OpenAPI subset: 30 tests OK;
- `make ci`: 599 primary unittest tests OK / 4 skipped, 12 eval tests OK,
  threshold report passed, OpenAPI up to date;
- PostgreSQL `ci-local-full`: 599 primary unittest tests OK, 12 eval tests OK,
  threshold report passed, OpenAPI up to date, full local parity passed.

## Merge Gate

Authorized action: cautious local ff-only merge to deployment `main`, followed
by post-merge `make ci` and PostgreSQL `ci-local-full`.

Not authorized: push, release, external product claim, autonomous-core/G10
claim, causal/value attribution claim, or R4/R5 execution claim.
