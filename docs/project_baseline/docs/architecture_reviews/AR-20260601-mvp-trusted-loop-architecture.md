# Architecture Design Brief: MVP Trusted Loop Architecture

> Review ID: AR-20260601-mvp-trusted-loop-architecture  
> Date: 2026-06-01  
> Prepared by: Architecture Agent  
> Review owner: CTO  
> Status: Proposed for CTO review  

## 1. 需求摘要

本次架构设计目标是为 AI Native Business Data OS 第一阶段实现提供完整工程架构。第一阶段不实现完整 OS，而是实现可验证的可信闭环：

```text
Business Question
  -> BusinessIntent
  -> MetricContract
  -> SQLTemplate / QueryPlan
  -> SQL Safety
  -> QueryResult
  -> EvidenceChain
  -> Answer
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
  -> Eval regression
```

首发业务域为内容电商经营分析，优先覆盖：

1. 投放效率诊断。
2. 爆款内容挖掘。
3. 日报全景扫描。

工程目标不是“Agent 很聪明”，而是让每个正式答案可复现、可解释、可审计、可评测，并且让行动建议先以提案和审批形式落地。

## 2. 架构结论

推荐：**Approve with conditions**。

建议按 repo scaffold 进入第一阶段实现，但必须满足以下条件：

1. Product Manager Agent 先产出 MVP PRD、feature map、acceptance criteria。
2. Project Manager Agent 先产出 backlog、roadmap、sprint plan、risk register。
3. Contract Agent 先冻结 P0 Contract，再允许 Backend/Data/AI/UI Agent 并行。
4. SQL Safety、EvidenceChain completeness、Eval Harness 必须在第一批实现中进入 CI。
5. R4/R5 业务动作第一阶段只能生成 ActionProposal，不允许自动执行。
6. Domain Pack 仅表达内容电商配置、指标、问题、golden cases，不允许反向污染 OS Core。
7. 定位修正后，MVP 必须包含 AI-ready data foundation 到 Agent-ready Business Operation 的最小闭环：SemanticObject lite、MetricContract、ProviderContract lite、DataRequirement/DataProduct candidate、lineage/metadata snapshot lite、ActionProposal、Approval lite、Feedback/Trace、KnowledgeAsset candidate；但不实现完整 Data Fabric、NoETL、Active Metadata Platform、完整 Business Agent Runtime 或高风险自动执行。

## 3. 模块归属

| 模块 | 归属 | 是否 Core | 说明 |
|---|---|---:|---|
| `ai-native-business-data-agent-os/packages/contracts/src/agent_os_contracts/` | Core | 是 | 所有公共契约，Pydantic/JSON schema |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/intent_runtime/` | Core | 是 | 业务问题解析为 BusinessIntent |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/semantic_runtime/` | Core | 是 | SemanticObject lite、MetricContract 解析、口径绑定、冲突提示 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/data_product_compiler/` | Core | 是 | DataRequirement、DataProduct candidate、metadata/lineage snapshot lite |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/query_runtime/` | Core | 是 | SQLTemplate、QueryPlan、QueryRun、QueryResult |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/sql_safety/` | Core | 是 | 只读、白名单、参数绑定、limit、审计 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/evidence_chain/` | Core | 是 | EvidenceChain 构建和完整性校验 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/action_proposal/` | Core | 是 | ActionProposal、风险等级、审批建议 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/approval_lite/` | Core | 是 | MVP 轻审批记录，不做复杂 BPM |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/feedback/` | Core | 是 | 反馈事件、采纳/拒绝/结果记录 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/knowledge_asset_lite/` | Core | 是 | KnowledgeAsset candidate、review state、eval 绑定 |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/trace/` | Core | 是 | TraceEvent 和端到端 run correlation |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/eval_hub/` | Core | 是 | eval case、eval run、eval result |
| `ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/model_gateway/` | Core | 是 | 模型路由、调用日志、成本和数据分类 |
| `domain_packs/content_commerce/` | Domain Pack | 否 | 业务问题、指标模板、golden SQL/loops |
| `providers/postgres_provider/` | Provider | 否 | 数据库 Provider 实现 |
| `providers/file_provider/` | Provider | 否 | 文件/样本数据 Provider，便于本地 smoke |
| `action_connectors/notification_connector/` | Action | 否 | 通知/任务提案，不做高风险写操作 |
| `apps/api_server/` | App | 否 | FastAPI 应用 |
| `apps/web_workspace/` | UI | 否 | Intent Workspace、Evidence Viewer、Proposal Panel |
| `tests/` | Quality | 否 | unit/integration/eval/smoke |
| `scripts/agent_runner/` | DevOps | 否 | AI 自动编码工作流执行器 |

