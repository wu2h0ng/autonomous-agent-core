# Agent Surface UI 信息放置规则

> 日期：2026-08-15  
> 主标签：`U/P`  次标签：`A`  
> 状态：`DESIGN_BASELINE / NOT_IMPLEMENTED`

## 1. 总规则

UI 位置按四个问题决定：

1. 用户是否需要持续知道它？
2. 用户是否要在当前任务中据此做决定？
3. 信息是否需要和当前对象保持上下文？
4. 这个动作是否足以打断用户？

对应关系：

```text
持续导航       -> 侧边栏
当前责任/阶段   -> 主区域
权威与证据     -> 右侧栏或详情抽屉
高风险决定     -> 对话框/审批卡
低风险反馈     -> Toast / 状态条
异步变化       -> 通知中心
大范围管理     -> 独立页面
```

核心原则：**侧边栏不解释，主区域不藏关键决定，对话框不承载阅读，Toast 不承载责任。**

## 2. 侧边栏放什么

### 应放

侧边栏承担“我在哪里、我负责哪些工作、我可以切到哪里”：

| 内容 | 放置方式 | 说明 |
| --- | --- | --- |
| Agent OS 产品入口 | 顶部品牌区 | 点击回到当前 Space 总览，不改变 Task |
| Workspace Profile | 顶部切换器 | Personal / Developer / Organization，只改变上下文默认值 |
| Space | Profile 下方 | 当前工作边界、仓库/数据源/文件集合 |
| Ask / Work | 紧邻 Space | 一级交互契约，不做成不同产品 |
| 新建 Task | 明确主按钮 | 侧边栏唯一稳定的创建入口 |
| 最近 Task | 中段列表 | 显示标题、状态点、最近更新时间 |
| 需要处理 | 可选队列入口 | 只聚合 `NEEDS_ATTENTION`、审批和恢复事项 |
| 搜索 Task / Space | 最近任务上方 | 搜索对象，不搜索所有日志 |
| 设置 / Provider 状态 | 底部 | 只显示摘要，详情进入独立设置页 |

### 不应放

- 当前 Task 的完整计划、证据和日志；
- 所有 Agent、Tool、Skill、Connector 的角色卡；
- 高频执行按钮，如批准、运行、回滚；
- 详细 Provider 配置和 API Key 表单；
- 研究型 DAG、Ontology、模型拓扑；
- 每个任务的所有历史事件。

理由：侧边栏是低频导航空间。把状态、执行和诊断内容堆进去，会让用户无法区分“切换对象”和“改变对象”。

## 3. 顶部栏放什么

顶部栏是当前作用域的稳定上下文，不是工具栏仓库。

### 左侧

- 当前 Space 名称；
- 当前 Mandate 的短标题或状态；
- 当前 Task 标题；
- 返回上一级的路径。

### 中间

只在有必要时显示一个状态胶囊：

`已跟踪`、`运行中`、`等待审批`、`需要处理`、`状态未知`、`已验证完成`。

不要同时显示多个竞争状态。优先显示对用户下一步最有影响的状态。

### 右侧

- Runtime / Provider 连接摘要；
- 当前 Task 的暂停/继续；
- 通知中心；
- 帮助、快捷键和设置入口。

高风险动作不应该只靠顶部按钮完成，必须在当前动作上下文内再次呈现。

## 4. 主区域放什么

主区域承载用户当前真正要理解或决定的内容，优先级从上到下固定。

### 4.1 Responsibility Header

首屏第一块回答：

- 当前 Mandate / Task 是什么；
- 预期结果是什么；
- 当前状态是什么；
- 当前阶段是什么；
- 下一步是什么。

这是所有用户进入 Task 后首先看到的内容，不能被聊天记录、设置表单或日志挤到下面。

### 4.2 Attention Strip

只在存在明确动作时出现：

- 等待用户审批；
- 需要补充信息；
- 发现环境变化；
- 证据冲突；
- 外部效果待对账；
- 任务失败但可恢复。

它必须说明“为什么现在需要你”，并直接提供下一步入口。

### 4.3 Current Step

显示当前动作或等待原因：

