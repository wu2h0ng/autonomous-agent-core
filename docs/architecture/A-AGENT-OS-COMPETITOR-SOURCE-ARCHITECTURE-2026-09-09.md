# Agent OS 双 Workbench 源码证据与重构蓝图

> Track: Product Track  
> 状态：`DESIGN_ONLY`；本文不主张当前实现已经可用  
> 日期：2026-09-09  
> 目标：以本机 Cursor、Qoder 的发行包和 VS Code 官方 Agents Window 源码为依据，确定 Agent OS 的 Code-OSS 产品架构。

## 1. 结论

当前 `apps/code-oss` 中的 Agent 页面实现应废弃。正确产品不是 Webview、EditorPane、编辑器标签页、覆盖在标准 Workbench 上的绝对定位 DOM，也不是另一个 Tauri/Electron 产品壳。

Agent OS 应是**一个 Code-OSS 桌面应用、两种顶层 Workbench**：

```text
Electron main process / shared application services
├── IDE Window
│   └── standard Code-OSS Workbench + coding-agent contributions
└── Agent Window
    └── AgentOSWorkbench + task/session/work/detail Parts
```

右上角只有一个目的地按钮：

- IDE Window 显示 `Agent ↗`，单击后聚焦已有 Agent Window；没有则创建。
- Agent Window 显示 `IDE ↗`，单击后聚焦最近的 IDE Window；没有则创建空 IDE Window。
- 这是窗口目的地动作，不是左右分段开关，不在编辑器里新增标签页。
- Agent Window 可以选择工作区并创建任务；空 IDE Window 也允许用户随后 Open Folder、Clone Repository 或连接远端环境。

## 2. 证据边界

### 2.1 Cursor 本机发行包

检查对象：`/Applications/Cursor.app/Contents/Resources/app`。

- 版本：Cursor `3.19.13`，commit `dd066f332fcea7382764400fde902f61920648d0`。
- 有标准 Workbench bundle `out/vs/workbench/workbench.desktop.main.js`。
- 另有独立 Agents/Glass bundle `out/vs/workbench/workbench.glass.main.js` 和单独 CSS。
- Electron main 的 `openGlassWindow` 使用 `glass: true`、`new-window: true` 创建窗口配置。
- `cursorFocusOrOpenEditorWindow` 查找非 Glass 窗口并聚焦；没有时创建 classic/editor 窗口。
- IDE 到 Agent 的工作区传递不是重新打开网页，而是向目标窗口发送 `glass.applyIdeWorkspaceHandoff` action。
- 已存在 Agent Window 时先聚焦，再通过 `cursorRunActionInWindow` 将 workspace identifier 传给目标 renderer。

**判断：** Cursor 的 Agent/IDE 是同一桌面应用内的两类原生 Code-OSS 窗口，分别加载不同 Workbench bundle，共享主进程能力并用跨窗口 action 完成 handoff。

### 2.2 Qoder 本机发行包

检查对象：`/Applications/Qoder IDE.app/Contents/Resources/app`。

- 版本：Qoder `1.106.3`，commit `733d555d9d78c46f93f09df4288a87ce18c87874`。
- 独立入口为 `out/lingma/agents-window/agents-window.desktop.main.js`，不是扩展 Webview。
- Electron main 暴露 `openAgentsWindow`、`focusLastActiveEditorWindow`，并以 `isAgentsWindow` 区分窗口。
- Agent Workbench 启动序列包含 `initServices → initLayout → renderWorkbench → createWorkbenchLayout → initializeArtifactArea → restore`。
- `renderWorkbench` 创建真正的 Part 容器并分别调用：
  - `taskListPart.create(...)`
  - `masterEditorPart.create(...)`
  - `artifactAreaPart.create(...)`
- Part 被放入 Workbench grid；task list 是 complementary 区域，master editor 是 main 区域，artifact area 是 complementary 区域。
- 从 Agent Window 打开 IDE 时，先根据当前 session/workspace 决定目标；没有目标时可以聚焦已有 IDE 或打开空 IDE。