## 4. 现状依据

已阅读和使用的依据：

- `.agent`
- `repo_scaffold/README.md`
- `07_CTO_实施管理与工程标准/架构师Agent角色与CTO审批流程.md`
- `06_方案评估与落地边界/AI_Native_Business_Data_OS_MVP技术选型与工程工作流.md`
- `06_方案评估与落地边界/AI_Native_Business_Data_OS_阶段性落地方案.md`
- `05_业务问题与评测样本/黄金业务闭环样本.md`
- `05_业务问题与评测样本/黄金查询样本.md`

关键约束：

- 第一版只证明可信闭环。
- 可信闭环必须内置 AI-ready data foundation 的最小对象，不允许只做问答或行动提案包装层。
- EvidenceChain 优先级高于复杂 Agent 和复杂 UI。
- SQL Safety 必须 100% 拦截写操作和非白名单 schema。
- 每个行动提案必须有证据引用、风险等级和审批建议。
- 失败样本必须进入 eval 回归集。

## 5. 推荐总体架构

### 5.1 逻辑层

```text
Web Workspace
  -> API Server
  -> Intent Runtime
  -> Semantic Runtime
  -> DataProduct candidate / metadata snapshot
  -> Query Runtime
  -> SQL Safety
  -> Provider
  -> QueryResult
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
  -> Eval Hub
```

支撑平面：

```text
Model Gateway
Domain Pack
Trace Store
Eval Store
Contract Registry
```

### 5.2 请求运行链路

```text
1. 用户输入业务问题
2. Intent Runtime 生成 BusinessIntent
3. Semantic Runtime 命中 SemanticObject lite / MetricContract / SQLTemplate
4. DataProduct candidate 记录 DataRequirement、ProviderContract、metadata/lineage snapshot
5. Query Runtime 生成 QueryPlan
6. SQL Safety 校验 QueryPlan
7. Provider 执行只读查询
8. Query Runtime 生成 QueryResult
9. EvidenceChain Builder 汇总证据、口径、SQL、质量、限制
10. Answer Builder 输出业务回答
11. ActionProposal Builder 生成行动提案和审批建议
12. Approval lite 记录人工确认/拒绝/修改
13. Feedback Runtime 记录采纳结果和业务反馈
14. Trace Runtime 串联全过程
15. Eval Hub 将失败样本沉淀为 regression case
```

### 5.3 数据存储

MVP 使用 PostgreSQL + JSONB，pgvector 作为可选增强。

建议 schema：

```text
core.business_intents
core.metric_contracts
core.sql_templates
core.query_runs
core.evidence_chains
core.action_proposals
core.approvals
core.feedback_events
core.trace_events
eval.eval_cases
eval.eval_runs
eval.eval_results
model.model_invocations
```

所有核心表必须包含：

```text
tenant_id
workspace_id
created_by
created_at
updated_at
trace_id
```

MVP 可以只有单租户，但字段必须存在，避免后续大迁移。

## 6. 核心 Contract

### 6.1 BusinessIntent

最小字段：

```text
intent_id
tenant_id
workspace_id
raw_question
goal
target_metrics
time_window
dimensions
constraints
expected_outputs
created_by
trace_id
```

职责：

- 保留原始问题。
- 记录解析后的目标、指标、时间范围和约束。
- 为后续 evidence 和 trace 提供主线 ID。

### 6.2 MetricContract

最小字段：

```text
metric_id
name
aliases
formula
grain
unit
owner
source_requirements
quality_contract
verified_queries
version
status
```

