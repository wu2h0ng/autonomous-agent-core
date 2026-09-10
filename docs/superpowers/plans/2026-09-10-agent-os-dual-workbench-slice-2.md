# Agent OS Dual Workbench Slice 2 Implementation Plan(DRAFT,待 CTO 门禁)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sessions 窗口中的只读任务投影从"列表"深化到"任务详情 + trajectory 只读转录":点击一个投影任务,在 Sessions 原生会话视图中看到该任务的白名单详情(statement/status/run/时间戳)与 trajectory 事件转录(单调递增校验 + gap 显式标注),全程保持只读、字段最小化。

**Architecture:** 沿用 Slice 1 已批准的拓扑——主进程独占 Runtime 桥(bearer 与富字段不出主进程)、renderer 只消费封闭类型投影、overlay `src/vs/agentos/` 承载全部新代码、patch 010 的上游改动面不扩大。数据源复用现有只读端点:详情 = `GET /v1/tasks/{task_id}`(task_json,白名单最小化),转录 = `GET /v1/tasks/{id}/runs/{run_id}/trajectory`(run_id 来自 task_json.run)。**Python/contracts 侧默认零变更。**

**Tech Stack:** 同 Slice 1(Code-OSS/Electron, TypeScript, Node test runner, Python Runtime HTTP API)。

**Spec:** `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`(§12 纵向切片验收②⑤;§557 生命周期;§7 权限边界)

**前置状态:** Slice 1 `APPROVE_SLICE_1`(round-3,P0=0/P1=0),head `e13684a2` on `codex/ide-ui`。Slice 2 从该 head 继续,**不 push、不 merge**。

**门禁状态:** 本计划为 DRAFT。按 AGENTS.md §13 中高危产品流程,开工前需 Goal Card + Context Pack + CTO gate;Slice 1 的 Goal Card/Context Pack 可增量续用。

## Global Constraints(继承 Slice 1,逐条仍然有效)

- 上游基线钉死在 `1.136.2 @ 88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`;patch 集合只允许在 patch 010 上小步演进,**不得新增上游文件**。
- bearer/凭证不出主进程;IPC 表面在 `listTasks` 之外新增命令必须逐个 typed、逐个测试、逐个评审。
- Sessions 侧保持只读:详情与转录不许出现任何写控件(发送/编辑/删除/审批)。
- 运行时新增端点只允许只读 GET,纳入 contracts 的封闭解码(fail-closed,多余字段即拒)。
- Runtime 生命周期不变:窗口 reload 不停 Runtime,application quit 有界终止(三层身份证据,c4d8023f 已批准,不得回归)。
- 无审批执行、自动化、多客户端写、后台服务、Rust 迁移、release、autonomy 声称。
- 每个 Task 先写失败测试再实现;`builder_id != reviewed_by`,收口仍需独立评审。

## 范围边界(In / Out)(评审修订版)

**In:**
1. 任务详情只读消费:**复用现有 `GET /v1/tasks/{task_id}`(task_json)**,桥侧白名单最小化解码(goal.statement/status/run 含 run_id/时间戳;`approval`/`proposed_action`/`provider_usage`/原始事件载荷不得穿过桥)。
2. 转录只读消费:**复用现有 `GET /v1/tasks/{id}/runs/{run_id}/trajectory`**;run_id 来自 task_json.run。事件类型→转录项白名单映射,未知类型 fail-closed;sequence 单调递增校验 + `source_stream_last_sequence` 完整性校验;**seq gap(run 过滤的常态)显式标注**。
3. Sessions 窗口交互:选中投影任务 → 打开只读详情/转录视图;刷新 reconcile 保持 facade 身份稳定。
4. e2e 扩展(失败先行):详情渲染、事件顺序与 gap 标注、bearer 与富字段不泄漏、无写控件、reload 存活、quit 有界终止不回归。

**Out(显式排除):** 事件流实时推送(SSE/WS)、写路径与审批卡(spec §12 ③④属后续切片)、IDE 窗口侧任务联动、多 workspace、后台保活、**Python/contracts 侧变更**(默认零变更;若确需,升级为独立 Task 并跑 tests/product 全量)。

