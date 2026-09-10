# Agent OS Dual Workbench Slice 1 Independent Review

| Field | Value |
|---|---|
| reviewer | codex-primary |
| builder | kimi-builder |
| reviewed range | `e4461dbe^..ac3c6d94` / requested implementation slice `e4461dbe..ac3c6d94` |
| review time | 2026-09-10T21:35:42+08:00 |
| verdict | **REVISE_TO_SPEC** |

## Summary

I did not rely on builder records. I read `docs/CURRENT_STATE.yaml`, the review request, the untracked Spec V2, the commit range, the patch surface, the overlay implementation, generated upstream files, and reran the requested verification commands as far as this sandbox permits.

Final judgment: **REVISE_TO_SPEC**. The approval bar is `P0=0 && P1=0`; I found **P1=1** in lifecycle pid-reuse handling, and the required verification gates did not produce the requested green evidence in this environment.

## Required Verification Reruns

1. `cd apps/code-oss && node scripts/verify.mjs`
   - Result: **FAIL**, 35/42 pass, 7/42 fail.
   - Failure mode: every failed subtest in `runtime-task-bridge.test.mjs` failed before assertions with `listen EPERM: operation not permitted 127.0.0.1`.
   - Independent sanity check: a minimal Node `createServer(...).listen(0, "127.0.0.1")` also fails with the same `EPERM`, so this is a sandbox/network permission blocker, not evidence that bridge assertions are false.

2. `cd apps/code-oss && node tests/dual-workbench-slice-1.test.mjs`
   - Result: **FAIL**, 0/1 pass.
   - Failure mode: timed out waiting for runtime descriptor.
   - Runtime log shows Python `ThreadingHTTPServer` failed at bind with `PermissionError: [Errno 1] Operation not permitted`.

3. `cd apps/code-oss && npm run compile`
   - Result: **FAIL**, `apps/code-oss/package.json` does not exist in this repo layout.
   - Equivalent actual Code-OSS checkout command: `cd .code-oss/upstream && npm run compile`.
   - Result: **FAIL**, `compile-copilot` failed when `tsx` tried to create `/var/.../tsx-501/*.pipe` with `listen EPERM`; then `npm-run-all2` hit `spawn EPERM`.
   - Additional scoped signal: `cd .code-oss/upstream && npm run compile-client` **PASS**, including `compile-src ... src/tsconfig.json with 0 errors`.

4. `git log --oneline e4461dbe^..ac3c6d94`
   - Confirmed six commits:
     - `ac3c6d94 test(agentos): verify dual workbench slice one`
     - `b8248ba1 feat(agentos): project runtime tasks into sessions`
     - `777bad1d feat(agentos): bridge read-only runtime task catalog`
     - `5cd01d66 feat(agentos): define read-only task catalog contract`
     - `5b132ee6 feat(code-oss): adopt native sessions workbench`
     - `e4461dbe build(code-oss): close 1.136.2 install toolchain`

5. `git diff --stat e4461dbe..ac3c6d94`
   - Confirmed 26 files changed, 2525 insertions, 13 deletions.
   - Main implementation surface is `apps/code-oss/overlay-src/src/vs/agentos/`, `apps/code-oss/patches/010-agent-os-sessions-window.patch`, and focused tests.

## Findings

### P1-1: Runtime quit can still SIGKILL a reused pid during the 5s grace window

