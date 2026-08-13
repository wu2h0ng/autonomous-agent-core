# Merge Assessment: codex/native-surface-wave2a-macos-shell-20260812 into main

- Date: 2026-08-13
- Branches: wave lineage head `5256c566` (Wave 1 + 2a + 2b + 2c) vs `main` head `cf2af7ee`
- Merge-base: `27337578`; wave branch 65 ahead / 94 behind main
- Status: **BLOCKED — architectural divergence in the capability execution authority spine**

## Dry-run conflict surface

20 files, ~120 conflict hunks. Resolved cleanly (union/additive semantics) in a dry-run worktree:
`packages/contracts/src/agent_os_contracts/{belief,candidate,environment,evaluator}.py` (main wins — wave carried stale base copies), `runtime.py` (+7 session event types applied onto main), `__init__.py` (surface exports applied), `packages/os_core/src/agent_os_core/{governance,task_aggregate,__init__}.py` (wave guard/continuation additions applied onto main), `pyproject.toml` (agent-os-runtime script added), `docs/CURRENT_STATE.yaml` (wave entries unioned). These 10 files are mechanically mergeable.

## The blocking finding: capability execution authority architecture divergence

The remaining 10 files — `packages/os_core/src/agent_os_core/{agent_loop,task_service,capability,action_pipeline,execution}.py`, `apps/api_server/app.py`, `apps/cli/__main__.py`, and the dependent test files — carry TWO different implementations of the same authority-critical behavior:

- **main lineage** (`cf2af7ee`): `CapabilityBroker.invoke(action, permit, attempt)` performs correction-epoch checks inside the broker and calls `connector.execute(action)`; agent_loop is the terminal-coding-agent M1 evolution (main-integrated at `1f78937` lineage).
- **wave lineage** (`5256c566`): `WorkspaceSandbox.invoke(action, permit, correction, execution_lease=...)` drives a durable reservation → fenced-dispatch → receipt/outcome spine with lease-fenced execution ownership, UNKNOWN fail-closed semantics, and C7 dispatch linearization (`guard_unchanged`); agent_loop adds the durable session/approval/continuation system.

These are not textually conflicting edits — they are two coherent but incompatible execution-authority architectures for the same spine. A mechanical union would either duplicate the dispatch path (two ways to execute a capability) or silently drop one lineage's correction/receipt semantics, violating the product's non-negotiable authority invariants (typed dispatch, evidence, C7, exactly-once reservations).

## Required resolution path (not a mechanical merge)

1. A founder/CTO architecture decision: which execution-authority architecture is canonical for merged main — (a) main's broker-execute shape re-gaining wave's durable reservation/lease/receipt spine and C7 linearization, or (b) wave's sandbox spine normalized onto main's connector contract. This is a route decision the constitution reserves for the founder.
2. A dedicated merge-design task with a written architecture reconciliation (ADR), then per-file implementation with the full test suites (Python ~1800, Rust 21, Vitest 25) and independent exact-head review at each gate.
3. The ~10 mechanically-resolvable files can be merged first as a separate prep commit, but the authority files must wait for the architecture decision.

## Recommendation

Do NOT merge the wave lineage into main as-is. Either:
- (A) authorize a merge-design task (decision 1 → ADR → per-file implementation → review), or
- (B) keep `codex/native-surface-wave2a-macos-shell-20260812` as an independent integration line until the architecture decision is made.

Neither push nor merge has occurred. Wave 1/2a/2b/2c remain independently reviewed and branch-contained on the wave lineage (`5256c566`).
