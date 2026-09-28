# Fusion Agent Architecture Spec v1.0 审查

> 审查对象：`/Users/mima1234/WorkBuddy/2026-09-09-02-35-15/deliverables/software-company/fusion-agent-architecture-spec-2026-09-09.md`  
> 审查日期：2026-09-09  
> 结论：`REVISE_TO_SPEC`  
> 置信度：高  
> 边界：本文只审查架构，不主张任何代码已经实现。

## 1. 总体结论

该文档结构完整、写作认真，也包含若干可复用的协议与安全设计片段，但**不能作为当前 Agent OS 的 Phase 0 实施输入**。

根本原因不是细节遗漏，而是它在未经本项目权威文档裁决的情况下锁定了错误的产品拓扑：

```text
spec v1.0:
独立 Agent Electron 应用 + 独立 Code-OSS IDE + Rust daemon

应采用：
一个 Agent OS Code-OSS 应用
├── IDE Window / standard Workbench
└── Agent Window / dedicated Sessions Workbench
    └── 共享 Agent Core、任务状态、窗口服务与产品数据
```

它还把 IDE 侧设计为 built-in extension + Webview，明确否决深度修改 Workbench。这与用户已经反复否决的形态、Cursor/Qoder 本机代码、VS Code 官方 `src/vs/sessions` Agents Window 架构同时冲突。

## 2. 阻塞性问题

### P0-1：D3“两个独立应用”必须撤销

证据位置：原 spec 第 42–48、824–869 行。

问题：

- “双应用 + daemon”并非当前项目权威文档中的 Founder-ratified 决策。
- 它重新制造两个壳、两套窗口生命周期、两个 deep-link handler 和跨应用切换。
- 原 spec 自己在第 811 行承认两个应用争抢同一 URL scheme，这是错误拓扑产生的问题。
- Cursor/Qoder 的本地发行代码显示，它们是在同一 Code-OSS 应用中区分 Agent/IDE 窗口类型并加载不同 Workbench。

裁决：`REJECT`。

替代：一个产品安装包、一个 Electron main/application service graph、两个顶层 window kind 和两个 renderer/Workbench entry。长期运行的 Agent Core 可以是受监督服务进程，但它不是拆成两个产品的理由。

### P0-2：ADR-05“最小 fork + Webview”必须撤销

证据位置：原 spec 第 112–120、739–791 行。

问题：

- `AI ViewContainer + webview` 无法实现独立 Agent Workbench。
- built-in extension 可以承担 provider、工具适配器和部分 IDE contribution，不能拥有 Agent Window 顶层布局。
- “至多五处源码补丁”的约束没有来源，也无法承载独立 renderer、window configuration、Parts、layout、session services 和跨窗口 handoff。
- VS Code 官方已经将 Agents Window 放在与 `vs/workbench` 平级的 `vs/sessions` 顶层层级，而不是扩展 Webview。

裁决：`REJECT`。

替代：深度 Code-OSS fork，但控制修改边界。Agent/Sessions 专属逻辑进入独立顶层模块；共享能力才进入 `vs/workbench`；provider/runtime adapter 可由 built-in contribution 提供。

### P0-3：D1“Rust 已锁定”缺少有效授权和迁移论证

证据位置：原 spec 第 42–46 行。

问题：

- Goal Blueprint、CURRENT_STATE 和 Agent OS Product Blueprint 没有把 Rust 规定为产品内核语言。
- “系统级沙箱只有原生语言可精确控制”是错误论据。沙箱由 OS 进程边界、profile、syscall/filesystem policy 和执行器保证，不由业务编排语言自动保证。
- 当前 Agent OS 已有真实 Python Product Runtime、Task/Run、权限、Evidence、Outcome、Help、恢复路径和测试证据。直接新建 Rust kernel 等于绕开而不是迁移这些能力。
- spec 没有列出当前合同到新 crate 的逐项映射、双写/回放迁移、兼容门和回滚策略。

裁决：`REOPEN_DECISION`。

建议：先定义语言无关的 Host/Runtime contract。Rust 可优先用于需要强进程隔离、低级系统控制或高吞吐的 executor/sandbox broker。只有在基准证明整体迁移收益覆盖回归风险后，才升级为主 Runtime 迁移 ADR。

### P0-4：产品状态模型被错误压缩成 Session/Turn/Event

证据位置：原 spec 第 83–100、225–323 行。

问题：

- 当前权威蓝图规定 `Mandate` 位于 Task/聊天之上，产品还需要 Outcome/Commitment、Task、Run、ActionContract、Evidence、Artifact、Decision、HelpRequest、权限与纠正状态。
- spec 只有 Session、Turn、工具和消息，仍是“耐久聊天内核”，不是 Agent OS。
- `payload: unknown` 让所谓完整类型定义失效。
- Coding 附件仅覆盖 selection/open_file/diagnostics/symbol，无法承载设计、数据、Ops、文档和组织协作产物。
- 没有组织、成员、角色、任务协作、评论、handoff、归属、可见性和租户边界。

裁决：`REJECT_MODEL`。

