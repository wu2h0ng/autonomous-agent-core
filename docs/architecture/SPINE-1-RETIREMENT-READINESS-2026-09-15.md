# SPINE-1 Donor Retirement — Readiness Ledger

> Status: `DATED_SNAPSHOT / NOT_AUTHORIZATION`
> Date: 2026-09-15
> Donor pin: `aaea36c694adb04664ff30fddccb43c2eb6a6614` (ai-native-business-data-agent-os)
> Target monorepo measurement: agent-os `origin/main = a0c7a604` (2026-09-15T02:22+08:00)
> Authorities: `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`,
> `docs/architecture/SPINE-1-DONOR-OWNER-COMPLETENESS-MANIFEST.yaml`,
> `docs/adr/ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md`

This ledger tracks the retirement preconditions from the retirement ADR draft. It is a measurement,
not an approval. "Reachable on origin/main" is never treated as authorization.

## Precondition status

| # | Precondition (ADR draft) | Status | Evidence / blocker |
|---|---|---|---|
| 1 | ADR-0054 gates G0-G7 recorded as accepted | **OPEN** | Only "reachable on origin/main" is measured; no artifact records the gates as accepted. |
| 2 | Owner-completeness manifest complete + independently reviewed | **PARTIAL_VERIFIED 2026-09-15** | Every entry `REVIEWED`, all `SPLIT` resolved; **12 entries credited via declared `verified_paths`** (the 6 implemented capabilities, the provenance docs, and 3 pre-existing extracted files). But **~35 module `EXTRACT*` entries are not yet ported** and a bare directory target is no longer credited (`retirement_ready: False`), reviews are same-provider, and the governance artifacts are untracked. |
| 3 | Behavior parity on extracted Data Agent path | **PARTIAL_VERIFIED 2026-09-15** | 49 new bypass tests pass; full `tests/product` on the branch: 2610 passed, 1 skipped, 24 failed — all 24 pre-existing fixed-NOW expiry/env failures in unrelated files. Full donor-vs-monorepo characterization replay not run. |
| 4 | Boundary checks (no `os_core` ← `domain_packs`, no domain semantics in core, no donor/`_migration` runtime import) | **VERIFIED_ON_BRANCH 2026-09-15** | 0 `os_core`→`domain_packs` imports; 0 real cross-repo imports; the only core-domain-term hit is a docstring disclaimer. Domain→core is the allowed direction. See `docs/architecture/provenance/SPINE-1-EXTRACTION-VERIFICATION-2026-09-15.md`. |
| 5 | Git/provenance + no secret/PII blob reachable | **RESOLVED 2026-09-15** | `gitleaks` 8.30.1 full-history scan: 507 commits, **0 findings (PASS)**, redacted report digest `37517e5f…`. No LFS, no >500KB files, no binaries; no real customer PII (placeholder domains only). See `docs/architecture/provenance/SPINE-1-DONOR-SECRET-PII-SCAN-2026-09-15.md`. |
| 6 | Customer-0 (or replacement validation env) explicit disposition | **RESOLVED 2026-09-15** | Founder withdrew the Customer-0 lane ("not required"). Recorded decision, not a silent drop; task pack removed, ledger retained; no replacement validation environment and no customer/commercial claim. |
| 7 | Founder authorization for retirement + push/merge-capability/release | **OPEN** | Founder-reserved. Four separate gates, none recorded as open. |

## Execution ledger (founder-directed, 2026-09-15)

Branch `codex/spine1-donor-extraction-20260915` (from `origin/main`), 8 commits, **not pushed/merged**:

1. `083d2ddc` re-home 18 donor provenance decisions (`HISTORICAL_NON_AUTHORITY`).
2. `34994240` `ConsequencePreview` contract + `ActionHistoryPort` / `build_consequence_preview` + 9 bypass tests (ADR-0016).
3. `f0f08891` approval `ApprovalChoiceSet` contract + REVISE discipline + 13 bypass tests (ADR-0014).
4. `4a3731b0` execution-time C7 recheck parity test (ADR-0005).
5. `91cc3ec3` evidence lineage: recency-tau parsing, typed completeness, semantic lineage + tests.
6. `9247b6c5` non-bypassable grounding invariant + tests (P5.1b).
7. policy-approval record lifecycle + tests (R4/R5).
8. `6aad9e3f` donor secret/PII scan (`gitleaks` PASS) + boundary/regression evidence.

All manifest `EXTRACT*` targets are now present; `--strict --target-ref codex/spine1-donor-extraction-20260915` reports `retirement_ready: True`.

- **Customer-0 withdrawn**; unrun task pack removed, ledger retained.
- Boundary checks: see precondition 4. Secret/PII full-history scan: **RESOLVED** (gitleaks PASS).
- Open founder item: `D-WORKSPACE` reconciliation with `M-WORKSPACE = REUSE_PRODUCT_SHELL`.
- The manifest gate is now honest about the remaining work: only entries with declared
  `verified_paths` are credited, so the ~35 module EXTRACT entries that are **not yet ported** keep
  the gate **red** (`retirement_ready: False`).

## Manifest summary (799 donor files, exactly one disposition each)

| Disposition | Files |
|---|---|
| `RETAIN_AS_HISTORY` | 578 (donor ADR ledger, architecture reviews, project baseline, tests, scripts) |
| `EXTRACT_TO_DOMAIN_PACK` | 91 (data compiler/access/NL/semantic/query, persistence, connectors, api_server, content_commerce) |
| `DROP_SUPERSEDED` | 62 (donor workspace frontend) |
| `EXTRACT_TO_PACKAGE` | 38 (generic contracts/sdk + os_core runtime candidates) |
| `DROP_OPERATIONAL` | 26 (CI, containers, build, repo scaffolding) |
| `EXTRACTED` | 4 (sql_safety, evidence, report, governance seam) |