- 正在收集什么；
- 已经产生什么提案；
- 正在验证什么；
- 为什么暂停；
- 哪个事件或权限尚未满足。

不要把全部工具调用原样堆出；默认显示人类可理解摘要，原始事件进入 Activity 详情。

### 4.4 Plan / Activity / Outcome

这三个视图属于主区域的阶段化内容，不做成三个同时争夺注意力的永久面板：

- `Plan`：任务尚未执行、正在重规划或用户需要审查计划时显示；
- `Activity`：运行中显示，回答“发生了什么”；
- `Outcome`：终态或阶段性结果显示，回答“结果是什么、证据在哪里、下一步是什么”。

建议顺序：`Outcome -> Activity -> Evidence -> Plan`。只有当前阶段相关的视图默认展开。

## 5. 右侧栏与详情抽屉放什么

右侧区域负责“可追溯性”，不负责持续推进任务。

### 右侧栏适合

在桌面宽屏下固定显示：

- 证据摘要；
- 来源、时间、新鲜度；
- 当前冲突；
- 权限和 Policy 摘要；
- Approval 状态；
- 变更影响和回滚可用性。

右侧栏应保持窄而稳定，避免变成第二个主工作区。

### 详情抽屉适合

当用户主动查看时展开：

- 单条 Evidence 的 lineage；
- ActionContract 和精确 digest；
- Diff 细节；
- 完整 Event / Trace；
- HelpRequest 的背景和已尝试步骤；
- Outcome evaluator 的输入和输出。

抽屉不会改变当前任务上下文，也不应该承担跨对象导航。

## 6. 对话框只放什么

对话框只用于“需要用户明确确认，且继续操作会产生显著后果”的情况。

### 应放

1. **具体外部效果审批**：目标、影响、权限、证据、精确动作摘要。
2. **不可逆或高风险变更确认**：删除、发布、发送、写入长期知识、跨系统操作。
3. **恢复分歧选择**：外部效果未知时，在“停止并对账 / 提供信息 / 终止任务”等选项中选择。
4. **切换会丢失当前草稿**：仅当确实会丢失用户输入或未提交纠正。
5. **首次授权**：文件夹、Provider、连接器等权限授权。

### 不应放

- 普通回答和证据阅读；
- 长篇任务日志；
- 完整计划编辑器；
- 所有设置；
- 低风险的暂停/继续；
- 普通错误详情；
- “Agent 正在思考”的动画。

对话框内容应是“一个决定”，不是一个迷你页面。超过一个决定就应回到主区域或独立页面。

## 7. Command Bar 放什么

Command Bar 是用户表达意图和继续任务的地方，不是万能命令终端。

### Ask 状态

- 询问当前 Space、Task、证据和结果；
- 快速引用来源；
- `升级为 Work`；
- 不显示执行类按钮。

### Work 状态

- 继续当前任务；
- 纠正目标、约束或计划；
- 请求重试/恢复；
- 打开 Review；
- 暂停或结束任务。

输入框附近应显示当前对象和作用域，例如：

`在“修复重复扣款”任务中继续工作…`

避免用户误以为输入会创建一个全新的无上下文对话。

## 8. 通知、Toast 与状态条

### Toast

只放低风险、短生命周期反馈：

- 已复制引用；
- 已保存本地偏好；
- 已切换 Space；
- 已提交非破坏性纠正。

Toast 不得承载失败原因、审批请求、外部效果结果或唯一的成功证据。

### 通知中心

放异步但需要回看的事件：

- 后台 Task 完成；
- HelpRequest；
- Approval 请求；
- 外部环境变化；
- Worker 离线；
- Sync 冲突；
- `UNKNOWN_REQUIRES_REVIEW`。

通知点击后必须回到对应 Task/Run，而不是打开一个孤立消息详情。

### 状态条

放当前连接和系统级健康：

- Runtime 是否在线；
- Provider 是否已配置；
- 当前 Surface Protocol 是否匹配；
- 是否存在未处理的同步或权限问题。

不要用状态条表达具体 Task 的业务结论。

## 9. 独立页面放什么

只有需要跨 Task、跨 Space 或长时间管理的内容才进入独立页面：