职责：

- 稳定指标口径。
- 绑定 SQLTemplate 或 verified query。
- 提供 owner 和质量规则。

### 6.3 SQLTemplate / QueryPlan

SQLTemplate 字段：

```text
template_id
metric_ids
sql_template
allowed_schemas
required_params
default_limits
owner
version
```

QueryPlan 字段：

```text
query_plan_id
intent_id
template_id
params
estimated_cost
safety_status
provider_id
trace_id
```

职责：

- SQLTemplate 只允许参数化模板。
- QueryPlan 是运行前计划，不直接拼接字符串。

### 6.4 SQLSafetyResult

字段：

```text
safety_result_id
query_plan_id
allow
blocked_reasons
checked_rules
allowed_schemas
max_rows
requires_masking
trace_id
```

必须覆盖：

- 只允许 SELECT。
- 禁止写操作和 DDL。
- 白名单 schema。
- 参数绑定。
- 时间范围或 limit。
- 敏感字段检查。

### 6.5 QueryResult

字段：

```text
query_run_id
query_plan_id
row_count
result_summary
result_sample
quality_results
executed_sql_hash
executed_at
trace_id
```

MVP 不需要保存完整大结果集，优先保存摘要、样本、hash、质量结果和审计信息。

### 6.6 EvidenceChain

字段：

```text
evidence_chain_id
intent_id
metric_contract_refs
query_plan_refs
query_result_refs
quality_results
claims
limitations
confidence
source_refs
action_proposal_refs
trace_id
```

正式答案必须由 EvidenceChain 派生，不允许只从 Agent 自然语言输出派生。

### 6.7 ActionProposal

字段：

```text
proposal_id
evidence_chain_id
target_object
recommended_action
reason
risk_level
expected_impact
approval_required
approver_role
dry_run_available
rollback_hint
feedback_metrics
feedback_window
trace_id
```

MVP 中 R4/R5 只能提案，不执行。

### 6.8 ApprovalRecord / FeedbackEvent / KnowledgeAssetCandidate / TraceEvent

ApprovalRecord：

```text
approval_id
proposal_id
decision
approver
reason
created_at
trace_id
```

FeedbackEvent：

```text
feedback_id
intent_id
proposal_id
user_rating
adoption_status
outcome_notes
created_at
trace_id
```

TraceEvent：

```text
trace_event_id
trace_id
event_type
payload
actor
created_at
```

## 7. API 架构

MVP API 以 FastAPI + Pydantic 实现。

### 7.1 Intent API

```text
POST /v1/intents
GET  /v1/intents/{intent_id}
GET  /v1/intents/{intent_id}/trace
```

### 7.2 Query API

```text
POST /v1/query-plans
POST /v1/query-plans/{query_plan_id}/safety-check
POST /v1/query-plans/{query_plan_id}/run
GET  /v1/query-runs/{query_run_id}
```

### 7.3 Evidence API

```text
POST /v1/evidence-chains
GET  /v1/evidence-chains/{evidence_chain_id}
GET  /v1/evidence-chains/{evidence_chain_id}/render
```

### 7.4 Action Proposal API

```text
POST /v1/action-proposals
GET  /v1/action-proposals/{proposal_id}
POST /v1/action-proposals/{proposal_id}/approval
POST /v1/action-proposals/{proposal_id}/feedback
```

### 7.5 Eval API

```text
POST /v1/evals/runs
GET  /v1/evals/runs/{eval_run_id}
GET  /v1/evals/results
```

API 约束：

- 所有写入 API 必须带 `tenant_id/workspace_id/created_by/trace_id` 上下文。
- 生产查询执行不得绕过 QueryPlan 和 SQL Safety。
- API 不直接暴露明文模型 key、数据库凭证或完整敏感 payload。

## 8. UI 架构

MVP UI 使用 React / Next.js + TypeScript。

### 8.1 核心页面

