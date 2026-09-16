# AB — P3a 多 Agent / 任务树（架构简报，2026-09-16）

- **状态**：`DESIGN_ONLY / IMPLEMENTED_IN_REVIEW / AWAITING_INDEPENDENT_REVIEW_AND_CTO_GATE`（P3a-1 已实现于 PR，见 §8）
- **上游**：`GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md`（P3a 范围已由 founder 批准 2026-09-16）。
- **本文件解决上游 OPEN#1 / OPEN#3，并给出可直接开工的实现边界与评审材料。**

## 1. 调研结论（把 OPEN 变成已核实事实）

### OPEN#1 关系数据是否存在 → **已解决：存在，无需新持久化**
- 既有层级：**mandate → task → session**。
  - mandate 列表：`GET /v1/mandates` → `{mandates: [MandateWorkspaceRecord…]}`（`apps/api_server/server.py:395-399`，`app.py:1217-1222`）。
  - mandate→task：`GET /v1/mandates/{id}/task-links`（`server.py:400-405`，`app.py:1236-1243`）。
  - 会话：`GET /v1/surface/sessions?limit&cursor` → `SurfaceSessionSummary[]`，**含 `task_id`**（`packages/contracts/.../surface.py:173-186`；客户端已实现 `SurfaceClient.listSessions`，`apps/cli-ts/src/client.ts:220-225`）。
  - mandate 派生树：`StandingMission.parent_mandate_digest`（`mandate.py:112-127`）。
- **不存在**：session→parent-session（Agent 派生 Agent）。→ 本 P3a **不含** agent-spawns-agent；那是后续 GC。
- 会话分页上限：kernel 校验 `1 <= limit <= 100` + cursor（`surface_runtime.py:200-204`）。

### OPEN#3 协议版本策略 → **已解决：既有先例 = 附加字段升 minor，保留旧解码**
- 先例（`docs/product/CP-TERMINAL-CODING-AGENT-M2-2026-09-11.md:140,146-150`）："Version bumps: usage contract `2.0`, surface protocol `1.1`（additive）"，且"v1 payloads without `cost_status` decode as `UNKNOWN`/`None`；readers accept v1 payloads for replay indefinitely"。
- 推论：**additional-only 字段 → `1.2`，并保留 `1.1` 解码**；破坏性变更才大版本。
- **且 P3a-1 不需要任何契约改动** → 协议版本问题在本阶段不触发（见 §2）。

## 2. 推荐实现（P3a-1：零协议改动、只读拼接）

**入口（全部已存在、已鉴权、只读）**
1. `GET /v1/mandates` → mandate 层（含 `standing_mission.parent_mandate_digest` 用于分层）。
2. `GET /v1/mandates/{id}/task-links` → task 层。
3. `GET /v1/surface/sessions` → session 层，按 `task_id` 归并。

**客户端**（纯拼接，不改内核/协议）
- `src/opentui/agents.ts`（纯函数，可 Node 测试）：`buildAgentTree(mandates, links, sessions)` → 树 + 降级（字段缺失/重复/孤儿会话 → 平铺）。
- 视图：P2 右侧栏新增 `agents` 面板（树），`Tab` 选中、独立滚动（复用 P2 机制）。
- 会话控制器：**活动会话才订阅 stream（N=1 条流）**；其余会话以只读轮询（listing + 单会话 snapshot）呈现状态；切换 = 切活动会话并重订阅。
- 审批：仍是活动会话内的 `y/n` 人工确认；树面板只显示"该会话存在 pending 审批"。

**为什么这样最小**：避免 N 条并发 stream 的资源上限问题（把未决问题①③降为"活动流=1，其余轮询"），避免契约/版本改动，避免任何写路径。

**P3a-2（可选，暂不做）**：若确需在树内直接显示 `pending_approval_count`/`label` 且不想轮询，再走附加字段 `1.2`（按 §1 先例）。

## 3. 契约/入口/失败路径/集成/追溯（Product Track 要求逐项）

