# Agent OS Dual Workbench Slice 2 Implementation Plan(DRAFT,待 CTO 门禁)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sessions 窗口中的只读任务投影从"列表"深化到"任务详情 + 事件流只读转录":点击一个投影任务,在 Sessions 原生会话视图中看到该任务的 statement/status/run 详情与按序事件转录,全程保持只读。

**Architecture:** 沿用 Slice 1 已批准的拓扑——主进程独占 Runtime 桥(bearer 不出主进程)、renderer 只消费封闭类型投影、overlay `src/vs/agentos/` 承载全部新代码、patch 010 的上游改动面不扩大。事件流经 Runtime 只读 HTTP 端点拉取,以 `ISession` 的只读 chat 转录形式投影;两个窗口共享同一 taskId 事件域(spec V2 §12 验收②的只读半边)。

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

## 范围边界(In / Out)

**In:**
1. Runtime 只读任务详情端点消费:任务 statement、status、run_status、时间戳(优先复用现有 `/v1/tasks` 载荷;不足才新增只读 GET,走 contracts 变更)。
2. Runtime 只读事件/转录端点消费:按 taskId 拉取有序事件(seq 连续),映射为 Sessions 只读转录项。
3. Sessions 窗口交互:选中投影任务 → 打开只读详情/转录视图;刷新 reconcile 保持 facade 身份稳定(Slice 1 语义延续)。
4. e2e 扩展:oracle 断言详情渲染、事件顺序、seq 空洞检测、bearer 不出主进程、无写控件、reload 存活、quit 有界终止不回归。

**Out(显式排除):** 事件流实时推送(SSE/WS)、写路径与审批卡(spec §12 ③④属后续切片)、IDE 窗口侧任务联动、多 workspace、后台保活。

## Tasks(草稿,CTO gate 后细化到步骤级)

### Task 1: 详情/事件只读合同(contracts + decoder,失败先行)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.ts`
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.test.ts`
- Create: `apps/code-oss/tests/runtime-task-detail-contract.test.mjs`

- [ ] Step 1: 失败测试——任务详情与事件列表的封闭解码(多余字段/乱序/seq 空洞/未知事件类型全部拒绝)
- [ ] Step 2: 实现 decoder 与类型;事件按 seq 严格递增校验,空洞即 fail-closed
- [ ] Step 3: 全量测试 + 编译 0 errors

### Task 2: 主进程桥扩展(详情 + 事件拉取)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts`
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogChannel.ts`
- Modify: `apps/code-oss/tests/runtime-task-bridge.test.mjs`

- [ ] Step 1: 失败测试——新 IPC 命令只放行允许路径;descriptor 中途变更拒绝;401→typed stale;响应体上限
- [ ] Step 2: 实现 `getTaskDetail` / `getTaskEvents`(GET-only allowlist 逐项登记)
- [ ] Step 3: 生命周期三层身份证据回归测试不红

### Task 3: Sessions provider 详情与转录投影

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/`(provider 相关文件)
- Modify: `apps/code-oss/tests/agent-os-sessions-provider.test.mjs`

- [ ] Step 1: 失败测试——选中任务打开只读详情;事件映射为转录项;乱序/空洞事件流不渲染并报 lastError
- [ ] Step 2: 实现投影;16 个写入口 typed-reject 集合不缩小
- [ ] Step 3: 结构测试更新(若触碰注册接缝)

### Task 4: e2e oracle 扩展 + 手动验证 + 独立评审

**Files:**
- Modify: `apps/code-oss/tests/dual-workbench-slice-1.test.mjs`(或新建 slice-2 e2e)
- Create: `.agent_runs/dual-workbench-slice-2-<date>/verification.md`

- [ ] Step 1: e2e 断言扩展(详情渲染、事件顺序、seq 空洞、bearer 不泄漏、无写控件、reload、quit 终止)
- [ ] Step 2: 截图 + verification.md;如实标注仅单测覆盖的行为
- [ ] Step 3: `git status --short` / `git diff --check`;提交;`messages.jsonl` 记账
- [ ] Step 4: 独立评审(builder ≠ reviewer),APPROVE 才谈下一步
