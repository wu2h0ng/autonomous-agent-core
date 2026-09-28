# Agent Surface UI 对标与设计基线

> 日期：2026-08-15  
> 主标签：`U/P`  现状：`DESIGN_BASELINE / NOT_IMPLEMENTED`  
> 范围：CLI、Web、桌面端的统一 Agent Surface 交互设计

## 结论

Agent OS 不应复制某一个聊天产品或 coding agent 的界面。最有价值的组合是：

1. 借鉴 ChatGPT Agent、Manus 的“任务接管与持续执行”表达；
2. 借鉴 Claude Code、Cursor、Devin、Replit Agent 的“工作区、差异、终端与验证”表达；
3. 借鉴 Perplexity、NotebookLM、Glean 的“来源、证据与可追溯回答”表达；
4. 用 Agent OS 自己的 Mandate、Outcome、Help、Approval、Recovery 把它们统一成一张责任界面。

核心判断：Agent OS 的首屏不应该是“输入框 + 对话记录”，而应该是“当前由谁负责什么、进展到哪里、下一步需要什么、哪些事实仍不确定”。输入框只是进入责任循环的入口。

## 参照产品地图

以下是设计参照，不是对这些产品当前全部功能的完整审计。功能和命名可能随版本变化，正式竞品结论仍需逐项复核。

