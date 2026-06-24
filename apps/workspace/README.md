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
F2: read-only report projection from GET /runs/{trace_id}/report plus ActionProposal/Approval Lite visibility
F3: full API integration and golden loop UI
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

Current F2 boundary:

- Static prototype with one read-only API-backed surface: `GET /runs/{trace_id}/report`.
- The prototype maps the public `UserResultArtifact` contract into the existing
  answer, EvidenceChain, dashboard, ActionProposal, DataProduct candidate, and
  KnowledgeAsset candidate panels.
- It does not call `/outcomes`, `/approvals`, operator-key routes, or any write /
  management surface.
- Contract-shaped mock states remain available when no API endpoint is configured.
- The UI smoke test in `tests/unit/test_workspace_prototype.py` locks report-read
  markers, read-only boundaries, DataProduct and KnowledgeAsset candidate visibility,
  plus the no-OS-Core-import boundary.
