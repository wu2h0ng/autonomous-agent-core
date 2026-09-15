# ADR-DRAFT-0060: Data Agent Donor Repository Retirement

- Status: **PROPOSED / DRAFT — NOT ACCEPTED. This ADR authorizes nothing until the founder accepts it.**
- Date: 2026-09-15
- Deciders: founder (decision pending); drafted by an agent under founder instruction
- Claim class: `product-architecture` / `repository-lifecycle`
- Target track: Product Track
- Authority chain: `docs/adr/ADR-0054-one-time-data-agent-history-migration.md` (parent) > this draft
- Related: `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`, `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`, `docs/adr/ADR-0057-adaptive-domain-materialization-and-optional-priors.md`, root `docs/GOAL-BLUEPRINT.md`
- Supersedes / closes: the "donor-repo retirement" gate named in ADR-0054 and in root/agent-os `docs/CURRENT_STATE.yaml`

> Drafting note: this file intentionally uses the `ADR-DRAFT-` prefix and does not take a final ADR
> number, because (a) it is not accepted and (b) the root repository already has an `ADR-0060`
> (terminology alignment). Assign the final agent-os number at founder acceptance.

## Context

ADR-0054 authorized exactly one bounded, history-safe migration of the Data Agent donor
(`ai-native-business-data-agent-os`) into the Agent OS monorepo, and reserved four independent
gates: push-of-main authorization, any merged-capability claim, **donor-repo retirement**, and
release. It explicitly permitted removing the `_migration/data-agent-os` staging tree after accepted
extraction, but it did **not** authorize retiring the donor repository itself.

Dated live measurement (2026-09-15T02:22+08:00, agent-os `origin/main = a0c7a604`):

- The history-preserving import (`78f4f613`, source donor commit `94e2b5918`), the bounded G5/G6
  extraction (`7ba65659..dca62052`, closed by `fde801a6`) and the staging removal (`43ccbec5`) are
  reachable from `origin/main`. `domain_packs/data_agent` exists on `origin/main` (10 files) plus
  `apps/api_server/data_agent_*` and 14 `tests/product/*data_agent*`.
- **However, the extraction is bounded, not complete.** The donor still holds ~799 tracked files
  that have no monorepo equivalent, including its 44 `packages/os_core` modules (`nl_query`,
  `semantic_runtime`, `data_product_compiler`, `knowledge_memory`, `query_runtime`,
  `data_access_plane`, `metric_contract_loader`, `embedding`, `eval_hub`, …), `apps/workspace`,
  `packages/persistence`, `packages/sdk`, `tests`, and `domain_packs/content_commerce`.
- The donor still carries `DEPLOYMENT_PUSH: HOLD`, and its only product-value execution
  (Customer-0) is `BLOCKED_AWAITING_FOUNDER_OPERATOR_INPUT`.
- No artifact records that the ADR-0054 execution gates G0-G7 and the four retirement gates were
  formally opened; reachability of commits is not authorization.

Therefore the naive reading ("the seam is on main, so the donor is redundant") is false. Retiring
the donor now would strand the majority of the standing Data Agent implementation with no target
owner and no provenance.

## Options Considered

### A. Retire the donor repository now (archive or delete)

- Cost: strands ~799 unmigrated files; destroys the only complete Data Agent implementation and the
  Customer-0 validation environment; unconsummated extraction becomes an un-ownable gap.
- Benefit: one fewer repo to maintain.
- C1–C7 compatibility: not unsafe by itself, but it converts an incomplete migration into an
  irreversible loss and would hide the incompleteness — a governance failure.
- Strongest counter-argument: if the monorepo is the only product body, keeping a second runtime
  invites drift. Accepted, but that argues for a *staged* retirement with exit criteria, not an
  immediate deletion.

### B. Permanent dual-repository operation (donor stays a second product runtime)

- Rejected by ADR-0054 Option B analysis (duplicate authority, version skew, operational overhead)
  and by GOAL-BLUEPRINT §7. Also keeps two divergent Data Agent implementations indefinitely.

### C. Freeze the donor and retire it only after a verified extraction-completeness gate

- Freeze donor `main` (no new feature work), declare it `DEPRECATED / READ-ONLY REFERENCE`,
  complete ownership-complete extraction of what remains useful, then archive with an audit
  tombstone and remove it from the active workspace.
- Cost: carries a bounded window of two-repo existence and one final extraction effort.
- Benefit: no stranded implementation; honours ADR-0054 gates; keeps provenance auditable.
- Recommended.

### D. Full absorption (extract every generic + domain capability) then retire in one step

