# Independent Exact-Head Review — b32f2cb "feat(selfdev): bind scoped product verifiers"

- Reviewer identity: `opencode-go/kimi-k3` (Kimi K3, independent of builder)
- Builder: Codex
- Target SHA: `b32f2cb2e499ba8e07e1b2b9551fc5036763a8bd` (HEAD of `codex/selfdev-scoped-verifier-20260808`)
- Review date: 2026-08-09
- Scope: single commit, 9 files, +972/-41, per `.agent_runs/selfdev-scoped-verifier-review-20260808/brief.md`

## Reassignment chain (as recorded)

claude-code (OAuth revoked 401) -> opencode/big-pickle (Zen balance insufficient) -> opencode/claude-sonnet-4-5+glm-5.2+deepseek-v4-pro+gpt-5.1 (Zen balance insufficient) -> volcengine/kimi-k2.6 (invalid auth) -> arkcli (STS expired) -> opencode-go/kimi-k3 (available, this review)

## Method

- Read the full diff (`git show b32f2cb`) and the full post-commit contents of `responsibility.py`, `capability.py`, `execution.py` (outcome evaluator + `_tool_arguments`), `self_development_organ.py`, `selfdev_admission.py`, `mandate_responsibility.py` (link digest chain), and `common.py` (`ContractModel`/`content_digest`).
- Created a detached temp worktree at b32f2cb and ran the brief's verification (results below); worktrees removed afterward. No source files modified, no commits made.

## Verification evidence (run at b32f2cb, macOS, sandbox-exec present)

- `pytest tests/product/test_selfdev_scoped_verifier.py tests/product/test_selfdev_admission.py -q` -> **58 passed** (54.5s)
- `pytest tests/product/test_responsibility_controller.py -q` -> **40 passed** (37.9s)
- `ruff check packages/contracts/src packages/os_core/src` + 3 changed test files -> **All checks passed**
- `pyright packages/contracts/src packages/os_core/src tests/product/test_selfdev_scoped_verifier.py` -> 1 error in `packages/contracts/src/agent_os_contracts/workflow.py:123` (`schema_version` override invariance). **Confirmed pre-existing**: identical error reproduced at parent `802ad98` in files untouched by this commit. Not a regression from b32f2cb, but the documented pyright product gate is red at this exact head for an unrelated pre-existing reason.

## Review focus answers

1. **No-self-approval / C7 non-bypass — SATISFIED.** Verifier bindings are computed exclusively server-side in `_seal_verifier_bindings` (selfdev_admission.py:120-188 at commit). Caller-supplied bindings are rejected twice: contract model validator ("server-computed", responsibility.py:247-250) and admission runtime (`ADMISSION_VERIFIER_INVALID`, selfdev_admission.py:123-127). The sealed spec is bound into the semantic key (selfdev_admission.py:1117-1127), the persisted plan, the `MandateTaskLink` command digest (selfdev_admission.py:1295-1301, 891-901), and the receipt `work_spec_digest` (selfdev_admission.py:1030-1033). The organ re-asserts bindings before the agent loop and at every phase transition (self_development_organ.py:65, 72-80, 152-222). The sandbox executes only bound paths, from sealed git base blobs (not worktree bytes), inside a network-denied `sandbox-exec` profile (capability.py:866-1087). C7/correction authority surfaces are untouched.
2. **Enforced in product path — YES.** Sealing (admission) -> assertion + envelope (organ) -> snapshot forwarding (execution.py:1556-1570) -> strict snapshot validation + mirror run (capability.py). Not test-only, not mock-only, no constant returns.
3. **Failure paths — fail-closed.** Malformed snapshot keys, binding count outside 1..8, missing/extra binding keys, wrong `schema_version`, non-canonical path, unavailable/non-blob/gitlink base object, blob digest mismatch, worktree oracle drift, duplicate paths, digest drift, HEAD drift, missing sandbox runtime all raise `CapabilityDenied`/`SelfDevelopmentOrganBlocked`. Tests cover reorder tamper, extra-field tamper, digest tamper, worktree drift, oracle self-write attempt (exit != 0, worktree bytes unchanged), and admission-time symlink/gitlink/missing oracles. Write-set/verifier-set disjointness is structural (targets restricted to `packages/os_core/src/agent_os_core/`, verifiers to `tests/product/test_*.py`) and additionally checked at admission and organ.
4. **Regressions — none found.** `execution.py` snapshot keys changed from `target_path(s)` to sealed bindings; the only consumer is the same-commit `capability.py` mirror runner and the only producer is the same-commit organ. `_receipt` now digests the sealed spec instead of the unsealed caller spec — an integrity improvement. Responsibility-controller tests updated consistently and pass.
5. **Claim boundary — respected.** Commit message, code, and tests claim only "scoped verifier binding"; no autonomy/self-improvement claims. This is L0-L3-style external candidate handling; no L4/L5 self-modification introduced.

