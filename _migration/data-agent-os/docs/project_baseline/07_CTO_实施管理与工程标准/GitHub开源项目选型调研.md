# GitHub 开源项目选型调研

> 日期：2026-06-01  
> 角色：CTO / Architecture Agent  
> 适用范围：AI Native Business Data OS 项目开发、Agent 工作流、工程化治理  
> 结论级别：候选技术雷达，不是依赖锁定清单  

## 1. 调研结论

本项目不应把开源项目简单拼成“大杂烩”。最新 CTO 决策是：**Agent OS 和产品 Core 必须 100% 自研**。开源 Agent OS、Agent framework、coding agent、skills 项目只能作为参考、对标、调研和测试样本。

最优策略是：

```text
OS Core / Agent OS Core 100% 自研
  + 开源项目只参考架构思想
  + 工程辅助工具可审慎使用
  + 第三方能力必须通过可替换 Adapter
  + 强制 Eval / Trace / Policy Gate
  + 内部 Agent Skills 标准化
```

第一阶段只建议引入少量确定性强、ROI 高、低耦合的项目：

| 优先级 | 建议 |
|---|---|
| P0 直接采用 | `uv`、`ruff`、`pyright`、`sqlglot`、`promptfoo`、GitHub Actions 等工程工具 |
| P1 小范围试点 | `instructor`、`phoenix` 或 `langfuse`、MCP Python SDK、Great Expectations 等非 Agent OS 底座能力 |
| P2 阶段引入 | Cube Core、MetricFlow/dbt、OpenLineage、Temporal、Prefect/Dagster、OPA/Cerbos |
| 只参考，不进入产品 Core | OpenAI Agents SDK、LangGraph、CrewAI、AutoGen、OpenHands、Goose、Cline、Aider、Anthropic skills、BMAD、SuperClaude |
| 暂不进入核心依赖 | n8n、OpenMetadata/DataHub、Marketplace 类生态平台 |

关键判断：

1. Agent Runtime、ToolRegistry、SkillRegistry、Agent Memory、Agent Eval、Agent Governance 必须自研，不能让 LangGraph、CrewAI、AutoGen、OpenAI Agents SDK 或某一家 SDK 支配 OS Core。
2. SQL Safety 第一阶段优先采用 `sqlglot`，因为它能解析 AST、识别表列、改写和跨方言处理。
3. Eval 第一阶段优先落 CI：`promptfoo` 做 prompt/agent/red-team 回归，项目内 `eval_hub` 记录业务 golden case。
4. Semantic Layer 不建议第一阶段直接引入 Cube 或 MetricFlow；先实现项目自己的 `MetricContract`，第二阶段再评估接入。
5. Skills 可以借鉴 Anthropic / Langfuse 的 SKILL.md 组织方式，但内部技能必须自建、审计、版本化，不能直接安装未知社区 skills。

## 2. 推荐技术雷达

### 2.1 Agent Runtime / Agent SDK

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | Agent runner、tools、handoff、guardrails、tracing adapter | 参考：研究 API、trace、handoff、guardrail 思路，不作为产品 runtime |
| PydanticAI | https://github.com/pydantic/pydantic-ai | 类型安全 Agent、依赖注入、结构化输出 | 参考/试验：只借鉴类型安全模式，不作为 Agent OS 底座 |
| Instructor | https://github.com/567-labs/instructor | LLM structured output、validation、retry | P1：用于 Intent/Contract extraction 的轻量能力 |
| LangGraph | https://github.com/langchain-ai/langgraph | 长流程、状态机、human-in-the-loop、多 Agent 图 | 参考：研究状态机和 human-in-the-loop，不进入 Core |
| CrewAI | https://github.com/crewAIInc/crewAI | role-based multi-agent orchestration | 参考：适合看角色协作模式，不建议进 Core |
| Microsoft AutoGen | https://github.com/microsoft/autogen | multi-agent framework | 参考：许可和复杂度需复核，不建议作为主依赖 |

