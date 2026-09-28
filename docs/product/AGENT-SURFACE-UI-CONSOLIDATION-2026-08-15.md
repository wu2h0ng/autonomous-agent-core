# Agent Surface UI 设计合并与优化决策

> 日期：2026-08-15  
> 主标签：`U/P`  次标签：`A`  
> 状态：`DESIGN_BASELINE / FOUNDER_REVIEW_REQUIRED / NOT_IMPLEMENTED`

## 1. 这次盘点覆盖了什么

本次检查了以下历史资产：

| 资产 | 角色 | 当前判断 |
| --- | --- | --- |
| `docs/research/autonomous-agent-core-v0.2/docs/frontend/UI_SPEC.md` | 早期研究控制台草图 | 保留为历史索引，不作为产品导航 |
| `docs/research/autonomous-agent-core-v0.3/docs/frontend/FRONTEND_ARCHITECTURE.md` | Next.js/React 方向 | 保留技术方向，不能覆盖当前 Python Surface 事实 |
| `docs/adr/ADR-0040-frontend-ux-review.md` | 对四面板研究控制台的用户视角批判 | 保留“上下文纠正、渐进披露、DAG 按需展开”原则 |
| `docs/product/AGENT-PRODUCT-DESIGN-SOURCE-STUDY-2026-07-10.md` | 竞品和运行时产品研究 | 作为产品约束和对标依据 |
| `docs/superpowers/specs/2026-07-10-agent-os-unified-workbench-i18n-design.md` | 统一 Workbench / 多语言 / SceneSpec | 作为当前 Web 视觉和交互基线 |
| `apps/api_server/preview-zh.html` | 静态场景设计稿 | 作为视觉试验场，不是真实运行时 |
| `apps/api_server/index.html` | 当前真实 Task Workspace | 作为功能和 API 行为真相 |
| `docs/superpowers/specs/2026-07-18-mandate-responsibility-view-design.md` | Mandate 责任投影 | 作为首屏责任信息的真实来源 |
| `docs/superpowers/specs/2026-08-11-agent-os-native-surface-runtime-program-design.md` | 原生桌面 / Workspace Canvas | 作为未来桌面壳和跨端协议方向 |
| `main:apps/macos/renderer`（当前工作分支未检出） | React/Tauri Canvas 真实实现候选 | 作为跨端协议和面板边界参考，不能把当前 scaffold 直接当成完成 UI |

结论：历史稿件不应继续并列演进。需要一份产品级的合并基线，旧文档保持历史事实，不回写成互相竞争的“当前设计”。

## 2. 设计演进的真实问题

### 2.1 早期研究控制台

早期方案把 Chat、DAG、Goals、Interventions、Log 并列放在首屏。这适合研究人员观察内部模块，不适合普通用户完成任务。它会迫使用户自己拼接“目标、计划、证据、动作”的关系。

### 2.2 聊天优先修正稿

ADR-0040 正确地发现了上下文纠正和渐进披露问题，但“聊天作为唯一主容器”仍然过度依赖用户的对话认知。对于长任务，聊天记录不是责任、承诺、Outcome 或 Recovery 的可靠主视图。

### 2.3 统一 Workbench 静态预览

2026-07-10 的 Workbench 已经解决了最重要的壳层问题：统一产品身份、Workspace Profile、Space、Ask/Work、ScenePreset、任务列表、证据、审批、响应式布局和多语言。它是当前最有价值的视觉资产。

但它仍然是 fixture 驱动的静态场景，不能承担真实 Task/Run/Outcome 的最终显示语义。

### 2.4 当前实时工作台

`index.html` 具备真实 API 路径、Task Workspace、Provider、Patch Review、Evidence 和 Mandate Responsibility，但视觉上仍是“配置区 + 任务表单 + 流程条 + 详情页”的工程型页面。

它的优点是可信，缺点是首屏没有先回答“现在由系统负责什么、用户要决定什么、为什么停住”。

### 2.5 原生桌面 Canvas

2026-08-11 的 Native Surface 方案正确地把桌面端定位为同一 Runtime 的 Canvas，而不是第二个产品。它把 Shell、面板、协议、事件流、通知、托盘、恢复和跨端一致性放在一起，是长期架构方向。

但十种面板和远程 Worker 不应在当前首版 UI 中全部显性化，否则会把未来架构误投影为当前用户负担。