- This is the same target as C but collapses the sequencing. Higher risk: a single large migration
  with no intermediate rollback point, and it would pull generic donor runtime into Agent Core,
  risking domain coupling (AGENTS.md Hard Boundary #3).

## Decision (PROPOSED — requires founder acceptance)

Adopt **Option C**, staged:

1. **Now (freeze, reversible):** mark the donor `DEPRECATED / FREEZE / READ-ONLY REFERENCE` in its
   own `docs/CURRENT_STATE.yaml`; stop all feature work; keep its history intact. This step changes
   no capability claim and is reversible.
2. **Extraction-completeness phase:** produce a machine-readable owner-completeness manifest that
   maps every donor file/module to one of: (a) already extracted into `domain_packs/data_agent`,
   (b) extractable to a domain-neutral `packages/*` target with a dependency-direction check,
   (c) intentionally retained as donor-only history, or (d) intentionally dropped with rationale.
   No generic donor module may enter `packages/os_core` if it carries Metric/SQL/DataProduct/
   business-action semantics (keep them in the domain pack).
3. **Verification phase:** prove behavior parity and boundary correctness before any retirement
   (see Preconditions).
4. **Retirement phase (irreversible):** archive the donor (read-only + annotated tag + provenance
   digest + audit tombstone), remove its worktrees/branches from the active workspace, and
   re-point docs/indexes to the monorepo. **No history rewrite.** Then, and only then, update root
   and agent-os CURRENT_STATE to record donor retirement as closed.

Explicitly out of scope for this ADR: authorizing the push/merge capability claim, release, or any
production activation. Those remain separate gates.

## Preconditions / exit criteria (all required before step 4)

1. ADR-0054 gates G0-G7 are each recorded as accepted, not merely reachable.
2. The owner-completeness manifest (step 2) is complete and independently reviewed; zero donor
   files are unowned or unexplained.
3. Behavior parity: the extracted Data Agent path passes its characterization/safety tests
   (SQL safety, evidence lineage, approval/trace negative cases) against the monorepo spine.
4. Boundary checks pass: no `packages/os_core` import from `domain_packs`; no domain semantics in
   core contracts; no runtime import from donor or `_migration`.
5. Git/provenance: import ancestry and old-to-new mapping (if a filtered mirror was used) verified;
   no secret/PII blob reachable in Agent OS history.
6. **Customer-0 or a named replacement validation environment has an explicit disposition —
   RESOLVED 2026-09-15:** the founder withdrew the Customer-0 lane and stated that this validation
   is not required. There is no replacement validation environment. This is a recorded founder
   decision, not a silent drop. No customer/commercial validation claim will be produced.
7. Founder authorization recorded for: donor retirement, push-of-main, merged-capability claim, and
   release (each separate). Independent reviewer identity ≠ drafter/implementer.

## Consequences

- While staged, the donor is frozen but still exists; it is neither a product runtime nor a target
  for new work.
- Generic donor code that is safe to promote must be re-homed without domain coupling; unsafe or
  domain-specific code stays in `domain_packs/data_agent`.
- The monorepo becomes the single product authority only after step 4; until then, "merged
  capability" claims remain forbidden.
- Historical success of the donor product still does not validate any Research Track autonomy claim.

## Non-claims

- This draft does not retire the donor, does not authorize push/merge/release, and does not claim
  the migration is complete.
- Reachability of the seam on `origin/main` is a dated Git fact, not founder authorization.
- No autonomy, general-intelligence, or product-superiority claim follows.

## Rollback

- Steps 1-3 are reversible: unfreeze the donor, discard partial extraction on an unpublished branch.
- Step 4 is intentionally irreversible; it may proceed only after every precondition holds and the
  founder records explicit approval. If a secret/sensitive blob is later found in agent-os history,
  follow ADR-0054 §5 (stop, rotate, filtered mirror, incident record) before any further retirement.

## Verification and review

- Owner-completeness manifest `docs/architecture/SPINE-1-DONOR-OWNER-COMPLETENESS-MANIFEST.yaml` with
  checker `scripts/check_spine1_donor_manifest.py`: structural coverage passes (799/799 donor files,
  exactly one disposition each, 0 unmatched, 0 ambiguous, donor pin verified). `--strict` still fails
  closed because ~35 `EXTRACT*` entries declare no `verified_paths` — the module extraction is **not
  yet executed**, so the gate is red. Readiness is tracked in
  `docs/architecture/SPINE-1-RETIREMENT-READINESS-2026-09-15.md`; subagent review rounds 1-3 returned
  REVISE and their corrections are incorporated.
- Machine-readable manifest + completeness checker; dependency-direction and boundary searches.
- Independent review of the manifest, parity tests and provenance.
- Founder approval record appended below at acceptance.

## Approval record

_Pending. Not accepted. Drafted 2026-09-15 by an agent; requires founder decision and independent
review before any effect._
