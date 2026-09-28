# Code-OSS Coding Agent IDE 重构架构

> Track: Product Track  
> 状态：`IMPLEMENTING`，仅限 `codex/ide-ui` 开发构建  
> 基线：Code-OSS `1.106.3` / `bf9252a2fb45be6893dd8870c0bf37e2e1766d61`

> 2026-09-09 架构纠偏：本文早期 P0 实现采用了手写 Agent 页面，不能证明真正的 Agent Workbench，现已判定为待删除实现。源码证据、最终拓扑与迁移门以 [A-AGENT-OS-COMPETITOR-SOURCE-ARCHITECTURE-2026-09-09.md](A-AGENT-OS-COMPETITOR-SOURCE-ARCHITECTURE-2026-09-09.md) 为准。

## 1. 产品边界

Code-OSS 是 Agent OS 的 IDE 窗口，不是承载 Agent 首页的 Webview。它负责编辑、搜索、代码导航、SCM、终端、调试、测试、扩展和变更审阅。Agent Window 是同一个 Code-OSS 应用的另一种原生窗口配置，负责跨 Coding、设计、数据、Ops 和日常工作的任务组织与协作。

两个窗口共享账号、项目、工作区、任务、会话、权限、技能、运行记录和产物引用。用户从 Agent Window 进入 IDE 时可以先进入 IDE，再选择或打开文件夹；不存在“必须已有 Coding 工作才能进入 IDE”的门槛。

## 2. 竞品实现事实与产品推断

### 2.1 本地实现事实

- Cursor 3.19.13 在 Code-OSS 主进程和 Workbench 内实现 Glass/Agent 窗口：`openGlassWindow`、`AgentLayoutService`、窗口恢复策略和 IDE workspace handoff 都位于原生窗口生命周期。
- Qoder 1.106.3 使用 `isAgentsWindow`、`openAgentsWindow`、`AgentsWindowSession` 和单独的 `agents-window.desktop.main`；Agent 窗口拥有自己的 task list、master editor、chat view 等 Workbench Part。
- 两者都保留 Code-OSS 原生编辑器、文件、SCM、终端、调试和扩展模型。Agent 能力深入 Workbench，而不是浮在 Webview 或独立 Electron/Tauri 壳上。

### 2.2 产品推断

对标不能等同于复制外观。需要重构的核心是：窗口类型、Workbench 布局、任务/会话状态、上下文选择、变更审阅、终端执行、恢复和可观察性成为同一个状态系统。

## 3. IDE 信息架构

```text
Native IDE Window
├── Title Bar / Command Center
│   ├── workspace + branch + remote
│   ├── universal search / command
│   └── one destination action: Agent ↗
├── Primary Side Bar
│   ├── Explorer / Search / SCM / Run / Extensions
│   └── Agent Sessions (task history, running state, attention state)
├── Editor Groups
│   ├── source / notebook / diff / multi-diff / preview
│   ├── inline edit proposal
│   └── exact-range review and accept/reject
├── Secondary Side Bar
│   └── Coding Agent conversation, plan, context chips, tool progress
├── Panel
│   ├── Problems / Output / Debug Console / Terminal / Ports
│   └── agent run output bound to task and command receipt
└── Status Bar
    ├── runtime / workspace trust / branch
    └── active task, running count and attention state
```

“Coding、设计、数据、Ops”不对应四套固定页面。IDE 暴露稳定的工作原语；任务所需的技能、工具和产物编辑器按需出现。布局由当前活动切换，数据分析可以打开 Notebook/表格/图表编辑器，设计可以打开画布/预览，Ops 可以打开终端/日志/拓扑，Coding 可以打开源码/diff/debug。

## 4. 原生组件与操作合同

