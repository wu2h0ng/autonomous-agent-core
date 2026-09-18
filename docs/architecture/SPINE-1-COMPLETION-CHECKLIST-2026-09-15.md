# SPINE-1 Donor Migration — Completion Checklist (what's left)

> Status: `ACTIVE / NOT_COMPLETE`
> Date: 2026-09-15
> Owner legend: **[me]** = agent/openCode · **[you]** = founder/CTO · **[rev]** = independent reviewer (provider ≠ author)
> Current reality: work is on branch `codex/spine1-donor-extraction-20260915` (25 commits), **PR #47 OPEN,
> not merged**; `main` has none of it; the donor repo is untouched.

## TL;DR

"Manifest gate green" means every donor file has an owner and the load-bearing domain was extracted.
It does **not** mean the migration is done, and it does **not** mean the donor can be deleted.
To actually finish: **merge → wire → sign gates → independent review → execute the retirement runbook.**

---

## Phase A — Merge the extraction (branch → main)

| # | Task | Owner | Blocked by / evidence |
|---|---|---|---|
| A1 | Independent-provider review of PR #47 | [rev] | no independent reviewer named; all reviews so far are same-provider |
| A2 | Address review findings on the branch | [me] | A1 |
| A3 | Authorize merge of PR #47 into `main` | [you] | A1 + A2 + your merge authorization |

## Phase B — Integrate (make the ported code actually used)

| # | Task | Owner | Blocked by |
|---|---|---|---|
| B1 | Pick the real product path that should consume the Data Agent pack | [you] | no named consumer today (Customer-0 withdrawn) |
| B2 | Wire `domain_packs/data_agent` modules into that entry point (`apps/api_server` / runtime) | [me] | B1 |
| B3 | End-to-end test: real entry → domain capability → evidence/outcome | [me] | B2 |
| B4 | Independent review of the integration | [rev] | B3 |

Note: without B1, the ported modules are `implemented + tested` but **not integrated**.

## Phase C — Record ADR-0054 G0-G7 + the four authorization gates

| # | Task | Owner | Blocked by |
|---|---|---|---|
| C1 | Confirm G0-G7 each "accepted" with evidence pointers | [you] + [me] | evidence collected on the branch; needs your sign-off |
| C2 | Sign the four gates: donor retirement · push of main · merged-capability claim · release | [you] | each separate; none open |

## Phase D — Execute the retirement runbook (`SPINE-1-DONOR-RETIREMENT-RUNBOOK-2026-09-15.md`)

| # | Task | Owner | Blocked by |
|---|---|---|---|
| D1 | Phase 1: freeze donor (mark DEPRECATED / read-only) | [me] | C2 authorization |
| D2 | Phase 3: archive (annotated tag, read-only remote, `RETIRED.md`) | [me] | C1 + C2 |
| D3 | Phase 4: redirect references (root + agent-os `CURRENT_STATE`, `GOAL-BLUEPRINT` §7, `README`, `FAQ`, ADR-0054/0060) | [me] | D2 |
| D4 | Phase 5: verify (strict gate green, no live refs, tests) | [me] | D3 |

## Phase E — Open decisions

| # | Item | Owner | Note |
|---|---|---|---|
| E1 | `D-WORKSPACE` vs migration map `M-WORKSPACE = REUSE_PRODUCT_SHELL` | [you] | manifest vs map contradiction |
| E2 | 11 founder-accepted reductions (`确认全砍`) | [you] | recorded; capability is gone until re-implemented |
| E3 | Real warehouse executors (postgres/mysql/clickhouse/feishu) if ever needed | [me] on demand | each ~100-155 L; not ported |

---

## Sign-offs required (all by founder, separate)

- [ ] Merge PR #47 into `main`
- [ ] ADR-0054 G0-G7 accepted
- [ ] Donor retirement authorized
- [ ] Push of `main` authorized
- [ ] Merged-capability claim authorized
- [ ] Release authorized
- [ ] `D-WORKSPACE` disposition

## One-line status

Extraction: **drafted on a branch (PR #47), not merged, not wired, donor not retired.** The remaining
path is merge → wire → sign → independent review → runbook execution, and most of it needs you or an
independent reviewer, not the agent.
