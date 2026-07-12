# T-P-OS-SPINE-0 Implementation Report

Date: 2026-07-10

This report records the implementation state after the design packet was accepted. It
does not promote any Research Track result or claim Codex parity.

PM Product Acceptance remained a separate gate. Its first review returned `REJECT` with
four P0 blockers. Provider-driven patch binding, repository onboarding, provider setup and
the Task Workspace were remediated; the clean-workspace re-review returned `ACCEPT`. See
`docs/product/PM-PRODUCT-ACCEPTANCE-SPINE-0-2026-07-10.md`.

## Implemented

- canonical Goal, Commitment, WorkflowGraph, GraphPatch, AgentRun, Action, Provider, Capability,
  Evidence and Outcome contracts with canonical digests;
- structural graph validation, including duplicate, cycle, unreachable and non-terminal
  paths;
- append-only SQLite WAL event store and a PostgreSQL adapter using the same port;
- task/run replay, lease fencing, explicit stale-worker recovery and idempotency keys;
- deterministic PolicyKernel, externally persisted correction epochs and permit binding;
- explicit CapabilityBroker boundary and approval/correction authority paths;
- non-secret CredentialRef resolution, local Integration Center connection testing and
  typed OpenAI-compatible provider failures;
- workspace-scoped read, patch, test and content-addressed artifact capabilities;
- path/symlink/command/network-boundary checks and sandbox compensation snapshots;
- deterministic evidence-based outcome evaluation;
- one RunCoordinator used by the HTTP API, CLI and Task Workspace;
- developer-agent domain-pack manifest and a provider-generated, exact-digest-approved
  repository patch golden path with no user-supplied final content;
- HTTP JSON API (workflow validation, start, approval, artifact/evidence reads), SSE event
  stream, local CLI and operational HTML workspace.

## Verification

Product tests (`96 passed, 1 skipped`) cover restart after a committed node, provider
proposal binding, approval-before-effect, malformed-output zero-write behavior, failed-run
retry, idempotent replay, policy denial,
correction persistence, path and command denial, domain-pack registration, API access,
workflow execution, artifacts and outcome evaluation. Credentialed live provider and
real-provider golden-path acceptance are recorded in
`SPINE-0-LIVE-PROVIDER-ACCEPTANCE-2026-07-10.md`.

The full regression is `1321 passed, 14 skipped, 5 subtests passed`; the opt-in live-provider
smoke separately passed `1/1`. Ruff is clean and pyright reports zero errors. PM browser
evidence records desktop/mobile rendering, real Kimi proposal generation, before/after
review, verified pytest evidence and failure recovery without console errors.

The implementation remains local/controlled-sandbox product infrastructure. It does not
claim production KMS, SSO, public multi-tenant deployment, arbitrary shell access,
enterprise consequential actions, CWM promotion, subagent swarms or product superiority.
