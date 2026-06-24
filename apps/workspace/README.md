# Workspace

User workspace UI boundary.

Authoritative architecture:

```text
../docs/architecture_reviews/AR-20260601-frontend-workspace-architecture.md
```

Implementation stage:

```text
F0: static workspace skeleton and contract-driven mock states
F1: static contract surface for EvidenceChain, DataProduct candidate, and KnowledgeAsset candidate
F2: ActionProposal and Approval Lite
F3: API integration and golden loop UI
```

Rules:

- Consume public API contracts only.
- Do not import OS Core.
- Do not invent backend fields locally.
- EvidenceChain, SQL Safety, provider/source, DataProduct candidate, ActionProposal,
  feedback, KnowledgeAsset candidate, and trace must be visible.

The first UI should expose BusinessIntent, EvidenceChain, DataProduct candidate,
ActionProposal, approval state, feedback, KnowledgeAsset candidate, and trace.

Prototype entry:

```text
prototype/index.html
```

The prototype is a contract-driven Intent Workspace concept surface. It demonstrates
business question intake, EvidenceChain review, DataProduct candidate reuse context,
SQL Safety state, ActionProposal governance, feedback-to-KnowledgeAsset candidate
review path, Trace, and Telemetry without becoming product runtime logic.

Current F1 boundary:

- Static prototype only; no live API integration.
- Contract-shaped mock state only; no locally invented backend fields.
- The UI smoke test in `tests/unit/test_workspace_prototype.py` locks DataProduct
  and KnowledgeAsset candidate visibility plus the no-OS-Core-import boundary.
