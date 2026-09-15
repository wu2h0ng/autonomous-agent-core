# SPINE-1 Data Agent Donor — Retirement Runbook

> Status: `PROPOSED / EXECUTION_NOT_AUTHORIZED`
> Date: 2026-09-15
> Authority: `docs/adr/ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md` (must be accepted first)
> Donor: `ai-native-business-data-agent-os` (pin `aaea36c694adb04664ff30fddccb43c2eb6a6614`)

This is the mechanical procedure to retire the donor **after** authorization. It changes nothing by
itself. Do not run any phase until Phase 0 preconditions are all signed.

## Phase 0 — Preconditions (all required)

| # | Gate | How verified |
|---|---|---|
| 1 | ADR-0060 accepted by founder; final ADR number assigned | signature block in the ADR |
| 2 | ADR-0054 G0-G7 each recorded as accepted | gate ledger |
| 3 | Manifest gate green | `python3 scripts/check_spine1_donor_manifest.py --strict` → `retirement_ready: True` (all `EXTRACT*` entries carry existing `verified_paths`) |
| 4 | All `EXTRACT*` modules actually ported (not just invariant tests) | the ~35 currently-unported entries credited via `verified_paths` |
| 5 | Secret/PII full-history scan PASS | `gitleaks` report + digest (done: 0 findings) |
| 6 | Boundary + regression re-run on the integration branch | 0 `os_core`→`domain_packs` imports; no new failures |
| 7 | `D-WORKSPACE` reconciled with `M-WORKSPACE = REUSE_PRODUCT_SHELL` | founder decision recorded |
| 8 | Four founder authorizations: retirement, push-of-main, merged-capability claim, release | dated decision records (each separate) |
| 9 | Independent-provider review of the extraction | reviewer identity ≠ builder/provider |

## Phase 1 — Freeze (reversible)

1. In the donor repo, set `docs/CURRENT_STATE.yaml` status to `DEPRECATED / FROZEN / READ-ONLY
   REFERENCE` and record the freeze date + authority.
2. Announce freeze: no new feature branches, commits or releases on the donor.
3. Do **not** delete anything yet.

## Phase 2 — Provenance + safety record (reversible)

1. Record the donor pin and a provenance manifest (already: `SPINE-1-donor-file-snapshot-2026-09-15.txt`).
2. Attach the secret/PII scan report + digest (already: `SPINE-1-DONOR-SECRET-PII-SCAN-2026-09-15.md`).
3. Record the imported ancestry (`78f4f613` add, `43ccbec5` retire staging) and old→new mapping.

## Phase 3 — Archive mechanics (IRREVERSIBLE; founder-authorized only)

1. `git -C ai-native-business-data-agent-os tag -a archive/data-agent-donor-2026-09-15 -m "Final donor archive" <pin>`
   (annotated tag; never move it).
2. Set the donor remote to **read-only/archived** (GitHub: Archive repository). Keep the remote; do not
   delete it — the archive must remain cloneable.
3. Add `RETIRED.md` at the donor root: what it was, its successor (`domain_packs/data_agent`), the
   pin, the scan digest, and "historical, non-authoritative".
4. Remove donor worktrees and **feature** branches from the active workspace (keep `main` + the archive
   tag). Do **not** rewrite donor history.
5. In the monorepo, do **not** delete the migration provenance (it is the audit trail).

## Phase 4 — Redirect references

1. Update `autonomous-agent-core/docs/CURRENT_STATE.yaml`: `physical_transition` → `DONOR_RETIRED`
   with the archive tag and receipt.
2. Update root `docs/CURRENT_STATE.yaml` + `docs/GOAL-BLUEPRINT.md` §7 physical topology and
   `README.md`/`code_index.md`.
3. Update `docs/FAQ-Dev.md` and `RR-0004-artifact-map.md` (they currently say "physically independent").
4. Mark ADR-0054 §1 donor-retirement clause closed; cross-link ADR-0060.

## Phase 5 — Verification

1. `python3 scripts/check_spine1_donor_manifest.py --strict` → `retirement_ready: True`.
2. `rg` the monorepo + root for live references to `ai-native-business-data-agent-os`; each must be a
   historical/immutable reference, not a live dependency.
3. Targeted + full `tests/product` re-run; no new failures.
4. Confirm the archive tag resolves and the remote is read-only.

## Rollback

- Phases 1-2: un-freeze; no repository truth changed.
- Phase 3 before remote archive: delete the tag, restore worktrees/branches.
- After the remote is archived: un-archive the remote; the donor history is intact (no rewrite), so the
  archive is reversible and the staging provenance is unaffected.

## Explicit non-goals

This runbook does not: rewrite donor history, delete donor history, authorize merge/push/release,
weaken C7, or turn the extraction into a product-capability claim. Each remains a separate gate.

## Sign-off

| Role | Identity | Date | Decision |
|---|---|---|---|
| Founder / CTO | | | |
| Independent reviewer (provider ≠ author) | | | |
| Security (secret/PII) | | | |
