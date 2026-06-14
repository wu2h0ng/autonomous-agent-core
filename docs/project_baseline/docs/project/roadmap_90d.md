# 90-Day Roadmap

> Date: 2026-06-06  
> Owner: Project Manager Agent  
> Goal: deliver a demonstrable, testable, auditable Stage 1 trusted business production loop.

## Milestones

| Phase | Weeks | Outcome | Exit Criteria |
|---|---:|---|---|
| M1 Contract Spine Hardening | W1-W2 | Contracts, SQL Safety, Query Runtime, DataProduct candidate stable for golden loops | Unit/eval green; unsafe SQL blocked; candidate emitted |
| M2 Governed Operation Loop | W3-W4 | ActionProposal, Approval lite, OperationTrace, action_record, snapshot/rollback real path | Approval-required action cannot execute; rollback path tested |
| M3 Feedback and Knowledge Loop | W5-W6 | record_outcome, FeedbackEvent, KnowledgeAsset candidate/version path | Known trace updates knowledge; unknown trace does not fake knowledge |
| M4 API and CLI Trigger Surface | W7-W8 | CLI/API exposes run and outcome flows with auth boundaries | `/runs`, `/outcomes`, CLI run, CLI record-outcome tested |
| M5 Workspace F1 | W9-W10 | Intent Workspace shows DataProduct, Evidence, Action, Feedback, Knowledge candidate | UI smoke covers loaded, blocked, insufficient evidence |
| M6 Pilot Readiness Review | W11-W12 | CEO/CTO can judge whether to enter POC/customer validation | Golden loops pass; docs current; risks accepted or blocked |

## 90-Day Acceptance

- At least 3 golden business loops are covered.
- EvidenceChain rate is 1.0 for formal answers.
- SQL Safety pass/block correctness is 1.0 for covered cases.
- At least one governed action path proves approval before side effects.
- At least one FeedbackEvent to KnowledgeAsset candidate/version path is real.
- UI communicates the loop without hiding evidence or action governance.

## Stop Conditions

- Any P0 depends on hard-coded demo-only behavior.
- SQL Safety or EvidenceChain can be bypassed.
- Action execution happens before approval when approval is required.
- OS Core imports domain packs/providers/action connectors.
- Product scope drifts into full Data Fabric or connector marketplace before Stage 1 proof.