## Findings

### P0
None.

### P1
None.

### P2

1. **No evaluation-time cross-check of the verifier seal.** `DeterministicOutcomeEvaluator.evaluate` (execution.py:88-161 at commit) validates exit-code/artifact binding but never compares the test-report artifact's `verifier_binding_digest` (recorded at capability.py:853-858) against the admission-sealed digest. The report-to-oracle binding holds today by construction (organ is the sole SELFDEV entry and always injects the envelope; RunCoordinator always attaches the snapshot when the envelope is present). If any future path produces a binding-less report for a SELFDEV run, evaluation would still return VERIFIED on exit 0. Recommend a follow-up: carry the sealed digest into the expected-outcome/run record and fail closed (INVALID/UNRESOLVED) when the report's digest is absent or mismatched.
2. **Cosmetic indentation drift.** `argv = [...]` literal at capability.py:1065-1077 is indented one extra level versus the surrounding block; same pattern in the expected-envelope dict in tests/product/test_responsibility_controller.py (~lines 777-790 at commit). Ruff-clean; style nit only.
3. **Test helper masks fixture defects.** `_test_verifier_bindings` (tests/product/test_responsibility_controller.py:87-103 at commit) silently returns `()` when `git show` fails, converting a fixture problem into a later, less-diagnosable `SELFDEV_VERIFIER_UNBOUND` failure. Harmless while the suite is green; weakens diagnostics.

## Open questions

1. `inspect_selfdev_workspace` (self_development_organ.py:357-378) does not re-assert verifier bindings and is used by admission recovery (selfdev_admission.py:93). Current execution paths re-assert via the organ, so this is believed safe — confirm no resume/re-admit decision relies on inspection output alone for oracle integrity.
2. Is a typed receipt field for the sealed verifier digest planned (e.g., on `ValidatedTestReport` or the admission receipt), so P2-1 can be enforced at evaluation time rather than by construction?
3. The non-snapshot fallback in `_run_tests` (capability.py:840-844) runs full-suite pytest in the live worktree for ordinary tasks. For a SELFDEV-routed run, is any caller-reachable path able to omit `selfdev_execution_envelope` (e.g., hand-constructed context), and should that fail closed instead of falling back?

## Required changes

None blocking. P2-1 is recommended as a follow-up hardening task; P2-2/P2-3 are optional.

## Exact-head verdict

**APPROVE_WITH_P2** — bound to SHA `b32f2cb2e499ba8e07e1b2b9551fc5036763a8bd`.

The commit delivers genuine, product-path-enforced scoped verifier binding: server-sealed immutable oracles, tamper-evident digest chaining through plan/link/receipt, fail-closed drift detection, and sandboxed execution from sealed base blobs — with no-self-approval preserved and claim boundaries respected. The three P2 items are hardening/cosmetic and do not undermine the merge-worthiness of this exact head.
