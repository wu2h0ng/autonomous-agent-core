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
- `P1-14-knowledge-asset-detail.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal read-only `GET
    /knowledge/assets/{asset_id}` drill-down surface over existing
    KnowledgeAssets. It returns safe metadata plus `has_source_trace`, denies
    `external_report`, does not embed trace events or mutate lifecycle/version,
    and branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 566
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not pushed or
    released.
- `P1-14-knowledge-asset-detail.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-14 after founder/CTO-authorized
    ff-only merge to `main@ec46dc0`; `make ci` and PostgreSQL `ci-local-full`
    passed with 566 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-15-knowledge-asset-lifecycle-events.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal read-only `GET
    /knowledge/assets/{asset_id}/lifecycle-events` audit surface over existing
    KnowledgeAsset lifecycle decision events. It projects only allowlisted
    review/publish/deprecate fields, omits raw reasons and full trace payloads,
    denies `external_report`, does not mutate lifecycle/version/feedback/adoption
    state, and branch-local `make ci` plus PostgreSQL `ci-local-full` passed with
    569 primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged,
    pushed, or released.
- `P1-15-knowledge-asset-lifecycle-events.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-15 after founder/CTO-authorized
    ff-only merge to `main@019dab8`; `make ci` and PostgreSQL `ci-local-full`
    passed with 569 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-16-knowledge-context-feedback-projection.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `knowledge_context_refs` projection on
    `/outcomes` and `/adoptions` responses from the source trace's
    `action_proposal` event. It exposes asset ids only, not raw
    KnowledgeAsset titles/content or full related knowledge, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 572 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-16-knowledge-context-feedback-projection.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-16 after founder/CTO-authorized
    ff-only merge to `main@9a18d02`; `make ci` and PostgreSQL `ci-local-full`
    passed with 572 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-17-correction-context-trace-audit.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `knowledge_context_refs` projection on
    successful correction-channel `agent_runtime.tool_succeeded` trace events
    for `/outcomes` and `/adoptions`. It appends asset ids only, preserves
    correction-channel append ordering, does not change feedback/adoption
    promotion semantics, and branch-local `make ci` plus PostgreSQL
    `ci-local-full` passed with 572 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-17-correction-context-trace-audit.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-17 after founder/CTO-authorized
    ff-only merge to `main@7e9e482`; `make ci` and PostgreSQL `ci-local-full`
    passed with 572 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-18-knowledge-usage-events.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal read-only `GET
    /knowledge/assets/{asset_id}/usage-events` audit surface over persisted
    trace usage of a KnowledgeAsset id. It projects allowlisted proposal and
    correction-context usage metadata only, denies `external_report`, does not
    expose KnowledgeAsset title/content/full related knowledge, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 576 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-18-knowledge-usage-events.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-18 after founder/CTO-authorized
    ff-only merge to `main@d0ca465`; `make ci` and PostgreSQL `ci-local-full`
    passed with 576 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-19-knowledge-decision-quality.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal read-only `GET
    /knowledge/assets/{asset_id}/decision-quality` aggregate surface over
    persisted proposal and correction-channel usage of a KnowledgeAsset id. It
    reports safe counts and trace ids only, denies `external_report`, does not
    expose KnowledgeAsset title/content/full related knowledge, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 580 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-19-knowledge-decision-quality.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-19 after founder/CTO-authorized
    ff-only merge to `main@bb785b9`; `make ci` and PostgreSQL `ci-local-full`
    passed with 580 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Not pushed, not released.
- `P1-20-knowledge-quality-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal read-only `GET
    /knowledge/assets/quality-summary` collection surface over all
    KnowledgeAssets. It reports safe per-asset quality counts and derived
    `quality_status` only, denies `external_report`, omits KnowledgeAsset
    title/content/full related knowledge and raw usage trace ids, preserves the
    P1-19 drill-down route, and branch-local `make ci` plus PostgreSQL
    `ci-local-full` passed with 583 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-20-knowledge-quality-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-20 after founder/CTO-authorized
    ff-only merge to `main@ff8f68f`; `make ci` and PostgreSQL
    `ci-local-full` passed with 583 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-21-knowledge-quality-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of an internal `quality_status` filter for
    `GET /knowledge/assets/quality-summary`, with allowed values
    `unused|proposal_only|outcome_observed|adoption_observed`, explicit 400 on
    invalid filters, and `quality_status_filter` echo in the response.
    Branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 585
    primary unittest tests OK / 4 skipped plus 12 eval OK. Later locally merged
    to deployment `main@4dda317`; not pushed or released.