| 项 | 内容 |
|---|---|
| 公共入口 | 终端 `agents` 面板（`Tab` 选中）；数据来自 3 个既有只读 HTTP 路由 |
| typed contract | 复用 `MandateWorkspaceRecord` / task-link record / `SurfaceSessionSummary`（**不新增**） |
| 失败路径 | 路由 4xx/5xx、鉴权失败 → 面板显示错误、不清空既有树；会话 `closed`/`STREAM_GONE`/`TURN_IN_PROGRESS` → 该会话行标注状态（沿用 P2 的降级不崩） |
| 集成点 | `apps/cli-ts/src/opentui/app.tsx`（面板）+ `agents.ts`（树）；`SurfaceClient` 现有方法 |
| Trace/Evidence | 终端只读展示；不产生新证据类型；不改 eval/trace 语义 |
| 权限 | 无新权限；切换会话不改变授权；**无跨会话审批** |
| Rollback | `--no-agents` 关闭面板即回 P2；无数据迁移 |
| 声明分级 | `specified`（本文件）；`implemented/tested/integrated/verified/released = NO` |

## 4. 边界核对

- **Agent Core 领域中立**：仅终端视图 + 纯函数，无领域语义。
- **C7/permit/approval**：零改动；`TURN_IN_PROGRESS`（rev 9，per-session）保持不变。
- **Stage 2c/2d 一致**：终端不新增治理入口；创建/派生仍 API-only。
- **最小投影纪律**：`GET /v1/mandates` 返回含 `statement` 的 mandate 记录，但 **TUI 只渲染标识/状态/计数**，不渲染 mission 文本（G5 检查项）；不显示凭证。
- **`MandateWorkspaceRecord` 不授权执行**：树/派生不产生执行权（`mandate.py:135-142`）。

## 5. 测试与证据计划（gates 对应）

- 单元（Node，bypass-detecting）：`buildAgentTree` 对 空/单层/孤儿会话/重复 task/缺失 `parent_mandate_digest`/超 100 分页 的确定性输出；常量或"仅返回首项"实现必须失败。
- 回归：`tests/product/test_surface_stream_runtime.py`（G2：`TURN_IN_PROGRESS` 逐字节不变）。
- 契约：G5 投影快照测试（树数据不含 statement/凭证）。
- pty 证据（复用 P2 脚本模式）：`agents` 面板渲染、`Tab` 选中、切换会话后 composer 仍可输入、审批仍在活动会话内可见可 `y/n`、`--no-agents` 无面板。
- 安全评审：§6（GC 包）5 项 + 本文件"跨会话审批不可达"证明。

## 6. 需 Founder/CTO 决策（开工前）

1. **批准 P3a-1 实现范围**（零协议改动、活动流=1、其余轮询、树只读）。
2. **确认不含 agent-spawns-agent**（session→parent-session 不存在；后续 GC）。
3. **N 上限**：活动流固定 1 是否接受；会话列表分页 ≤100/cursor 是否接受。
4. **是否允许终端渲染 mandate `statement`**：本简报判"否"（只显示标识），若你要显示需改 G5。
5. 是否同意"P3a-2（附加字段 `1.2`）仅在有明确需求时另立 GC"。

## 7. 当前声明

`specified: GC 包 + 本 AB` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。
未执行架构评审通过与 CTO gate 前，**不得**编写 P3a 运行时代码，也不得声称多 Agent 能力。

## 8. P3a-1 实现结果（2026-09-16，IMPLEMENTED_IN_REVIEW / PENDING_INDEPENDENT_REVIEW）

- **改动**（全部在终端客户端，**零协议/零内核改动**）：
  - `src/opentui/agents.ts`（纯）：`buildAgentTree` + `agentRowLine`，确定性排序/分组、孤儿任务归入 `(unlinked task)`、上限截断并置 `truncated`。
  - `src/opentui/agent-tree-source.ts`：只读拼接 `GET /v1/mandates` + `GET /v1/mandates/{id}/task-links` + `SurfaceClient.listSessions`；宽松解析（只取所需字段）、失败降级为 note、mandate 扇出上限 20。
  - `SurfaceClient.getReadOnly(path)`：仅 GET、无 body、沿用同一 bearer/错误映射；**不做任何治理操作**。
  - `app.tsx`：侧栏新增 `agents` 面板（`Tab` 选中、独立滚动，复用 P2）；`--no-agents` 关闭（关闭后不拉取树）。面板只渲染标识/状态，**不渲染 mission/statement 文本或凭证**。
