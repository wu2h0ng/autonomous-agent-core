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
  - Capability gap audit: `ADR-0003-agent-runtime-capability-gap-audit-20260626.md`
- `PR-07-product-integration-release-gate.REVIEW-20260624.md`
  - Current verdict: do not merge old F3 rehearsal `d46bd45`; fresh rehearsal from current local main `77c7b07` is recorded in `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
- `PR-07-frontend-workspace-f3-rerehearsal-current.VERIFICATION-20260624.md`
  - Fresh combined successor rehearsal for reconcile/F1/F2/F3a from local main `77c7b07`; CI/browser QA passed; merge and release remain separate gates

Read `docs/CURRENT_STATE.yaml` first for live status and verification state.