CTO 决策：

- 第一阶段以自研 `AgentRuntime`、`ToolRegistry`、`AgentRunContext`、`StructuredOutputValidator`、`AgentTraceWriter` 为主。
- OpenAI Agents SDK、PydanticAI、LangGraph、CrewAI、AutoGen 只做参考和 spike，不进入产品 Core 依赖。
- 可以通过 `ModelProviderAdapter` 调用 OpenAI-compatible API，但模型 API 客户端不等于 Agent OS runtime。

### 2.2 Code Agent / AI IDE / 开发辅助

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| Aider | https://github.com/aider-ai/aider | terminal AI pair programming，Git-first | 工程师个人备用工具，不进自动流水线 |
| OpenHands | https://github.com/OpenHands/OpenHands | AI software development agent platform | 参考 sandbox 和评测思路，不进核心链路 |
| Cline | https://github.com/cline/cline | VS Code / CLI autonomous coding agent | 人工 IDE 辅助，需权限白名单 |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | terminal coding agent | 备用，不作为标准工作流 |
| Continue | https://github.com/continuedev/continue | open-source IDE code assistant | 可作为 BYOK IDE 辅助，不作为交付标准 |
| OpenCode | https://github.com/opencode-ai/opencode | terminal coding agent | 可参考 skills/agent 配置，不作为主工具 |

CTO 决策：

- 项目标准 Code Agent 仍以当前 Codex 工作流为主。
- 其他工具可用于个人效率，但任何代码进入主线必须经过同一套 PR、CI、Eval、Review。
- 禁止让 IDE Agent 直接推送或合并主分支。

### 2.3 Workflow / Orchestration

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| Temporal | https://github.com/temporalio/temporal | durable execution、补偿、长流程 | P2：Stage 3 业务动作闭环再引入 |
| Prefect | https://github.com/PrefectHQ/prefect | Python workflow、数据任务 | P2：数据产品编译和批任务候选 |
| Dagster | https://github.com/dagster-io/dagster | data asset orchestration | P2：DataProduct / data asset 管理参考 |
| n8n | https://github.com/n8n-io/n8n | 低代码自动化、连接器原型 | 只做内部 PoC；生产需强隔离和安全评审 |
| Airflow | https://github.com/apache/airflow | 调度和 DAG | 可接客户已有系统，不建议第一阶段自建 |

CTO 决策：

- Stage 1 不引入重型 workflow engine。
- Stage 3 出现审批、补偿、回滚、长时间观察窗口后，再评估 Temporal。
- n8n 的连接器和可视化很有用，但安全面大，不能直接承载生产核心动作。

### 2.4 Semantic Layer / Metrics / BI as Code

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| Cube Core | https://github.com/cube-js/cube | headless semantic layer for AI/BI | P2：Stage 2+ 评估接入 MetricContract |
| MetricFlow | https://github.com/dbt-labs/metricflow | metrics as code、semantic layer | P2：参考 query plan 和指标 DSL，许可需复核 |
| dbt Core | https://github.com/dbt-labs/dbt-core | analytics engineering、transformation | 接客户已有 dbt，不作为 OS 内核 |
| Lightdash | https://github.com/lightdash/lightdash | dbt-native BI / semantic layer | 参考 UI 和 self-service BI，不进入 Core |
| Evidence | https://github.com/evidence-dev/evidence | SQL + Markdown BI as code | 参考报告生成，不作为主 UI |

CTO 决策：

- 第一阶段先实现自有 `MetricContract` 和 verified SQL。
- 第二阶段如果需要对外暴露 semantic API，再评估 Cube Core。
- 不要把 BI 产品本身当作 OS Core。