- `P1-21-knowledge-quality-filter.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-21 after founder/CTO-authorized
    ff-only merge to `main@4dda317`; `make ci` and PostgreSQL
    `ci-local-full` passed with 585 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-22-knowledge-quality-review-priority.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of reviewer action hints on internal
    `GET /knowledge/assets/quality-summary`: each item now includes typed
    `review_priority` and `recommended_review_action` fields derived from safe
    `quality_status`. Branch-local `make ci` plus PostgreSQL `ci-local-full`
    passed with 585 primary unittest tests OK / 4 skipped plus 12 eval OK.
    Later locally merged to deployment `main@816cb3e`; not pushed or released.
- `P1-22-knowledge-quality-review-priority.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-22 after founder/CTO-authorized
    ff-only merge to `main@816cb3e`; `make ci` and PostgreSQL
    `ci-local-full` passed with 585 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-23-knowledge-quality-review-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of internal reviewer queue filters on
    `GET /knowledge/assets/quality-summary`: `review_priority` and
    `recommended_review_action` can now be used as safe read-only filters and
    are echoed in the response. Branch-local `make ci` plus PostgreSQL
    `ci-local-full` passed with 585 primary unittest tests OK / 4 skipped plus
    12 eval OK. Later locally merged to deployment `main@b06b282`; not pushed
    or released.
- `P1-23-knowledge-quality-review-filter.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-23 after founder/CTO-authorized
    ff-only merge to `main@b06b282`; `make ci` and PostgreSQL
    `ci-local-full` passed with 585 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-24-knowledge-quality-review-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of deterministic internal reviewer queue
    ordering on `GET /knowledge/assets/quality-summary`: `order_by=review_priority`
    returns high-priority items before medium/low items and echoes `order_by`.
    Branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 586
    primary unittest tests OK / 4 skipped plus 12 eval OK. Later locally merged
    to deployment `main@e5fa33f`; not pushed or released.
- `P1-24-knowledge-quality-review-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-24 after founder/CTO-authorized
    ff-only merge to `main@e5fa33f`; `make ci` and PostgreSQL
    `ci-local-full` passed with 586 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-25-knowledge-quality-review-counts.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe internal reviewer queue facet counts on
    `GET /knowledge/assets/quality-summary`: `quality_status_counts`,
    `review_priority_counts`, and `recommended_review_action_counts` summarize
    the currently returned items with stable allowlisted keys. Branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 586 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Later locally merged to deployment
    `main@7c1d0b2`; not pushed or released.
- `P1-25-knowledge-quality-review-counts.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-25 after founder/CTO-authorized
    ff-only merge to `main@7c1d0b2`; `make ci` and PostgreSQL
    `ci-local-full` passed with 586 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-26-knowledge-quality-review-pagination.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of bounded pagination on the internal
    KnowledgeAsset quality review queue: `GET /knowledge/assets/quality-summary`
    now accepts `limit` and `offset`, returns `total_count` and `has_more`, and
    preserves safe page-scoped count maps. Branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 587 primary unittest tests OK plus
    12 eval OK. Later locally merged to deployment `main@d931b63`; not pushed
    or released.
- `P1-26-knowledge-quality-review-pagination.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-26 after founder/CTO-authorized
    ff-only merge to `main@d931b63`; `make ci` and PostgreSQL
    `ci-local-full` passed with 587 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-27-knowledge-context-quality-recall.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe context-quality reranking for recalled
    KnowledgeAssets. Prior outcome/adoption correction usage can now boost a
    recalled asset before it is bound into `ActionProposal.knowledge_context_refs`,
    while only aggregate quality boost metadata is traced. Branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 588 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Later locally merged to deployment
    `main@7e0b284`; not pushed or released.
