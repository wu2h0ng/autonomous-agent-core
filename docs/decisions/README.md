# Decisions

Implementation-local ADRs for the Enterprise OS deployment layer.

Current active ADRs:

- `ADR-0001-p5-substrate-harvest.md`
- `ADR-0002-governed-action-outcome-loop-v0.md`
- `ADR-0003-agent-runtime-v0-trusted-substrate.md`
  - Review: `ADR-0003-agent-runtime-v0-trusted-substrate.REVIEW-20260624.md`
  - Remediation: `ADR-0003-agent-runtime-v0-trusted-substrate.CODEX-REMEDIATION-20260624.md`
  - Second review: `ADR-0003-agent-runtime-v0-trusted-substrate.SECOND-REVIEW-20260624.md`
  - A7 reconciliation audit: `ADR-0003-agent-runtime-A7-reconciliation-audit-20260625.md`
  - Checkpoint/trace security review: `ADR-0003-agent-runtime-checkpoint-trace-security.REVIEW-20260625.md`
  - Live `/runs` wiring review: `ADR-0003-agent-runtime-live-wiring.REVIEW-20260625.md`
  - Diagnostics boundary implementation: `ADR-0003-agent-runtime-diagnostics-boundary.IMPLEMENTATION-20260625.md`
  - Diagnostics boundary review: `ADR-0003-agent-runtime-diagnostics-boundary.REVIEW-20260625.md`
  - Success trace bridge implementation: `ADR-0003-agent-runtime-success-trace-bridge.IMPLEMENTATION-20260626.md`
  - Success trace bridge review: `ADR-0003-agent-runtime-success-trace-bridge.REVIEW-20260626.md`
  - Approval execute envelope implementation: `ADR-0003-agent-runtime-approval-execute-envelope.IMPLEMENTATION-20260626.md`
  - Approval execute envelope review: `ADR-0003-agent-runtime-approval-execute-envelope.REVIEW-20260626.md`
  - Reviewed slices consolidation review: `ADR-0003-agent-runtime-reviewed-slices-consolidation.REVIEW-20260626.md`
  - Checkpoint factory selection implementation: `ADR-0003-agent-runtime-checkpoint-factory-selection.IMPLEMENTATION-20260626.md`
  - Checkpoint factory selection review: `ADR-0003-agent-runtime-checkpoint-factory-selection.REVIEW-20260626.md`
  - Budget guard implementation: `ADR-0003-agent-runtime-budget-guard.IMPLEMENTATION-20260626.md`
  - Budget guard review: `ADR-0003-agent-runtime-budget-guard.REVIEW-20260626.md`
  - Stacked merge gate review: `ADR-0003-agent-runtime-stacked-merge-gate.REVIEW-20260626.md`
  - Correction channel scope candidate: `ADR-0003-agent-runtime-correction-channel-scope-20260626.md`
  - Correction channel review: `ADR-0003-agent-runtime-correction-channel.REVIEW-20260627.md`
  - Correction channel merge readiness: `ADR-0003-agent-runtime-correction-channel.MERGE-READINESS-20260627.md`
  - Correction channel post-merge verification: `ADR-0003-agent-runtime-correction-channel.POST-MERGE-VERIFY-20260627.md`
  - Public resume API implementation: `ADR-0003-agent-runtime-public-resume-api.IMPLEMENTATION-20260627.md`
  - Public resume API self-review: `ADR-0003-agent-runtime-public-resume-api.SELF-REVIEW-20260627.md`
  - Public resume API merge readiness: `ADR-0003-agent-runtime-public-resume-api.MERGE-READINESS-20260627.md`
  - Public resume API post-verify: `ADR-0003-agent-runtime-public-resume-api.POST-VERIFY-20260628.md`
  - Public resume API refresh verify: `ADR-0003-agent-runtime-public-resume-api.REFRESH-VERIFY-20260629.md`
  - Public resume API resume-order fix: `ADR-0003-agent-runtime-public-resume-api.RESUME-ORDER-FIX-20260629.md`
  - Public resume API checkpoint-read failure fix: `ADR-0003-agent-runtime-public-resume-api.CHECKPOINT-READ-FAILURE-FIX-20260630.md`
  - Public resume API fresh verify: `ADR-0003-agent-runtime-public-resume-api.FRESH-VERIFY-20260701.md`
  - Public resume API post-merge verify: `ADR-0003-agent-runtime-public-resume-api.POST-MERGE-VERIFY-20260701.md`
  - Capability gap audit: `ADR-0003-agent-runtime-capability-gap-audit-20260626.md`
- `ADR-0004-governed-decision-seam.md`
  - Governed-decision injection seam for RR-0032 R0-R3 RPC boundary.
    Fast-forward merged to deployment local `main@b2225ac` on 2026-07-03 after
    founder/CTO authorization; not pushed or released.
  - Review/remediation: `ADR-0004-governed-decision-seam.REVIEW-20260702.md`
  - Merge readiness: `ADR-0004-governed-decision-seam.MERGE-READINESS-20260702.md`
  - Post-merge verification: `ADR-0004-governed-decision-seam.POST-MERGE-VERIFY-20260703.md`
- `P1-04-eval-threshold-report.IMPLEMENTATION-20260703.md`
  - Eval threshold report surface originally implemented on
    `codex/eval-threshold-report-20260703`; locally merged to deployment
    `main` on 2026-07-03. Not pushed or released.