File: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/interactiveRuntimeLifecycle.ts`

Lines reviewed: 38-78.

`beginInteractiveRuntimeTermination()` validates descriptor safety and re-reads `pid/boot_id` immediately before SIGTERM. After that it stores only `pid`, polls `kill(pid, 0)` every 50ms, and if the pid is still alive at deadline it sends SIGKILL to that pid.

This does **not** satisfy the review request's lifecycle requirement: "SIGTERM -> 50ms polling -> 5s SIGKILL, boot_id 防 pid 复用". If the intended runtime exits after SIGTERM and the OS reuses the pid before the next poll or before deadline, the loop has no remaining boot identity check. It may treat the reused process as the still-live runtime and SIGKILL it.

Required fix: before any destructive escalation and ideally during polling, revalidate the descriptor/runtime identity against `pid + boot_id` or use a process handle/child ownership primitive that cannot target a reused pid. If identity cannot be proven, fail closed and do not SIGKILL.

## Review Questions

1. **密钥红线**
   - Code inspection: bearer token is read only in main-side `RuntimeTaskCatalogMainService`; IPC channel exposes only `listTasks`; renderer proxy has no descriptor or token field.
   - Decoder rejects root/task extra keys including `bearer_token`/token-shaped task keys.
   - e2e bearer non-leak oracle could not complete because local bind is blocked in this sandbox.
   - Conclusion: code shape is consistent with the red line, but end-to-end proof is **not obtained** in this run.

2. **只读边界**
   - `AgentOSSessionsProvider` mutation entries reviewed: create/delete/rename/model/archive/unarchive/read-state/delete chat/new chat/fork/side chat/send request all reject with `AgentOSReadOnlyError`.
   - Channel exposes exactly one command, `listTasks`; other commands throw.
   - I found no renderer path directly reaching runtime write endpoints in the slice code.
   - Conclusion: **PASS by code inspection and partial unit tests**.

3. **descriptor 校验**
   - Symlink, file type, mode, uid, protocol, loopback host, port, bearer, boot_id, pid shape, and pid liveness are checked.
   - Each request reloads descriptor after fetch and compares `pid/boot_id/port/bearer`.
   - Runtime bridge tests that would exercise HTTP request behavior could not run under sandbox loopback bind restrictions.
   - Conclusion: **mostly PASS by inspection**, with runtime proof blocked.

4. **生命周期**
   - `hasServedCatalog` gates quit termination on a catalog having actually been served, which matches the "only this interacted instance" intent.
   - SIGTERM -> 50ms poll -> SIGKILL is implemented.
   - Boot-id protection is incomplete after SIGTERM; see P1-1.
   - Conclusion: **FAIL / P1**.

5. **上游改动面**
   - Patch 010 touches these upstream files: `src/vs/code/electron-main/app.ts`, `src/vs/platform/native/electron-main/nativeHostMainService.ts`, `src/vs/platform/window/common/window.ts`, `src/vs/sessions/sessions.desktop.main.ts`, and `src/vs/workbench/electron-browser/desktop.contribution.ts`.
   - That is **5 upstream files**, not 4 as stated in the review request. It adds no upstream files through the patch; new files are copied from `overlay-src`.
   - Sessions entry seam is exactly `src/vs/sessions/sessions.desktop.main.ts`.
   - Conclusion: **P2 discrepancy** unless the intended count excluded the IDE desktop contribution.

6. **伪实现检查**
   - Overlay contains 13 files under `src/vs/agentos`.
   - I found no empty implementation, mock success, or constant-return capability claim in the core slice path.
   - `getSessionTypes()` returns `[]` and model picker returns no models intentionally for read-only/no-model Slice 1; this is covered by tests and is not a fake success claim.
   - Conclusion: **PASS**.

7. **测试有效性**
   - Provider tests exercise projection, duplicate/unknown-status fail-closed behavior, offline preservation, and typed rejection of mutation methods.
   - E2E oracle is designed to fail if runtime task labels do not render or bearer leaks, so it is meaningful when runnable.
   - In this sandbox the e2e did not reach those assertions because runtime could not bind a local port.
   - Conclusion: **test design is meaningful, but current rerun proof is absent**.

## Additional Notes

- `RuntimeTaskCatalogMainService.fetchFrom(url)` is a public diagnostic escape hatch that can fetch any path on the same runtime origin and is not exposed by the IPC channel. I am not grading it P1 because renderer code cannot call it through the registered channel, but it is unnecessary attack surface for Slice 1 and should be removed or constrained to the same allowlist before promotion.
- The descriptor `lstat()` then `readFile()` pattern has a standard TOCTOU gap. Given same-user local threat assumptions this may be acceptable for Slice 1, but a stronger implementation would open with no-follow semantics and validate via file descriptor `fstat` before reading.

## Verdict

**REVISE_TO_SPEC**

Reason: approval requires `P0=0 && P1=0`; current review has **P0=0, P1=1, P2=1**. Required green evidence was also not reproduced in this sandbox: `verify.mjs`, e2e, and full `npm run compile` did not pass, although the failures are largely attributable to local bind/IPC restrictions and `compile-client` did pass with 0 TypeScript errors.