- `P1-27-knowledge-context-quality-recall.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-27 after founder/CTO-authorized
    ff-only merge to `main@7e0b284`; `make ci` and PostgreSQL
    `ci-local-full` passed with 588 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-28-knowledge-context-rationale.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of internal
    `user_result.decision.knowledge_context_rationale`, a safe explanation for
    recalled KnowledgeAssets bound into proposal context. External audience
    projection returns an empty rationale list. Branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 589 primary unittest tests OK / 4
    skipped plus 12 eval OK. Later locally merged to deployment `main@f5d901d`;
    not pushed or released.
- `P1-28-knowledge-context-rationale.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-28 after founder/CTO-authorized
    ff-only merge to `main@f5d901d`; `make ci` and PostgreSQL
    `ci-local-full` passed with 589 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `P1-29-knowledge-rationale-review-surface.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe internal
    `review_rationale_codes` on `GET /knowledge/assets/quality-summary`
    items. The codes are allowlisted and derived from existing aggregate
    quality status, not raw traces or KnowledgeAsset content. Branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 590 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-29-knowledge-rationale-review-surface.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-29. Current deployment `main`
    is an ancestor of the branch (`ancestor=0`, `0 1`), both worktrees only
    had untracked `.agent_runs/`, and branch-local `make ci` plus PostgreSQL
    `ci-local-full` evidence is recorded. Not merge authorization, not pushed,
    not released.
- `P1-30-knowledge-rationale-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of internal `review_rationale_code` filtering
    on `GET /knowledge/assets/quality-summary`, with allowlisted enum values
    derived from existing aggregate quality status. Branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 590 primary unittest tests OK / 4
    skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-30-knowledge-rationale-filter.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for the stacked P1-29/P1-30 branch. Current
    deployment `main` was an ancestor of the branch at readiness check
    (`ancestor=0`, `0 3`), both worktrees only had untracked `.agent_runs/`,
    and branch-local `make ci` plus PostgreSQL `ci-local-full` evidence is
    recorded. Not merge authorization, not pushed, not released.
- `P1-31-knowledge-rationale-counts.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of internal `review_rationale_code_counts` on
    `GET /knowledge/assets/quality-summary`, summarizing the currently returned
    page by allowlisted rationale code. Branch-local `make ci` plus PostgreSQL
    `ci-local-full` passed with 590 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-31-knowledge-rationale-counts.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for the stacked P1-29/P1-30/P1-31 branch. Current
    deployment `main` was an ancestor of the branch at readiness check
    (`ancestor=0`, `0 5`), both worktrees only had untracked `.agent_runs/`,
    and branch-local `make ci` plus PostgreSQL `ci-local-full` evidence is
    recorded. Not merge authorization, not pushed, not released.
- `P1-32-knowledge-detail-review-state.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe review-state fields on internal
    `GET /knowledge/assets/{asset_id}` detail responses. The route now includes
    aggregate usage counts, quality status, review priority, recommended review
    action, and allowlisted rationale codes without exposing raw usage trace ids.
    Branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 591
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-32-knowledge-detail-review-state.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for the stacked P1-29/P1-30/P1-31/P1-32 branch.
    Current deployment `main` was an ancestor of the branch at readiness check
    (`ancestor=0`, `0 7`), both worktrees only had untracked `.agent_runs/`,
    and branch-local `make ci` plus PostgreSQL `ci-local-full` evidence is
    recorded. Not merge authorization, not pushed, not released.
- `P1-33-knowledge-catalog-review-state.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe review-state fields on internal
    `GET /knowledge/assets` catalog items. The route now includes aggregate
    usage counts, quality status, review priority, recommended review action,
    and allowlisted rationale codes without exposing raw usage trace ids.
    Branch-local `make ci` plus PostgreSQL `ci-local-full` passed with 592
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-33-knowledge-catalog-review-state.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for the stacked P1-29/P1-30/P1-31/P1-32/P1-33
    branch. Current deployment `main` was an ancestor of the branch at
    readiness check (`ancestor=0`, `0 9`), both worktrees only had untracked
    `.agent_runs/`, and branch-local `make ci` plus PostgreSQL
    `ci-local-full` evidence is recorded. Not merge authorization, not pushed,
    not released.
- `P1-33-knowledge-catalog-review-state.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-33 after user-authorized cautious
    ff-only merge to `main@ef074ee`; `make ci` and PostgreSQL
    `ci-local-full` passed. Not pushed, not released.