### 2.5 SQL Safety / Query Runtime

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| SQLGlot | https://github.com/tobymao/sqlglot | SQL parser、AST、transpiler、optimizer | P0：SQL Safety 核心依赖 |
| SQLFluff | https://github.com/sqlfluff/sqlfluff | SQL lint / format | P1：开发期 SQL 规范检查 |
| SQLAlchemy | https://github.com/sqlalchemy/sqlalchemy | DB access abstraction | P0/P1：Provider 实现可用 |

SQL Safety 第一阶段必须基于 AST，不得只靠正则。

建议规则：

- 只允许 `SELECT` / read-only CTE。
- 拦截 DDL、DML、函数副作用、跨库访问。
- 强制 schema allowlist。
- 强制参数绑定。
- 强制 limit / cost estimation。
- 记录 query fingerprint 和 trace_id。

### 2.6 Data Quality / Lineage / Metadata

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| Great Expectations | https://github.com/great-expectations/great_expectations | data quality expectations | P1/P2：质量契约参考或局部接入 |
| OpenLineage | https://github.com/OpenLineage/OpenLineage | lineage standard | P2：EvidenceChain lineage model 参考 |
| OpenMetadata | https://github.com/open-metadata/OpenMetadata | metadata、catalog、governance | P3：企业试点后评估，不进 MVP |
| DataHub | https://github.com/datahub-project/datahub | metadata platform | P3：大型企业 metadata 集成候选 |

CTO 决策：

- Stage 1 不上完整 metadata platform。
- EvidenceChain 先记录轻量 lineage snapshot。
- 企业客户已有 OpenMetadata/DataHub 时，做 Provider/Bridge，而不是替换。

### 2.7 LLM Eval / Observability / Prompt Management

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| Promptfoo | https://github.com/promptfoo/promptfoo | prompt、agent、RAG eval、red-team、CI | P0：第一阶段 CI eval 候选 |
| Phoenix | https://github.com/Arize-ai/phoenix | OpenTelemetry-based AI observability/evals | P1：本地和早期 trace/eval 可选 |
| Langfuse | https://github.com/langfuse/langfuse | LLM tracing、prompt management、datasets、evals | P1：团队协作和 prompt 管理候选 |
| DeepEval | https://github.com/confident-ai/deepeval | pytest-style LLM eval | P1：业务 eval 单测候选 |
| OpenAI Evals | https://github.com/openai/evals | eval examples/framework | 参考，不作为唯一 eval runtime |

CTO 决策：

- Stage 1 先做项目内 `eval_hub` + `promptfoo` CI。
- Phoenix / Langfuse 二选一试点，避免同时维护两套观测平台。
- eval 结果必须回写项目自己的 EvalResult，不把数据锁死在第三方平台。

### 2.8 MCP / Tool Registry / Skills

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | MCP server/client SDK | P1/P2：工具网关和生态接入候选 |
| MCP Servers | https://github.com/modelcontextprotocol/servers | reference MCP servers | 参考实现，不直接开放生产 |
| MCP Registry | https://github.com/modelcontextprotocol/registry | MCP server registry | P2/P3：生态阶段参考 |
| Anthropic skills | https://github.com/anthropics/skills | Agent Skills reference | 参考；source-available，不当作开源依赖 |
| Langfuse skills | https://github.com/langfuse/skills | Langfuse Agent Skill | 参考 skill packaging 和 eval setup |

内部 Skills 建议：

```text
skills/
  architecture-review/
  contract-first-development/
  sql-safety-review/
  evidencechain-review/
  eval-regression/
  security-risk-review/
  release-checklist/
  github-pr-review/
  product-prd-breakdown/
  project-backlog-planning/
```

Skill 标准：

- 每个 Skill 必须有 `SKILL.md`。
- 必须声明适用场景、输入、输出、禁止行为、验证步骤。
- 涉及命令执行的 Skill 必须声明安全边界。
- 外部 Skills 只能进入 sandbox 试验，不能直接放进项目主工作流。

