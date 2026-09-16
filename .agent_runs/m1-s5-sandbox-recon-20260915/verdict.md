# S5 SANDBOX — RECON VERDICT (read-only)

> Status: `ALREADY_RESOLVED_ON_ORIGIN_MAIN / NO_NEW_CODE_RECOMMENDED`
> Cast: P2-7 M1 route A (option B). Base `origin/main` @ `18d7b9b0`.
> Claim ceiling: no parity / autonomy / release claim.

## Question

M1 lists "沙箱 3 档"; the benchmark P0 (2026-07-26) is *"命令执行隔离 **或** 显式
trusted-workspace 边界"*. Does option B need new work on origin/main?

## Evidence (verified at origin/main 18d7b9b0)

- Isolation tiers are real and wired: `EXECUTION_ISOLATION_TRUSTED_WORKSPACE` (default)
  and `EXECUTION_ISOLATION_SANDBOXED`, passed into `DeveloperWorkspaceAdapter` from
  `apps/api_server/app.py` (two sites) and selectable by constructor/env.
- The sandboxed tier is a **real macOS Seatbelt** profile
  (`_workspace_seatbelt_profile`): `(deny default)`, `(deny network*)`,
  `(deny process-exec* .../sudo)`, broad read minus `/Users|/Volumes|/Network|/private/{tmp,var/folders}`,
  write confined to the workspace + redirected HOME/TMPDIR; the dispatched profile is
  bound by a stable digest (`_profile_digest`).
- **Fail-closed**: sandboxed without `sandbox-exec` or off-macOS raises rather than
  silently downgrading (`tests/product/test_os_sandbox.py`).
- `tests/product/test_os_sandbox.py` (14 tests) covers: default = trusted-workspace;
  opt-in via constructor/env; invalid rejected; sandboxed-without-OS and off-macOS fail
  closed; trusted still executes; sandboxed confines writes + network; profile digest
  stable; seatbelt path guard; read-roots exclude `/` and home; shell report records
  isolation evidence; `run_tests` sandboxed blocks a filesystem escape.

## Verdict

The benchmark P0 is **already satisfied** on origin/main by *both* a real OS-level
execution-isolation tier (opt-in, fail-closed) and the explicitly documented
trusted-workspace boundary. The M1 boundary in `CURRENT_STATE` explicitly excluded OS
isolation; the implementation now **exceeds** that boundary.

- "沙箱 3 档" (three tiers) is **not required by the P0**; two tiers + the explicit
  boundary meet it. No third tier should be invented to match a number.
- **Recommendation: close S5 with no new code**, and record the trusted-workspace
  boundary as the documented **default** (already the default) — i.e., sign option B as
  satisfied, not as debt.

## Residual / honesty

- The sandboxed tier is opt-in, not default; the default remains trusted-workspace. If
  the product wants isolation-by-default that is a separate founder risk decision, not
  an M1 completion gap.
- This is a read-only recon; no code changed.
