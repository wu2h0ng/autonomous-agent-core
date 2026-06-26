# MVP Acceptance Criteria

> Date: 2026-06-06  
> Owner: Product Manager Agent  
> Scope: Stage 1 Trusted Business Production Loop

## 1. Global Acceptance

| ID | Criteria | Required Evidence |
|---|---|---|
| G-01 | MVP is not reduced to trusted Q&A | DataProduct candidate, ActionProposal, Feedback/Trace, KnowledgeAsset candidate exist in loop |
| G-02 | Every formal answer has EvidenceChain | EvidenceChain id visible in result/API/UI |
| G-03 | Unsafe SQL blocks answer and action | Negative SQL Safety test and blocked UI/API state |
| G-04 | ActionProposal references evidence | proposal includes evidence id or trace link |
| G-05 | R4/R5 are proposal-only | test proves approval-required action does not execute side effects |
| G-06 | Feedback can update learning asset | record_outcome or feedback path creates/version KnowledgeAsset candidate |
| G-07 | No domain logic leaks into OS Core | import boundary test or review check |
| G-08 | No pseudo implementation | real entry point + failure path + non-fixture test |

## 2. Scenario Acceptance

### AC-GMV: GMV Anomaly

Given an operations manager asks whether GMV is abnormal, when the trusted loop runs, then the system must:

- Resolve BusinessIntent with metric `GMV` and time window.
- Bind a MetricContract and ProviderContract.
- Create a DataProduct candidate or reuse candidate context.
- Pass SQL Safety before query execution.
- Return EvidenceChain with SQL evidence, source/provider, limitations, and confidence.
- Create an ActionProposal with risk level and approval requirement.
- Emit trace id and feedback/knowledge candidate path.

Negative path:

- If SQL Safety blocks the query, no formal answer and no ActionProposal are produced.

### AC-ROI: ROI Diagnosis

Given a business user asks why ROI dropped, when the system analyzes channel/material performance, then it must:

- Bind ROI metric definition and owner.
- Explain result with evidence, not unsupported natural language.
- Distinguish recommendation from execution.
- Require approval for any budget or campaign action.
- Track feedback metrics such as ROI, spend, conversion rate, and GMV.

Negative path:

- If material owner or key attribution dimension is missing, result enters insufficient-evidence state.

### AC-DAILY: Daily Scan

Given an operations lead requests a daily report, when the scan completes, then it must:

- Summarize the MVP metric subset explicitly.
- Flag priority anomaly and route to diagnosis loop.
- Mark unsupported dimensions as limitations.
- Avoid pretending to cover inventory/content metrics if not connected.

Negative path:

- Empty or unsupported metric set shows an empty/unsupported state rather than a fabricated report.

## 3. UI Acceptance

| ID | Criteria | Status |
|---|---|---|
| UI-01 | Business Context visible | F0 pass |
| UI-02 | Trusted Answer visible with confidence/eval/block count | F0 pass |
| UI-03 | EvidenceChain visible as first-class section | F0 pass |
| UI-04 | DataProduct candidate visible or planned for F1 | F1 static pass |
| UI-05 | Action Governance visible with risk and approval | F0 pass |
| UI-06 | Feedback controls visible | F0 pass |
| UI-07 | Trace id and steps visible | F0 pass |
| UI-08 | SQL blocked state visible | F0 pass |
| UI-09 | Insufficient evidence state visible | F0 pass |
| UI-10 | Loading and empty states visible | P1 required |
| UI-11 | KnowledgeAsset candidate review path visible | F1 static pass |

## 4. CTO Exit Gate

Before Stage 1 is accepted:

- Unit/eval tests must pass.
- SQL Safety safety_pass_rate must be 1.0 on covered cases.
- EvidenceChain rate must be 1.0 for formal answers.
- At least one feedback-to-KnowledgeAsset path must run from a real entry point.
- At least one governed action path must prove no unauthorized execution.
- Documentation must state entry point, contracts, negative path, tests, and boundary status.
