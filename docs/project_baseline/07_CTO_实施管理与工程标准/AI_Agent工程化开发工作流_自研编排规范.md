# AI Agent 工程化开发工作流：自研编排规范

> 日期：2026-06-01  
> Owner：CTO  
> 状态：Approved baseline  
> 适用范围：AI Native Business Data Agent OS 的全部 Agent 驱动开发任务  
> 配套独立辅助工程：`ai-agent-engineering-workflow/`
> 配套机器可读文件：`ai-agent-engineering-workflow/workflow.yaml`

## 0. 边界声明

`AI Agent 工程化开发工作流` 是辅助产品开发的工程工具，不是
`AI Native Business Data Agent OS` 的产品运行时。

必须保持以下边界：

- 工作流工程根目录：`ai-agent-engineering-workflow/`
- 产品实现根目录：`ai-native-business-data-agent-os/`
- 工作流可以读取产品文档、生成 `.agent_runs`、调用质量门禁命令。
- 工作流不得被 `ai-native-business-data-agent-os` 的 runtime、OS Core、API Server、Workspace UI import。
- 产品不得依赖工作流包才能启动、测试或部署。
- 工作流可以作为未来 Agent OS 产品能力的参考原型，但任何产品化都必须重新走 ADR 和架构评审。

## 1. 为什么必须自研工作流

通用 Agent、IDE、n8n、CI/CD 只能解决局部问题，不能直接保证本项目需要的工程结果。

本项目的特殊要求是：

- 必须防止伪实现。
- 必须保证新增代码被真实入口调用。
- 必须保证 Contract、SQL Safety、EvidenceChain、Eval、Trace 不被绕过。
- 必须让不同能力水平的 Agent 在同一套门禁下工作。
- 必须把失败案例转成项目记忆和 eval。
- 必须支持后续产品自身的 Agent OS 能力沉淀。

因此自研工作流的目标不是“让 Agent 更自由”，而是“让 Agent 在可审计状态机里工作”。

## 2. 总体状态机

```text
intake
  -> classify
  -> context_pack
  -> plan
  -> architecture_gate
  -> contract_gate
  -> implement
  -> self_check
  -> quality_gate
  -> review_gate
  -> integration_gate
  -> memory_update
  -> done
```

失败路径：

```text
any_state
  -> blocked
  -> human_decision
  -> retry | rescope | reject | defer
```

## 3. 工作流输入

每个任务必须先生成 `Goal Card`。

```yaml
goal_card:
  objective: string
  business_value: string
  scope:
    include: []
    exclude: []
  risk_level: R0-R5
  owner: string
  required_outputs: []
  required_checks: []
  max_agent_retries: 2
```

禁止没有 Goal Card 直接进入实现。

## 4. 状态定义

### 4.1 intake

目标：把用户请求转成可执行任务。

输入：

- 用户请求。
- 当前项目状态。

输出：

- `goal_card.md`

检查：

- 是否有明确目标。
- 是否有非目标。
- 是否能在当前阶段执行。
- 是否需要拆分。

### 4.2 classify

目标：决定任务类型、风险等级和 Agent 路由。

任务类型：

```text
docs
contract
architecture
backend
frontend
eval
security
workflow
release
bugfix
```

风险升级条件：

- 改 contract。
- 改 SQL Safety。
- 改 EvidenceChain。
- 改 Eval。
- 改 auth/permission/security。
- 改 model routing。
- 改 Provider/Action Connector。
- 改 deployment/release。
- 触达 R4/R5 action。

输出：

- `task_classification.json`

### 4.3 context_pack

目标：给 Agent 最小必要上下文，避免全局无意识和上下文污染。

必须包含：

- 已阅读文件列表。
- 相关 source-of-truth。
- 相关模块。
- 相关测试。
- 当前假设。
- 明确未读的风险文件。

输出：

- `context_pack.json`

### 4.4 plan

目标：让 Agent 在实现前说明具体改动。

输出：

- `implementation_plan.md`

必须回答：

- 要改哪些文件。
- 为什么改这些文件。
- 真实 entry point 是什么。
- 哪些 tests/eval 会证明有效。
- 失败路径怎么处理。
- 是否需要更新文档/索引。

### 4.5 architecture_gate

目标：阻止未经批准的架构变更。

触发条件：

- medium/high complexity。
- 跨模块。
- 新 runtime capability。
- 新 API/UI integration。
- 新外部依赖。

输出：

- `architecture_brief.md`
- `cto_approval.md` 或 `architecture_gate_result.json`

未通过不得进入实现。

### 4.6 contract_gate

目标：所有实现先明确 contract。

检查：

- 是否改 dataclass/schema/API。
- 是否影响字段语义、单位、可空性、状态枚举。
- 是否需要 compatibility test。
- 是否需要 migration plan。

输出：

- `contract_impact_report.md`

### 4.7 implement

