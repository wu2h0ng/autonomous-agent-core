# M2 rev 5 — CTO Gate 4 审查包（审查建议，非裁决）

> Date: 2026-09-11
> Reviewer: Kimi Work session（审查支持；CTO gate 4 裁决权在创始人）
> Scope: `GC-TERMINAL-CODING-AGENT-M2-2026-09-11.md` (rev 5) +
> `CP-TERMINAL-CODING-AGENT-M2-2026-09-11.md` (rev 5) +
> `T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md` §13 (rev 5)
> Question: gate 3 冻结的三项 P1 修正（E1/E2/E3）在 rev 5 内是否自洽；
> base sequencing 是否可执行。

## 1. 事实核验（全部通过）

| 核验项 | 结果 |
|---|---|
| local main HEAD == `b05d29b8`（exact） | ✓ `git rev-parse main` 实测一致，无漂移 |
| 真值表行号（main 树实读） | ✓ 5/5 精确：`SessionProjector` @ session_projection.py:195；`SurfaceRuntime` @ surface_runtime.py:118；`complete_streaming` @ provider.py:122/167/332；`AgentLoop` 调 `complete()` @ agent_loop.py:1148；fake zero `Decimal("0")` @ provider.py:461（另 225/593 两处同型） |
| CURRENT_STATE 修正 from-strings | ✓ 与 main 版 line 492（status）、line 494（boundary 首句）逐字匹配，修正可干净落地 |
| `D1-RECONCILE-b05d29b8-2026-09-11.md` | ✓ 存在于 workspace 根（CP 引用位置一致；注意它在仓外，见 §3-N2） |
| 三文档 E1/E2/E3 冻结文本互洽 | ✓ GC §E1/E2/E3、CP §frozen contracts、AB §13.2/§13.5 逐条对齐，无相互矛盾 |
| Base sequencing 内部一致 | ✓ GC header、CP header、CP §Companion、AB §13.3 四处描述同一顺序：gate 4 → `docs(state)` 提交 → 其 SHA 为 final base → 干净 worktree；非目标（push 需单独 gate）一致 |

结论：gate 3 三项拒绝点均已实质性闭合——E1 补齐了并发/丢失协议（独立端点+独立游标、订阅先于回合、帧绑定、有界缓冲+显式 gap、完成排序、崩溃诚实）；E2 改为 `POLICY_VERDICT_RECORDED(basis=permission_mode, mode_event_id)` 且禁止伪造 `ApprovalDecision`；E3 自矛盾已消除（`Decimal|None` + `cost_status` + 两条不变量 + 禁止零值 + 历史零值不重解释）。

## 2. 发现（按严重度）

### P2-1 — E1 重连时 `stream_id` 同一性未冻结（建议接受前以一句话补冻结）

GC 生命周期第 2 条：客户端只渲染匹配"当前 stream+turn"的帧；第 4 条：断线后"以其最后的帧游标重连"。但全文未说明重连后 `stream_id` 是否保持。若每次订阅铸造新 `stream_id`，则"从游标恢复"与"帧绑定 stream_id"冲突（重连后的帧会被当作 stale 丢弃）。这正落在 gate 3 冻结的区域内，属同类歧义的残余。

建议补冻结一句（无设计变更）：*session-stream 的 `stream_id` 在其生命周期内跨重连稳定；瞬态游标以 stream 为作用域；重新订阅铸造新 `stream_id` 并使旧流显式终止（`stream_terminated`）。*

### P2-2 — E2 READ_ONLY auto-pass 的记录语义未指明

冻结的记录语义覆盖"auto-allowed action"（= 矩阵中的 **policy auto-allow**，tier-2 @ ACCEPT_IN_WORKSPACE）。但矩阵中 READ_ONLY 在三模式下是 **auto-pass**——它是否也产生 `POLICY_VERDICT_RECORDED`？若产生，`basis=permission_mode` 语义错误（READ_ONLY 放行是 tier 默认行为，与模式无关）；若不产生，则需明示它走既有 policy 路径、无需 mode 溯源记录。建议补一句区分：*READ_ONLY auto-pass 是 tier 默认放行，不产生 mode 溯源记录；"三件套"记录链仅适用于 policy auto-allow。*

### P3 — "finalizing…" 无界等待

`stream_end` 无 durable commit 时渲染 "finalizing…"。守护进程崩溃的情形已被第 6 条覆盖（重启后显示 terminated），但"活着但挂起"的 daemon 会让该状态无限持续。可在 TUI 侧加停滞提示（不改变协议），不阻塞 gate。

### 编辑性 — 冻结矩阵表内混入中文单元格

GC line 130/132、CP line 75、AB §13.2 矩阵含"（记录 1–3…）""同左"。按 ADR-0060 外部术语优先政策，建议统一为英文，纯编辑性。

## 3. 出处与程序备注（不构成阻塞）

- **N1：** rev 5 三件套当前**未提交**（GC/CP untracked，AB modified，位于 dirty 的 feature checkout）。gate 4 若接受，建议先以独立 `docs(product)` 提交固定被接受规格的 SHA，再执行 state-correction sequencing——否则"被接受的 rev 5"没有可引用的事务哈希。
- **N2：** D1-RECONCILE 在 workspace 根、仓树之外；对账证据不入仓则 M2 包的外部引用不可随仓追溯。可考虑移入 `docs/reviews/` 或在仓内留存指针。
- **N3：** 修正落地后 local main 将领先 origin 107 提交；GC 非目标已正确注明 push 为单独创始人 gate。

## 4. 建议

**APPROVE_WITH_P2**（建议，待创始人裁决）：rev 5 事实与冻结合同自洽、base sequencing 可执行，可以进入 sequencing；P2-1/P2-2 以 addendum 一句话补冻结（不产生 rev 6、不改设计），编辑性与 N1–N3 随 sequencing 一并处理。

若创始人认为 P2-1/P2-2 触及"冻结区域不得再留歧义"的 gate-3 先例，则改为 `REVISE_TO_SPEC`（单点修订 rev 6）。两条路径的后续动作相同：state-correction 提交 → final base SHA → 干净 worktree → test-first 实现。

**本审查不代行 CTO gate；裁决与 sequencing 启动均需创始人明示。**

---

## 裁决结果（2026-09-11 01:48，创始人）

创始人裁决 **`REVISE_TO_SPEC`**，指出 rev 5 仍留有 5 处会迫使实现者临场拍板的协议空白（E1 `turn_id` 来源 / 游标未绑定 daemon generation / gap 帧自身可被淘汰 / E2 tier-3 与 out-of-allowlist 规则冲突 / E3 缺历史兼容且零值禁令过宽），外加 AB §13.3 重复 D1 残句。本审查包的 APPROVE_WITH_P2 建议被更严格的裁决取代——创始人将 P2-1 同类歧义升级为阻断项，方向正确。

rev 6 已按五点修法完成（GC/CP 全量同步，AB §13 同步），状态 `RESUBMISSION_PENDING_CTO_GATE_5`。
