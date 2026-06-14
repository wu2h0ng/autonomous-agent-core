# Intent Workspace Prototype V2 Requirements

> Date: 2026-06-03  
> Owner: Product Manager Agent  
> Scope: `ai-native-business-data-agent-os/apps/workspace/prototype/index.html`  
> Stage: F0 static workspace skeleton

## 1. Product Decision

Replace the first prototype visual direction with a desktop-first enterprise workspace.

The prototype must express the core product chain. After the 2026-06-06 product-definition update, this chain is no longer "trusted answer only":

```text
Business question
  -> DataProduct candidate
  -> trusted answer
  -> EvidenceChain
  -> ActionProposal
  -> approval / feedback
  -> trace
  -> KnowledgeAsset candidate
```

The UI is not a BI dashboard, chat page, or marketing page. It is the human control surface for trusted business data work.

## 2. User Goal

The first target user is a business owner or operations manager who needs to answer:

1. What question did the system understand?
2. Why is the answer trustworthy?
3. What action is proposed?
4. What requires approval or more evidence?

## 3. Required MVP Modules

| Module | Product Requirement | F0 Prototype Status |
|---|---|---|
| Business Context | Show question, role, metric, time window, trace id, scenario shortcuts | Implemented as static mock |
| Trusted Answer | Show conclusion, confidence, eval coverage, blocking issue count | Implemented as static mock |
| DataProduct Candidate | Show reusable/reviewable data product candidate context | F1 required |
| EvidenceChain | Show metric contract, provider/source, SQL evidence, limitations | Implemented as static mock |
| Action Governance | Show recommended action, risk level, approval state, observation window, feedback metrics | Implemented as static mock |
| Governance Status | Show evidence id, SQL safety, approval, feedback, gap note | Implemented as static mock |
| KnowledgeAsset Candidate | Show whether the loop can become a reviewable knowledge asset | F1 required |
| Trace | Show ordered execution steps | Implemented as static mock |
| Failure States | Show loaded, SQL blocked, insufficient evidence states | Implemented as static mock |

## 4. Functional Scope

### P0

- GMV abnormality question.
- ROI diagnosis question.
- Daily report scan question.
- Loaded state.
- SQL blocked state.
- Insufficient evidence state.
- EvidenceChain visible without hiding behind a generic answer card.
- ActionProposal displayed as proposal or approval draft only.
- Trace id visible.
- Feedback and KnowledgeAsset candidate path is represented at least as staged F1.

### P1

- Typed API response mapping once backend contracts are stable.
- Empty and loading states.
- More complete feedback event model.
- DataProduct candidate and KnowledgeAsset candidate visibility.
- UI smoke test in CI.

### P2

- Telemetry dashboard.
- KnowledgeAsset registry view.
- Cross-workflow history.
- Mobile operational workflow.

## 5. Non-Goals

- No live API integration in F0.
- No new backend contract fields.
- No OS Core import.
- No direct R4/R5 business action execution.
- No production-data query.
- No domain-pack business logic embedded in Core.

## 6. Acceptance Criteria

| ID | Criteria | Status |
|---|---|---|
| AC-01 | Business owner can see and edit a business question | Pass |
| AC-02 | Parsed intent context is visible | Pass |
| AC-03 | Formal answer is accompanied by EvidenceChain | Pass |
| AC-04 | SQL Safety state is visible | Pass |
| AC-05 | Provider/source and SQL evidence are visible | Pass |
| AC-06 | ActionProposal has risk and approval requirement | Pass |
| AC-07 | Feedback controls are visible | Pass |
| AC-08 | Trace id and trace steps are visible | Pass |
| AC-09 | SQL blocked state exists | Pass |
| AC-10 | Insufficient evidence state exists | Pass |
| AC-11 | Mobile first screen does not get trapped by sidebar | Pass |
| AC-12 | DataProduct candidate is visible or explicitly staged for F1 | F1 required |
| AC-13 | KnowledgeAsset candidate is visible or explicitly staged for F1 | F1 required |

## 7. Engineering Handoff

Prototype entry:

```text
ai-native-business-data-agent-os/apps/workspace/prototype/index.html
```

Verification screenshots:

```text
output/playwright/workspace-prototype-v2-desktop.png
output/playwright/workspace-prototype-v2-mobile.png
```

Next engineering step:

1. Keep this as F0 static prototype.
2. Convert into React/Next.js component boundaries only after frontend scaffold is created.
3. Add F1 visibility for DataProduct candidate and KnowledgeAsset candidate before live API integration.
4. Do not integrate live APIs until typed contracts and backend tests are stable.