**判断：** Qoder 的 Agent Window 是专用 Workbench 和专用服务集合。它验证了用户指出的核心问题：Agent Window 不能是 IDE editor area 中的一张页面。

### 2.3 VS Code 官方 Agents Window

VS Code `main` 已公开 `src/vs/sessions/`。这是一套完整的 Agents Window，而不是概念示例：

- renderer：`src/vs/sessions/electron-browser/sessions.ts`
- desktop main：`src/vs/sessions/electron-browser/sessions.main.ts`
- Workbench：`src/vs/sessions/browser/workbench.ts`
- Parts：`src/vs/sessions/browser/parts/`
- session contracts/services：`src/vs/sessions/services/sessions/`
- provider seam：`ISessionsProvider`
- contribution entries：`sessions.common.main.ts`、`sessions.desktop.main.ts`

官方固定拓扑：

```text
Titlebar
└── Content
    ├── Sidebar: sessions / automations / customizations
    └── Main region
        ├── Sessions Part | Editor | Auxiliary Bar | Custom View Grid
        └── Panel
```

关键约束：

- 不显示标准 Activity Bar、Status Bar、Banner。
- Sidebar、Sessions Part、Editor、Auxiliary Bar、Panel 都是 Workbench grid 的 Part。
- Sessions Part 自己管理一个会话视图 grid，不借用 editor group 冒充任务页面。
- Editor 默认隐藏；打开文件、diff、浏览器或需要细节时出现。
- Auxiliary Bar 展示当前 session 的 changes/files/details。
- Panel 默认隐藏，需要终端等工具时出现。
- `ISessionsService` 唯一拥有 visible sessions、active session、active chat 和恢复状态；Part 只渲染模型。
- `ISessionsProvider` 把本地、远端、不同 agent runtime 作为 provider 接入，不让 UI 写死某个 Agent。

**判断：** 对当前 Code-OSS 1.106.3，最可靠的路线是选定兼容的 VS Code `src/vs/sessions` 上游提交做架构回移，再将 Agent OS Runtime 作为 provider 接入。手写一个缩小版页面会继续制造不可维护的伪 Workbench。

## 3. 产品模型

### 3.1 用户对象

顶层对象只保留：

| 对象 | 含义 | 用户是否必须理解 |
|---|---|---|
| 工作区 | 文件夹、仓库、远端环境，或无工作区快速对话 | 是 |
| 任务 | 有目标、状态、权限与产物的持续工作单元 | 是 |
| 对话 | 一个任务中的主对话或侧对话 | 是 |
| 运行 | 某次执行 attempt，包含步骤、日志、权限决策与结果 | 按需 |
| 产物 | 文件、diff、文档、画布、数据视图、报告、部署记录等 | 是 |
| Skill/工具 | 系统按需调用的能力 | 按需 |
| 内部 Agent | Runtime 的执行单元 | 默认隐藏；调试/治理时显示 |

界面不再出现“个人空间”“创业工作室”“未添加上下文”“Agent·自动”或让用户手工指定内部 Agent 的控件。这些词没有稳定操作合同。

### 3.2 一套壳，多种工作

Coding、设计、数据、Ops 和日常工作不对应五个固定页面。它们共享任务、对话、运行、产物、权限和协作模型，区别由打开的原生 surface 决定：

- Coding：源码、搜索、diff、测试、终端。
- 设计：画布、资源、预览、批注。
- 数据：表格、Notebook、查询、图表、数据证据。
- Ops：终端、日志、拓扑、部署、告警。
- 日常工作：文档、浏览器、邮件/日历连接器、审批与交付物。

同一任务可在这些 surface 间切换；任务详情不能和某个专业页面绑定。

## 4. Agent Window 的可开发布局

### 4.1 Titlebar

```text
[macOS window controls] [←][→] [search / command center] [IDE ↗] […]
```

- `IDE ↗`：聚焦最近 IDE；不存在则打开空 IDE。若当前任务已有 workspace，则同时提供该 workspace 的打开意图，但不阻塞进入 IDE。
- Search：搜索任务、对话、产物、命令和工作区。
- `…`：新窗口、设置、帮助、诊断；不能放常用工作流动作。

