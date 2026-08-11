# Frontend Workspace V2 Development Alignment

> Date: 2026-06-03  
> Participants represented: Product Manager, Project Manager, Frontend Workspace Agent, CTO Gate, CEO reporting  
> Scope: Intent Workspace F0 prototype refresh

## 1. Decision Summary

The V1 visual direction is rejected for productization. It looked like a concept document and did not clearly communicate the operational workflow.

V2 is accepted as the new F0 direction for development alignment:

```text
Business Context | DataProduct + Trusted Answer + EvidenceChain | Action Governance + Feedback + KnowledgeAsset + Trace
```

After the 2026-06-06 product-definition update, frontend scope must not present the MVP as trusted Q&A only. The workspace is the human control surface for the minimum trusted business production loop.

## 2. Project Manager Alignment

Add these items to the frontend backlog.

| Priority | Item | Owner | Definition of Done |
|---|---|---|---|
| P0 | Preserve V2 information architecture in frontend scaffold | Frontend Workspace Agent | Intent, Evidence, Action, Trace, Feedback areas render |
| P0 | Create typed mock state model | Frontend Workspace Agent | loaded / blocked / insufficient evidence states exist |
| P0 | Add UI smoke for desktop loaded state | Test Automation Agent | Browser smoke sees question, EvidenceChain, SQL Safety, ActionProposal, trace |
| P0 | Add no-OS-Core-import check | Frontend Workspace Agent | UI package does not import `packages/os_core` |
| P0 | Add DataProduct candidate visibility | Frontend Workspace Agent | Workspace shows candidate id/status/source context |
| P0 | Add KnowledgeAsset candidate visibility | Frontend Workspace Agent | Workspace shows whether feedback can create/review an asset |
| P1 | Add empty and loading states | Frontend Workspace Agent | States visible and understandable |
| P1 | Map to API contract when stable | Frontend + Contract Agent | No local-only backend fields |

## 3. Development Requirements

- Use the current prototype only as static UI behavior, not runtime logic.
- Keep mock data contract-shaped.
- Do not add backend fields in frontend.
- Do not hide EvidenceChain behind generic AI answer UI.
- Do not allow high-risk actions to execute.
- Keep business-domain examples in mock data or domain-pack context, not OS Core.
- Do not reduce the product to trusted Q&A; show DataProduct and KnowledgeAsset candidate path.

## 4. CTO Gate Conditions

CTO approval is required before:

- Live API integration.
- Any schema or public API change.
- Any R4/R5 action workflow.
- Any model routing or prompt behavior change.
- Any weakening of SQL Safety, Eval, EvidenceChain, Trace, or Approval gates.

## 5. CEO Reporting Line

CEO-facing message:

The product direction is now clearer. The workspace demonstrates how a business user moves from a question to evidence, then to a governed action proposal. It is still an F0 prototype, not a production demo. The next milestone is a tested frontend scaffold and a live golden-loop integration after backend contracts stabilize.

Updated 2026-06-06 CEO-facing message:

The workspace must demonstrate a business production loop: business intent becomes a reusable DataProduct candidate, trusted EvidenceChain, governed ActionProposal, approval/feedback trace, and KnowledgeAsset candidate. This is still not a production demo, but the product story is no longer just "ask a question and see evidence."

## 6. Open Risks

| Risk | Mitigation |
|---|---|
| Static prototype gets treated as production demo | Mark F0 scope in docs and sidebar |
| Frontend invents fields before contract stabilization | Gate API integration through Contract Agent |
| UI polish hides trust details | EvidenceChain remains mandatory |
| Mobile scope expands too early | Keep mobile readable, not full operational flow |
| UI underrepresents DataProduct/KnowledgeAsset | Add F1 sections before live integration |

## 7. Handoff Status

Status: ready for frontend scaffold planning, with F1 scope updated for DataProduct and KnowledgeAsset candidate visibility.

Not ready for live API integration.