- `P1-34-knowledge-catalog-review-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe review-state filtering on internal
    `GET /knowledge/assets`: `review_priority` and `review_rationale_code`
    filters reuse existing allowlists, echo applied filters, and preserve the
    internal-only/read-only/no-raw-trace boundary. Branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 594 primary unittest tests OK / 4
    skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-34-knowledge-catalog-review-filter.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-34. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-34-knowledge-catalog-review-filter.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-34 after user-authorized cautious
    ff-only merge to `main@7483dea`; `make ci` and PostgreSQL
    `ci-local-full` passed. Not pushed, not released.
- `P1-35-knowledge-catalog-action-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `recommended_review_action` filtering
    on internal `GET /knowledge/assets`, reusing the allowlisted action values
    derived from aggregate quality status. Branch-local `make ci` plus
    PostgreSQL `ci-local-full` passed with 594 primary unittest tests OK / 4
    skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-35-knowledge-catalog-action-filter.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-35. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-35-knowledge-catalog-action-filter.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-35 after cautious ff-only merge
    to `main@2c4e5b8`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-36-knowledge-catalog-action-counts.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `recommended_review_action_counts` on
    internal `GET /knowledge/assets`, summarizing the currently returned
    catalog result by allowlisted recommended review action. Branch-local
    `make ci` plus PostgreSQL `ci-local-full` passed with 594 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-36-knowledge-catalog-action-counts.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-36. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-36-knowledge-catalog-action-counts.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-36 after cautious ff-only merge
    to `main@3e98f2a`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-37-knowledge-catalog-rationale-counts.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `review_rationale_code_counts` on
    internal `GET /knowledge/assets`, summarizing the currently returned
    catalog result by allowlisted review rationale code. Branch-local targeted
    RED/GREEN, `make ci`, and PostgreSQL `ci-local-full` passed with 594
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-37-knowledge-catalog-rationale-counts.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-37. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-37-knowledge-catalog-rationale-counts.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-37 after cautious ff-only merge
    to `main@1b0e706`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-38-knowledge-catalog-pagination.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `limit`/`offset` pagination on internal
    `GET /knowledge/assets`, with `limit`, `offset`, `total_count`, `has_more`,
    and page-local counts. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 596 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-38-knowledge-catalog-pagination.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-38. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-38-knowledge-catalog-pagination.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-38 after cautious ff-only merge
    to `main@289713a`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-39-knowledge-catalog-review-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `order_by=review_priority` ordering on
    internal `GET /knowledge/assets`, sorting filtered catalog results before
    pagination so high-priority review work can be paged first. Branch-local
    targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI tests, `make ci`,
    and PostgreSQL `ci-local-full` passed with 598 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-39-knowledge-catalog-review-order.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-39. Current deployment `main`
    was an ancestor of the branch at readiness check (`ancestor=0`, `0 1`),
    the feature worktree only had untracked `.agent_runs/`, and branch-local
    `make ci` plus PostgreSQL `ci-local-full` evidence is recorded. Not merge
    authorization, not pushed, not released.
- `P1-39-knowledge-catalog-review-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-39 after cautious ff-only merge
    to `main@a93d4d8`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-40-knowledge-catalog-priority-counts.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe page-local `review_priority_counts` on
    internal `GET /knowledge/assets`, alongside existing page-local action and
    rationale counts. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 598 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-40-knowledge-catalog-priority-counts.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-40 priority counts; local
    `main` was confirmed as an ancestor and only `.agent_runs/` remained
    untracked. Not merged, pushed, or released.
- `P1-40-knowledge-catalog-priority-counts.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-40 after cautious ff-only merge
    to `main@f7c4f1f`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-41-knowledge-catalog-quality-status.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `quality_status` filtering and
    page-local `quality_status_counts` on internal `GET /knowledge/assets`.
    Branch-local targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI tests,
    `make ci`, and PostgreSQL `ci-local-full` passed with 598 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-41-knowledge-catalog-quality-status.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-41 quality-status catalog
    filtering; local `main` was confirmed as an ancestor and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-41-knowledge-catalog-quality-status.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-41 after cautious ff-only merge
    to `main@1a4767e`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-42-knowledge-catalog-quality-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of catalog-only `order_by=quality_status` for
    internal `GET /knowledge/assets`; quality-summary ordering remains limited
    to `review_priority`. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 598 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-42-knowledge-catalog-quality-order.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-42 catalog quality-status
    ordering; local `main` was confirmed as an ancestor and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-42-knowledge-catalog-quality-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-42 after cautious ff-only merge
    to `main@3c33dc6`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-43-knowledge-catalog-action-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of catalog-only
    `order_by=recommended_review_action` for internal `GET /knowledge/assets`;
    quality-summary ordering remains limited to `review_priority`. Branch-local
    targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI tests, `make ci`,
    and PostgreSQL `ci-local-full` passed with 598 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-43-knowledge-catalog-action-order.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-43 catalog recommended-action
    ordering; local `main` was confirmed as an ancestor and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-43-knowledge-catalog-action-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-43 after cautious ff-only merge
    to `main@cdd1af7`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-44-knowledge-catalog-rationale-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of catalog-only
    `order_by=review_rationale_code` for internal `GET /knowledge/assets`;
    quality-summary ordering remains limited to `review_priority`.
    Branch-local targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI tests,
    `make ci`, and PostgreSQL `ci-local-full` passed with 598 primary unittest
    tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-44-knowledge-catalog-rationale-order.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-44 catalog rationale-code
    ordering; local `main` was confirmed as an ancestor and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-44-knowledge-catalog-rationale-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-44 after cautious ff-only merge
    to `main@bb43e92`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-45-knowledge-usage-events-pagination.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of bounded `limit`/`offset` pagination for
    internal `GET /knowledge/assets/{asset_id}/usage-events`, returning
    `total_count`, `has_more`, `limit`, and `offset` while preserving the safe
    usage-event projection. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 598 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-45-knowledge-usage-events-pagination.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-45 usage-events pagination;
    local `main` was confirmed as an ancestor and only `.agent_runs/` remained
    untracked. Not merged, pushed, or released.