## What "before retirement" concretely requires next

1. **Execute the accepted extractions** (domain-neutral → `packages/*`; domain → `domain_packs/data_agent`;
   invariants → `tests/product/*`; provenance docs → `docs/architecture/provenance/` and
   `domain_packs/data_agent/docs/provenance/`) with dependency-direction and domain-independence
   checks. The manifest now resolves every file to a concrete owner, so this is execution, not
   design. It is a cross-repo migration and is **founder-gated** (AGENTS.md §7; ADR-0054 §4).
2. **Reconcile the open D-WORKSPACE founder item**: the manifest now retains the donor UI as history,
   but `M-WORKSPACE = REUSE_PRODUCT_SHELL` in the migration map still points at `apps/workspace`,
   which does not exist on `origin/main`. The founder must decide reuse vs capability reduction.
3. **Run the parity, boundary and secret/PII checks** and attach the digests.
4. **Resolve Customer-0** and record the four founder authorizations.

## How to check

```bash
# structural coverage (must be 0 unmatched / 0 ambiguous)
python3 scripts/check_spine1_donor_manifest.py

# retirement gate (must exit 0 before any retirement)
python3 scripts/check_spine1_donor_manifest.py --strict --require-targets

# offline (no donor checkout): uses the pinned snapshot automatically
python3 scripts/check_spine1_donor_manifest.py --files-from docs/architecture/SPINE-1-donor-file-snapshot-2026-09-15.txt
```

`--strict` currently exits 1: ~35 `EXTRACT*` entries declare no `verified_paths` and are therefore
**not credited** (a bare directory target never counts). That is the intended fail-closed behavior:
the donor is **not** retireable because the module extraction has not been executed. Only entries
with declared, existing `verified_paths` are counted.

## Review round 3 (subagent, 2026-09-15)

All 7 `SPLIT` entries resolved into concrete file-level owners:

- `D-OSCORE-QUERYRUNTIME` / `D-OSCORE-KNOWLEDGE` / `D-OSCORE-CONVERSATION` → `EXTRACT_TO_DOMAIN_PACK`
  (generic part not separable at file granularity).
- `D-APISERVER` → split into domain pack (9 files), app/composition layer `apps/api_server` (2),
  `packages/os_core` heavy-infra adapter (1), `DROP_SUPERSEDED` (3), `DROP_OPERATIONAL` (1),
  `RETAIN_AS_HISTORY` (1).
- `D-WORKSPACE` → `RETAIN_AS_HISTORY` (runnable shell + e2e closed loop + prototype) +
  `DROP_OPERATIONAL` (5 hygiene files); **open founder item** to reconcile with
  `M-WORKSPACE = REUSE_PRODUCT_SHELL`.
- `D-TESTS` → bulk `RETAIN_AS_HISTORY` + 6 invariant-only carve-outs (grounding, exec-time governance
  recheck, consequence preview, choice-set, policy-approval lifecycle, evidence lineage).
- `D-DOCS` → bulk `RETAIN_AS_HISTORY` + 12 generic-invariant decisions + 6 domain-behavior decisions.

## Review round 2 (subagent, 2026-09-15)

The remaining 33 entries were checked against monorepo `origin/main` + donor code. Four BLOCKERs
found and applied to the manifest:

- **D-OSCORE-GOVSEAM** was recorded `EXTRACTED` to `report_policy.py`; the reviewer falsified this —
  `report_policy.py` is an unrelated external-report envelope and no governance seam exists in the
  monorepo. Reclassified `EXTRACT_TO_PACKAGE` (generic Product-core governance).
- **D-CONTRACTS** as `packages/contracts/**` would have injected Metric/SQL/DataProduct/business-action
  semantics into Product core. Split into `D-CONTRACTS-GENERIC` (`EXTRACT_TO_PACKAGE`) and
  `D-CONTRACTS-DOMAIN` (`EXTRACT_TO_DOMAIN_PACK`).
- **D-SDK** target `packages/sdk` does not exist and the surface is a thin domain-pack loader already
  superseded by `DomainPackManifest` → reclassified `DROP_SUPERSEDED`.
- **D-WORKSPACE** `DROP_SUPERSEDED` contradicted the parent migration map `M-WORKSPACE =
  REUSE_PRODUCT_SHELL` and would strand the only UI→public-API e2e evidence → reclassified `SPLIT`.

Also reclassified: `EMBEDDING`/`EVALHUB`/`FEEDBACK`/`ADOPTION` → `EXTRACT_TO_PACKAGE` (generic
primitives that must not enter the domain pack); `QUERYRUNTIME`/`KNOWLEDGE`/`CONVERSATION`,
`D-APISERVER`, `D-TESTS`, `D-DOCS` → `SPLIT`; `D-PERSISTENCE` → `DROP_SUPERSEDED`; `D-PROVIDERS` →
`RETAIN_AS_HISTORY` (doc-only).

The 7 `SPLIT` entries from round 2 were resolved in round 3 (see above); the manifest-level blocker
is cleared. Readiness is now blocked only on extraction execution and the founder gates.

## Review round 1 (subagent, 2026-09-15)

Two independent subagent reviewers, read-only, same workspace/provider as the drafter (so
corroboration, not independent-provider adjudication):

- Tooling review → **REVISE**: made `--strict` enforce targets/pin/reviewer-identity, fixed a
  mid-path `**/` glob bug, added recommendation validation and graceful errors, added CLI gate tests.
  All addressed in this revision.
- Owner-claim review → **REVISE**: corrected the low-confidence recommendations (revision 2 above).
  Most consequential unowned capability: the `_assert_grounded` security invariant; most likely
  silent loss: tenant usage/quota metering.
