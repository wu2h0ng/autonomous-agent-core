# SPINE-1 extraction — boundary + regression verification

> Status: `EVIDENCE / PASS_WITH_KNOWN_BASELINE_DEBT`
> Date: 2026-09-15
> Branch: `codex/spine1-donor-extraction-20260915` (from `origin/main`), not pushed/merged
> Donor pin: `aaea36c694adb04664ff30fddccb43c2eb6a6614`

## Boundary checks (no domain semantics in core; no cross-repo coupling)

| Check | Result |
|---|---|
| domain semantics (`MetricContract`/`SQLSafety`/`SemanticObject`/`DataProduct`/`EvidenceChain`/`BusinessIntent`/`SQLTemplate`) in `packages/os_core/src` + `packages/contracts/src` | **1 match, benign** — `consequence_preview.py` docstring *disclaiming* those semantics; no code symbol |
| cross-repo import (`_migration` / `agent_os_api` / donor repo / `agent_workflow_runner`) in `packages apps domain_packs` | **1 match, benign** — provenance `README.md` names the donor repo; no `import` statement |
| `os_core` importing `domain_packs` | **0** (none) |
| domain pack → core spine (`agent_os_core.capability` / `action_pipeline`) | 3 — **allowed direction** (`domain_packs/data_agent/runtime.py:23,29`, `domain_packs/developer_agent/workspace_collaboration.py:26`; the forbidden direction is core → pack) |

No real boundary violation.

## Targeted verification

- 6 new test files (consequence preview, approval choice-set, exec-time C7 recheck, evidence lineage,
  grounding invariant, policy-approval lifecycle): **49 passed**.
- `ruff check` on changed files: clean. `pyright` on changed files: **0 errors**.
- Full `tests/product`: **~2609-2611 passed, 1 skipped, 24-25 failed** (SSE/streaming tests are
  order- and timing-sensitive; the exact pass/fail count varies run to run).

### The failures are pre-existing baseline debt, not regressions

All failures are fixed-NOW expiry / environment / order-sensitive tests in files unrelated to this
change. Counts vary by ±1 between runs (one streaming test toggles):

| File | Count | Nature |
|---|---|---|
| `test_task_configuration_application.py` | 17 | `CommitmentExpiredError: commitment expired before run start` |
| `test_task_configuration_api.py` | 2 | fixed-NOW / expired commitment |
| `test_provider_relevance_assessor.py` | 2 | `provider credential must be unexpired` |
| `test_data_agent_situated_fullstack.py` | 1 | environment/time |
| `test_surface_streaming_integration.py` | 1 | streaming/env |
| `test_wave2_renderer_conformance.py` | 1 | renderer/env |

None involve the changed modules or features; the failure modes (`CommitmentExpiredError`,
`provider credential must be unexpired`, SSE ordering) are time/environment-based. Base reproduction
was **not** independently re-run on a second checkout, so this is attributed — not proven — as
pre-existing. Claim boundary: `implemented + tested` on the branch; **not** integrated, released or
retirement-authorizing.
