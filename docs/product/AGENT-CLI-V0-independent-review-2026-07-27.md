# Independent exact-diff review — Agent CLI V0 + P1 + streaming

> Date: 2026-07-27
> Reviewer identity: Cursor Security Review + Bugbot (independent of writer session)
> Branch: `codex/agent-cli-v0-20260727`
> Exact head: `9542a87adf6eb8d7a44d620b5609e5c2f22fabb0`
> Merge-base (`origin/main`): `675749ba95b2eeb73c268e6a6a95f916758515e0`
> Diff scope: `675749ba...9542a87` (committed branch changes; working tree clean of product code)
> Request: `docs/product/AGENT-CLI-V0-independent-review-request-2026-07-27.md`
> Verdict vocabulary: `APPROVE` / `APPROVE_WITH_BASELINE_DEBT` / `REVISE_TO_SPEC` / `NO_APPROVE`

## Verdict

**`APPROVE_WITH_BASELINE_DEBT`**

Governed SE-organ path, Mandate binding, resume mandate/workspace checks, shell
exact allowlist, `.agent_os` reservation, and SSE streaming credential handling
pass independent security review with **no medium+ findings**.

Baseline debt remains on headless `-p` confirmation policy vs documented intent,
session/database binding on resume, and resume run-activity checks. These do
**not** authorize merge/release/usable-alpha/Autonomy claims by themselves.

## Security review (summary)

No medium / high / critical issues under the local single-user Agent CLI threat
model.

| Check | Result |
| --- | --- |
| Synthetic terminal-minted permits | Not found; PolicyKernel → permit → broker only |
| Model text → workspace effect without proposal/policy | Not found |
| Shell / workspace escape | Exact allowlist + `_safe_path`; `.agent_os` reserved |
| Resume invents authority | Not found; mandate_id + repo_root + task/run match |
| SSE secret leakage | Not found; deltas are content only |
| Credential persistence/logging | Not found in this diff |
| Trusted command bypass | Not found |

Optional non-blocking notes: AWL `risk_tier` vs capability floor; persist
database path on resume for operator misconfig defense.

## Bugbot / technical findings

| Severity | Location | Finding | Disposition |
| --- | --- | --- | --- |
| high | `apps/cli/__main__.py:69-72` | One-shot `-p` uses `NonInteractiveDenyGateway`, so `workspace.edit` / `apply_patch` (tier 2) always reject. Contradicts `AutoApproveGateway` docstring (“for `-p` runs”) and makes the fixture’s `agent -p "…edit…"` path non-viable without a separate AutoApprove harness. | **Baseline debt** — fail-closed is safer than silent auto-edit; product intent for one-shot SE work is underspecified. Fix before claiming CLI `-p` can complete edit fixtures. |
| high | `agent_cli.py` resume / `ensure_local_mandate_session` | Sidecars keyed by workspace only; `--database` not bound/checked against attach or saved session. | **Baseline debt** — local misconfig risk; not cross-tenant authority forgery in the stated threat model. |
| medium | `agent_cli.py:148-150` | Resume checks `run_id` match only; does not require run still `RUNNING` / not correction-halted. | **Baseline debt** — may resume a logically dead run until provider/tool halt surfaces. |

## Must-verify (from review request)

1. No synthetic permits — **PASS**
2. Model output needs `ProviderToolProposal` + policy — **PASS**
3. Resume does not invent authority / skip Task/Run sealing — **PASS** (with DB-binding debt above)
4. Clock-fixed `ensure_local_mandate_session` — **PASS** (prior remediation retained)
5. `chat` alias; product entry `agent` — **PASS**
6. No MCP / arbitrary shell / AWL rewrite smuggled — **PASS** (trusted exact allowlist only)

## Evidence pin

- Targeted tests claimed locally: terminal + v0 + p1 + stream ⇒ 40 passed (writer evidence; not re-run by this review)
- Live DeepSeek narrow fixture: prior green via harness (`LIVE_PROVIDER_NARROW_VERIFIED`); **not** proof that stock `agent -p` auto-approves edits
- Claim ceiling remains: `IMPLEMENTED_LOCAL / TARGETED_TESTED / REVIEWED_WITH_BASELINE_DEBT` — **not** usable-alpha / release / Autonomy

## Required before stronger claims

1. ~~Decide and implement one-shot policy~~ — **REMEDIATED 2026-07-27**: `-p` uses `AutoApproveGateway` (tier&lt;3); shell still headless-denied.
2. ~~Bind `database`~~ — **REMEDIATED**: `agent-cli-session.v1` + attach/database mismatch fail-closed.
3. ~~Resume reject halted/terminal~~ — **REMEDIATED**: status + `correction.halted` checks.

See `docs/product/AGENT-CLI-V0-review-debt-remediation-2026-07-27.md`. Original verdict remains historical; debt items above are closed locally pending optional delta re-review / merge authorization.

## Out of reviewer authority

Push, merge, release, usable-alpha, Autonomy(`S,E,O,V,T`).
