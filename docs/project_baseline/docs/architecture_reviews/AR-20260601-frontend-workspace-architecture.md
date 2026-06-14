# AR-20260601 Frontend Workspace Architecture

> Status: Approved for architecture baseline  
> Owner: Frontend Workspace Agent  
> Reviewer: CTO  
> Date: 2026-06-01  
> Scope: `ai-native-business-data-agent-os/apps/workspace/`

## 1. Decision

Frontend development is approved as a staged workstream, not as a late-stage add-on.

The workspace UI must start now with architecture, interaction model, static shell, and contract-driven mock states. Real API integration starts only after the corresponding API contracts are stable and covered by tests.

Implementation order:

```text
Contracts
  -> SQL Safety
  -> Query Runtime
  -> EvidenceChain
  -> ActionProposal
  -> Eval
  -> API
  -> UI integration
```

Parallel frontend work is allowed only for:

- Information architecture.
- Page/component skeleton.
- Typed API client contract.
- Static mock states.
- Empty/error/loading states.
- UI smoke and E2E scaffolding.

## 2. Product Goal

The workspace is the human control surface for trusted business data work.

It must help a business owner answer four questions:

1. What question did the system understand?
2. What evidence supports the answer?
3. What action is proposed?
4. What can I approve, reject, or send back as feedback?

The UI is not a decorative dashboard. It is an operational workspace for trust, evidence, approval, and feedback.

## 3. MVP UI Modules

| Module | Purpose | First Release Requirement |
|---|---|---|
| Intent Workspace | Enter business questions and view parsed intent/run state | Question input, run status, parsed metric, trace id |
| EvidenceChain Viewer | Show why the answer is trustworthy | metric definition, SQL template, safety result, source provider, result summary, limitations |
| ActionProposal Panel | Convert evidence into governed action | proposal, reason, risk level, approval requirement, feedback controls |
| Trace Drawer | Show execution path for debugging/review | ordered trace steps and payload summaries |
| Feedback Bar | Capture explicit feedback | useful/not useful, issue category, note |

## 4. UI Red Lines

The frontend must not:

- Hide EvidenceChain behind a generic "AI answer" card.
- Display formal answers without evidence and trace.
- Allow R4/R5 actions to execute directly.
- Create new backend contract fields ad hoc.
- Hard-code business-domain logic that belongs in domain packs.
- Use mock API responses as if they were production behavior.
- Ship UI success states without error, empty, and loading states.
- Add decorative landing-page UI before the actual workspace exists.

## 5. Stage Plan

### Stage F0: Architecture and Static Skeleton

Timing: current stage.

Allowed work:

- `apps/workspace/` project scaffold.
- Route shell and workspace layout.
- Static mock data matching current contracts.
- Component boundaries.
- UI state model.
- Frontend lint/test/smoke commands.

Exit criteria:

- Static workspace renders Intent, Evidence, Action, Trace, and Feedback areas.
- No backend contract invention.
- No OS Core imports.

### Stage F1: EvidenceChain Viewer MVP

Timing: Sprint 3.

Allowed work:

- Render EvidenceChain from typed API response.
- Show SQL Safety result and checked schemas/tables.
- Show provider and lineage summary.
- Show limitations and confidence.

Exit criteria:

- Business owner can explain where the answer came from.
- UI smoke covers loaded, empty, and error states.

### Stage F2: ActionProposal and Approval Lite

Timing: Sprint 4.

Allowed work:

- Render ActionProposal.
- Display risk level and approval requirement.
- Capture approve/reject/feedback intent.
- Do not execute high-risk business actions.

Exit criteria:

- Proposal references EvidenceChain.
- R4/R5 actions are proposal-only.
- Feedback creates a typed event or staged API call.

### Stage F3: API Integration and Golden Loop UI

Timing: Sprint 5.

Allowed work:

- Connect Intent Workspace to API.
- Display live Trusted Loop result.
- Add smoke/E2E for at least one golden query.

Exit criteria:

- One content-commerce golden loop can be run from UI.
- UI smoke is part of CI or release gate.
- Failure states are visible and understandable.

## 6. Technology Choice

Approved MVP stack:

```text
React / Next.js
TypeScript
Typed API client generated or hand-maintained from API contracts
Playwright or equivalent browser smoke testing
```

Do not add a heavy component framework until visual direction and interaction density are validated.

## 7. Data Flow

```text
User Question
  -> Intent Workspace
  -> API: run trusted loop
  -> TrustedLoopResult
  -> EvidenceChain Viewer
  -> ActionProposal Panel
  -> Feedback Bar
  -> API: feedback / approval lite
```

The frontend consumes public API contracts only. It must not import `packages/os_core/`.

## 8. Minimum API Contract Needed

The workspace needs these response fields before live integration:

```text
intent.metric_name
query_plan.metric_name
query_plan.sql
evidence_chain.evidence_chain_id
evidence_chain.conclusion
evidence_chain.confidence
evidence_chain.limitations
evidence_chain.sql_safety
provider_contract.provider_id
provider_contract.name
data_product_candidate.data_product_id
action_proposal.proposal_id
action_proposal.recommended_action
action_proposal.risk_level
action_proposal.approval_required
trace_events[]
```

If a field is missing from the backend contract, the frontend must request a contract change instead of inventing a local-only field.

## 9. Testing Requirements

Frontend work is complete only when it includes:

- Component test or smoke test for loaded state.
- Empty state.
- Error state.
- Long text behavior.
- EvidenceChain visible check.
- ActionProposal risk display check.
- No OS Core import check.

For Stage F3, add browser smoke:

```text
open workspace
enter GMV question
run trusted loop
see EvidenceChain
see SQL Safety status
see ActionProposal
see trace id
```

## 10. Acceptance Criteria

The first usable workspace is accepted when:

1. A business owner can ask a GMV question from the UI.
2. The UI shows parsed intent and trace id.
3. The UI shows EvidenceChain, not just an answer.
4. The UI shows SQL Safety and provider/source information.
5. The UI shows ActionProposal with risk and approval requirement.
6. The UI can capture feedback.
7. UI smoke passes.
8. No domain-specific logic leaks into OS Core.

## 11. Risks

| Risk | Control |
|---|---|
| UI starts before API contract stabilizes | Static mock only until contract is tested |
| UI hides trust details | EvidenceChain Viewer is mandatory |
| UI becomes marketing/dashboard page | Workspace-first rule |
| Frontend invents backend fields | API contract gate |
| High-risk action accidentally executable | ActionProposal Panel is proposal-only for R4/R5 |

## 12. CTO Approval

Approved.

Frontend work may begin in Stage F0 immediately. Live API integration remains gated by API contract stability and backend tests.