替代：以现有 Agent OS typed contracts 为源，协议投影至少覆盖 Mandate、Task、Run/Attempt、Step、Chat、Artifact、Evidence、Outcome、Decision、CapabilityGrant、HelpRequest 和 WorkspaceBinding。Session 只是交互/订阅投影，不是真相根。

### P0-5：共享 daemon 的 stdio 拓扑自相矛盾

证据位置：原 spec 第 124–149、759–778、828–846 行。

问题：

- stdio 连接天然属于启动子进程的单一父进程。
- spec 同时画出 IDE extension 和 Electron Main 各自用 stdio 连接同一个 daemon，却没有定义谁拥有 daemon、第二个宿主如何接入、进程重启后如何重新发现，以及单实例仲裁。
- 如果两端各自 spawn，会得到两个 daemon；如果只有桌面端拥有 daemon，桌面端关闭后 IDE 路径失效。
- “本地 stdio 信任”也不能替代 host identity、authority scope 和 profile 隔离。

裁决：`INVALID_TOPOLOGY`。

替代：

- 同一 Code-OSS 应用内，两种窗口优先通过 shared process/main-process services 访问同一 Runtime client。
- 若 Runtime 独立为服务进程，监督者使用 stdio 管理子进程；多个 renderer/CLI 客户端通过受权限保护的 Unix domain socket / named pipe 接入。
- 握手必须绑定 instance、profile、host identity、protocol version、capability lease 和 authority scope。

### P0-6：权限决策没有绑定权威主体与精确效果

证据位置：原 spec 第 228–260、365–374、915–935 行。

问题：

- `PermissionDecision { requestId, decision }` 没有 actor、role、tenant、task/run、action digest、policy version、expiry 和 authority proof。
- “任一在线宿主均可审批”把显示界面误当权威主体，违反 C7 与 typed authority 边界。
- `ConfigureSession` 对权限/沙箱采用后写覆盖，允许并发宿主用普通配置更新改变权限。
- `Interrupt` 只绑定 session，不能精确停止 run/attempt/step。
- `always_allow_rule` 没有范围、期限、资源、命令模式和撤销合同。

裁决：`SECURITY_BLOCKER`。

替代：审批必须绑定不可变 ActionContract digest、请求者、审批主体、权限范围、策略版本、有效期和 receipt；权限扩张不能走普通 LWW 配置。停止操作按 run/attempt 定位并保持 C7 优先级。

## 3. 重大设计缺陷

### P1-1：JSONL 不应成为产品唯一真相

原 spec 的 append-only、seq、checksum、blob 外置和可回放目标有价值，但“每个 session 一个 JSONL + meta.json”无法单独可靠承载：

- 多实体原子事务和唯一约束；
- 多客户端并发、租约和查询；
- 任务、运行、审批、产物与索引的一致快照；
- schema migration、retention、归档和局部恢复；
- 组织权限查询与审计隔离。

此外，“发现损坏行就截断”会销毁后续证据，不符合不可抹除审计。xxhash 只能检查意外损坏，不提供防篡改性。

建议采用：事务型 durable state store + append-only domain/audit event log + content-addressed blob store + 可重建搜索索引。研究导出可以是 JSONL，但不能反过来让研究格式决定产品真相模型。

### P1-2：回放语义不应全量重放 token delta

无游标时从 seq 0 重放所有 token delta 会随长期任务无限变慢，并把 UI 恢复绑定到历史 reducer 的每个版本。

应采用 versioned snapshot/checkpoint + tail events：

- raw immutable events 用于审计；
- canonical materialized state 用于快速 attach；
- cursor/epoch 检测缺口和历史裁剪；
- reducer/schema migration 明确版本；
- attach 返回 snapshot digest、tail start、head seq 和 subscription lease。

原规则 R3 在事件已裁剪时要求退回全量 R2，逻辑上也无法成立。

### P1-3：Op 幂等与并发控制不充分

- UserTurn/CreateSession 非幂等会在网络重试、宿主崩溃和 ack 丢失时重复执行。
- 所有 mutation 都需要 `clientOperationId/idempotencyKey`。
- 配置和策略修改需要 `expectedRevision` 或显式 conflict。
- 先到先服务不是可靠的跨设备顺序定义，需要 server-assigned order 与客户端 causal metadata。
- Event 必须是 discriminated union，禁止 `payload: unknown` 作为冻结协议。

### P1-4：自动化调度放在桌面 UI 进程中不合理

原 spec 明确桌面端不运行时 cron 不触发。这与长期工作、恢复和后台执行目标冲突，也让 UI 进程获得了调度权威。

调度应属于 Runtime/service 层，桌面端只编辑定义和展示运行。无人值守执行必须绑定单独 Mandate、CapabilityGrant、预算、期限、停止条件和结果投递策略。

### P1-5：缺少真实 Agent Workbench 的状态与布局合同

文档没有定义：

- 独立 renderer bootstrap；
- Agent Workbench service collection；
- Titlebar/Sidebar/Sessions Part/Editor/Auxiliary Bar/Panel 的 Part ownership；
- SerializableGrid topology；
- per-session editor/detail/panel working set；
- session provider → visible session → active chat 的单一状态源；
- Agent ↔ IDE window focus/create/workspace handoff；
- window restore、crash recovery、empty workspace 路径。

