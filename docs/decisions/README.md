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
- `PR-07-product-integration-release-gate.REVIEW-20260624.md`
  - Current verdict: do not merge old F3 rehearsal `d46bd45`; fresh rehearsal from current local main `77c7b07` is recorded in `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
- `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
  - Fresh combined successor rehearsal for reconcile/F1/F2/F3a from local main `77c7b07`; CI/browser QA passed; merge and release remain separate gates

Read `docs/CURRENT_STATE.yaml` first for live status and verification state.