| 产品 | 主要参照价值 | 值得借鉴 | 不应照搬 |
| --- | --- | --- | --- |
| [ChatGPT Agent](https://openai.com/index/introducing-chatgpt-agent/) | 通用任务接管 | 任务开始前的计划感、执行中状态、用户接管点 | 以聊天线程作为长期责任真相 |
| [Manus](https://manus.im/) | 长任务执行 | 任务进度、后台运行、结果交付感 | 黑箱式“正在替你完成一切” |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) | 终端 coding agent | 低干扰命令流、上下文连续、工具调用可读 | 把终端输出当成完整产品体验 |
| [Cursor](https://www.cursor.com/) | IDE 内 Agent | 文件上下文、局部编辑、diff 审查、快捷操作 | 让 Agent 永久绑定 IDE，忽略非代码工作 |
| [Devin](https://devin.ai/) | 软件工程任务代理 | 任务委派、执行轨迹、产出物导向 | 只用“任务完成率”替代真实结果验证 |
| [Replit Agent](https://replit.com/ai) | 从意图到可运行产物 | 快速创建、即时预览、错误反馈闭环 | 把快速生成误认为可靠交付 |
| [Perplexity](https://www.perplexity.ai/) | 研究型回答 | 引用、来源定位、回答与证据绑定 | 只显示引用数量，不显示证据质量和冲突 |
| [NotebookLM](https://notebooklm.google/) | 受限知识空间 | 明确资料边界、基于来源问答、低幻觉预期 | 让用户手工维护全部上下文 |
| [Glean](https://www.glean.com/ai) | 企业知识与工作入口 | 权限感知搜索、企业对象聚合、回答后行动 | 把企业搜索结果堆成信息墙 |

### 参照优先级

首轮设计优先参考：`Claude Code + Cursor + Perplexity + ChatGPT Agent`。

理由：这四类分别覆盖日常操作、局部编辑、证据表达、长任务接管，最接近 Agent OS 当前真实产品闭环。Manus、Devin、Glean 用于验证长任务和组织级扩展，不作为首版主界面模板。

## 设计对象

### 用户真正需要看到的五件事

1. **责任**：当前 Mandate/Task 要达成的结果是什么。
2. **状态**：系统现在处于理解、执行、等待、验证、求助、恢复还是完成。
3. **证据**：为什么系统得出当前判断，证据是否新鲜、是否冲突。
4. **边界**：下一步是否需要审批、权限是否足够、哪些动作不会自动发生。
5. **接续**：用户纠正后，系统如何重规划；重启后，如何继续同一个任务。

### 不把认知负荷转嫁给用户

用户不应被要求反复回答：

- 你是谁、当前在做什么；
- 这个任务有哪些承诺和截止条件；
- 哪些信息已经失效；
- 为什么 Agent 停住；
- 哪个证据支持当前结论；
- 纠正之后哪些计划和改动需要重算。

这些内容应由界面主动汇总，且必须保留来源和时间。

## Agent OS 首屏信息架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Space / Mandate       当前任务状态       Provider / 权限 / 同步 │
├───────────────┬───────────────────────────────┬───────────────┤
│ 工作空间       │ 当前责任                       │ 证据与边界     │
│ 任务/承诺       │ 目标结果                       │ 来源           │
│ 最近变化       │ 当前阶段                       │ 新鲜度/冲突    │
│ 收藏/搜索       │ 下一步                         │ 权限/审批       │
│               │ 需要用户决定的问题               │ 变更/回滚       │
├───────────────┴───────────────────────────────┴───────────────┤
│ Command / Ask / Work 输入区                                  │
└─────────────────────────────────────────────────────────────┘
```

### 三栏职责

- **左栏：导航，不承载解释**。显示 Space、Mandate、Task、最近事件和搜索；避免把所有 Agent/工具做成角色列表。
- **中栏：当前责任，不是聊天流水账**。首屏先显示预期结果、阶段、阻塞点和下一步；聊天/工具轨迹作为可展开的过程证据。
- **右栏：可追溯边界**。显示证据来源、权限、审批、变更摘要、失败恢复和未知状态。所有高影响动作都要能回答“依据是什么、谁批准、失败如何收敛”。

## 交互模式

### Ask

适用于只读理解、查询、比较、解释。

- 默认不产生外部效果；
- 回答旁边显示来源、时间和冲突；
- 用户可一键“保留当前上下文，升级为 Work”；
- 不把 Ask 的回答误显示为已执行结果。

### Work

适用于需要持续状态、工具、验证或交付物的任务。

- 创建或附加到持久 Task；
- 首屏展示预期结果、验证方式、预算和当前阶段；
- 计划可以被用户纠正，纠正产生事件并使失效假设显式化；
- 工具执行、审批、证据和 Outcome 进入同一时间线。

### Review

适用于用户审查 Agent 提案。

- diff/动作摘要优先于完整日志；
- `Approve`、`Reject`、`Request changes` 三个动作必须区分；
- 审批绑定到精确 digest、权限和当前证据，不能只看自然语言描述。

### Recover

适用于中断、超时、外部效果未知或环境发生变化。

- 用“发生了什么 / 已确认什么 / 尚未确认什么 / 下一步如何对账”取代模糊的失败提示；
- `UNKNOWN_REQUIRES_REVIEW` 不能显示成普通失败，也不能自动重发；
- 恢复后保留同一 Task/Run 身份和 provenance。

## 跨端映射

| 设计对象 | CLI | Web | 桌面端 |
| --- | --- | --- | --- |
| 当前责任 | `agent status` | Responsibility header | 常驻顶部责任条 |
| Ask | `agent ask` | Ask 模式 | 全局快捷键唤起 |
| Work | `agent work` | Work composer | 新建任务面板 |
| 审批 | 明确的交互确认 | Review card + diff | 原生通知 + Review drawer |
| 证据 | 可复制引用/JSON | Evidence drawer | 侧栏详情与系统分享 |
| 恢复 | `agent resume` / `agent task-recovery` | Recovery state | 托盘/通知回到原任务 |
| 连接状态 | 单行状态摘要 | 顶栏 badge | 菜单栏/托盘状态 |

## 视觉方向

### 应该采用

- 浅色、低饱和、工作台式界面；用少量绿色/蓝色表达已验证与可执行状态；
- 8px 以下圆角，稳定网格，适合长时间扫描；
- 信息密度高于营销页面，但每个区块只回答一个问题；
- 状态颜色同时配合文字和图标，不能依赖颜色 alone；
- 关键动作固定在当前对象附近，减少鼠标往返；
- 键盘操作优先：`Cmd/Ctrl+K`、`Enter`、`Esc`、任务搜索和快速切换。

### 明确避免

- 巨型聊天气泡作为主界面；
- 把 Agent、工具、插件堆成“角色商城”；
- 把节点图、指标卡和日志同时放在首屏；
- 只展示“运行中”而不显示阶段、等待原因和下一步；
- 用黑箱动画掩盖权限、证据和未知状态；
- 为桌面端复制一份 Web 页面，而不处理窗口、通知、恢复和快捷键。

## 首版设计验收

首版 UI 设计完成前，至少回答以下问题：

1. 新用户 10 秒内能否说出当前 Task 的目标和状态？
2. 用户能否在 2 次点击内找到下一步和需要自己决定的事项？
3. 用户能否区分“Agent 建议”“已批准”“已执行”“已验证”？
4. 中断后能否从同一个 Task 恢复，而不是重新描述背景？
5. 用户能否看到证据来源、时间、新鲜度和冲突？
6. 任何外部效果是否都有清晰的审批/权限/回滚边界？
7. CLI、Web、桌面端切换后，Task、Run、审批、证据和恢复状态是否一致？

## 下一步设计任务

1. 先做 `1440x900` Web/桌面高保真首屏：Ask、Work、Review、Recover 四个状态。
2. 再做 `390x844` 移动/窄窗口版本，验证信息折叠顺序和关键动作可达性。
3. 同步输出 CLI 文案与状态词汇表，避免三端同一状态不同命名。
4. 用现有 `/preview-zh` 作为视觉试验场，再接入真实责任视图和 Task API。
5. 最后做 Tauri/native shell，不提前引入桌面专属业务状态。

## 公开参照入口

- OpenAI，ChatGPT Agent：<https://openai.com/index/introducing-chatgpt-agent/>
- Anthropic，Claude Code：<https://docs.anthropic.com/en/docs/claude-code/overview>
- Cursor：<https://www.cursor.com/>
- Devin：<https://devin.ai/>
- Replit Agent：<https://replit.com/ai>
- Manus：<https://manus.im/>
- Perplexity：<https://www.perplexity.ai/>
- Google NotebookLM：<https://notebooklm.google/>
- Glean：<https://www.glean.com/ai>