因此它无法指导用户要求的 Agent Window 实施。

### P1-6：竞品表存在无来源或错误归纳

原 spec 没有固定来源、版本、路径和事实/推断分类。例如：

- 把 Cursor/Qoder 仅概括为“fork 内嵌”，遗漏独立 Agent Workbench bundle。
- 把 Qoder Agent Window 降成“Quest 悬浮窗近似”。
- 对 Cursor 的 shadow workspace 演进作出无可核验主张。
- 对各产品的沙箱、协议和持久化以“无”填表；闭源不可见不等于不存在。

竞品证据应改为：产品版本、文件路径/公开源码 URL、观察到的符号、事实、有限推断、未知项。

## 4. 可保留内容

以下内容可以迁入 v2，但必须挂到正确产品模型上：

- Op/Event 信封、session 内 seq 和 gap detection。
- schema 单一来源和协议版本协商。
- write-ahead 后再发布事件的原则。
- 大对象 content-addressed blob 外置。
- replay 与 live subscription 之间的原子 cutover。
- host capability lease、离线撤销和工具执行超时思路。
- 权限策略与 OS sandbox 两个正交维度。
- secret 不进入普通日志/事件的红线。
- 阶段验收必须有反例、故障与绕过测试。

这些约占文档价值的三分之一；不能因为这些段落写得完整，就接受上层错误拓扑。

## 5. 修正后的架构骨架

```text
Agent OS Code-OSS Application
├── Electron Main / Shared Process
│   ├── WindowKindRegistry
│   ├── AgentWindowLifecycle
│   ├── IDEWindowLifecycle
│   ├── CrossWindowActionRouter
│   └── AgentCoreSupervisor / RuntimeClient
├── IDE Renderer
│   └── standard Workbench
│       ├── editor/search/SCM/test/debug/terminal
│       ├── native coding chat and edit review
│       └── Agent ↗
├── Agent Renderer
│   └── AgentOS/Sessions Workbench
│       ├── Titlebar + IDE ↗
│       ├── Sessions Sidebar
│       ├── Sessions Part
│       ├── on-demand Editor
│       ├── Auxiliary Bar
│       └── on-demand Panel
└── Agent Core
    ├── Mandate/Task/Run/Outcome state
    ├── provider-neutral model and capability routing
    ├── authority/C7/evidence/receipt spine
    ├── durable state + event/audit log + blobs
    └── local/remote execution providers
```

关键边界：

- 一个应用不等于一个 renderer；两个 Workbench 可以共享同一安装包、主进程和状态服务。
- 独立 Runtime 进程是可靠性/安全实现选择，不是独立 Agent 桌面产品。
- 内部 Agent、模型和工具由 Runtime 按需组合；UI 不要求用户选择执行 Agent。
- Coding、设计、数据、Ops 共用任务/运行/产物合同，通过 Editor/Artifact provider 打开不同 surface。

## 6. 三项所谓“待拍板事项”的裁决建议

| 原事项 | 审查建议 | 理由 |
|---|---|---|
| codex-rs 自研或二开 | `DEFER / SPIKE` | 先完成现有 Agent Core contract mapping、license/API/安全基底差异和迁移成本；不能预设 Rust 全量重写 |
| ndjson 或 Content-Length | 暂选 `Content-Length` 或 socket length-prefix，待 transport spike | shared daemon 不应以双父进程 stdio 为主拓扑；先确定连接拓扑再冻结 framing |
| 产品名/deep link | `PARK` | 同一应用内部切换优先使用 window action/handoff；外部 deep link 不是当前阻塞项 |

另一个必须先拍板的问题是：**以哪个 VS Code `src/vs/sessions` commit 作为回移/升级基线**。这比 scheme 命名优先级高。

## 7. v2 必须达到的退出条件

1. 删除“双应用”和 Webview 顶层 Agent UI。
2. 明确一个 Code-OSS 应用的双 Workbench 启动与窗口生命周期。
3. 将当前 Agent OS Product Runtime 的真实合同逐项映射到 host protocol，不能另起一个 chat daemon 替代它。
4. 给出 VS Code `src/vs/sessions` 上游 commit、依赖差异、直接复用/改写/不采用清单。
5. 定义 Task/Run/Artifact/Evidence/Outcome/Decision/Mandate，而不只定义 Session/Turn。
6. 修复 multi-client transport、snapshot+tail、幂等、revision 和 capability lease。
7. 审批绑定 authority actor 与 exact action digest，并证明 C7 不可旁路。
8. 补组织协作、成员权限、任务看板、评论/handoff 和多 Agent 执行可观察性。
9. 每个竞品判断附本地路径或一手公开来源，并区分事实、推断和未知。
10. 给出一个真实纵向切片：创建任务 → 选择工作区 → 执行 → 打开产物/diff → Agent/IDE 双向切换 → 停止/失败/恢复。

在这十项满足前，不应冻结 schema，也不应启动 Rust kernel 或 Electron desktop Phase。