- `P1-45-knowledge-usage-events-pagination.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-45 after cautious ff-only merge
    to `main@b95699e`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-46-knowledge-lifecycle-events-pagination.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of bounded `limit`/`offset` pagination for
    internal `GET /knowledge/assets/{asset_id}/lifecycle-events`, returning
    `total_count`, `has_more`, `limit`, and `offset` while preserving the safe
    lifecycle-event projection. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 599 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-46-knowledge-lifecycle-events-pagination.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-46 lifecycle-events pagination;
    local `main` was confirmed as an ancestor, branch was `0 1` ahead, and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-46-knowledge-lifecycle-events-pagination.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-46 after cautious ff-only merge
    to `main@2a6967a`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-47-knowledge-detail-lifecycle-count.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `lifecycle_event_count` on internal
    `GET /knowledge/assets/{asset_id}` detail, counting lifecycle audit events
    without returning event bodies or raw reasons. Branch-local targeted
    RED/GREEN, related KnowledgeAsset/API/OpenAPI tests, `make ci`, and
    PostgreSQL `ci-local-full` passed with 599 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-47-knowledge-detail-lifecycle-count.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-47 detail lifecycle count;
    local `main` was confirmed as an ancestor, branch was `0 1` ahead, and only
    `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-47-knowledge-detail-lifecycle-count.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-47 after cautious ff-only merge
    to `main@6d65515`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-48-knowledge-catalog-lifecycle-count.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `lifecycle_event_count` on internal
    `GET /knowledge/assets` catalog items, counting lifecycle audit events
    without returning event bodies or raw reasons. Branch-local targeted
    RED/GREEN, related KnowledgeAsset/API/OpenAPI tests, `make ci`, and
    PostgreSQL `ci-local-full` passed with 599 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-48-knowledge-catalog-lifecycle-count.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-48 catalog lifecycle count;
    local `main@61228a9` was confirmed as an ancestor, branch was `0 1`
    ahead, and only `.agent_runs/` remained untracked. Not merged, pushed, or
    released.
- `P1-48-knowledge-catalog-lifecycle-count.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-48 after cautious ff-only merge
    to `main@f3cc0ec`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-49-knowledge-quality-lifecycle-count.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `lifecycle_event_count` on internal
    `GET /knowledge/assets/quality-summary` items, counting lifecycle audit
    events without returning event bodies or raw reasons. Branch-local
    targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI tests, `make ci`,
    and PostgreSQL `ci-local-full` passed with 599 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-49-knowledge-quality-lifecycle-count.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-49 quality-summary lifecycle
    count; local `main@7dc1624` was confirmed as an ancestor, branch was `0 1`
    ahead, and only `.agent_runs/` remained untracked. Not merged, pushed, or
    released.
- `P1-49-knowledge-quality-lifecycle-count.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-49 after cautious ff-only merge
    to `main@a37cca6`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-50-knowledge-detail-lifecycle-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe nullable `latest_lifecycle_event` on
    internal `GET /knowledge/assets/{asset_id}` detail, projecting only
    allowlisted lifecycle transition fields without reviewer identity, event
    bodies, or raw reasons. Branch-local targeted RED/GREEN, related
    KnowledgeAsset/API/OpenAPI tests, `make ci`, and PostgreSQL
    `ci-local-full` passed with 599 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-50-knowledge-detail-lifecycle-summary.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-50 detail lifecycle summary;
    local `main@78bdbe1` was confirmed as an ancestor, branch was `0 1`
    ahead, and only `.agent_runs/` remained untracked. Not merged, pushed, or
    released.
