# Risk Register

> Date: 2026-06-06  
> Owner: Project Manager Agent

| ID | Risk | Probability | Impact | Owner | Mitigation |
|---|---|---:|---:|---|---|
| R-01 | MVP slips back into trusted Q&A only | Medium | High | Product + CTO | PRD/acceptance requires DataProduct, Action, Feedback, Knowledge |
| R-02 | Data Fabric temptation expands scope | Medium | High | CTO | Follow 8.8 decision: ride data plane, own contract spine |
| R-03 | Pseudo implementation passes review | Medium | High | Code Review Agent | Enforce entry point, failure path, non-fixture test |
| R-04 | SQL Safety bypass | Low | High | SQL Safety Agent | Regression tests and safety_pass_rate 1.0 |
| R-05 | Action connector executes before approval | Low | Critical | Action Governance Agent | Spy connector and AWAITING_APPROVAL tests |
| R-06 | Feedback/KnowledgeAsset only works in-process | Medium | Medium | Backend + CTO | Persistence ADR before pilot |
| R-07 | Frontend invents backend fields | Medium | Medium | Frontend + Contract | Contract-shaped mocks only; typed API gate |
| R-08 | Domain logic leaks into OS Core | Low | High | Architecture Agent | Import boundary review |
| R-09 | Parallel agent stale-base integration overwrites governance fixes | Medium | High | Development Team Agent | Verify worktree base; manually integrate orchestrator changes |
| R-10 | CEO/demo messaging overclaims production readiness | Medium | High | CEO + PM | Mark implemented vs prototype vs staged-out |

## CTO Escalation Conditions

- Any P0 scope change.
- Contract/API/schema change.
- SQL Safety/EvidenceChain/Eval/Trace weakening.
- New Provider or ActionConnector behavior.
- R4/R5 execution request.
- Persistent storage or auth model change.
