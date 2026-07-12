# 热门 Agent 产品设计、源码与工程落地研究

> 日期：2026-07-10
> Track：Product
> 状态：外部参考研究；形成架构建议，但不直接授权实现
> 本地权威：`docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
> 产品事实：SPINE-0 仅在受限的本地独立开发者路径通过 PM 验收

## 1. 核心结论

领先 Agent 产品正在收敛到同一个判断：

```text
模型可以替换。
真正的产品是持久工作上下文、执行环境、能力边界、
人类纠正路径，以及对结果的证明。
```

市场竞争已经不是增加一个聊天框、ReAct 循环或可视化画布。可信产品都在模型
外围建设一套“工作操作层”：

- 持久 Task / Project 容器；
- 完整、可复现的执行环境；
- 由模型外系统执行权限检查的类型化工具；
- 可检查点、可恢复、可观测的长期运行；
- 绑定到具体变更和具体后果的审阅界面；
- 可复用的厂商所谓 Skill、App、知识和 Workflow 资产；
- Eval、监控、治理、发布和回滚生命周期；
- 只有在可证明有效时才启用的并行 Agent。

这支持现有 Agent OS 蓝图，但也要求修正近期重心：下一瓶颈不是继续增加静态页面
或 Agent 名单，而是把已经批准的 `WorkspaceProfile`、`ScenePreset`、`Task`、
`WorkflowGraph`、`ActionContract`、`Evidence` 和 `Outcome` 变成同一个持久运行时，
并贯通三个经过验证的黄金路径。

### 1.1 2026-07-11 产品裁决：Skill 只作外部兼容术语

本研究保留竞品官方使用的 `Skill` 名称作为事实记录，但 Agent OS 不把 Skill 定义
为 canonical kernel object。依据 ADR-0055，任何外部 SkillPackage 必须先拆解为：

```text
CapabilitySpec
+ WorkflowTemplate / LearnedProcedure candidate
+ Knowledge dependencies
+ Credential and Policy requirements
```

然后经过扫描、沙箱、Eval、权限审查和显式发布。Prompt、Persona 或 Skill 名称本身
不能授予执行权。场景冷启动由 `ScenePreset`/`DomainPack` 承担；长期方向是减少手工
skill glue，而不是消灭外部世界所需的 typed Capability 接口。

## 2. 证据方法与边界

本研究使用两类证据：

1. 对闭源商业产品使用官方产品与技术文档；
2. 对开源项目使用 2026-07-10 拉取的固定源码快照。

产品宣传只按“厂商主张”处理，不当作独立证明。源码检查只能证明某机制存在于所
检查版本，不证明其生产可靠性，也不构成直接复用建议。

Agent OS Core 继续保持自研。开源 Agent OS、Agent Framework 和 MCP 实现只作参考；
本研究没有复制源码，也不建议把任何外部 Agent Framework 变成 Core 运行时依赖。

## 3. 商业产品的设计哲学

### 3.1 OpenAI Codex：监督 Agent 的工作台取代传统 IDE 中心

**事实**

- Codex App 以 Project 下的长期 Agent Thread 为中心，可并行运行多个任务；
- Worktree 隔离并发变更，用户在线程中查看 Diff、评论并接管；
- Skill 封装指令、资源和脚本；Plugin 将 Skill 与经过批准的 App 组合；
- Automation 将指令和 Skill 放入定时后台任务，结果进入审阅队列；
- 沙箱和提权确认由 Harness 执行，不依赖模型自律。

**设计哲学**

产品核心从“编辑文件”转成“委派、监督、审阅和处理异常”。Plugin 负责打包工作，
但不会绕过底层 App 和数据源权限。

**对 Agent OS 的约束**

统一 Agent Surface 应作为主入口；低风险临时交互进入 `Ask`，有后果或长周期工作
进入 Task Workspace。`CapabilityPack` 和 `ScenePreset` 可以打包场景，但有效权限
必须由用户、Space、App 和 Runtime Policy 共同计算。

来源：[Codex App](https://openai.com/index/introducing-the-codex-app/)、
[ChatGPT 与 Codex Plugin](https://help.openai.com/en/articles/20001256-plugins-in-codex/)。

### 3.2 Claude Code：Gather、Act、Verify，并且始终可被打断

**事实**

- 显式 Agent 循环是收集上下文、执行动作、验证结果、继续迭代；
- Harness 提供项目上下文、工具、执行环境和 Session 管理；
- Session 可恢复和 Fork，修改文件前会建立 Checkpoint；
- 权限按工具类型分层，并由 Claude Code 而不是 Prompt 强制执行；
- Skill、MCP、Hook、Subagent 都是核心循环上方的扩展层。

**设计哲学**

Agency 来自工具和反馈，不来自更长的模型回答。用户通过随时打断和纠正留在闭环中。
Prompt 只能影响提议，不能授予权限。

**对 Agent OS 的约束**

`PolicyDecision` 必须发生在 Capability 执行之前。Ask、Plan、Work 应成为明确影响
能力范围的交互契约，而不是三套 System Prompt。

来源：[Claude Code 工作原理](https://code.claude.com/docs/en/how-claude-code-works)、
[Claude Code 权限系统](https://code.claude.com/docs/en/permissions)。

### 3.3 Cursor：环境与持久执行本身就是产品

**事实**

- Background Agent 在隔离机器和分支运行，可配置安装、后台 Terminal 和加密 Secret；
- Cursor 发现云环境缺失经常表现为“模型质量悄悄下降”，而不是明确报错；
- 云运行时从脆弱的 Work-stealing Loop 迁移到 Durable Workflow；
- Agent Loop、Machine Lifecycle 和 Conversation Stream 被拆成独立组件；
- 客户端流能够识别重试并回滚已经展示的部分输出；
- 多 Agent 实验发现：结构不足会冲突和漂移，结构过多会产生新瓶颈。

**设计哲学**

云 Agent 需要一套“Agent 的企业 IT”：环境镜像、休眠恢复、网络策略、Secret 管理、
检查点和自诊断。模型只是分布式系统中的一个进程。

**对 Agent OS 的约束**

必须拆分 `Task/Run`、`ExecutionLease`、`EnvironmentInstance` 和
`ConversationProjection`。HTTP 请求进程或单个 VM 不能成为长期任务的权威状态。

来源：[Cursor 云 Agent 工程经验](https://cursor.com/blog/cloud-agent-lessons)、
[Background Agent](https://docs.cursor.com/background-agent)、
[长期多 Agent 实验](https://cursor.com/blog/scaling-agents)。

### 3.4 Manus：持久化配置与按任务形态扩展并行度

**事实**

- Project 持久化 Master Instruction 和 Knowledge Base；
- 已有 Session 保留创建时配置，新 Session 才继承更新，避免静默追溯修改；
- Wide Research 将大量相互独立的对象拆到独立上下文并行处理，再统一合并；
- 官方明确指出：顺序依赖任务、小批量任务和交互式深挖不适合 Wide Research。

**设计哲学**

通用 Agent 通过持久工作环境和弹性计算变得实用。并行度应由任务结构决定，不应由
预设的“Agent 角色组织图”决定。

**对 Agent OS 的约束**

每次 Run 必须绑定不可变 `TaskConfigurationSnapshot`。只有在独立性、合并规则、
预算和评估器都明确时，才允许 Subagent Fan-out。

来源：[Manus Projects](https://manus.im/blog/manus-projects)、
[Wide Research](https://manus.im/docs/features/wide-research)。

### 3.5 Microsoft Copilot Studio：Build、Preview、Evaluate、Publish、Monitor

**事实**

- 新体验以自然语言生成底层 Agent 配置；
- Build 页面统一配置 Instructions、Knowledge、Tools、Skills、Model 和 Connected Agents；
- 生命周期是 Create -> Build -> Test/Evaluate -> Publish -> Monitor；
- Environment 是企业数据、角色、Connector 和 Dev/Test/Prod 生命周期边界。

**设计哲学**

企业 Agent 的价值取决于 Agent 外围的应用生命周期和治理，而不只是单次对话中的
Orchestration。

**对 Agent OS 的约束**

Organization Workspace 必须是 Tenant 和 Policy 边界，不是换皮预设。Agent、Workflow、
Plugin、Preset 都需要 Draft、Evaluated、Published、Deprecated、Revoked 状态。

来源：[Copilot Studio 新 Agent 体验](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/overview)、
[分区治理](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/sec-gov-phase2)。

## 4. 开源项目源码检查

GitHub Star 只用作 2026-07-10 的热度信号，不代表技术质量排名。

### 4.1 OpenHands

- 仓库：[OpenHands/OpenHands](https://github.com/OpenHands/OpenHands)，检查时约 80.3k Star；
- 快照：`d1563c95260d`；
- 许可：指定 Enterprise 目录之外为 MIT。

**源码事实**

- `AppConversationInfo` 分离 Conversation、Repository、Branch、Sandbox、Provider、
  Trigger、Metrics、父子 Conversation 和 Agent Profile 来源；
- `PluginSpec` 按 Conversation 加载 Plugin 配置，不把插件状态隐式设为全局；
- `SandboxService` 定义 Start、Resume、Pause、Health、Archive、Delete 生命周期端口；
- `EventService` 将事件访问从 Conversation 存储中分离，并支持文件和云端实现。

**可借鉴点**

前端、Task/Conversation 状态和执行后端必须可独立替换。但其本地文件事件实现也说明，
Agent OS 权威日志不能只按时间戳排序；还需要单调 Sequence、乐观并发、Idempotency 和
Digest Integrity。

固定源码：

- [Conversation 模型](https://github.com/OpenHands/OpenHands/blob/d1563c95260d/openhands/app_server/app_conversation/app_conversation_models.py)
- [Sandbox 生命周期](https://github.com/OpenHands/OpenHands/blob/d1563c95260d/openhands/app_server/sandbox/sandbox_service.py)
- [Event Service](https://github.com/OpenHands/OpenHands/blob/d1563c95260d/openhands/app_server/event/event_service.py)

### 4.2 Cline

- 仓库：[cline/cline](https://github.com/cline/cline)，检查时约 64.5k Star；
- 快照：`3266121fa1b2`；
- 许可：Apache-2.0。

**源码事实**

- Tool Policy 只为少量只读工具建立默认 Auto-approve 集合；
- MCP 工具通过 Policy 条目禁用，而不是依赖 UI 隐藏；
- Checkpoint 将消息历史和 Git Ref 绑定，可恢复到指定 Run 边界。

**可借鉴点**

权限和恢复是一等产品能力。Cline 的 Restore 会执行 Hard Reset 和 Clean，因此只能在
显式拥有的隔离 Worktree 中使用。Agent OS 不能把类似恢复操作用于用户共享的脏工作区。

固定源码：

- [Tool Policy](https://github.com/cline/cline/blob/3266121fa1b2/apps/cli/src/runtime/tool-policies.ts)
- [Checkpoint Restore](https://github.com/cline/cline/blob/3266121fa1b2/sdk/packages/core/src/session/checkpoint-restore.ts)
- [MCP Policy](https://github.com/cline/cline/blob/3266121fa1b2/sdk/packages/core/src/extensions/mcp/policies.ts)

### 4.3 OpenAI Agents SDK

- 仓库：[openai/openai-agents-python](https://github.com/openai/openai-agents-python)；
- 快照：`dd0300bff9d5`；
- 许可：MIT。

**源码事实**

- Run Loop 显式协调 Model Turn、Tool、Handoff、Approval、Guardrail、Trace、Streaming 和
  Session Persistence；
- `RunState` 是用于暂停/恢复的版本化快照，保存模型响应、生成项、审批、Guardrail、
  Usage 和 Sandbox Resume State；
- Session Persistence 含归一化、去重、孤立 Tool Call 清理，说明 Memory 不是简单追加消息；
- Sandbox Session 有生命周期所有权、清理、并发保护和后端恢复状态。

**可借鉴点**

这是 RunState 和 Human-in-the-loop 的高价值参考，但仍是 SDK Harness，不是完整产品权威层。
Agent OS 仍需自行实现 Tenant、Policy、ActionContract、Evidence、Outcome 和发布语义。

固定源码：

- [Run Loop](https://github.com/openai/openai-agents-python/blob/dd0300bff9d5/src/agents/run_internal/run_loop.py)
- [RunState](https://github.com/openai/openai-agents-python/blob/dd0300bff9d5/src/agents/run_state.py)
- [Session Persistence](https://github.com/openai/openai-agents-python/blob/dd0300bff9d5/src/agents/run_internal/session_persistence.py)

### 4.4 LangGraph

- 仓库：[langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)；
- 快照：`95af6a007185`，版本 `1.2.9`；
- 许可：MIT。

**源码事实**

- `StateGraph` 将类型化状态、Node 和 Reducer 编译到 Pregel 风格 Runtime；
- Runtime 暴露 Sync、Async、Exit-only 三种 Durability Mode；
- Checkpoint 保存 Values、Next Nodes、Parent Config 和 Pending Tasks；
- Stream 区分 Values、Updates、Messages、Checkpoints、Tasks 和 Debug；
- Retry Policy 区分瞬态基础设施错误和确定性应用错误。

**可借鉴点**

Graph Durability、Interrupt、Stream Semantics 是 WorkflowGraph 的重要参考，但不能解决
副作用幂等、Approval Binding、Authority、Outcome Verification。采用框架也不会消除这些
困难，并且当前边界禁止其成为 Agent OS Core 依赖。

固定源码：

- [Graph 与 Durability 类型](https://github.com/langchain-ai/langgraph/blob/95af6a007185/libs/langgraph/langgraph/types.py)
- [Checkpoint](https://github.com/langchain-ai/langgraph/blob/95af6a007185/libs/langgraph/langgraph/pregel/_checkpoint.py)
- [Pregel Loop](https://github.com/langchain-ai/langgraph/blob/95af6a007185/libs/langgraph/langgraph/pregel/_loop.py)

### 4.5 Dify

- 仓库：[langgenius/dify](https://github.com/langgenius/dify)，检查时约 148k Star；
- 快照：`489e77658e98`；
- 许可：修改版 Apache-2.0；使用其源码运营多租户服务需要商业许可，前端还有品牌限制。

**源码事实**

- Workflow 绑定 Tenant、App、Version、Graph、Environment、Conversation 和 RAG Variables；
- Workflow Run 与 Node Execution 独立存储并按 Tenant 查询；
- 新 `dify-agent` 使用追加式 Run Event 和 Snapshot；
- Ask-human 是经过字段和 Action Schema 验证的 External Deferred Tool，初次模型运行不能自行执行。

**可借鉴点**

Dify 是视觉工作流、RAG、Provider、Tenant 产品宽度的强参考，也证明画布不是 Agent OS：
其大块可变 Graph JSON 外围仍需要大量 Runtime、Tenant、Plugin、Data 和 Lifecycle 机制。
许可证与项目自研边界都禁止将其作为产品底座。

固定源码：

- [Workflow Model](https://github.com/langgenius/dify/blob/489e77658e98/api/models/workflow.py)
- [Ask-human Layer](https://github.com/langgenius/dify/blob/489e77658e98/dify-agent/src/dify_agent/layers/ask_human/layer.py)
- [Run Event Sink](https://github.com/langgenius/dify/blob/489e77658e98/dify-agent/src/dify_agent/runtime/event_sink.py)
- [License](https://github.com/langgenius/dify/blob/489e77658e98/LICENSE)

## 5. 跨产品成立的设计原则

### 原则 1：Task State 必须比模型进程活得更久

Conversation、Model Process、Execution Machine 和 Task Authority 是四个不同对象。关闭
客户端、替换 Worker、重试 Provider、等待审批和 Fork Run 都不能破坏权威状态。

### 原则 2：环境是正确性的一部分

缺依赖、Credential、Network Route、Data Mount、Test Service 往往不会立即报错，而会
产生看似合理但质量更差的结果。因此 `EnvironmentSpec`、Readiness Diagnostic 和 Snapshot
Digest 必须成为可见产品对象。

### 原则 3：Prompt 不授予权限

Instruction、Skill 和 Persona 只能影响 Proposal。只有 Capability、Policy、Credential 和
Approval 可以授权 Effect。Tool Output 也是不可信输入。

### 原则 4：Checkpoint 必须同时处理副作用

保存 Graph State 不够。每个有后果的 Node 都需要 Idempotency Key、Effect Receipt、Retry
Classification，以及 Compensation 或明确不可逆声明，否则 Resume 会重复发信、付款、部署或写数据。

### 原则 5：Memory 是治理状态，不是 Transcript Dump

短期消息、Task State、用户偏好、来源知识、Belief、验证经验具有不同 Provenance、Retention、
Invalidation，不能全部进入一个 Vector Store。

### 原则 6：并行需要证明义务

只有任务相互独立、上下文分离有收益、合并规则存在、质量/速度收益超过协调成本时才使用
Subagent。Swarm 本身不是价值。

### 原则 7：Evaluation 属于 Authoring Lifecycle

正确生命周期是 Build -> Preview -> Evaluate -> Publish -> Monitor。Workflow、Agent、Plugin、
Preset 不能从自然语言生成后直接进入生产。

## 6. 真实痛点与工程方案

| 真实痛点 | 用户看到的失败 | 工程机制 | 产品落点 | 最小验收门 |
|---|---|---|---|---|
| 冷启动 | 每次重述上下文和格式 | WorkspaceProfile + 版本化 ScenePreset Ref | 空间/预设切换 | 正确加载工具和知识且不隐藏扩权 |
| 环境漂移 | 本地成功、远程失败 | EnvironmentSpec、Probe、Snapshot Digest | 环境设置与阻塞面板 | 模型运行前识别缺依赖 |
| 长任务中断 | 任务消失或从头开始 | Event Log、Lease、Checkpoint、Resumable Worker | Timeline / Resume | 每个 Node 后杀 Worker，完成 Effect 不重复 |
| Provider 差异 | 模型更换后 Tool 失效 | Capability Discovery、Adapter Conformance、Routing Eval | Provider Center | 切换后契约不变，不支持能力被显式拒绝 |
| Secret 泄漏 | Key 进入 Prompt/Log | CredentialRef、Broker、Scoped Injection、Redaction | Connection Center | Event/Trace/Context 中找不到 Secret |
| 审批疲劳 | 用户无脑同意 | Risk Class + Exact ActionContract Diff | Consequence-bound Approval | Target/Digest 改变即使旧审批失效 |
| Plugin 扩权 | 更新后突然可写 | Signed Manifest、Permission Diff、Review、Revocation | Plugin Directory | 新 Write Capability 必须重新批准 |
| Workflow 漂移 | NL 与画布逻辑不同 | Canonical Typed IR + Lossless Compiler/Diff | Workflow Studio | NL/Canvas 往返不丢 Policy 和 Digest |
| Context 污染 | 旧数据或越权数据参与判断 | ContextGraph、ACL、Provenance、Validity、Deletion | Source Inspector | Source 撤权后检索和缓存都失效 |
| 假完成 | Agent 只说“已完成” | ExpectedOutcome、Evidence、Evaluator、ObservedOutcome | Outcome Panel | 无 Evidence 的固定回答不能通过 |
| 不安全恢复 | Retry 重复外部动作 | Node Idempotency + Effect Ledger | Recovery Preview | Effect 后崩溃只生成一个真实 Effect |
| Agent 冲突 | 并行覆盖或重复劳动 | Scope Ownership、Isolation、Dependency、Merge Policy | Topology View | 同 Scope 不得并发写入 |
| 成本失控 | 长时间消耗但无进展 | Budget、Progress Signal、Stall Detector、Escalation | Run Budget | 达冻结阈值后停止或升级 |
| 企业资产失控 | 无人负责的 Agent 持续运行 | Tenant Inventory、Owner、Lifecycle、Policy、Eval | Admin / Operations | Revoked Asset 不得开始新 Run |
| UI 幻觉 | 生成按钮暗示不存在权限 | UISceneSpec Registry + InteractionContract Validation | Generative Workspace | 未注册或越权 Control 被拒绝 |

## 7. Agent OS 目标工程结构

```text
Experience Plane
  Stable Shell -> WorkspaceProfile -> Ask/Work -> ScenePreset -> UISceneSpec