- `P1-50-knowledge-detail-lifecycle-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-50 after cautious ff-only merge
    to `main@7a87f61`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-51-knowledge-catalog-lifecycle-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe nullable `latest_lifecycle_event` on
    internal `GET /knowledge/assets` catalog items, projecting only allowlisted
    lifecycle transition fields without reviewer identity, event bodies, or raw
    reasons. Branch-local targeted RED/GREEN, related KnowledgeAsset/API/OpenAPI
    tests, `make ci`, and PostgreSQL `ci-local-full` passed with 599 primary
    unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed, or
    released.
- `P1-51-knowledge-catalog-lifecycle-summary.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-51 catalog lifecycle summary;
    local `main@8eaa27c` was confirmed as an ancestor, branch was `0 1`
    ahead, and only `.agent_runs/` remained untracked. Not merged, pushed, or
    released.
- `P1-51-knowledge-catalog-lifecycle-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-51 after cautious ff-only merge
    to `main@ee4cabb`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-52-knowledge-detail-usage-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe nullable `latest_usage_event` on
    internal `GET /knowledge/assets/{asset_id}` detail, projecting only
    allowlisted usage summary fields without raw trace payloads, tool names,
    source content, correction payloads, metric deltas, or secret-like fields.
    Branch-local RED/GREEN, related subset, `make ci`, and PostgreSQL
    `ci-local-full` passed with 599 primary unittest tests OK plus 12 eval OK.
    Not merged, pushed, or released.
- `P1-52-knowledge-detail-usage-summary.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-52 detail usage summary; local
    `main@88b8128` was confirmed as an ancestor, branch was `0 1` ahead, and
    only `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-52-knowledge-detail-usage-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-52 after cautious ff-only merge
    to `main@e6d1e49`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-53-knowledge-catalog-usage-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe nullable `latest_usage_event` on
    internal `GET /knowledge/assets` catalog items, projecting only allowlisted
    usage summary fields without raw trace payloads, tool names, source content,
    correction payloads, metric deltas, or secret-like fields. Branch-local
    RED/GREEN, related subset, `make ci`, and PostgreSQL `ci-local-full` passed
    with 599 primary unittest tests OK plus 12 eval OK. Not merged, pushed, or
    released.
- `P1-53-knowledge-catalog-usage-summary.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-53 catalog usage summary; local
    `main@68ac803` was confirmed as an ancestor, branch was `0 1` ahead, and
    only `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-53-knowledge-catalog-usage-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-53 after cautious ff-only merge
    to `main@b469995`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-54-knowledge-quality-usage-summary.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe nullable `latest_usage_event` on
    internal `GET /knowledge/assets/quality-summary` items. The quality triage
    view can show the latest proposal/correction reuse signal with only
    allowlisted summary fields; branch-local `make ci` and PostgreSQL
    `ci-local-full` passed with 599 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, not pushed, not released.
- `P1-54-knowledge-quality-usage-summary.MERGE-READINESS-20260703.md`
  - Merge-readiness packet for branch-local P1-54 quality usage summary; local
    `main@119ece9` was confirmed as an ancestor, branch was `0 1` ahead, and
    only `.agent_runs/` remained untracked. Not merged, pushed, or released.
- `P1-54-knowledge-quality-usage-summary.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-54 after cautious ff-only merge
    to `main@053dc3c`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-55-knowledge-review-queue-triage-fields.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe quality/usage triage fields on internal
    `GET /knowledge/review-queue` items. The DRAFT review screen now exposes
    nullable `latest_usage_event`, usage counters, quality status, priority,
    recommended action, and rationale codes without making draft assets
    consumable; branch-local `make ci` and PostgreSQL `ci-local-full` passed
    with 600 primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged,
    pushed, or released.
- `P1-55-knowledge-review-queue-triage-fields.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness packet for P1-55. `main` is an ancestor,
    `main...HEAD` is `0 1`, the latest focused review-queue/OpenAPI regression
    set passed, and only `.agent_runs/` remains untracked. Not merged, pushed,
    or released.
- `P1-55-knowledge-review-queue-triage-fields.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-55 after cautious ff-only merge
    to `main@1b24d36`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-56-knowledge-review-queue-filters.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe triage filters and
    `order_by=review_priority` for internal `GET /knowledge/review-queue`.
    The DRAFT review queue now echoes normalized filters and returns safe
    quality/priority/action counts without making draft assets consumable;
    branch-local `make ci` and PostgreSQL `ci-local-full` passed with 602
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-56-knowledge-review-queue-filters.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness packet for P1-56. `main` is an ancestor,
    `main...HEAD` is `0 1`, and branch-local `make ci` plus PostgreSQL
    `ci-local-full` passed. Not merged, pushed, or released.