- Task / Outcome 总览；
- Knowledge / Evidence 资产管理；
- Provider / Capability / Permission 设置；
- Automations；
- Workspace / Organization 管理；
- 审计与高级 Trace；
- UI / ScenePreset 管理。

独立页面不是把主界面内容复制一遍，而是提供筛选、批量查看、生命周期管理和导出。

## 10. 对象到位置的最终映射

| 对象 | 默认位置 | 用户主动查看时 | 主要动作位置 |
| --- | --- | --- | --- |
| Space / Profile | 侧边栏 + 顶部栏 | Space 页面 | 切换器 |
| Mandate | 顶部栏 + Responsibility Header | 责任详情页 | Mandate 管理页 |
| Task | 侧边栏列表 + 主区域 | Task 页面 | 主区域 Command Bar |
| Task 状态 | 顶部状态胶囊 + 主区域 | 状态详情 | 当前 Task |
| Plan | 主区域 | Plan 详情 | Plan 审查区 |
| Activity | 主区域摘要 | Activity 抽屉 | 当前 Task |
| Evidence | 右侧摘要 | Evidence 抽屉/页面 | Evidence 行附近 |
| Approval | 主区域 Attention Strip | Approval 对话框 | 具体动作附近 |
| Correction | Command Bar + 当前动作附近 | Correction 抽屉 | 当前 Task |
| Recovery | Attention Strip | Recovery 对话框/详情 | 当前 Task |
| HelpRequest | Attention Strip + 通知中心 | Help 详情 | 求助决策附近 |
| Outcome | 主区域终态 | Outcome 页面 | Outcome 区 |
| Diff | 主区域 Review | Diff 抽屉 | 提案/动作附近 |
| Provider / 权限 | 顶部摘要 | 设置页面 | 首次授权对话框 |
| DAG / Ontology | 不进首屏 | 高级详情页 | 当前解释/假设附近 |
| Agent / Tool | 不做角色列表 | Activity / Capability 详情 | 当前步骤 |

## 11. 三端映射

### Web

使用三栏桌面布局；窄屏时将右栏折叠为抽屉，侧边栏变成顶部菜单。对话框仅保留审批、授权和恢复分歧。

### 桌面端

沿用 Web 的信息层级，增加：

- 全局快捷键打开 Command Bar；
- 通知中心和系统通知；
- 托盘显示需要处理的 Task 数量；
- 多窗口只共享同一 Task/Run 真相；
- 原生文件夹授权不进入普通表单。

### CLI

CLI 用同一对象顺序表达，不模拟视觉布局：

```text
status  -> Space / Mandate / Task 状态 / 待处理事项
ask     -> 只读回答 / 来源
work    -> 目标 / 预期结果 / Task ID
review  -> 动作 / Diff / Approval
resume  -> Task/Run / 已确认 / 未确认 / 下一步
```

## 12. 放置反模式

- 侧边栏放“批准”“运行”“回滚”：导航和执行边界混淆；
- 弹窗里放完整日志：用户无法比较决定，只能被迫阅读；
- Toast 显示“任务完成”：没有证据、不可追溯；
- 顶栏同时显示 Mandate、Task、Run、Provider、Model、Token、Worker 全部状态：状态过载；
- 主区域默认展开 DAG、Agent topology、Terminal、Raw JSON：研究工具取代用户任务；
- 通知中心只显示消息，不绑定 Task/Run：异步信息无法回到责任上下文；
- Ask 和 Work 使用两个独立历史：用户升级任务后必须重建上下文。

## 13. 首版落地顺序

1. 先把 `index.html` 的当前 Task、Mandate Responsibility、Review、Evidence 映射到上述位置。
2. 用 `preview-zh.html` 的视觉资产重做主区域和右侧抽屉，而不是继续扩展静态面板。
3. 把 Provider 设置从默认首屏移入设置/首次授权流程。
4. 为 `NEEDS_ATTENTION / UNKNOWN / WAITING_APPROVAL / DONE_VERIFIED` 建立统一状态条和文案。
5. 再把同一信息层级迁移到 `main` 分支的 React/Tauri renderer。
6. 最后补通知中心、Observe、Automate 和批量管理页面。