Authority Plane
  Identity/Tenant -> Policy -> CredentialRef -> CapabilityGrant -> Approval/Correction

Task Plane
  Goal -> Commitment -> Task -> WorkflowGraph Version -> AgentRun -> Outcome

Durable Runtime Plane
  EventLog -> Lease/Worker -> Checkpoint -> EffectLedger -> Recovery/Replan

Environment Plane
  EnvironmentSpec -> Snapshot -> Sandbox/VM -> Mount/Network/Secret -> Readiness

Capability Plane
  ProviderAdapter + ToolPlugin + App/Connector + MCP Edge Adapter

Context Plane
  ContextGraph -> Retrieval View -> Belief/Provenance -> Promotion/Invalidation

Verification Plane
  ExpectedOutcome -> Evidence -> Evaluator -> ObservedOutcome -> Learning Proposal

Operations Plane
  Trace/Replay -> Cost/Latency -> Incident -> Asset Inventory -> Publish/Rollback
```

这些 Plane 应分离 Package 和 Port，但不能分裂成多个产品。Personal、Developer、Organization
只是在同一组 Plane 上使用不同默认值和 Authority Envelope。

## 8. 建议优先级

### P0：先让静态产品模型变成真实契约

1. 新增类型化 `WorkspaceProfile`、`Space`、`ScenePresetManifest`、
   `TaskConfigurationSnapshot`；
2. 将 Preset 确定性编译到 Workflow、Capability、Knowledge、Policy、Evaluator、Memory、
   UISceneSeed 引用；Preset 只能收紧，不能扩大权限；
3. 将 Run Progression 放到 Durable Worker Port 后，API/UI 只发送 Command 和读取 Projection；
4. 新增 `EnvironmentSpec`、Readiness Check 和一个隔离的本地 Worktree/Sandbox Provider；
5. 将当前 Developer Path 从单文件全量替换扩展到受审阅 Multi-file Patch、Allowlisted Command、
   Browser/Visual Artifact Verification。

**退出门：**在每个 Workflow Node 后注入 Process Kill、Provider Failure、Approval Delay，仍然
保持可恢复和 Effect Exactly-once。

### P1：打通三个完整 Workspace 黄金路径

1. Personal：Research + Files -> 引用充分的交付物 -> 经批准的 Knowledge Promotion；
2. Developer：Issue -> 隔离修改 -> Test/Review -> Patch 或 PR Artifact；
3. Organization：只读 Data Diagnosis -> Evidence -> Approval Proposal -> Audit Record。

三条路径必须共享同一 Task、WorkflowGraph、Provider、Capability、Policy、Evidence、Outcome。
Organization 在 Tenant、Connector、Action Control 通过独立门之前保持只读/Proposal-only。

### P2：Authoring 与生态

1. 同一 WorkflowGraph 的自然语言、可视化 Canvas、Structured View；
2. 带 Signed Manifest、Capability Schema、Credential Requirement、Health、Compatibility、
   Permission Diff、Revocation 的 Plugin SDK；
3. Agent/Preset 的 Draft、Preview、Evaluated、Published、Deprecated、Revoked 生命周期；
4. ContextGraph 与来源级 Provenance/Invalidation，而不是通用 Vector-store RAG；
5. 只为预注册并行任务类开放 Subagent Fan-out、预算和 Merge Evaluator。

### P3：企业运营和差异化学习

1. 生产级 Tenant/RBAC/SSO/Retention/Audit 和 Environment Zoning；
2. Durable Schedule、Recurring Trigger、Incident/Replay、Cost Governance；
3. 按 ADR-0054 Gate 执行 Data Agent Migration；
4. 只有市场标配路径产生真实 Expected/Observed Outcome 后，才推进 Belief Ledger 和
   Governed Outcome Learning 产品化；
5. CWM 只在变量、干预、结果可测量的 Operating Envelope 中，与非 CWM 基线做 Held-out 对比。

## 9. 不应复制的东西

- 不复制竞品导航并把它误当成产品架构；
- 不把 Chat History 当作 Task State Authority；
- 不把 Agent Framework 直接作为 Agent OS Kernel；
- 不在非一次性隔离环境中提供全局“Approve Everything”；
- 不用 Mutable、Unversioned JSON 承载 Workflow Authority；
- 不把所有 Memory 放进同一个 Vector Database；
- 没有 Permission Diff、Revocation、Compatibility Test 前不上 Marketplace；
- 没有独立性和 Merge-quality Evidence 前不上 Agent Swarm；
- 不以 Dify 源码或前端为多租户基础：许可证和项目边界都不允许。

## 10. 决定是否超越的真实对照测试

| Operating Envelope | Baseline | 主要指标 | 必须包含的对抗条件 |
|---|---|---|---|
| Developer Repository Task | Codex / Claude Code / Cline / OpenHands | Verified Success、Review Time、Recovery Rate | Provider 中断、脏 Worktree |
| Personal Research / Files | ChatGPT / Claude / Manus | Citation Correctness、Artifact Quality、Setup Repetition | 过期和冲突 Source |
| Organization Data Decision | Copilot Studio / Dify / Data Agent Baseline | Evidence Completeness、Approval Burden、Decision Error | Source 撤权、Policy 变化 |
| Workflow Authoring | Dify / Copilot Studio / LangGraph Studio | Round-trip Fidelity、Time-to-valid | NL 与 Canvas 交替修改 |
| Plugin Ecosystem | Codex Plugin / MCP Tool | Setup Success、Permission Comprehension、Safe Update | Plugin 新增 Write Action |
| Long-running Execution | Cursor Cloud / OpenHands / LangGraph Reference | Resume Correctness、Duplicate-effect Rate、Intervention Load | 每个 Node 后 Worker/Network Failure |

只有市场标配先达到可信水平，且 CWM + Belief Ledger + Governed Outcome Learning 在声明的
Operating Envelope 中赢得这些测试，才可以主张“超越”。

## 11. 最终判断

现有 Blueprint 方向基本正确，但执行重点需要调整：

```text
不要先建设更大的 Agent 名单。
先建设一个持久操作底座、三个经过验证的工作环境，
以及权限和结果都可检查的生态。
```

最高杠杆的下一架构包应是：

> **P0 Workspace/Preset Contract + Durable Runtime Hardening**

而不是 Swarm、通用 RAG 或大规模 Generative UI。后续 UI 只能消费该底座输出的真实类型化
Projection，不能继续依赖浏览器 Fixture 模拟产品能力。
