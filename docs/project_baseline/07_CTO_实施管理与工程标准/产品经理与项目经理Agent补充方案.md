# 产品经理与项目经理 Agent 补充方案

> 日期：2026-06-01  
> 角色视角：CTO  
> 结论：现有资料足够支撑战略、架构和工程治理，但开工前仍需要 Product Manager Agent 和 Project Manager Agent 补齐产品执行与项目交付层。

## 1. 当前文档充分性判断

当前文档体系已经比较清晰、深入、结构化，覆盖了：

- 产品战略和长期北极星。
- 技术 PRD 和总体架构。
- MVP 边界和阶段性落地方案。
- 业务问题、golden query、golden business loop。
- CTO 决策简报。
- 90 天研发执行方案。
- 工程 SOP、风险控制、Code Agent 治理。
- AI 自动编码工作流。
- 架构师 Agent 和 CTO 审批流程。
- Agent/Skill 注册表。
- `.agent`、`code_index.md`、ADR、repo scaffold。

这些足以作为开工前的 **战略、架构、工程治理基线**。

但如果目标是让团队和 Code Agent 直接进入产品开发，还缺三个执行层资产：

1. 细化 PRD：用户角色、核心流程、功能列表、页面/接口/状态、验收标准。
2. Backlog：Epic、Story、Task、优先级、依赖、DoD、测试映射。
3. 项目管理：里程碑、Sprint、RACI、风险台账、状态报告和交付节奏。

因此需要新增 Product Manager Agent 和 Project Manager Agent。

## 2. Product Manager Agent

### 2.1 角色定位

Product Manager Agent 负责把战略 PRD 和业务样本拆成可开发的产品需求，不负责架构实现，也不直接写代码。

它在流程中的位置：

```text
Product Requirements Agent
  -> Product Manager Agent
  -> Project Manager Agent
  -> Context Agent
  -> Architecture Agent
  -> CTO Gate
```

### 2.2 工程目标

- 把业务目标转成可验收的功能需求。
- 把 30 个业务问题映射到 MVP 功能。
- 把 3 条 golden loop 拆成用户流程、页面、接口、状态和验收标准。
- 定义功能优先级和不做事项。
- 为架构师 Agent 提供清晰需求输入。

### 2.3 输入

- CEO/CTO 指令。
- 技术 PRD。
- 阶段性落地方案。
- MVP 技术选型文档。
- 业务问题样本。
- golden query。
- golden business loop。
- 竞品和商业化材料。

### 2.4 输出

```text
docs/product/
  PRD-MVP.md
  feature_map.md
  user_stories.md
  acceptance_criteria.md
  workflow_specs/
    roi_diagnosis.md
    hit_content_discovery.md
    daily_report.md
```

核心输出结构：

| 输出 | 内容 |
|---|---|
| `PRD-MVP.md` | MVP 背景、目标用户、核心场景、功能范围、非目标 |
| `feature_map.md` | 功能树、P0/P1/P2、依赖关系 |
| `user_stories.md` | 用户故事、角色、业务价值 |
| `acceptance_criteria.md` | 可测试验收标准 |
| `workflow_specs/*.md` | 每条业务闭环的输入、输出、状态、异常、数据和行动提案 |

### 2.5 边界条件

Product Manager Agent 不可以：

- 承诺 MVP 外能力。
- 将“完整 OS”写成第一版需求。
- 跳过 EvidenceChain、SQL Safety、Eval、Trace。
- 为了产品体验要求 R4/R5 自动执行。
- 直接决定架构和数据模型。

必须升级 CTO：

- 新增 P0 功能。
- 删除质量门禁。
- 修改第一阶段边界。
- 引入高风险写操作。
- 影响销售承诺或交付范围。

## 3. Project Manager Agent

### 3.1 角色定位

Project Manager Agent 负责把 PRD、架构方案和工程任务组织成可交付计划，关注排期、依赖、风险、状态和交付节奏，不直接写代码。

它在流程中的位置：

```text
Product Manager Agent
  -> Project Manager Agent
  -> Architecture Agent
  -> CTO Gate
  -> Implementation Agents
  -> Project Manager Agent 更新状态
```

### 3.2 工程目标

- 把 PRD 拆成 Epic、Story、Task。
- 形成 90 天 backlog 和 Sprint 计划。
- 管理依赖、阻塞、风险和资源。
- 维护交付状态和周报。
- 确保每个任务有 owner、验收标准、测试/eval 绑定。

### 3.3 输入

- PRD-MVP。
- Architecture Design Brief。
- CTO approval。
- Agent registry。
- CI/eval 报告。
- PR 状态。
- 风险清单。
- 业务评测会结论。

### 3.4 输出

```text
docs/project/
  roadmap_90d.md
  backlog.md
  sprint_plan.md
  dependency_map.md
  risk_register.md
  raci.md
  weekly_status/YYYY-MM-DD.md
```

核心输出结构：

| 输出 | 内容 |
|---|---|
| `roadmap_90d.md` | 90 天目标、里程碑、退出标准 |
| `backlog.md` | Epic/Story/Task、优先级、owner、DoD |
| `sprint_plan.md` | Sprint 目标、任务、容量、验收 |
| `dependency_map.md` | 模块、团队、数据、外部系统依赖 |
| `risk_register.md` | 风险、概率、影响、owner、缓解计划 |
| `raci.md` | 角色职责矩阵 |
| `weekly_status/*.md` | 进度、风险、阻塞、下周计划 |

### 3.5 边界条件

Project Manager Agent 不可以：

- 为了赶进度降低测试和 eval 门槛。
- 自动扩大 scope。
- 绕过 CTO Gate。
- 让多个 Agent 并行修改同一高风险模块。
- 把未审批需求排入 Sprint。

必须升级 CTO：

- 关键里程碑延期。
- P0 功能范围变化。
- CI/eval 长期不达标。
- 出现高风险安全/数据/权限问题。
- 资源不足影响 90 天目标。

## 4. 开工前必补交付物

正式开工写代码前，Product Manager Agent 和 Project Manager Agent 至少要产出：

1. `docs/product/PRD-MVP.md`
2. `docs/product/feature_map.md`
3. `docs/product/acceptance_criteria.md`
4. `docs/project/backlog.md`
5. `docs/project/roadmap_90d.md`
6. `docs/project/sprint_plan.md`
7. `docs/project/risk_register.md`
8. `docs/project/raci.md`

这些文档完成后，再由 Architecture Agent 为第一批 P0 功能输出 Architecture Design Brief。

## 5. 最小开工标准

可以进入第一批代码实现的条件：

- P0 功能清单明确。
- 每个 P0 功能有验收标准。
- 每个 P0 功能绑定测试或 eval。
- 每个任务有 owner。
- 架构师 Agent 已完成第一批 Architecture Brief。
- CTO Gate 已批准。
- repo scaffold 已确认。
- CI 最小门禁已定义。

否则只能继续做需求拆解、架构设计和脚手架，不应进入大规模代码生成。

