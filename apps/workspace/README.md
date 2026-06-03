# Workspace

User workspace UI boundary.

Authoritative architecture:

```text
../docs/architecture_reviews/AR-20260601-frontend-workspace-architecture.md
```

Implementation stage:

```text
F0: static workspace skeleton and contract-driven mock states
F1: EvidenceChain Viewer
F2: ActionProposal and Approval Lite
F3: API integration and golden loop UI
```

Rules:

- Consume public API contracts only.
- Do not import OS Core.
- Do not invent backend fields locally.
- EvidenceChain, SQL Safety, provider/source, ActionProposal, trace, and feedback must be visible.

The first UI should expose BusinessIntent, EvidenceChain, ActionProposal, approval state, and trace.

Prototype entry:

```text
prototype/index.html
```

The prototype is a contract-driven Intent Workspace concept surface. It demonstrates business question intake, EvidenceChain review, SQL Safety state, ActionProposal governance, Trace, and Telemetry without becoming product runtime logic.
