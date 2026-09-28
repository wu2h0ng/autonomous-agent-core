# Decision Packet — P2-7 / M1 ROUTE ADMISSION

> Status: `RECOMMEND_ONLY / NOT_AUTHORIZED / NO_IMPLEMENTATION / FOUNDER_GATE`
> Owner: CTO cast (actor: opencode)
> Date: 2026-09-15
> Claim ceiling: no Alpha / Autonomy(S,E,O,V,T) / release / parity claim.

## 1. What P2-7 is

`priority-execution-20260913/README.md` §2: *"Any M1 route admission (P2-7) ... `FOUNDER_GATE`."*
This is a **route cast** — a founder-reserved decision (AGENTS.md §7), not an agent task.
No code may start from this packet until the founder signs the route.

Evidence used (all read-only):
- `docs/agent-cli/GC-TERMINAL-AGENT-EVAL-0-2026-09-13.md` + `CP-AB-TERMINAL-AGENT-EVAL-0-2026-09-13.md`
  (the C#16 product eval set; the "measure before extending" precondition for MCP/checkpoint/hooks/subagents).
- `docs/agent-cli/TERMINAL-AGENT-NEXT-CAPABILITIES-GATING-2026-09-13.md` (§5 ordering).
- `docs/agent-cli/AGENT-CLI-DEVELOPMENT.md` §13 milestone table (M1 exit criteria).
- `docs/agent-cli/GAP-ANALYSIS-M2-VS-PARITY-2026-09-11.md` (open P0: command-execution isolation).
- `autonomous-agent-core/docs/CURRENT_STATE.yaml` `P-TERMINAL-CODING-AGENT-1` (M1 boundary, verbatim).

## 2. M1 definition (frozen vocabulary)

| Item | Scope | Exit |
|---|---|---|
| M1 内核完整 | 权限 4 模式 + 沙箱 3 档 + 危险命令识别 + TodoWrite + 会话持久化/resume + 上下文压缩 + 项目指令分层 | 内核集成测试全集通过；30min 长任务不炸上下文 |

## 3. Measured state (facts, 2026-09-15)

- Primary checkout is on `feature/terminal-coding-agent-m1` @ `77b1a597`, **NOT merged**; `local main == origin/main`.
  The branch has diverged from `origin/main` (ahead/behind both non-zero). It is **not** a fast-forward target.
- M1 boundary (per CURRENT_STATE) **excludes** checkpoint/rewind and OS-level filesystem/network isolation;
  shell is an exact allowlist + minimal secret-free environment, **not** OS isolation.
- The C#16 product eval set (P2-7 in the eval packet = its "condition 7" deterministic fail-closed gateway)
  is `SLICE_1_INSTRUMENT_IMPLEMENTED / EXACT_DIFF_REVIEW_REVISE_FIXED`; the eval harness branch carries an
  E3 live run and a working-set discriminator that returned **INVALID (retest required)**.
- **Open benchmark P0:** "命令执行隔离或显式 trusted-workspace 边界" — the OS sandbox is still not built;
  only the explicit trusted-workspace boundary statement exists.

## 4. The decision (what the founder must cast)

Admit the M1 route means choosing which of the following is authorized **next**. This packet does not pick.

- **A. Close the remaining M1 kernel items** on `feature/terminal-coding-agent-m1` (whatever of
  TodoWrite / persistence-resume / context compression / project-instruction layering is still open),
  then merge M1 into main via a normal reviewed PR (no rebase; branch is diverged).
- **B. Decide the P0 command-execution isolation:** build one of the 3 sandbox tiers (OS isolation)
  or formally accept the trusted-workspace boundary as the M1-level answer and record it as residual debt.
- **C. Gate the next capability from eval measurement** (§5 ordering): Hooks / Subagents / Checkpoint-Rewind / MCP
  — only if the C#16 eval shows a **可归因瓶颈**. The working-set discriminator is currently INVALID (retest).
- **D. Do nothing on M1**; keep `PARK` and wait for the Sep-19 cross-provider window (the two SRL increments
  + N6/N7 also await it).

## 5. CTO recommendation

1. **B before A is wrong; A before C is right.** Do not admit a new capability (C) before the eval
   instrument is retested to a valid (non-INVALID) L1 baseline — otherwise "是否该做" has no measurement.
2. **A** is the smallest defensible step: it finishes the already-scoped M1 kernel and makes the branch
   mergeable through review. It touches no C7/permission semantics and no new contract surface.
3. **B** must be decided explicitly: an unclosed P0 must not be silently inherited. Either authorize one
   sandbox tier or sign the trusted-workspace boundary as the M1 residual (it is already documented, so
   signing it is cheap and honest).
4. **C** stays gated on a valid eval retest.

## 6. Authority boundary

- This packet authorizes nothing. M1 route admission is a founder route cast (AGENTS.md §7);
  implementation additionally needs GC → CP+AB → CTO gate → test-first → independent exact-diff review.
- No push/merge of `main` without explicit authorization; the branch is diverged, so the path is PR + review.

## 7. Founder cast: A (finish M1 kernel) — completion breakdown

> Cast received 2026-09-15: **A**. Base the work on **`origin/main`**, not the stale
> `feature/terminal-coding-agent-m1` @ 77b1a597 (575 behind; much of M1 already landed on main).

Measured M1 item status against `origin/main` (read-only):

| M1 item | State | Evidence |
|---|---|---|
| 权限 4 模式 | DONE | `permission_gate.py`, `tests/product/test_permission_mode_matrix.py` (@origin/main) |
| 会话持久化 / restart resume | DONE | durable projection; Wave-1 Tier-1 verified |
| TodoWrite | DONE | `tests/product/test_session_todo_write.py` (@origin/main) |
| 沙箱 3 档 | **OPEN** | no OS fs/net isolation; benchmark P0 unclosed → this is option B |
| 危险命令识别 | **OPEN** | no classification library; out-of-allowlist fail-closed covers worst case |
| 上下文压缩（手动+自动） | **OPEN** | none; must be recorded as an event (stricter than peer) |
| 项目指令分层（AGENTS.md/CLAUDE.md） | **OPEN** | single-layer only (`agent_context.py`, sha256, 12000 truncation, symlink fail-closed) |
| allow/deny 规则持久化（"don't ask again"） | **OPEN** | exact allowlist only; no glob rules, no durable rule records |

Proposed slices (each: GC → CP+AB → CTO gate → test-first → independent exact-diff review):

- **S1 危险命令识别库** — typed deny-classification, no OS dependency; smallest, no permission-semantics change. **Recommended first.**
- **S2 allow/deny 持久化** — durable rule records reusing the E2 three-record chain.
- **S3 项目指令分层** — layered AGENTS.md with change digest (GC-CONTEXT-ENGINEERING P1).
- **S4 上下文压缩** — deterministic compaction recorded as an event (GC-CONTEXT-ENGINEERING P1).
- **S5 沙箱 3 档** — blocked on the founder decision in §4 option B (OS route vs trusted-workspace boundary).

No code written; S1–S4 CTO-gated, S5 founder-gated.