### 4.2 Sidebar Part

```text
[新建任务]
[搜索]
[任务] [自动任务]

进行中
  任务 A       运行中
  任务 B       需决定
最近
  任务 C

[账号] [设置]
```

- 单击任务：设为 active session，在 Sessions Part 恢复其主对话；不打开 editor tab。
- 双击/快捷动作：在 Sessions Part 并排打开多个任务。
- 右键：重命名、固定、归档、复制链接、在 IDE 打开工作区。
- “需决定”是任务状态过滤器，不建独立 Inbox 产品概念。
- 工作区只作为任务分组/过滤和新建任务选择，不作为抽象“空间”。

### 4.3 Sessions Part

中心区域承载一个或多个 `SessionView`：

```text
[任务标题] [workspace] [status] [成员] […]
[主对话] [侧对话/协作线程]

conversation timeline
├── 用户目标
├── Agent 计划（可折叠）
├── tool/run steps（流式、可定位）
├── artifacts / decisions / errors
└── final result

composer
├── 输入
├── [+ 添加文件/图片/连接器/任务/对话]
├── [权限/执行环境摘要]
└── [发送/停止]
```

- `@` 是引用入口，不要求预先“添加上下文”。空状态不显示“未添加上下文”。
- `/` 调用 Skill/命令；系统也可按任务自动调用。
- 模型、内部 Agent 和路由策略默认由系统决定；只在高级设置/治理策略显式暴露。
- 单击运行步骤定位到相应日志、终端、文件、浏览器或产物。
- 失败显示失败原因、已完成步骤和可恢复动作，不能只显示“Runtime 未连接”。

### 4.4 Auxiliary Bar

按任务状态切换同一个组件的内容：

- `变更`：文件与 hunk、接受/拒绝、基线 digest。
- `产物`：文档、表格、画布、报告、链接。
- `详情`：目标、状态、成员、权限、环境、运行记录。
- `文件`：当前工作区树。

它是当前任务的 inspector，不是永久“当前工作”空壳。

### 4.5 Editor 与 Panel

- Editor 默认隐藏。单击文件、diff、Notebook、画布、浏览器或数据视图时，通过 `IEditorService` 打开。
- Panel 默认隐藏。终端、Problems、Output、Debug 等按需出现。
- 打开 Editor/Panel 不把 Agent Window 变成 IDE；它们是完成任务所需的细节 surface。
- “切换到 IDE”是打开另一顶层 Workbench，用于持续、密集的专业编辑。

## 5. 共享运行时合同

```text
AgentOSSessionsProvider implements ISessionsProvider
├── list/create/rename/archive task sessions
├── create quick chat or workspace-backed session
├── resolve local/remote workspace
├── send request + stream events
├── stop/retry/follow-up
├── expose models and permission policy
├── expose changesets/artifacts/run receipts
└── recover after restart or sequence gap
```

Agent Window 和 IDE Window 共享同一任务数据库与 Runtime client。它们不共享页面 DOM，也不通过文件夹命名猜窗口类型。

建议最小 typed entities：

```text
TaskSession { id, title, workspace?, status, chats[], activeRun?, artifacts[] }
Chat       { uri, title, kind, messages[], unread }
Run        { id, attempt, status, steps[], startedAt, endedAt? }
Step       { id, kind, status, capability, inputRefs[], outputRefs[], receipt? }
Artifact   { id, kind, uri, version, provenance, openWith }
Decision   { id, action, risk, requestedBy, status, receipt? }
```

权限审批是运行中的 `Decision`，在任务时间线和详情中出现；“需要我处理”不再是独立导航体系。

## 6. 对现有实现的处置

必须删除或替换：

- `agentOSWindowEditor.ts` 中手写的 task/master/detail DOM 页面。
- 用 CSS 或 DOM 覆盖标准 editor area 的做法。
- 把 Agent 入口注册成 EditorPane/EditorInput 的做法。
- 用文件夹名、临时空 workspace 或特殊标签页模拟窗口类型。
- 仅验证字符串存在的测试；它无法证明真实 Workbench topology。

