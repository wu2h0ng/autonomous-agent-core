# P1-29 Knowledge Rationale Review Surface Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Target: deployment local `main`
Status: ready for founder/CTO-authorized local ff-only merge; not merged; not
pushed; not released

## Scope

P1-29 adds safe internal `review_rationale_codes` to
`GET /knowledge/assets/quality-summary` items. The codes are derived from
existing aggregate `quality_status` only:

- `unused_context_candidate`
- `proposal_context_needs_outcome`
- `outcome_supported_context`
- `adoption_supported_context`

This packet records merge readiness only. It is not merge authorization.

## Git Readiness

Commands run from deployment repo:

```bash
git merge-base --is-ancestor main codex/p1-29-knowledge-rationale-review-surface-20260703
echo ancestor=$?
git rev-list --left-right --count main...codex/p1-29-knowledge-rationale-review-surface-20260703
```

Result:

```text
ancestor=0
0 1
```

Main and feature worktree status both contained only untracked `.agent_runs/`
output. No tracked unstaged or staged changes were present at readiness check.

## Verification Evidence

Branch commit:

```text
7379c8d feat(knowledge): explain review rationale codes
```

RED before implementation:

```text
KeyError: 'review_rationale_codes'
AssertionError: Items in the second set but not the first:
'review_rationale_codes'
```

Targeted tests after implementation:

```text
Ran 3 tests in 0.270s
OK
```

Related service/API/OpenAPI suite:

```text
Ran 9 tests in 0.376s
OK
```

Branch-local `make ci`:

```text
Ran 590 tests in 3.329s
OK (skipped=4)
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

Branch-local PostgreSQL `ci-local-full`:

```text
Ran 590 tests in 3.493s
OK
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Boundary

The slice is internal and read-only. It does not expose the route to
`external_report`, expose KnowledgeAsset title/content/full related knowledge,
expose raw historical trace ids, raw trace payloads, raw reasons, score
breakdowns, correction payloads, metric deltas, or secret-like fields.

It does not mutate lifecycle/version/retrieval/feedback/adoption state, lower
SQL Safety/EvidenceChain/Approval, promote adoption/value, write feedback,
change connector routing, claim causal attribution/value, claim autonomous-core
or G10 product validation, or allow R4/R5 automatic execution.

## Required Post-Merge Gate

If founder/CTO authorizes the merge:

1. Run `git merge --ff-only codex/p1-29-knowledge-rationale-review-surface-20260703`
   from deployment local `main`.
2. Run post-merge `make ci`.
3. Run post-merge PostgreSQL `ci-local-full`.
4. Record `P1-29-knowledge-rationale-review-surface.POST-MERGE-VERIFY-20260703.md`.
5. Update `docs/CURRENT_STATE.yaml` to local-main verified.
