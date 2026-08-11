# P1-52 Knowledge Detail Usage Summary Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-52-knowledge-detail-usage-summary-20260703`
Local main checked: `88b8128`
Status: branch-local implementation verified and ready for cautious local
ff-only merge; not pushed or released

## Scope

P1-52 adds nullable `latest_usage_event` to internal
`GET /knowledge/assets/{asset_id}` detail. The summary lets reviewers see the
latest proposal/correction reuse signal before opening paginated usage-events.

## Ancestry Check

```text
git merge-base --is-ancestor main HEAD
```

Result: exit 0.

```text
git rev-list --left-right --count main...HEAD
```

Result: `0 1`.

The branch is a fast-forward candidate from local `main@88b8128`.

## Verification Evidence

Already recorded in
`docs/decisions/P1-52-knowledge-detail-usage-summary.IMPLEMENTATION-20260703.md`:

- RED/GREEN target tests
- related KnowledgeAsset/API/OpenAPI subset: 12 tests OK
- `make ci`: 599 primary unittest tests OK / 4 skipped, 12 eval OK, threshold
  report passed, OpenAPI up to date
- PostgreSQL `ci-local-full`: 599 primary unittest tests OK, 12 eval OK,
  threshold report passed, OpenAPI up to date, full local CI parity passed

## Dirty-State Check

```text
git status --short --branch
```

Result before this readiness record:

```text
## codex/p1-52-knowledge-detail-usage-summary-20260703
?? .agent_runs/
```

Only generated local `.agent_runs/` output was untracked.

## Boundary

- Local ff-only merge only; no push, no release.
- Internal-only and read-only.
- No raw trace payloads, raw run parameters, source asset content, related
  knowledge content, tool names on detail summaries, correction payloads,
  metric_deltas, or secret-like fields.
- No lifecycle/version/retrieval/feedback/adoption mutation.
- No SQL Safety/EvidenceChain/Approval bypass.
- No causal/value attribution claim, autonomous-core/G10 validation claim, or
  R4/R5 automatic execution.