| 页面 | 目标 |
|---|---|
| Intent Workspace | 输入业务问题、查看解析意图和运行状态 |
| EvidenceChain Viewer | 查看指标口径、SQL、安全检查、数据来源、质量检查、限制 |
| ActionProposal Panel | 查看建议动作、理由、风险、审批建议、反馈入口 |
| Eval Dashboard lite | 查看 golden query/eval 运行结果和失败样本 |
| Trace Viewer lite | 根据 trace id 回放关键步骤 |

### 8.2 UI 红线

- 不隐藏 evidence limitations。
- 不把 draft 输出渲染为正式结论。
- 高风险提案必须清晰标注审批需求。
- 失败状态必须显示可复现 trace id。

## 9. Eval 和测试架构

### 9.1 测试分层

```text
unit tests
schema tests
sql safety tests
golden query tests
intent / metric eval
evidence completeness tests
action risk tests
frontend smoke tests
```

### 9.2 Eval Pack

首发 `content_commerce` eval pack：

```text
domain_packs/content_commerce/eval_pack/
  golden_questions.jsonl
  golden_queries.jsonl
  golden_business_loops.jsonl
  metric_alias_cases.jsonl
  sql_safety_negative_cases.jsonl
  evidence_completeness_cases.jsonl
  action_risk_cases.jsonl
```

### 9.3 通过标准

MVP 阶段：

- SQL Safety 写操作拦截率 100%。
- 非白名单 schema 拦截率 100%。
- EvidenceChain 正式输出完整率 100%。
- golden query 正确率阶段目标 >= 85%。
- 核心指标口径命中率阶段目标 >= 90%。
- 每个 bug fix 尽量新增 regression case。

## 10. 安全与风险

整体风险等级：R2-R3。

原因：

- MVP 主要做只读查询、证据链和行动提案。
- 不做高风险业务写操作自动执行。
- 模型调用、数据查询、证据链存储仍需审计。

### 10.1 安全边界

- 生产查询只读。
- 数据库凭证隔离。
- 模型 key 只能经 Model Gateway 引用，不落业务代码。
- 日志不得输出密钥、token、cookie、完整敏感 payload。
- EvidenceChain 按数据权限渲染。
- ActionProposal 不直接触发 R4/R5 操作。

### 10.2 PolicyEngine 策略

MVP 使用 Python/config 轻实现，不引入 OPA 全量复杂度。

输出：

```text
allow
deny
require_approval
require_masking
require_human_review
```

## 11. 可观测性和 Trace

端到端 trace 必须串起：

```text
intent
  -> metric
  -> query_plan
  -> sql_safety
  -> query_run
  -> quality_check
  -> evidence_chain
  -> answer
  -> action_proposal
  -> approval
  -> feedback
  -> eval_case
```

MVP 使用应用内 TraceEvent + OpenTelemetry-compatible TelemetryEvent，不提前强制部署完整 OpenTelemetry 平台，但字段和事件结构要为后续映射预留。

## 12. Agent Runtime 架构

第一阶段 Agent Runtime 必须 100% 自研。OpenAI Agents SDK、LangGraph、CrewAI、AutoGen、OpenHands、Goose 等开源或商业 Agent OS / Agent framework 只能作为设计参考和对标样本，不能成为产品运行时底座。

```text
ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/model_gateway/
ai-native-business-data-agent-os/packages/os_core/src/agent_os_core/agent_runtime/
  AgentRuntime
  AgentRunContext
  ToolRegistry
  StructuredOutputValidator
  AgentTraceWriter
```

约束：

- 业务代码只依赖项目自研 `AgentRuntime`、`ToolRegistry`、`AgentRunContext`、`StructuredOutputValidator`。
- 可通过 `ModelProviderAdapter` 调用 OpenAI-compatible API 或其他模型服务，但不得依赖外部 Agent SDK 执行工具编排、handoff、状态管理或权限判断。
- 外部 Agent framework 的代码、prompt、skill、orchestration pattern 可进入调研报告，不得复制进 Core 实现。
- Agent 输出必须通过 Pydantic/JSON schema 校验。
- 权限、SQL Safety、风险分级由代码执行，不由 prompt 决定。
- 模型升级必须跑 eval regression。

## 13. 部署和环境

MVP 环境：

```text
local/dev
staging
demo/internal pilot
```

建议：