补充核对了 `main` 上的实际 React/Tauri renderer：它已经有 `SurfaceClient`、Ask/Observe、Approval、Diff、Files、Terminal、Conflict、LayoutTemplate 和闭合集面板测试。这证明跨端协议和组件边界已经有实现资产；同时它当前的 `App.tsx` 仍是开发 scaffold，默认布局把十个面板按网格平铺，不能直接作为视觉成品。合并策略应是“复用协议/面板纯逻辑，重做壳层和首屏编排”，而不是把静态预览或 scaffold 任一方整体替换另一方。

## 3. 合并后的唯一产品模型

```text
Agent OS Shell
  -> Space / Mandate
  -> Task responsibility
  -> Ask or Work
  -> Plan / Activity / Review
  -> Evidence / Outcome
  -> Help / Recovery
```

### 3.1 首屏唯一中心：当前责任

首屏中心对象不是 Chat、Agent 列表、DAG 或 WorkflowGraph，而是：

- 当前 Mandate / Space；
- 当前 Task 要达成的结果；
- 当前状态：`TRACKED / NEEDS_ATTENTION / UNKNOWN / DONE_VERIFIED`；
- 当前阶段和下一步；
- 需要用户决定的事项；
- 支持当前判断的证据和边界。

### 3.2 Chat 的新位置

Chat 保留，但从“主容器”降为两种投影：

1. `Ask` 的轻量输入和回答流；
2. `Activity` 中可折叠的自然语言解释。

Chat 不承载权威 Task 状态、批准状态、Outcome 或恢复事实。聊天内容可以解释系统，但不能替代系统事实。

### 3.3 四种工作姿态的收敛

Native Surface 方案提出 `Work / Ask / Automate / Observe` 四种姿态。首版 UI 只把前两者做成一级交互：

- `Ask`：只读、来源优先、可以升级为 Work；
- `Work`：持久 Task、计划、工具、审批、证据、Outcome；
- `Observe`：先作为 Workbench 首页中的责任摘要，不单独做复杂导航；
- `Automate`：暂留为后续入口，不能用静态按钮制造已实现错觉。

这样保留 Native Surface 的长期方向，又避免当前用户面对四个几乎空的产品模块。

## 4. 统一桌面/Web 信息架构

```text
┌────────────────────────────────────────────────────────────────┐
│ Agent OS · Space / Mandate        当前状态   Provider  帮助/设置 │
├──────────────┬────────────────────────────────┬────────────────┤
│ 导航栏        │ 当前责任                         │ 证据与边界       │
│ Space         │ Task 标题                       │ 来源             │
│ 最近任务      │ 目标结果                         │ 新鲜度/冲突       │
│ 搜索          │ 当前阶段                         │ 权限/审批         │
│ Ask / Work    │ 下一步                           │ 变更/回滚         │
│               │ 用户待决定事项                   │ Outcome          │
├──────────────┴────────────────────────────────┴────────────────┤
│ Ask / Work Command Bar                                        │
└────────────────────────────────────────────────────────────────┘
```

### 中栏主视图顺序

1. `Responsibility header`：当前任务、目标和状态；
2. `Attention strip`：只显示真正需要用户处理的事项；
3. `Current step`：当前行动、等待原因或验证状态；
4. `Plan / Activity / Outcome`：按当前阶段选择性展开；
5. `Command bar`：Ask、纠正、继续、暂停、升级为 Work。

### 右栏渐进披露顺序

1. 证据摘要；
2. 具体来源和时间；
3. 权限、Policy、Approval；
4. Diff、ActionContract、Receipt；
5. 原始 Trace / JSON 作为高级详情。

## 5. 旧设计如何取舍

| 设计元素 | 决策 | 原因 |
| --- | --- | --- |
| 四面板研究控制台 | `RETIRE_FROM_PRIMARY_UI` | 认知负荷高，适合诊断模式而非日常模式 |
| Chat-first | `MERGE_AS_ASK_ACTIVITY` | 保留表达效率，取消其作为长期真相根的地位 |
| Workspace Profile | `KEEP` | 是冷启动与权限边界的有效上下文，不是人格切换 |
| ScenePreset | `KEEP_AS_SOFT_PRESET` | 可改善冷启动，但不能扩权或静默改 Workflow |
| SceneSpec / Component Registry | `KEEP_AS_RENDERING_BOUNDARY` | 保证可组合 UI 不变成任意模型生成前端 |
| Mandate Responsibility View | `PROMOTE_TO_PRIMARY` | 它直接回答用户“系统正在负责什么” |
| DAG / Ontology Explorer | `PROGRESSIVE_DISCLOSURE` | 仅在关系、计划或诊断需要时打开 |
| Approval / Correction | `KEEP_AND_MOVE_TO_CONSEQUENCE` | 动作附近必须能批准、拒绝、纠正，不只放全局工具栏 |
| Outcome / Evidence | `PROMOTE` | 完成必须落到可验证结果，不接受自然语言自报完成 |
| 十种 Canvas 面板 | `CLOSED_SET_BEHIND_STAGE` | 作为未来可组合能力，不在首版全部显性化 |
| Automate / Worker / Sync | `RESERVE_SURFACE` | 先保留协议和状态位置，暂不伪装成现成能力 |