| 组件 | 单击/操作 | 结果 | 状态保持 |
|---|---|---|---|
| `Agent ↗` | 单击 | 打开或聚焦同一应用的 Agent Window | 当前 workspace、active task、selection handoff |
| Agent Sessions | 单击任务 | 恢复该任务聊天、上下文和运行记录 | task/session id |
| Coding Agent | `Cmd/Ctrl+L` | 打开右侧原生 Chat 容器并聚焦输入 | 不改变编辑器和终端 |
| Review Layout | 命令面板或任务动作 | 左侧 SCM、中央 diff/multi-diff、右侧 Agent；隐藏底部 Panel | 记住用户调整后的宽度 |
| Run Layout | 命令面板或任务动作 | 保留编辑器和 Agent，打开并聚焦 Terminal | terminal 与 task/run receipt 绑定 |
| context chip | 单击 | 定位到文件、selection、symbol、diagnostic 或 terminal output | 只传引用；按需读取 |
| proposed edit | 单击文件 | 打开原生 diff；逐文件/逐 hunk 接受或拒绝 | exact digest + decision receipt |
| stop | 单击 | 请求停止当前 run；显示 stopping，收到确认后 stopped | 不伪装即时成功 |
| retry | 单击失败步骤 | 创建新 attempt 并保留原失败证据 | attempt id 单调增加 |

## 5. IDE 内部服务拆分

```text
AgentCodingWorkbenchService
├── LayoutProfileService
│   ├── coding
│   ├── review
│   └── run
├── WorkspaceContextService
│   ├── explicit references
│   ├── active editor / selection
│   ├── diagnostics / symbols
│   └── SCM / terminal summaries
├── AgentEditService
│   ├── proposal -> native diff
│   ├── accept/reject by digest
│   └── rollback receipt
├── AgentRunService
│   ├── terminal/task execution
│   ├── output streaming
│   └── cancellation/retry
└── AgentSessionProjection
    ├── task/session/run state
    ├── pending user decision
    └── restart recovery
```

模型或内部 Agent 不是用户必须选择的执行者。系统按任务调用技能、工具和内部 Agent；只有在调试或管理员策略中才显示具体执行单元。

## 6. 实施切片

### P0 原生宿主与布局

- 原生 Agent/IDE 窗口类型、聚焦、恢复和 workspace handoff。
- IDE 原生 Coding Agent、Review、Run 三种布局动作。
- Agent Window 单独 renderer/Workbench，不使用 Webview。
- Runtime 不可用时 IDE 仍完整可用。

### P1 上下文与编辑

- typed workspace projection，显式引用优先，禁止“未添加上下文”这类无意义状态。
- 原生 diff/multi-diff 审阅、hunk 级接受/拒绝、digest receipt。
- diagnostics、SCM 和 terminal output 作为可定位引用。

### P2 执行与恢复

- task/terminal execution、流式输出、停止、重试和 sequence-gap 恢复。
- Agent Sessions、运行状态、需要用户决策的统一投影。
- 进程重启后恢复窗口、task、编辑器、终端和未完成 run。

### P3 IDE 深度能力

- code index、跨仓检索、符号图、引用图和语义重构。
- debug/test failure 自动上下文闭环。
- worktree/branch/PR 生命周期与冲突处理。
- remote/SSH/dev container 和企业策略。

## 7. 当前实现状态

IDE 布局动作已有原生 Workbench contribution 草稿：

- `agentOS.coding.openAgent`
- `agentOS.coding.openReview`
- `agentOS.coding.openRun`

它们直接编排 `IWorkbenchLayoutService`、`IViewsService`、原生 Chat、SCM 和 Terminal，但尚未与真实 task/session provider 完成集成。

Agent Window 当前仍是不可接受的手写 UI，不是已完成切片，不能标记为 `implemented` 或 `verified`。后续必须用独立 Sessions/Agent Workbench、真实 Part grid 和 provider contract 替换。

## 8. 验收与证伪

- 删除 contribution import 后测试必须失败。
- 引入 Webview/DOM 替换后原生性测试必须失败。
- 三个布局动作缺少任一命令或不调用对应 Workbench Part 时测试必须失败。
- TypeScript 全仓 compile check 必须通过。
- 视觉验收只证明布局；真实任务验收必须覆盖：打开仓库、引用 selection、生成修改、审阅 diff、运行测试、停止/重试、重启恢复。

Cursor/Qoder 对标是架构和关键交互的产品基线，不构成已经达到功能同等水平的主张。
