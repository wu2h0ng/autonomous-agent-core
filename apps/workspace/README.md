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
F3a: limited live-run submit to POST /runs plus existing read-only report projection
F3 future: fuller API integration and golden-loop UI after separate CTO/founder gate
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

Current F3a boundary:

- Static prototype with two API-backed surfaces: limited `POST /runs` submit and
  read-only `GET /runs/{trace_id}/report`.
- The prototype maps the public `RunResponse.user_result` /
  `RunReportResponse.user_result` contract into the existing answer,
  EvidenceChain, dashboard, ActionProposal, DataProduct candidate, and
  KnowledgeAsset candidate panels.
- `POST /runs` sends only `question`, empty `parameters`, and `audience`; it is
  analysis/report generation only and does not execute approvals.
- It does not call `/outcomes`, `/approvals`, `/adoptions`, `/knowledge`,
  operator-key routes, or any management surface.
- Contract-shaped mock states remain available when no API endpoint is configured.
- The UI smoke test in `tests/unit/test_workspace_prototype.py` locks live-run
  and report-read markers, management-surface boundaries, DataProduct and
  KnowledgeAsset candidate visibility, script-global run handler scope, and the
  no-OS-Core-import boundary.