- `P1-56-knowledge-review-queue-filters.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-56 after cautious ff-only merge
    to `main@6553a04`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-57-knowledge-review-queue-pagination.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of pagination for internal
    `GET /knowledge/review-queue`. The DRAFT review queue now accepts `limit`
    and `offset`, returns `total_count` and `has_more`, and keeps counts
    page-local without making draft assets consumable; branch-local `make ci`
    and PostgreSQL `ci-local-full` passed with 604 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-57-knowledge-review-queue-pagination.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness for P1-57 after fast-forward checks
    (`main...HEAD = 0 1`), focused OpenAPI + pagination rerun, and current
    branch `make ci` plus PostgreSQL `ci-local-full` verification at 604
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-57-knowledge-review-queue-pagination.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-57 after cautious ff-only merge
    to `main@3021172`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-58-knowledge-review-queue-rationale-filter.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of `review_rationale_code` filtering and
    page-local `review_rationale_code_counts` for internal
    `GET /knowledge/review-queue`. It uses the existing allowlisted rationale
    vocabulary, keeps DRAFT assets non-consumable, and branch-local `make ci`
    plus PostgreSQL `ci-local-full` passed with 606 primary unittest tests OK /
    4 skipped plus 12 eval OK. Not merged, pushed, or released.
- `P1-58-knowledge-review-queue-rationale-filter.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness for P1-58 after fast-forward checks
    (`main...HEAD = 0 1`) and current branch `make ci` plus PostgreSQL
    `ci-local-full` verification at 606 primary unittest tests OK / 4 skipped
    plus 12 eval OK. Not merged, pushed, or released.
- `P1-58-knowledge-review-queue-rationale-filter.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-58 after cautious ff-only merge
    to `main@3e04da1`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-59-knowledge-review-queue-rationale-order.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of `order_by=review_rationale_code` for
    internal `GET /knowledge/review-queue`. Ordering uses the existing safe
    rationale vocabulary before pagination, keeps DRAFT assets non-consumable,
    and focused plus related KnowledgeAsset/API/OpenAPI tests passed. Full
    branch `make ci` and PostgreSQL `ci-local-full` also passed with 608
    primary unittest tests OK / 4 skipped plus 12 eval OK. Not merged, pushed,
    or released.
- `P1-59-knowledge-review-queue-rationale-order.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness for P1-59 after fast-forward checks
    (`main...HEAD = 0 1`) and current branch `make ci` plus PostgreSQL
    `ci-local-full` verification at 608 primary unittest tests OK / 4 skipped
    plus 12 eval OK. Not merged, pushed, or released.
- `P1-59-knowledge-review-queue-rationale-order.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-59 after cautious ff-only merge
    to `main@57537a1`; `make ci` and PostgreSQL `ci-local-full` passed. Not
    pushed, not released.
- `P1-60-correction-knowledge-rationale.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `knowledge_context_rationale` on
    `/outcomes` and `/adoptions` responses. The projection is derived from
    persisted proposal/recall metadata and exposes only asset id, score,
    context-quality boost, and an allowlisted reason code; branch `make ci` and
    PostgreSQL `ci-local-full` passed with 609 primary unittest tests OK / 4
    skipped plus 12 eval OK. Later locally merged; see the post-merge
    verification record. Not pushed or released.
- `P1-60-correction-knowledge-rationale.MERGE-READINESS-20260703.md`
  - Initial branch-local merge-readiness for P1-60 after fast-forward checks
    (`main...HEAD = 0 1`) and current branch `make ci` plus PostgreSQL
    `ci-local-full` verification at 608 primary unittest tests OK / 4 skipped
    plus 12 eval OK. Superseded by the hardening refresh for final merge
    readiness. Not merged, pushed, or released.
- `P1-60-correction-knowledge-rationale.MERGE-READINESS-REFRESH-20260703.md`
  - Branch-local merge-readiness refresh for P1-60 after recall-metadata
    boundary hardening. Latest fast-forward check showed `main...HEAD = 0 3`
    before the docs refresh commit, and current branch `make ci` plus PostgreSQL
    `ci-local-full` verification at 609 primary unittest tests OK / 4 skipped
    plus 12 eval OK. Not merged, pushed, or released.
