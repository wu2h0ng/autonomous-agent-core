# Review Specification

Authoritative inputs:

- `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`
- `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`
- `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`
- `docs/migration/SPINE-1-CAPABILITY-OWNERSHIP.yaml`
- `docs/migration/SPINE-1-PROVENANCE-MANIFEST.yaml`
- `/Users/mima1234/Documents/AI-Agent-Projects-convergence-design-20260811/docs/superpowers/specs/2026-08-11-agent-os-portfolio-convergence-design.md`
- `/Users/mima1234/Documents/AI-Agent-Projects-convergence-design-20260811/docs/superpowers/plans/2026-08-11-agent-os-data-agent-convergence-implementation.md`

Required invariants:

1. Data semantics stay in `domain_packs/data_agent`; generic authority remains in shared Agent OS packages.
2. No Product Runtime import from `_migration`, donor repository paths, `src/aac`, or `experiments`.
3. Safe query input is AST-validated before provider/capability execution and tenant/run/outcome authority is server-bound.
4. Evidence confidence is conservative and provenance-bound.
5. Business action is proposal-only and cannot execute a connector.
6. Report observation has one runtime owner while compatibility imports do not create divergent module state.
7. Unknown external effects remain fail-closed and durable; retry does not silently resend.
8. Staging removal preserves approved donor ancestry and recoverability.
9. Claims remain local, unpushed, unmerged, unreleased, and do not imply production, commercial validation, self-improvement, general intelligence, or `Autonomy(S,E,O,V,T)`.
