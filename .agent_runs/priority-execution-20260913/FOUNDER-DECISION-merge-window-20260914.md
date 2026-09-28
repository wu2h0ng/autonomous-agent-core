# Founder Decision Packet — origin/main Merge Window + One Refresh-Merge

> Status: `AUTHORIZED_BY_FOUNDER 2026-09-14` / `one refresh-merge`
> Owner: Founder (authorizes) / CTO cast (executes)
> Repo: `wu2h0ng/autonomous-agent-core` (origin https)
> Purpose: stop the rebase-treadmill by defining one coordinated window to refresh and merge the two independently approved integration candidates.

## 1. Problem

`origin/main` is advancing every few minutes (observed e2564ecb → ecc82b13 → fcbe6ef9 → 3c8d858e → aeb88c73 within one session) while the two approved candidates are built off earlier tips. Each refresh changes the exact head SHA, which strictly requires review re-binding. Without a window, refresh + re-review never converges.

## 2. Freeze window

- Pin `origin/main` at its tip at window open (`git rev-parse origin/main`), recorded in the merge receipt.
- All other writers pause pushes to `main` for the duration of the window (or the merge is retried on the new tip; pushes are non-force, so a race is rejected, never destructive).
- Window closes when both candidates are refreshed, gated, re-confirmed and pushed — or aborts.

## 3. Candidates (already cross-provider approved)

| Candidate | Branch | Approved code head | Base |
|---|---|---|---|
| Contract inference | `feature/contract-inference-onto-main-20260913` | `8f4e302d` | origin/main `fcbe6ef9` |
| SRL TaskActivationGate | `feature/srl-closed-loop-1-20260913` | `27854701` | origin/main (rebased) |

Both hold an OpenAI gpt-5.5 cross-provider APPROVE. The contract-inference head is a content-preserving port of the earlier approved `cac7cdc3`; the SRL head is a content-preserving rebase of `a2634d81` (delta hash `5d7e5f8e...`).

## 4. Procedure (one refresh-merge)

For each candidate, on a scratch branch off the pinned `origin/main`:
1. `git fetch origin` ; pin `PIN=$(git rev-parse origin/main)`.
2. Rebase the candidate onto `PIN` (content-preserving; conflicts require a port + fresh review).
3. Run gates: `uv run --extra product-test --extra tui pytest tests/product -q` ; `ruff check` ; `pyright`; compare failures against a same-pin `origin/main` baseline — require zero new failures.
4. Cross-provider re-confirmation of the rebased head (content-delta hash equality + the slice's key invariant).
5. Non-force fast-forward/merge to `main`; push. If rejected (remote advanced), re-pin and repeat — never force-push.
6. Record a merge receipt: pin, candidate head, gate results, reviewer identity, push result.

## 5. Explicit boundaries

- Non-force push only; never rewrite `origin/main` history.
- The two candidates are independent; either may be merged or held separately.
- No release/tag/deploy follows from this merge.
- Deferred non-blocking items stay documented, not silently bundled.
- If a rebase conflicts, stop and treat as a port (fresh review), not a mechanical merge.

## 6. Recorded authorization

Founder instruction 2026-09-14: "给 origin/main 设一个合并窗口/冻结并授权一次刷新合并."
