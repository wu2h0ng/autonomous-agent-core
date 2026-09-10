# Agent OS Dual Workbench Slice 1 Re-review

| Field | Value |
|---|---|
| reviewer | codex-primary |
| builder | kimi-builder |
| reviewed commit | `d3158313a0bd3520f593867da67ba45547744434` |
| review time | 2026-09-10T21:47:01+08:00 |
| verdict | **REVISE_TO_SPEC** |

## Summary

I reviewed the repair commit directly, not just the builder note. The P2 file-count correction is complete, and the unnecessary `RuntimeTaskCatalogMainService.fetchFrom()` escape hatch has been removed. However, I cannot close P1-1 because the new pid identity proof is still not fail-closed enough for the stated lifecycle requirement.

Final judgment: **REVISE_TO_SPEC**. Approval requires `P0=0 && P1=0`; this round has **P0=0, P1=1, P2=0**.

## Diff Review

Reviewed command surface:

- `git show --stat --oneline --decorate --no-renames d3158313`
- `git show --name-status --no-renames --format=fuller d3158313`
- `git show --no-ext-diff --unified=80 --no-renames d3158313 -- ...`
- `rg -n "fetchFrom|processStartFingerprint|beginInteractiveRuntimeTermination|5 个上游文件|4 个上游文件" ...`

Observed repair scope:

- `interactiveRuntimeLifecycle.ts`: adds `processStartFingerprint(pid)` using `ps -o lstart= -p <pid>`, captures the value before `SIGTERM`, checks it during polling, and rechecks fingerprint plus descriptor `pid/boot_id` before `SIGKILL`.
- `runtimeTaskCatalogMainService.ts`: removes `fetchFrom(url)`.
- `runtime-task-bridge.test.mjs`: changes the read-only bridge test to assert `fetchFrom` is absent; adds pid reuse and descriptor-change lifecycle regression tests.
- `verification.md`: corrects upstream Code-OSS patch count to 5 files.

## Required Verification Reruns

1. `cd apps/code-oss && node scripts/verify.mjs`
   - Result: **FAIL**, 34/44 pass, 10/44 fail.
   - 7 failures are the same sandbox loopback blocker: `listen EPERM: operation not permitted 127.0.0.1`.
   - 3 lifecycle tests returned `pending=false` where the tests expected true because this sandbox blocks `spawnSync ps` with `EPERM`, so `processStartFingerprint()` returns null and the lifecycle fails closed before signalling.

2. `cd apps/code-oss && node tests/runtime-task-bridge.test.mjs`
   - Result: **FAIL**, 3/13 pass, 10/13 fail.
   - Same split: 7 local HTTP server `listen EPERM` failures; 3 lifecycle tests fail because the `ps` fingerprint command cannot run under this sandbox.

3. Minimal Node loopback sanity check:
   - Command: `node -e "createServer(...).listen(0, '127.0.0.1', ...)"`
   - Result: **FAIL**, `EPERM listen EPERM: operation not permitted 127.0.0.1`.
   - Conclusion: loopback verification remains environment-blocked.

4. Minimal `ps` fingerprint sanity check:
   - Command: `node -e "execFileSync('ps', ['-o','lstart=','-p', String(process.pid)])"`
   - Result: **FAIL**, `EPERM spawnSync ps EPERM`.
   - Conclusion: lifecycle tests that depend on the real fingerprint command are also environment-blocked here. The implementation does fail closed when identity cannot be inspected, which is good, but this does not prove the fingerprint is sufficient.

## Findings

### P1-1: Pid identity fingerprint is not strong enough to be fail-closed

File: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/interactiveRuntimeLifecycle.ts`

`processStartFingerprint(pid)` uses only `ps -o lstart=`. On this target shape, `lstart` is a human-readable start time with second-level precision. It is not a collision-resistant process identity. A pid can be reused by another process whose reported `lstart` is the same second as the original runtime. In that case:

1. the original runtime is signalled with `SIGTERM`;
2. the pid is reused within the same displayed start-time second;
3. `fingerprintOf(pid)` still returns the same `lstart` string;
4. the stale descriptor file still contains the old `pid/boot_id`;
5. the pre-`SIGKILL` descriptor recheck passes because it reads the same stale file;
6. `SIGKILL` can still hit the unrelated process.

The code comment says "Two different processes never share a start time"; with `ps -o lstart=` this is not a defensible identity guarantee. The fix narrows the bug substantially, and it fails closed when `ps` is unavailable, but it does not satisfy the original requirement of pid-reuse protection on destructive escalation.

Required fix: use a process identity that cannot collide at the relevant granularity, or avoid pid-based destructive escalation when the process cannot be proven as the exact child/runtime instance. Acceptable directions include a real child-process handle where possible, a platform-specific kernel start-time/tick identity with adequate precision, or recording/verifying a daemon-held termination nonce/handshake before escalation. If using a fingerprint, the tests need to model same-fingerprint pid reuse, not only fingerprint flip.

## Closed Items

### `fetchFrom` removal

`RuntimeTaskCatalogMainService.fetchFrom()` is absent from the service implementation. The bridge still exposes `listTasks()` and the guarded internal `request('GET', '/v1/tasks')` path; IPC still exposes exactly `listTasks`. This resolves the additional attack-surface note from round 1.

### File count correction

`verification.md` section 8 now states patch 010 touches **5 upstream files**:

- `src/vs/code/electron-main/app.ts`
- `src/vs/platform/native/electron-main/nativeHostMainService.ts`
- `src/vs/platform/window/common/window.ts`
- `src/vs/workbench/electron-browser/desktop.contribution.ts`
- `src/vs/sessions/sessions.desktop.main.ts`

I also inspected `apps/code-oss/patches/010-agent-os-sessions-window.patch`; the count is correct, and `sessions.desktop.main.ts` remains the single Sessions tree entry seam.

## Verdict

**REVISE_TO_SPEC**

Reason: **P1=1** remains. There is no P0 in this round, and the P2 file-count issue is closed, but the approval bar is not met.