目标：执行最小可验证实现。

规则：

- 小步提交。
- 不做无关重构。
- 不删除测试绕过失败。
- 不把 staged seam 伪装成完成能力。
- 新模块必须有真实入口或显式 staged 标记。

输出：

- patch。
- `patch_manifest.json`

### 4.8 self_check

目标：Agent 自查伪实现。

必须回答 Reality Gate：

- Entry point。
- Contract。
- Failure mode。
- Test validity。
- Integration。
- Boundary。
- Observability。

输出：

- `self_check_report.md`

### 4.9 quality_gate

目标：机器门禁。

当前必跑：

```text
python -m ruff check --no-cache .
python -m ruff format --check --no-cache .
python -m unittest discover -t . -s tests -p "test_*.py"
```

按需追加：

- eval suite。
- UI smoke。
- security scan。
- import boundary scan。
- type check。

输出：

- `quality_report.md`

### 4.10 review_gate

目标：人类或 Review Agent 做工程审查。

必须检查：

- 根因是否正确。
- 代码是否被真实调用。
- 测试是否不是自证。
- 是否破坏架构边界。
- 是否绕过安全/证据/eval。
- 是否更新项目记忆。

输出：

- `review_report.md`

### 4.11 integration_gate

目标：判断能否进入主线或下一阶段。

通过条件：

- 所有 required checks 通过。
- reviewer 无 blocker。
- 文档和索引更新。
- 风险已接受或关闭。

输出：

- `integration_decision.md`

### 4.12 memory_update

目标：把重要变更和失败经验沉淀。

更新对象：

- `code_index.md`
- `.agent`
- `AGENTS.md`
- ADR
- architecture review
- eval cases
- runbook
- failure knowledge

输出：

- `memory_update_report.md`

## 5. Agent 路由

| 任务类型 | 主 Agent | 必须协作 | Gate |
|---|---|---|---|
| docs | Documentation Agent | CTO optional | review |
| contract | Contract Agent | Architecture, Eval | contract + CTO |
| architecture | Architecture Agent | CTO | CTO approval |
| backend | Backend Core Agent | Contract, Eval | quality + review |
| frontend | Frontend Workspace Agent | Contract, API | UI smoke + review |
| eval | Eval Agent | Product, Backend | eval review |
| security | Security Agent | CTO | security review |
| workflow | CTO / Workflow Agent | All owners | CTO approval |
| release | Release Agent | QA, Security | release gate |
| bugfix | Implementation Agent | Review Agent | root-cause gate |

## 6. 自动化等级

| 等级 | 范围 | 当前允许 |
|---|---|---|
| A0 | 只读分析 | 是 |
| A1 | 本地分支实现 + 测试 | 是 |
| A2 | 自动开 PR | 是，需人工 review |
| A3 | docs/test-only 自动合并 | 暂缓 |
| A4 | 自动部署测试环境 | 后续 |
| A5 | 自动生产发布 | 禁止 |

## 7. 重试与终止规则

Agent 最多自动重试 2 次。

立即终止并请求人工判断：

- 同一测试失败 2 次仍未定位根因。
- 需要 secret 或生产权限。
- 触达 R4/R5。
- 需要破坏性文件操作。
- 出现 contract 冲突。
- 输出和架构文档冲突。

## 8. 产物目录

推荐每次运行生成：

```text
.agent_runs/{run_id}/
  goal_card.md
  task_classification.json
  context_pack.json
  implementation_plan.md
  architecture_brief.md
  contract_impact_report.md
  patch_manifest.json
  self_check_report.md
  quality_report.md
  review_report.md
  integration_decision.md
  memory_update_report.md
  logs/
```

## 9. MVP 执行策略

当前阶段先实现“文档化 + 机器可读配置 + 手动执行”的工作流。

路线：

```text
V0: Markdown + YAML workflow baseline          [done]
V1: Python Agent Runner reads YAML and creates .agent_runs  [done]
V2: Local task execution + quality gate        [done 2026-06-11, run 20260611-v2-local-quality-gate]
V3: GitHub PR automation                       [done 2026-06-11, run 20260611-v3-pr-automation; status + pr commands, automation ceiling A2]
V4: n8n notification / approval integration    [notification integration live 2026-06-12, runs 20260611-v4-ci-and-notify + 20260612-v4-n8n-instance: CI gate + notify command + n8n 2.25.7 instance with workflow AgentRunStatus01 (config in n8n/); approval flow + outbound channel pending Feishu/DingTalk/email credentials]
V5: Productized internal workflow runtime      [ADR-0011 accepted 2026-06-12: re-implement in os_core when trigger met (roadmap need + 2 internal consumers); dormant until then]
```

## 10. CTO 结论

批准自研 AI Agent 工程化开发工作流。

短期它是项目治理工具；中期它会成为 Agent OS 自身的一个可产品化能力原型。
