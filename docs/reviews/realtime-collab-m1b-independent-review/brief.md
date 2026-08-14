# Realtime Collaboration M1b — Independent Exact-Head Review Brief

- Review target: `4f5753fd96fd93109c636fc6b80c44302113abd2` (feature/realtime-collab-surface-m1b-20260814)
- Base: `bcab802efb974634b90e32c91c4f78eec8023ef7` (local main; M1a merge + P2 #4/#5 closed)
- Track: Product / Architecture / Engineering review
- Reviewer: OpenCode / DeepSeek (`deepseek/deepseek-v4-pro`), read-only
- Builder: Codex

## Question

Review whether the M1b implementation correctly adds, on top of the M1a runtime
fence, three capabilities without weakening the ADR-0059 single-dispatch spine:

1. **WorkspaceEventProducer** (closes P2 #3): translates external file writes into
   append-only `WorkspaceEvent` records on the fence, advancing the coordination
   cursor. It must hold no authority and never dispatch.
2. **Cursor advance**: a new run's lease cursor starts at the fence high-water
   instead of hard-coded 0, so replanning after a conflict does not permanently
   block. Must fail-safe if the fence read fails.
3. **SurfaceConflictProjection**: a typed read-only projection derived from a
   `WorkspaceWriteDecision` (REPLAN→REPLAN, CONFLICT→REVIEW_DIFF, CANCEL→NONE),
   exported through `agent_os_contracts.surface`.

The reviewer must not edit implementation files. Findings must cite files/lines
and conclude `APPROVE`, `APPROVE_WITH_P2`, or `REVISE`.

## Exact-content manifest

`manifest.sha256` binds the four mechanism files. Drift invalidates this review.
