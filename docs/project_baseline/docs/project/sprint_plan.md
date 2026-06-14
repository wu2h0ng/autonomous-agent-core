# Sprint Plan

> Date: 2026-06-06  
> Owner: Project Manager Agent  
> Planning horizon: next 3 engineering sprints

## Sprint 1: Contract Spine and Safety

Goal: make the trusted data path hard to bypass.

| Task | Owner | Gate |
|---|---|---|
| Re-run and review contract test coverage | Contract Agent | tests first |
| Keep SQL Safety select-star hardening green | SQL Safety Agent | negative tests |
| Confirm DataProduct candidate is emitted from trusted loop | Data Product Compiler Agent | non-stub unit/eval |
| Update eval cases for GMV / ROI / Daily Report | Eval Agent | eval report |

Exit:

- Unit/eval green.
- No formal answer path without SQL Safety and EvidenceChain.

## Sprint 2: Governed Operation and Feedback

Goal: prove action governance and learning loop are real.

| Task | Owner | Gate |
|---|---|---|
| Verify approval-required actions stop at `AWAITING_APPROVAL` | Action Governance Agent | spy connector test |
| Verify action_record snapshot and rollback | Action Connector Agent | rollback test |
| Verify record_outcome feedback to KnowledgeAsset version | Feedback + Memory Agents | known/unknown trace tests |
| Document ActionProposal routing decision point | Product + CTO | decision recorded |

Exit:

- No unauthorized side effect.
- At least one reversible action path tested.
- Feedback-to-knowledge path tested.

## Sprint 3: API/UI Readiness

Goal: make the loop visible and triggerable.

| Task | Owner | Gate |
|---|---|---|
| Keep CLI run and record-outcome paths tested | Backend Core Agent | CLI tests |
| Keep HTTP auth boundaries tested | Backend Core Agent | 503/401 tests |
| Update Intent Workspace to show DataProduct and KnowledgeAsset candidate | Frontend Workspace Agent | UI smoke |
| Prepare CTO Stage 1 readiness review | PM + CTO | approval record |

Exit:

- API/CLI entry points documented.
- UI communicates full loop.
- CTO can approve or block pilot readiness.