## 6. 视觉语言合并

### 保留

- `preview-zh.html` 的浅色、低饱和、紧凑工作台风格；
- 左侧固定导航、顶部状态栏、中央任务区、右侧抽屉；
- 绿色表示已验证，琥珀表示等待/审批，红色表示失败/需要纠正，蓝色表示当前焦点；
- 8px 以下圆角、稳定栅格、键盘优先、响应式折叠；
- 证据详情、审批卡、纠正抽屉和 `Ask -> Work` 连续性。

### 删除或降权

- 研究型拓扑图、关系图、指标图同时占据首屏；
- 将“Agent 协作”显示为角色卡片堆叠；
- 以大型运行动画替代真实阶段和证据；
- 将 Provider、模型、密钥配置放在默认首屏；
- 把静态 fixture 的示例状态混在真实 Task 状态中。

### 统一状态词汇

| 用户看到的中文 | 内部语义 |
| --- | --- |
| 已跟踪 | `TRACKED` |
| 需要处理 | `NEEDS_ATTENTION` |
| 状态未知 | `UNKNOWN` |
| 已验证完成 | `DONE_VERIFIED` |
| 等待审批 | `WAITING_APPROVAL` |
| 等待外部事件 | `WAITING_EVENT` |
| 外部效果待对账 | `UNKNOWN_REQUIRES_REVIEW` |

不可把 `RUNNING` 直接翻译成“已完成中”，也不可把 `UNKNOWN` 降级成普通错误。

## 7. 三端统一而不强求同形

### Web

Web 是首个真实 UI 入口：验证责任视图、Task、Review、Evidence、Recovery 和响应式布局。`index.html` 提供行为基线，`preview-zh.html` 提供视觉基线，最终应合并为一套组件和一套状态语义。

### 桌面端

桌面端沿用同一 Shell 和 Surface Protocol，增加窗口、托盘、通知、快捷键、恢复和多窗口语义。它不拥有第二套 Task、Approval 或 Evidence 状态。

### CLI

CLI 不需要复制三栏视觉，而要提供同样的对象顺序：

```text
status -> 当前责任/状态/待处理事项
ask    -> 只读回答 + 来源
work   -> 创建持久 Task + 预期结果
review -> 精确动作 / Diff / Approval
resume -> 原 Task/Run 恢复与对账
```

## 8. 当前最优实施顺序

1. 把 `preview-zh.html` 的视觉结构拆成稳定 Shell、责任头、状态条、证据抽屉和命令栏；
2. 把 `index.html` 的真实 Task/Provider/Review/API 行为接入这些结构；
3. 先实现 `Responsibility / Attention / Outcome` 首屏，隐藏不影响当前任务的工程设置；
4. 增加 `Plan / Activity / Evidence / Outcome` 四个渐进披露视图；
5. 将 CLI 状态词汇与 Web 同步；
6. 再以同一 Surface Protocol 实现 Tauri Canvas；
7. 最后再接入 Observe、Automate、Worker 和多 Agent 面板。

## 9. 设计验收

首屏合并设计必须通过以下检查：

- 10 秒内能说出当前 Task 的目标、阶段和状态；
- 2 次操作内找到下一步和待自己决定的事项；
- 能区分“建议 / 已批准 / 已执行 / 已验证”；
- 失败、中断和未知外部效果有不同视觉与文案；
- 不需要用户重述 Mandate、上下文和已发生的结果；
- Web、桌面、CLI 切换后 Task/Run/Approval/Evidence 身份一致；
- 研究型面板不进入默认首屏，但高级用户仍可通过渐进披露访问；
- 静态场景和实时状态不会被用户误认为同一证据等级。

## 10. 设计状态边界

这份合并基线只关闭设计方向，不关闭产品实现、发布、企业部署、持续责任、一般智能或 `Autonomy(S,E,O,V,T)` 主张。所有真实能力仍需通过现有 Product Track 合同、失败路径、证据和独立验证关闭。