### 2.9 Policy / Security / Secrets

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| OPA | https://github.com/open-policy-agent/opa | policy-as-code | P2：Action Governance / deployment policy 候选 |
| Cerbos | https://github.com/cerbos/cerbos | authorization layer | P2：应用层授权候选 |
| Casbin | https://github.com/casbin/casbin | RBAC/ABAC library | P1/P2：轻量权限候选 |
| TruffleHog | https://github.com/trufflesecurity/trufflehog | secret scanning | P0/P1：CI secret scanning 候选 |

CTO 决策：

- Stage 1 可先用轻量 policy rules + tests。
- Stage 3 进入业务动作后，再评估 OPA/Cerbos。
- Secret scanning 应尽早进 CI。

### 2.10 Engineering Quality

| 项目 | GitHub | 用途 | 建议 |
|---|---|---|---|
| uv | https://github.com/astral-sh/uv | Python package/project manager | P0 |
| Ruff | https://github.com/astral-sh/ruff | Python lint/format | P0 |
| Pyright | https://github.com/microsoft/pyright | Python static type check | P0/P1 |
| Biome | https://github.com/biomejs/biome | JS/TS lint/format | P0 for frontend |
| pre-commit | https://github.com/pre-commit/pre-commit | local quality hooks | P0/P1 |

CTO 决策：

- Python 默认 `uv + ruff + pyright + pytest`。
- Frontend 默认 `typescript + biome/eslint + playwright smoke`。
- 所有 Agent 生成代码必须通过同一套格式化、类型检查、测试和 eval。

## 3. 推荐组合

### 3.1 Stage 1 最小技术组合

```text
Agent:
  self-developed AgentRuntime
  self-developed ToolRegistry
  self-developed AgentRunContext
  ModelProviderAdapter for OpenAI-compatible APIs

Contracts:
  Pydantic v2 / JSON Schema

SQL Safety:
  SQLGlot

Eval:
  promptfoo + project eval_hub

Quality:
  uv + ruff + pyright + pytest
  Biome / TypeScript checks for frontend

Trace:
  project trace table first
  optional Phoenix or Langfuse spike

Skill:
  internal SKILL.md library only
```

### 3.2 Stage 2 候选组合

```text
Data Product:
  MetricContract -> DataRequirement -> DataProduct
  Evaluate Cube Core / MetricFlow integration

Data Quality:
  Great Expectations ideas or adapter

Lineage:
  OpenLineage-compatible snapshots

Workflow:
  Prefect or Dagster for data tasks if simple internal scheduler is insufficient
```

### 3.3 Stage 3+ 候选组合

```text
Business Action:
  Temporal for durable workflow
  OPA or Cerbos for policy
  ActionConnectorContract for external writes

Observability:
  Phoenix or Langfuse as managed/self-hosted observability

MCP:
  MCP Gateway only through Tool Registry + PolicyEngine
```

## 4. 许可和安全红线

1. 引入依赖前必须确认 license、商业使用限制、copyleft 风险和企业部署限制。
2. `source-available` 不等于 open source，不能默认进入商业产品依赖。
3. n8n、MCP server、coding agent、skills 都有较大执行权限风险，必须隔离运行。
4. 外部 skills 不得直接执行生产命令、访问凭据、修改仓库或调用业务系统。
5. 所有 Provider / Action Connector 都必须通过项目自定义 Contract，不直接暴露第三方工具 API 给 Agent。
6. 所有高风险动作必须保留人工审批和 OperationTrace。

## 5. 下一步建议

建议新增一个轻量开源雷达文件：

```text
docs/vendor_radar/open_source_radar.yaml
```

字段：

```yaml
name:
repo:
category:
stage:
decision: adopt | trial | reference | hold
license:
owner_agent:
risk:
adapter_required:
eval_required:
notes:
```

该文件由 CTO / Architecture Agent 维护。每次新增依赖、Agent Skill 或开发工具前，先登记再审批。
