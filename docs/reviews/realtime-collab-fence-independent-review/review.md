# Realtime Collaboration Fence — Exact-Head Review (Round 2)

- Date: 2026-08-14
- Review target: `d0afc3a6106809c2736d5e5f780151f8ff55f1b3`
- Base: `c819f75b9ad01850a90850d72da2b621129308a2`
- Packet head inspected: `ce025eb5` (round-2 packet, manifest verified against target)
- Reviewer: OpenCode / DeepSeek (`deepseek/deepseek-v4-pro`), read-only review session
- Builder: Codex implementation session
- Identity: reviewer identity differs from builder (recast per founder rule 2026-08-14 §复审身份)

## Independent verification performed

Beyond the packet's recorded verification, the reviewer executed independent
runtime probes against the reviewed bytes:

1. registry exception (`connector.specs()` raises) → dispatch rejected (`CapabilityDenied`), zero execute.
2. collaboration-required write without preflight → rejected, `execute_count == 0`.
3. capability absent from trusted registry → rejected.
4. same-origin `task_id` mismatch → `CANCEL`.
5. unresolvable write scope (no `path`) → `CANCEL`.
6. `CONTEXT_CHANGED` event → broker blocks with `ReplanRequired`, `execute_count == 0`.
7. event-sequence gap → `complete=False` → `CANCEL`.
8. duplicate event sequence → `WorkspaceEventSequenceConflict`.
9. production `AgentOSApplication` wires `collaboration_preflight` + `workspace_fence`;
   `workspace.edit`/`workspace.apply_patch` marked collaboration-required; `workspace.read`
   not.
10. `open_chat_session` → `start_run` installs a run-bound lease into the fence.
11. the `AgentLoop` produced by the app carries the injected preflight.

Full Product suite (executed by builder, spot-re-run by reviewer): 2200 passed,
1 skipped, 1 failed (`test_product_entrypoint` editable-install environment debt,
reproduces on base). Ruff clean; Pyright 0 on changed files.

## Findings

### P0

None.

### P1

None.

### P2

1. `domain_packs/developer_agent/workspace_collaboration.py:146-153`: the
   same-origin binding checks `action.principal_id == lease.holder_id` but the
   `ExecutionLease.owner` field is no longer bound to anything. The production
   `RunCoordinator` issues a fresh `worker:{uuid}` owner per dispatch, so `owner`
   cannot meaningfully equal a principal. This is acceptable for the current
   single-principal slice, but the `owner` field's authority semantics should be
   documented or dropped before multi-principal collaboration.
2. `apps/api_server/app.py:1296`: the authoritative lease hard-codes
   `ResourceScope(resource_uri="file:///ws")` as the workspace root, while the
   scope resolver derives `file:///ws/{path}`. The coupling is consistent today
   but both sides depend on the literal `file:///ws` convention; a single named
   constant would reduce drift risk.
3. `domain_packs/developer_agent/workspace_collaboration.py:270-272`: the
   in-memory `read_coordination` timestamp (`datetime.now`) differs from the
   SQLite path's snapshot semantics; both are internally consistent but the
   in-memory fence is not cross-process linearizable (expected — it is the
   `:memory:` test path only).

## Verdict

`APPROVE_WITH_P2`

All five P1 findings from the first review (`84b41e2c`) are closed, verified by
independent runtime probes and not merely by the builder's recorded verification.
The three P2 findings are non-blocking documentation/consistency notes; none
constitutes a bypass, a regression, or an unsafe authority path.

This verdict applies only to target `d0afc3a6106809c2736d5e5f780151f8ff55f1b3`.
It does not authorize push, merge, release, production activation, or a product
completion claim. The CTO merge gate remains a separate decision.