- `P1-60-correction-knowledge-rationale.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-60 after cautious ff-only merge
    to `main@4f8e2fb`; post-merge `make ci` and PostgreSQL `ci-local-full`
    passed with 609 primary unittest tests OK / 4 skipped plus 12 eval OK. Not
    pushed, not released.
- `P1-61-knowledge-usage-rationale-events.IMPLEMENTATION-20260703.md`
  - Branch-local implementation of safe `knowledge_context_rationale` on
    internal `GET /knowledge/assets/{asset_id}/usage-events` correction-context
    events. It derives allowlisted rationale from persisted proposal/recall
    metadata, keeps proposal-context rationale empty, and does not expand
    catalog/latest-summary surfaces. Branch `make ci` and PostgreSQL
    `ci-local-full` passed with 609 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-61-knowledge-usage-rationale-events.MERGE-READINESS-20260703.md`
  - Branch-local merge-readiness for P1-61; final ff-only linearness must be
    rechecked immediately before local merge. Branch `make ci` and PostgreSQL
    `ci-local-full` passed with 609 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not merged, pushed, or released.
- `P1-61-knowledge-usage-rationale-events.POST-MERGE-VERIFY-20260703.md`
  - Local-main post-merge verification for P1-61 after cautious ff-only merge
    to `main@55da9a7`; focused usage-events rationale/OpenAPI regressions
    passed 4 tests OK, related usage-events/decision-quality/quality-summary
    regression passed 14 tests OK, and post-merge `make ci` plus PostgreSQL
    `ci-local-full` passed with 609 primary unittest tests OK / 4 skipped plus
    12 eval OK. Not pushed, not released.
- `PR-08-deployment-local-main-release-gap-audit-20260703.md`
  - Aggregate deployment audit for the current local-only mainline:
    `origin/main` remains at `dba87bc`, local `main` is `55da9a7`, and the
    repository is ahead by 172 commits as of 2026-07-03. Current verdict:
    local-main post-merge verified is the claim ceiling; push and release are
    separate gates requiring an aggregate release packet plus explicit
    founder/CTO authorization.
- `PR-09-deployment-local-main-aggregate-release-packet-20260703.md`
  - Aggregate authorization packet for the current deployment local mainline.
    Current packet head is `f27fd99`, latest code-bearing product head is
    `55da9a7`, `origin/main` remains `dba87bc`, and the repo is now ahead by
    173 commits. The packet asks for an explicit founder/CTO push decision and
    keeps release as a separate post-push gate.
- `PR-10-deployment-push-hold-decision-20260704.md`
  - Explicit recorded decision for the current deployment packet:
    `DEPLOYMENT_PUSH: HOLD`. Local main remains verified and packeted, but no
    push authorization is granted and no release claim follows.
- `PR-11-deployment-current-head-verification-refresh-20260704.md`
  - Fresh verification record for current local `main@c71dfef` after docs-only
    truth commits on top of the latest code-bearing product head `55da9a7`.
    `make ci` and PostgreSQL `ci-local-full` passed with 609 primary unittest
    tests OK / 4 skipped plus 12 eval OK, threshold report passed, and OpenAPI
    was up to date. Push remains HOLD and release remains absent.
- `PR-12-deployment-push-hold-executable-gate-20260704.md`
  - Local executable push authorization gate for the current HOLD decision.
    `make push-authorization-check` reads the deployment push decision record
    and fails closed while `DEPLOYMENT_PUSH: HOLD` is active; the Make target
    binds the full current HEAD by default, future AUTHORIZED records must
    contain exactly one decision token line, be checked with a full expected
    head, and name exactly one matching exact-line `candidate_head`; unbound
    AUTHORIZED, duplicated/conflicting decision tokens, short/non-hex expected
    heads, missing/multiple/prose-only candidate_head ambiguity, prefix-only
    candidate_head matches, and prose-only token mentions fail closed. The target is
    not part of `make ci`. Focused gate tests passed with 12 tests OK, the target
    exits 2 under HOLD, and `make ci` plus PostgreSQL `ci-local-full` passed
    with 621 primary unittest tests OK / 4 skipped plus 12 eval OK. Not pushed,
    not released.
- `PR-07-product-integration-release-gate.REVIEW-20260624.md`
  - Current verdict: do not merge old F3 rehearsal `d46bd45`; fresh rehearsal from current local main `77c7b07` is recorded in `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
- `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
  - Fresh combined successor rehearsal for reconcile/F1/F2/F3a from local main `77c7b07`; CI/browser QA passed; merge and release remain separate gates

Read `docs/CURRENT_STATE.yaml` first for live status and verification state.