## Tasks(草稿,CTO gate 后细化到步骤级)

### Task 1: 详情/trajectory 只读合同(封闭解码器,失败先行)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.ts`
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.test.ts`
- Create: `apps/code-oss/tests/runtime-task-detail-contract.test.mjs`

- [ ] Step 1: 失败测试——详情解码器:**白名单投影 + 输出封闭校验**(task_json 输入恒含 `approval`/`proposed_action`/`provider_usage` 等键,不拒输入,但投影输出必须只含白名单字段且这些键缺席;多余未知顶层字段按封闭约定拒绝);trajectory 解码器:乱序/非单调 sequence 拒绝、step sequence 超出 `source_stream_last_sequence` 或末端 step 与完整性基准不一致拒绝(精确语义:全部 step sequence 严格递增且 ≤ source_stream_last_sequence)、未知事件类型拒绝、gap 被保留为标注而非拒绝
- [ ] Step 2: 实现两个封闭 decoder 与类型
- [ ] Step 3: 对真实 Runtime 响应样本跑合同测试(捕获真实 task_json/trajectory 响应作为 fixture,不含任何 secret)
- [ ] Step 4: 全量测试 + 编译 0 errors

### Task 2: 主进程桥扩展(详情 + trajectory 拉取)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts`
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogChannel.ts`
- Modify: `apps/code-oss/tests/runtime-task-bridge.test.mjs`

- [ ] Step 1: 失败测试——`getTaskDetail`/`getTaskTrajectory` 只放行精确允许路径(taskId/runId 需防路径穿越);descriptor 中途变更拒绝;401 → typed stale;1 MiB 上限;channel 未知命令仍拒绝
- [ ] Step 2: 实现两个命令;GET allowlist 逐项登记
- [ ] Step 3: 生命周期三层身份证据回归测试不红

### Task 3: Sessions provider 详情与转录投影

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/`(provider 相关文件)
- Modify: `apps/code-oss/tests/agent-os-sessions-provider.test.mjs`

- [ ] Step 1: 失败测试——选中任务打开只读详情;trajectory 映射为转录项;非单调/未知类型事件流不渲染并报 lastError;gap 标注项存在
- [ ] Step 2: 实现投影;16 个写入口 typed-reject 集合不缩小
- [ ] Step 3: 结构测试更新(若触碰注册接缝)

### Task 4: e2e oracle 扩展(失败先行)+ 手动验证 + 独立评审

**Files:**
- Create: `apps/code-oss/tests/dual-workbench-slice-2.test.mjs`(不动 slice-1 oracle)
- Create: `.agent_runs/dual-workbench-slice-2-<date>/verification.md`

- [ ] Step 1: **先写失败 e2e**:真实 runtime 起任务 → Sessions 选中 → 断言详情渲染、转录顺序与 gap 标注、页面/载荷无 `approval`/`proposed_action`/`provider_usage` 键、bearer 不泄漏、无写控件、reload 存活、quit 有界终止
- [ ] Step 2: 实现至 e2e 转绿;截图 + verification.md;如实标注仅单测覆盖的行为
- [ ] Step 3: `git status --short` / `git diff --check`;提交;`messages.jsonl` 记账
- [ ] Step 4: 独立评审(builder ≠ reviewer),APPROVE 才谈下一步

### Task 5(条件触发): Python/contracts 变更

仅当 Task 1–4 证明现有端点确实不够时启动:contracts 变更走封闭模型 + tests/product 全量 + 独立评审范围扩大。默认不启动。

## 实施补记（评审收口后追加）

- **DRAFT/null → SessionStatus.InProgress**（原 Slice 1 映射为 Untitled）：
  e2e 发现上游把 Untitled 视为本地未发送草稿并打开可交互 new-chat 编辑器，
  对 runtime 拥有的 DRAFT 任务构成写面。修正见 commit 01d4d97e，
  证据见 verification-slice-2.md。
- **decodeTaskDetail 输入面封闭**：独立评审 P1-1 后追加已知顶层键校验（19 键），
  未知顶层字段 fail-closed。