- `P1-04-eval-threshold-report.MERGE-READINESS-20260703.md`
  - Merge-decision packet for branch-local P1-04 eval threshold report;
    fast-forward readiness checked from local `main@f56054c` to implementation
    head `e652db0`, with docs-only readiness metadata on top. Not merge
    authorization, not pushed, not released.
- `P1-04-eval-threshold-report.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-04 after founder/CTO-authorized
    ff-only merge to `main@4fb4591`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-05-knowledge-review-queue.IMPLEMENTATION-20260703.md`
  - Read-only KnowledgeAsset review queue originally implemented on
    `codex/p1-05-knowledge-review-queue-20260703`; locally merged to
    deployment `main` on 2026-07-03. Not pushed or released.
- `P1-05-knowledge-review-queue.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-05 after founder/CTO-authorized
    ff-only merge to `main@0d4b0cb`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-06-knowledge-review-actions.IMPLEMENTATION-20260703.md`
  - Bounded KnowledgeAsset review action surface originally implemented on
    `codex/p1-06-knowledge-review-actions-20260703`; locally merged to
    deployment `main` on 2026-07-03. Not pushed or released.
- `P1-06-knowledge-review-actions.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-06 after founder/CTO-authorized
    ff-only merge to `main@e1986e9`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-07-knowledge-review-audit.IMPLEMENTATION-20260703.md`
  - Safe persistent trace audit for KnowledgeAsset review decisions implemented
    on `codex/p1-07-knowledge-review-audit-20260703`; branch-local `make ci`
    and PostgreSQL `ci-local-full` passed. Not pushed or released.
- `P1-07-knowledge-review-audit.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-07 after founder/CTO-authorized
    ff-only merge to `main@1b42cba`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-08-reviewed-knowledge-consumption.IMPLEMENTATION-20260703.md`
  - Default KnowledgeAsset consumption now excludes unreviewed DRAFT and
    DEPRECATED assets while preserving reviewed ACTIVE and external adopted
    value-backed knowledge; branch-local `make ci` and PostgreSQL
    `ci-local-full` passed. Not pushed or released.
- `P1-08-reviewed-knowledge-consumption.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-08 after founder/CTO-authorized
    ff-only merge to `main@6471924`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-09-knowledge-context-proposal.IMPLEMENTATION-20260703.md`
  - Recalled reviewed/value-backed KnowledgeAsset ids are bound into the next
    `ActionProposal.knowledge_context_refs` and the `action_proposal` trace
    event as safe proposal context; branch-local `make ci` and PostgreSQL
    `ci-local-full` passed. Not pushed or released.
- `P1-09-knowledge-context-proposal.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-09 after founder/CTO-authorized
    ff-only merge to `main@ea099ac`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-10-internal-knowledge-context-projection.IMPLEMENTATION-20260703.md`
  - Internal `user_result.decision.knowledge_context_refs` now exposes safe
    recalled KnowledgeAsset asset ids for audited internal decisions, while
    external audience projections return an empty list; branch-local `make ci`
    and PostgreSQL `ci-local-full` passed. Not pushed or released.
- `P1-10-internal-knowledge-context-projection.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-10 after founder/CTO-authorized
    ff-only merge to `main@4432784`; `make ci` and PostgreSQL `ci-local-full`
    passed. Not pushed, not released.
- `P1-11-knowledge-publish-lifecycle.IMPLEMENTATION-20260703.md`
  - Internal KnowledgeAsset publish lifecycle implemented on
    `codex/p1-11-knowledge-publish-lifecycle-20260703`: reviewed `active`
    assets can become `published`, draft/deprecated assets cannot skip gates,
    and default retrieval consumes `published` assets; branch-local `make ci`
    and PostgreSQL `ci-local-full` passed. Not pushed or released.
- `P1-11-knowledge-publish-lifecycle.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-11 after founder/CTO-authorized
    ff-only merge to `main@29d3253`; `make ci` and PostgreSQL `ci-local-full`
    passed with 557 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-12-knowledge-asset-catalog.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal `GET /knowledge/assets`
    lifecycle catalog for active/published KnowledgeAssets, with explicit
    `state=draft|active|published|deprecated|all` filtering. The route requires
    internal `knowledge:review` scope, denies `external_report`, is read-only,
    and branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 560
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, not
    pushed, not released.
- `P1-12-knowledge-asset-catalog.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-12 after founder/CTO-authorized
    ff-only merge to `main@85d527d`; `make ci` and PostgreSQL `ci-local-full`
    passed with 560 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-13-knowledge-deprecate-lifecycle.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal `POST
    /knowledge/assets/{asset_id}/deprecate` lifecycle transition: only
    reviewed `active` or `published` KnowledgeAssets can become `deprecated`;
    raw deprecation reasons are not written into trace payloads, default
    consumption excludes deprecated assets, and branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 563 primary unittest tests OK / 4
    skipped plus 12 eval OK. Not pushed or released.
- `P1-13-knowledge-deprecate-lifecycle.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-13 after founder/CTO-authorized
    ff-only merge to `main@cd9b9dc`; `make ci` and PostgreSQL `ci-local-full`
    passed with 563 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `PR-07-product-integration-release-gate.REVIEW-20260624.md`
  - Current verdict: do not merge old F3 rehearsal `d46bd45`; fresh rehearsal from current local main `77c7b07` is recorded in `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
- `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
  - Fresh combined successor rehearsal for reconcile/F1/F2/F3a from local main `77c7b07`; CI/browser QA passed; merge and release remain separate gates

Read `docs/CURRENT_STATE.yaml` first for live status and verification state.