- PostgreSQL + JSONB。
- pgvector 可选，不阻塞第一闭环。
- 本地开发使用 Docker Compose 或 devcontainer。
- CI 使用 GitHub Actions。
- 第一阶段不做 production 自动部署。

## 14. 任务拆分

建议 PR 顺序：

### PR-01 Contracts

范围：

- BusinessIntent。
- SemanticObject lite。
- MetricContract。
- ProviderContract lite。
- DataRequirement。
- DataProduct candidate。
- SQLTemplate。
- QueryPlan。
- QueryResult。
- EvidenceChain。
- ActionProposal。
- ApprovalRecord。
- FeedbackEvent。
- TraceEvent。
- EvalCase/EvalResult。

验收：

- schema tests。
- sample payloads。
- backward compatibility note。

### PR-02 SQL Safety

范围：

- SQL parser/validator。
- write/DDL block。
- schema allowlist。
- parameter binding check。
- limit/time-window enforcement。
- audit result。

验收：

- negative cases 100% block。
- golden SQL passes。

### PR-03 Query Runtime + Provider

范围：

- SQLTemplate registry。
- ProviderContract registry lite。
- DataRequirement and DataProduct candidate builder。
- metadata/lineage snapshot。
- QueryPlan builder。
- QueryRun executor。
- Postgres provider。
- File/mock provider for local smoke。

验收：

- golden query Q1-Q5 smoke。
- QueryResult summary and trace。

### PR-04 EvidenceChain

范围：

- EvidenceChain builder。
- completeness validator。
- evidence renderer payload。

验收：

- formal answer requires EvidenceChain。
- missing required field fails test。

### PR-05 ActionProposal + Approval lite

范围：

- proposal builder。
- risk level rules。
- approval record。
- feedback event。

验收：

- R4/R5 not executable。
- proposal references evidence_chain_id。

### PR-06 Eval Hub

范围：

- eval case registry。
- eval runner。
- eval result storage。
- content commerce eval pack seed。

验收：

- intent/metric/sql/evidence/action eval sample runs。

### PR-07 API Server

范围：

- FastAPI app。
- Intent/Query/Evidence/Proposal/Eval endpoints。
- tenant/workspace/trace context。

验收：

- API contract tests。
- integration smoke。

### PR-08 Web Workspace

范围：

- Intent Workspace。
- EvidenceChain Viewer。
- ActionProposal Panel。
- Eval Dashboard lite。

验收：

- frontend smoke。
- evidence limitations visible。

### PR-09 Agent Runtime Adapter

范围：

- AgentRuntime adapter。
- ToolRegistry。
- StructuredOutputValidator。
- ModelInvocation log。

验收：

- structured output validation。
- model invocation trace。
- no permission logic in prompt。

## 15. 不做事项

MVP 不做：

- 完整 DataProduct Compiler。
- 完整 Business Agent Runtime。
- 高风险业务写操作自动执行。
- Marketplace。
- 完整 Domain Pack SDK。
- 完整 MCP Gateway。
- 完整 OPA/Temporal/OpenLineage 集成。
- Air-gapped 私有化。
- 所有云厂商适配。
- 多业务域同时落地。

## 16. CTO 审批项

需要 CTO 审批：

1. 是否批准使用 repo scaffold 作为第一实现结构。
2. 是否批准第一阶段以 Contracts -> SQL Safety -> Query -> Evidence -> Action -> Eval -> API -> UI 顺序实现。
3. 是否批准 Agent Runtime 100% 自研，外部 Agent framework 仅作参考，不进入产品 Core 依赖。
4. 是否批准不做 R4/R5 自动执行。
5. 是否批准 Product Manager Agent 和 Project Manager Agent 先产出 PRD-MVP/backlog，再进入 PR-01。
6. 是否批准第一阶段不做完整平台组件，只留接口边界。

## 17. 结论

该架构满足当前项目的第一阶段目标：用最小但完整的工程路径证明可信数据产品、证据链、受治理行动、反馈追踪、知识资产候选和评测闭环。

推荐进入 CTO 审批，但必须先补齐产品和项目执行输入，再启动 Contract Agent。
