# Stage 1 Backlog

> Date: 2026-06-06  
> Owner: Project Manager Agent  
> Product source: `docs/product/PRD-MVP.md`

## Definition of Done

Every P0 task is done only when it has:

- Real entry point.
- Typed contract consumed or produced.
- Failure path.
- Test/eval written before implementation.
- Trace/Evidence/OperationTrace/Feedback/KnowledgeAsset update where relevant.
- OS Core boundary check.
- CTO approval if it touches contract, SQL Safety, EvidenceChain, Eval, Trace, Provider, ActionConnector, model routing, auth, deployment, or R4/R5.

## P0 Backlog

| ID | Epic | Task | Owner | DoD |
|---|---|---|---|---|
| P0-01 | Contract Spine | Verify BusinessIntent, MetricContract, ProviderContract, DataProductCandidate, EvidenceChain, ActionProposal, FeedbackEvent, KnowledgeAsset contracts cover Stage 1 | Contract Agent | Contract tests and no breaking change without ADR |
| P0-02 | SQL Safety | Keep select-star hardening and negative safety cases green | SQL Safety Agent | Safety tests include bypass and false-positive cases |
| P0-03 | DataProduct Candidate | Ensure trusted loop emits candidate from real query context | Data Product Compiler Agent | Unit/eval fails if candidate creation is bypassed |
| P0-04 | Governed Action | Ensure approval-required actions stop before side-effect execution | Action Governance Agent | Spy connector proves no unauthorized execute |
| P0-05 | Feedback Loop | Ensure `record_outcome` creates FeedbackEvent and versions KnowledgeAsset candidate | Feedback + Memory Agents | Unknown trace and known trace paths tested |
| P0-06 | Snapshot / Rollback | Keep action_record snapshot and rollback path real and tested | Action Connector Agent | Snapshot id returned and rollback restores state |
| P0-07 | API Trigger Surface | Keep `/runs`, `/outcomes`, CLI run, CLI record-outcome covered | Backend Core Agent | Auth negative paths and CLI tests pass |
| P0-08 | Eval Golden Loops | Map GMV, ROI, Daily Report to eval cases | Eval Agent | Eval report covers intent/metric/sql/evidence/action |
| P0-09 | Intent Workspace F1 | Add DataProduct candidate and KnowledgeAsset candidate visibility to prototype/scaffold | Frontend Workspace Agent | UI smoke sees evidence, action, feedback, knowledge candidate |
| P0-10 | Documentation Gate | Keep PRD, feature map, acceptance criteria, project plan synced | PM + Docs Agent | Source docs updated and no old `data-agent-os/` implementation path |

## P1 Backlog

| ID | Task | Owner | Trigger |
|---|---|---|---|
| P1-01 | Empty/loading UI states | Frontend Workspace Agent | Before UI ships beyond prototype |
| P1-02 | Persistent store ADR | CTO + Backend | Before cross-process feedback/knowledge requirement |
| P1-03 | Typed API client | Contract + Frontend | API contract stable |
| P1-04 | Eval threshold report | Eval Agent | Before release gate |
| P1-05 | KnowledgeAsset review queue | Product + Frontend | 3+ candidates need human review |

## Staged Out

- Full Data Fabric / NoETL.
- Broad provider marketplace.
- Full workflow engine / Temporal.
- R4/R5 automatic execution.
- Production deployment hardening.