可以保留并重构：

- `agentOSWindow?: boolean` 原生窗口配置概念。
- NativeHost 的 open/focus/return-to-IDE 入口，但需补 workspace/session handoff 和单实例策略。
- IDE 侧布局/Chat/SCM/Terminal 的原生 contribution，前提是与 task/session 服务接通。
- built-in extension 作为 provider/工具适配器，不能拥有顶层 Agent Window UI。

## 7. 实施顺序与退出门

### Slice A：上游 Agents Window 回移设计

1. 固定 VS Code 上游 commit，生成 `src/vs/sessions` 文件清单和依赖差异。
2. 明确 Code-OSS `1.106.3` 是回移还是整体升级；不得边写 UI 边猜依赖。
3. 建立新的 renderer entry、product/window configuration 和独立 bundle。

退出门：启动 Agent Window 后不存在标准 Welcome/Editor tab strip；DevTools 中根 Workbench 为 Agent/Sessions Workbench；IDE 仍独立可启动。

### Slice B：真实 Parts 与 grid

1. Titlebar、Sidebar、Sessions Part、Auxiliary Bar、Editor、Panel 注册到 layout service。
2. 使用 `SerializableGrid` 构造固定 topology。
3. 关闭 Activity Bar、Status Bar、Banner；Editor/Panel 初始隐藏。

退出门：尺寸、显隐和重启恢复由 layout service 管理；删除任一 Part 注册会使结构测试失败。

### Slice C：Provider 与真实任务

1. 用内存 provider 先走通 typed session contract，但禁止硬编码成功。
2. 接 Agent OS Runtime：list/create/send/stream/stop/retry/recover。
3. Runtime 不可用时展示可诊断错误和重新连接，不阻断本地任务历史浏览。

退出门：创建任务、选择工作区、发送请求、流式步骤、停止、失败、重试和重启恢复均有集成测试。

### Slice D：IDE handoff 与 coding-agent 深度集成

1. Agent → IDE：聚焦/创建 IDE，并传 workspace + task/session id。
2. IDE → Agent：聚焦/创建 Agent Window，并传 workspace + selection/active task intent。
3. IDE 中接入 native chat、diff/multi-diff、terminal/test/debug 和 task receipts。

退出门：两种窗口之间没有 EditorPane 跳转；空 IDE 和 workspace-backed IDE 两条路径都可用。

### Slice E：非 Coding surfaces

通过 artifact/editor/provider contracts 接入文档、设计、数据、Ops 能力，不新增专业场景首页。

退出门：同一任务能打开至少三类不同产物，任务/对话/运行模型保持不变。

## 8. 验证策略

“验证”不是一个面向用户的固定按钮。这里指工程验收：证明实现没有再次退化成看起来相似的假窗口。

- 架构测试：独立 renderer entry、window flag、Workbench subclass、Part registry、grid topology。
- 反绕过测试：出现 `EditorPane`、`createWebviewPanel`、顶层绝对定位 overlay 或 fake workspace window 时失败。
- 集成测试：真实打开两个窗口，断言不同 renderer 与共享 session id。
- 交互测试：Agent↔IDE、先进入 IDE 再选文件夹、Agent 中选工作区、任务恢复、diff/terminal 打开。
- 故障测试：Runtime 离线、流中断、重复事件、停止超时、权限拒绝、工作区丢失。
- 视觉测试：只验证设计稿一致性，不替代上述行为测试。

## 9. 当前判断与置信度

- Cursor/Qoder 采用同应用、不同原生 Workbench/renderer：**高置信度，本机发行包直接证据**。
- 当前 DOM/EditorPane 方案必须删除：**高置信度，与三套实现均冲突**。
- 优先回移 VS Code 官方 `src/vs/sessions`：**高置信度的架构选择**，但具体成本必须通过固定 commit 的依赖差异审计后确定。
- 直接从当前 Code-OSS 1.106.3 手写全部 Agent Workbench：**不建议**，会重复实现已经公开且测试完备的基础设施。