- **实测**（`scripts/pty_fullscreen_p3a.py`，120×40，hermetic daemon；连续两次一致）：
  `AGENTS_PANEL_PRESENT: True`（boot 首帧含 `─agents` 面板标题）、`TREE_ROWS_RENDERED: True`、`TYPABLE_WITH_AGENTS_PANEL: True`（Tab 后 composer 仍可输入）、`HAS_AGENTS_TITLE: False`（`--no-agents` 无该面板）。
  **断言口径（R2 修正）**：渲染器逐格 diff，Tab 后只重发变化的单元格 → 面板标题会被拆到不同帧，早期"`agents · selected` 字符串"断言**不可复现**。故 pty 只断言**确定性可见事实**（首帧存在、树内容、可输入、`--no-agents` 移除）；**面板选中**不靠截图，由渲染器无关的单测（`nextPanel`/`visiblePanels`，`test/opentui-panels.test.ts`）覆盖。
- **测试**：`test/opentui-agents.test.ts` 4 pass（bypass-detecting：忽略 links 的扁平实现、丢孤儿会话、不截断都会失败）；`test/opentui-panels.test.ts` 更新为 4 面板 + `--no-agents`；`test/client.test.ts` 新增 `getReadOnly` 仅 GET/无 body 断言；cli-ts 全量 **161 pass**。
- **诚实边界**：
  - hermetic daemon 无 mandate，实测走的是"`(unlinked task)` 分组 + 真实 task/session"路径；**mandate→task→session 三层**路径仅由单元测试覆盖，**未做端到端 live**（需要真实 mandate bootstrap）。
  - 活动流仍为 1（仅活动会话订阅）；树内不显示 pending 审批计数（需 P3a-2 附加字段 `1.2`，未做）。
  - 树面板刷新 5s 轮询；未做增量/事件驱动。
- **证据口径（R1/R2 复审条件）**：pty 只断言确定性可观察事实 → 本机连续两次 `AGENTS_PANEL_PRESENT/TREE_ROWS_RENDERED/TYPABLE_WITH_AGENTS_PANEL = True`、`HAS_AGENTS_TITLE = False`（`--no-agents`）；**面板选中不做帧断言**，由 `nextPanel/visiblePanels` 单测覆盖（含 4 面板含 `agents` 的循环用例）。另：mandate 子集先按 id 排序再截断（确定性）；树轮询由**面板可见性**门控（窄终端不再空拉）。
- **声明分级**：`specified+implemented+tested`（目标测试）；`integrated: 终端内已接入`；`verified: 待独立复审（R1=APPROVE_WITH_CONDITIONS，条件已修，待 R2 确认）`；`released: NO`。

## 9. P3a-1 收尾：会话切换（2026-09-16，IMPLEMENTED_IN_REVIEW）

- **交互**：`agents` 面板被选中时，`ctrl+↑/↓`（或 `ctrl+p/n`）在树内移动高亮；`enter` 在**session 行**上切换活动会话。
  - 普通字母与方向键仍归 composer（输入框始终持有焦点，P2 焦点策略不变）；因此只有"面板被选中 + ctrl 组合键/Enter"会改变行为，并在 footer 提示。
- **实现路径（零协议/零内核改动）**：直接复用**既有** `/resume <session-id>` 命令（`controller.ts:788`），不在视图层重实现会话绑定。
- **安全性质（关键）**：`/resume` 在 `busy`（`controller.ts:986-1044`，覆盖整个回合 **包括审批挂起**）时拒绝并提示 `turn in progress; cannot resume now` → 切换**不可能**遗弃在途回合，**不可能**把审批面移出视野。非 session 行（mandate/task/组）**不可**触发切换（`resumableSessionId`）。
- **有界**：树刷新（5s）后游标自动 clamp（`clampCursor`），行数变化不会越界。
- **实测**（`scripts/pty_fullscreen_p3a.py`，连续两次一致）：`AGENTS_PANEL_PRESENT/TREE_ROWS_RENDERED/RESUMED/TYPABLE_WITH_AGENTS_PANEL = True`、`HAS_AGENTS_TITLE = False`（`--no-agents`）。其中 `RESUMED` 为在 session 行 `enter` 后 transcript 出现 `resumed session …`。
- **测试**：`test/opentui-agents.test.ts` 增 `clampCursor/moveCursor/resumableSessionId`（含"task/mandate 行不可切换"）；`test/controller.test.ts` 增 `/resume` 在 `busy` 时的拒绝用例（并断言**未**发生会话切换）；cli-ts 全量 **163 pass**。
- **诚实边界**：hermetic daemon 只有 1 个会话，实测为"切换到同一会话"（走完整 `/resume` 路径并显示 resumed）；**多会话互切**未做端到端（需真实多会话/多 mandate 场景）。树内不显示会话内容预览（只标识/状态）。`RESUMED` 断言为规范化子串匹配（样式可能拆分单词）。
